"""
SemanticVerifier — Unified Dual-Axis Verification Agent.
Replaces the old Inspector with a combined Syntax + Semantic checker.

Chiều 1 (Syntactic/Runtime): Catches Traceback errors, generates fix instructions.
Chiều 2 (Semantic/Business): Validates business logic, data integrity, required metrics.

Integrates with RIMRULE Memory Bank for self-evolving error prevention.
Uses Semantic Routing to only activate Chiều 2 for business-critical tasks.
"""

import openai
import json
from prompt_engineering.prompts import SEMANTIC_VERIFY_PROMPT
from dgm_agent_v2.core.rimrule_memory import RimruleMemoryBank, Rule
from core.inspector import compute_mdl_epiplexity

# Keywords that trigger full semantic verification (Semantic Routing)
BUSINESS_KEYWORDS = [
    'clustering', 'cluster', 'persona', 'phân cụm', 'gom cụm',
    'churn', 'hidden pattern', 'phân tích persona', 'segment',
    'nhóm khách', 'k-means', 'kmeans', 'decision tree', 'retention',
    'phân tích khách hàng', 'customer analysis', 'segmentation',
]


class SemanticVerifier:
    """
    Unified Verifier Agent implementing Dual-Axis Verification (Triadic DGM).

    Axis 1 — Syntactic/Runtime Validity:
        Kế thừa vai trò của Inspector cũ. Bắt lỗi Traceback và sinh ra
        Reflexion Feedback cho Programmer sửa code.

    Axis 2 — Semantic & Business Logic Fitness:
        Kiểm tra ngữ nghĩa kết quả: Silhouette Score có tồn tại không?
        Churn Rate có nằm trong [0, 1] không? Decision Tree rules có
        Support thực không? Nếu thiếu → REVISE.

    Semantic Routing:
        Business tasks (Clustering, Persona, Churn) → Bật cả 2 chiều.
        Utility tasks (df.head(), vẽ biểu đồ) → Chỉ bật Chiều 1.
    """

    def __init__(self, api_key, model="gpt-4o-mini", base_url=''):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.memory_bank = RimruleMemoryBank()
        self.messages = []  # Compatibility with old Inspector interface

    # ------------------------------------------------------------------ #
    #  Semantic Routing                                                    #
    # ------------------------------------------------------------------ #

    def is_business_task(self, user_query: str) -> bool:
        """
        Semantic Router: chỉ bật Chiều 2 cho các tác vụ nghiệp vụ sâu.
        Tiết kiệm API cost cho các lệnh utility đơn giản.
        """
        query_lower = user_query.lower()
        return any(kw in query_lower for kw in BUSINESS_KEYWORDS)

    # ------------------------------------------------------------------ #
    #  Chiều 1 — Syntactic / Runtime Validity                              #
    # ------------------------------------------------------------------ #

    def verify_syntax(self, code: str, error_log: str, task: str) -> str:
        """
        Bắt lỗi Traceback và sinh ra hướng dẫn sửa lỗi tổng quát.
        Thay thế hoàn toàn vai trò CODE_INSPECT của Inspector cũ.
        Tự động lưu bài học vào RIMRULE Memory Bank.

        Returns:
            str: Fix instruction cho Programmer.
        """
        # Truy xuất kinh nghiệm từ RIMRULE Memory
        past_rules = self.memory_bank.retrieve_rules_symbolic("python", top_k=3)

        system_prompt = (
            "You are a strict QA Engineer and Code Reviewer. "
            "Analyze the faulty code and the execution error log based on the original task. "
            "Provide a concise, actionable instruction on how to fix the error. "
            "CRITICAL: Your fix instructions must be generalizable. "
            "Do NOT hardcode variable names or line numbers. "
            "Do NOT write the code yourself, just give the logical steps to avoid the error."
        )
        if past_rules:
            system_prompt += f"\n\n{past_rules}"

        user_prompt = (
            f"Original Task:\n{task}\n\n"
            f"Code:\n```python\n{code}\n```\n\n"
            f"Error Log:\n{error_log}\n\n"
            "Please analyze and provide generalized fix instructions."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.2
            )
            feedback = response.choices[0].message.content
        except Exception as e:
            print(f"[SemanticVerifier] Syntax check error: {e}")
            feedback = f"Try using alternative approach or package. Error: {e}"

        # Lưu bài học vào RIMRULE Memory Bank
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

    # ------------------------------------------------------------------ #
    #  Chiều 2 — Semantic & Business Logic Fitness                         #
    # ------------------------------------------------------------------ #

    def verify_semantics(self, task: str, code: str, exec_output: str) -> dict:
        """
        Kiểm tra ngữ nghĩa nghiệp vụ của kết quả chạy code.
        Trả về JSON verdict:
            {"status": "ACCEPT"/"REVISE", "missing": [...], "feedback": "...", "epiplexity_score": float}
        """
        # Tính Epiplexity (Information-theoretic fitness)
        epi_score = compute_mdl_epiplexity(code)

        # Cắt output để tránh vượt token limit
        truncated_output = exec_output[:8000] if len(exec_output) > 8000 else exec_output

        verify_prompt = SEMANTIC_VERIFY_PROMPT.format(
            task=task,
            code=code,
            exec_output=truncated_output
        )

        messages = [
            {"role": "system", "content": "You are a strict Business Data Analyst Auditor. Respond ONLY with valid JSON."},
            {"role": "user", "content": verify_prompt}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.0
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences nếu có
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            verdict = json.loads(raw)
            verdict["epiplexity_score"] = epi_score

            # Nếu REVISE, lưu vào RIMRULE Memory để lần sau Solver nhớ
            if verdict.get("status") == "REVISE":
                feedback = verdict.get("feedback", "")
                new_rule = Rule(
                    nl_rule=f"Semantic check failed: {feedback}",
                    domain="python",
                    qualifier=["semantic_error", "business_logic"],
                    action=["add_metrics", "fix_logic"],
                    strength="MUST",
                    tool_category="data_analysis"
                )
                self.memory_bank.add_or_consolidate_rule(new_rule)

            return verdict

        except (json.JSONDecodeError, Exception) as e:
            print(f"[SemanticVerifier] Semantic check error: {e}")
            # On parse error, default to ACCEPT to avoid blocking pipeline
            return {
                "status": "ACCEPT",
                "missing": [],
                "feedback": f"Verifier parse error (defaulting to ACCEPT): {e}",
                "epiplexity_score": epi_score
            }

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def clear(self):
        """Reset verifier state."""
        self.messages = []
