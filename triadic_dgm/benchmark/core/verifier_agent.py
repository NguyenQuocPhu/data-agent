import zlib
from typing import Tuple, List, Dict, Any, Optional
from triadic_dgm.benchmark.interfaces.llm_client import ILLMClient
from triadic_dgm.memory.rimrule_memory import RimruleMemoryBank
from triadic_dgm.benchmark.core.evolution_hyperparams import HYPERPARAMS

class VerifierAgent:
    """
    Verifier Agent in the Triadic DGM architecture.
    Responsible for validating execution output, calculating Epiplexity (Goldilocks filter), 
    and generating debug feedback for the Solver.
    """

    def __init__(self, llm_client: ILLMClient, memory_bank: RimruleMemoryBank):
        # [SOLID] Dependency Injection
        self.llm_client = llm_client
        self.memory_bank = memory_bank

    def _compute_epiplexity(self, task_description: str, generated_code: str) -> float:
        """
        [SOTA] Toán học Epiplexity dựa trên Normalized Compression Distance (NCD) [1].
        Đo lường khoảng cách thông tin giữa Bài toán (x) và Giải pháp (y).
        """
        x_bytes = task_description.encode('utf-8')
        y_bytes = generated_code.encode('utf-8')
        xy_bytes = (task_description + "\n" + generated_code).encode('utf-8')
        
        c_x = len(zlib.compress(x_bytes))
        c_y = len(zlib.compress(y_bytes))
        c_xy = len(zlib.compress(xy_bytes))
        
        # Công thức NCD = (C(xy) - min(C(x), C(y))) / max(C(x), C(y)) [1]
        ncd = (c_xy - min(c_x, c_y)) / max(c_x, c_y)
        
        # Hệ số scaling 2.0 theo cấu hình thực nghiệm trên Polyglot [1]
        return 2.0 * ncd

    def _generate_reflexion_feedback(self, code: str, error_log: str, task_description: str) -> str:
        """
        Dùng LLM làm Surrogate Evaluator để sinh ra gợi ý sửa lỗi (Reflexion) cho Solver.
        """
        system_prompt = (
            "You are a strict QA Engineer and Code Reviewer. "
            "Analyze the faulty code and the execution error log based on the original task. "
            "Provide a concise, actionable instruction on how to fix the error. "
            "CRITICAL RULE: Quy tắc phải mang tính tổng quát (generalizable) và có thể áp dụng cho các bài toán khác, "
            "KHÔNG được ghi cứng (hardcode) tên biến hay số dòng. "
            "Ví dụ: Thay vì 'Sửa dòng 45 thành df.fillna(0)', hãy viết: 'Khi tính toán tỷ lệ, bắt buộc phải xử lý dữ liệu NaN bằng cách fillna(0) trước khi chia'. "
            "Do NOT write the code yourself, just give the generalized logical steps to avoid the error."
        )
        user_prompt = f"Original Task:\n{task_description}\n\nCode:\n```python\n{code}\n```\n\nError Log:\n{error_log}\n\nPlease analyze and provide generalized fix instructions."
        
        feedback = self.llm_client.generate(prompt=user_prompt, system_prompt=system_prompt, temperature=0.2)
        
        # [SOTA] Tự động nạp kinh nghiệm (Running Prompt) vào RIMRULE Memory Bank
        from triadic_dgm.memory.rimrule_memory import Rule
        new_rule = Rule(
            nl_rule=feedback,
            domain="python",
            qualifier=["runtime_error"],
            action=["fix_logic"],
            strength="MUST",
            tool_category="coding"
        )
        self.memory_bank.add_or_consolidate_rule(new_rule)
        
        return feedback

    def verify_candidates(self, task_description: str, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Đánh giá các ứng viên từ Solver qua 2 chiều: Runtime Validity và Epiplexity.
        candidates: List of dicts, e.g., [{"code": "...", "is_success": True/False, "error_log": "..."}]
        """
        best_candidate = None
        highest_epi = -1.0
        feedback_for_solver = ""
        
        # Cập nhật ngưỡng Goldilocks từ Gen tiến hóa hiện tại
        epi_min = HYPERPARAMS.epiplexity_min
        epi_max = HYPERPARAMS.epiplexity_max

        for cand in candidates:
            code = cand["code"]
            runtime_pass = cand["is_success"]
            error_log = cand.get("error_log", "")
            
            # Chiều 2: Tính điểm Epiplexity
            epi_score = self._compute_epiplexity(task_description, code)
            is_goldilocks = epi_min <= epi_score <= epi_max
            
            cand["epiplexity_score"] = epi_score
            cand["goldilocks_status"] = "PASS" if is_goldilocks else "FAIL"

            # [RIMRULE TRIGGER] Hardcode đánh trượt bằng Python
            import re
            sil_matches = re.findall(r'(?i)silhouette.*?([0-9]*\.[0-9]+)', cand.get("output", error_log))
            if sil_matches:
                try:
                    sil_score = float(sil_matches[-1])
                    if sil_score < 0.15:
                        runtime_pass = False
                        is_goldilocks = True  # force it into "Reject + Reflexion"
                        error_log = f"Cấu trúc dữ liệu không có tính phân cụm (Silhouette {sil_score} < 0.15). Dừng việc tạo Persona giả."
                except ValueError:
                    pass

            # Phân loại theo 4 Quadrants (Table I) [1]
            if runtime_pass and is_goldilocks:
                cand["decision"] = "Archive" # Tình huống A: Tuyệt hảo!
                # Cập nhật best candidate dựa trên Epiplexity cao nhất (vẫn trong khoảng Goldilocks)
                if epi_score > highest_epi:
                    highest_epi = epi_score
                    best_candidate = cand
                    
            elif runtime_pass and not is_goldilocks:
                cand["decision"] = "Reject (Trivial/Over-complex)" # Tình huống B
                
            elif not runtime_pass and is_goldilocks:
                cand["decision"] = "Reject + Reflexion" # Tình huống C: Code lỗi nhưng ý tưởng tốt
                # Lấy feedback để Solver sửa ở vòng sau
                if not feedback_for_solver: 
                    feedback_for_solver = self._generate_reflexion_feedback(code, error_log, task_description)
                    
            else:
                cand["decision"] = "Discard" # Tình huống D: Vừa lỗi vừa vớ vẩn

        # Kết quả trả về cho Orchestrator
        return {
            "best_valid_solution": best_candidate, # Có thể là None nếu không có ứng viên nào đạt Tình huống A
            "reflexion_feedback": feedback_for_solver, # Gợi ý sửa lỗi nếu rơi vào Tình huống C
            "all_evaluations": candidates
        }
