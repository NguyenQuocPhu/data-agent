"""Deterministic business-rule engine: persona typing, naming, risk tiering and actions.

PORTED VERBATIM from the code block inside ``PROGRAMMER_PROMPT_V2``. Until now this logic
existed only as prompt TEXT that the sandbox LLM retyped on every run: two runs on the same
data could produce different code, nothing here was reachable by a test, and any error sent
the repair loop rewriting the script from memory — drifting further with each retry
(observed live: NameError, then KeyError, then five exhausted attempts and no report).

Function bodies are copied unchanged rather than rewritten, so the telco path behaves
exactly as before; only the surrounding structure, imports and documentation are new.
"""
from __future__ import annotations

import pandas as pd

from triadic_dgm.persona.columns import get_metric

def apply_business_rules(m, support_pct, profile=None, profile_global=None, dataset_mode=None, churn_driver_info=None, domain_sig=None):
    profile = profile or {}
    profile_global = profile_global or {}
    domain_sig = domain_sig or {}
    cl = get_metric(m, ['cl_total', 'cl', 'sự cố'])
    comp = get_metric(m, ['complaint', 'khiếu nại'])
    call = get_metric(m, ['call_total', 'call', 'gọi', 'cuộc gọi'])
    no_call = get_metric(m, ['no_call', 'không gọi'])
    no_comp = get_metric(m, ['no_complaint', 'không khiếu nại'])
    no_cl = get_metric(m, ['no_cl', 'không sự cố'])
    
    # 1. Persona Type
    if support_pct < 0.01:
        persona_type = "ANOMALY"
    elif support_pct > 0.50:
        persona_type = "MAINSTREAM"
    else:
        persona_type = "SEGMENT"
        
    # 2. Severity (Sự cố kỹ thuật)
    if cl >= 5:
        severity = "EXTREME"
    elif cl >= 3:
        severity = "HIGH"
    elif cl >= 1.5:
        severity = "MEDIUM"
    else:
        severity = "LOW"
        
    # 3. Risk (Khiếu nại & Cuộc gọi) — comp>=1.0 khớp ngưỡng nhánh "bất mãn" bên dưới
    if call >= 50:
        risk = "EXTREME"
    elif comp >= 1.0 or call > 5:
        risk = "HIGH"
    elif comp >= 0.3 or call > 2:
        risk = "MEDIUM"
    else:
        risk = "LOW"
        
    # 4. Deterministic Naming & Priority Scoring
    if persona_type == "ANOMALY":
        name = "Hành vi bất thường"
        priority_score = 10
    elif risk == "HIGH" and comp >= 1.0:
        name = "Khách hàng bất mãn"
        priority_score = 95 + (support_pct * 10)
    elif risk == "EXTREME":
        name = "Liên hệ CSKH bất thường"
        priority_score = 70 + (support_pct * 10)
    elif risk == "HIGH" and call > 0:
        name = "Liên hệ CSKH nhiều"
        priority_score = 60 + (support_pct * 10)
    elif severity == "EXTREME":
        name = "Sự cố kỹ thuật mức nghiêm trọng"
        priority_score = 90 + (support_pct * 10)
    elif severity == "HIGH":
        name = "Sự cố kỹ thuật mức cao"
        priority_score = 80 + (support_pct * 10)
    elif severity == "MEDIUM":
        name = "Sự cố kỹ thuật mức trung bình"
        priority_score = 50 + (support_pct * 10)
    elif risk == "MEDIUM":
        name = "Liên hệ CSKH tần suất vừa"
        priority_score = 40 + (support_pct * 10)
    elif no_call >= 0.9 and no_comp >= 0.9 and no_cl >= 0.9:
        name = "Khách hàng im lặng"
        priority_score = 20 + (support_pct * 10)
    elif no_call >= 0.5 and no_comp >= 0.5 and no_cl >= 0.5:
        name = "Khách hàng tương tác nhẹ"
        priority_score = 30 + (support_pct * 10)
    else:
        name = "Nhóm hành vi chưa rõ"
        priority_score = 15 + (support_pct * 10)

    # 5. Composite Signal Overrides — trước đây CHỈ chạy khi severity/risk chưa HIGH/EXTREME. Giữ
    # nguyên gate đó cho các tên ĐÃ CÓ Ý NGHĨA rõ ràng từ bước 4 (vd "Khách hàng bất mãn" khi
    # comp>=1.0, hay tên severity kỹ thuật) — không tự ý ghi đè chúng. NHƯNG mở rộng thêm 1 exception:
    # name == "Liên hệ CSKH bất thường" (nhánh `risk == "EXTREME"`, dòng ~113) là 1 CATCH-ALL không
    # phân biệt nguyên nhân (chỉ dựa `call >= 50` tuyệt đối) — ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: 4/5 cụm
    # hoàn toàn khác nhau (1 cụm complaint+technical cao, 1 cụm loyalty tăng mạnh, 1 cụm usage
    # giảm/gần như không tín hiệu gì) đều rơi vào risk=EXTREME và bị gán CHUNG tên này, xoá sạch ý
    # nghĩa phân cụm. Với catch-all này, LUÔN cho phép composite override chạy để tìm tên cụ thể hơn
    # dựa trên domain_signature/profile — nếu không có gì đủ mạnh thì mới giữ nguyên tên catch-all.
    if name == "Liên hệ CSKH bất thường" or (severity not in ("HIGH", "EXTREME") and risk not in ("HIGH", "EXTREME")):
        def rel_dev(key):
            g = profile_global.get(key, 0)
            v = profile.get(key, 0)
            return (v - g) / abs(g) if g != 0 else v

        def dom_stars(dom):
            info = domain_sig.get(dom)
            return info.get('stars', 0) if isinstance(info, dict) else 0

        combo_decline = max(rel_dev('tier_downgrade_rate'), rel_dev('usage_decline_mild_pct'))
        if profile.get('high_spender_pct', 0) >= 0.3 and rel_dev('high_spender_pct') >= 0.25 and combo_decline >= 0.25:
            name = "Khách hàng chi tiêu cao có dấu hiệu suy giảm"
            priority_score = max(priority_score, 85 + (support_pct * 10))
        else:
            # (key, tên, base_score, "dev" đã chuẩn hoá) — profile dùng rel_dev (tỉ lệ lệch so với
            # global), domain_sig dùng (stars-1)/4 quy về cùng khoảng 0-1 để so sánh công bằng trên 1
            # thang điểm duy nhất, tránh phải duy trì 2 hệ so sánh tách rời.
            candidates = [
                ('status_worsening_pct', "Khách hàng có dấu hiệu tạm ngưng dịch vụ", 75, rel_dev('status_worsening_pct')),
                ('usage_decline_strong_pct', "Khách hàng suy giảm mạnh", 65, rel_dev('usage_decline_strong_pct')),
                ('tier_downgrade_rate', "Khách hàng có dấu hiệu hạ cấp dịch vụ", 55, rel_dev('tier_downgrade_rate')),
                ('usage_unstable_pct', "Khách hàng sử dụng dao động thất thường", 50, rel_dev('usage_unstable_pct')),
                ('usage_decline_mild_pct', "Khách hàng giảm sử dụng nhẹ", 45, rel_dev('usage_decline_mild_pct')),
                ('high_spender_pct', "Khách hàng chi tiêu cao, ổn định", 40, rel_dev('high_spender_pct')),
                ('tier_upgrade_rate', "Khách hàng có xu hướng nâng cấp dịch vụ", 35, rel_dev('tier_upgrade_rate')),
                (None, "Khách hàng bất mãn, khiếu nại tăng mạnh", 78, (dom_stars('complaint') - 1) / 4.0),
                (None, "Khách hàng gặp sự cố kỹ thuật lặp lại", 74, (dom_stars('technical') - 1) / 4.0),
                (None, "Liên hệ CSKH/cuộc gọi tăng bất thường", 66, (max(dom_stars('call'), dom_stars('missed')) - 1) / 4.0),
            ]
            best_name, best_score, best_dev = None, 0, 0.25  # 0.25 = ngưỡng lệch tối thiểu để được coi là "đáng nói"
            for key, cname, base_score, d in candidates:
                if d > best_dev and (key is None or profile.get(key, 0) > 0):
                    best_name, best_score, best_dev = cname, base_score, d
            loyalty_dev = rel_dev('loyalty_rank_avg')
            if loyalty_dev <= -0.4 and -loyalty_dev > best_dev:
                best_name, best_score, best_dev = "Khách hàng giảm gắn bó, cần tái kích hoạt", 58, -loyalty_dev
            elif loyalty_dev >= 1.0 and loyalty_dev > best_dev:
                # loyalty_rank_avg cao GẤP ĐÔI trở lên trung bình quần thể — đủ nổi bật để gọi thẳng
                # là "trung thành" thay vì chỉ "gắn bó" chung chung (ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: 1
                # cụm có loyalty_rank_avg lệch +690% vẫn chỉ rơi vào tên fallback "Khách hàng tương
                # tác nhẹ" — cần 1 mức tên mạnh hơn hẳn cho trường hợp lệch cực đoan này).
                best_name, best_score, best_dev = "Khách hàng trung thành", 46, loyalty_dev
            elif loyalty_dev >= 0.4 and loyalty_dev > best_dev:
                best_name, best_score, best_dev = "Khách hàng gắn bó, thân thiết", 42, loyalty_dev
            if best_name:
                name = best_name
                priority_score = max(priority_score, best_score + (support_pct * 10))
            elif name == "Nhóm hành vi chưa rõ":
                name = "Khách hàng ổn định"

    churn_driver_info = churn_driver_info or {}
    if dataset_mode == "POST_CHURN" and churn_driver_info:
        name = churn_driver_info['churn_driver']
        priority_score = (70 if churn_driver_info['churn_driver_confidence'] == 'MEDIUM' else 30) + (support_pct * 10)

    return {
        "persona_type": persona_type,
        "severity": severity,
        "risk": risk,
        "persona_name": name,
        "priority_score": round(priority_score),
        "churn_driver": churn_driver_info.get('churn_driver'),
        "churn_driver_evidence": churn_driver_info.get('churn_driver_evidence'),
        "churn_driver_confidence": churn_driver_info.get('churn_driver_confidence'),
        "temporal_trajectory": churn_driver_info.get('temporal_trajectory', [])
    }


def classify_risk_tier(meta, profile):
    severity = meta.get('severity', 'LOW')
    risk = meta.get('risk', 'LOW')
    persona_type = meta.get('persona_type', 'SEGMENT')
    if persona_type == "ANOMALY":
        return "Nhóm bị động – theo dõi & cảnh báo"
    if severity == "EXTREME" or risk == "EXTREME" or profile.get('status_worsening_pct', 0) >= 0.3:
        return "Nhóm rủi ro cao – cần hành động ưu tiên"
    if profile.get('high_spender_pct', 0) >= 0.5 and (profile.get('tier_downgrade_rate', 0) > 0 or profile.get('usage_decline_mild_pct', 0) >= 0.3):
        return "Nhóm cần giữ chân ngay – ưu tiên giữ chân"
    if severity in ("HIGH", "MEDIUM") or risk in ("HIGH", "MEDIUM"):
        return "Nhóm rủi ro cao – cần hành động ưu tiên"
    return "Nhóm bị động – theo dõi & cảnh báo"


def generate_actions(dataset_mode, persona_name, severity, risk, profile=None):
    profile = profile or {}
    actions = []
    if dataset_mode == "POST_CHURN":
        # persona_name (POST_CHURN) == churn_driver — mỗi driver cần 1 hướng xử lý KHÁC NHAU, không
        # phải cùng 1 bộ hành động cho mọi persona (đã xảy ra trên báo cáo thật: Roadmap 4 dòng đều
        # là "Exit Survey" — trông như rule engine chưa đủ, dù nguyên nhân rời mạng của mỗi nhóm là
        # khác nhau và cần hành động khác nhau).
        # Kiểm tra tổ hợp CỤ THỂ HƠN (Silent Premium Churn, Support Failure) TRƯỚC các nhánh chung
        # chung hơn ("giá trị cao", "sự cố") — nếu không nhánh rộng sẽ khớp nhầm và gán sai hành động
        # (vd Silent Premium Churn chứa "giá trị cao" nhưng cần hành động early-warning theo usage,
        # KHÔNG PHẢI phân tích giá như nhóm giá trị cao thuần tuý).
        name_l = persona_name.lower()
        if "trải nghiệm suy giảm" in name_l:
            actions.extend(["Trigger chiến dịch retention ngay khi usage giảm 20% (Early Warning, không chờ khiếu nại)", "Theo dõi usage giảm và cảnh báo sớm (Early Warning System)"])
        elif "sự cố kỹ thuật không được xử lý" in name_l:
            actions.extend(["Escalate khiếu nại kỹ thuật lặp lại trong 24h", "Callback tự động sau khi xử lý sự cố kỹ thuật"])
        elif "giá trị cao" in name_l:
            actions.extend(["Phân tích đối thủ cạnh tranh và chính sách giá", "Khảo sát nguyên nhân rời mạng (Exit Survey) cho nhóm giá trị cao"])
        elif "bất mãn" in name_l or "sự cố" in name_l or "khiếu nại" in name_l:
            actions.extend(["Rút ngắn SLA xử lý khiếu nại", "Kiểm tra lịch sử tương tác trước khi rời mạng (Root Cause Investigation)"])
        elif "liên hệ" in name_l or "hỗ trợ" in name_l:
            actions.extend(["Cải thiện tỷ lệ xử lý xong trong 1 lần liên hệ (First Call Resolution)", "Kiểm tra lịch sử tương tác trước khi rời mạng (Root Cause Investigation)"])
        elif "âm thầm" in name_l:
            actions.extend(["Theo dõi usage giảm và cảnh báo sớm (Early Warning System)", "Chạy chiến dịch Win-back Campaign nếu khách hàng tiềm năng"])
        else:
            actions.extend(["Thực hiện khảo sát nguyên nhân rời mạng (Exit Survey)", "Kiểm tra lịch sử tương tác trước khi rời mạng (Root Cause Investigation)", "Chạy chiến dịch Win-back Campaign nếu khách hàng tiềm năng"])
    elif dataset_mode == "GENERIC":
        actions.extend([
            "Phân tích sâu các đặc điểm nổi bật của nhóm để hiểu hành vi đặc trưng",
            "Xây dựng chiến lược tiếp cận phù hợp với đặc trưng của nhóm",
        ])
    else:
        if risk in ["HIGH", "EXTREME"] or "bất mãn" in persona_name.lower():
            actions.append("Outbound CSKH chủ động để xoa dịu khách hàng")
        if severity in ["HIGH", "EXTREME"] or "kỹ thuật" in persona_name.lower():
            actions.append("Kiểm tra chất lượng mạng, tuyến cáp quang, đo suy hao")
        if "im lặng" in persona_name.lower() or "tương tác nhẹ" in persona_name.lower():
            actions.extend(["Thu thập thêm App usage logs, Data usage patterns", "Khảo sát mức độ hài lòng qua Zalo/SMS"])
        # Behavioral signals (call/complaint) are often zero-inflated and identical across
        # personas — fall back to profile_attributes (spend/tier/usage-trend/loyalty) so
        # personas still get differentiated, evidence-backed actions instead of every LOW/LOW
        # persona collapsing onto the same one generic fallback action. Ordered by urgency to
        # match the naming priority in apply_business_rules's composite overrides above.
        if profile.get('tier_downgrade_rate', 0) >= 0.3:
            actions.append("Chủ động liên hệ trước nguy cơ hạ cấp dịch vụ")
        if profile.get('usage_unstable_pct', 0) >= 0.4:
            actions.append("Phân tích nguyên nhân sử dụng dao động")
        if profile.get('usage_decline_strong_pct', 0) >= 0.3 or profile.get('usage_decline_mild_pct', 0) >= 0.3:
            actions.append("Tư vấn đổi gói cước phù hợp hành vi sử dụng")
        if profile.get('tier_upgrade_rate', 0) >= 0.3:
            actions.append("Khảo sát cơ hội upsell/cross-sell dịch vụ")
        if not actions:
            actions.append("Thu thập thêm dữ liệu hành vi (Ticket logs, Call Center logs)")
    return actions
