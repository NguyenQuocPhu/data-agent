import openai
from triadic_dgm.prompts.prompts import OBSERVATION_AGENT_PROMPT
from triadic_dgm.knowledge.knw_in import retrieval_knowledge
import os
import json
import time
import traceback
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Qwen3.5 (hosted qua proxy proxy.onebot.meobeo.ai) hỗ trợ chế độ "thinking" — sinh 1 đoạn suy luận
# nội bộ dài trước khi trả lời thật, làm request lâu hơn nhiều và dễ chạm timeout của gateway (504,
# ĐÃ XẢY RA NHIỀU LẦN trên live run, request treo ~90s trước khi gateway trả 504). Tắt hẳn để giảm
# thời gian sinh — cùng pattern đã dùng cho đúng model/proxy này ở
# triadic_dgm/benchmark/implementations/qwen_llm.py (comment gốc: "proxy thường xuyên rớt").
def _model_extra_body():
    """Load provider-specific payload fields from the environment."""
    extra_body = {}
    raw = os.environ.get("OPENAI_EXTRA_BODY", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                extra_body.update(parsed)
        except json.JSONDecodeError as exc:
            print(f"Ignoring invalid OPENAI_EXTRA_BODY JSON: {exc}")

    chat_template = extra_body.setdefault("chat_template_kwargs", {})
    if isinstance(chat_template, dict):
        chat_template.setdefault("enable_thinking", False)
    return extra_body


class DecisionAgent:

    # The company gateway advertises a 32k TOTAL window (prompt + requested output). One action
    # envelope is intentionally much smaller than the old monolithic Programmer response, so it
    # does not need a 20k output reservation on every observation-loop step.
    MODEL_CONTEXT_LIMIT = 32000
    OUTPUT_TOKENS_FLOOR = 1000
    OUTPUT_TOKENS_CEILING = 6000
    CONTEXT_SAFETY_MARGIN = 2000

    # Qwen's exact tokenizer is owned by the remote gateway. Two characters/token deliberately
    # overestimates mixed Vietnamese/English/code prompts so compaction happens before the gateway
    # rejects the request, rather than after it.
    CHARS_PER_TOKEN_ESTIMATE = 2
    COMPACTION_TRIGGER_TOKENS = 20000
    COMPACTION_TARGET_TOKENS = 10000
    COMPACTION_MAX_OUTPUT_TOKENS = 2000
    COMPACTION_RECENT_MESSAGES = 4
    COMPACTION_MARKER = "[COMPACTED_WORKING_MEMORY]"

    def __init__(self, api_key, model="gpt-4o-mini", base_url=None):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.system_prompt = OBSERVATION_AGENT_PROMPT
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.function_repository = {}
        self.last_snaps = None
        self.compaction_count = 0
        # Durable summary of compacted turns. Keep it outside ``messages`` so providers
        # whose chat templates allow exactly one leading system message never receive a
        # second system role. It is merged into that one system message only at request time.
        self.working_memory = ""

    def add_functions(self, function_lib: dict) -> None:
        self.function_repository = function_lib

    def set_system_prompt(self, prompt: str) -> None:
        """Replace the control prompt and make future ``clear`` calls preserve it."""
        self.system_prompt = prompt
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {"role": "system", "content": prompt}
        else:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def decide_next_action(self) -> str:
        """Ask the model for one action envelope instead of a monolithic script."""
        response = self._call_chat_model()
        if response is None or not getattr(response, "choices", None):
            raise RuntimeError("Decision model returned no response")
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Decision model returned an empty response")
        return content

    def _compute_max_tokens(self) -> int:
        estimated_prompt_tokens = self._estimate_message_tokens(
            self._build_request_messages()
        )
        available = self.MODEL_CONTEXT_LIMIT - estimated_prompt_tokens - self.CONTEXT_SAFETY_MARGIN
        return max(self.OUTPUT_TOKENS_FLOOR, min(self.OUTPUT_TOKENS_CEILING, available))

    def context_usage(self) -> dict:
        """Return the same conservative context estimate used for request budgeting."""
        estimated_tokens = self._estimate_message_tokens(
            self._build_request_messages()
        )
        used_percent = min(100.0, estimated_tokens / self.MODEL_CONTEXT_LIMIT * 100)
        compact_percent = min(
            100.0,
            estimated_tokens / self.COMPACTION_TRIGGER_TOKENS * 100,
        )
        return {
            "estimated_tokens": estimated_tokens,
            "context_limit": self.MODEL_CONTEXT_LIMIT,
            "used_percent": round(used_percent, 1),
            "remaining_tokens": max(0, self.MODEL_CONTEXT_LIMIT - estimated_tokens),
            "compaction_trigger_tokens": self.COMPACTION_TRIGGER_TOKENS,
            "compaction_progress_percent": round(compact_percent, 1),
            "near_compaction": compact_percent >= 80,
            "compaction_count": self.compaction_count,
        }

    @classmethod
    def _estimate_message_tokens(cls, messages) -> int:
        prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
        return max(1, prompt_chars // cls.CHARS_PER_TOKEN_ESTIMATE)

    @staticmethod
    def _message_transcript(messages) -> str:
        blocks = []
        for message in messages:
            role = str(message.get("role", "unknown")).upper()
            content = str(message.get("content", ""))
            blocks.append(f"--- {role} ---\n{content}")
        return "\n\n".join(blocks)

    def _fallback_compaction(self, messages) -> str:
        """Keep bounded evidence when the summarizer endpoint is temporarily unavailable."""
        transcript = self._message_transcript(messages)
        limit = self.COMPACTION_TARGET_TOKENS * self.CHARS_PER_TOKEN_ESTIMATE
        if len(transcript) > limit:
            half = max(1, (limit - 80) // 2)
            transcript = transcript[:half] + "\n...[OLDER CONTEXT OMITTED]...\n" + transcript[-half:]
        return (
            f"{self.COMPACTION_MARKER}\n"
            "Automatic semantic summary was unavailable. The following bounded excerpts are "
            "authoritative working memory from earlier turns:\n"
            f"{transcript}"
        )

    def _build_request_messages(self) -> list[dict]:
        """Build a provider-compatible request with exactly one leading system role."""
        base_system = self.system_prompt
        non_system_messages = self.messages
        if self.messages and self.messages[0].get("role") == "system":
            base_system = str(self.messages[0].get("content", self.system_prompt))
            non_system_messages = self.messages[1:]

        system_content = base_system
        if self.working_memory:
            system_content = (
                f"{base_system.rstrip()}\n\n"
                "[DURABLE WORKING MEMORY FROM EARLIER TURNS]\n"
                f"{self.working_memory.strip()}"
            )

        # Defensive normalization also makes old in-memory state recoverable if this code is
        # hot-reloaded after the previous implementation inserted a second system message.
        normalized_messages = []
        extra_system_content = []
        for message in non_system_messages:
            if message.get("role") == "system":
                extra_system_content.append(str(message.get("content", "")))
            else:
                normalized_messages.append(message)
        if extra_system_content:
            system_content += "\n\n" + "\n\n".join(extra_system_content)

        return [
            {"role": "system", "content": system_content},
            *normalized_messages,
        ]

    def _compact_context_if_needed(self) -> bool:
        """Summarize old loop turns while retaining recent actions and notebook observations."""
        if self._estimate_message_tokens(
            self._build_request_messages()
        ) <= self.COMPACTION_TRIGGER_TOKENS:
            return False
        if len(self.messages) <= 3:
            return False

        system_message = self.messages[0]
        non_system = self.messages[1:]
        # Always leave at least two recent messages verbatim, but make sure there is an older
        # section to compact even when a few individual notebook outputs are unusually large.
        keep_count = min(self.COMPACTION_RECENT_MESSAGES, max(2, len(non_system) - 1))
        older_messages = non_system[:-keep_count]
        recent_messages = non_system[-keep_count:]
        if not older_messages:
            return False

        compaction_instruction = (
            "Compress the transcript into durable working memory for a stateful notebook agent. "
            "Preserve: the user's goal and constraints; human approvals/decisions; dataset IDs, "
            "filenames and relevant schema; the accepted plan; notebook variables/files that now "
            "exist; completed actions and verified numeric results; unresolved errors and the next "
            "step. Do not reproduce full code or verbose raw output. Do not invent facts. Return "
            "only a concise structured summary, ideally under 1200 tokens."
        )
        source_messages = []
        if self.working_memory:
            source_messages.append({
                "role": "user",
                "content": (
                    "Existing durable working memory to merge and refresh:\n"
                    f"{self.working_memory}"
                ),
            })
        source_messages.extend(older_messages)
        transcript = self._message_transcript(source_messages)
        # This call happens proactively around 20k estimated tokens, safely below the 32k window.
        # Still cap pathological single messages so the recovery mechanism cannot itself overflow.
        max_source_chars = (
            self.MODEL_CONTEXT_LIMIT
            - self.COMPACTION_MAX_OUTPUT_TOKENS
            - self.CONTEXT_SAFETY_MARGIN
        ) * self.CHARS_PER_TOKEN_ESTIMATE
        if len(transcript) > max_source_chars:
            half = max(1, (max_source_chars - 80) // 2)
            transcript = transcript[:half] + "\n...[MIDDLE OMITTED FOR COMPACTION]...\n" + transcript[-half:]

        summary = None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": compaction_instruction},
                    {"role": "user", "content": transcript},
                ],
                max_tokens=self.COMPACTION_MAX_OUTPUT_TOKENS,
                extra_body=_model_extra_body(),
            )
            if response is not None and getattr(response, "choices", None):
                summary = response.choices[0].message.content
        except Exception as exc:
            print(f"Context compaction failed; using bounded excerpts: {exc}")

        if not summary:
            compacted_content = self._fallback_compaction(source_messages)
        else:
            compacted_content = f"{self.COMPACTION_MARKER}\n{summary.strip()}"

        self.working_memory = compacted_content
        self.messages = [system_message, *recent_messages]
        self.compaction_count += 1
        print(
            "Context compacted: "
            f"{len(older_messages)} old message(s) -> working summary; "
            f"{len(recent_messages)} recent message(s) kept verbatim."
        )
        return True

    def _call_chat_model(self, functions=None, include_functions=False, retrieval=False):
        if retrieval:
            snaps = retrieval_knowledge(self.messages[-1]["content"])
            if snaps:
                self.last_snaps = snaps
                self.messages[-1]["content"] += snaps
            else:
                self.last_snaps = None

        self._compact_context_if_needed()

        params = {
            "model": self.model,
            "messages": self._build_request_messages(),
            "max_tokens": self._compute_max_tokens(),
            "extra_body": _model_extra_body(),
        }

        if include_functions:
            params['functions'] = functions
            params['function_call'] = "auto"

        try:
            response = self.client.chat.completions.create(**params)
            usage = response.usage
            print(f"======Prompt Tokens: {usage.prompt_tokens}======Completion Tokens: {usage.completion_tokens}=======Total Tokens: {usage.total_tokens}")
            return response
        except Exception as e:
            print(f"Error calling chat model: {e}")
            raise RuntimeError(f"Decision model request failed: {e}") from e

    def _call_chat_model_streaming(self, functions=None, include_functions=False, retrieval=False, kernel=None):
        temp = self.messages[-1]["content"]
        if retrieval:
            snaps = retrieval_knowledge(self.messages[-1]["content"], kernel=kernel)
            if snaps:
                for chunk in snaps:
                    yield chunk
                self.last_snaps = snaps
                self.messages[-1]["content"] += snaps
            else:
                self.last_snaps = None

        self._compact_context_if_needed()

        params = {
            "model": self.model,
            "messages": self._build_request_messages(),
            "stream": True,
            "max_tokens": self._compute_max_tokens(),
            "extra_body": _model_extra_body(),
        }

        if include_functions:
            params['functions'] = functions
            params['function_call'] = "auto"

        # Retry với backoff — đây là lệnh gọi LLM NẶNG NHẤT và chạy ĐẦU TIÊN trong cả pipeline (sinh
        # toàn bộ code K-Means/business-rules/JSON), trước đây KHÔNG có retry nào cả: 1 lần gateway
        # timeout (504, cùng loại lỗi đã gặp ở report_generator.py) là mất trắng, không có gì để
        # fallback (khác narrative LLM call — cái đó còn rơi về bản deterministic). CHỈ retry khi
        # CHƯA yield được chunk nào (stream fail ngay từ đầu, an toàn để thử lại từ đầu) — nếu đã
        # stream ra 1 phần nội dung rồi mới fail thì KHÔNG retry (sẽ bị lặp nội dung trong chat).
        max_attempts = 3
        for attempt in range(max_attempts):
            yielded_any = False
            try:
                stream = self.client.chat.completions.create(**params)
                self.messages[-1]["content"] = temp
                for chunk in stream:
                    if (hasattr(chunk, 'choices') and
                            chunk.choices and
                            len(chunk.choices) > 0 and
                            chunk.choices[0].delta.content is not None):
                        chunk_message = chunk.choices[0].delta.content
                        yielded_any = True
                        yield chunk_message
                return
            except Exception as e:
                print(f"Error calling chat model (attempt {attempt + 1}/{max_attempts}): {e}")
                traceback.print_exc()
                if yielded_any or attempt == max_attempts - 1:
                    yield f"\n\n[LLM ERROR: {e}]\n\n"
                    return
                time.sleep(2 * (attempt + 1))  # 2s, rồi 4s trước lần thử tiếp theo

    def clear(self):
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.function_repository = {}
        self.compaction_count = 0
        self.working_memory = ""


# Compatibility for legacy benchmark and UI code that still imports the old name.
Programmer = DecisionAgent
