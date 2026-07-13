"""Small, dependency-free helpers for parsing/normalizing persona JSON blocks.

Deliberately standalone rather than reusing ReportGenerator.extract_json /
clean_persona_name — those require a fully-constructed ReportGenerator (which builds an
instructor-wrapped OpenAI client in __init__), too heavy for callers that just need to
parse a string.
"""

from __future__ import annotations

import hashlib
import json
import re

_PERSONA_JSON_RE = re.compile(r"\[JSON_START_PERSONA\]\s*(.*?)\s*\[JSON_END_PERSONA\]", re.DOTALL)
_NHOM_SUFFIX_RE = re.compile(r" - Nhóm (\d+)$")

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
    size_bits = [b for b in (pct_str and f"khoảng {pct_str} tổng số khách hàng", support and f"~{support:,} KH".replace(",", ".")) if b]
    if size_bits:
        parts.append(f"Nhóm này chiếm {' — '.join(size_bits)}.")

    churn_driver = str(p.get("churn_driver") or "").strip()
    if churn_driver.lower() not in _GENERIC_CHURN_DRIVER_VALUES:
        parts.append(f"Nguyên nhân rời mạng chính được ghi nhận: {churn_driver}.")

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
