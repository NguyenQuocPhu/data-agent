from __future__ import annotations

import json
import uuid
import time
import asyncio
from fastapi import APIRouter, Body, HTTPException, Depends
from fastapi.responses import StreamingResponse

from ..dependencies import get_lambda_agent

router = APIRouter()

@router.post("/execute")
async def execute_code_api(
    request: dict = Body(...),
    lambda_instance = Depends(get_lambda_agent)
):
    code = request.get("code", "")
    session_id = request.get("session_id", "default")

    if not code:
        return {
            "success": False,
            "result": "Error: No code provided",
            "message": "Code execution failed",
        }

    try:
        # Run code directly through LAMBDA's Jupyter Kernel
        sign, msg_llm, exe_res = lambda_instance.conv.run_code(code)
        
        # Display new files generated in workspace
        display, link_info = lambda_instance.conv.check_folder()
        if display:
            exe_res += f"\n\n[Files Generated]: {link_info}"
            
        success = True if sign and 'error' not in sign else False
        
        return {
            "success": success,
            "result": exe_res if exe_res else msg_llm,
            "message": "Code executed successfully" if success else "Code execution failed",
        }
    except Exception as exc:
        return {
            "success": False,
            "result": f"Error: {exc}",
            "message": "Code execution failed",
        }

@router.get("/memory")
async def get_rimrule_memory(lambda_instance = Depends(get_lambda_agent)):
    try:
        rules = [r.to_dict() for r in lambda_instance.conv.verifier.memory_bank.rules]
        return {
            "success": True,
            "rules": rules
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc)
        }


def format_chunk(content: str, model: str) -> str:
    chunk = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    return json.dumps(chunk) + "\n"

def format_end_chunk(model: str) -> str:
    end_chunk = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    return json.dumps(end_chunk) + "\n"

@router.post("/chat/completions")
async def chat(body: dict = Body(...), lambda_instance = Depends(get_lambda_agent)):
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
        
    last_msg = messages[-1]
    user_query = last_msg.get("content", "")
    
    # [DOMAIN KNOWLEDGE INJECTION & RIMRULE EVOLUTION]
    if any(keyword in user_query.lower() for keyword in ["phân cụm", "persona", "clustering", "cluster"]):
        try:
            rules_context = lambda_instance.conv.verifier.memory_bank.retrieve_rules_symbolic(query_domain="python", top_k=5)
            if not rules_context:
                rules_context = "No past mistakes recorded yet."
        except Exception as e:
            rules_context = ""
            
        domain_knowledge = f"""
---
[DOMAIN KNOWLEDGE FOR DATA AGENT]
1. Financial Metrics:
- ARPU (Average Revenue Per User) MUST be calculated exactly as `df['cuoc_hang_thang'].mean()` for each cluster. NEVER divide by 30 or any other number.
- Churn_Rate MUST be calculated exactly as `df['RMDT'].mean()` for each cluster.

2. Anti-Hallucination for Categorical Data:
- When writing if-else rules to describe a persona based on a categorical column (like `khu_vuc`), you MUST NOT hallucinate or guess the values (e.g., 'Đô thị', 'Nông thôn'). You MUST use only the exact values present in the data (e.g., 'Vung Tau', 'Binh Duong'). To be safe, run `.unique()` on the column first if you are unsure.

3. RIMRULE EVOLUTION MEMORY (LESSONS LEARNED FROM PAST ERRORS):
{rules_context}
---
"""
        user_query += "\n" + domain_knowledge

    model_name = body.get("model", "lambda-triadic-agent")

    async def event_generator():
        try:
            # Reconstruct history for LAMBDA Gradio interface
            # LAMBDA expects a list of dictionaries with 'role' and 'content'
            gradio_history = []
            for msg in messages[:-1]:
                gradio_history.append({"role": msg["role"], "content": msg["content"]})
            
            # LAMBDA chat_streaming typically adds the user's current message, 
            # but since we are bypassing chat_streaming and calling stream_workflow directly,
            # we MUST add the user's current message here.
            gradio_history.append({"role": "user", "content": user_query})
            
            # Sync backend memory: If frontend only sends 1 message, it means it's a new chat, so clear backend context!
            if not messages[:-1]:
                lambda_instance.conv.programmer.clear()
            
            # CRITICAL: We also MUST add it to the actual LLM's conversation context!
            lambda_instance.conv.programmer.messages.append({"role": "user", "content": user_query})
            
            # Start streaming workflow
            workflow_generator = lambda_instance.conv.stream_workflow(gradio_history, code=None)
            
            last_len = 0
            is_executing = False
            
            yield format_chunk("<Analyze>\n", model_name)
            current_tag = "Analyze"
            
            # Since LAMBDA is synchronous generator, we should yield its delta chunks.
            buffer = ""
            for history in workflow_generator:
                if not history:
                    continue
                last_msg_dict = history[-1]
                if last_msg_dict.get("role") == "assistant" and last_msg_dict.get("content"):
                    assistant_response = last_msg_dict["content"]
                    new_text = assistant_response[last_len:]
                    if new_text:
                        last_len = len(assistant_response)
                        buffer += new_text

                        while True:
                            if "🖥️ Execute code..." in buffer:
                                idx = buffer.find("🖥️ Execute code...")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                yield format_chunk(f"\n</{current_tag}>\n<Execute>\nRunning in Sandbox Jupyter Kernel...\n", model_name)
                                current_tag = "Execute"
                                buffer = buffer[idx + len("🖥️ Execute code..."):]
                                continue

                            if "⭕ Execution error" in buffer:
                                idx = buffer.find("⭕ Execution error")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                yield format_chunk(f"\n</{current_tag}>\n<Analyze>\nAnalyzing error and repairing...\n", model_name)
                                current_tag = "Analyze"
                                buffer = buffer[idx + len("⭕ Execution error"):]
                                continue

                            if "**Execution Results:**" in buffer:
                                idx = buffer.find("**Execution Results:**")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                yield format_chunk(f"\n\n</{current_tag}>\n\n<Answer>\n\n", model_name)
                                current_tag = "Answer"
                                yield format_chunk("**Execution Results:**", model_name)
                                buffer = buffer[idx + len("**Execution Results:**"):]
                                continue

                            if "```python" in buffer and current_tag != "Execute":
                                idx = buffer.find("```python")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                yield format_chunk(f"\n\n</{current_tag}>\n\n<Code>\n\n```python", model_name)
                                current_tag = "Code"
                                buffer = buffer[idx + len("```python"):]
                                continue

                            if "**Final Report:**" in buffer:
                                idx = buffer.find("**Final Report:**")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                if current_tag != "Answer":
                                    yield format_chunk(f"\n\n</{current_tag}>\n\n<Answer>\n\n", model_name)
                                    current_tag = "Answer"
                                buffer = buffer[idx + len("**Final Report:**"):]
                                continue

                            # Remove unsupported html fragments
                            for tag in ["</button></div>", "<button class='suggestion-btn'>"]:
                                if tag in buffer:
                                    idx = buffer.find(tag)
                                    chunk_to_yield = buffer[:idx]
                                    if chunk_to_yield:
                                        yield format_chunk(chunk_to_yield, model_name)
                                    buffer = buffer[idx + len(tag):]

                            markers = ["🖥️ Execute code...", "⭕ Execution error", "**Execution Results:**", "**Final Report:**", "```python", "</button></div>", "<button class='suggestion-btn'>"]
                            safe_len = len(buffer)
                            for marker in markers:
                                for i in range(1, len(marker)):
                                    if buffer.endswith(marker[:i]):
                                        safe_len = min(safe_len, len(buffer) - i)
                                        break

                            if safe_len > 0:
                                chunk_to_yield = buffer[:safe_len]
                                if '](/file=' in chunk_to_yield:
                                    chunk_to_yield = chunk_to_yield.replace('](/file=', '](/file?path=')
                                yield format_chunk(chunk_to_yield, model_name)
                                buffer = buffer[safe_len:]
                            
                            break
                            
                        await asyncio.sleep(0.01)
            
            if buffer:
                if '](/file=' in buffer:
                    buffer = buffer.replace('](/file=', '](/file?path=')
                yield format_chunk(buffer, model_name)

            if current_tag != "Answer":
                yield format_chunk(f"\n\n</{current_tag}>\n\n<Answer>\n\n", model_name)
                
            # If we are already in Answer, we don't need to open it again, just close it.
            # But wait, earlier code appended "Workflow complete.\n\n</Answer>". Let's preserve that.
            if current_tag == "Answer":
                yield format_chunk("\n\n", model_name)
            
            # The UI doesn't necessarily need "Workflow complete" if it's already in Answer.
            yield format_chunk("Workflow complete.\n\n</Answer>", model_name)
            yield format_end_chunk(model_name)
            
        except Exception as e:
            yield format_chunk(f"\n\n</Analyze>\n\n<Answer>\n\nError: {e}\n\n</Answer>", model_name)
            yield format_end_chunk(model_name)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/chat/stop")
async def stop_chat(body: dict = Body(default={})):
    # LAMBDA doesn't have native abort yet, just acknowledge
    session_id = body.get("session_id", "default")
    return {"message": "stop requested", "session_id": session_id}
