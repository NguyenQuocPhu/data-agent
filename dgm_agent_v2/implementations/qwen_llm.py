import os
from typing import Optional

try:
    import openai
except ImportError:
    openai = None

from dgm_agent_v2.interfaces.llm_client import ILLMClient


class OpenAICompatibleClient(ILLMClient):
    """
    Implementation of ILLMClient for OpenAI-compatible APIs (including Qwen via Proxy, GPT-4o, DeepSeek).
    """

    def __init__(self, api_key: str = "", base_url: str = "", model_name: str = "hosted_vllm/Qwen/Qwen3.5-35B-A3B-FP8"):
        if "hosted_vllm" in model_name or not base_url or base_url == "EMPTY":
            try:
                from dotenv import load_dotenv
                # Try to load .env from the workspace root (parent of dgm_agent_v2)
                env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
                load_dotenv(env_path)
            except ImportError:
                pass
                
            default_url = "https://proxy.onebot.meobeo.ai/v1"
            try:
                import yaml
                config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.yaml")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                base_url = config.get("base_url_conv_model", default_url)
                api_key_env = config.get("api_key_env_var", "QWEN_API_KEY")
            except Exception:
                base_url = default_url
                api_key_env = "QWEN_API_KEY"
            api_key = os.environ.get(api_key_env) or os.environ.get("OPENAI_API_KEY", "EMPTY")
        
        self.api_key = api_key or "EMPTY"
        self.base_url = base_url
        self.model_name = model_name
        
        if openai is None:
            raise ImportError("The 'openai' package is required to use OpenAICompatibleClient.")
            
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=45.0)

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        stop_sequences: Optional[list[str]] = None
    ) -> str:
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        print("\n" + "="*30 + " 🧠 LLM INPUT " + "="*30)
        if system_prompt:
            print(f"[SYSTEM]:\n{system_prompt}\n")
        print(f"[USER]:\n{prompt}")
        print("="*74 + "\n")
        
        import time
        # Pacing: Đợi 3 giây trước mỗi request để tránh Rate Limit của proxy server (RPM limits)
        time.sleep(3)
        
        max_retries = 10 # Tăng số lần thử lại lên 10 vì proxy thường xuyên rớt
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stop=stop_sequences,
                    extra_body={"cache":{"no-cache":True},"chat_template_kwargs":{"enable_thinking":True},"timeout":60}

                )
                
                choice = response.choices[0]
                content = choice.message.content or ""
                finish_reason = getattr(choice, "finish_reason", "stop")
                
                if not content.strip():
                    raise ValueError("Empty response from LLM")
                if finish_reason == "length":
                    raise ValueError("Response truncated due to length")
                    
                print("\n" + "="*30 + " 🤖 LLM OUTPUT " + "="*30)
                print(content)
                print("="*75 + "\n")
                return content
            except Exception as e:
                err_msg = str(e).lower()
                if "429" in err_msg or "rate limit" in err_msg or "too many requests" in err_msg or "empty response" in err_msg or "timeout" in err_msg:
                    wait_time = 5 * (attempt + 1)
                    print(f"LLM API Error / Drop: Waiting {wait_time}s before retry {attempt+1}/{max_retries}... ({e})")
                    time.sleep(wait_time)
                else:
                    print(f"LLM API Error (Attempt {attempt+1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        return ""
                    time.sleep(2)
        return ""

    def generate_with_tools(
        self,
        messages: list,
        system_prompt: str,
        tools: list,
        temperature: float = 0.2,
        max_tokens: int = 8192
    ) -> tuple[str, Optional[dict]]:
        
        req_messages = []
        if system_prompt:
            req_messages.append({"role": "system", "content": system_prompt})
        req_messages.extend(messages)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
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
                tool_call_dict = {
                    "name": tcall.function.name,
                    "arguments": json.loads(tcall.function.arguments)
                }
            return content, tool_call_dict
        except Exception as e:
            print(f"LLM API Tool Error: {e}")
            return str(e), None
