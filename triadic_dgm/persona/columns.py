"""Column lookup helpers shared by the persona pipeline.

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

def get_column(cols, keywords):
    for c in cols:
        cl = str(c).lower()
        if any(kw in cl for kw in keywords):
            return c
    return None


def get_columns(cols, keyword_groups):
    found = []
    for kws in keyword_groups:
        c = get_column(cols, kws)
        if c is not None and c not in found:
            found.append(c)
    return found


def get_categorical_column(df, keywords):
    # Dùng cho các cột DANH MỤC (services, package_type) — get_column() thường dùng khớp SUBSTRING
    # thuần trên TÊN cột, nên có thể khớp NHẦM 1 cột SỐ ĐẾM có tên chứa cùng từ khóa (vd cột dịch vụ
    # tên 'services' bị khớp nhầm thành cột số như 'add_services'/'num_services' nếu cột đó đứng
    # trước trong thứ tự DataFrame — ĐÃ XẢY RA TRÊN DỮ LIỆU THẬT: value_counts() ra "0.0 (100%)"
    # thay vì tên dịch vụ thật như "Net Pay"). Ưu tiên khớp CHÍNH XÁC tên cột trước, sau đó mới khớp
    # substring NHƯNG bắt buộc kiểm tra cột đó thực sự là dạng text (không parse được thành số).
    cols = df.columns
    exact = [c for c in cols if str(c).lower() in keywords]
    if exact:
        return exact[0]
    for c in cols:
        cl = str(c).lower()
        if any(kw in cl for kw in keywords):
            sample = df[c].dropna()
            if len(sample) == 0:
                continue
            sample = sample.astype(str).head(200)
            numeric_frac = pd.to_numeric(sample, errors='coerce').notna().mean()
            if numeric_frac < 0.5:
                return c
    return None


def get_metric(m, keywords):
    for k, v in m.items():
        if any(kw in k.lower() for kw in keywords):
            return float(v)
    return 0.0
