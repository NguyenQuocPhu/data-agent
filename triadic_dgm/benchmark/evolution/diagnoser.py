import json
from typing import Dict, Any
from triadic_dgm.benchmark.interfaces.llm_client import ILLMClient

class Diagnoser:
    """
    [SOTA] Meta-Reflection module (Outer Loop).
    Analyzes the execution logs and test results of a failed/sub-optimal generation
    to automatically propose a 'mutation_goal' (Textual Gradients) for the next evolutionary step.
    Replaces self_improvement_prompt.py from V1.
    """
    def __init__(self, llm_client: ILLMClient):
        # [SOLID] Dependency Injection
        self.llm_client = llm_client

    def diagnose(self, code: str, error_log: str) -> Dict[str, Any]:
        """
        Thực thi toán tử Diagnose (δ).
        Phân tích mã nguồn và log lỗi từ Real Compiler để sinh ra bản thiết kế tiến hóa.
        """
        # Áp dụng chính xác schema chẩn đoán từ bài báo Darwin Gödel Machine và TPGO
        system_prompt = (
            "You are an expert Meta-Reasoning AI diagnosing a coding agent's failure.\n"
            "Your task is to analyze the agent's code and its execution error log, then "
            "identify ONE detailed plan that would improve the agent's general coding ability.\n\n"
            "Respond precisely in the following JSON format:\n"
            "{\n"
            "  \"log_summarization\": \"Analyze the logs and summarize how the agent tried to solve the task and what failed.\",\n"
            "  \"potential_improvements\": \"List potential improvements to the agent's general logic or tools.\",\n"
            "  \"improvement_proposal\": \"Choose ONE high-impact improvement and describe it in detail.\",\n"
            "  \"implementation_suggestion\": \"Describe exactly how to modify the existing Python code to implement this.\",\n"
            "  \"textual_gradient\": \"A short abstract failure pattern (Negative Gradient δ-) that the agent should avoid in the future.\"\n"
            "}"
        )

        user_prompt = (
            f"=== Agent's Current Code ===\n```python\n{code}\n```\n\n"
            f"=== Execution Error Log ===\n{error_log}\n\n"
            "Provide the detailed JSON diagnosis."
        )

        # Sử dụng temperature thấp (0.4) để đảm bảo tính phân tích logic, tránh ảo giác
        response_text = self.llm_client.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.4 
        )

        return self._parse_json_response(response_text)

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Trích xuất và ép kiểu JSON an toàn từ phản hồi của LLM."""
        try:
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            if start_idx != -1 and end_idx != 0:
                json_str = text[start_idx:end_idx]
                return json.loads(json_str)
            return {"error": "No JSON block found in response.", "raw_response": text}
        except json.JSONDecodeError as e:
            return {"error": f"JSON parsing failed: {str(e)}", "raw_response": text}
