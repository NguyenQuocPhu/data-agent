import json
import random
from typing import Dict, Any, List
from triadic_dgm.benchmark.interfaces.llm_client import ILLMClient
from triadic_dgm.benchmark.core.evolution_hyperparams import HYPERPARAMS

class ProposerAgent:
    """
    Proposer Agent in the Triadic DGM architecture.
    Responsible for analyzing the question, dataset context, and generating a conceptual plan.
    Does NOT write code.
    """

    def __init__(self, llm_client: ILLMClient):
        # [SOLID] Dependency Injection: Tiêm LLM Client từ ngoài vào
        self.llm_client = llm_client
        self.history_concepts = [] # Lưu lại các concept đã dùng để làm Vocab Dropout

    def _apply_vocab_dropout(self) -> str:
        """
        [SOTA] Triển khai cơ chế Vocabulary Dropout (VD) để chống "AI lười biếng".
        Trích xuất ngẫu nhiên các phương pháp cũ và cấm LLM sử dụng lại chúng
        để ép Proposer phải sáng tạo ra hướng đi (curriculum) mới.
        """
        dropout_rate = HYPERPARAMS.vocab_dropout_rate
        
        if not self.history_concepts or random.random() > dropout_rate:
            return ""
            
        # Lấy ngẫu nhiên một số concept/từ vựng cũ để cấm
        banned_words = random.sample(self.history_concepts, max(1, int(len(self.history_concepts) * dropout_rate)))
        return f"\n[VOCAB DROPOUT CONSTRAINT]: You are STRICTLY FORBIDDEN from using the following approaches or keywords in your plan: {', '.join(banned_words)}. Find an alternative analytical perspective."

    def propose_plan(self, task_description: str, context_graph: str) -> Dict[str, Any]:
        """
        Nhận đề bài và Đồ thị tri thức (từ Understand-Anything), phân tích và 
        lập kế hoạch khái niệm (Conceptual Plan) giao cho Solver.
        """
        
        # Kích hoạt Vocab Dropout từ bộ gen tiến hóa
        dropout_constraint = self._apply_vocab_dropout()

        system_prompt = (
            "You are the Proposer Agent in a Triadic AI System.\n"
            "Your sole responsibility is to analyze the data problem and formulate a step-by-step conceptual plan.\n"
            "CRITICAL RULE: YOU MUST NOT WRITE ANY PYTHON OR EXECUTABLE CODE. Leave coding to the Solver Agent.\n"
            "CRITICAL RULE: If the task involves Exploratory Data Analysis (EDA), you MUST include data visualization (charts) in your transformation or statistical model logic.\n"
            "Output your response STRICTLY as a JSON object with the following schema:\n"
            "{\n"
            "  \"conceptual_variables\": [\"list of independent/dependent variables\"],\n"
            "  \"transformation_logic\": \"Step-by-step natural language logic to clean/transform the data\",\n"
            "  \"statistical_model_logic\": \"The mathematical/statistical approach to solve the problem\"\n"
            "}\n"
            "Do NOT wrap the JSON in markdown blocks (```json). Do NOT use trailing commas. Output ONLY the raw JSON.\n"
            f"{dropout_constraint}"
        )

        user_prompt = (
            f"Task Description:\n{task_description}\n\n"
            f"Knowledge Graph Context (Dataset structures & constraints):\n{context_graph}\n\n"
            "Please generate the conceptual plan."
        )

        # Gọi qua interface, không phụ thuộc vào LLM cụ thể (Claude hay Qwen)
        for attempt in range(3):
            response_text = self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.4 # Đủ thấp để JSON không bị hỏng, nhưng vẫn có chút sáng tạo
            )

            try:
                import re
                # Clean up response to ensure JSON loads correctly
                clean_response = re.sub(r'```json\n?', '', response_text)
                clean_response = re.sub(r'```\n?', '', clean_response)
                # Ép kiểu và bóc tách JSON
                start_idx = clean_response.find('{')
                end_idx = clean_response.rfind('}') + 1
                if start_idx != -1 and end_idx != 0:
                    json_str = clean_response[start_idx:end_idx]
                    # Fix trailing commas
                    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                    plan_dict = json.loads(json_str)
                    
                    # Cập nhật lịch sử để dùng cho Vocab Dropout các vòng sau
                    if isinstance(plan_dict.get("conceptual_variables"), list):
                        self.history_concepts.extend(plan_dict.get("conceptual_variables", []))
                    
                    return plan_dict
                else:
                    raise ValueError("No JSON object found in response.")
            except Exception as e:
                print(f"[PROPOSER] JSON parse error on attempt {attempt+1}: {e}. RAW: {response_text[:200]}...")
                if attempt == 2:
                    return {
                        "error": f"Failed to parse Proposer output: {str(e)}",
                        "raw_response": response_text
                    }
