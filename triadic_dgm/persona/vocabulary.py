"""Shared telco vocabulary used to keep generic-dataset output domain-neutral.

Single source of truth for both enforcement layers, which must agree or output
leaks through whichever one is laxer:

* :mod:`triadic_dgm.persona.characterization` — scrubs persona *fields* emitted
  by the sandbox pipeline (``recommended_actions``, ``profile_attributes``).
* :mod:`triadic_dgm.services.report_generator` — scrubs the LLM *narrative*
  prose before it is rendered.

Kept in the persona layer (no dependencies) so services can import it without
creating a cycle.
"""
from typing import Final, Sequence, Tuple

#: Substrings that presuppose the telco churn domain. A generic dataset has no
#: such concept, so any text containing one of these is an unfounded claim about
#: data the pipeline never saw. Matched case-insensitively against lowercased
#: text; both accented and unaccented spellings are listed because the sandbox
#: LLM emits either.
GENERIC_FORBIDDEN_TERMS: Final[Tuple[str, ...]] = (
    "arpu", "churn", "cskh", "rời mạng", "roi mang", "khiếu nại", "khieu nai",
    "sự cố kỹ thuật", "su co ky thuat", "cước", "cuoc phi", "thuê bao", "rmdt",
    "giữ chân", "giu chan", "gói cước", "chăm sóc khách hàng", "bán chéo", "cross-sell",
    "upsell", "bán thêm", "retention", "win-back", "exit survey", "outbound",
    "csat", "loyalty", "tụt hạng", "nâng hạng", "hạ cấp", "tái kích hoạt",
)

#: Fallback actions for a generic dataset, mirroring ``generate_actions``'s
#: ``dataset_mode == "GENERIC"`` branch in ``prompts.py``. Duplicated here on
#: purpose: the prompt branch is soft steering the LLM may ignore, this is the
#: deterministic guarantee. Both have matching ``ROADMAP_METADATA`` entries in
#: report_generator, so they never render an "TBD" owner/timeline.
GENERIC_FALLBACK_ACTIONS: Final[Tuple[str, ...]] = (
    "Phân tích sâu các đặc điểm nổi bật của nhóm để hiểu hành vi đặc trưng",
    "Xây dựng chiến lược tiếp cận phù hợp với đặc trưng của nhóm",
)


def contains_forbidden_term(text: str) -> bool:
    """Report whether ``text`` asserts anything from the telco domain.

    Args:
        text: Arbitrary text; falsy input is treated as clean.

    Returns:
        True if any term in :data:`GENERIC_FORBIDDEN_TERMS` occurs in ``text``.
    """
    if not text:
        return False
    lowered = str(text).lower()
    return any(term in lowered for term in GENERIC_FORBIDDEN_TERMS)


def drop_forbidden(items: Sequence[str]) -> list[str]:
    """Filter telco-domain entries out of a list of short strings.

    Used for ``recommended_actions``, where each element is an independent
    claim, so a single contaminated action can be dropped without discarding
    the legitimate ones beside it.

    Args:
        items: Strings to filter; non-string elements are dropped.

    Returns:
        A new list containing only entries free of forbidden terms.
    """
    if not items:
        return []
    return [s for s in items if isinstance(s, str) and s.strip() and not contains_forbidden_term(s)]
