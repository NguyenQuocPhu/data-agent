"""
LangGraph Graph — Phase 1
Assembles the nodes into a stateful graph with conditional edges.

Graph flow:
  generate_code → execute_code → [error? repair_code → execute_code]
                               → semantic_verify → [REVISE? semantic_fix → execute_code]
                                                 → generate_report → END

Phase 1: No interrupt points yet — the whole graph runs end-to-end like the
         original stream_workflow(). Interrupt hooks are stubbed for Phase 2.
"""
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command


from .state import AgentState
from .nodes import (
    generate_plan,
    human_review,
    classify_review,
    code_critic,
    generate_code,
    execute_code,
    repair_code,
    semantic_verify,
    semantic_fix,
    generate_report,
)

if TYPE_CHECKING:
    from triadic_dgm.engine import TriadicAgent


# ── Conditional edge functions ──────────────────────────────────────────────

def _after_classify(state: AgentState) -> str:
    """Route after classifying human review feedback."""
    status = state.get("review_status", "REJECT")
    if status == "APPROVE":
        return "generate_code"
    # For REJECT or CLARIFICATION, we route back to the planner
    return "generate_plan"


def _after_critic(state: AgentState) -> str:
    """Route after code quality check."""
    if state.get("critic_verdict"):
        return "execute_code"
    return "generate_code"


def _after_execute(state: AgentState) -> str:
    """Route after execute_code: retry on error, verify semantics on success."""
    sign = state.get("exe_sign", "")
    attempts = state.get("syntax_attempts", 0)
    max_attempts = 4  # mirrors engine.py default

    if sign and "error" not in sign:
        return "semantic_verify"
    elif attempts >= max_attempts:
        # Give up repairing — go straight to report with best available result
        return "generate_report"
    else:
        return "repair_code"


def _after_verify(state: AgentState) -> str:
    """Route after semantic_verify: accept or ask for a fix."""
    verdict = state.get("verdict", {})
    attempts = state.get("semantic_attempts", 0)
    max_retries = 5  # mirrors engine.py MAX_SEMANTIC_RETRIES

    if verdict.get("status") == "ACCEPT" or attempts >= max_retries:
        return "generate_report"
    return "semantic_fix"


def _after_semantic_fix(state: AgentState) -> str:
    """After semantic_fix, always re-execute the patched code."""
    return "execute_code"


def _after_repair(state: AgentState) -> str:
    """After repair_code, always re-execute."""
    return "execute_code"


# ── Graph builder ────────────────────────────────────────────────────────────

def build_graph(agent: "TriadicAgent") -> StateGraph:
    """
    Build and compile the LangGraph StateGraph.

    Args:
        agent: A fully initialised TriadicAgent instance.
               The agent carries the Programmer, Verifier, and Kernel.

    Returns:
        A compiled LangGraph that can be invoked with an initial AgentState.
    """
    # Bind the agent instance into each node via partial so nodes stay pure functions
    _gen_plan      = partial(generate_plan,    agent=agent)
    _human         = partial(human_review,     agent=agent)
    _classify      = partial(classify_review,  agent=agent)
    _gen_code      = partial(generate_code,    agent=agent)
    _critic        = partial(code_critic,      agent=agent)
    _exec_code     = partial(execute_code,     agent=agent)
    _repair        = partial(repair_code,      agent=agent)
    _sem_verify    = partial(semantic_verify,  agent=agent)
    _sem_fix       = partial(semantic_fix,     agent=agent)
    _gen_report    = partial(generate_report,  agent=agent)

    graph = StateGraph(AgentState)

    # ── Register nodes ───────────────────────────────────────────
    graph.add_node("generate_plan",   _gen_plan)
    graph.add_node("human_review",    _human)
    graph.add_node("classify_review", _classify)
    graph.add_node("generate_code",   _gen_code)
    graph.add_node("code_critic",     _critic)
    graph.add_node("execute_code",    _exec_code)
    graph.add_node("repair_code",     _repair)
    graph.add_node("semantic_verify", _sem_verify)
    graph.add_node("semantic_fix",    _sem_fix)
    graph.add_node("generate_report", _gen_report)

    # ── Entry point ───────────────────────────────────────────────
    graph.set_entry_point("generate_plan")

    # ── Edges ─────────────────────────────────────────────────────
    graph.add_edge("generate_plan", "human_review")
    graph.add_edge("human_review", "classify_review")
    
    graph.add_conditional_edges(
        "classify_review",
        _after_classify,
        {
            "generate_code": "generate_code",
            "generate_plan": "generate_plan",
        }
    )
    
    graph.add_edge("generate_code", "code_critic")
    
    graph.add_conditional_edges(
        "code_critic",
        _after_critic,
        {
            "execute_code": "execute_code",
            "generate_code": "generate_code",
        }
    )

    graph.add_conditional_edges(
        "execute_code",
        _after_execute,
        {
            "repair_code":     "repair_code",
            "semantic_verify": "semantic_verify",
            "generate_report": "generate_report",
        },
    )

    graph.add_edge("repair_code", "execute_code")

    graph.add_conditional_edges(
        "semantic_verify",
        _after_verify,
        {
            "generate_report": "generate_report",
            "semantic_fix":    "semantic_fix",
        },
    )

    graph.add_edge("semantic_fix", "execute_code")
    graph.add_edge("generate_report", END)

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


# ── Convenience wrapper ──────────────────────────────────────────────────────

class DataAgentGraph:
    """
    Thin wrapper around the compiled LangGraph.

    Usage (drop-in replacement for engine.stream_workflow):
        graph = DataAgentGraph(agent)
        for state in graph.stream(user_message, chat_history):
            yield state["chat_history_display"]
    """

    def __init__(self, agent: "TriadicAgent"):
        self.agent = agent
        self.compiled = build_graph(agent)

    def stream(self, user_message: str, chat_history_display: list, session_id: str = "default") -> object:
        """
        Stream node-by-node updates. Handles pausing and resuming via Checkpointer.
        """
        config = {"configurable": {"thread_id": session_id}}
        state_snapshot = self.compiled.get_state(config)
        is_paused = len(state_snapshot.next) > 0

        self.agent.programmer.messages.append({
            "role": "user",
            "content": user_message,
        })

        # Ensure there is an assistant placeholder in display
        if not chat_history_display or chat_history_display[-1].get("role") != "assistant":
            chat_history_display.append({"role": "assistant", "content": ""})
        
        # Only clear content if it's a new generation, keep it if resuming?
        # Actually it's better to append to the existing message if resuming,
        # but the UI expects a new SSE stream. Let's start fresh for the stream step.
        chat_history_display[-1]["content"] = ""

        if is_paused:
            # Resuming graph from interrupt
            # Pass the NEW chat_history_display into the state so nodes append to it
            stream_gen = self.compiled.stream(
                Command(resume=user_message, update={"chat_history_display": chat_history_display}), 
                config=config
            )
        else:
            initial_state: AgentState = {
                "messages":               self.agent.programmer.messages,
                "user_task":              user_message,
                "chat_history_display":   chat_history_display,
                "analysis_plan":          "",
                "review_status":          "",
                "review_feedback":        "",
                "review_history":         [],
                "critic_verdict":         True,
                "generated_code":         "",
                "exe_result":             "",
                "exe_sign":               "",
                "syntax_attempts":        0,
                "semantic_attempts":      0,
                "verdict":                {},
                "inspector_hypotheses":   "",
                "awaiting_human_approval": False,
                "human_decision":         "",
                "human_edited_code":      None,
                "final_report":           "",
                "error_message":          "",
            }
            stream_gen = self.compiled.stream(initial_state, config=config)

        for step_output in stream_gen:
            if "__interrupt__" in step_output:
                # Graph hit the interrupt
                interrupt_data = step_output["__interrupt__"][0].value
                if interrupt_data.get("type") == "plan_review":
                    chat_history_display[-1]["content"] += "\n\n**Human Review Required:**\n*Please review the Analysis Plan above. Reply with 'Approve', or specify any changes.*"
                    yield chat_history_display
                continue

            for node_name, partial_state in step_output.items():
                updated_history = partial_state.get("chat_history_display")
                if updated_history:
                    yield updated_history

    def invoke(self, user_message: str, chat_history_display: list, session_id: str = "default") -> AgentState:
        """Non-streaming version — returns final state."""
        for _ in self.stream(user_message, chat_history_display, session_id):
            pass
        return self.compiled.get_state({"configurable": {"thread_id": session_id}})
