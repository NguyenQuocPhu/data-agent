import re
from typing import List, Dict, Any
from dgm_agent_v2.interfaces.llm_client import ILLMClient
from dgm_agent_v2.core.rimrule_memory import RimruleMemoryBank

class SolverAgent:
    """
    Solver Agent in the Triadic DGM architecture.
    Responsible for generating actual code based on the Proposer's plan 
    and avoiding past mistakes using context from the RIMRULE Memory Bank.
    """

    def __init__(self, llm_client: ILLMClient, memory_bank: RimruleMemoryBank):
        # [SOLID] Dependency Injection: Tiêm LLM Client và Memory Bank
        self.llm_client = llm_client
        self.memory_bank = memory_bank

    def solve(self, task_description: str, proposer_plan: Dict[str, Any], domain: str = "python", num_candidates: int = 3) -> List[str]:
        """
        [SOTA] Sinh mã đa ứng viên (Multiple Candidates Generation).
        Nhận kế hoạch từ Proposer, truy vấn RIMRULE, và trả về danh sách các code Python.
        """
        
        # 1. Truy xuất luật từ RIMRULE (Cross-lingual Memory)
        # Nếu domain là python, nó sẽ lấy các luật chống lỗi Python đã được nén bằng MDL
        rules_context = self.memory_bank.retrieve_rules_symbolic(query_domain=domain, top_k=3)

        # 2. Bóc tách kế hoạch của Proposer
        concept_vars = proposer_plan.get("conceptual_variables", [])
        transform_logic = proposer_plan.get("transformation_logic", "")
        model_logic = proposer_plan.get("statistical_model_logic", "")

        # 3. Xây dựng System Prompt (Ép khuôn theo chuẩn BLADE / Data Science)
        system_prompt = (
            "You are the elite Solver Agent in a Triadic AI System.\n"
            "Your task is to write highly optimized, executable code based strictly on the Proposer's conceptual plan.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Implement exactly what the plan describes: data transformation and the statistical model.\n"
            "2. Ensure the code is self-contained and imports all necessary libraries.\n"
            "3. Output ONLY the raw code enclosed within standard markdown blocks (e.g. ```python). Do not add any conversational text.\n"
            "4. If the task involves Exploratory Data Analysis (EDA) or data overview, you MUST proactively write code to generate charts (e.g. distributions, correlations) using matplotlib/seaborn and call `plt.show()`.\n"
            "5. DO NOT write any code comments. DO NOT explain your logic inside the code.\n\n"
            f"{rules_context}"
        )

        # 4. Xây dựng User Prompt
        user_prompt = (
            f"Original Task:\n{task_description}\n\n"
            "Proposer's Execution Plan:\n"
            f"- Conceptual Variables: {', '.join(concept_vars)}\n"
            f"- Transformation Logic: {transform_logic}\n"
            f"- Statistical Model Logic: {model_logic}\n\n"
            "Please write the complete code to execute this plan."
        )

        # 5. Vòng lặp sinh đa ứng viên (Tránh kẹt ở Local Optima)
        candidate_codes = []
        for attempt in range(num_candidates):
            response_text = self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2 + (attempt * 0.1) # Tăng nhẹ nhiệt độ qua mỗi candidate để tạo độ đa dạng, giữ mức thấp để code chính xác
            )
            
            clean_code = self._extract_code(response_text)
            if clean_code and clean_code not in candidate_codes:
                candidate_codes.append(clean_code)

        # Trả về danh sách code để Verifier/Sandbox chấm điểm
        return candidate_codes if candidate_codes else ["# Failed to generate valid code"]

    def _extract_code(self, text: str) -> str:
        """Extracts code blocks from LLM response safely."""
        if not text:
            return ""
        # Bắt mọi code block không phân biệt ngôn ngữ, dùng \s* để xử lý \r\n
        match = re.search(r"```[a-zA-Z]*\s*(.*?)\s*```", text, re.DOTALL)
        return match.group(1).strip() if match else text.strip()
        
        # Fallback nếu LLM quên sinh markdown block
        return text.strip()
