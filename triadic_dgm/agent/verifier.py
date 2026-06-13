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
from triadic_dgm.prompts.prompts import SEMANTIC_VERIFY_PROMPT
from triadic_dgm.memory.rimrule_memory import RimruleMemoryBank, Rule
from triadic_dgm.agent.inspector import compute_mdl_epiplexity

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

        verdict = {
            "status": "ACCEPT",
            "missing": [],
            "feedback": "",
            "epiplexity_score": epi_score
        }

        verdict_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "semantic_verification_verdict",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["ACCEPT", "REVISE"]
                        },
                        "missing": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "feedback": {
                            "type": "string"
                        }
                    },
                    "required": ["status", "missing", "feedback"],
                    "additionalProperties": False
                }
            }
        }

        try:
            response = self.client.chat.completions.create(
                model=self.model, 
                messages=messages, 
                temperature=0.0,
                response_format=verdict_schema
            )
            raw = response.choices[0].message.content.strip()

            llm_verdict = json.loads(raw)
            if "status" in llm_verdict: verdict["status"] = llm_verdict["status"]
            if "missing" in llm_verdict: verdict["missing"] = llm_verdict["missing"]
            if "feedback" in llm_verdict: verdict["feedback"] = llm_verdict["feedback"]
        except Exception as e:
            print(f"[SemanticVerifier] Semantic check LLM error: {e}")
            verdict["feedback"] = f"Verifier LLM error (defaulting to ACCEPT): {e}"

        # [RIMRULE TRIGGER] Hardcode đánh trượt bằng Python
        import re
        
        # Rule 1: Silhouette < 0.2
        sil_matches = re.findall(r'(?i)silhouette.*?([0-9]*\.[0-9]+)', exec_output)
        if sil_matches:
            try:
                sil_score = float(sil_matches[-1])
                if sil_score < 0.2:
                    verdict["status"] = "REVISE"
                    verdict["feedback"] = f"⚠ Persona quality too low. Silhouette {sil_score} < 0.2. Không đủ bằng chứng thống kê để tạo persona đáng tin cậy. Dừng việc tạo Persona giả."
            except ValueError:
                pass

        # Rule 2: Target Leakage Check
        if "RMDT" in code and ("KMeans" in code or "clustering" in code or "TfidfVectorizer" in code):
            if re.search(r'(?i)(features|cols|columns)\s*=\s*\[[^\]]*\'RMDT\'[^\]]*\]', code) or \
               (re.search(r'KMeans', code) and not re.search(r'drop\([^\)]*RMDT', code) and not re.search(r'features\s*=', code)):
                verdict["status"] = "REVISE"
                verdict["feedback"] = "⚠ Data Leakage: Biến mục tiêu `RMDT` đang được dùng làm feature cho thuật toán phân cụm. BẮT BUỘC phải drop `RMDT` khỏi tập dữ liệu huấn luyện KMeans!"

        # Rule 2.5: Geography Dominance Check
        if "khu_vuc" in code and "KMeans" in code:
            if re.search(r'(?i)(feature_cols|cols_for_clustering|behavior_cols|cat_cols_to_use)\s*=[^\]\n]*\'khu_vuc\'', code):
                verdict["status"] = "REVISE"
                verdict["feedback"] = "⚠ Geography Dominance: KHÔNG được dùng `khu_vuc`, `goi_cuoc` hoặc `ma_su_co_pho_bien` làm input features cho KMeans. Điều này khiến cụm bị chia hoàn toàn theo địa lý. CHỈ dùng các biến hành vi (rớt mạng, CSKH, suy hao, thang_su_dung) và text TF-IDF để train KMeans!"

        # Rule 3 & 4 & 5 & 6: JSON Validation & Support & Scale & Unique
        if "KMeans" in code or "TfidfVectorizer" in code:
            json_matches = re.findall(r'\[\s*\{.*?\}\s*\]', exec_output, re.DOTALL)
            has_valid_json = False
            for match in json_matches:
                try:
                    data_arr = json.loads(match)
                    if isinstance(data_arr, list) and len(data_arr) > 0 and "persona_name" in data_arr[0]:
                        has_valid_json = True
                        # Business Diversity K-Score
                        k_scores = {}
                        for m in re.finditer(r"K=(\d+).*?Silhouette=([0-9.]+)", exec_output, re.IGNORECASE):
                            k_scores[int(m.group(1))] = float(m.group(2))
                        
                        total_support = sum(c.get("support", 0) for c in data_arr)
                        
                        if len(data_arr) < 3:
                            verdict["status"] = "REVISE"
                            verdict["feedback"] = "⚠ Lỗi nghiệp vụ (Business Logic Error): Số lượng cụm (K) phải >= 3. K=2 là quá ít để phân tách rủi ro (Low, Medium, High). BẮT BUỘC thử K từ 3 đến 6 và chọn K >= 3."

                        if total_support > 0:
                            overall_churn = sum(c.get("churn_rate", 0) * c.get("support", 0) for c in data_arr) / total_support
                        else:
                            overall_churn = 0.0
                            
                        churn_rates = [c.get("churn_rate", 0) for c in data_arr]
                        if churn_rates and max(churn_rates) < 0.001:
                            verdict["status"] = "REVISE"
                            verdict["feedback"] = "⚠ Lỗi Toán Học: Churn Rate của TẤT CẢ các cụm đều < 0.1% (0.001). Bạn đang tính sai công thức. Churn Rate phải là `mean(RMDT)` của từng cụm, KHÔNG PHẢI `sum(RMDT) / len(data)`."
                        
                        if churn_rates and max(churn_rates) - min(churn_rates) < 0.05:
                            verdict["status"] = "REVISE"
                            verdict["feedback"] = f"⚠ Churn Variance Error: Chênh lệch Churn Rate giữa các cụm ({max(churn_rates):.2f} vs {min(churn_rates):.2f}) < 5%. Các cụm này không phân tách được rủi ro rời mạng. BẮT BUỘC phải tăng K hoặc thay đổi features để nhóm rủi ro phân tách rõ rệt hơn!"
                            
                        persona_names = []
                        for cluster in data_arr:
                            pct = cluster.get("support_pct", 1.0)
                            arpu = cluster.get("arpu", 0)
                            churn = cluster.get("churn_rate", 0)
                            p_name = cluster.get("persona_name", "")
                            sample_text = cluster.get("sample_persona_text", "").lower()
                            
                            # RULE_PERSONA_NAME Numeric Check
                            if re.match(r"^(cluster_)?\d+$", p_name, re.IGNORECASE) or len(p_name) < 5 or "đặc điểm" in p_name.lower() or "0.0" in p_name:
                                verdict["status"] = "REVISE"
                                verdict["feedback"] = f"⚠ Lỗi nghiệp vụ: Tên Persona '{p_name}' quá ngắn, là số đếm, hoặc chứa các cụm vô nghĩa (như 'đặc điểm 0.0'). Bạn PHẢI đặt tên có Semantic Meaning dựa trên hành vi (VD: 'Khách mới ổn định', 'KH hay gặp sự cố', 'KH hài lòng nhưng rủi ro cao')."

                            if pct < 0.05:
                                verdict["status"] = "REVISE"
                                verdict["feedback"] = f"⚠ Support quá thấp ({pct*100}% < 5%). Cụm '{p_name}' không mang ý nghĩa thống kê."
                            elif pct > 1.0 or churn > 1.0:
                                verdict["status"] = "REVISE"
                                verdict["feedback"] = "⚠ Lỗi định dạng: support_pct và churn_rate phải là tỷ lệ dạng số thực trong khoảng [0.0, 1.0]. Hãy đảm bảo bạn không nhầm với phần trăm (0-100)."
                            
                            if arpu > 0 and arpu < 50000:
                                verdict["status"] = "REVISE"
                                verdict["feedback"] = f"⚠ Lỗi Kế Toán: ARPU của cụm '{p_name}' quá thấp ({arpu} VND < 50,000 VND). ARPU phải được tính bằng `mean(cuoc_hang_thang)` của cụm đó, TUYỆT ĐỐI KHÔNG chia cho 30."
                                
                            if any(word in p_name.lower() for word in ["nguy cơ", "rời mạng", "rủi ro", "kém"]):
                                if churn <= overall_churn and churn < 0.05:
                                    verdict["status"] = "REVISE"
                                    verdict["feedback"] = f"⚠ Mâu thuẫn Logic: Cụm '{p_name}' được gắn nhãn Rủi ro/Nguy cơ nhưng Churn Rate ({churn}) lại thấp. Tên Persona BẮT BUỘC phản ánh đúng tỷ lệ Churn."
                                if not any(kw in sample_text for kw in ["rớt mạng", "cskh", "suy hao"]):
                                    verdict["status"] = "REVISE"
                                    verdict["feedback"] = f"⚠ Mâu thuẫn mô tả: Persona tên là '{p_name}' nhưng mô tả ({sample_text}) không đề cập đến yếu tố rủi ro nào (rớt mạng, cskh, suy hao). Hãy giải thích tại sao họ lại có nguy cơ!"
                            
                            if churn > 0.15 and "loyal" in p_name.lower():
                                verdict["status"] = "REVISE"
                                verdict["feedback"] = f"⚠ Lỗi nghiệp vụ (Business Logic Error): Cụm '{p_name}' có Churn Rate = {churn*100}% (> 15%) nhưng lại chứa từ 'Loyal'. Khách hàng rời mạng cao không thể gọi là Trung Thành!"
                            
                            if p_name:
                                persona_names.append(p_name)
                                
                        if verdict.get("status") != "REVISE" and len(set(persona_names)) < len(persona_names):
                            verdict["status"] = "REVISE"
                            verdict["feedback"] = "⚠ Lỗi nghiệp vụ: Các nhóm Persona đang bị trùng tên. Hãy điều chỉnh luật IF-ELSE để đặt tên phân biệt rõ ràng."
                        break
                except Exception:
                    continue
            
            if not has_valid_json and verdict.get("status") != "REVISE":
                verdict["status"] = "REVISE"
                verdict["feedback"] = "⚠ Không tìm thấy JSON Output hợp lệ cho Persona. BẮT BUỘC phải dùng lệnh print('[JSON_START_PERSONA]'), sau đó print(json.dumps(personas)), và cuối cùng print('[JSON_END_PERSONA]')."

        # Rule 8: Hidden Pattern Actionable Logic (Decision Tree) & Hallucination Check
        if "CHURN PREDICTION RULES:" in exec_output:
            tree_text = exec_output.split("CHURN PREDICTION RULES:")[1].lower()
            if "class: 0" in tree_text and "class: 1" not in tree_text:
                verdict["status"] = "REVISE"
                verdict["feedback"] = "⚠ Actionable Pattern Validator: Decision Tree không tìm được pattern nào cho class: 1 (Churn). Thuật toán đã thất bại trong việc phân loại rời mạng. YÊU CẦU: Không được bịa đặt insights từ cây quyết định rỗng này!"
                
            allowed_concepts = {
                "so_lan_rot_mang": ["rớt mạng", "mạng rớt", "network drop", "mất kết nối"],
                "so_lan_goi_cskh": ["cskh", "support", "tổng đài", "chăm sóc khách hàng", "hỗ trợ"],
                "do_suy_hao_quang": ["suy hao", "cáp quang", "tín hiệu", "chất lượng kém", "đường truyền"]
            }
            insight_text = exec_output.lower()
            code_lower = code.lower()
            for feature, keywords in allowed_concepts.items():
                if feature not in tree_text and feature not in code_lower:
                    for kw in keywords:
                        if kw in insight_text:
                            verdict["status"] = "REVISE"
                            verdict["feedback"] = f"⚠ Ảo giác diễn giải (Business Hallucination): Bạn kết luận về '{kw}' nhưng feature `{feature}` lại không được dùng trong mô hình. Hãy dựa hoàn toàn vào dữ liệu có thật!"

        # Rule 9: Metadata Integrity
        if "sentiment" in code.lower() or "cảm xúc" in exec_output.lower():
            if "do_suy_hao_quang" in code.lower() or "do_suy_hao_quang" in exec_output.lower():
                verdict["status"] = "REVISE"
                verdict["feedback"] = "⚠ Lỗi Metadata (Metadata Integrity): 'do_suy_hao_quang' là độ suy hao quang học (Optical Attenuation), KHÔNG PHẢI chỉ số cảm xúc (Sentiment). Không được tự chế khái niệm."

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
            # Đẩy rule nén ra để frontend bắt được
            verdict["new_rule"] = new_rule.nl_rule

        return verdict

    # ------------------------------------------------------------------ #
    #  Cleanup                                                             #
    # ------------------------------------------------------------------ #

    def clear(self):
        """Reset verifier state."""
        self.messages = []
