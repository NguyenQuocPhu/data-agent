import math
import json
import logging

def calculate_mdl_score(rule_length: int, total_errors: int, errors_fixed: int, alpha: float = 0.1) -> float:
    """
    Tính điểm nén thông tin MDL (Minimum Description Length) cho một luật sửa lỗi.
    - rule_length: Độ dài của luật tính bằng token/ký tự.
    - total_errors: Tổng số lượng lỗi biên dịch ghi nhận được (n).
    - errors_fixed: Số lượng lỗi mà luật này áp dụng thành công (k_H).
    - alpha: Hệ số phạt độ dài (Càng lớn thì càng ép model phải viết luật thật ngắn gọn).
    """
    if errors_fixed == 0 or total_errors == 0:
        return float('inf')  # Loại bỏ ngay lập tức các luật vô dụng

    # 1. Model Cost L(H): Chi phí lưu trữ luật (Luật càng dài, điểm phạt càng cao)
    L_H = alpha * rule_length

    # 2. Data Cost L(D|H): Chi phí dữ liệu (Càng sửa được nhiều lỗi, điểm càng thấp)
    p_hat = errors_fixed / total_errors
    
    # Tính NLL (Negative Log-Likelihood) bằng Bernoulli likelihood
    if p_hat >= 1.0:
        # Nếu sửa được 100% lỗi
        L_D_H = - (errors_fixed * math.log(p_hat))
    elif p_hat <= 0.0:
        L_D_H = float('inf')
    else:
        # Nếu sửa được một phần
        L_D_H = - (errors_fixed * math.log(p_hat) + (total_errors - errors_fixed) * math.log(1 - p_hat))

    # 3. Điểm MDL tổng (MDL CÀNG THẤP CÀNG TỐT)
    mdl_score = L_H + L_D_H
    return mdl_score


class RuleLibrary:
    """
    Quản lý Thư viện Luật học được từ Reflexion, chấm điểm bằng MDL.
    """
    def __init__(self):
        self.rules = []  # Danh sách các luật: {"rule_text": str, "length": int, "errors_fixed": int, "mdl_score": float}
        self.total_errors_encountered = 0

    def add_error_encountered(self):
        self.total_errors_encountered += 1
        self._update_all_scores()

    def add_or_update_rule(self, rule_text: str):
        """Thêm luật mới (vừa sửa được 1 lỗi) hoặc tăng số lần hữu ích cho luật cũ."""
        # Tránh trùng lặp luật quá giống nhau
        for r in self.rules:
            if rule_text.lower().strip() == r["rule_text"].lower().strip():
                r["errors_fixed"] += 1
                self._update_all_scores()
                return

        length = len(rule_text.split())
        new_rule = {
            "rule_text": rule_text.strip(),
            "length": length,
            "errors_fixed": 1,
            "mdl_score": 0.0
        }
        self.rules.append(new_rule)
        self._update_all_scores()

    def _update_all_scores(self):
        for r in self.rules:
            r["mdl_score"] = calculate_mdl_score(
                rule_length=r["length"], 
                total_errors=self.total_errors_encountered, 
                errors_fixed=r["errors_fixed"]
            )
        # Sắp xếp luật theo điểm MDL từ thấp đến cao (MDL càng thấp càng tốt)
        self.rules.sort(key=lambda x: x["mdl_score"])

    def get_top_rules(self, top_k=5) -> str:
        """Lấy danh sách các luật tốt nhất để tiêm vào Prompt."""
        if not self.rules:
            return ""
        
        best_rules = self.rules[:top_k]
        rule_strings = []
        for r in best_rules:
            try:
                # Try to parse and format if it's JSON
                rule_obj = json.loads(r["rule_text"])
                formatted = f"[{rule_obj.get('Domain', 'General')}] {rule_obj.get('Qualifier', [])} -> {rule_obj.get('Action', [])} (Strength: {rule_obj.get('Strength', 'RECOMMENDED')})"
                rule_strings.append(f"- {formatted} (MDL Score: {r['mdl_score']:.2f})")
            except Exception:
                rule_strings.append(f"- {r['rule_text']} (MDL Score: {r['mdl_score']:.2f})")
                
        return "\n".join(rule_strings)


def extract_rule_from_reflexion(failed_code: str, error_log: str, fixed_code: str, client, model="llama-3.1-8b-instant") -> str:
    """
    Sử dụng LLM để rút trích một luật sửa lỗi ngắn gọn từ quá trình Reflexion thành công.
    """
    system_prompt = (
        "You are an expert rule classification specialist for the RIMRULE system. "
        "Your task is to analyze a failed code snippet, its error log, and the successful fixed code, "
        "and distill a single, highly generalizable rule (heuristic) to prevent this error in the future.\n\n"
        "Guidelines:\n"
        "- The rule must be represented as a JSON object with exactly 5 fields:\n"
        "  1. \"Domain\": The programming language (e.g., \"Go\", \"Python\").\n"
        "  2. \"Qualifier\": List of Enums for the trigger condition (e.g., [\"ARRAY_BOUNDS\", \"FOR_LOOP\"]).\n"
        "  3. \"Action\": List of Enums for the resolution (e.g., [\"CHECK_LENGTH_BEFORE_INDEX\"]).\n"
        "  4. \"Strength\": Must be one of [\"MANDATORY\", \"RECOMMENDED\", \"OPTIONAL\"].\n"
        "  5. \"LanguageFeature\": A string categorizing the feature (e.g., \"RUNTIME_PANIC_PREVENTION\").\n"
        "- Output ONLY the JSON block, nothing else."
    )
    
    # Rút gọn context để tránh vượt token limit
    failed_code = failed_code[-1000:] if len(failed_code) > 1000 else failed_code
    fixed_code = fixed_code[-1000:] if len(fixed_code) > 1000 else fixed_code
    error_log = error_log[-1000:] if len(error_log) > 1000 else error_log
    
    user_prompt = f"""Failed Code snippet:
{failed_code}

Error Log:
{error_log}

Successfully Fixed Code:
{fixed_code}

Based on the above, write ONE concise rule that caused this fix:"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=50
        )
        rule = response.choices[0].message.content.strip()
        return rule
    except Exception as e:
        logging.error(f"Rule extraction failed: {e}")
        return ""
