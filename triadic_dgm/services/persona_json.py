"""Small, dependency-free helpers for parsing/normalizing persona JSON blocks.

Deliberately standalone rather than reusing ReportGenerator.extract_json /
clean_persona_name — those require a fully-constructed ReportGenerator (which builds an
instructor-wrapped OpenAI client in __init__), too heavy for callers that just need to
parse a string.
"""

from __future__ import annotations

import json
import re

_PERSONA_JSON_RE = re.compile(r"\[JSON_START_PERSONA\]\s*(.*?)\s*\[JSON_END_PERSONA\]", re.DOTALL)
_NHOM_SUFFIX_RE = re.compile(r" - Nhóm (\d+)$")


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
