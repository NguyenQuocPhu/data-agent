"""
Unified LLM Client - Multi-provider support.
Ported from dgm_agent (V1) llm.py and adapted to triadic_dgm.benchmark architecture.

Supports: Anthropic, OpenAI (GPT/o1/o3), Amazon Bedrock, Vertex AI,
           DeepSeek, hosted_vllm (Qwen proxy), and any OpenAI-compatible API.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import backoff

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import openai
except ImportError:
    openai = None

from triadic_dgm.benchmark.interfaces.llm_client import ILLMClient

MAX_OUTPUT_TOKENS = 4096
AVAILABLE_LLMS = [
    # Anthropic models
    "claude-3-5-sonnet-20240620",
    "claude-3-5-sonnet-20241022",
    # OpenAI models
    "gpt-4o-mini-2024-07-18",
    "gpt-4o-2024-05-13",
    "gpt-4o-2024-08-06",
    "o1-preview-2024-09-12",
    "o1-mini-2024-09-12",
    "o1-2024-12-17",
    "o3-mini-2025-01-31",
    # OpenRouter models
    "llama3.1-405b",
    # Anthropic Claude models via Amazon Bedrock
    "bedrock/anthropic.claude-3-sonnet-20240229-v1:0",
    "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "bedrock/anthropic.claude-3-opus-20240229-v1:0",
    "bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    # Anthropic Claude models Vertex AI
    "vertex_ai/claude-3-opus@20240229",
    "vertex_ai/claude-3-5-sonnet@20240620",
    "vertex_ai/claude-3-5-sonnet-v2@20241022",
    "vertex_ai/claude-3-sonnet@20240229",
    "vertex_ai/claude-3-haiku@20240307",
    # DeepSeek models
    "deepseek-chat",
    "deepseek-coder",
    "deepseek-reasoner",
]


def create_client(model: str) -> Tuple[Any, str]:
    """
    Create and return an LLM client based on the specified model.

    Returns:
        Tuple[client, model_name]: The client instance and effective model name.
    """
    if model.startswith("claude-"):
        print(f"Using Anthropic API with model {model}.")
        return anthropic.Anthropic(), model
    elif model.startswith("bedrock") and "claude" in model:
        client_model = model.split("/")[-1]
        print(f"Using Amazon Bedrock with model {client_model}.")
        client = anthropic.AnthropicBedrock(
            aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_region=os.getenv("AWS_REGION_NAME"),
        )
        return client, client_model
    elif model.startswith("vertex_ai") and "claude" in model:
        client_model = model.split("/")[-1]
        print(f"Using Vertex AI with model {client_model}.")
        return anthropic.AnthropicVertex(), client_model
    elif 'gpt' in model or model.startswith("o1-") or model.startswith("o3-"):
        print(f"Using OpenAI API with model {model}.")
        return openai.OpenAI(), model
    elif model.startswith("deepseek-"):
        print(f"Using DeepSeek API with {model}.")
        client = openai.OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", os.environ.get("DEEP_SEEK_API", "")),
            base_url="https://api.deepseek.com"
        )
        return client, model
    elif model == "llama3.1-405b":
        print(f"Using OpenRouter API with {model}.")
        client = openai.OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1"
        )
        return client, model
    elif model.startswith("hosted_vllm/"):
        # Qwen proxy (proxy.onebot.meobeo.ai) or any hosted vLLM endpoint
        base_url = "https://proxy.onebot.meobeo.ai/v1"
        api_key_env = "QWEN_API_KEY"
        try:
            import yaml
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "config.yaml"
            )
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            base_url = config.get("base_url_conv_model", base_url)
            api_key_env = config.get("api_key_env_var", api_key_env)
        except Exception:
            pass
        api_key = os.environ.get(api_key_env) or os.environ.get("OPENAI_API_KEY", "")
        print(f"Using hosted_vllm proxy ({base_url}) with model {model}.")
        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        return client, model
    else:
        raise ValueError(f"Model {model} not supported.")


def _get_retry_exceptions():
    """Get retry exception classes based on available libraries."""
    exceptions = []
    if openai:
        exceptions.extend([openai.RateLimitError, openai.APITimeoutError])
    if anthropic:
        exceptions.extend([anthropic.RateLimitError, anthropic.APIStatusError])
    return tuple(exceptions) if exceptions else (Exception,)


@backoff.on_exception(
    backoff.expo,
    _get_retry_exceptions(),
    max_time=120,
)
def get_response_from_llm(
    msg: str,
    client: Any,
    model: str,
    system_message: str,
    print_debug: bool = False,
    msg_history: Optional[List[Dict]] = None,
    temperature: float = 0.7,
) -> Tuple[str, List[Dict]]:
    """
    Get a single response from the LLM.
    Supports Anthropic Claude, OpenAI GPT/o1/o3, DeepSeek, and OpenAI-compatible APIs.

    Returns:
        Tuple[content, new_msg_history]
    """
    if msg_history is None:
        msg_history = []

    if "claude" in model:
        new_msg_history = msg_history + [
            {"role": "user", "content": [{"type": "text", "text": msg}]}
        ]
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=temperature,
            system=system_message,
            messages=new_msg_history,
        )
        content = response.content[0].text
        new_msg_history = new_msg_history + [
            {"role": "assistant", "content": [{"type": "text", "text": content}]}
        ]
    elif model.startswith("gpt-4o-"):
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            stop=None,
            seed=0,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    elif model.startswith("o1-") or model.startswith("o3-"):
        new_msg_history = msg_history + [{"role": "user", "content": system_message + msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[*new_msg_history],
            temperature=1,
            n=1,
            seed=0,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    elif model in ["deepseek-chat", "deepseek-coder"]:
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            stop=None,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    elif model in ["deepseek-reasoner"]:
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            n=1,
            stop=None,
        )
        content = response.choices[0].message.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]
    else:
        # Fallback: OpenAI-compatible API (hosted_vllm, Groq, etc.)
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=1,
            stream=True
        )
        content = ""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content += chunk.choices[0].delta.content
        new_msg_history = new_msg_history + [{"role": "assistant", "content": content}]

    if print_debug:
        print("\n" + "*" * 20 + " LLM START " + "*" * 20)
        print(f'User: {new_msg_history[-2]["content"]}')
        print(f'Assistant: {new_msg_history[-1]["content"]}')
        print("*" * 21 + " LLM END " + "*" * 21 + "\n")

    return content, new_msg_history


def get_batch_responses_from_llm(
    msg: str,
    client: Any,
    model: str,
    system_message: str,
    print_debug: bool = False,
    msg_history: Optional[List[Dict]] = None,
    temperature: float = 0.75,
    n_responses: int = 1,
) -> Tuple[List[str], List[List[Dict]]]:
    """
    Get N responses from a single message, used for ensembling.

    Returns:
        Tuple[list_of_contents, list_of_msg_histories]
    """
    if msg_history is None:
        msg_history = []

    # For models that support native n>1
    if model in ["gpt-4o-2024-05-13", "gpt-4o-mini-2024-07-18", "gpt-4o-2024-08-06"]:
        new_msg_history = msg_history + [{"role": "user", "content": msg}]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                *new_msg_history,
            ],
            temperature=temperature,
            max_tokens=MAX_OUTPUT_TOKENS,
            n=n_responses,
            stop=None,
            seed=0,
        )
        content = [r.message.content for r in response.choices]
        new_msg_history = [
            new_msg_history + [{"role": "assistant", "content": c}] for c in content
        ]
    else:
        # Fallback: call get_response_from_llm N times
        content, new_msg_history = [], []
        for _ in range(n_responses):
            c, hist = get_response_from_llm(
                msg, client, model, system_message,
                print_debug=False, msg_history=None, temperature=temperature,
            )
            content.append(c)
            new_msg_history.append(hist)

    if print_debug:
        print("\n" + "*" * 20 + " LLM START " + "*" * 20)
        for j, m in enumerate(new_msg_history[0]):
            print(f'{j}, {m["role"]}: {m["content"]}')
        print(content)
        print("*" * 21 + " LLM END " + "*" * 21 + "\n")

    return content, new_msg_history


def extract_json_between_markers(llm_output: str) -> Optional[dict]:
    """
    Extract a JSON object from LLM output, looking for ```json code blocks first,
    then falling back to regex search.
    """
    inside_json_block = False
    json_lines = []

    for line in llm_output.split('\n'):
        stripped_line = line.strip()

        if stripped_line.startswith("```json"):
            inside_json_block = True
            continue

        if inside_json_block and stripped_line.startswith("```"):
            inside_json_block = False
            break

        if inside_json_block:
            json_lines.append(line)

    # Fallback: regex for any JSON-like object
    if not json_lines:
        fallback_pattern = r"\{.*?\}"
        matches = re.findall(fallback_pattern, llm_output, re.DOTALL)
        for candidate in matches:
            candidate = candidate.strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    candidate_clean = re.sub(r"[\x00-\x1F\x7F]", "", candidate)
                    try:
                        return json.loads(candidate_clean)
                    except json.JSONDecodeError:
                        continue
        return None

    json_string = "\n".join(json_lines).strip()

    try:
        return json.loads(json_string)
    except json.JSONDecodeError:
        json_string_clean = re.sub(r"[\x00-\x1F\x7F]", "", json_string)
        try:
            return json.loads(json_string_clean)
        except json.JSONDecodeError:
            return None


class UnifiedLLMClient(ILLMClient):
    """
    Adapter that wraps the V1 multi-provider LLM functions
    behind the V2 ILLMClient interface.
    """

    def __init__(self, model: str):
        self.model = model
        self._client, self._effective_model = create_client(model)

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.7) -> str:
        """Generate a response from the LLM."""
        content, _ = get_response_from_llm(
            msg=prompt,
            client=self._client,
            model=self._effective_model,
            system_message=system_prompt,
            temperature=temperature,
        )
        return content

    def generate_with_tools(
        self,
        messages: list,
        system_prompt: str,
        tools: list,
        temperature: float = 0.2,
        max_tokens: int = 4096
    ) -> tuple[str, Optional[dict]]:
        
        req_messages = []
        if system_prompt:
            req_messages.append({"role": "system", "content": system_prompt})
        req_messages.extend(messages)
        
        try:
            response = self._client.chat.completions.create(
                model=self._effective_model,
                messages=req_messages,
                tools=tools,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens
            )
            msg = response.choices[0].message
            content = msg.content or ""
            
            tool_call_dict = None
            if msg.tool_calls and len(msg.tool_calls) > 0:
                tcall = msg.tool_calls[0]
                import json
                tool_call_dict = {
                    "name": tcall.function.name,
                    "arguments": json.loads(tcall.function.arguments)
                }
            return content, tool_call_dict
        except Exception as e:
            print(f"LLM API Tool Error: {e}")
            return str(e), None
