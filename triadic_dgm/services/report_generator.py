import json
import re
from datetime import datetime
import instructor
from openai import OpenAI
from triadic_dgm.schemas.report_schema import ReportNarrative

# ==============================================================
# TAXONOMY & MAPPING CATALOG (Enterprise Metadata)
# ==============================================================
ROADMAP_METADATA = {
    "Outbound CSKH chủ động để xoa dịu khách hàng": {
        "objective": "Khôi phục trải nghiệm khách hàng",
        "kpi": "NPS, FCR, Contact Rate",
        "investigation": "Review Ticket, Analyze Call Recording",
        "owner": "Customer Care",
        "timeline": "30 days"
    },
    "Thu thập thêm dữ liệu hành vi": {
        "objective": "Khám phá nguyên nhân gốc rễ (Root Cause)",
        "kpi": "Behavior Coverage, Model Accuracy",
        "investigation": "Pull CRM History, Enrich Telemetry Data",
        "owner": "Data Team",
        "timeline": "14 days"
    },
    "Thu thập thêm App usage logs": {
        "objective": "Nắm bắt hành vi tương tác số",
        "kpi": "App Usage Coverage, Active Rate",
        "investigation": "Review App Sessions, Analyze Feature Usage",
        "owner": "Product Team",
        "timeline": "14 days"
    },
    "Khảo sát mức độ hài lòng qua Zalo/SMS": {
        "objective": "Thu thập phản hồi trực tiếp",
        "kpi": "NPS, CES, Response Rate",
        "investigation": "Send Pulse Survey, Post-interaction Survey",
        "owner": "CX Team",
        "timeline": "7 days"
    },
    "Phân tích nguyên nhân khiếu nại/liên hệ": {
        "objective": "Giảm tỷ lệ khiếu nại lặp lại",
        "kpi": "Repeat Incident Rate, MTTR",
        "investigation": "Check Ticket Categories, Trace Root Cause",
        "owner": "Operations",
        "timeline": "21 days"
    },
    "Nghiên cứu nguyên nhân kỹ thuật": {
        "objective": "Cải thiện chất lượng hạ tầng mạng",
        "kpi": "Network Stability, SLA Success Rate",
        "investigation": "Pull OSS Log, Check Fiber Loss, Review Alarm",
        "owner": "NOC Team",
        "timeline": "14 days"
    },
    "Tư vấn đổi gói cước phù hợp hành vi sử dụng": {
        "objective": "Giữ chân qua điều chỉnh gói cước phù hợp nhu cầu thực tế",
        "kpi": "Usage Recovery Rate, Churn Rate",
        "investigation": "Review Usage Pattern, Compare Package Fit",
        "owner": "Product Team",
        "timeline": "21 days"
    },
    "Khảo sát cơ hội upsell/cross-sell dịch vụ": {
        "objective": "Tăng doanh thu từ nhóm có xu hướng nâng cấp",
        "kpi": "Upsell Conversion Rate, ARPU Uplift",
        "investigation": "Review Upgrade History, Segment by Package Tier",
        "owner": "Sales/CRM Team",
        "timeline": "14 days"
    },
    "Chủ động liên hệ trước nguy cơ hạ cấp dịch vụ": {
        "objective": "Ngăn chặn tụt hạng phân khúc / rời mạng",
        "kpi": "Retention Rate, Downgrade Rate",
        "investigation": "Pull Billing History, Check Tier Change Log",
        "owner": "Retention Team",
        "timeline": "10 days"
    },
    "Phân tích nguyên nhân sử dụng dao động": {
        "objective": "Ổn định hành vi sử dụng, giảm rủi ro rời mạng do thiếu nhất quán",
        "kpi": "Usage Stability Index, Churn Rate",
        "investigation": "Review Usage Timeline, Segment by Package Change",
        "owner": "Product Team",
        "timeline": "14 days"
    }
}

RETENTION_SCRIPT_CATALOG = {
    "TECHNICAL": {
        "category": "Vấn đề kỹ thuật",
        "script": "Xin lỗi vì trải nghiệm mạng chưa ổn định, xác nhận lại sự cố, cam kết thời gian xử lý, đề xuất kiểm tra đường truyền miễn phí.",
    },
    "PRICE": {
        "category": "Giá cước cao / Thay đổi hạng phân khúc",
        "script": "Ghi nhận phản hồi về chi phí, giải thích thay đổi hạng phân khúc (nếu có), đề xuất gói/ưu đãi giữ chân phù hợp theo chính sách hiện hành.",
    },
    "EXPERIENCE": {
        "category": "Trải nghiệm kém / CSAT thấp",
        "script": "Xin lỗi về trải nghiệm liên hệ nhiều lần, tổng hợp lịch sử tương tác, xử lý dứt điểm trong 1 lần gọi (FCR), khảo sát lại sau xử lý.",
    },
    "NEEDS_CHANGE": {
        "category": "Nhu cầu thay đổi (giảm sử dụng)",
        "script": "Tìm hiểu lý do giảm nhu cầu sử dụng, tư vấn gói phù hợp hơn với hành vi hiện tại thay vì chỉ giữ nguyên gói cũ.",
    },
    "PAYMENT": {
        "category": "Dấu hiệu tạm ngưng / nguy cơ rời mạng",
        "script": "Chủ động liên hệ hỏi thăm tình trạng sử dụng, xác nhận nhu cầu tiếp tục dịch vụ, đề xuất hỗ trợ trước khi khách hàng chuyển sang trạng thái tạm ngưng.",
    },
}


def attach_recommended_scripts(persona: dict) -> list:
    """Deterministic, catalog-driven — never LLM-authored (anti-hallucination)."""
    profile = persona.get('profile_attributes', {}) or {}
    severity = persona.get('severity')
    risk = persona.get('risk')
    scripts = []
    if severity in ("HIGH", "EXTREME"):
        scripts.append(RETENTION_SCRIPT_CATALOG["TECHNICAL"])
    if profile.get('tier_downgrade_rate', 0) > 0:
        scripts.append(RETENTION_SCRIPT_CATALOG["PRICE"])
    if profile.get('csat_avg') is not None and profile.get('csat_avg', 5) <= 2:
        scripts.append(RETENTION_SCRIPT_CATALOG["EXPERIENCE"])
    if profile.get('usage_decline_strong_pct', 0) >= 0.2 or profile.get('usage_decline_mild_pct', 0) >= 0.3 or profile.get('usage_unstable_pct', 0) >= 0.3:
        scripts.append(RETENTION_SCRIPT_CATALOG["NEEDS_CHANGE"])
    if profile.get('status_worsening_pct', 0) >= 0.2:
        scripts.append(RETENTION_SCRIPT_CATALOG["PAYMENT"])
    if risk in ("HIGH", "EXTREME") and not scripts:
        scripts.append(RETENTION_SCRIPT_CATALOG["EXPERIENCE"])
    return scripts


FEATURE_SEMANTIC_MAP = {
    "months_since_last_call": "Tần suất liên hệ CSKH",
    "months_since_first_call": "Lịch sử liên hệ",
    "months_since_last_cl": "Tần suất khiếu nại",
    "cl_total_6m": "Tổng số khiếu nại",
    "call_total_6m": "Tổng số cuộc gọi",
    "missed_total_6m": "Tỷ lệ cuộc gọi không thành công",
    "cl_trend": "Xu hướng khiếu nại",
    "call_trend": "Xu hướng liên hệ",
    "complaint_trend": "Xu hướng phàn nàn",
    "declining_cl": "Dấu hiệu giảm khiếu nại",
    "declining_contact": "Dấu hiệu giảm tương tác",
    "declining_complaint": "Dấu hiệu giảm phàn nàn",
    "escalating_cl": "Dấu hiệu khiếu nại leo thang",
    "escalating_complaint": "Dấu hiệu phàn nàn leo thang",
    "old_complaint": "Lịch sử phàn nàn cũ",
    "cl_recent_only": "Hành vi khiếu nại mới phát sinh",
    "no_cl_all_period": "Lịch sử khiếu nại",
    "no_complaint_all_period": "Lịch sử phàn nàn",
    "call_cv": "Mức độ biến động liên hệ",
    "cl_avg_6m": "Mật độ khiếu nại trung bình",
    "fee_total": "Tổng cước phí",
    "fee_avg": "Cước phí trung bình",
    "fee_trend": "Xu hướng cước phí",
    "high_spender": "Khách hàng chi tiêu cao",
    "segment_trend": "Xu hướng hạng phân khúc",
    "segment_upgrade_count": "Số lần nâng hạng phân khúc",
    "segment_downgrade_count": "Số lần tụt hạng phân khúc",
    "spending_decline": "Chi tiêu đang giảm",
    "spending_growth": "Chi tiêu đang tăng",
    "cnt_giam_nhe": "Số tháng sử dụng giảm nhẹ",
    "cnt_giam_manh": "Số tháng sử dụng giảm mạnh",
    "cnt_dao_dong": "Số tháng sử dụng dao động",
    "persistent_giam_manh": "Xu hướng giảm sử dụng mạnh kéo dài",
    "ever_giam_manh": "Từng giảm sử dụng mạnh",
    "ever_giam_nhe": "Từng giảm sử dụng nhẹ",
    "status_worsening": "Trạng thái thuê bao xấu đi",
    "status_trend": "Xu hướng trạng thái thuê bao",
    "loyalty_rank": "Hạng khách hàng thân thiết",
    "loyalty_status": "Trạng thái khách hàng thân thiết",
    "total_csat": "Điểm hài lòng khách hàng (CSAT)",
}
# Lookup phải case-insensitive vì tên cột thực tế trong dataset không luôn khớp casing ở trên
# (vd: cnt_Dao_dong vs cnt_dao_dong) — khớp sai casing từng khiến signal hiện tên cột thô ra báo cáo.
_FEATURE_SEMANTIC_MAP_LOWER = {k.lower(): v for k, v in FEATURE_SEMANTIC_MAP.items()}

# Các cột này là artifact nội bộ của pipeline (ID cụm, cờ nội bộ...), KHÔNG PHẢI business signal —
# tuyệt đối không được lọt vào Business Signals/Evidence dù dataset nào cũng có thể vô tình include.
EXCLUDED_TECHNICAL_FEATURES = {"cluster", "cluster_id", "is_anomaly", "persona_type", "priority_score"}

# Các feature mà FEATURE_SEMANTIC_MAP đã diễn giải SẴN CÓ HƯỚNG (giảm/tăng/leo thang...) — nếu
# vẫn nối thêm hậu tố "tăng/giảm rất mạnh" của _get_business_signal sẽ ra câu 2 hướng vô nghĩa,
# vd "Chi tiêu đang giảm tăng rất mạnh" (đã xảy ra trên báo cáo thật). Với nhóm feature này, độ
# lệch so với trung bình phải được diễn giải là MỨC ĐỘ PHỔ BIẾN của tín hiệu trong cụm, không phải
# một hướng tăng/giảm thứ hai.
_DIRECTIONAL_FLAG_FEATURES = {
    "persistent_giam_manh", "ever_giam_manh", "ever_giam_nhe",
    "spending_decline", "spending_growth",
    "declining_cl", "declining_contact", "declining_complaint",
    "escalating_cl", "escalating_complaint",
    "status_worsening", "cl_recent_only", "complaint_recent_only",
}

# Các cặp tín hiệu đối lập không nên cùng xuất hiện trong 1 persona (gây mâu thuẫn logic trong
# narrative, vd: "Chi tiêu đang tăng" và "Chi tiêu đang giảm" cùng lúc). Khi cả 2 đều lọt vào top
# deviations, chỉ giữ lại tín hiệu có độ lệch (deviation) lớn hơn.
CONFLICTING_FEATURE_PAIRS = [
    ("spending_growth", "spending_decline"),
    ("segment_upgrade_count", "segment_downgrade_count"),
]

# ==============================================================
# REPORT VALIDATION HARNESS
# ==============================================================
class ReportValidator:
    @staticmethod
    def validate(personas_data: list):
        if not personas_data:
            return
            
        total_customers = sum(p.get('support', 0) for p in personas_data)
        assert total_customers > 0, "Total support must be greater than 0"
        
        # Check unique persona names
        names = [p.get('persona_name') for p in personas_data]
        # Allow duplicate base names since we clean them, but warn
        
        # Ensure KPI mapping exists
        for p in personas_data:
            actions = p.get('recommended_actions', [])
            if actions:
                action = actions[0]
                if action not in ROADMAP_METADATA:
                    print(f"[Validator Warning] Action '{action}' not found in Roadmap Metadata.")

        # Soft warning only — older/plainer JSON without the extended profiling fields must keep working
        if not any(p.get('profile_attributes') for p in personas_data):
            print("[Validator Warning] No persona has 'profile_attributes' — dataset may lack the extended columns (spend/tier/usage-trend/CSAT/loyalty). Risk-tier/profile sections will be limited.")

# ==============================================================
# CORE GENERATOR (v3 Enterprise)
# ==============================================================
class ReportGenerator:
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.client = instructor.from_openai(
            OpenAI(api_key=api_key, base_url=base_url),
            mode=instructor.Mode.JSON
        )

    def extract_json(self, raw_python_output: str):
        match = re.search(r'\[JSON_START_PERSONA\](.*?)\[JSON_END_PERSONA\]', raw_python_output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return []
        return []

    # Icon/nhãn cường độ CHỈ là cách trình bày (mapping tĩnh từ persona_name/risk/severity đã tính
    # thật) — KHÔNG bịa nội dung, chỉ chọn biểu tượng phù hợp với tên/risk đã có sẵn trong JSON.
    _PERSONA_ICON_RULES = [
        (["chi tiêu cao có dấu hiệu suy giảm"], "💎📉"),
        (["chi tiêu cao"], "💎"),
        (["bất mãn"], "😞"),
        (["tạm ngưng"], "⚠️"),
        (["hạ cấp", "suy giảm mạnh", "giảm sử dụng"], "📉"),
        (["dao động"], "🔀"),
        (["nâng cấp"], "📈"),
        (["giảm gắn bó"], "🔌"),
        (["gắn bó"], "🔗"),
        (["liên hệ cskh", "cskh nhiều"], "🎧"),
        (["kỹ thuật"], "🛠️"),
        (["im lặng"], "🔕"),
        (["tương tác nhẹ"], "📵"),
        (["bất thường"], "❗"),
        (["ổn định"], "⚖️"),
    ]

    def _get_persona_icon(self, persona_name: str) -> str:
        n = persona_name.lower()
        for keywords, icon in self._PERSONA_ICON_RULES:
            if any(k in n for k in keywords):
                return icon
        return "👤"

    def _get_intensity_tag(self, p: dict) -> str:
        """English risk-intensity tag derived ONLY from already-computed severity/risk/risk_tier
        fields — never a separate judgment call, just a shorter label for the same real data."""
        if p.get('persona_type') == 'ANOMALY':
            return "Anomaly"
        if p.get('severity') == 'EXTREME' or p.get('risk') == 'EXTREME':
            return "Very High Risk"
        tier = p.get('risk_tier', '')
        if "giữ chân" in tier:
            return "Priority Retention"
        if p.get('severity') == 'HIGH' or p.get('risk') == 'HIGH':
            return "High Risk"
        if "bị động" in tier:
            return "Passive"
        if p.get('severity') == 'MEDIUM' or p.get('risk') == 'MEDIUM':
            return "Medium"
        return "Stable"

    def _get_evidence_bullets(self, p: dict, global_means: dict, top_n: int = 3) -> list:
        """Real evidence bullets only — top_n strongest feature deviations (already computed by
        _top_signals) plus the dominant service usage if present. Never fabricated commentary."""
        means = self._get_means(p)
        bullets = []
        if means:
            for f, val, g_val, _ in self._top_signals(means, global_means, top_n=top_n):
                bullets.append(self._get_business_signal(f, val, g_val))
        profile = p.get('profile_attributes') or {}
        svc_comp = profile.get('service_composition')
        if svc_comp:
            top_svc, top_pct = max(svc_comp.items(), key=lambda kv: kv[1])
            bullets.append(f"Đa số là KH dùng dịch vụ {top_svc} ({top_pct * 100:.1f}%)")
        return bullets if bullets else ["Không có tín hiệu nổi bật so với trung bình"]

    def _format_composition(self, comp: dict, top_n: int = 3) -> str:
        """Renders a {category: fraction} breakdown (vd package/service composition) as a
        readable 'A (45.2%), B (30.1%)' string instead of a raw Python dict repr."""
        if not comp:
            return "N/A"
        top_items = sorted(comp.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        return ", ".join(f"{k} ({v * 100:.1f}%)" for k, v in top_items)

    def clean_persona_name(self, raw_name: str) -> str:
        name = raw_name
        if " - Cluster " in name:
            name = name.split(" - Cluster ")[0].strip()
        if " - Nhóm" in name:
            name = name.split(" - Nhóm")[0].strip()
        if " - Rank" in name:
            name = name.split(" - Rank")[0].strip()
        return name

    def format_support(self, support: int) -> str:
        if support >= 1000:
            return f"≈{support/1000:.1f}k KH"
        return f"{support} KH"

    def _get_business_signal(self, feature: str, val: float, global_mean: float) -> str:
        """SEMANTIC LAYER: Converts feature and data into natural business signals."""
        base_name = _FEATURE_SEMANTIC_MAP_LOWER.get(str(feature).lower(), feature)
        
        # Handle the magic 999
        if val in [999, 999.0, 888, 888.0, 500.0, 500.95, 887, 886.77, 898.38, 898.34]:
            if 'call' in feature:
                return "Không phát sinh liên hệ trong kỳ"
            if 'cl' in feature or 'complaint' in feature:
                return "Không có khiếu nại trong kỳ"
            return "Chưa có dữ liệu"
            
        # Handle Boolean 1.0 flags
        if val == 1.0 and ("no_" in feature or "escalating_" in feature or "declining_" in feature):
            return f"Tồn tại {base_name.lower()}"
        if val == 0.0 and ("no_" in feature):
            return f"Có phát sinh {base_name.lower()}"
            
        # Delta comparison
        delta_pct = ((val - global_mean) / abs(global_mean)) * 100 if global_mean != 0 else val * 100

        if str(feature).lower() in _DIRECTIONAL_FLAG_FEATURES:
            # base_name đã tự mang hướng (vd "Chi tiêu đang giảm") — độ lệch ở đây nói về MỨC ĐỘ
            # PHỔ BIẾN của tín hiệu đó trong cụm này so với toàn quần thể, không phải hướng thứ 2.
            if delta_pct > 100:
                return f"{base_name} — phổ biến hơn hẳn trong nhóm này"
            elif delta_pct > 0:
                return f"{base_name} — phổ biến hơn trung bình"
            elif delta_pct < -100:
                return f"{base_name} — hiếm gặp trong nhóm này"
            elif delta_pct < 0:
                return f"{base_name} — ít phổ biến hơn trung bình"
            else:
                return f"{base_name} — ở mức trung bình"

        if delta_pct > 100:
            return f"{base_name} tăng rất mạnh"
        elif delta_pct > 0:
            return f"{base_name} có xu hướng tăng"
        elif delta_pct < -100:
            return f"{base_name} giảm rất mạnh"
        elif delta_pct < 0:
            return f"{base_name} có xu hướng giảm"
        else:
            return f"{base_name} ổn định"

    def _get_means(self, p: dict) -> dict:
        means = p.get('feature_means', p.get('evidence', {}))
        return {f: v for f, v in means.items() if str(f).lower() not in EXCLUDED_TECHNICAL_FEATURES}

    def _ranked_deviations(self, means: dict, global_means: dict) -> list:
        deviations = []
        for f, val in means.items():
            g_val = global_means.get(f, 0)
            dev = abs(val - g_val) / abs(g_val) if g_val != 0 else abs(val) * 100
            deviations.append((f, val, g_val, dev))
        deviations.sort(key=lambda x: x[3], reverse=True)
        return deviations

    def _resolve_conflicts(self, deviations: list) -> list:
        """Drop the weaker signal of any known-opposite pair (e.g. spending_growth vs
        spending_decline) so a persona's narrative never asserts contradictory trends."""
        feature_names = [d[0] for d in deviations]
        dropped = set()
        for a, b in CONFLICTING_FEATURE_PAIRS:
            if a in feature_names and b in feature_names:
                idx_a, idx_b = feature_names.index(a), feature_names.index(b)
                dropped.add(a if deviations[idx_a][3] < deviations[idx_b][3] else b)
        return [d for d in deviations if d[0] not in dropped]

    def _top_signals(self, means: dict, global_means: dict, top_n: int = 3) -> list:
        return self._resolve_conflicts(self._ranked_deviations(means, global_means))[:top_n]

    def _build_prompt(self, personas_data: list, global_means: dict) -> str:
        """Prepares a heavily sterilized JSON for the LLM"""
        clean_data = []
        for p in personas_data:
            c = {}
            c['persona'] = self.clean_persona_name(p.get('persona_name', ''))

            # Translate top features into business signals
            means = self._get_means(p)
            signals = []
            deviations = self._top_signals(means, global_means, top_n=3) if means else []
            for f, val, g_val, dev in deviations:
                signals.append(self._get_business_signal(f, val, g_val))

            c['business_signals'] = signals
            c['confidence'] = "High" if deviations and deviations[0][3] > 1.0 else "Medium"
            c['cluster_id'] = p.get('cluster_id')
            clean_data.append(c)
            
        data_str = json.dumps(clean_data, ensure_ascii=False, indent=2)
        return f"""
Bạn là Consultant tại Deloitte.
Nhiệm vụ: Viết diễn giải Báo cáo Chân dung Khách hàng bằng NGÔN NGỮ QUẢN TRỊ.

QUY TẮC CỨNG:
- KHÔNG sinh số liệu. KHÔNG nhắc lại số liệu.
- KHÔNG suy diễn ngoài Business Signals được cấp.
- KHÔNG đề xuất hành động mới (Action/Investigation).
- Độ dài: Tối đa 2 câu cho mỗi trường phân tích.

Dữ liệu Business Facts duy nhất bạn được thấy:
{data_str}
"""

    def generate_llm_narrative(self, personas_data: list, global_means: dict) -> ReportNarrative:
        prompt = self._build_prompt(personas_data, global_means)
        try:
            report_narrative: ReportNarrative = self.client.chat.completions.create(
                model=self.model_name,
                response_model=ReportNarrative,
                messages=[{"role": "user", "content": prompt}],
                max_retries=2
            )
            return report_narrative
        except Exception as e:
            raise RuntimeError(f"Failed to generate LLM Narrative: {e}")

    def render_markdown(self, raw_python_output: str) -> str:
        personas_data = self.extract_json(raw_python_output)
        if not personas_data:
            return "Lỗi: Không tìm thấy dữ liệu JSON Persona hợp lệ."
            
        # 1. Validation Harness
        ReportValidator.validate(personas_data)
        
        # 2. Global Calculations
        total_customers = sum(p.get('support', 0) for p in personas_data)
        date_str = datetime.now().strftime("%d tháng %m năm %Y")
        max_pct = max([p.get('support_pct', 0) for p in personas_data])
        max_pct_val = max_pct * 100 if max_pct < 1.0 else max_pct
        seg_quality = personas_data[0].get('segmentation_quality', 'NORMAL')
        
        global_means = {}
        all_features = set()
        for p in personas_data:
            for f in self._get_means(p).keys():
                all_features.add(f)
                
        for f in all_features:
            total_val = sum(self._get_means(p).get(f, 0) * p.get('support', 0) for p in personas_data)
            global_means[f] = total_val / total_customers if total_customers > 0 else 0
            
        for p in personas_data:
            p['priority_score'] = p.get('priority_score', 0)
        ranked_personas = sorted(personas_data, key=lambda x: x['priority_score'], reverse=True)
            
        # 3. Trigger LLM
        narrative = self.generate_llm_narrative(personas_data, global_means)
        
        # ==============================================================
        # 4. REPORT COMPOSER (Presentation Layer)
        # ==============================================================
        
        # Executive Summary
        md = "# BÁO CÁO PHÂN TÍCH CHÂN DUNG KHÁCH HÀNG\n\n"
        md += "**ISC - AI - Data Product Team**\n\n"
        md += f"*Ngày {date_str}*\n\n"
        md += "---\n\n"
        
        md += "## 1. Executive Summary\n\n"
        md += "> [!NOTE]\n"
        md += "> **Executive Facts:**\n"
        md += f"> - **Segmentation Quality:** {seg_quality}\n"
        md += f"> - **Dominant Persona Size:** {max_pct_val:.1f}%\n"
        md += f"> - **Total Population:** {self.format_support(total_customers)}\n\n"
        
        md += f"{narrative.executive_summary.executive_overview}\n\n"
            
        # Methodology
        md += "## 2. Methodology\n\n"
        md += "`Dataset ➔ Feature Engineering ➔ Clustering ➔ Rule Engine ➔ Semantic Layer ➔ Presentation Layer ➔ Narrative Generator (LLM) ➔ Report Composer`\n\n"
        
        # Persona Overview — infographic-style card per persona: icon + tên + % + tag cường độ,
        # theo sau là 3 bullet bằng chứng THẬT (top feature deviations + dịch vụ chiếm ưu thế).
        # Không có bullet nào ở đây là văn bản tự bịa — mọi dòng đều trace được về JSON gốc.
        md += "## 3. Persona Overview\n\n"
        for p in personas_data:
            p_name = self.clean_persona_name(p.get('persona_name', 'Unknown'))
            icon = self._get_persona_icon(p_name)
            tag = self._get_intensity_tag(p)
            sup_pct = p.get('support_pct', 0) * 100
            sup_str = self.format_support(p.get('support', 0))
            bullets = self._get_evidence_bullets(p, global_means, top_n=3)

            md += f"### {icon} {p_name} — {sup_pct:.1f}% ({tag})\n\n"
            md += f"*Quy mô: {sup_str} | Severity: {p.get('severity','N/A')} | Risk: {p.get('risk','N/A')}*\n\n"
            for b in bullets:
                md += f"- {b}\n"
            md += "\n"

        # Risk Tier Grouping (only if at least one persona has risk_tier computed) — mỗi persona
        # kèm 1 dòng "why" lấy từ tín hiệu lệch mạnh nhất thực tế của chính nó (không suy diễn thêm).
        if any(p.get('risk_tier') for p in personas_data):
            md += "## 3b. Risk Tier Grouping\n\n"
            tier_order = [
                "Nhóm rủi ro cao – cần hành động ưu tiên",
                "Nhóm bị động – theo dõi & cảnh báo",
                "Nhóm cần giữ chân ngay – ưu tiên giữ chân",
            ]
            tiers = {t: [] for t in tier_order}
            for p in personas_data:
                t = p.get('risk_tier')
                if t not in tiers:
                    continue
                p_name = self.clean_persona_name(p.get('persona_name', ''))
                means = self._get_means(p)
                top = self._top_signals(means, global_means, top_n=1) if means else []
                why = self._get_business_signal(*top[0][:3]) if top else None
                tiers[t].append((p_name, why))

            for t in tier_order:
                md += f"**{t}**\n\n"
                if tiers[t]:
                    for name, why in tiers[t]:
                        md += f"- **{name}**" + (f" — {why}\n" if why else "\n")
                else:
                    md += "- Không có persona nào\n"
                md += "\n"

        # Persona Analysis
        md += "## 4. Persona Analysis\n\n"
        narrative_dict = {n.cluster_id: n for n in narrative.personas_analysis}
        
        for p in personas_data:
            cid = p.get('cluster_id')
            n = narrative_dict.get(cid)
            p_name = self.clean_persona_name(p.get('persona_name', f'Nhóm {cid}'))
            actions = p.get('recommended_actions', [])
            primary_action = actions[0] if actions else "N/A"
            sup_str = self.format_support(p.get('support', 0))
            
            # Calculate signals and confidence
            means = self._get_means(p)
            signals = []
            confidence = "MEDIUM"
            deviations = self._top_signals(means, global_means, top_n=3) if means else []
            if deviations:
                if deviations[0][3] > 1.0: confidence = "HIGH"
                for f, val, g_val, dev in deviations:
                    signals.append(f"- {self._get_business_signal(f, val, g_val)}")
                    
            signals_text = "\n".join(signals) if signals else "- N/A"
            investigation = ROADMAP_METADATA.get(primary_action, {}).get("investigation", "Review Data")
            
            md += f"### {p_name}\n\n"
            md += "| Thuộc tính | Giá trị |\n"
            md += "|---|---|\n"
            md += f"| **Quy mô** | {sup_str} |\n"
            md += f"| **Severity** | {p.get('severity','N/A')} |\n"
            md += f"| **Risk** | {p.get('risk','N/A')} |\n"
            md += f"| **Semantic Confidence**| {confidence} |\n"
            md += f"| **Recommended Direction**| {investigation} |\n\n"
            
            md += f"**Business Signals:**\n{signals_text}\n\n"

            # Dịch vụ sử dụng phổ biến (vd 'Net Only', 'Net Pay Cam') KHÔNG dùng để train KMeans
            # nhưng vẫn là thông tin nghiệp vụ quan trọng để mô tả persona — đặt nổi bật ngay dưới
            # Business Signals, giống cách infographic tham chiếu ghi "Đa số là KH Combo Net Pay".
            profile_for_services = p.get('profile_attributes') or {}
            if profile_for_services.get('service_composition'):
                md += f"**Dịch vụ sử dụng phổ biến:** {self._format_composition(profile_for_services['service_composition'])}\n\n"

            if n:
                md += f"**Business Interpretation:**\n{n.business_interpretation}\n\n"
                md += f"**Operational Impact:**\n{n.operational_impact}\n\n"

            # Profile Attributes (only present keys — never fabricate missing ones)
            profile = p.get('profile_attributes') or {}
            if profile:
                profile_labels = {
                    'high_spender_pct': 'Tỷ lệ chi tiêu cao',
                    'avg_fee': 'Cước phí trung bình',
                    'tier_upgrade_rate': 'Số lần nâng hạng phân khúc (TB)',
                    'tier_downgrade_rate': 'Số lần tụt hạng phân khúc (TB)',
                    'usage_decline_strong_pct': 'Tỷ lệ giảm sử dụng mạnh',
                    'usage_decline_mild_pct': 'Tỷ lệ giảm sử dụng nhẹ',
                    'usage_unstable_pct': 'Tỷ lệ sử dụng dao động',
                    'status_worsening_pct': 'Tỷ lệ trạng thái thuê bao xấu đi',
                    'loyalty_rank_avg': 'Hạng khách hàng thân thiết (TB)',
                    'csat_avg': 'CSAT trung bình',
                    'ces_avg': 'CES trung bình',
                    'package_composition': 'Thành phần loại gói cước',
                    'service_composition': 'Thành phần dịch vụ sử dụng',
                }
                composition_keys = {'package_composition', 'service_composition'}
                md += "**Profile Attributes:**\n"
                for key, label in profile_labels.items():
                    if key in profile:
                        val = self._format_composition(profile[key]) if key in composition_keys else profile[key]
                        md += f"- {label}: {val}\n"
                md += "\n"

            # Retention Scripts — only for the "cần giữ chân ngay" tier or HIGH+/EXTREME severity/risk
            risk_tier = p.get('risk_tier', '')
            if "giữ chân" in risk_tier or p.get('severity') in ("HIGH", "EXTREME") or p.get('risk') in ("HIGH", "EXTREME"):
                scripts = attach_recommended_scripts(p)
                if scripts:
                    md += "**Retention Scripts:**\n"
                    for s in scripts:
                        md += f"- *{s['category']}*: {s['script']}\n"
                    md += "\n"

            md += "---\n\n"
            
        # Business Roadmap
        md += "## 5. Business Roadmap\n\n"

        md += "| Priority | Initiative | Target Persona | Owner | Timeline | KPI | Expected Outcome |\n"
        md += "|---|---|---|---|---|---|---|\n"

        for rank, p in enumerate(ranked_personas, start=1):
            p_name = self.clean_persona_name(p.get('persona_name', ''))
            sup_str = self.format_support(p.get('support', 0))
            sup_pct = p.get('support_pct', 0) * 100
            actions = p.get('recommended_actions', [])

            action_text = actions[0] if actions else "N/A"
            meta = ROADMAP_METADATA.get(action_text, {})
            owner = meta.get("owner", "TBD")
            timeline = meta.get("timeline", "TBD")
            kpi = meta.get("kpi", "TBD")
            objective = meta.get("objective", "Cải thiện chỉ số nghiệp vụ")
            # Deterministic, Python-computed outcome — never LLM-authored (anti-hallucination),
            # tied to this persona's actual support size/rank instead of generic LLM prose.
            outcome = f"{objective} cho ~{sup_str} ({sup_pct:.1f}% tổng đàn) — ưu tiên #{rank}, theo dõi qua {kpi}."

            md += f"| **#{rank}** | {action_text} | {p_name} | {owner} | {timeline} | {kpi} | {outcome} |\n"

        md += "\n"
            
        # Conclusion
        md += "## 6. Conclusion\n\n"
        if hasattr(narrative, 'conclusion'):
            md += f"{narrative.conclusion}\n\n"
        
        # Appendix
        md += "## Appendix\n\n"
        md += "### Cluster Feature Statistics\n"
        
        for p in personas_data:
            p_name = self.clean_persona_name(p.get('persona_name', ''))
            md += f"#### {p_name}\n"
            md += "| Feature | Value | Benchmark | Dev % |\n"
            md += "|---|---|---|---|\n"
            means = self._get_means(p)
            deviations = self._ranked_deviations(means, global_means)
            for f, val, g_val, dev in deviations[:5]:
                delta_pct = ((val - g_val) / abs(g_val)) * 100 if g_val != 0 else (100 if val > 0 else 0)
                md += f"| {f} | {val:.2f} | {g_val:.2f} | {delta_pct:+.1f}% |\n"
            md += "\n"
        
        md += "### Raw Facts\n"
        match = re.search(r'\[JSON_START_PERSONA\].*?\[JSON_END_PERSONA\]', raw_python_output, re.DOTALL)
        if match:
            md += match.group(0) + "\n"
            
        return md

    def generate_markdown_report(self, raw_python_output: str) -> str:
        return self.render_markdown(raw_python_output)
