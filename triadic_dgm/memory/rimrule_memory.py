import json
import os
from typing import List, Dict, Any

from triadic_dgm.persona.vocabulary import dataset_is_telco, mentions_telco_domain

class Rule:
    """
    [SOTA] Cấu trúc Lưu trữ Kép (Dual Representation) theo bài báo RIMRULE.
    Kết hợp giữa Ngôn ngữ tự nhiên (cho LLM đọc) và Symbolic (cho truy xuất nhanh).
    """
    def __init__(self, nl_rule: str, domain: str, qualifier: List[str], action: List[str], strength: str, tool_category: str):
        self.nl_rule = nl_rule  # Natural Language form
        
        # Symbolic Fields (Từ vựng đóng)
        self.domain = domain
        self.qualifier = qualifier
        self.action = action
        self.strength = strength
        self.tool_category = tool_category
        
        # MDL Metrics
        self.errors_fixed = 1
        self.token_length = max(1, len(nl_rule.split())) # Tránh chia cho 0
        
    @property
    def mdl_score(self) -> float:
        """
        [Khóa luận] Công thức tính điểm Minimum Description Length (MDL).
        MDL-score(r) = số lỗi được sửa nhờ r / độ dài của r (token).
        """
        return self.errors_fixed / self.token_length

    def to_dict(self) -> dict:
        return {
            "nl_rule": self.nl_rule,
            "domain": self.domain,
            "qualifier": self.qualifier,
            "action": self.action,
            "strength": self.strength,
            "tool_category": self.tool_category,
            "errors_fixed": self.errors_fixed,
            "token_length": self.token_length,
            "mdl_score": round(self.mdl_score, 4)
        }

class RimruleMemoryBank:
    """
    Manages the heuristics and rules derived from the Triadic DGM process.
    Provides context to Agents to avoid repeating past mistakes.
    """
    
    def __init__(self, archive_path: str = "dgm_agent_v2/rimrule_archive.json"):
        self.archive_path = archive_path
        self.rules: List[Rule] = []
        # Tự động nạp bộ nhớ từ các lần chạy trước
        self._load_archive()

    def add_or_consolidate_rule(self, new_rule: Rule):
        """
        [SOTA] Cơ chế Gộp luật (MDL Consolidation).
        Thay vì lưu tràn lan, nếu gặp luật có cùng Domain và Action,
        ta chỉ tăng biến errors_fixed (tăng DataCost) để làm MDL-score tăng vọt.
        """
        # Tránh gộp nhầm (Over-merging): Kiểm tra thêm độ tương đồng ngữ nghĩa cơ bản
        # bằng cách check xem text có độ trùng lặp cao không (Jaccard cơ bản)
        new_words = set(new_rule.nl_rule.lower().split())
        
        for existing_rule in self.rules:
            if existing_rule.domain == new_rule.domain and set(existing_rule.action) == set(new_rule.action):
                exist_words = set(existing_rule.nl_rule.lower().split())
                # Tính độ tương đồng Jaccard
                if len(new_words.union(exist_words)) > 0:
                    similarity = len(new_words.intersection(exist_words)) / len(new_words.union(exist_words))
                    if similarity > 0.4:  # Ngưỡng tương đồng 40%
                        existing_rule.errors_fixed += 1
                        self._save_archive()
                        return
        
        # Thêm luật mới nếu chưa tồn tại hoặc khác biệt ngữ nghĩa
        self.rules.append(new_rule)
        self._save_archive()

    def retrieve_rules_symbolic(self, query_domain: str, top_k: int = 3,
                                active_columns: List[str] | None = None) -> str:
        """
        [SOTA] Truy xuất luật dựa trên Symbolic Matching.
        Trả về các quy tắc tốt nhất để tiêm vào System Prompt của Solver.

        Args:
            query_domain: Miền cần truy xuất (khớp với ``domain`` hoặc ``qualifier``).
            top_k: Số luật tối đa trả về.
            active_columns: Tên cột của dataset ĐANG được phân tích. Nếu dataset này không
                phải telco, các luật nhắc tới định danh telco sẽ bị loại — chúng được học
                trên một dataset khác, và khi tiêm vào chúng khẳng định với model rằng dữ
                liệu hiện tại có những cột không hề tồn tại. ``None`` = người gọi không đưa
                ra khẳng định nào, giữ nguyên hành vi cũ (vòng lặp tiến hoá đang debug
                chính dataset telco cần đúng những luật đó).
        """
        if not self.rules:
            return ""

        # Lọc thô (Coarse filter) bằng Domain
        relevant_rules = [r for r in self.rules if r.domain == query_domain or query_domain in r.qualifier]

        # Lọc theo dataset đang phân tích. Phải chạy TRƯỚC khi cắt top_k: xếp hạng theo MDL
        # ưu tiên luật ngắn, mà các luật telco lại rất ngắn — cắt trước sẽ để chúng chiếm
        # hết slot và đẩy các luật dùng được ra ngoài.
        if active_columns is not None and not dataset_is_telco(active_columns):
            relevant_rules = [r for r in relevant_rules if not mentions_telco_domain(r.nl_rule)]
            if not relevant_rules:
                return ""

        # Xếp hạng (Rank) theo MDL Score (ưu tiên luật sửa nhiều lỗi, ngắn gọn)
        ranked_rules = sorted(relevant_rules, key=lambda r: r.mdl_score, reverse=True)
        
        # Trích xuất dạng text để Solver Agent dễ đọc
        result = ["[CÁC LỖI TỪNG GẶP TRONG QUÁ KHỨ & CÁCH TRÁNH]"]
        for idx, rule in enumerate(ranked_rules[:top_k]):
            result.append(f"- Rule {idx+1} [MDL Score: {rule.mdl_score:.2f}]: {rule.nl_rule}")
            
        return "\n".join(result)

    def _save_archive(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.archive_path)), exist_ok=True)
        with open(self.archive_path, 'w', encoding='utf-8') as f:
            json.dump([r.to_dict() for r in self.rules], f, indent=4)

    def _load_archive(self):
        if os.path.exists(self.archive_path):
            with open(self.archive_path, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    for item in data:
                        r = Rule(
                            nl_rule=item['nl_rule'],
                            domain=item['domain'],
                            qualifier=item['qualifier'],
                            action=item['action'],
                            strength=item['strength'],
                            tool_category=item['tool_category']
                        )
                        r.errors_fixed = item.get('errors_fixed', 1)
                        self.rules.append(r)
                except json.JSONDecodeError:
                    pass
