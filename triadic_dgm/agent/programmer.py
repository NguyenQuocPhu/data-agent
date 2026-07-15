import openai
from triadic_dgm.prompts.prompts import PROGRAMMER_PROMPT
from triadic_dgm.knowledge.knw_in import retrieval_knowledge
import os
import time
import traceback
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Qwen3.5 (hosted qua proxy proxy.onebot.meobeo.ai) hỗ trợ chế độ "thinking" — sinh 1 đoạn suy luận
# nội bộ dài trước khi trả lời thật, làm request lâu hơn nhiều và dễ chạm timeout của gateway (504,
# ĐÃ XẢY RA NHIỀU LẦN trên live run, request treo ~90s trước khi gateway trả 504). Tắt hẳn để giảm
# thời gian sinh — cùng pattern đã dùng cho đúng model/proxy này ở
# triadic_dgm/benchmark/implementations/qwen_llm.py (comment gốc: "proxy thường xuyên rớt").
_DISABLE_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


class Programmer:

    # Model's real context window is 64000 tokens TOTAL (input + output combined), confirmed
    # directly by the user — the previous 30000 figure (from an earlier session's 400
    # ContextWindowExceededError) was wrong/stale and was needlessly starving output generation:
    # every pipeline script got hard cut off by max_tokens well before finishing (same
    # SyntaxError, same truncation point, on every retry — a token-limit cutoff isn't something
    # retrying alone can fix). max_tokens is still computed from remaining budget rather than a
    # flat constant, so a large prompt/history doesn't blow past the real limit.
    MODEL_CONTEXT_LIMIT = 62000
    OUTPUT_TOKENS_FLOOR = 1500
    OUTPUT_TOKENS_CEILING = 20000
    CONTEXT_SAFETY_MARGIN = 1000
    CHARS_PER_TOKEN_ESTIMATE = 3  # conservative for mixed Vietnamese/English/code content

    def __init__(self, api_key, model="gpt-4o-mini", base_url=None):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.messages = []
        self.function_repository = {}
        self.last_snaps = None

    def add_functions(self, function_lib: dict) -> None:
        self.function_repository = function_lib

    def _compute_max_tokens(self) -> int:
        prompt_chars = sum(len(str(m.get("content", ""))) for m in self.messages)
        estimated_prompt_tokens = prompt_chars // self.CHARS_PER_TOKEN_ESTIMATE
        available = self.MODEL_CONTEXT_LIMIT - estimated_prompt_tokens - self.CONTEXT_SAFETY_MARGIN
        return max(self.OUTPUT_TOKENS_FLOOR, min(self.OUTPUT_TOKENS_CEILING, available))

    def _call_chat_model(self, functions=None, include_functions=False, retrieval=False):
        if retrieval:
            snaps = retrieval_knowledge(self.messages[-1]["content"])
            if snaps:
                self.last_snaps = snaps
                self.messages[-1]["content"] += snaps
            else:
                self.last_snaps = None

        # Protect System Prompt (0) and Initial Task/Domain Knowledge (1). Threshold scaled to the
        # real 62000-token budget (MODEL_CONTEXT_LIMIT) — keeps enough headroom for at least a full
        # OUTPUT_TOKENS_CEILING-sized generation even after several repair rounds' worth of history
        # (each failed attempt appends its full generated script) have accumulated.
        while sum(len(str(m.get("content", ""))) for m in self.messages) > 120000 and len(self.messages) > 4:
            self.messages.pop(2)

        params = {
            "model": self.model,
            "messages": self.messages,
            "max_tokens": self._compute_max_tokens(),
            "extra_body": _DISABLE_THINKING_EXTRA_BODY,
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
            return None

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

        # Protect System Prompt (0) and Initial Task/Domain Knowledge (1). Threshold scaled to the
        # real 62000-token budget (MODEL_CONTEXT_LIMIT) — keeps enough headroom for at least a full
        # OUTPUT_TOKENS_CEILING-sized generation even after several repair rounds' worth of history
        # (each failed attempt appends its full generated script) have accumulated.
        while sum(len(str(m.get("content", ""))) for m in self.messages) > 120000 and len(self.messages) > 4:
            self.messages.pop(2)

        params = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "max_tokens": self._compute_max_tokens(),
            "extra_body": _DISABLE_THINKING_EXTRA_BODY,
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
        # IMPORTANT — do NOT .format() PROGRAMMER_PROMPT here (tried it, reverted). The prompt's
        # embedded reference pipeline uses {{double-brace}} escapes so LAMBDA.py's one-time
        # .format(working_path=...) at init produces valid Python. But that one-time formatted
        # copy is immediately overwritten: clear() runs on every new chat (chat.py) and every
        # convergence-loop iteration, and the system has been tuned against the RAW (doubled-
        # brace) prompt ever since — the LLM can't copy the malformed reference code verbatim,
        # so it IMPROVISES working clustering code. Confirmed live: 358 convergence runs on
        # 07-14 with this raw prompt were 100% healthy; switching clear() to .format() (valid
        # braces → LLM copies the canonical pipeline verbatim, incl. its fragile Stage-2 gates)
        # made 100% of runs hard-stop to "Clustering Failed". The doubled-brace state is the
        # battle-tested one — keep it.
        self.messages = [
            {
                "role": "system",
                "content": PROGRAMMER_PROMPT
            }
        ]
        self.function_repository = {}
