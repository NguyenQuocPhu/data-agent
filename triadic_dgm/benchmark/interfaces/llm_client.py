from abc import ABC, abstractmethod
from typing import Optional


class ILLMClient(ABC):
    """
    Interface for LLM Clients to decouple the agent logic from the specific LLM API (OpenAI, Claude, Groq, etc.).
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 4096,
        stop_sequences: Optional[list[str]] = None
    ) -> str:
        """
        Generates a response from the language model.
        
        Args:
            prompt: The user prompt.
            system_prompt: The system prompt (context/instructions).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            stop_sequences: Optional list of stop sequences.
            
        """
        pass

    @abstractmethod
    def generate_with_tools(
        self,
        messages: list,
        system_prompt: str,
        tools: list,
        temperature: float = 0.2,
        max_tokens: int = 4096
    ) -> tuple[str, Optional[dict]]:
        """
        Generates a response from the language model, potentially calling a tool.
        
        Args:
            messages: The list of message dictionaries (history).
            system_prompt: The system prompt (context/instructions).
            tools: List of tool schemas.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            
        Returns:
            A tuple (response_content, tool_call_dict).
        """
        pass
