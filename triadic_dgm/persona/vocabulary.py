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

#: Literal identifiers from the telco dataset this system was first built on: column
#: names, and the client's name. Unlike :data:`GENERIC_FORBIDDEN_TERMS` — which are
#: *concepts* a generic dataset cannot support — these are *names*, and a model shown one
#: will happily write it into a column list for data that has no such column. Matched
#: case-insensitively as substrings, so ``cl_total`` also covers ``cl_total_6m``.
TELCO_IDENTIFIERS: Final[Tuple[str, ...]] = (
    "rmdt", "cuoc_hang_thang", "ctbdv", "objid", "cl_total", "cl_avg",
    "fee_total", "fee_avg", "complaint_total", "status_worsening", "loyalty_rank",
    "total_cl_t12", "filter_month", "filter_year", "segment_downgrade_count",
    "cnt_dao_dong", "vip_type", "high_spender", "ftel",
)


def mentions_telco_domain(text: str) -> bool:
    """Report whether ``text`` names the telco domain by concept OR by identifier.

    The union of the two lists, for callers deciding whether a whole block of text belongs
    in front of a model analysing unknown data.

    Args:
        text: Arbitrary text; falsy input is treated as clean.

    Returns:
        True if ``text`` contains a forbidden term or a telco identifier.
    """
    if not text:
        return False
    lowered = str(text).lower()
    return (any(term in lowered for term in GENERIC_FORBIDDEN_TERMS)
            or any(name in lowered for name in TELCO_IDENTIFIERS))


def dataset_is_telco(columns: Sequence[str] | None) -> bool:
    """Report whether the dataset actually in play carries telco columns.

    The dual-path switch. Everything telco-specific stays enabled when this is True, so the
    original churn analysis is unaffected; it is only the *other* datasets that get the
    domain stripped out.

    An empty sequence deliberately answers False rather than "unknown": callers reach that
    state when no dataset could be read, and the safe reading of "I cannot see any telco
    column" is that there is none. ``None`` means the caller is not making a claim at all
    and is handled by each caller's own default.

    Args:
        columns: Column names of the active dataset, or None if unknown.

    Returns:
        True if any column name contains a telco identifier.
    """
    if not columns:
        return False
    lowered = " ".join(str(c).lower() for c in columns)
    return any(name in lowered for name in TELCO_IDENTIFIERS)


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
