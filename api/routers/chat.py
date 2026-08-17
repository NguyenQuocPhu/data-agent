from __future__ import annotations

import json
import uuid
import time
import asyncio
from fastapi import APIRouter, Body, HTTPException, Depends
from fastapi.responses import StreamingResponse

from ..dependencies import get_lambda_agent
from ..services import workspace as workspace_service
from ..services.metadata_gate import collect_matching_metadata
from triadic_dgm.rlm_agent.skill_registry import list_skills
import os

router = APIRouter()


def _active_dataset_columns() -> list[str] | None:
    """Best-effort column peek at the currently active dataset in the "default"
    workspace, without loading the full file. Mirrors the same latest-tabular-file
    selection logic as api/dependencies.py's injected load_dataset(), so the file
    picked here matches what the sandbox will actually load. Returns None if no
    usable tabular dataset is registered (e.g. nothing uploaded yet)."""
    try:
        workspace_root = str(workspace_service.resolve_workspace_root("default"))
        index_path = os.path.join(workspace_root, "index.json")
        if not os.path.exists(index_path):
            return None
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
        if not index_data:
            return None
        tabular_exts = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
        tabular_entries = [
            (fid, info) for fid, info in index_data.items()
            if os.path.splitext(info.get("filename", info.get("path", "")))[1].lower() in tabular_exts
        ]
        if not tabular_entries:
            return None
        tabular_entries.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
        _, info = tabular_entries[0]
        file_path = os.path.join(workspace_root, info["path"])
        ext = os.path.splitext(file_path)[1].lower()
        import pandas as pd
        if ext in (".csv", ".tsv"):
            from api.services.profile_provider import stored_separator

            df = pd.read_csv(file_path, sep=stored_separator(workspace_root, info, ext),
                             nrows=0, engine="python")
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, nrows=0)
        else:
            return None
        return list(df.columns)
    except Exception:
        return None


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
        is_rlm = getattr(lambda_instance.conv, "is_rlm_agent", False)
        # RLM's notebook works directly in the active workspace. Legacy code
        # still writes into LAMBDA's session cache first.
        source_dir = (
            str(workspace_service.resolve_workspace_root(session_id))
            if is_rlm else lambda_instance.session_cache_path
        )
        known_before = {
            f for f in os.listdir(source_dir)
            if os.path.isfile(os.path.join(source_dir, f))
        } if os.path.isdir(source_dir) else set()

        # Run code directly through LAMBDA's Jupyter Kernel
        sign, msg_llm, exe_res = lambda_instance.conv.run_code(code)
        
        # Display new files generated in workspace
        display, link_info = lambda_instance.conv.check_folder()
        if display:
            exe_res += f"\n\n[Files Generated]: {link_info}"

        # RLM tools already save below workspace/generated. Legacy execution
        # still needs the copy/register pass from its cache directory.
        if is_rlm:
            new_generated_files = workspace_service.get_generated_files_for_session(session_id)
        else:
            new_generated_files = workspace_service.scan_and_register_generated(
                session_id=session_id,
                source_dir=source_dir,
                known_files_before=known_before,
            )

        success = True if sign and 'error' not in sign else False
        
        return {
            "success": success,
            "result": exe_res if exe_res else msg_llm,
            "message": "Code executed successfully" if success else "Code execution failed",
            "generated_files": new_generated_files,
        }
    except Exception as exc:
        return {
            "success": False,
            "result": f"Error: {exc}",
            "message": "Code execution failed",
            "generated_files": [],
        }

@router.get("/memory")
async def get_rimrule_memory(lambda_instance = Depends(get_lambda_agent)):
    try:
        if getattr(lambda_instance.conv, "verifier", None) is None:
            return {"success": True, "rules": [], "linked": False}
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


@router.get("/chat/context")
async def get_context_usage(lambda_instance = Depends(get_lambda_agent)):
    """Expose current agent context metrics for initial page load and refresh."""
    if getattr(lambda_instance.conv, "is_rlm_agent", False):
        return lambda_instance.conv.context_usage()
    return lambda_instance.conv.programmer.context_usage()


@router.get("/skills")
async def get_user_skills():
    """Return only skills that users may explicitly select from the chat UI."""
    return {"skills": list_skills(user_invocable_only=True)}


@router.post("/chat/reset")
async def reset_chat_context(lambda_instance = Depends(get_lambda_agent)):
    """Reset model conversation/compaction state without deleting data or notebook variables."""
    if getattr(lambda_instance.conv, "is_rlm_agent", False):
        lambda_instance.conv.clear()
        return {
            "success": True,
            "context_usage": lambda_instance.conv.context_usage(),
        }
    lambda_instance.conv.programmer.clear()
    lambda_instance.conv.observation_paused = False
    lambda_instance.conv.observation_pause_reason = None
    lambda_instance.conv.pending_human_decision = None
    return {
        "success": True,
        "context_usage": lambda_instance.conv.programmer.context_usage(),
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
    return "data: " + json.dumps(chunk) + "\n\n"


def format_context_chunk(context_usage: dict, model: str) -> str:
    """Send control-plane context metrics without adding text to the assistant answer."""
    chunk = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "context_usage": context_usage,
    }
    return "data: " + json.dumps(chunk) + "\n\n"


def format_human_decision_chunk(decision: dict, model: str) -> str:
    """Send a HITL control event without embedding UI syntax in chat text."""
    chunk = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "human_decision": decision,
    }
    return "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"


def format_rlm_event_chunk(event: dict, model: str) -> str:
    """Expose typed RLM events while keeping the tagged chat UI readable."""
    event_type = event.get("type")
    content = ""
    if event_type == "turn_started":
        # Open the section immediately, but do not present transport/runtime
        # status as model analysis. The following `analysis` event contains the
        # main model's verbatim prose before its first REPL block.
        content = "<Analyze>\n"
    elif event_type == "iteration_started":
        content = ""
    elif event_type == "analysis":
        response = str(event.get("content", "")).strip()
        content = "\n" + response + "\n" if response else ""
    elif event_type == "subcall_started":
        # Lifecycle events are useful in the typed event stream, but rendering
        # them inside the main model's Analyze/Execute sections makes the two
        # models look like one response. The complete call is rendered by the
        # `subcall_result` event below.
        content = ""
    elif event_type == "subcall_completed":
        content = ""
    elif event_type == "subcall_result":
        prompt = event.get("prompt", "")
        if not isinstance(prompt, str):
            prompt = json.dumps(prompt, ensure_ascii=False, indent=2)
        response = str(event.get("response", "") or "")
        error = event.get("error")
        usage = event.get("usage") or {}
        duration = event.get("execution_time")
        details = [
            f"**Call:** {event.get('call', '?')}",
            f"**Method:** `{event.get('call_type', 'sub_llm')}`",
            f"**Model:** `{event.get('model', 'unknown')}`",
        ]
        if duration is not None:
            details.append(f"**Duration:** {float(duration):.2f}s")
        details.extend([
            "---\n### Input prompt (full)\n" + str(prompt),
            "---\n### Output response (full)\n" + response,
        ])
        if usage:
            details.append(
                "---\n### Usage\n```json\n"
                + json.dumps(usage, ensure_ascii=False, indent=2)
                + "\n```"
            )
        if error:
            details.append("**Error:**\n" + str(error))
        content = (
            "\n</Execute>\n<SubLLM>\n"
            + "\n\n".join(details)
            + "\n</SubLLM>\n<Execute>\n"
        )
    elif event_type == "code":
        content = (
            "\n</Analyze>\n<Code>\n```python\n"
            + str(event.get("code", ""))
            + "\n```\n</Code>\n<Execute>\n"
        )
    elif event_type == "observation":
        output = str(event.get("stdout") or event.get("stderr") or "")
        if not output:
            output = "Cell completed without textual output."
        content = f"\n```trace\n{output}\n```\n</Execute>\n<Analyze>\n"
    elif event_type == "final_answer":
        content = "\n</Analyze>\n<Answer>\n" + str(event.get("content", "")) + "\n</Answer>"
    elif event_type == "error":
        content = "\n</Analyze>\n<Answer>\nError: " + str(event.get("message", "")) + "\n</Answer>"

    chunk = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"content": content} if content else {},
            "finish_reason": None,
        }],
        "agent_event": event,
    }
    if event_type == "context_usage":
        chunk["context_usage"] = {
            key: value for key, value in event.items() if key != "type"
        }
    if event_type == "human_decision":
        chunk["human_decision"] = {
            key: value for key, value in event.items() if key != "type"
        }
    return "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"


def _next_or_done(iterator):
    try:
        return False, next(iterator)
    except StopIteration:
        return True, None

def format_end_chunk(model: str) -> str:
    end_chunk = {
        "id": "chatcmpl-" + str(uuid.uuid4()),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    return "data: " + json.dumps(end_chunk) + "\n\ndata: [DONE]\n\n"

@router.post("/chat/completions")
async def chat(body: dict = Body(...), lambda_instance = Depends(get_lambda_agent)):
    messages = body.get("messages", [])
    session_id = body.get("session_id", "default")
    selected_skill = body.get("selected_skill")
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
        
    last_msg = messages[-1]
    user_query = last_msg.get("content", "")
    
    # Every block below appends to the model's context, and each one used to assert
    # something about the data without checking it. Peek at the dataset once, up front, and
    # gate all of them on it.
    active_cols = [str(c).lower() for c in (_active_dataset_columns() or [])]

    # Dynamic Metadata Injection.
    # Only dictionaries that actually describe the loaded dataset are injected. This used to
    # glob the working directory unconditionally, and `data_processed_t4_metadata.json` — the
    # telco data dictionary, 11.8 KB naming cl_total_6m / fee_total / OBJID / LOYALTY_RANK —
    # lives there permanently. Every analysis was handed it under "tuân thủ chặt chẽ", which
    # is why a 17-column retail upload produced behavioral_features from a telco schema.
    metadata_content = collect_matching_metadata(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        active_cols,
    )

    if metadata_content:
        user_query += f"\n\n[USER UPLOADED METADATA]\nHãy tham khảo và tuân thủ chặt chẽ metadata sau đây cho dữ liệu:\n{metadata_content}\n"

    model_name = body.get("model", "lambda-triadic-agent")

    if getattr(lambda_instance.conv, "is_rlm_agent", False):
        async def rlm_event_generator():
            iterator = iter(lambda_instance.conv.stream_turn(
                user_query,
                session_id=session_id,
                selected_skill=selected_skill,
            ))
            while True:
                done, event = await asyncio.to_thread(_next_or_done, iterator)
                if done:
                    break
                yield format_rlm_event_chunk(event.to_dict(), model_name)
            yield format_end_chunk(model_name)

        return StreamingResponse(rlm_event_generator(), media_type="text/event-stream")

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
            
            # A custom UI system prompt may precede the first user message, so detect actual
            # conversational history rather than relying on the raw array length.
            has_prior_conversation = any(
                msg.get("role") in {"user", "assistant"} for msg in messages[:-1]
            )
            if not has_prior_conversation:
                lambda_instance.conv.programmer.clear()
            
            # CRITICAL: We also MUST add it to the actual LLM's conversation context!
            lambda_instance.conv.programmer.messages.append({"role": "user", "content": user_query})
            yield format_context_chunk(
                lambda_instance.conv.programmer.context_usage(),
                model_name,
            )
            
            # Start streaming workflow
            # ── Phase 1: LangGraph routing ──────────────────────────────────────
            # USER KHUYẾN NGHỊ TẮT LANGGRAPH DO LỖI, SỬ DỤNG LUỒNG CŨ
            use_lg = False
            if use_lg and hasattr(lambda_instance, "lg_graph"):
                workflow_generator = lambda_instance.lg_graph.stream(user_query, gradio_history, session_id=session_id)
            else:
                workflow_generator = lambda_instance.conv.stream_workflow(
                    gradio_history,
                    code=None,
                    session_id=session_id,
                )

            
            last_len = 0
            is_executing = False
            
            yield format_chunk("<Analyze>\n", model_name)
            current_tag = "Analyze"
            
            # Since LAMBDA is synchronous generator, we should yield its delta chunks.
            buffer = ""
            for history in workflow_generator:
                if not history:
                    continue
                yield format_context_chunk(
                    lambda_instance.conv.programmer.context_usage(),
                    model_name,
                )
                last_msg_dict = history[-1]
                if last_msg_dict.get("role") == "assistant" and last_msg_dict.get("content"):
                    assistant_response = last_msg_dict["content"]
                    new_text = assistant_response[last_len:]
                    if new_text:
                        last_len = len(assistant_response)
                        buffer += new_text

                        while True:
                            if "🧭 Agent deciding next action" in buffer:
                                idx = buffer.find("🧭 Agent deciding next action")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                if current_tag != "Analyze":
                                    yield format_chunk(f"\n</{current_tag}>\n<Analyze>\n", model_name)
                                    current_tag = "Analyze"
                                line_end = buffer.find("\n", idx)
                                if line_end == -1:
                                    buffer = ""
                                else:
                                    buffer = buffer[line_end + 1:]
                                yield format_chunk("Choosing the next notebook action...\n", model_name)
                                continue

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

                            if "**Final Answer:**" in buffer:
                                idx = buffer.find("**Final Answer:**")
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                if current_tag != "Answer":
                                    yield format_chunk(f"\n\n</{current_tag}>\n\n<Answer>\n\n", model_name)
                                    current_tag = "Answer"
                                buffer = buffer[idx + len("**Final Answer:**"):]
                                continue

                            human_marker = None
                            for candidate in ("**Agent cần bạn quyết định:**", "**Kế hoạch đề xuất:**"):
                                if candidate in buffer:
                                    human_marker = candidate
                                    break
                            if human_marker:
                                idx = buffer.find(human_marker)
                                chunk_to_yield = buffer[:idx]
                                if chunk_to_yield:
                                    yield format_chunk(chunk_to_yield, model_name)
                                if current_tag != "Answer":
                                    yield format_chunk(f"\n\n</{current_tag}>\n\n<Answer>\n\n", model_name)
                                    current_tag = "Answer"
                                yield format_chunk(human_marker, model_name)
                                buffer = buffer[idx + len(human_marker):]
                                continue

                            # Remove unsupported html fragments
                            for tag in ["</button></div>", "<button class='suggestion-btn'>"]:
                                if tag in buffer:
                                    idx = buffer.find(tag)
                                    chunk_to_yield = buffer[:idx]
                                    if chunk_to_yield:
                                        yield format_chunk(chunk_to_yield, model_name)
                                    buffer = buffer[idx + len(tag):]

                            markers = ["🧭 Agent deciding next action", "🖥️ Execute code...", "⭕ Execution error", "**Execution Results:**", "**Final Report:**", "**Final Answer:**", "**Agent cần bạn quyết định:**", "**Kế hoạch đề xuất:**", "```python", "</button></div>", "<button class='suggestion-btn'>"]
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
            
            # Check if paused
            config = {"configurable": {"thread_id": session_id}}
            is_paused_now = False
            if use_lg and hasattr(lambda_instance, "lg_graph"):
                final_state = lambda_instance.lg_graph.compiled.get_state(config)
                if len(final_state.next) > 0:
                    is_paused_now = True
            elif getattr(lambda_instance.conv, "observation_paused", False):
                is_paused_now = True

            if is_paused_now:
                pending_decision = getattr(
                    lambda_instance.conv, "pending_human_decision", None
                )
                if pending_decision:
                    yield format_human_decision_chunk(pending_decision, model_name)
                yield format_chunk("Chờ phản hồi của bạn để chạy tiếp...\n\n</Answer>", model_name)
            else:
                yield format_chunk("Workflow complete.\n\n</Answer>", model_name)

            # ==== SCAN for newly generated files and notify frontend ====
            try:
                source_dir = lambda_instance.session_cache_path
                new_files = workspace_service.scan_and_register_generated(
                    session_id=session_id,
                    source_dir=source_dir,
                    known_files_before=None,  # grab all valid-extension files each time
                )
                if new_files:
                    files_event = json.dumps({"type": "generated_files", "files": new_files})
                    yield format_chunk(f"\n<!-- GENERATED_FILES:{files_event} -->\n", model_name)
            except Exception as scan_err:
                print(f"[chat] scan_and_register_generated failed: {scan_err}")

            yield format_context_chunk(
                lambda_instance.conv.programmer.context_usage(),
                model_name,
            )
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
