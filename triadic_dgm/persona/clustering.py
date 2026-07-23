"""Stage-2 sub-clustering of an over-dominant cluster.

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

from triadic_dgm.persona.columns import get_column, get_columns

def try_substage_cluster(data, dominant_cid, cluster_col='cluster'):
    from sklearn.cluster import KMeans as _KMeans2
    from sklearn.preprocessing import StandardScaler as _Scaler2
    from sklearn.metrics import silhouette_score as _sil2

    subset_mask = data[cluster_col] == dominant_cid
    subset = data.loc[subset_mask]
    cols = data.columns

    stage2_keyword_groups = [
        ['high_spender'], ['fee_total', 'fee_avg'], ['fee_trend'],
        ['segment_upgrade_count'], ['segment_downgrade_count'], ['segment_trend'],
        ['spending_decline'], ['spending_growth'],
        ['persistent_giam_manh'], ['ever_giam_manh'], ['ever_giam_nhe'], ['cnt_dao_dong'],
        ['status_worsening'], ['status_trend'],
        ['loyalty_rank'], ['loyalty_status'], ['loyalty_point'], ['loyalty_coin'],
        ['customer_type'], ['vip_type'],
    ]
    stage2_profile_cols = get_columns(cols, stage2_keyword_groups)
    if len(stage2_profile_cols) < 3:
        # GENERIC FALLBACK — the keyword groups above are telco PROFILE columns, so on any
        # other dataset they match nothing, Stage-2 never runs, and the >0.8 dominant-cluster
        # hard stop below then aborts the whole run. ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT (retail 50k
        # dòng): "n_features_found: 0, reason: insufficient_features", cụm dominant 86.5%,
        # và script xuất ra đúng 1 persona "Clustering Failed" — trong khi dữ liệu hoàn toàn
        # tách được, chỉ là không có cột telco nào để Stage-2 bám vào.
        # Fall back to the subset's OWN numeric columns that still vary INSIDE the dominant
        # cluster: sub-structure the global clustering missed is exactly what this stage
        # looks for, and the silhouette/size gates below still reject a bad split.
        numeric_sub = subset.select_dtypes(include='number')
        stage2_profile_cols = [
            c for c in numeric_sub.columns
            if c != cluster_col and numeric_sub[c].nunique(dropna=True) > 1
        ]
    info = {'attempted': False, 'n_features_found': len(stage2_profile_cols), 'reason': None}

    if len(stage2_profile_cols) < 3:
        info['reason'] = 'insufficient_features'
        return data, False, info

    stage2_matrix = subset[stage2_profile_cols].apply(lambda c: pd.to_numeric(c, errors='coerce')).fillna(0)
    nonzero_frac = (stage2_matrix != 0).any(axis=1).mean()
    if nonzero_frac < 0.01 or stage2_matrix.nunique().max() <= 1:
        info['reason'] = 'no_variance'
        return data, False, info

    info['attempted'] = True
    scaler2 = _Scaler2()
    X_sub = scaler2.fit_transform(stage2_matrix)

    best_k2, best_sil2, best_labels2 = None, -1.0, None
    for k2 in range(2, 5):
        if k2 >= len(subset):
            break
        labels2 = _KMeans2(n_clusters=k2, random_state=42, n_init=10).fit_predict(X_sub)
        if len(set(labels2)) < 2:
            continue
        sil2 = _sil2(X_sub, labels2, sample_size=min(5000, len(X_sub)), random_state=42)
        if sil2 > best_sil2:
            best_k2, best_sil2, best_labels2 = k2, sil2, labels2

    if best_labels2 is None or best_sil2 < 0.2:
        info['reason'] = f'low_silhouette({best_sil2:.3f})' if best_labels2 is not None else 'no_valid_k'
        return data, False, info

    sub_sizes = pd.Series(best_labels2).value_counts(normalize=True)
    if sub_sizes.max() > 0.8:
        info['reason'] = 'stage2_still_dominant'
        return data, False, info

    max_existing_cid = int(data[cluster_col].max())
    data.loc[subset_mask, cluster_col] = best_labels2 + (max_existing_cid + 1)
    info.update(reason='success', best_k2=int(best_k2), best_silhouette2=round(float(best_sil2), 4),
                stage2_features_used=stage2_profile_cols)
    return data, True, info
