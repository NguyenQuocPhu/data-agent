"""Post-hoc descriptive profiling: profile attributes, domain signature, churn drivers.

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

from triadic_dgm.persona.columns import get_categorical_column, get_column

#: Telco behavioural domains, keyed by column-name fragments. Ported verbatim.
DOMAIN_KEYWORD_GROUPS = {
    'complaint': ['complaint_total', 'complaint_avg', 'complaint_recent', 'complaint_trend', 'complaint_std', 'active_complaint_months', 'old_complaint', 'no_complaint'],
    'call': ['call_total', 'call_avg', 'call_std', 'call_trend', 'old_call', 'recent_call', 'call_cv', 'active_call_months', 'no_call'],
    'missed': ['missed_total', 'missed_avg', 'missed_std', 'missed_trend', 'old_missed', 'recent_missed', 'active_missed_months', 'no_missed'],
    'technical': ['cl_total', 'cl_avg', 'cl_std', 'cl_trend', 'old_cl', 'recent_cl', 'active_cl_months', 'no_cl'],
    'usage': ['spending_decline', 'spending_growth', 'usage_decline', 'usage_unstable', 'segment_downgrade', 'segment_upgrade', 'cnt_dao_dong', 'cnt_giam', 'status_worsening'],
    'value': ['high_spender', 'fee_total', 'fee_avg', 'loyalty_rank', 'loyalty_point', 'segment_avg'],
}


def compute_profile_attributes(df, cluster_col='cluster'):
    cols = df.columns
    col_map = {
        'spend_flag':   get_column(cols, ['high_spender']),
        # BẮT BUỘC exact-match 'fee_avg' TRƯỚC — get_column() match theo THỨ TỰ CỘT trong DataFrame,
        # KHÔNG theo thứ tự keyword truyền vào, nên get_column(cols, ['fee_total', 'fee_avg']) vẫn
        # trả về 'fee_total' nếu cột đó đứng trước 'fee_avg' trong DataFrame (ĐÃ XẢY RA TRÊN DỮ LIỆU
        # THẬT: fee_total ở vị trí cột 50, fee_avg ở vị trí 51 → avg_fee/"ARPU" hiển thị suốt session
        # thực ra là TỔNG cước phí 6 tháng, không phải cước phí trung bình 1 tháng — bị thổi phồng
        # gấp active_fee_months lần). 'fee_avg' là TRUNG BÌNH THÁNG thật sự — chỉ fallback về
        # 'fee_total' nếu dataset không có cột fee_avg (còn hơn không có ARPU nào).
        'fee': next((c for c in cols if str(c).lower() == 'fee_avg'), None)                or next((c for c in cols if str(c).lower() == 'fee_total'), None),
        'tier_upgrade': get_column(cols, ['segment_upgrade_count']),
        'tier_downgrade': get_column(cols, ['segment_downgrade_count']),
        'usage_giam_nhe':  get_column(cols, ['ever_giam_nhe']),
        'usage_giam_manh': get_column(cols, ['persistent_giam_manh']) or get_column(cols, ['ever_giam_manh']),
        'usage_dao_dong_cnt':  get_column(cols, ['cnt_dao_dong']),
        'status_worsening': get_column(cols, ['status_worsening']),
        'loyalty_rank':   get_column(cols, ['loyalty_rank']),
        'csat':           get_column(cols, ['total_csat', 'csat']),
        'ces': next((c for c in cols if str(c).lower() == 'ces' or str(c).lower().endswith('_ces')
                     or str(c).lower().startswith('ces_') or 'customer_effort' in str(c).lower()), None),
        'package_type':   get_categorical_column(df, ['goi_cuoc', 'package_type', 'skd_bill_localtype']),
        'services':       get_categorical_column(df, ['services', 'dich_vu']),
    }
    profiles = {}
    for cid, grp in df.groupby(cluster_col):
        p = {}
        if col_map['spend_flag']:
            p['high_spender_pct'] = round(float(pd.to_numeric(grp[col_map['spend_flag']], errors='coerce').fillna(0).mean()), 4)
        if col_map['fee']:
            p['avg_fee'] = round(float(pd.to_numeric(grp[col_map['fee']], errors='coerce').fillna(0).mean()), 2)
        if col_map['tier_upgrade']:
            p['tier_upgrade_rate'] = round(float(pd.to_numeric(grp[col_map['tier_upgrade']], errors='coerce').fillna(0).mean()), 4)
        if col_map['tier_downgrade']:
            p['tier_downgrade_rate'] = round(float(pd.to_numeric(grp[col_map['tier_downgrade']], errors='coerce').fillna(0).mean()), 4)
        if col_map['usage_giam_manh']:
            p['usage_decline_strong_pct'] = round(float(pd.to_numeric(grp[col_map['usage_giam_manh']], errors='coerce').fillna(0).mean()), 4)
        if col_map['usage_giam_nhe']:
            p['usage_decline_mild_pct'] = round(float(pd.to_numeric(grp[col_map['usage_giam_nhe']], errors='coerce').fillna(0).mean()), 4)
        if col_map['usage_dao_dong_cnt']:
            raw_months = float(pd.to_numeric(grp[col_map['usage_dao_dong_cnt']], errors='coerce').fillna(0).mean())
            p['usage_unstable_pct'] = round(min(raw_months / 6.0, 1.0), 4)
        if col_map['status_worsening']:
            p['status_worsening_pct'] = round(float(pd.to_numeric(grp[col_map['status_worsening']], errors='coerce').fillna(0).mean()), 4)
        if col_map['loyalty_rank']:
            p['loyalty_rank_avg'] = round(float(pd.to_numeric(grp[col_map['loyalty_rank']], errors='coerce').fillna(0).mean()), 2)
        if col_map['csat']:
            p['csat_avg'] = round(float(pd.to_numeric(grp[col_map['csat']], errors='coerce').fillna(0).mean()), 2)
        if col_map['ces']:
            p['ces_avg'] = round(float(pd.to_numeric(grp[col_map['ces']], errors='coerce').fillna(0).mean()), 2)
        if col_map['package_type']:
            vc = grp[col_map['package_type']].astype(str).value_counts(normalize=True)
            p['package_composition'] = vc.round(4).to_dict()
        if col_map['services']:
            vc_svc = grp[col_map['services']].astype(str).value_counts(normalize=True)
            p['service_composition'] = vc_svc.round(4).to_dict()
        profiles[cid] = p
    return profiles


def compute_profile_global_means(profile_attributes, cluster_sizes):
    total = sum(cluster_sizes.values()) or 1
    keys = set()
    for p in profile_attributes.values():
        keys.update(k for k, v in p.items() if isinstance(v, (int, float)))
    out = {}
    for k in keys:
        s = sum(profile_attributes.get(cid, {}).get(k, 0) * cluster_sizes.get(cid, 0) for cid in profile_attributes)
        out[k] = s / total
    return out


def compute_domain_signature(df, cluster_col='cluster'):
    groups = DOMAIN_KEYWORD_GROUPS
    if not any(
        any(kw in str(c).lower() for c in df.columns for kw in kws)
        for kws in DOMAIN_KEYWORD_GROUPS.values()
    ):
        # GENERIC FALLBACK — the groups above are telco column fragments. On any other
        # dataset they match nothing, every domain scores 1 star, and the persona is then
        # described as "not standing out anywhere" no matter how distinctive it actually is
        # (the same keyword false-negative that made reports assert telco facts about data
        # with no telco columns). Derive domains from the dataset's own column-name roots
        # instead — infer_domains() is the tested helper the DatasetProfile already uses.
        from triadic_dgm.persona.dataset_profile import infer_domains

        numeric = df.select_dtypes(include='number')
        feats = [str(c) for c in numeric.columns if str(c) != cluster_col]
        groups = infer_domains(feats)

    domain_cols = {}
    for dom, kws in groups.items():
        found = []
        for c in df.columns:
            cl = str(c).lower()
            if c != cluster_col and any(kw in cl for kw in kws) and c not in found:
                found.append(c)
        domain_cols[dom] = found

    numeric_cache = {}
    def numeric(col):
        if col not in numeric_cache:
            numeric_cache[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return numeric_cache[col]

    global_means = {col: float(numeric(col).mean()) for cols in domain_cols.values() for col in cols}

    signature = {}
    for cid, grp in df.groupby(cluster_col):
        dom_scores = {}
        for dom, cols in domain_cols.items():
            feats = []
            for col in cols:
                g = global_means.get(col, 0)
                v = float(numeric(col).loc[grp.index].mean())
                # LƯU Ý QUAN TRỌNG: dev PHẢI là độ lệch CÓ DẤU (v - g), KHÔNG PHẢI abs(v - g).
                # Dùng abs() từng khiến 1 cụm có complaint/technical THẤP HƠN hẳn trung bình (vd
                # complaint_trend lệch -117%) nhận SAO CAO y hệt 1 cụm có complaint CAO HƠN hẳn —
                # dẫn tới business_interpretation nói "ít sự cố" nhưng Customer Profile lại nói "có
                # nhiều sự cố" (2 câu ngay cạnh nhau mâu thuẫn nhau, đã xảy ra trên báo cáo thật).
                # complaint/call/missed/technical CÀNG CAO càng xấu — chỉ độ lệch DƯƠNG (nhiều hơn
                # trung bình) mới là tín hiệu "đáng lo", độ lệch âm (ít hơn trung bình) là tín hiệu
                # TỐT/trung tính, không được tính là "nổi bật" cho các domain này.
                dev = (v - g) / abs(g) if g != 0 else v
                feats.append((col, round(v, 4), round(g, 4), round(dev, 4)))
            feats.sort(key=lambda x: -x[3])
            top2 = [f for f in feats if f[3] > 0][:2]
            max_dev = max([f[3] for f in feats] + [0])
            stars = 5 if max_dev >= 5.0 else 4 if max_dev >= 2.0 else 3 if max_dev >= 0.75 else 2 if max_dev >= 0.25 else 1
            dom_scores[dom] = {'stars': stars, 'top_features': top2}
        signature[cid] = dom_scores
    return signature


def get_temporal_trajectory(grp):
    roots = [('cl', 'Sự cố kỹ thuật'), ('complaint', 'Phàn nàn/khiếu nại'),
             ('call', 'Cuộc gọi CSKH'), ('missed', 'Cuộc gọi nhỡ')]
    cols = grp.columns
    trajectory = []
    for root, label in roots:
        old_col = get_column(cols, [f'old_{root}'])
        recent_col = get_column(cols, [f'recent_{root}'])
        trend_col = get_column(cols, [f'{root}_trend'])
        old_v = float(pd.to_numeric(grp[old_col], errors='coerce').fillna(0).mean()) if old_col else 0.0
        recent_v = float(pd.to_numeric(grp[recent_col], errors='coerce').fillna(0).mean()) if recent_col else 0.0
        trend_v = float(pd.to_numeric(grp[trend_col], errors='coerce').fillna(0).mean()) if trend_col else 0.0
        if old_v > 0 or recent_v > 0:
            direction = 'giảm mạnh' if trend_v < -0.3 else ('tăng mạnh' if trend_v > 0.3 else 'ổn định')
            trajectory.append({'metric': label, 'old': round(old_v, 3), 'recent': round(recent_v, 3), 'trend': direction})
    return trajectory


def classify_churn_driver(grp, domain_sig=None):
    # RULE ENGINE — persona LÀ TỔ HỢP NHIỀU DOMAIN (complaint/call/missed/technical/usage/value),
    # KHÔNG PHẢI 1 domain nổi bật nhất (đã xảy ra trên dữ liệu thật: "Khách hàng bất mãn" chỉ dựa
    # 100% vào complaint, "Liên hệ CSKH nhiều" chỉ dựa vào call — mất hết insight về SỰ KẾT HỢP,
    # vd "giá trị cao + usage giảm + KHÔNG complaint" là 1 câu chuyện hoàn toàn khác "call cao +
    # complaint cao + technical cao"). Luật CÀNG NHIỀU ĐIỀU KIỆN PHẢI xếp TRƯỚC luật ít điều kiện
    # hơn, nếu không luật rộng sẽ "nuốt" mất các tổ hợp đặc biệt đáng nói hơn.
    domain_sig = domain_sig or {}

    def stars(dom):
        info = domain_sig.get(dom)
        return info.get('stars', 1) if isinstance(info, dict) else 1

    s_complaint, s_call, s_missed = stars('complaint'), stars('call'), stars('missed')
    s_technical, s_usage, s_value = stars('technical'), stars('usage'), stars('value')

    trajectory = get_temporal_trajectory(grp)
    by_metric = {t['metric']: t for t in trajectory}
    empty = {'old': 0, 'recent': 0, 'trend': 'ổn định'}
    cl_t = by_metric.get('Sự cố kỹ thuật', empty)
    comp_t = by_metric.get('Phàn nàn/khiếu nại', empty)
    # Trình tự xuất hiện (THEO DỮ LIỆU THẬT CÓ, không suy diễn quá mức): domain có "old" cao đã tồn
    # tại từ giai đoạn đầu; domain chỉ có "recent" cao là tín hiệu MỚI, chỉ xuất hiện gần lúc rời
    # mạng. Đây là thông tin trình tự thô (early/late), KHÔNG PHẢI timeline theo tháng chính xác.
    onset_sequence = sorted(trajectory, key=lambda t: -t['old']) if trajectory else []

    def result(driver, evidence, confidence):
        return {'churn_driver': driver, 'churn_driver_evidence': evidence,
                 'churn_driver_confidence': confidence, 'temporal_trajectory': trajectory,
                 'onset_sequence': onset_sequence}

    # 1. Silent Premium Churn: giá trị cao + usage suy giảm rõ, HOÀN TOÀN không complaint/call/missed
    if s_value >= 4 and s_usage >= 3 and s_complaint <= 2 and s_call <= 2 and s_missed <= 2:
        return result(
            'Khách hàng giá trị cao nhưng trải nghiệm suy giảm',
            'Nhóm chi tiêu cao với hành vi sử dụng dịch vụ suy giảm rõ rệt, nhưng KHÔNG phát sinh khiếu nại hay liên hệ CSKH trước khi rời mạng — dấu hiệu "rời mạng trong im lặng" ở nhóm giá trị cao, nhiều khả năng đã chuyển sang đối thủ thay vì phản ánh vấn đề.',
            'MEDIUM')

    # 2. Support Failure: gọi nhiều + phàn nàn + sự cố kỹ thuật CÙNG LÚC — lặp lại nhiều lần không xử lý dứt điểm
    if s_call >= 4 and s_complaint >= 3 and s_technical >= 3:
        return result(
            'Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để',
            'Tần suất liên hệ CSKH cao đi kèm sự cố kỹ thuật và khiếu nại đều tăng mạnh cùng lúc — cho thấy vấn đề kỹ thuật lặp lại nhiều lần mà không được giải quyết dứt điểm qua các lần liên hệ.',
            'MEDIUM')

    # 3. Bất mãn thuần tuý do trải nghiệm dịch vụ (complaint là domain NỔI BẬT NHẤT)
    # ĐIỀU KIỆN GỐC là `s_call <= 2 and s_missed <= 2` (ngưỡng TUYỆT ĐỐI) — ĐÃ XẢY RA TRÊN DỮ LIỆU
    # THẬT: complaint 5⭐ (dev +3800%, áp đảo hoàn toàn) nhưng call chỉ cần đạt 3⭐ (dev vừa phải,
    # +97%) là ĐỦ để rule này KHÔNG khớp — rơi xuống rule 4 và bị gán nhãn "Tăng liên hệ CSKH" dù
    # complaint mới là tín hiệu áp đảo thật sự. Đổi sang so sánh TƯƠNG ĐỐI (complaint phải CAO HƠN
    # call VÀ missed, không cần chúng thấp tuyệt đối) để complaint luôn thắng khi nó thực sự là
    # domain nổi bật nhất, bất kể call/missed có đồng thời tăng nhẹ hay không.
    if s_complaint >= 4 and s_complaint > s_call and s_complaint > s_missed:
        had_early_problem = comp_t['old'] > 0.3 or cl_t['old'] > 0.3
        faded_out = (comp_t['recent'] < comp_t['old'] * 0.5 or cl_t['recent'] < cl_t['old'] * 0.5) and                     (comp_t['trend'] == 'giảm mạnh' or cl_t['trend'] == 'giảm mạnh')
        if had_early_problem and faded_out:
            return result(
                'Bất mãn kéo dài, không được xử lý',
                'Từng phát sinh khiếu nại/sự cố nhiều ở giai đoạn đầu, sau đó giảm dần và gần như im lặng trước khi rời mạng — dấu hiệu cho thấy khả năng vấn đề chưa từng được giải quyết triệt để, khách hàng "âm thầm" rời đi thay vì tiếp tục phản ánh.',
                'MEDIUM')
        return result(
            'Sự cố/khiếu nại cấp tính ngay trước khi rời mạng',
            'Khiếu nại/sự cố tăng mạnh ở giai đoạn gần rời mạng so với trước đó — dấu hiệu một sự kiện cụ thể (sự cố kỹ thuật, trải nghiệm tệ) là nguyên nhân trực tiếp, khác với một quá trình bất mãn kéo dài.',
            'MEDIUM')

    # 4. Liên hệ CSKH/cuộc gọi nhỡ tăng cao (call/missed cao, KHÔNG đi kèm complaint/technical mạnh)
    # — TÊN VÀ EVIDENCE CHỈ MÔ TẢ QUAN SÁT (số lần liên hệ/cuộc gọi nhỡ), KHÔNG suy ra kết luận nhân
    # quả "nhu cầu không được đáp ứng" — dữ liệu chỉ có TẦN SUẤT liên hệ, không có thông tin liên hệ
    # đó có được xử lý/giải quyết hay không, nên không đủ căn cứ để khẳng định "chưa đáp ứng".
    # GUARD BỔ SUNG (cùng gốc bug với rule 3 phía trên): chỉ khớp nếu call/missed thực sự là domain
    # NỔI BẬT NHẤT (>= complaint và >= technical), không khớp chỉ vì call/missed vượt ngưỡng tuyệt
    # đối 3⭐ trong khi 1 domain khác đang cao hơn hẳn (vd technical 4⭐ nhưng call cũng đạt 3⭐ —
    # không nên gán nhãn theo call khi technical mới là tín hiệu nổi bật hơn).
    if (s_call >= 3 or s_missed >= 3) and max(s_call, s_missed) >= s_complaint and max(s_call, s_missed) >= s_technical:
        return result(
            'Tăng liên hệ CSKH/cuộc gọi nhỡ trước khi rời mạng',
            'Tần suất liên hệ CSKH/cuộc gọi nhỡ tăng cao gần thời điểm rời mạng — dữ liệu chỉ phản ánh SỐ LẦN liên hệ, không xác định được các lần liên hệ này đã được xử lý thoả đáng hay chưa.',
            'MEDIUM')

    # 5. Khách hàng giá trị cao, chủ động rời mạng (giá trị cao, MỌI domain khác đều thấp)
    if s_value >= 4 and s_complaint <= 2 and s_call <= 2 and s_usage <= 2:
        return result(
            'Khách hàng giá trị cao, chủ động rời mạng',
            'Nhóm chi tiêu cao, hành vi sử dụng dịch vụ vẫn ổn định và không phát sinh khiếu nại/sự cố — nguyên nhân rời mạng nhiều khả năng đến từ yếu tố NGOÀI trải nghiệm dịch vụ (giá cước, ưu đãi đối thủ cạnh tranh...) chứ không phải chất lượng dịch vụ.',
            'MEDIUM')

    # 6. Khách hàng âm thầm rời mạng (usage suy giảm, giá trị không cao, không phàn nàn)
    if s_usage >= 3 and s_value <= 2 and s_complaint <= 2 and s_call <= 2:
        return result(
            'Khách hàng âm thầm rời mạng',
            'Không phát sinh khiếu nại hay liên hệ CSKH đáng kể, nhưng hành vi sử dụng dịch vụ suy giảm dần trước khi rời mạng — dấu hiệu "rời mạng trong im lặng" thay vì phản ánh qua kênh CSKH trước.',
            'MEDIUM')

    return result(
        'Không rõ nguyên nhân hành vi (có thể do giá cước/cạnh tranh/khác)',
        'Không phát hiện dấu hiệu khiếu nại hoặc sự cố đáng kể trong lịch sử tương tác — nguyên nhân rời mạng nhiều khả năng đến từ yếu tố NGOÀI hành vi tương tác (giá cước, đối thủ cạnh tranh, chuyển vùng...), không đủ dữ liệu hành vi để kết luận thêm.',
        'LOW')


def compute_churn_drivers(df, domain_signature=None, cluster_col='cluster'):
    domain_signature = domain_signature or {}
    return {cid: classify_churn_driver(grp, domain_signature.get(cid, {})) for cid, grp in df.groupby(cluster_col)}
