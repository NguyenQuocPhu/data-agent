"""
LangGraph Nodes — Phase 1
Each node wraps a discrete step from the original engine.py stream_workflow().
These are pure functions: (state) -> partial state update (dict).

Phase 1 approach: Each node calls the existing TriadicAgent methods directly.
Phase 2: Nodes will be broken apart further and interrupt points added.
"""
from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from utils.utils import extract_code
from triadic_dgm.prompts.prompts import (
    HUMAN_LOOP,
    RESULT_PROMPT,
    SEMANTIC_FIX,
    PLANNER_PROMPT,
    CLASSIFIER_PROMPT,
    CRITIC_PROMPT,
)
from ui.display import display_exe_results, display_suggestions
from langgraph.types import interrupt

if TYPE_CHECKING:
    from triadic_dgm.engine import TriadicAgent

# ─────────────────────────────────────────────────────────────────────────────
# Node: generate_plan (Phase 2 HITL)
# Generates an Analysis Plan based on the user's task.
# ─────────────────────────────────────────────────────────────────────────────
def generate_plan(state: dict, agent: "TriadicAgent") -> dict:
    """Ask the Programmer LLM to create an Analysis Plan."""
    user_task = state.get("user_task", "")
    review_feedback = state.get("review_feedback", "")
    chat_history = state.get("chat_history_display", [])
    
    prompt = PLANNER_PROMPT + f"\n\nUser Task: {user_task}"
    if review_feedback:
        prompt += f"\n\nHuman Review Feedback: {review_feedback}\nPlease revise your plan to accommodate this feedback."

    agent.programmer.messages.append({"role": "user", "content": prompt})

    plan_response = ""
    for message in agent.programmer._call_chat_model_streaming():
        plan_response += message
        if chat_history:
            chat_history[-1]["content"] += message

    agent.programmer.messages.append({"role": "assistant", "content": plan_response})
    
    return {
        "analysis_plan": plan_response,
        "messages": agent.programmer.messages,
        "chat_history_display": chat_history,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Node: human_review (Phase 2 HITL)
# Pauses graph execution to wait for user approval of the plan.
# ─────────────────────────────────────────────────────────────────────────────
def human_review(state: dict, agent: "TriadicAgent") -> dict:
    """Interrupt execution and wait for Human-in-the-Loop review."""
    plan = state.get("analysis_plan", "")
    
    # Pause graph execution here using LangGraph's interrupt feature.
    # The API will resume this node by passing the user's chat message as 'decision'.
    decision = interrupt({
        "type": "plan_review",
        "plan": plan
    })
    
    return {
        "review_feedback": decision
    }

# ─────────────────────────────────────────────────────────────────────────────
# Node: classify_review (Phase 2 HITL)
# Classifies the human feedback using LLM to determine the next routing step.
# ─────────────────────────────────────────────────────────────────────────────
def classify_review(state: dict, agent: "TriadicAgent") -> dict:
    """Classify the human review feedback into APPROVE, REJECT, or CLARIFICATION."""
    feedback = state.get("review_feedback", "")
    history = state.get("review_history", [])
    
    prompt = CLASSIFIER_PROMPT.format(feedback=feedback)
    
    # We call the model synchronously here as it's a short classification
    # Using the agent.programmer as the LLM interface
    agent.programmer.messages.append({"role": "user", "content": prompt})
    response = ""
    for msg in agent.programmer._call_chat_model_streaming():
        response += msg
    agent.programmer.messages.append({"role": "assistant", "content": response})
    
    status = "REJECT"
    if "APPROVE" in response.upper():
        status = "APPROVE"
    elif "CLARIFICATION" in response.upper():
        status = "CLARIFICATION"
        
    history.append({
        "version": len(history) + 1,
        "feedback": feedback,
        "status": status
    })
    
    return {
        "review_status": status,
        "review_history": history,
        "messages": agent.programmer.messages
    }

# ─────────────────────────────────────────────────────────────────────────────
# Node: code_critic (Phase 2 HITL)
# Checks the generated code for syntax or basic errors before executing.
# ─────────────────────────────────────────────────────────────────────────────
def code_critic(state: dict, agent: "TriadicAgent") -> dict:
    """Quality gate for the generated Python code."""
    code = state.get("generated_code", "")
    chat_history = state.get("chat_history_display", [])
    
    prompt = CRITIC_PROMPT.format(code=code)
    agent.programmer.messages.append({"role": "user", "content": prompt})
    
    response = ""
    for msg in agent.programmer._call_chat_model_streaming():
        response += msg
    agent.programmer.messages.append({"role": "assistant", "content": response})
    
    verdict = True
    error_msg = ""
    if "FAIL" in response.upper():
        verdict = False
        error_msg = response.replace("FAIL", "").strip()
        
    if not verdict and chat_history:
        chat_history[-1]["content"] += f"\n\n⚠️ **Code Critic Failed:** {error_msg}\nRegenerating code...\n\n"
    elif verdict and chat_history:
        chat_history[-1]["content"] += "\n\n🖥️ Execute code...\n\n"
        
    return {
        "critic_verdict": verdict,
        "error_message": error_msg if not verdict else "",
        "messages": agent.programmer.messages,
        "chat_history_display": chat_history
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: generate_code
# Calls Programmer LLM to produce a Python code block.
# ─────────────────────────────────────────────────────────────────────────────
def generate_code(state: dict, agent: "TriadicAgent") -> dict:
    """Ask the Programmer LLM to write code based on the approved Analysis Plan."""
    human_edited = state.get("human_edited_code")
    plan = state.get("analysis_plan", "")
    critic_failed = state.get("critic_verdict") is False
    error_message = state.get("error_message", "")

    if human_edited:
        # Human provided / edited the code directly — skip LLM generation
        code = human_edited
        agent.programmer.messages.append({
            "role": "user",
            "content": HUMAN_LOOP.format(code=code),
        })
        return {
            "generated_code": code,
            "human_edited_code": None,  # consumed
            "chat_history_display": state.get("chat_history_display", []),
        }

    # Inject the plan or the critic error
    if critic_failed:
        agent.programmer.messages.append({
            "role": "user",
            "content": f"The Code Critic rejected your code. Reason: {error_message}\nPlease write a corrected Python script based on the original analysis plan."
        })
    else:
        agent.programmer.messages.append({
            "role": "user",
            "content": f"Please generate the complete Python code to implement this approved Analysis Plan:\n\n{plan}"
        })

    # Normal LLM generation
    prog_response = ""
    code_started = False
    chat_history = state["chat_history_display"]

    for message in agent.programmer._call_chat_model_streaming(
        retrieval=agent.retrieval, kernel=agent.kernel
    ):
        prev = prog_response
        prog_response += message

        if not code_started and "```python" in prog_response:
            code_started = True

        if code_started and prog_response.count("```") >= 2:
            idx = prog_response.find("```", prog_response.find("```python") + 9)
            if idx != -1:
                excess = len(prog_response) - (idx + 3)
                if excess > 0:
                    message = message[:-excess]
                prog_response = prog_response[: idx + 3]
                if chat_history:
                    chat_history[-1]["content"] += message
                break

        if chat_history:
            chat_history[-1]["content"] += message

    agent.programmer.messages.append({"role": "assistant", "content": prog_response})

    _, code = extract_code(prog_response)

    return {
        "generated_code": code or "",
        "messages": agent.programmer.messages,
        "chat_history_display": chat_history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: execute_code
# Runs generated_code in the Jupyter sandbox.
# ─────────────────────────────────────────────────────────────────────────────
def execute_code(state: dict, agent: "TriadicAgent") -> dict:
    """Execute the generated Python code in the sandbox kernel."""
    code = state.get("generated_code", "")
    chat_history = state.get("chat_history_display", [])
    
    if not code:
        return {"exe_sign": "error", "exe_result": "No code to execute.", "error_message": "Empty code block."}

    sign, msg_llm, exe_res = agent.run_code(code)
    
    if chat_history:
        if sign == 'error' or 'error' in str(sign).lower():
            chat_history[-1]["content"] += f'\n⭕ Execution error\n\n```text\n{exe_res}\n```\n'
        else:
            chat_history[-1]["content"] += f'\n**Execution Results:**\n\n```text\n{exe_res}\n```\n'
            
    return {
        "exe_sign": sign,
        "exe_result": msg_llm,
        "chat_history_display": chat_history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: repair_code
# When execution fails, calls SemanticVerifier to diagnose and Programmer to fix.
# ─────────────────────────────────────────────────────────────────────────────
def repair_code(state: dict, agent: "TriadicAgent") -> dict:
    """Inspect the error and ask Programmer to repair the code."""
    code = state.get("generated_code", "")
    error_msg = state.get("exe_result", "")
    attempts = state.get("syntax_attempts", 0)
    chat_history = state["chat_history_display"]

    # Diagnose
    if attempts < 3:
        user_task = state.get("user_task", "")
        hypotheses = agent.verifier.verify_syntax(code, error_msg, user_task)
    else:
        hypotheses = "Try other packages or methods."

    if chat_history:
        chat_history[-1]["content"] += (
            f"\n🕵️ **Inspector Hypotheses:**\n> "
            + hypotheses.replace("\n", "\n> ")
            + "\n\n"
        )

    agent.programmer.messages.append({
        "role": "user",
        "content": f"Fix this bug:\n{error_msg}\n\nSuggestion: {hypotheses}",
    })

    # Ask Programmer for repaired code
    prog_response = ""
    code_started = False
    for message in agent.programmer._call_chat_model_streaming():
        prog_response += message
        if not code_started and "```python" in prog_response:
            code_started = True
        if code_started and prog_response.count("```") >= 2:
            idx = prog_response.find("```", prog_response.find("```python") + 9)
            if idx != -1:
                prog_response = prog_response[: idx + 3]
                if chat_history:
                    chat_history[-1]["content"] += message
                break
        if chat_history:
            chat_history[-1]["content"] += message

    agent.programmer.messages.append({"role": "assistant", "content": prog_response})
    _, new_code = extract_code(prog_response)

    return {
        "generated_code": new_code or code,
        "syntax_attempts": attempts + 1,
        "inspector_hypotheses": hypotheses,
        "messages": agent.programmer.messages,
        "chat_history_display": chat_history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: semantic_verify
# Calls SemanticVerifier to check business rules on the execution result.
# ─────────────────────────────────────────────────────────────────────────────
def semantic_verify(state: dict, agent: "TriadicAgent") -> dict:
    """Run the Semantic Verifier (12 hard business gates) on execution output."""
    user_task = state.get("user_task", "")
    code = state.get("generated_code", "")
    exe_result = state.get("exe_result", "")

    if not agent.verifier.is_business_task(user_task):
        return {"verdict": {"status": "ACCEPT"}}

    verdict = agent.verifier.verify_semantics(user_task, code, exe_result)
    return {
        "verdict": verdict,
        "semantic_attempts": state.get("semantic_attempts", 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: semantic_fix
# When Verifier returns REVISE, inject feedback and re-generate code.
# ─────────────────────────────────────────────────────────────────────────────
def semantic_fix(state: dict, agent: "TriadicAgent") -> dict:
    """Apply Verifier feedback, re-generate and re-execute code."""
    verdict = state.get("verdict", {})
    feedback = verdict.get("feedback", "")
    attempts = state.get("semantic_attempts", 0)
    chat_history = state["chat_history_display"]

    fix_prompt = SEMANTIC_FIX.format(feedback=feedback)
    agent.programmer.messages.append({"role": "user", "content": fix_prompt})

    if chat_history:
        chat_history[-1]["content"] += (
            f"\n⚠️ **Verifier REVISE** (Attempt {attempts + 1}):\n   {feedback}\n"
        )

    # Re-generate
    prog_response = ""
    code_started = False
    for message in agent.programmer._call_chat_model_streaming():
        prog_response += message
        if not code_started and "```python" in prog_response:
            code_started = True
        if code_started and prog_response.count("```") >= 2:
            idx = prog_response.find("```", prog_response.find("```python") + 9)
            if idx != -1:
                prog_response = prog_response[: idx + 3]
                break

    agent.programmer.messages.append({"role": "assistant", "content": prog_response})
    _, new_code = extract_code(prog_response)

    return {
        "generated_code": new_code or state.get("generated_code", ""),
        "semantic_attempts": attempts + 1,
        "messages": agent.programmer.messages,
        "chat_history_display": chat_history,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node: generate_report
# Calls the Programmer one final time to produce the 5-Tab Markdown report.
# ─────────────────────────────────────────────────────────────────────────────
def generate_report(state: dict, agent: "TriadicAgent") -> dict:
    """Generate the final business report (5-Tab Markdown)."""
    exe_result = state.get("exe_result", "")
    chat_history = state["chat_history_display"]

    # Truncate very long results to avoid LLM gateway timeout
    if len(exe_result) > 4000:
        exe_result = exe_result[:2000] + "\n...[TRUNCATED]...\n" + exe_result[-2000:]

    final_prompt = (
        RESULT_PROMPT.format(exe_result)
        + "\n\nCRITICAL: DO NOT WRITE ANY PYTHON CODE! "
        "Output ONLY the 5-Tab Markdown report starting with '### 🚨 EXECUTIVE SUMMARY'!"
    )
    agent.programmer.messages.append({"role": "user", "content": final_prompt})

    if chat_history:
        chat_history[-1]["content"] += "\n\n**Final Report:**\n\n"

    report = ""
    for message in agent.programmer._call_chat_model_streaming():
        report += message
        if chat_history:
            chat_history[-1]["content"] += message

    agent.programmer.messages.append({"role": "assistant", "content": report})

    # Append suggestion buttons
    if chat_history:
        chat_history[-1]["content"] = display_suggestions(
            report, chat_history[-1]["content"]
        )

    return {
        "final_report": report,
        "messages": agent.programmer.messages,
        "chat_history_display": chat_history,
    }
