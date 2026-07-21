"""Small, dependency-free helpers for parsing/normalizing persona JSON blocks.

Deliberately standalone rather than reusing ReportGenerator.extract_json /
clean_persona_name — those require a fully-constructed ReportGenerator (which builds an
instructor-wrapped OpenAI client in __init__), too heavy for callers that just need to
parse a string.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

_PERSONA_JSON_RE = re.compile(r"\[JSON_START_PERSONA\]\s*(.*?)\s*\[JSON_END_PERSONA\]", re.DOTALL)
_NHOM_SUFFIX_RE = re.compile(r" - Nhóm (\d+)$")

# Metadata for the convergence loop's fixed dataset (workspace/convergence/index.json ->
# data_processed_t4.csv) — repo-root file, read-only reference, never modified. Used only to
# translate raw column names (cl_recent_only, fee_trend, ...) into Vietnamese business labels
# for display, so a non-technical reader (e.g. ban giám đốc) doesn't have to guess what a
# column name means.
_FEATURE_METADATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data_processed_t4_metadata.json"
)


def _load_feature_labels() -> dict[str, str]:
    try:
        with open(_FEATURE_METADATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            c["column"]: c["description"]
            for c in data.get("columns", [])
            if c.get("column") and c.get("description")
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


FEATURE_LABELS: dict[str, str] = _load_feature_labels()


def get_feature_label(feature: str) -> str:
    """Human-readable Vietnamese description of a raw feature/column name, sourced from
    data_processed_t4_metadata.json. Falls back to the raw name itself if the column isn't
    in the metadata (e.g. a derived/renamed column the pipeline computed on the fly)."""
    return FEATURE_LABELS.get(feature, feature)


# profile_attributes (report_generator.py's _build_profile_context / prompts.py's
# compute_profile_attributes) are pipeline-DERIVED keys, not raw dataset columns — so they
# aren't in data_processed_t4_metadata.json and need their own label map.
PROFILE_ATTR_LABELS: dict[str, str] = {
    "avg_fee": "ARPU trung bình (cước phí trung bình/tháng)",
    "high_spender_pct": "Tỷ lệ khách hàng chi tiêu cao",
    "loyalty_rank_avg": "Hạng loyalty trung bình",
    "tier_upgrade_rate": "Tỷ lệ nâng hạng phân khúc",
    "tier_downgrade_rate": "Tỷ lệ tụt hạng phân khúc",
    "usage_decline_strong_pct": "Tỷ lệ giảm sử dụng mạnh",
    "usage_decline_mild_pct": "Tỷ lệ giảm sử dụng nhẹ",
    "usage_unstable_pct": "Tỷ lệ sử dụng dao động",
    "status_worsening_pct": "Tỷ lệ trạng thái thuê bao xấu đi",
    "csat_avg": "CSAT trung bình",
    "ces_avg": "CES trung bình",
}


def get_profile_attr_label(key: str) -> str:
    return PROFILE_ATTR_LABELS.get(key, key)


# LOYALTY_RANK is a CATEGORICAL tier code (confirmed against the real dataset: only values
# 0-4 ever occur), not a continuous metric — showing its cluster average as a bare float like
# "1.03" is meaningless to a reader. Map to the actual business tier names.
LOYALTY_RANK_TIER_LABELS = {
    0: "Không có hạng",
    1: "Bạc",
    2: "Vàng",
    3: "Bạch kim",
    4: "Kim cương",
}


def format_loyalty_rank_avg(val: float) -> str:
    """Cluster-average loyalty rank -> 'value (~nearest tier)'. Values outside the valid 0-4
    range are a known intermittent pipeline bug (compute_profile_attributes in prompts.py is
    regenerated fresh by the LLM each run and occasionally grabs LOYALTY_POINT/LOYALTY_COIN by
    mistake instead of LOYALTY_RANK — confirmed on live data: real LOYALTY_RANK never exceeds
    4, but some runs recorded 940+) — flag those instead of pretending they map to a real tier."""
    if not isinstance(val, (int, float)):
        return str(val)
    if val < -0.5 or val > 4.5:
        return f"{val:.2f} (bất thường — ngoài khoảng hợp lệ 0-4, có thể do lỗi chọn nhầm cột)"
    nearest = max(0, min(4, round(val)))
    return f"{val:.2f} (~{LOYALTY_RANK_TIER_LABELS[nearest]})"

# Mirrors report_generator.py's EXCLUDED_TECHNICAL_FEATURES — kept as its own small copy
# rather than imported, same rationale as the rest of this module (dependency-free, no
# ReportGenerator construction needed just to fingerprint a persona dict).
_EXCLUDED_TECHNICAL_FEATURES = {"cluster", "cluster_id", "is_anomaly", "persona_type", "priority_score"}


def extract_persona_list(raw_text: str) -> list[dict]:
    """Find the [JSON_START_PERSONA]...[JSON_END_PERSONA] block and return the parsed
    list of persona dicts. Returns [] if the markers are absent or the JSON is invalid —
    never raises.

    Callers that pass a FULL multi-round transcript (e.g. an entire stream_workflow() chat
    history, not just one execution round's stdout) can contain more than one occurrence of
    these markers — e.g. an earlier Inspector Hypothesis / fix-instruction message that
    quotes the markers as illustrative text. Scanning from the LAST match backwards (instead
    of taking the first) and validating shape before accepting it avoids latching onto stale
    or non-JSON text from an earlier round instead of the final, real result."""
    if not raw_text:
        return []
    matches = _PERSONA_JSON_RE.findall(raw_text)
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, list) or not data:
            continue
        personas = [p for p in data if isinstance(p, dict) and "persona_name" in p]
        if personas:
            return personas
    return []


_GENERIC_CHURN_DRIVER_VALUES = {"", "đang xử lý", "none", "n/a", "chưa xác định"}


def describe_persona(p: dict) -> str:
    """Compose a short, deterministic Vietnamese description straight from the raw
    persona fields — no LLM call. The convergence loop only captures the pipeline's raw
    clustering output (not the separate LLM-authored narrative pass the full report uses),
    and calling an LLM here would add latency/failure risk to every loop iteration for a
    lightweight monitoring feed — so this stays 100% derived from data already in hand."""
    parts: list[str] = []

    support_pct = p.get("support_pct")
    support = p.get("support")
    pct_str = f"{support_pct * 100:.1f}%" if isinstance(support_pct, (int, float)) else None
    size_bits = [b for b in (pct_str and f"khoảng {pct_str} tổng thể", support and f"~{support:,} bản ghi".replace(",", ".")) if b]
    if size_bits:
        parts.append(f"Nhóm này chiếm {' — '.join(size_bits)}.")

    sig = p.get("distinguishing_signal")
    if isinstance(sig, dict):
        evidence = str(sig.get("evidence") or "").strip()
        if evidence:
            parts.append(evidence)

    risk, severity = p.get("risk"), p.get("severity")
    if risk or severity:
        parts.append(f"Mức độ rủi ro: {risk or 'N/A'} · Mức độ nghiêm trọng: {severity or 'N/A'}.")

    actions = [a for a in (p.get("recommended_actions") or []) if a]
    if actions:
        parts.append(f"Đề xuất hành động: {', '.join(actions[:2])}.")

    return " ".join(parts) if parts else "Chưa có đủ dữ liệu để mô tả persona này."


_DUPLICATE_NAME_SUFFIX_RE = re.compile(r"^(.+) \(\1\)$")


def clean_display_persona_name(raw_name: str) -> str:
    """Fix a display-only pipeline artifact: the disambiguation-suffix code sometimes ends up
    appending the persona's OWN full name back onto itself in parens instead of a distinguishing
    tier/cluster suffix (e.g. 'X (X)' — observed live: 'Khách hàng gặp sự cố kỹ thuật không
    được xử lý triệt để (Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để)'), presumably
    because that run had only 1 cluster for that churn_driver so the 'distinguishing' text
    came out identical to the base name. Collapses back to the base name. Does NOT touch
    persona_name_normalized/fingerprint matching — this is purely a display cleanup."""
    name = (raw_name or "").strip()
    # Strip unrendered Python template literals that leak into a persona_name when the pipeline's
    # LLM-generated naming code builds a name with an f-string but forgets the `f` prefix (or the
    # variable is undefined) — observed live: "... - Mức thấp - {tier_counts[tier]}". The raw
    # "{...}" fragment is never legitimate Vietnamese name text, so drop it and any dangling
    # separator it leaves behind.
    if "{" in name:
        name = re.sub(r"\s*[-–]?\s*\{[^}]*\}", "", name)
        name = re.sub(r"[\s\-–]+$", "", name).strip()
    m = _DUPLICATE_NAME_SUFFIX_RE.match(name)
    return m.group(1).strip() if m else name


def normalize_persona_name(raw_name: str) -> str:
    """Strip disambiguation suffixes added when 2 clusters in the same run collide on a
    name (see prompts.py's apply_business_rules dedup logic), so persona_name can be used
    as a cross-run matching key. Mirrors ReportGenerator.clean_persona_name."""
    name = (raw_name or "").strip()
    if not name:
        return name
    if " - Cluster " in name:
        name = name.split(" - Cluster ")[0].strip()
    m = _NHOM_SUFFIX_RE.search(name)
    if m:
        name = f"{name[:m.start()].strip()} ({m.group(1)})"
    if " - Rank" in name:
        name = name.split(" - Rank")[0].strip()
    return name.lower()


def compute_fingerprint(p: dict) -> str:
    """Identify a persona across runs by its actual STATISTICS instead of its LLM-generated
    display name. The clustering/persona-naming code is regenerated fresh every run, so the
    same underlying cluster gets a different persona_name almost every time even though its
    support_pct and feature_means are reproduced near-bit-for-bit (confirmed directly on live
    convergence-loop data, e.g. feature_means['spending_decline']==0.7356 exactly across 4+
    runs under 4+ different names) — matching on name alone made the convergence feed treat
    a genuinely stable cluster as a stream of unrelated 'new' personas.

    support_pct is rounded to 3 decimals (0.1pp) and every numeric feature_means/evidence
    value to 3 decimals, sorted by feature name for order-independence, then hashed — cheap
    to store/compare as a single indexed TEXT column instead of a fuzzy/distance query."""
    support_pct = p.get("support_pct")
    support_bucket = round(float(support_pct), 3) if isinstance(support_pct, (int, float)) else None

    means = p.get("feature_means") or p.get("evidence") or {}
    # Degenerate personas (e.g. "Clustering Failed" / "Error in generation" placeholder
    # rows the pipeline emits on a bad run) have been observed with feature_means as a
    # plain string instead of a dict — guard so one malformed row can't blow up a whole
    # batch backfill/save_run transaction.
    feature_sig = (
        sorted(
            (str(f), round(float(v), 3))
            for f, v in means.items()
            if isinstance(v, (int, float)) and str(f).lower() not in _EXCLUDED_TECHNICAL_FEATURES
        )
        if isinstance(means, dict)
        else []
    )

    if support_bucket is None and not feature_sig:
        # No usable stats at all (degenerate/error persona) — fall back to name so it still
        # gets a stable (if imperfect) identity instead of colliding with every other blank one.
        return "name:" + normalize_persona_name(p.get("persona_name", ""))

    raw = json.dumps([support_bucket, feature_sig], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
