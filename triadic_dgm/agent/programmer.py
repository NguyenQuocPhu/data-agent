import openai
from triadic_dgm.prompts.prompts import PROGRAMMER_PROMPT
from triadic_dgm.knowledge.knw_in import retrieval_knowledge
import os
import traceback
os.environ["TOKENIZERS_PARALLELISM"] = "false"


class Programmer:

    # hosted_vllm/Qwen3.5-35B-A3B-FP8's actual context window is 30000 tokens TOTAL
    # (input + output combined) — confirmed via a real 400 ContextWindowExceededError.
    # max_tokens must therefore be computed from remaining budget, not a large fixed
    # constant, or a normal-sized prompt plus a generous output request blows past 30000.
    MODEL_CONTEXT_LIMIT = 30000
    OUTPUT_TOKENS_FLOOR = 1500
    OUTPUT_TOKENS_CEILING = 8000
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

        # Protect System Prompt (0) and Initial Task/Domain Knowledge (1)
        while sum(len(str(m.get("content", ""))) for m in self.messages) > 70000 and len(self.messages) > 4:
            self.messages.pop(2)

        params = {
            "model": self.model,
            "messages": self.messages,
            "max_tokens": self._compute_max_tokens()
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

        # Protect System Prompt (0) and Initial Task/Domain Knowledge (1)
        while sum(len(str(m.get("content", ""))) for m in self.messages) > 70000 and len(self.messages) > 4:
            self.messages.pop(2)

        params = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "max_tokens": self._compute_max_tokens()
        }

        if include_functions:
            params['functions'] = functions
            params['function_call'] = "auto"

        try:
            stream = self.client.chat.completions.create(**params)
            self.messages[-1]["content"] = temp
            for chunk in stream:
                if (hasattr(chunk, 'choices') and
                        chunk.choices and
                        len(chunk.choices) > 0 and
                        chunk.choices[0].delta.content is not None):
                    chunk_message = chunk.choices[0].delta.content
                    yield chunk_message
        except Exception as e:
            print(f"Error calling chat model: {e}")
            traceback.print_exc()
            yield f"\n\n[LLM ERROR: {e}]\n\n"

    def clear(self):
        self.messages = [
            {
                "role": "system",
                "content": PROGRAMMER_PROMPT
            }
        ]
        self.function_repository = {}
