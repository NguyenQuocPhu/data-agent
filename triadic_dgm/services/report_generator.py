import json
import re
import time
from datetime import datetime
import instructor
from openai import OpenAI
from triadic_dgm.schemas.report_schema import ReportNarrative, ExecutiveSummaryNarrative

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
    # LƯU Ý: key ở đây PHẢI khớp CHÍNH XÁC (ký tự-cho-ký tự) với chuỗi mà generate_actions() trong
    # triadic_dgm/prompts/prompts.py trả về — nếu lệch dù chỉ 1 ký tự, ROADMAP_METADATA.get() sẽ
    # không tìm thấy và Owner/Timeline/KPI sẽ hiện "TBD" dù recommended_actions vẫn có dữ liệu thật
    # (đã xảy ra trên báo cáo thật với 2 key bên dưới trước khi sửa).
    "Thu thập thêm dữ liệu hành vi (Ticket logs, Call Center logs)": {
        "objective": "Khám phá nguyên nhân gốc rễ (Root Cause)",
        "kpi": "Behavior Coverage, Model Accuracy",
        "investigation": "Pull CRM History, Enrich Telemetry Data",
        "owner": "Data Team",
        "timeline": "14 days"
    },
    "Thu thập thêm App usage logs, Data usage patterns": {
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
    "Kiểm tra chất lượng mạng, tuyến cáp quang, đo suy hao": {
        "objective": "Cải thiện chất lượng hạ tầng mạng",
        "kpi": "Network Stability, SLA Success Rate",
        "investigation": "Pull OSS Log, Check Fiber Loss, Review Alarm",
        "owner": "NOC Team",
        "timeline": "14 days"
    },
    "Thực hiện khảo sát nguyên nhân rời mạng (Exit Survey)": {
        "objective": "Hiểu nguyên nhân rời mạng thực tế",
        "kpi": "Exit Survey Response Rate, Root Cause Coverage",
        "investigation": "Send Exit Survey, Tag Churn Reason",
        "owner": "CX Team",
        "timeline": "14 days"
    },
    "Kiểm tra lịch sử tương tác trước khi rời mạng (Root Cause Investigation)": {
        "objective": "Xác định điểm nghẽn trước khi khách hàng rời mạng",
        "kpi": "Root Cause Coverage, Repeat Churn Pattern Rate",
        "investigation": "Pull Interaction Timeline, Trace Last-Touch Events",
        "owner": "Operations",
        "timeline": "14 days"
    },
    "Chạy chiến dịch Win-back Campaign nếu khách hàng tiềm năng": {
        "objective": "Thu hồi khách hàng có giá trị tiềm năng đã rời mạng",
        "kpi": "Win-back Rate, Reactivation ARPU",
        "investigation": "Score Churned Base by Prior Value, Segment Win-back List",
        "owner": "Retention Team",
        "timeline": "30 days"
    },
    # 4 action bên dưới: mỗi churn_driver (POST_CHURN) giờ có hành động RIÊNG thay vì tất cả đều
    # là "Exit Survey" — key PHẢI khớp CHÍNH XÁC với generate_actions() trong prompts.py.
    "Phân tích đối thủ cạnh tranh và chính sách giá": {
        "objective": "Đánh giá rủi ro cạnh tranh về giá cho nhóm khách hàng giá trị cao",
        "kpi": "Price Competitiveness Index, High-Value Churn Rate",
        "investigation": "Benchmark Competitor Pricing, Review Recent Price Changes",
        "owner": "Pricing/Strategy Team",
        "timeline": "21 days"
    },
    "Khảo sát nguyên nhân rời mạng (Exit Survey) cho nhóm giá trị cao": {
        "objective": "Hiểu nguyên nhân rời mạng của nhóm giá trị cao dù không có tín hiệu bất mãn",
        "kpi": "Exit Survey Response Rate (High-Value), Root Cause Coverage",
        "investigation": "Send Targeted Exit Survey, Tag Non-Service Churn Reason",
        "owner": "CX Team",
        "timeline": "14 days"
    },
    "Rút ngắn SLA xử lý khiếu nại": {
        "objective": "Giảm thời gian tồn đọng khiếu nại trước khi khách hàng rời mạng",
        "kpi": "Complaint SLA, Repeat Complaint Rate",
        "investigation": "Review Complaint Aging Report, Trace Unresolved Tickets",
        "owner": "Customer Care",
        "timeline": "14 days"
    },
    "Cải thiện tỷ lệ xử lý xong trong 1 lần liên hệ (First Call Resolution)": {
        "objective": "Giảm số lần khách hàng phải liên hệ lại cho cùng 1 vấn đề",
        "kpi": "First Call Resolution Rate, Repeat Contact Rate",
        "investigation": "Review Call/Missed-Call Logs, Trace Repeat Contact Reasons",
        "owner": "Customer Care",
        "timeline": "21 days"
    },
    "Theo dõi usage giảm và cảnh báo sớm (Early Warning System)": {
        "objective": "Phát hiện sớm dấu hiệu suy giảm sử dụng trước khi khách hàng rời mạng trong im lặng",
        "kpi": "Usage Decline Detection Rate, Early Intervention Rate",
        "investigation": "Build Usage Trend Alert, Review Silent-Churn Cohort",
        "owner": "Data/Product Team",
        "timeline": "30 days"
    },
    # 3 action bên dưới: 2 persona MỚI từ rule engine tổ hợp domain (Silent Premium Churn, Support
    # Failure) — key PHẢI khớp CHÍNH XÁC với generate_actions() trong prompts.py.
    "Trigger chiến dịch retention ngay khi usage giảm 20% (Early Warning, không chờ khiếu nại)": {
        "objective": "Giữ chân nhóm giá trị cao trước khi họ rời mạng trong im lặng (không đợi khiếu nại)",
        "kpi": "High-Value Usage Decline Detection Rate, Retention Rate (High-Value)",
        "investigation": "Build Usage Decline Alert (High-Value Segment), Review Threshold 20%",
        "owner": "Retention/Data Team",
        "timeline": "21 days"
    },
    "Escalate khiếu nại kỹ thuật lặp lại trong 24h": {
        "objective": "Ngăn sự cố kỹ thuật lặp lại nhiều lần không được xử lý dứt điểm",
        "kpi": "Repeat Technical Issue Rate, Escalation SLA (24h)",
        "investigation": "Review Repeat Ticket Pattern, Trace Unresolved Technical Root Cause",
        "owner": "NOC/Technical Support",
        "timeline": "10 days"
    },
    "Callback tự động sau khi xử lý sự cố kỹ thuật": {
        "objective": "Xác nhận sự cố kỹ thuật đã thực sự được giải quyết, tránh khiếu nại lặp lại",
        "kpi": "Post-Resolution CSAT, Repeat Contact Rate",
        "investigation": "Review Post-Fix Callback Logs, Confirm Resolution Quality",
        "owner": "Customer Care",
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

# Fallback KEYWORD-BASED khi action_text không khớp CHÍNH XÁC bất kỳ key nào ở trên — bắt buộc vì
# generate_actions() nằm trong code do LLM copy-paste vào pipeline, có thể drift cách viết dù chỉ
# 1 chữ (ĐÃ XẢY RA NHIỀU LẦN trên báo cáo thật: dù đã thêm đủ metadata, Roadmap vẫn ra "TBD" vì
# action_text thực tế không khớp byte-for-byte). Thay vì phụ thuộc hoàn toàn vào exact match (dễ vỡ
# với BẤT KỲ thay đổi từ ngữ nào trong tương lai), dùng từ khóa để tìm metadata GẦN ĐÚNG nhất thay vì
# rơi thẳng về "TBD".
ROADMAP_KEYWORD_FALLBACKS = [
    (["đối thủ", "cạnh tranh", "chính sách giá"], {
        "objective": "Đánh giá rủi ro cạnh tranh về giá", "kpi": "Price Competitiveness Index",
        "investigation": "Benchmark Competitor Pricing", "owner": "Pricing/Strategy Team", "timeline": "21 days"}),
    (["escalate", "leo thang"], {
        "objective": "Ngăn sự cố kỹ thuật lặp lại không được xử lý dứt điểm", "kpi": "Repeat Technical Issue Rate",
        "investigation": "Review Repeat Ticket Pattern", "owner": "NOC/Technical Support", "timeline": "10 days"}),
    (["callback"], {
        "objective": "Xác nhận sự cố kỹ thuật đã thực sự được giải quyết", "kpi": "Post-Resolution CSAT",
        "investigation": "Review Post-Fix Callback Logs", "owner": "Customer Care", "timeline": "14 days"}),
    (["sla", "khiếu nại"], {
        "objective": "Giảm thời gian tồn đọng khiếu nại", "kpi": "Complaint SLA, Repeat Complaint Rate",
        "investigation": "Review Complaint Aging Report", "owner": "Customer Care", "timeline": "14 days"}),
    (["cảnh báo sớm", "early warning", "trigger", "usage giảm"], {
        "objective": "Phát hiện sớm dấu hiệu suy giảm sử dụng trước khi rời mạng trong im lặng", "kpi": "Usage Decline Detection Rate",
        "investigation": "Build Usage Trend Alert", "owner": "Data/Product Team", "timeline": "21 days"}),
    (["first call resolution", "1 lần liên hệ"], {
        "objective": "Giảm số lần khách hàng phải liên hệ lại cho cùng 1 vấn đề", "kpi": "First Call Resolution Rate",
        "investigation": "Review Call/Missed-Call Logs", "owner": "Customer Care", "timeline": "21 days"}),
    (["win-back", "win back"], {
        "objective": "Thu hồi khách hàng có giá trị tiềm năng đã rời mạng", "kpi": "Win-back Rate, Reactivation ARPU",
        "investigation": "Score Churned Base by Prior Value", "owner": "Retention Team", "timeline": "30 days"}),
    (["exit survey", "khảo sát nguyên nhân rời mạng"], {
        "objective": "Hiểu nguyên nhân rời mạng thực tế", "kpi": "Exit Survey Response Rate",
        "investigation": "Send Exit Survey, Tag Churn Reason", "owner": "CX Team", "timeline": "14 days"}),
    (["gói cước", "đổi gói"], {
        "objective": "Giữ chân qua điều chỉnh gói cước phù hợp nhu cầu thực tế", "kpi": "Usage Recovery Rate, Churn Rate",
        "investigation": "Review Usage Pattern, Compare Package Fit", "owner": "Product Team", "timeline": "21 days"}),
    (["upsell", "cross-sell", "cross sell"], {
        "objective": "Tăng doanh thu từ nhóm có xu hướng nâng cấp", "kpi": "Upsell Conversion Rate, ARPU Uplift",
        "investigation": "Review Upgrade History", "owner": "Sales/CRM Team", "timeline": "14 days"}),
    (["hạ cấp", "downgrade"], {
        "objective": "Ngăn chặn tụt hạng phân khúc / rời mạng", "kpi": "Retention Rate, Downgrade Rate",
        "investigation": "Pull Billing History, Check Tier Change Log", "owner": "Retention Team", "timeline": "10 days"}),
    (["thu thập", "dữ liệu hành vi"], {
        "objective": "Khám phá nguyên nhân gốc rễ (Root Cause)", "kpi": "Behavior Coverage, Model Accuracy",
        "investigation": "Pull CRM History, Enrich Telemetry Data", "owner": "Data Team", "timeline": "14 days"}),
]


def resolve_roadmap_metadata(action_text: str) -> dict:
    """Exact match first; falls back to keyword matching so Roadmap never silently shows raw
    TBD just because generate_actions()'s exact wording drifted from the ROADMAP_METADATA key."""
    if action_text in ROADMAP_METADATA:
        return ROADMAP_METADATA[action_text]
    al = action_text.lower()
    for keywords, meta in ROADMAP_KEYWORD_FALLBACKS:
        if any(kw in al for kw in keywords):
            return meta
    return {}


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
    # LƯU Ý: "cl" = Checklist/sự cố kỹ thuật (xem apply_business_rules trong prompts.py:
    # get_metric(m, ['cl_total', 'cl', 'sự cố'])) — KHÔNG PHẢI "complaint" (phàn nàn/khiếu nại),
    # đây là 2 cột khác nhau trong dataset. Trước đây map nhầm "cl_*" thành "khiếu nại" khiến báo
    # cáo lẫn lộn 2 loại tín hiệu khác nhau (đã sửa: dùng "sự cố kỹ thuật" cho mọi cột "cl_*").
    "months_since_last_cl": "Số tháng kể từ lần phát sinh sự cố kỹ thuật gần nhất",
    "cl_total_6m": "Tổng số sự cố kỹ thuật (6 tháng)",
    "call_total_6m": "Tổng số cuộc gọi",
    "missed_total_6m": "Tỷ lệ cuộc gọi không thành công",
    "cl_trend": "Xu hướng sự cố kỹ thuật",
    "call_trend": "Xu hướng liên hệ",
    "complaint_trend": "Xu hướng phàn nàn",
    "declining_cl": "Dấu hiệu giảm sự cố kỹ thuật",
    "declining_contact": "Dấu hiệu giảm tương tác",
    "declining_complaint": "Dấu hiệu giảm phàn nàn",
    "escalating_cl": "Dấu hiệu sự cố kỹ thuật leo thang",
    "escalating_complaint": "Dấu hiệu phàn nàn leo thang",
    "old_complaint": "Lịch sử phàn nàn cũ",
    "cl_recent_only": "Sự cố kỹ thuật mới phát sinh",
    "no_cl_all_period": "Không phát sinh sự cố kỹ thuật trong toàn kỳ",
    "no_complaint_all_period": "Lịch sử phàn nàn",
    "call_cv": "Mức độ biến động liên hệ",
    "cl_avg_6m": "Mật độ sự cố kỹ thuật trung bình",
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

# FEATURE_SEMANTIC_MAP chỉ liệt kê từng cột riêng lẻ — dataset thực tế có ~95 cột theo 4 gốc chỉ số
# (cl/complaint/call/missed) x nhiều biến thể tính toán (old_/recent_/_avg_6m/_std/active_*_months/...),
# nên hardcode từng cột là KHÔNG BAO GIỜ đủ (đã xảy ra trên báo cáo thật: "old_missed", "recent_complaint",
# "active_complaint_months"... hiện tên cột thô vì không có trong map). PATTERN-BASED FALLBACK bên dưới
# tách tên cột thành (gốc chỉ số, biến thể tính toán) để tự động suy ra câu tiếng Việt cho MỌI cột theo
# quy ước đặt tên này, kể cả cột chưa từng được liệt kê thủ công.
_METRIC_ROOTS = {
    "cl": "sự cố kỹ thuật",
    "complaint": "phàn nàn/khiếu nại",
    "call": "cuộc gọi CSKH",
    "caller": "cuộc gọi CSKH",
    "missed": "cuộc gọi nhỡ",
}

_FEATURE_PATTERN_RULES = [
    (re.compile(r'^no_(\w+)_all_period$'), "Không phát sinh {metric} trong toàn kỳ"),
    (re.compile(r'^active_(\w+)_months$'), "Số tháng phát sinh {metric}"),
    (re.compile(r'^(\w+)_recent_only$'), "{metric} chỉ mới phát sinh gần đây"),
    (re.compile(r'^(\w+)_ratio_6m$'), "Tỷ lệ {metric} (6 tháng)"),
    (re.compile(r'^high_(\w+)_ratio$'), "Tỷ lệ {metric} cao"),
    (re.compile(r'^(\w+)_total_6m$'), "Tổng số {metric} (6 tháng)"),
    (re.compile(r'^(\w+)_avg_6m$'), "Trung bình {metric}/tháng (6 tháng)"),
    (re.compile(r'^(\w+)_std$'), "Độ biến động {metric}"),
    (re.compile(r'^(\w+)_cv$'), "Độ biến động tương đối {metric}"),
    (re.compile(r'^(\w+)_trend$'), "Xu hướng {metric}"),
    (re.compile(r'^old_(\w+)$'), "{metric} trong giai đoạn đầu kỳ"),
    (re.compile(r'^recent_(\w+)$'), "{metric} gần đây"),
    (re.compile(r'^escalating_(\w+)$'), "{metric} leo thang"),
    (re.compile(r'^declining_(\w+)$'), "{metric} giảm dần"),
    (re.compile(r'^frequent_(\w+)$'), "Tần suất {metric} cao"),
    (re.compile(r'^months_since_last_(\w+)$'), "Số tháng kể từ lần {metric} gần nhất"),
    (re.compile(r'^months_since_first_(\w+)$'), "Số tháng kể từ lần {metric} đầu tiên"),
]


def _pattern_semantic_name(feature_lower: str):
    """Returns a Vietnamese phrase composed from (metric root, naming pattern), or None if the
    column doesn't follow any known convention — caller falls back to the raw column name."""
    for pattern, template in _FEATURE_PATTERN_RULES:
        m = pattern.match(feature_lower)
        if m:
            metric = _METRIC_ROOTS.get(m.group(1))
            if metric:
                phrase = template.format(metric=metric)
                return phrase[:1].upper() + phrase[1:]  # capitalize only the first char (preserve "CSKH")
    return None

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

# Chuyển churn_driver (nhãn ngắn) thành 1 mệnh đề "sau khi ___" cho câu mở đầu story, và 1 cụm
# danh từ ngắn cho câu kết. Cả 2 đều bám sát nghĩa gốc của churn_driver — không thêm nguyên nhân
# mới, chỉ đổi hình thức ngữ pháp để ghép được vào câu kể chuyện.
# Mirrors DOMAIN_KEYWORD_GROUPS in triadic_dgm/prompts/prompts.py's compute_domain_signature() —
# used ONLY as a fallback in _build_customer_profile_bullets() when the pipeline's domain_signature
# field comes back empty, so Customer Profile can still be derived from feature_means directly.
_PROFILE_DOMAIN_FALLBACK_KEYWORDS = {
    'complaint': ['complaint'],
    'call': ['call'],
    'missed': ['missed'],
    'technical': ['cl_total', 'cl_avg', 'cl_std', 'cl_trend', 'old_cl', 'recent_cl', 'active_cl_months', 'no_cl'],
    'usage': ['spending_decline', 'spending_growth', 'usage_decline', 'usage_unstable', 'segment_downgrade', 'segment_upgrade', 'cnt_dao_dong', 'cnt_giam', 'status_worsening'],
    'value': ['high_spender', 'fee_total', 'fee_avg', 'loyalty_rank', 'loyalty_point', 'segment_avg'],
}

_CHURN_DRIVER_NARRATIVE_CLAUSE = {
    "Bất mãn kéo dài, không được xử lý": "trải qua một thời gian dài bất mãn mà không được xử lý triệt để",
    "Sự cố/khiếu nại cấp tính ngay trước khi rời mạng": "xuất hiện nhiều khiếu nại mới trong thời gian gần đây",
    "Tăng liên hệ CSKH/cuộc gọi nhỡ trước khi rời mạng": "tần suất liên hệ CSKH/cuộc gọi nhỡ tăng cao trước khi rời mạng",
    "Khách hàng giá trị cao, chủ động rời mạng": "không có dấu hiệu bất mãn nào, dù là nhóm chi tiêu cao — nguyên nhân nhiều khả năng đến từ giá cước hoặc ưu đãi đối thủ cạnh tranh",
    "Khách hàng âm thầm rời mạng": "hành vi sử dụng dịch vụ suy giảm dần mà không hề khiếu nại hay liên hệ CSKH trước đó",
    "Khách hàng giá trị cao nhưng trải nghiệm suy giảm": "hành vi sử dụng dịch vụ suy giảm rõ rệt dù là nhóm chi tiêu cao, và KHÔNG hề khiếu nại hay liên hệ CSKH trước đó — dấu hiệu rời mạng trong im lặng ở nhóm giá trị cao",
    "Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để": "liên hệ CSKH nhiều lần vì sự cố kỹ thuật lặp lại, đi kèm khiếu nại tăng mạnh, cho thấy vấn đề không được xử lý dứt điểm qua các lần liên hệ",
    "Không rõ nguyên nhân hành vi (có thể do giá cước/cạnh tranh/khác)": "không có dấu hiệu bất thường rõ ràng trong hành vi tương tác — nguyên nhân nhiều khả năng đến từ yếu tố ngoài hành vi (giá cước, cạnh tranh...)",
}
_CHURN_DRIVER_NARRATIVE_NOUN = {
    "Bất mãn kéo dài, không được xử lý": "sự bất mãn kéo dài chưa được xử lý",
    "Sự cố/khiếu nại cấp tính ngay trước khi rời mạng": "sự gia tăng bất mãn",
    "Tăng liên hệ CSKH/cuộc gọi nhỡ trước khi rời mạng": "tần suất liên hệ CSKH/cuộc gọi nhỡ tăng cao",
    "Khách hàng giá trị cao, chủ động rời mạng": "yếu tố ngoài trải nghiệm dịch vụ (giá cước, cạnh tranh)",
    "Khách hàng âm thầm rời mạng": "xu hướng rời mạng trong im lặng, không qua kênh CSKH",
    "Khách hàng giá trị cao nhưng trải nghiệm suy giảm": "xu hướng rời mạng trong im lặng ở nhóm giá trị cao",
    "Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để": "sự cố kỹ thuật lặp lại không được xử lý dứt điểm",
    "Không rõ nguyên nhân hành vi (có thể do giá cước/cạnh tranh/khác)": "yếu tố ngoài hành vi tương tác",
}
# Câu kết insight RIÊNG cho từng driver đã biết — thay cho câu chung chung "Dữ liệu cho thấy X là dấu
# hiệu nổi bật trước khi chấm dứt dịch vụ" lặp lại y hệt cấu trúc ở MỌI persona (đọc nhàm, không có
# ý nghĩa nghiệp vụ cụ thể). Luôn HEDGE ("nhiều khả năng", "phản ánh", "cho thấy") — đây là tương quan
# quan sát được trên tập KHÁCH HÀNG ĐÃ RỜI MẠNG, không phải nguyên nhân đã được xác nhận tuyệt đối,
# TUYỆT ĐỐI KHÔNG khẳng định thẳng kiểu "chất lượng dịch vụ đang ảnh hưởng...".
_CHURN_DRIVER_BUSINESS_INSIGHT = {
    "Bất mãn kéo dài, không được xử lý": "Việc bất mãn kéo dài không được xử lý dứt điểm nhiều khả năng là yếu tố góp phần khiến khách hàng quyết định chấm dứt dịch vụ.",
    "Sự cố/khiếu nại cấp tính ngay trước khi rời mạng": "Việc gia tăng khiếu nại ngay trước thời điểm rời mạng cho thấy trải nghiệm dịch vụ tiêu cực nhiều khả năng là yếu tố góp phần vào quyết định chấm dứt dịch vụ.",
    "Tăng liên hệ CSKH/cuộc gọi nhỡ trước khi rời mạng": "Điều này phản ánh khách hàng có nhu cầu hỗ trợ cao hoặc gặp vướng mắc trong quá trình sử dụng, tuy nhiên các vấn đề chưa leo thang thành khiếu nại chính thức.",
    "Khách hàng giá trị cao, chủ động rời mạng": "Việc rời mạng không đi kèm dấu hiệu bất mãn nào cho thấy nguyên nhân nhiều khả năng đến từ yếu tố bên ngoài (giá cước, ưu đãi đối thủ cạnh tranh) hơn là trải nghiệm dịch vụ.",
    "Khách hàng âm thầm rời mạng": "Việc không phát sinh khiếu nại hay liên hệ CSKH trước khi rời mạng phản ánh nhóm này nhiều khả năng đã âm thầm chuyển sang nhà mạng khác mà không qua kênh phản hồi chính thức.",
    "Khách hàng giá trị cao nhưng trải nghiệm suy giảm": "Hành vi sử dụng suy giảm dần mà không đi kèm khiếu nại cho thấy nhóm khách hàng giá trị cao này nhiều khả năng đã rời mạng trong im lặng, không qua kênh phản hồi chính thức.",
    "Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để": "Việc liên hệ nhiều lần vì sự cố lặp lại trong khi khiếu nại vẫn tiếp tục tăng cho thấy vấn đề kỹ thuật nhiều khả năng chưa được xử lý dứt điểm qua các lần liên hệ.",
    "Không rõ nguyên nhân hành vi (có thể do giá cước/cạnh tranh/khác)": "Việc không ghi nhận tín hiệu hành vi bất thường cho thấy quyết định rời mạng của nhóm này nhiều khả năng đến từ yếu tố ngoài dữ liệu quan sát được, không phải trải nghiệm dịch vụ.",
}
# Tiền tố hay gặp trong FEATURE_SEMANTIC_MAP/pattern semantic name — cắt bỏ để nhét gọn vào câu
# "có xu hướng {noun} cao gấp X lần" (giữ nguyên "Xu hướng" vì câu đã có sẵn từ "xu hướng").
_NARRATIVE_NOUN_STRIP_PREFIXES = [
    "Xu hướng ", "Tổng số ", "Trung bình ", "Tỷ lệ ", "Số tháng phát sinh ",
    "Mức độ biến động tương đối ", "Mức độ biến động ", "Số tháng kể từ lần ",
]
# classify_risk_tier() (prompts.py) gán risk_tier THUẦN theo severity/risk/profile, KHÔNG biết
# dataset_mode — nên chuỗi gốc mang ngôn ngữ hành động TƯƠNG LAI ("giữ chân", "hành động ưu tiên")
# vốn chỉ hợp với KH đang hoạt động. KHÔNG đổi chuỗi risk_tier GỐC (dùng để group/match, và frontend
# persona-cards.tsx hardcode đúng 3 chuỗi này) — chỉ đổi NHÃN HIỂN THỊ trong markdown khi persona có
# churn_driver (POST_CHURN), để tránh đề xuất "giữ chân" người ĐÃ rời mạng.
_POST_CHURN_TIER_DISPLAY_LABELS = {
    "Nhóm rủi ro cao – cần hành động ưu tiên": "Nhóm có dấu hiệu rõ ràng trước khi rời mạng – ưu tiên điều tra nguyên nhân",
    "Nhóm bị động – theo dõi & cảnh báo": "Nhóm không có dấu hiệu hành vi rõ ràng trước khi rời mạng",
    "Nhóm cần giữ chân ngay – ưu tiên giữ chân": "Nhóm giá trị cao đã rời mạng – ưu tiên phân tích nguyên nhân",
}

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
        # POST_CHURN mode: "risk" (future risk) is meaningless for customers who already left —
        # tag reflects whether a churn driver could be identified from the behavioral trajectory.
        if p.get('churn_driver'):
            return "Root Cause Identified" if p.get('churn_driver_confidence') == 'MEDIUM' else "Unclear Cause"
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

    def _narrative_noun(self, base_name: str) -> str:
        n = base_name
        for prefix in _NARRATIVE_NOUN_STRIP_PREFIXES:
            if n.startswith(prefix):
                n = n[len(prefix):]
                break
        return n.lower()

    def _narrative_magnitude(self, val: float, global_mean: float) -> str:
        """Qualitative-only phrasing (KHÔNG kèm số liệu thô %/lần) để lắp vào 'có xu hướng {noun}
        ___' — văn phong business-facing kiểu 'cao hơn hẳn'/'thấp hơn' thay vì 'cao gấp X lần'/
        'cao hơn Y%', theo đúng tông của các bullet mẫu (không ghi số phần trăm nào)."""
        if global_mean != 0:
            delta_pct = (val - global_mean) / abs(global_mean) * 100
        else:
            delta_pct = val * 100
        abs_pct = abs(delta_pct)
        if abs_pct < 20:
            return "ở mức tương đương trung bình"
        if delta_pct > 0:
            return "cao vượt trội" if abs_pct >= 200 else ("cao hơn hẳn" if abs_pct >= 75 else "cao hơn")
        return "thấp hơn hẳn" if abs_pct >= 75 else "thấp hơn"

    def _compose_fallback_driver(self, p: dict) -> dict:
        """Khi `churn_driver` KHÔNG nằm trong danh sách driver đã biết (pipeline LLM không dùng
        đúng classify_churn_driver, tự sinh 1 chuỗi vô nghĩa kiểu "Dựa trên hành vi quan sát được từ
        hệ thống CSKH" — ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: chuỗi này lan truyền y nguyên vào CẢ TÊN lẫn
        STORY của mọi persona, vì _CHURN_DRIVER_NARRATIVE_CLAUSE/_NOUN.get(driver, driver.lower())
        chỉ hạ chữ thường driver gốc khi không khớp key nào, biến "lý do phân tích" thành "nguyên
        nhân rời mạng" một cách vô nghĩa), suy ra tên + lý do rời mạng TRỰC TIẾP từ domain_signature/
        profile_attributes — 100% Python, không phụ thuộc pipeline LLM tuân thủ đúng
        classify_churn_driver. Thứ tự ưu tiên giống classify_churn_driver: combo cụ thể trước,
        generic sau."""
        domain_sig = p.get('domain_signature') or {}
        profile = p.get('profile_attributes') or {}

        def stars(dom):
            info = domain_sig.get(dom)
            return info.get('stars', 1) if isinstance(info, dict) else 1

        s_complaint, s_call, s_missed = stars('complaint'), stars('call'), stars('missed')
        s_usage = stars('usage')
        loyalty = profile.get('loyalty_rank_avg', 0)
        high_spender = profile.get('high_spender_pct', 0)
        downgrade = profile.get('tier_downgrade_rate', 0)

        if s_complaint >= 4:
            return {
                'name': "Khách hàng rời mạng sau khi khiếu nại gia tăng",
                'clause': "khiếu nại/phàn nàn tăng mạnh trước khi rời mạng",
                'noun_phrase': "xu hướng khiếu nại tăng mạnh",
            }
        if s_call >= 3 or s_missed >= 3:
            return {
                'name': "Khách hàng rời mạng sau giai đoạn liên hệ CSKH liên tục",
                'clause': "tần suất liên hệ CSKH/cuộc gọi nhỡ tăng cao trước khi rời mạng",
                'noun_phrase': "tần suất liên hệ CSKH/cuộc gọi nhỡ tăng cao",
            }
        if loyalty >= 1.0:
            return {
                'name': "Khách hàng thân thiết nhưng vẫn rời mạng",
                'clause': "vẫn rời mạng dù mức độ gắn bó/loyalty cao hơn hẳn trung bình",
                'noun_phrase': "mức độ gắn bó/loyalty cao bất thường so với việc rời mạng",
            }
        if high_spender >= 0.3 and (s_usage >= 3 or downgrade >= 0.3):
            return {
                'name': "Khách hàng giá trị cao suy giảm sử dụng trước khi rời mạng",
                'clause': "hành vi sử dụng dịch vụ suy giảm dần dù thuộc nhóm chi tiêu cao",
                'noun_phrase': "xu hướng suy giảm sử dụng ở nhóm giá trị cao",
            }
        if loyalty < 0.3 and s_complaint <= 2 and s_call <= 2:
            return {
                'name': "Khách hàng giá trị thấp rời mạng âm thầm",
                'clause': "rời mạng trong im lặng, không qua khiếu nại hay liên hệ CSKH",
                'noun_phrase': "xu hướng rời mạng trong im lặng",
            }
        return {
            'name': "Khách hàng rời mạng không rõ nguyên nhân hành vi",
            'clause': "không có dấu hiệu hành vi nổi bật trước khi rời mạng",
            'noun_phrase': "thiếu tín hiệu hành vi rõ ràng",
        }

    def _build_persona_story_facts(self, p: dict, global_means: dict):
        """Tính các FACT thô cho câu chuyện POST_CHURN (KHÔNG ghép câu) — dùng CHUNG bởi
        _build_persona_story (ghép cứng thành văn, dùng làm fallback deterministic khi LLM lỗi/
        timeout) và _build_prompt (đưa cho LLM diễn đạt lại tự nhiên/đa dạng hơn) — đảm bảo 2 đường
        LUÔN xuất phát từ đúng 1 bộ số liệu, không lệch nhau. Trả về None nếu persona không có
        churn_driver (không phải POST_CHURN)."""
        driver = p.get('churn_driver')
        if not driver:
            return None
        if driver not in _CHURN_DRIVER_NARRATIVE_CLAUSE:
            # driver không khớp danh sách đã biết -> suy ra lại toàn bộ từ domain_signature/profile
            fb = self._compose_fallback_driver(p)
            driver, clause, noun_phrase_override = fb['name'], fb['clause'], fb['noun_phrase']
        else:
            clause = _CHURN_DRIVER_NARRATIVE_CLAUSE[driver]
            noun_phrase_override = None

        # Câu định lượng (ARPU/high spender/loyalty/downgrade/service mix) — trước đây story chỉ có
        # 1 domain signal + tên dịch vụ, đọc như "cluster thống kê" chứ chưa phải chân dung khách
        # hàng (thiếu 3-5 feature định lượng để người đọc hình dung rõ nhóm này là ai).
        value_sentence = self._compose_profile_value_sentence(
            self._build_profile_context(p), (p.get('profile_attributes') or {}).get('service_composition'))

        means = self._get_means(p)
        top = self._top_signals(means, global_means, top_n=1) if means else []
        magnitude, noun = None, None
        if top:
            f, val, g_val, _ = top[0]
            base_name = _FEATURE_SEMANTIC_MAP_LOWER.get(f.lower()) or _pattern_semantic_name(f.lower()) or f
            noun = self._narrative_noun(base_name)
            magnitude = self._narrative_magnitude(val, g_val)
        is_elevated = magnitude in ("cao hơn", "cao hơn hẳn", "cao vượt trội")

        signal_clause = None
        if is_elevated:
            signal_clause = f"xu hướng {noun} {magnitude}"
        # Nếu KHÔNG elevated: KHÔNG nhét 1 feature lệch âm/trung tính vào câu "xu hướng X cao..."
        # (đọc như đang mô tả nguyên nhân trong khi thực ra không có) — ĐÃ XẢY RA TRÊN BÁO CÁO THẬT
        # với persona 92.8% "Không rõ nguyên nhân hành vi". signal_clause=None báo hiệu "không có
        # tín hiệu hành vi nổi bật" cho cả 2 phía dùng chung.

        svc_comp = (p.get('profile_attributes') or {}).get('service_composition')
        svc_desc = self._describe_composition(svc_comp) if svc_comp else ""

        insight = _CHURN_DRIVER_BUSINESS_INSIGHT.get(driver)
        if not insight:
            noun_phrase = noun_phrase_override or _CHURN_DRIVER_NARRATIVE_NOUN.get(driver, driver.lower())
            insight = f"Dữ liệu cho thấy {noun_phrase} là dấu hiệu nổi bật trước khi chấm dứt dịch vụ."

        return {
            'driver': driver,
            'support': p.get('support', 0),
            'support_pct': p.get('support_pct', 0),
            'clause': clause,
            'value_sentence': value_sentence,
            'is_elevated_signal': is_elevated,
            'signal_clause': signal_clause,
            'service_desc': svc_desc,
            'insight': insight,
        }

    def _build_persona_story(self, p: dict, global_means: dict):
        """POST_CHURN storytelling paragraph — bản GHÉP CỨNG (deterministic, 100% Python) từ
        _build_persona_story_facts, dùng làm fallback khi LLM lỗi/timeout hoặc business_interpretation
        rỗng, để layer Insight không bao giờ biến mất khỏi report."""
        facts = self._build_persona_story_facts(p, global_means)
        if not facts:
            return None
        sup_str = f"{facts['support']:,}".replace(",", ".")
        sup_pct = facts['support_pct'] * 100
        sentences = [f"Khoảng {sup_str} khách hàng ({sup_pct:.1f}%) rời mạng sau khi {facts['clause']}."]

        if facts['value_sentence']:
            sentences.append(facts['value_sentence'])

        if facts['signal_clause']:
            if facts['value_sentence']:
                # profile_context đã nêu ARPU/loyalty/downgrade/service mix — câu này chỉ nối thêm
                # domain signal, KHÔNG lặp lại dịch vụ chủ yếu (đã nói ở câu trên).
                sentences.append(f"Song song đó, nhóm này có {facts['signal_clause']}.")
            else:
                svc_clause = f" và {facts['service_desc']}" if facts['service_desc'] else ""
                sentences.append(f"So với toàn bộ khách hàng, nhóm này có {facts['signal_clause']}{svc_clause}.")
        else:
            sentences.append(
                "Không ghi nhận tín hiệu bất thường về khiếu nại, liên hệ CSKH hay sự cố kỹ thuật "
                "trước thời điểm rời mạng."
            )

        sentences.append(facts['insight'])
        return " ".join(sentences)

    def _get_evidence_bullets(self, p: dict, global_means: dict, top_n: int = 3) -> list:
        """Real evidence bullets only — top_n strongest feature deviations (already computed by
        _top_signals) plus the dominant service usage if present. Never fabricated commentary."""
        bullets = []
        # Churn-driver narrative (POST_CHURN only) leads the list — it's the single most important
        # sentence for a churned-customer persona, ahead of raw feature deviations.
        if p.get('churn_driver_evidence'):
            bullets.append(p['churn_driver_evidence'])
        means = self._get_means(p)
        if means:
            for f, val, g_val, _ in self._top_signals(means, global_means, top_n=top_n):
                bullets.append(self._get_business_signal(f, val, g_val))
        profile = p.get('profile_attributes') or {}
        svc_comp = profile.get('service_composition')
        svc_desc = self._describe_composition(svc_comp) if svc_comp else ""
        if svc_desc:
            bullets.append(svc_desc[0].upper() + svc_desc[1:])
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
        # " - Nhóm {idx}" là hậu tố PHÂN BIỆT do dedup logic ở prompts.py tự thêm khi 2 cụm khác
        # nhau lỡ nhận cùng 1 tên gốc từ apply_business_rules (vd cả 2 đều fallback "Nhóm hành vi ổn
        # định" dù feature/risk hoàn toàn khác nhau) — verifier CHỈ pass vì 2 tên JSON thực sự khác
        # nhau nhờ hậu tố này. TUYỆT ĐỐI KHÔNG được xoá trắng như "- Cluster"/"- Rank" (những hậu tố
        # kỹ thuật thuần tuý không mang nghĩa) — ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: xoá trắng làm 2 persona
        # hiện ra y hệt nhau ở report dù verifier đã pass đúng vì chúng khác nhau. Giữ lại dưới dạng
        # số thứ tự ngắn gọn "(idx)" thay vì xoá hẳn.
        m = re.search(r" - Nhóm (\d+)$", name)
        if m:
            name = f"{name[:m.start()].strip()} ({m.group(1)})"
        if " - Rank" in name:
            name = name.split(" - Rank")[0].strip()
        return name

    def format_support(self, support: int) -> str:
        if support >= 1000:
            return f"≈{support/1000:.1f}k KH"
        return f"{support} KH"

    def _build_executive_headline(self, personas_data: list) -> str:
        """Deterministic, Python-computed lead sentence — never LLM-authored (anti-hallucination).
        A CEO wants the concrete split up front (e.g. '92.8% stable, 7.2% driving CS/complaint
        load'), not generic scene-setting prose like 'sự phân hóa rõ rệt trong hành vi...'."""
        # POST_CHURN: "risk"/"stable" framing is meaningless (the whole sample already left) — lead
        # with a FULL breakdown of every distinct churn-driver group and its %, not just "top
        # identified vs rest" — a CEO needs to see ALL the actionable buckets, not just the
        # biggest one, to know how many separate interventions are actually on the table.
        if any(p.get('churn_driver') for p in personas_data):
            total_customers = sum(p.get('support', 0) for p in personas_data)
            total_str = f"{total_customers:,}".replace(",", ".")
            n_personas = len(personas_data)

            driver_groups = {}
            for p in personas_data:
                driver = p.get('churn_driver') or "Không rõ nguyên nhân hành vi"
                conf = p.get('churn_driver_confidence', 'LOW')
                g = driver_groups.setdefault(driver, {'pct': 0.0, 'confidence': conf})
                g['pct'] += p.get('support_pct', 0) * 100

            sorted_drivers = sorted(driver_groups.items(), key=lambda kv: -kv[1]['pct'])
            lines = [f"**{total_str} khách hàng rời mạng**, chia thành **{n_personas} nhóm hành vi**."]
            for driver, info in sorted_drivers:
                clause = _CHURN_DRIVER_NARRATIVE_CLAUSE.get(driver, driver.lower())
                lines.append(f"Khoảng **{info['pct']:.0f}%** rời mạng sau khi {clause}.")

            actionable = sum(1 for info in driver_groups.values() if info['confidence'] == 'MEDIUM')
            if actionable > 0:
                lines.append(f"→ Có ít nhất **{actionable} nguyên nhân** doanh nghiệp có thể chủ động can thiệp.")
            else:
                lines.append("→ Không có nguyên nhân hành vi rõ ràng để can thiệp trực tiếp — cần xem xét yếu tố ngoài hành vi (giá cước, đối thủ cạnh tranh...).")
            return " ".join(lines)

        at_risk = [p for p in personas_data if p.get('risk') in ('HIGH', 'EXTREME') or p.get('severity') in ('HIGH', 'EXTREME')]
        at_risk_ids = {p.get('cluster_id') for p in at_risk}
        stable = [p for p in personas_data if p.get('cluster_id') not in at_risk_ids]
        stable_pct = sum(p.get('support_pct', 0) for p in stable) * 100
        at_risk_pct = sum(p.get('support_pct', 0) for p in at_risk) * 100

        if at_risk and stable:
            at_risk_sorted = sorted(at_risk, key=lambda p: -p.get('support_pct', 0))
            at_risk_names = ", ".join(self.clean_persona_name(p.get('persona_name', '')) for p in at_risk_sorted[:2])
            return (f"**{stable_pct:.1f}% khách hàng đang ở trạng thái ổn định.** Tuy nhiên "
                    f"**{at_risk_pct:.1f}%** còn lại ({at_risk_names}) đang tạo ra phần lớn áp lực "
                    f"CSKH/khiếu nại và cần hành động ưu tiên.")
        if at_risk:
            return f"**{at_risk_pct:.1f}% khách hàng** đang thuộc nhóm rủi ro cao, cần hành động ưu tiên ngay."
        return f"**{stable_pct:.1f}% khách hàng** đang ở trạng thái ổn định, không phát hiện nhóm rủi ro cao nào."

    def _qualitative_magnitude(self, val: float, global_mean: float) -> tuple:
        """Bucket a REAL (val, global_mean) deviation into a qualitative Vietnamese phrase — NO
        raw %/ratio number attached. Mirrors the target persona-card style (vd 'Có xu hướng sử
        dụng giảm nhẹ trong 3 tháng gần nhất', 'Xu hướng sử dụng không còn ổn định và giảm mạnh')
        where every bullet is a plain business statement, never a "gấp X lần trung bình" figure.
        Returns (direction, phrase) where direction is 'up'/'down'/'flat'."""
        delta_pct = ((val - global_mean) / abs(global_mean)) * 100 if global_mean != 0 else val * 100
        abs_pct = abs(delta_pct)
        if abs_pct < 20:
            return ('flat', 'ổn định')
        direction = 'up' if delta_pct > 0 else 'down'
        if abs_pct >= 200:
            return (direction, 'rất mạnh')
        if abs_pct >= 75:
            return (direction, 'mạnh')
        return (direction, 'nhẹ')

    def _get_business_signal(self, feature: str, val: float, global_mean: float) -> str:
        """SEMANTIC LAYER: Converts feature and data into concrete, qualitative business signals —
        no raw %/ratio numbers (matches the target persona-card style: plain statements like "Có
        lịch sử tăng giá gói cước", "Đa số là KH Combo Net Pay", never "tăng gấp X lần trung bình")."""
        key = str(feature).lower()
        base_name = _FEATURE_SEMANTIC_MAP_LOWER.get(key) or _pattern_semantic_name(key) or feature

        # Handle the magic 999
        if val in [999, 999.0, 888, 888.0, 500.0, 500.95, 887, 886.77, 898.38, 898.34]:
            if 'call' in key:
                return "Không phát sinh liên hệ trong kỳ"
            # "cl" = sự cố kỹ thuật (Checklist), KHÔNG PHẢI "complaint" (phàn nàn/khiếu nại) — 2 cột
            # khác nhau trong dataset (xem cảnh báo tương tự ở FEATURE_SEMANTIC_MAP phía trên). PHẢI
            # check "complaint" TRƯỚC "cl" — "declining_complaint" chứa substring "cl" (từ
            # "de-CL-ining"), nên check 'cl' trước sẽ nhận nhầm cột complaint thành cột sự cố kỹ thuật.
            if 'complaint' in key:
                return "Không có khiếu nại trong kỳ"
            if 'cl' in key:
                return "Không có sự cố kỹ thuật trong kỳ"
            return "Chưa có dữ liệu"

        # Handle Boolean 1.0 flags
        if val == 1.0 and ("no_" in key or "escalating_" in key or "declining_" in key):
            return f"Có lịch sử {base_name.lower()}"
        if val == 0.0 and ("no_" in key):
            return f"Có phát sinh {base_name.lower()}"

        direction, mag = self._qualitative_magnitude(val, global_mean)

        if key in _DIRECTIONAL_FLAG_FEATURES:
            # base_name đã tự mang hướng (vd "Chi tiêu đang giảm") — độ lệch ở đây nói về MỨC ĐỘ
            # PHỔ BIẾN của tín hiệu đó trong cụm này so với toàn quần thể, không phải hướng thứ 2.
            if direction == 'up' and mag == 'rất mạnh':
                return f"{base_name} — phổ biến hơn hẳn trong nhóm này"
            elif direction == 'up':
                return f"{base_name} — phổ biến hơn trung bình"
            elif direction == 'down' and mag == 'rất mạnh':
                return f"{base_name} — hiếm gặp trong nhóm này"
            elif direction == 'down':
                return f"{base_name} — ít phổ biến hơn trung bình"
            else:
                return f"{base_name} — ở mức trung bình"

        if direction == 'flat':
            return f"{base_name} ổn định so với trung bình"
        verb = "tăng" if direction == 'up' else "giảm"
        # base_name đã bắt đầu bằng "Xu hướng ..." (vd "Xu hướng sự cố kỹ thuật") thì KHÔNG thêm
        # "có xu hướng" nữa — tránh câu lặp nghĩa "Xu hướng X có xu hướng giảm".
        if str(base_name).startswith("Xu hướng"):
            return f"{base_name} {verb} {mag}"
        return f"{base_name} có xu hướng {verb} {mag}"

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

    def _get_feature_val(self, p: dict, keywords: list) -> float:
        """Đọc trực tiếp 1 giá trị feature_means/evidence theo substring keyword — dùng cho các
        feature phụ (active_call_months, call_recent_only...) mà domain_signature không giữ lại
        (domain_signature chỉ giữ top-2 feature lệch NHIỀU NHẤT mỗi domain, các feature phụ khác bị
        bỏ phí dù vẫn có trong feature_means/evidence gốc)."""
        means = p.get('feature_means') or p.get('evidence') or {}
        for f, v in means.items():
            if any(kw in str(f).lower() for kw in keywords):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    def _build_customer_profile_bullets(self, p: dict, global_means: dict = None) -> list:
        """Qualitative persona summary (Adobe/Salesforce-style) — derived from domain_signature
        stars, profile_attributes and onset_sequence. Deliberately NOT just 2 bullets — a real
        profile needs enough dimensions (value/usage/loyalty/segment/complaint/technical/service/
        sequencing) that a reader can actually picture the customer, not just skim raw numbers."""
        domain_sig = p.get('domain_signature') or {}

        def stars(dom):
            info = domain_sig.get(dom)
            if isinstance(info, dict):
                return info.get('stars', 0)
            # Fallback ONLY when domain_signature is empty/missing (pipeline drift confirmed on a
            # live run: domain_signature was empty for every persona even though feature_means had
            # clear signal — every domain silently defaulted to "not notable", producing FACTUALLY
            # WRONG bullets like "ít khi liên hệ CSKH" for a persona with a 20x call-volume spike).
            # Derive an equivalent star rating directly from feature_means/global_means instead of
            # defaulting to 0, so Customer Profile never contradicts the Business Signals above it.
            means = p.get('feature_means') or p.get('evidence') or {}
            if not means or not global_means:
                return 0
            kws = _PROFILE_DOMAIN_FALLBACK_KEYWORDS.get(dom, [])
            max_dev = 0.0
            for f, v in means.items():
                if not any(kw in f.lower() for kw in kws):
                    continue
                g = global_means.get(f, 0)
                dev = (v - g) / abs(g) if g != 0 else v
                if dev > max_dev:
                    max_dev = dev
            return 5 if max_dev >= 5.0 else 4 if max_dev >= 2.0 else 3 if max_dev >= 0.75 else 2 if max_dev >= 0.25 else 1

        bullets = []
        value_stars = stars('value')
        if value_stars >= 4:
            bullets.append("ARPU/cước phí cao hơn hẳn trung bình — thuộc nhóm khách hàng giá trị cao")
        elif value_stars <= 1:
            bullets.append("ARPU/cước phí ở mức trung bình hoặc thấp")

        # LƯU Ý: profile_attributes là số liệu TRUNG BÌNH CẢ KỲ (1 snapshot), KHÔNG có so sánh
        # trước/sau — TUYỆT ĐỐI KHÔNG suy diễn thành câu CÓ THAY ĐỔI THEO THỜI GIAN kiểu "từng cao
        # nhưng đang giảm"/"trước khi rời mạng" nếu không có dữ liệu old/recent thực sự chứng minh
        # (đã xảy ra trên báo cáo thật: "Loyalty từng ở mức cao" chỉ suy từ LOYALTY_RANK=0.18 tại 1
        # thời điểm, không có bằng chứng nó "từng" cao hơn). Chỉ nói ở dạng TĨNH, đúng với 1 snapshot.
        profile = p.get('profile_attributes') or {}
        tier_downgrade = profile.get('tier_downgrade_rate', 0)
        tier_upgrade = profile.get('tier_upgrade_rate', 0)
        if tier_downgrade >= 0.5:
            bullets.append("Tỷ lệ tụt hạng phân khúc (segment downgrade) cao hơn hẳn trung bình")
        elif tier_upgrade >= 0.5:
            bullets.append("Tỷ lệ nâng hạng phân khúc (segment upgrade) cao hơn hẳn trung bình")

        loyalty = profile.get('loyalty_rank_avg')
        if loyalty is not None:
            if value_stars >= 3 and loyalty < 0.3:
                bullets.append("Mức độ gắn bó/loyalty (hạng thân thiết) thấp hơn trung bình, dù thuộc nhóm chi tiêu cao")
            elif loyalty >= 1.0:
                bullets.append("Mức độ gắn bó/loyalty ở mức khá")

        usage_stars = stars('usage')
        if usage_stars >= 4:
            bullets.append("Hành vi sử dụng dịch vụ suy giảm rõ rệt trong giai đoạn gần rời mạng")
        elif usage_stars <= 1:
            bullets.append("Hành vi sử dụng dịch vụ ổn định, không suy giảm rõ rệt")

        complaint_stars, call_stars, missed_stars, technical_stars = stars('complaint'), stars('call'), stars('missed'), stars('technical')
        if complaint_stars >= 3:
            bullets.append("Có lịch sử khiếu nại/phàn nàn đáng kể")
        if technical_stars >= 3:
            bullets.append("Từng gặp sự cố kỹ thuật nhiều hơn trung bình")
        if call_stars >= 3 or missed_stars >= 3:
            # active_*_months (persistent qua nhiều tháng) vs *_recent_only (chỉ mới phát sinh gần
            # đây) đổi câu generic "cao hơn trung bình" thành câu có Ý NGHĨA NGHIỆP VỤ khác nhau —
            # 1 khách gọi CSKH đều đặn 4-6 tháng liền là câu chuyện khác hẳn 1 khách chỉ mới gọi gần
            # đây (và feature_means/evidence đã sẵn có active_call_months/call_recent_only, trước
            # đây bị bỏ phí, chỉ dùng 1 câu chung chung như nhau cho cả 2 trường hợp).
            active_months = self._get_feature_val(p, ['active_call_months', 'active_missed_months'])
            recent_only = self._get_feature_val(p, ['call_recent_only', 'missed_recent_only'])
            if active_months is not None and active_months >= 3:
                bullets.append("Cường độ liên hệ CSKH/cuộc gọi nhỡ cao và LIÊN TỤC trong nhiều tháng, không chỉ phát sinh nhất thời")
            elif recent_only is not None and recent_only >= 0.5 and complaint_stars <= 2:
                bullets.append("Chủ yếu phát sinh liên hệ CSKH/cuộc gọi nhỡ trong giai đoạn gần đây, nhưng chưa chuyển thành khiếu nại chính thức")
            else:
                bullets.append("Tần suất liên hệ CSKH/cuộc gọi nhỡ cao hơn trung bình")
        if complaint_stars <= 1 and call_stars <= 1 and missed_stars <= 1 and technical_stars <= 1:
            bullets.append("Ít khi liên hệ CSKH hoặc khiếu nại trong suốt vòng đời")

        # Trình tự tín hiệu — CHỈ dùng dữ liệu THẬT có (old vs recent), không suy diễn timeline
        # theo tháng chính xác (dữ liệu chỉ có 2 giai đoạn, không có lưới thời gian chi tiết hơn).
        onset = p.get('onset_sequence') or []
        signaled = [t for t in onset if isinstance(t, dict) and (t.get('old', 0) > 0 or t.get('recent', 0) > 0)]
        if len(signaled) >= 2 and signaled[0].get('metric') != signaled[-1].get('metric'):
            bullets.append(f"Trình tự tín hiệu: {signaled[0].get('metric', 'N/A')} xuất hiện sớm nhất, {signaled[-1].get('metric', 'N/A')} chỉ mới xuất hiện gần đây trước khi rời mạng")

        svc_comp = profile.get('service_composition')
        svc_desc = self._describe_composition(svc_comp) if svc_comp else ""
        if svc_desc:
            bullets.append(svc_desc[0].upper() + svc_desc[1:])

        return bullets

    def _get_domain_signals(self, p: dict, global_means: dict) -> list:
        """Groups evidence by behavioral domain (complaint/call/missed/technical/usage/value)
        instead of a flat top-3 ranking — a persona defined by ONE dominant column reads as a
        single-cause label ("Sự cố cấp tính"), while the SAME persona described across domains
        (complaint=5★, technical=4★, value=5★, usage=1★) lets the narrative connect them into a
        real story ("khách hàng giá trị cao gặp sự cố kỹ thuật + khiếu nại dồn dập, usage vẫn ổn
        định -> nguyên nhân nhiều khả năng là chất lượng dịch vụ, không phải nhu cầu suy giảm")."""
        domain_sig = p.get('domain_signature') or {}
        if not domain_sig:
            return []
        domains = []
        low_domains = []  # domain rõ ràng THẤP (1★) — dùng làm đối chứng tường minh cho LLM, thay
                           # vì để LLM tự suy đoán "không nhắc tới = bình thường".
        for dom, info in domain_sig.items():
            if not isinstance(info, dict):
                continue
            stars = info.get('stars', 0)
            if stars <= 1:
                low_domains.append(dom)
                continue
            if stars < 2:
                continue
            evidence = []
            for feat in info.get('top_features', []):
                # top_features do LLM copy-paste sinh ra — phòng thủ nếu thiếu phần tử thay vì
                # IndexError làm sập toàn bộ báo cáo.
                if not isinstance(feat, (list, tuple)) or len(feat) < 3:
                    continue
                f, val, g_val = feat[0], feat[1], feat[2]
                evidence.append(self._get_business_signal(f, val, g_val))
            if evidence:
                domains.append({'domain': dom, 'stars': stars, 'evidence': evidence})
        domains.sort(key=lambda d: -d['stars'])
        if domains and low_domains:
            domains.append({'domain_contrast_note': f"Các domain sau ở mức BÌNH THƯỜNG (1★, dùng làm đối chứng, KHÔNG suy diễn thêm): {', '.join(low_domains)}"})
        return domains

    def _build_profile_context(self, p: dict) -> dict:
        """SUPPORTING/CONTEXT facts from profile_attributes (ARPU, loyalty, tier upgrade/downgrade,
        service/package mix) — domain_signals alone only carries whichever 1-2 features had the
        strongest deviation per domain, so ARPU/loyalty/service mix were NEVER reaching the LLM at
        all (persona_interpretation could only ever reference call/missed/usage/complaint, never
        "ARPU trung bình 650k" or "chủ yếu dùng Net Pay 62%" — exactly what was reported missing)."""
        profile = p.get('profile_attributes') or {}
        ctx = {}
        if 'avg_fee' in profile:
            ctx['arpu_trung_binh'] = profile['avg_fee']
        if 'high_spender_pct' in profile:
            ctx['ty_le_chi_tieu_cao'] = profile['high_spender_pct']
        if 'loyalty_rank_avg' in profile:
            ctx['hang_loyalty_trung_binh'] = profile['loyalty_rank_avg']
        if 'tier_upgrade_rate' in profile:
            ctx['ty_le_nang_hang_phan_khuc'] = profile['tier_upgrade_rate']
        if 'tier_downgrade_rate' in profile:
            ctx['ty_le_tut_hang_phan_khuc'] = profile['tier_downgrade_rate']
        if 'usage_decline_strong_pct' in profile:
            ctx['ty_le_giam_su_dung_manh'] = profile['usage_decline_strong_pct']
        if 'csat_avg' in profile:
            ctx['csat_trung_binh'] = profile['csat_avg']
        if 'ces_avg' in profile:
            ctx['ces_trung_binh'] = profile['ces_avg']
        svc = profile.get('service_composition')
        if svc:
            top_svc = sorted(svc.items(), key=lambda kv: -kv[1])[:2]
            ctx['dich_vu_chinh'] = [f"{k} ({v * 100:.0f}%)" for k, v in top_svc]
        pkg = profile.get('package_composition')
        if pkg:
            top_pkg = sorted(pkg.items(), key=lambda kv: -kv[1])[:2]
            ctx['goi_cuoc_chinh'] = [f"{k} ({v * 100:.0f}%)" for k, v in top_pkg]
        return ctx

    def _compute_profile_global(self, personas_data: list) -> dict:
        """Trung bình CÓ TRỌNG SỐ (theo support) của profile_attributes trên TOÀN BỘ personas —
        dùng làm baseline để tìm feature nào phân biệt 1 cụm rõ nhất so với các cụm còn lại (phục vụ
        _distinguishing_suffix, thay thế hậu tố số thứ tự (1)/(2) vô nghĩa khi 2+ persona trùng tên
        gốc — ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: 2 cụm rất khác nhau về ARPU/loyalty/downgrade nhưng cùng
        tên, chỉ phân biệt được bằng số thứ tự chứ không phải đặc trưng thật)."""
        keys = ['avg_fee', 'high_spender_pct', 'loyalty_rank_avg', 'tier_downgrade_rate', 'tier_upgrade_rate']
        out = {}
        for k in keys:
            weighted_sum, weight = 0.0, 0.0
            for p in personas_data:
                profile = p.get('profile_attributes') or {}
                if k not in profile:
                    continue
                sup = p.get('support', 0)
                weighted_sum += profile[k] * sup
                weight += sup
            if weight > 0:
                out[k] = weighted_sum / weight
        return out

    def _distinguishing_suffix(self, p: dict, profile_global: dict) -> str:
        """Trả về cụm từ NGẮN mô tả feature lệch NHIỀU NHẤT so với baseline toàn quần thể (vd 'ARPU
        cao hơn', 'loyalty thấp hơn') — dùng làm hậu tố phân biệt persona theo ĐẶC TRƯNG THẬT thay vì
        số thứ tự vô nghĩa. Trả về "" nếu không có feature nào lệch đủ rõ (>=15%)."""
        profile = p.get('profile_attributes') or {}

        def rel_dev(key):
            g = profile_global.get(key, 0)
            v = profile.get(key, 0)
            return (v - g) / abs(g) if g != 0 else 0.0

        labels = {
            'avg_fee': ("ARPU cao hơn", "ARPU thấp hơn"),
            'high_spender_pct': ("tỷ lệ chi tiêu cao hơn", "tỷ lệ chi tiêu thấp hơn"),
            'loyalty_rank_avg': ("loyalty cao hơn", "loyalty thấp hơn"),
            'tier_downgrade_rate': ("tỷ lệ downgrade cao hơn", "tỷ lệ downgrade thấp hơn"),
            'tier_upgrade_rate': ("tỷ lệ upgrade cao hơn", "tỷ lệ upgrade thấp hơn"),
        }
        candidates = []
        for key, (label_up, label_down) in labels.items():
            if key not in profile:
                continue
            d = rel_dev(key)
            if abs(d) >= 0.15:
                candidates.append((abs(d), label_up if d > 0 else label_down))
        if not candidates:
            return ""
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]

    def _disambiguate_display_names(self, personas_data: list) -> dict:
        """Map cluster_id -> tên hiển thị CUỐI CÙNG. Khi 2+ persona trùng tên gốc (churn_driver nếu
        có, hoặc clean_persona_name), thay vì hậu tố số thứ tự "(N)" vô nghĩa, gắn thêm feature THẬT
        phân biệt nhất của từng cụm (vd "— ARPU cao hơn" / "— loyalty thấp hơn"). Nếu không tìm được
        feature nào đủ rõ, fallback về số thứ tự để đảm bảo KHÔNG BAO GIỜ có 2 tên hiển thị giống hệt
        nhau (an toàn hơn là để trống)."""
        profile_global = self._compute_profile_global(personas_data)
        base_names = {}
        for p in personas_data:
            cid = p.get('cluster_id')
            # Anomaly cluster (<1% data) PHẢI giữ tên riêng "Hành vi bất thường" — không gộp nhóm
            # theo churn_driver dù có thể trùng với 1 cụm bình thường khác (ANOMALY GATE: không bao
            # giờ đặt tên persona bình thường cho cụm quá nhỏ).
            churn_driver = None if p.get('is_anomaly') else p.get('churn_driver')
            # churn_driver không khớp danh sách đã biết (pipeline LLM tự sinh 1 chuỗi vô nghĩa, vd
            # "Dựa trên hành vi quan sát được từ hệ thống CSKH" — ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT) -> suy
            # ra lại tên TỪ domain_signature/profile_attributes thay vì dùng chuỗi rác làm tên persona
            # (dùng CHUNG hàm _compose_fallback_driver với _build_persona_story để tên và story luôn
            # khớp nhau, không lệch pha).
            if churn_driver and churn_driver not in _CHURN_DRIVER_NARRATIVE_CLAUSE:
                churn_driver = self._compose_fallback_driver(p)['name']
            base_names[cid] = churn_driver or self.clean_persona_name(p.get('persona_name', ''))

        groups = {}
        for cid, base in base_names.items():
            groups.setdefault(base, []).append(cid)

        display = {}
        for base, cids in groups.items():
            if len(cids) == 1:
                display[cids[0]] = base
                continue
            used_suffixes = set()
            for idx, cid in enumerate(cids, start=1):
                p = next((pp for pp in personas_data if pp.get('cluster_id') == cid), {})
                suffix = self._distinguishing_suffix(p, profile_global)
                if suffix and suffix not in used_suffixes:
                    used_suffixes.add(suffix)
                    display[cid] = f"{base} — {suffix}"
                else:
                    display[cid] = f"{base} ({idx})"
        return display

    def _flip_minority_pct(self, pct: float, label_pos: str, label_neg: str):
        """Đồng bộ với QUY TẮC XOAY CHIỀU % trong _build_prompt (áp dụng cho path LLM) — bản Python
        dùng cho fallback KHÔNG LLM, để hành vi giống hệt nhau dù narrative đến từ LLM hay từ
        fallback. Nêu thẳng 1 tỷ lệ THIỂU SỐ (<40%) kèm nhãn dương tính dễ đọc nhầm thành đặc trưng
        của CẢ nhóm. NẾU pct < 40%: xoay ngược thành phần bù (>=50%, luôn là ĐA SỐ thật) + đổi sang
        `label_neg` — PHẢI là 1 phạm trù thực chất đối lập/trung tính (vd "giá trị thấp, trung bình"),
        KHÔNG PHẢI phủ định đơn thuần kiểu "không {label_pos}" (phủ định suông không nói rõ nhóm này
        THỰC SỰ là gì). NẾU >=40%: giữ nguyên. Trả về (pct_hiển_thị, nhãn_hiển_thị)."""
        if pct < 0.4:
            return 1 - pct, label_neg
        return pct, label_pos

    def _describe_composition(self, comp: dict, noun: str = "dịch vụ", top_n: int = 3) -> str:
        """Cùng tinh thần với _flip_minority_pct nhưng cho composition dict ({category: fraction},
        vd service_composition/package_composition hoặc field tương tự trong tương lai) — generic
        cho MỌI field composition, không riêng dịch vụ. Trước đây code luôn lấy category % LỚN
        NHẤT rồi gọi thẳng là "chủ yếu"/"đa số", bất kể mục đó có thực sự áp đảo hay không — nếu
        phân bố khá đều (vd Net Pay 24%, Mobile Pay 23%, Bank 21%...) thì gọi Net Pay là "chủ yếu"
        đánh lừa người đọc, vì 76% KH KHÔNG dùng Net Pay và không mục nào thực sự chiếm đa số. Chỉ
        gọi mục đứng đầu là "chủ yếu" khi nó THỰC SỰ áp đảo (>=40%, cùng ngưỡng với QUY TẮC XOAY
        CHIỀU %); nếu không, mô tả trung thực là dùng đa dạng/không tập trung, kèm số liệu thật.
        Trả về "" nếu comp rỗng."""
        if not comp:
            return ""
        items = sorted(comp.items(), key=lambda kv: -kv[1])
        top1_name, top1_pct = items[0]
        if top1_pct >= 0.4:
            return f"chủ yếu sử dụng {noun} {top1_name} ({top1_pct * 100:.0f}%)"
        listed = ", ".join(f"{k} ({v * 100:.0f}%)" for k, v in items[:top_n])
        return f"sử dụng đa dạng {noun}, không tập trung vào 1 {noun} cụ thể ({listed})"

    def _compose_profile_value_sentence(self, profile_context: dict, svc_comp: dict = None) -> str:
        """Deterministic (no-LLM) 'Customer Value' opening sentence from profile_context — ARPU,
        % chi tiêu cao, tỷ lệ tụt/nâng hạng, loyalty, dịch vụ chính. Dùng làm fallback khi LLM
        narrative không khả dụng, để layer Insight không bao giờ biến mất khỏi report chỉ vì LLM
        timeout/lỗi kết nối (đã xảy ra nhiều lần trên live run)."""
        parts = []
        high_pct = profile_context.get('ty_le_chi_tieu_cao')
        arpu = profile_context.get('arpu_trung_binh')
        if high_pct is not None:
            high_pct, high_label = self._flip_minority_pct(high_pct, "giá trị cao", "giá trị thấp, trung bình")
        if high_pct is not None and arpu is not None:
            parts.append(f"tỷ lệ khách hàng {high_label} khoảng {high_pct * 100:.0f}%, mức cước trung bình khoảng {arpu / 1000:.0f} nghìn đồng/tháng")
        elif arpu is not None:
            parts.append(f"mức cước trung bình khoảng {arpu / 1000:.0f} nghìn đồng/tháng")
        elif high_pct is not None:
            parts.append(f"tỷ lệ khách hàng {high_label} khoảng {high_pct * 100:.0f}%")

        downgrade = profile_context.get('ty_le_tut_hang_phan_khuc')
        upgrade = profile_context.get('ty_le_nang_hang_phan_khuc')
        if downgrade is not None and downgrade >= 0.2:
            parts.append("số lần tụt hạng phân khúc cao hơn mặt bằng chung")
        elif upgrade is not None and upgrade >= 0.2:
            parts.append("số lần nâng hạng phân khúc cao hơn mặt bằng chung")

        # Trước đây field này chỉ tồn tại trong profile_context cho LLM đọc, KHÔNG được dùng ở
        # fallback deterministic — nhóm "Behavior" trong câu bị thiếu tín hiệu giảm sử dụng dù dữ
        # liệu đã có sẵn.
        usage_decline = profile_context.get('ty_le_giam_su_dung_manh')
        if usage_decline is not None and usage_decline >= 0.2:
            parts.append("tỷ lệ giảm sử dụng mạnh cao hơn mặt bằng chung")

        loyalty = profile_context.get('hang_loyalty_trung_binh')
        if loyalty is not None and loyalty >= 1.0:
            parts.append("hạng khách hàng thân thiết ở mức khá")

        svc_desc = self._describe_composition(svc_comp) if svc_comp else ""
        if svc_desc:
            parts.append(svc_desc)

        if not parts:
            return ""
        return "Nhóm này có " + ", ".join(parts) + "."

    def _compose_deterministic_insight(self, p: dict, global_means: dict) -> str:
        """Fallback 'Insight' đoạn văn (layer 4/4: Trigger → Value → Behavior → Insight) dùng KHI
        LLM narrative thất bại/timeout — ghép từ profile_context + contradictions đã tính sẵn
        (100% deterministic, không gọi LLM). Trước đây khi LLM lỗi, Business Interpretation biến
        mất hoàn toàn khỏi report (chỉ còn Business Signals top-3 rời rạc) — đây là fallback để
        layer insight luôn có mặt, kể cả khi generate_llm_narrative() raise exception."""
        profile_context = self._build_profile_context(p)
        value_sentence = self._compose_profile_value_sentence(
            profile_context, (p.get('profile_attributes') or {}).get('service_composition'))

        contradictions = self._detect_contradictions(p)
        if contradictions:
            c = contradictions[0]
            insight_sentence = "Song song đó, " + c[0].lower() + c[1:] + "."
        else:
            domain_signals = self._get_domain_signals(p, global_means)
            top = next((d for d in domain_signals if 'domain' in d), None)
            if top and top.get('evidence'):
                ev = top['evidence'][0]
                insight_sentence = "Song song đó, " + ev[0].lower() + ev[1:] + "."
            else:
                insight_sentence = ""

        return " ".join(s for s in (value_sentence, insight_sentence) if s)

    def _detect_contradictions(self, p: dict) -> list:
        """Deterministically flags TENSION pairs (vd ARPU cao + complaint cao, loyalty cao +
        tương tác giảm) — đây chính là kiểu câu 'Mặc dù... vẫn... Điều này cho thấy...' mà lãnh đạo
        thích đọc nhất, nhưng nếu để LLM tự tìm thì không ổn định — tính sẵn ở đây để LLM chỉ cần
        DIỄN GIẢI thành câu, không phải tự suy luận từ số liệu rời rạc."""
        domain_sig = p.get('domain_signature') or {}
        profile = p.get('profile_attributes') or {}

        def stars(dom):
            info = domain_sig.get(dom)
            return info.get('stars', 0) if isinstance(info, dict) else 0

        value_high = stars('value') >= 3 or profile.get('high_spender_pct', 0) >= 0.4
        complaint_high = stars('complaint') >= 3
        technical_high = stars('technical') >= 3
        call_high = stars('call') >= 3 or stars('missed') >= 3
        usage_declining = stars('usage') >= 3
        loyalty_high = profile.get('loyalty_rank_avg', 0) >= 1.0

        contradictions = []
        if value_high and (complaint_high or technical_high):
            # Hedge ("nhiều khả năng là yếu tố góp phần") thay vì khẳng định thẳng "đang ảnh hưởng" —
            # chuỗi này được dùng NGUYÊN VĂN (không qua LLM diễn giải lại) trong fallback deterministic
            # _compose_deterministic_insight, nên bản thân câu FACT gốc cũng phải hedge sẵn.
            contradictions.append("ARPU/giá trị cao NHƯNG complaint hoặc sự cố kỹ thuật cũng cao — trải nghiệm dịch vụ chưa tốt nhiều khả năng là yếu tố góp phần ảnh hưởng ngay cả nhóm khách hàng giá trị cao")
        if loyalty_high and (call_high or usage_declining):
            contradictions.append("Loyalty cao NHƯNG mức độ tương tác/sử dụng đang giảm — có thể là dấu hiệu suy giảm âm thầm dù khách hàng vẫn trung thành")
        if value_high and usage_declining and not (complaint_high or technical_high or call_high):
            contradictions.append("Giá trị cao NHƯNG usage giảm, KHÔNG có complaint/sự cố kỹ thuật đi kèm — nguyên nhân nhiều khả năng KHÔNG phải chất lượng dịch vụ")
        return contradictions

    def _build_prompt(self, personas_data: list, global_means: dict) -> str:
        """Prepares a heavily sterilized JSON for the LLM"""
        clean_data = []
        for p in personas_data:
            c = {}
            c['persona'] = self.clean_persona_name(p.get('persona_name', ''))
            # Đánh dấu persona ĐÃ RỜI MẠNG (churn_driver chỉ được gán ở mode POST_CHURN) để LLM biết
            # dùng framing QUÁ KHỨ thay vì "đang có nguy cơ rời mạng" — xem QUY TẮC THÌ/FRAMING bên
            # dưới.
            if p.get('churn_driver'):
                c['already_churned'] = True
                # Đưa đúng bộ FACT đã tính sẵn (_build_persona_story_facts — CÙNG hàm dùng cho bản
                # fallback deterministic ở dưới) để LLM diễn đạt lại TỰ NHIÊN/ĐA DẠNG hơn thay vì lộ
                # rõ 1 khuôn câu giống hệt nhau ở mọi persona (đã bị phát hiện trên báo cáo thật: 3
                # persona liền nhau đọc y hệt cấu trúc "Nhóm này có tỷ lệ... mức cước... chủ yếu sử
                # dụng..."). LLM KHÔNG được bịa số liệu ngoài các facts này — xem QUY TẮC CHURN_STORY_
                # FACTS bên dưới.
                facts = self._build_persona_story_facts(p, global_means)
                if facts:
                    c['churn_story_facts'] = {
                        'quy_mo': f"Khoảng {facts['support']:,} khách hàng ({facts['support_pct']*100:.1f}%)".replace(",", "."),
                        'ly_do_roi_mang': facts['clause'],
                        'thong_tin_gia_tri_hanh_vi_dich_vu': facts['value_sentence'] or None,
                        'tin_hieu_hanh_vi_manh_nhat': facts['signal_clause'] or "không có tín hiệu hành vi nào cao hơn rõ rệt so với trung bình",
                        'ket_luan_goi_y': facts['insight'],
                    }

            domain_signals = self._get_domain_signals(p, global_means)
            if domain_signals:
                c['domain_signals'] = domain_signals
                # Trình tự tín hiệu (chỉ old vs recent — KHÔNG phải lưới thời gian theo tháng) để
                # LLM có thể viết câu có trình tự thay vì liệt kê domain không theo thứ tự nào.
                onset = p.get('onset_sequence') or []
                signaled = [t for t in onset if isinstance(t, dict) and (t.get('old', 0) > 0 or t.get('recent', 0) > 0)]
                if len(signaled) >= 2:
                    c['onset_order'] = [t.get('metric') for t in signaled]
                confidence_dev = domain_signals[0]['stars'] / 5.0
            else:
                # Fallback (no domain_signature in JSON — older run) — flat top-3 as before.
                means = self._get_means(p)
                deviations = self._top_signals(means, global_means, top_n=3) if means else []
                c['business_signals'] = [self._get_business_signal(f, val, g_val) for f, val, g_val, dev in deviations]
                confidence_dev = deviations[0][3] if deviations else 0

            profile_context = self._build_profile_context(p)
            if profile_context:
                c['profile_context'] = profile_context
            contradictions = self._detect_contradictions(p)
            if contradictions:
                c['contradictions'] = contradictions

            c['confidence'] = "High" if confidence_dev > 1.0 else "Medium"
            c['cluster_id'] = p.get('cluster_id')
            clean_data.append(c)

        data_str = json.dumps(clean_data, ensure_ascii=False, indent=2)
        return f"""
Bạn là Consultant tại Deloitte.
Nhiệm vụ: Viết diễn giải Báo cáo Chân dung Khách hàng bằng NGÔN NGỮ QUẢN TRỊ.

QUY TẮC CỨNG:
- KHÔNG sinh số liệu. KHÔNG nhắc lại số liệu.
- KHÔNG suy diễn ngoài Business Signals/domain_signals được cấp.
- KHÔNG đề xuất hành động mới (Action/Investigation).
- Độ dài: Tối đa 2 câu cho mỗi trường phân tích (business_interpretation được nới lên tối đa 3 câu
  KHI có `profile_context` — xem quy tắc riêng bên dưới).
- QUY TẮC CHURN_STORY_FACTS (ƯU TIÊN CAO NHẤT, đọc trước mọi quy tắc domain_signals/profile_context
  bên dưới): NẾU persona có `churn_story_facts`, đây là bộ FACT đã tính sẵn 100% chính xác (quy mô,
  lý do rời mạng, thông tin giá trị/hành vi/dịch vụ, tín hiệu hành vi mạnh nhất, kết luận gợi ý) —
  PHẢI dùng CHÍNH bộ facts này để viết business_interpretation, BỎ QUA hoàn toàn các quy tắc
  domain_signals/onset_order/contradictions bên dưới cho persona này (facts đã tổng hợp sẵn, không
  cần suy luận lại từ dữ liệu thô). Nhiệm vụ của bạn CHỈ là DIỄN ĐẠT LẠI các facts này thành 1 đoạn
  văn 3-4 câu TỰ NHIÊN — KHÔNG bịa thêm số liệu/domain/nguyên nhân ngoài facts đã cho, nhưng ĐƯỢC
  PHÉP đổi thứ tự câu, gộp câu, đổi từ nối, miễn giữ đúng Ý NGHĨA từng fact. Đây chính là điểm quan
  trọng nhất: KHÔNG được ghép các fact lại theo đúng 1 khuôn cố định giống hệt nhau ở mọi persona
  (vd luôn "Nhóm này có tỷ lệ... mức cước... chủ yếu sử dụng..." — đã bị phát hiện đọc rất máy móc
  trên báo cáo thật khi nhiều persona liên tiếp dùng y hệt cấu trúc này) — mỗi persona PHẢI đọc như
  1 đoạn phân tích RIÊNG, câu chữ/thứ tự khác nhau tuỳ persona, dù vẫn tôn trọng đúng dữ liệu. Ví dụ:
  churn_story_facts = {{"quy_mo": "Khoảng 1.346 khách hàng (2.5%)", "ly_do_roi_mang": "xuất hiện
  nhiều khiếu nại mới trong thời gian gần đây", "thong_tin_gia_tri_hanh_vi_dich_vu": "tỷ lệ khách
  hàng giá trị cao khoảng 42%, mức cước trung bình khoảng 220 nghìn đồng/tháng, chủ yếu sử dụng Net
  Pay (62%)", "tin_hieu_hanh_vi_manh_nhat": "xu hướng phàn nàn cao vượt trội", "ket_luan_goi_y":
  "Việc gia tăng khiếu nại ngay trước thời điểm rời mạng cho thấy trải nghiệm dịch vụ tiêu cực nhiều
  khả năng là yếu tố góp phần vào quyết định chấm dứt dịch vụ."}} → "Khoảng 1.346 khách hàng (2.5%)
  rời mạng ngay sau một đợt khiếu nại tăng đột biến. Đây là nhóm có giá trị tương đối cao (~42% chi
  tiêu cao, ARPU khoảng 220 nghìn đồng/tháng) và chủ yếu gắn với Net Pay (62%), nhưng mức độ phàn nàn
  lại vượt trội hẳn so với mặt bằng chung. Trải nghiệm dịch vụ tiêu cực nhiều khả năng là yếu tố góp
  phần trực tiếp vào quyết định rời mạng của nhóm này." (Lưu ý: thứ tự câu và cách nối đã thay đổi so
  với facts gốc, nhưng KHÔNG thêm số liệu nào ngoài facts).
- NẾU có `domain_signals` (nhiều domain, mỗi domain có "stars" 1-5): business_interpretation PHẢI
  LIÊN KẾT các domain có stars cao với nhau thành 1 câu chuyện — KHÔNG được chỉ mô tả 1 domain
  riêng lẻ. Ví dụ 1: complaint=5★ + technical=4★ + value=5★ + usage=1★ (thấp) → "Khách hàng giá trị
  cao gặp nhiều sự cố kỹ thuật và phát sinh khiếu nại dồn dập, trong khi hành vi sử dụng chưa suy
  giảm đáng kể — cho thấy nguyên nhân nhiều khả năng đến từ chất lượng dịch vụ hơn là thay đổi nhu
  cầu."
- BẮT BUỘC dùng văn phong TƯƠNG PHẢN (contrastive) khi 1 domain cao đi kèm nhiều domain thấp — đây
  là kiểu câu có giá trị business cao nhất. Ví dụ 2: value=5★, còn complaint/call/missed/technical
  đều thấp (xem `domain_contrast_note` nếu có) → "Mặc dù nhóm này gần như không phát sinh khiếu
  nại hay sự cố kỹ thuật, khách hàng vẫn quyết định rời mạng. Điều này cho thấy nguyên nhân nhiều
  khả năng KHÔNG nằm ở chất lượng dịch vụ, mà ở giá cước, chương trình cạnh tranh, hoặc thay đổi
  nhu cầu." KHÔNG viết câu chung chung kiểu "Khách hàng có giá trị cao, quan trọng với doanh thu"
  — câu đó không có insight, AI nào cũng viết được.
- CẤM các câu generic sau (và các biến thể tương đương) — đây là loại câu KHÔNG có insight, chỉ
  đổi tên persona vào là "an toàn" nhưng vô nghĩa với người đọc: "Khách hàng nhóm này có giá trị
  cao/quan trọng với doanh thu", "Cần theo dõi/quan tâm đặc biệt nhóm này", "Nhóm này thể hiện dấu
  hiệu bất thường". LUÔN nói CÁI GÌ xảy ra và HỆ QUẢ nghiệp vụ CỤ THỂ là gì.
- NẾU có `onset_order` (danh sách domain theo TRÌNH TỰ xuất hiện, domain đầu tiên xuất hiện SỚM
  NHẤT): PHẢI thể hiện trình tự này trong business_interpretation thay vì liệt kê domain không theo
  thứ tự. Ví dụ 3: onset_order = ["Cuộc gọi CSKH", "Phàn nàn/khiếu nại"] + value=5★ → "Nhóm này từng
  là khách hàng giá trị cao. Dấu hiệu liên hệ CSKH xuất hiện trước, sau đó mới đến khiếu nại, cho
  thấy vấn đề ban đầu không được xử lý dứt điểm dẫn đến bất mãn leo thang trước khi rời mạng."
  KHÔNG bịa mốc thời gian cụ thể (tháng -6, -3...) nếu không có trong dữ liệu — chỉ nói "trước/sau",
  "ban đầu/gần đây".
- `domain_contrast_note` (nếu có trong domain_signals) liệt kê các domain ở mức BÌNH THƯỜNG (1★) —
  dùng làm đối chứng tường minh, KHÔNG suy diễn thêm ngoài domain được liệt kê.
- NẾU có `profile_context` (ARPU, tỷ lệ chi tiêu cao, loyalty, tỷ lệ nâng/tụt hạng phân khúc, dịch vụ
  chính...): business_interpretation PHẢI MỞ ĐẦU bằng 1 câu mô tả nhóm khách hàng này là ai, dùng
  ĐÚNG các con số trong profile_context (không bịa, không làm tròn quá mức). Câu domain_signals/
  contrastive đứng SAU, nối bằng "Song song với đó," / "Đồng thời," / "Trong khi đó,". Ví dụ:
  profile_context = {{"arpu_trung_binh": 666198, "ty_le_chi_tieu_cao": 0.446,
  "ty_le_tut_hang_phan_khuc": 0.42}} + domain_signals cho thấy complaint tăng mạnh → "Nhóm này có tỷ
  lệ khách hàng giá trị cao gần 45%, mức cước trung bình khoảng 666 nghìn đồng và số lần tụt hạng
  phân khúc cao hơn mặt bằng chung. Song song với đó, số lượng khiếu nại và dấu hiệu leo thang khiếu
  nại tăng rất mạnh. Điều này cho thấy doanh nghiệp đang đánh mất những khách hàng có giá trị ngay
  sau các trải nghiệm dịch vụ tiêu cực." KHÔNG được bỏ qua profile_context và chỉ mô tả domain_signals
  như khi không có profile_context.
- QUY TẮC XOAY CHIỀU % (áp dụng cho MỌI trường tỷ lệ dạng phân số trong `profile_context`, vd
  `ty_le_chi_tieu_cao`, `ty_le_nang_hang_phan_khuc`, `ty_le_tut_hang_phan_khuc`,
  `ty_le_giam_su_dung_manh`, và bất kỳ trường `ty_le_...`/`...pct` nào khác xuất hiện): nêu thẳng 1
  tỷ lệ THIỂU SỐ (<40%) kèm nhãn dương tính rất dễ đọc nhầm thành đặc trưng của CẢ nhóm (vd "tỷ lệ
  khách hàng giá trị cao khoảng 24%" nghe như mô tả cả cụm, trong khi thực tế 76% KHÔNG như vậy).
  Với MỖI trường tỷ lệ như vậy: NẾU giá trị < 40%, PHẢI xoay ngược thành phần bù (100% - x%, luôn
  >=50%) và đổi nhãn sang MỘT PHẠM TRÙ THỰC CHẤT đối lập/trung tính (thấp, trung bình, ổn định...),
  TUYỆT ĐỐI KHÔNG dùng phủ định đơn thuần kiểu thêm chữ "không" trước nhãn gốc — phủ định suông
  ("không cao") không cho biết nhóm này THỰC SỰ là gì, phải nói rõ mức thực tế của họ. Vd: "giá trị
  cao" → "giá trị thấp, trung bình" (KHÔNG viết "không thuộc nhóm chi tiêu cao"); "tụt hạng phân khúc
  cao" → "tụt hạng phân khúc thấp, ổn định" (KHÔNG viết "không tụt hạng phân khúc"); "giảm sử dụng
  mạnh" → "sử dụng ổn định, ít biến động" (KHÔNG viết "không giảm sử dụng mạnh"). NẾU giá trị >= 40%,
  giữ nguyên chiều nêu số liệu như bình thường, KHÔNG xoay ngược. Ví dụ: `ty_le_chi_tieu_cao` = 0.24
  → viết "khoảng 76% khách hàng có giá trị thấp, trung bình", KHÔNG viết "tỷ lệ khách hàng giá trị
  cao khoảng 24%" và KHÔNG viết "76% khách hàng không thuộc nhóm chi tiêu cao". Quy tắc này áp dụng
  ĐỘC LẬP cho từng trường — mỗi trường tự xét ngưỡng 40% của chính nó, không gộp chung.
- NẾU có `contradictions` (danh sách nghịch lý đã tính sẵn): mỗi phần tử PHẢI được diễn giải lại
  thành ĐÚNG 1 câu theo cấu trúc "Mặc dù/Dù ... vẫn/nhưng ... " + 1 câu hệ quả "Điều này cho thấy...".
  KHÔNG bỏ qua, KHÔNG viết chung chung. Câu hệ quả PHẢI hedge ("nhiều khả năng", "có thể là yếu tố góp
  phần") — đây là tương quan quan sát được, KHÔNG PHẢI nguyên nhân đã xác nhận tuyệt đối, TUYỆT ĐỐI
  KHÔNG khẳng định thẳng kiểu "chất lượng dịch vụ đang ảnh hưởng...". Ví dụ: "ARPU/giá trị cao NHƯNG
  complaint hoặc sự cố kỹ thuật cũng cao..." → "Mặc dù khách hàng vẫn mang lại doanh thu cao, trải
  nghiệm dịch vụ chưa tốt nhiều khả năng là yếu tố góp phần làm gia tăng mức độ bất mãn." Ví dụ khác:
  "Loyalty cao NHƯNG mức độ tương tác/sử dụng đang giảm..." → "Dù vẫn duy trì giá trị tích lũy cao,
  mức độ tương tác với kênh truyền thống có dấu hiệu giảm."
- Khi CÓ `profile_context`, business_interpretation được phép dài TỐI ĐA 3 CÂU (thay vì 2) để chứa đủ
  câu mô tả profile_context + câu domain_signals/contradiction + câu hệ quả. Các trường phân tích khác
  (Operational Impact, Customer Profile...) vẫn giữ tối đa 2 câu.
- NẾU KHÔNG có `domain_signals` (rỗng — không domain nào lệch đáng kể) VÀ `profile_context` cũng
  không cho thấy tín hiệu mạnh (loyalty thấp, ARPU trung bình, downgrade thấp): TUYỆT ĐỐI KHÔNG suy
  diễn ra kết luận mang tính dự đoán/khuyến nghị kiểu "có cơ hội phát triển"/"tiềm năng tăng trưởng"
  — đây là suy luận NHẢY CÓC không có bằng chứng hỗ trợ (đã bị phát hiện trên báo cáo thật: profile
  chỉ cho thấy "loyalty thấp, giá trị trung bình, không có vấn đề nổi bật" nhưng lại kết luận "doanh
  nghiệp có cơ hội để phát triển nhóm này"). Dùng đúng khung câu AN TOÀN sau, chỉ thay số liệu theo
  profile_context thực tế, KHÔNG thêm từ "cơ hội"/"tiềm năng":
  - NẾU KHÔNG có `already_churned: true` (khách hàng đang hoạt động): "Đây là nhóm khách hàng phổ
    thông có hành vi ổn định nhưng mức độ gắn kết còn thấp, phù hợp với các chương trình tăng tương
    tác và bán chéo."
  - NẾU CÓ `already_churned: true` (khách hàng ĐÃ RỜI MẠNG): KHÔNG được dùng câu trên (đề xuất
    "chương trình tăng tương tác/bán chéo" cho người ĐÃ rời mạng là vô nghĩa). Dùng thay: "Đây là
    nhóm khách hàng rời mạng có hành vi ổn định, không ghi nhận tín hiệu bất thường rõ ràng trước
    thời điểm rời mạng."
- QUY TẮC THÌ/FRAMING cho khách hàng ĐÃ RỜI MẠNG (`already_churned: true` trong persona): TOÀN BỘ
  business_interpretation PHẢI dùng framing QUÁ KHỨ — "trước thời điểm rời mạng", "ngay trước khi
  chấm dứt dịch vụ", "quan sát được trong giai đoạn trước khi rời mạng", "là dấu hiệu phổ biến ở
  nhóm khách hàng đã rời mạng". TUYỆT ĐỐI KHÔNG dùng framing TƯƠNG LAI/rủi ro kiểu "đang có nguy cơ
  rời mạng", "cần giữ chân", "có thể rời mạng" — dữ liệu này là KHÁCH HÀNG ĐÃ RỜI MẠNG RỒI, không
  phải khách hàng đang hoạt động cần dự đoán rủi ro tương lai.
- NẾU `profile_context.dich_vu_chinh` cho thấy 1 dịch vụ chiếm ưu thế rõ rệt (>=60% theo % đã cho):
  PHẢI biến thành 1 câu insight về cơ hội kinh doanh, KHÔNG chỉ liệt kê tên dịch vụ suông. Ví dụ:
  dich_vu_chinh = ["Net Pay (73%)", "Net Pay Cam (10%)"] → "Phần lớn khách hàng chỉ dùng Net Pay đơn
  lẻ, rất ít sử dụng dịch vụ tích hợp như Net Pay Cam — cho thấy dư địa cho các chiến dịch upsell dịch
  vụ tích hợp." KHÔNG bịa số liệu ngoài % đã cho trong `dich_vu_chinh`.
- QUY TẮC "% LỚN NHẤT KHÔNG ĐỒNG NGHĨA VỚI CHỦ YẾU" (áp dụng cho MỌI trường composition dạng danh
  sách "Tên (X%)" trong `profile_context`, vd `dich_vu_chinh`, `goi_cuoc_chinh`, và bất kỳ trường
  composition nào khác xuất hiện): mục đứng ĐẦU danh sách chỉ là mục có % LỚN NHẤT trong nhóm, KHÔNG
  tự động là "chủ yếu"/"phần lớn"/"đa số" — nếu các mục còn lại có % gần bằng nhau (phân bố khá đều)
  thì gọi mục đầu là "chủ yếu" ĐÁNH LỪA người đọc, vì phần lớn khách hàng thực ra KHÔNG dùng mục đó.
  NẾU mục đứng đầu < 40%: TUYỆT ĐỐI KHÔNG dùng "chủ yếu"/"phần lớn"/"đa số"/"chỉ dùng" cho riêng mục
  đó — PHẢI mô tả là khách hàng sử dụng ĐA DẠNG, không tập trung vào 1 mục cụ thể, kèm liệt kê % thật
  đã cho. Ví dụ: `dich_vu_chinh` = ["Net Pay (24%)", "Mobile Pay (23%)"] → viết "khách hàng sử dụng đa
  dạng dịch vụ (Net Pay 24%, Mobile Pay 23%...), không tập trung vào 1 dịch vụ cụ thể", KHÔNG viết
  "chủ yếu sử dụng dịch vụ Net Pay". NẾU mục đứng đầu >= 40%, được phép nêu là "chủ yếu" như bình
  thường (ngưỡng >=60% ở quy tắc trên chỉ áp dụng riêng cho việc có thêm câu insight upsell hay
  không, không ảnh hưởng đến việc có được dùng từ "chủ yếu" hay không).

Dữ liệu Business Facts duy nhất bạn được thấy:
{data_str}
"""

    def _call_narrative_llm(self, prompt: str) -> ReportNarrative:
        """1 lệnh gọi LLM (structured output qua instructor) + retry NGOÀI với backoff — khác với
        max_retries=2 của instructor bên dưới (cái đó CHỈ retry khi response về đúng nhưng SAI SCHEMA
        Pydantic, không bắt được lỗi mạng/gateway timeout xảy ra TRƯỚC khi có response để validate, vd
        504 từ Qwen proxy trả về nguyên trang HTML thay vì JSON — ĐÃ XẢY RA NHIỀU LẦN trên live run)."""
        last_err = None
        for attempt in range(3):
            try:
                return self.client.chat.completions.create(
                    model=self.model_name,
                    response_model=ReportNarrative,
                    messages=[{"role": "user", "content": prompt}],
                    max_retries=2,
                    # Tắt "thinking mode" của Qwen3.5 — giảm thời gian sinh, giảm khả năng chạm
                    # timeout của gateway (cùng lý do đã áp dụng ở programmer.py).
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))  # 2s, rồi 4s trước lần thử tiếp theo
        # Sanitize before re-raising — a raw upstream error (nginx/gateway 504 pages are full
        # HTML documents) must NEVER be dumped verbatim into the user-facing chat/report; it
        # happened on a live run and read as a broken page dumped mid-conversation.
        msg = str(last_err)
        if "<html" in msg.lower() or len(msg) > 300:
            msg = "LLM service tạm thời không phản hồi (timeout/gateway error)."
        raise RuntimeError(f"Failed to generate LLM Narrative: {msg}")

    def generate_llm_narrative(self, personas_data: list, global_means: dict, batch_size: int = 3) -> ReportNarrative:
        """Chia personas_data thành các BATCH nhỏ (batch_size persona/lần gọi) thay vì 1 lệnh gọi
        DUY NHẤT cho TOÀN BỘ report — trước đây 1 request gộp hết mọi persona nên prompt/output càng
        lúc càng dài (đặc biệt sau khi thêm churn_story_facts + hàng loạt QUY TẮC mới), dễ vượt
        ngưỡng timeout của gateway (504, ĐÃ XẢY RA TRÊN LIVE RUN — log cho thấy request treo ~94s
        trước khi gateway trả 504) — và 1 lần fail làm mất SẠCH phần LLM viết lại cho MỌI persona,
        rơi hết về bản ghép cứng giống hệt nhau giữa các persona cùng driver (ĐÃ XẢY RA TRÊN BÁO CÁO
        THẬT). Với batch nhỏ: mỗi request ngắn hơn (ít khả năng chạm timeout), và nếu 1 batch fail thì
        CHỈ personas trong batch đó rơi về fallback deterministic, các batch khác vẫn giữ được bản LLM.
        executive_summary/conclusion lấy từ batch THÀNH CÔNG ĐẦU TIÊN (không cần mọi persona mới viết
        được 1 đoạn tổng quan hợp lý — report đã có _build_executive_headline() deterministic đứng
        trước để cung cấp số liệu chính xác, đây chỉ là văn phong bổ sung)."""
        batches = [personas_data[i:i + batch_size] for i in range(0, len(personas_data), batch_size)]
        merged_personas = []
        exec_summary, conclusion = None, None
        last_err = None
        for batch in batches:
            prompt = self._build_prompt(batch, global_means)
            try:
                batch_narrative = self._call_narrative_llm(prompt)
            except Exception as e:
                last_err = e
                print(f"[ReportGenerator] LLM narrative batch failed ({len(batch)} persona(s)), "
                      f"những persona này sẽ dùng fallback deterministic: {e}")
                continue
            merged_personas.extend(batch_narrative.personas_analysis)
            if exec_summary is None:
                exec_summary = batch_narrative.executive_summary
                conclusion = batch_narrative.conclusion

        if exec_summary is None:
            # TOÀN BỘ batch đều fail — không còn gì để trả, để caller (render_markdown) bắt exception
            # và rơi về _fallback_narrative() như hành vi cũ.
            raise RuntimeError(f"Failed to generate LLM Narrative for any batch: {last_err}")

        return ReportNarrative(executive_summary=exec_summary, personas_analysis=merged_personas, conclusion=conclusion)

    def _fallback_narrative(self) -> ReportNarrative:
        """Used when generate_llm_narrative() fails (timeout, gateway error, etc.) so the report
        still renders with all deterministic sections — losing only the AI-authored prose, never
        the whole report. Empty personas_analysis makes every `if n:` lookup downstream a no-op."""
        return ReportNarrative(
            executive_summary=ExecutiveSummaryNarrative(
                executive_overview="AI narrative tạm thời không khả dụng do lỗi kết nối dịch vụ LLM. Các số liệu, phân tích nguyên nhân và roadmap bên dưới vẫn được tính toán đầy đủ và chính xác — chỉ thiếu phần diễn giải văn phong bổ sung từ AI."
            ),
            personas_analysis=[],
            conclusion="Báo cáo được tạo với dữ liệu và phân tích đầy đủ; phần diễn giải mở rộng từ AI tạm thời không khả dụng do lỗi kết nối dịch vụ."
        )

    def render_markdown(self, raw_python_output: str) -> str:
        personas_data = self.extract_json(raw_python_output)
        if not personas_data:
            return "Lỗi: Không tìm thấy dữ liệu JSON Persona hợp lệ."

        # Chuẩn hoá support_pct về DẠNG PHÂN SỐ (0-1) NGAY TẠI ĐÂY, một lần duy nhất — pipeline
        # script do LLM tự sinh có thể tính support_pct thành SỐ PHẦN TRĂM (0-100) thay vì phân số
        # (ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: 1 cụm 93.14% bị hiển thị thành "9314.0%" vì mọi nơi khác
        # trong file này đều nhân *100 giả định support_pct luôn là phân số). Chuẩn hoá 1 lần ở đây
        # thay vì vá từng chỗ dùng *100 rải rác khắp file.
        for p in personas_data:
            sp = p.get('support_pct')
            if isinstance(sp, (int, float)) and sp > 1:
                p['support_pct'] = sp / 100

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
            
        # 3. Trigger LLM — on failure (timeout/gateway error), degrade to a fallback narrative
        # instead of losing the ENTIRE report. Every downstream usage of `narrative` only reads
        # deterministic, pre-computed facts elsewhere in this method; the AI prose is the only
        # casualty (confirmed on a live run: a transient 504 crashed the whole markdown report,
        # even though every number/action/roadmap entry was already computed and ready to render).
        try:
            narrative = self.generate_llm_narrative(personas_data, global_means)
        except Exception as e:
            print(f"[ReportGenerator] LLM narrative failed, using fallback: {e}")
            narrative = self._fallback_narrative()
        
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

        md += f"{self._build_executive_headline(personas_data)}\n\n"
        md += f"{narrative.executive_summary.executive_overview}\n\n"
            
        # Methodology
        md += "## 2. Methodology\n\n"
        md += "`Dataset ➔ Feature Engineering ➔ Clustering ➔ Rule Engine ➔ Semantic Layer ➔ Presentation Layer ➔ Narrative Generator (LLM) ➔ Report Composer`\n\n"
        
        # narrative_dict được build SỚM hơn (trước đây chỉ build ở mục 4) để Persona Overview cũng
        # dùng được business_interpretation do LLM tổng hợp — tránh tình trạng card Overview chỉ là
        # bullet rời rạc (feature-by-feature, %/lần lệch) trong khi mục 4 mới có văn xuôi thật.
        narrative_dict = {n.cluster_id: n for n in narrative.personas_analysis}
        # Tên hiển thị cuối cùng — khi 2+ cụm trùng tên gốc, phân biệt bằng feature THẬT (ARPU/
        # loyalty/downgrade...) thay vì hậu tố số thứ tự "(1)/(2)" vô nghĩa (xem _disambiguate_display_names).
        display_name_map = self._disambiguate_display_names(personas_data)

        # Persona Overview — infographic-style card per persona: icon + tên + % + tag cường độ, theo
        # sau là 1 ĐOẠN VĂN diễn giải (không phải bullet rời rạc từng feature). POST_CHURN: LLM viết
        # lại từ churn_story_facts (đa dạng câu chữ hơn, tránh 1 khuôn cố định lặp lại ở mọi persona
        # — phát hiện trên báo cáo thật), fallback về story composer deterministic khi LLM lỗi/timeout/
        # rỗng; các persona khác dùng business_interpretation LLM tổng hợp từ domain_signals/
        # business_signals như cũ (đã sterilize, không tự bịa số liệu/domain).
        md += "## 3. Persona Overview\n\n"
        for p in personas_data:
            cid = p.get('cluster_id')
            p_name = display_name_map.get(cid, self.clean_persona_name(p.get('persona_name', 'Unknown')))
            icon = self._get_persona_icon(p_name)
            tag = self._get_intensity_tag(p)
            sup_pct = p.get('support_pct', 0) * 100
            sup_str = self.format_support(p.get('support', 0))

            md += f"### {icon} {p_name} — {sup_pct:.1f}% ({tag})\n\n"
            md += f"*Quy mô: {sup_str} | Severity: {p.get('severity','N/A')} | Risk: {p.get('risk','N/A')}*\n\n"
            story = self._build_persona_story(p, global_means)
            n = narrative_dict.get(cid)
            llm_text = getattr(n, 'business_interpretation', None) if n else None
            if story:
                # story != None => POST_CHURN (có churn_driver) => đã gửi churn_story_facts cho LLM
                # viết lại tự nhiên hơn. Ưu tiên bản LLM khi có, fallback về bản ghép cứng khi LLM
                # lỗi/timeout/trả rỗng — layer Insight không bao giờ mất, chỉ mất phần "đa dạng câu chữ".
                md += f"{llm_text if llm_text else story}\n\n"
            elif llm_text:
                md += f"{llm_text}\n\n"
            else:
                # LLM narrative không khả dụng (timeout/lỗi kết nối) — vẫn ưu tiên 1 đoạn văn
                # deterministic ghép từ profile_context/contradictions thay vì rơi thẳng xuống
                # bullet rời rạc, để card Overview không bao giờ trông như "cluster thống kê".
                insight = self._compose_deterministic_insight(p, global_means)
                if insight:
                    md += f"{insight}\n\n"
                else:
                    for b in self._get_evidence_bullets(p, global_means, top_n=3):
                        md += f"- {b}\n"
                    md += "\n"

        # Risk Tier Grouping (only if at least one persona has risk_tier computed) — mỗi persona
        # kèm 1 dòng "why" lấy từ tín hiệu lệch mạnh nhất thực tế của chính nó (không suy diễn thêm).
        if any(p.get('risk_tier') for p in personas_data):
            md += "## 3b. Risk Tier Grouping\n\n"
            is_post_churn = any(p.get('churn_driver') for p in personas_data)
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
                p_name = display_name_map.get(p.get('cluster_id'), self.clean_persona_name(p.get('persona_name', '')))
                means = self._get_means(p)
                top = self._top_signals(means, global_means, top_n=1) if means else []
                why = None
                if top:
                    f, val, g_val, _ = top[0]
                    # CHỈ nêu "why" khi feature lệch MẠNH NHẤT thực sự TĂNG/CAO hơn baseline — 1
                    # feature GIẢM (vd khiếu nại giảm mạnh) tuy lệch nhiều nhất về con số nhưng
                    # KHÔNG giải thích được vì sao nhóm này rơi vào risk tier này (cùng lỗi đã fix ở
                    # _build_persona_story: top-deviation ≠ nguyên nhân nếu chiều lệch không phải
                    # "cao hơn").
                    direction, _ = self._qualitative_magnitude(val, g_val)
                    if direction == 'up':
                        why = self._get_business_signal(f, val, g_val)
                tiers[t].append((p_name, why))

            for t in tier_order:
                label = _POST_CHURN_TIER_DISPLAY_LABELS.get(t, t) if is_post_churn else t
                md += f"**{label}**\n\n"
                if tiers[t]:
                    for name, why in tiers[t]:
                        md += f"- **{name}**" + (f" — {why}\n" if why else "\n")
                else:
                    md += "- Không có persona nào\n"
                md += "\n"

        # Persona Analysis
        md += "## 4. Persona Analysis\n\n"

        for p in personas_data:
            cid = p.get('cluster_id')
            n = narrative_dict.get(cid)
            p_name = display_name_map.get(cid, self.clean_persona_name(p.get('persona_name', f'Nhóm {cid}')))
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

            # Churn Driver (POST_CHURN only) — nguyên nhân rời mạng suy ra từ QUỸ ĐẠO hành vi (old vs
            # recent vs trend), không chỉ snapshot cuối kỳ. Story kể lại toàn bộ suy luận thành 1
            # đoạn văn liền mạch thay vì tách rời nhãn + câu evidence, giữ hedge ("dữ liệu cho thấy")
            # vì đây là tương quan quan sát được, không phải nguyên nhân đã được xác nhận.
            if p.get('churn_driver'):
                md += "**🔎 Nguyên nhân rời mạng (suy luận từ hành vi):**\n\n"
                story = self._build_persona_story(p, global_means)
                md += f"{story or p['churn_driver']}\n\n"
                trajectory = p.get('temporal_trajectory') or []
                # temporal_trajectory được sinh bởi code do LLM copy-paste vào pipeline — không
                # đảm bảo 100% đúng schema (đã xảy ra trên dữ liệu thật: KeyError 'trend' làm SẬP
                # TOÀN BỘ báo cáo markdown). Dùng .get() phòng thủ, bỏ qua entry hỏng thay vì crash.
                if trajectory and isinstance(trajectory, list):
                    rows = []
                    for t in trajectory:
                        if not isinstance(t, dict):
                            continue
                        rows.append(f"| {t.get('metric', 'N/A')} | {t.get('old', 'N/A')} | {t.get('recent', 'N/A')} | {t.get('trend', 'N/A')} |")
                    if rows:
                        md += "**Diễn biến theo thời gian (đầu kỳ → gần đây):**\n\n"
                        md += "| Chỉ số | Đầu kỳ | Gần đây | Xu hướng |\n"
                        md += "|---|---|---|---|\n"
                        md += "\n".join(rows) + "\n\n"

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
            else:
                # LLM narrative không khả dụng cho cả report — vẫn hiển thị Business Interpretation
                # bằng đoạn deterministic ghép từ profile_context/contradictions, để mục 4 không bị
                # thiếu hẳn layer Insight chỉ vì gọi LLM lỗi/timeout.
                insight = self._compose_deterministic_insight(p, global_means)
                if insight:
                    md += f"**Business Interpretation:**\n{insight}\n\n"

            # Customer Profile — qualitative, business-readable summary (Adobe/Salesforce-style
            # persona card) derived from domain_signature stars + service_composition, so business
            # readers get "Top nhóm giá trị cao, ít liên hệ CSKH" instead of raw numbers they skip.
            profile_bullets = self._build_customer_profile_bullets(p, global_means)
            if profile_bullets:
                md += "**Customer Profile:**\n"
                for b in profile_bullets:
                    md += f"- {b}\n"
                md += "\n"

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
            p_name = display_name_map.get(p.get('cluster_id'), self.clean_persona_name(p.get('persona_name', '')))
            sup_str = self.format_support(p.get('support', 0))
            sup_pct = p.get('support_pct', 0) * 100
            actions = p.get('recommended_actions', [])

            # Defensive fallback ONLY — generate_actions() in the pipeline prompt always returns
            # at least one action, so this should never fire. But if a run's pipeline code ever
            # drops recommended_actions, derive a real one from severity/risk instead of showing
            # a bare "N/A"/"TBD" roadmap row to the business reader.
            if not actions:
                name_l = p_name.lower()
                if p.get('risk') in ("HIGH", "EXTREME") or "bất mãn" in name_l:
                    actions = ["Outbound CSKH chủ động để xoa dịu khách hàng"]
                elif p.get('severity') in ("HIGH", "EXTREME") or "kỹ thuật" in name_l:
                    actions = ["Kiểm tra chất lượng mạng, tuyến cáp quang, đo suy hao"]
                else:
                    actions = ["Thu thập thêm dữ liệu hành vi (Ticket logs, Call Center logs)"]

            action_text = actions[0] if actions else "N/A"
            meta = resolve_roadmap_metadata(action_text)
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
            p_name = display_name_map.get(p.get('cluster_id'), self.clean_persona_name(p.get('persona_name', '')))
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
