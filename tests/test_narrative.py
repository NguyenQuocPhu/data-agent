"""Tests for generic, dataset-agnostic persona narrative (no churn vocabulary)."""
from __future__ import annotations

from triadic_dgm.persona.characterization import compose_signal_narrative
from triadic_dgm.services.persona_json import describe_persona

_CHURN_WORDS = ("rời mạng", "churn", "cskh", "khiếu nại")


def _persona_with_signal() -> dict:
    return {
        "persona_name": "Nhóm A",
        "support": 1200,
        "support_pct": 0.42,
        "churn_driver": "Khách hàng âm thầm rời mạng",  # legacy telco field, must be ignored
        "distinguishing_signal": {
            "dominant_domain": "revenue",
            "stars": {"revenue": {"stars": 4, "max_dev": 3.0}},
            "top_features": [{"feature": "revenue_sum", "label": "Doanh thu", "deviation": 3.0}],
            "evidence": "Nhóm nổi bật nhất ở 'revenue': Doanh thu (+300% so với trung bình).",
        },
    }


def test_compose_signal_narrative_is_generic_and_has_size_plus_evidence():
    text = compose_signal_narrative(_persona_with_signal())
    assert "42.0%" in text or "42" in text  # size surfaced
    assert "Doanh thu" in text  # uses embedded label
    low = text.lower()
    for w in _CHURN_WORDS:
        assert w not in low


def test_compose_signal_narrative_empty_without_signal():
    assert compose_signal_narrative({"persona_name": "X", "support": 5}) == ""


def test_describe_persona_no_longer_uses_churn_wording():
    text = describe_persona(_persona_with_signal())
    low = text.lower()
    for w in _CHURN_WORDS:
        assert w not in low
    # still describes the group via the generic evidence
    assert "Doanh thu" in text


def test_describe_persona_never_raises_on_empty():
    assert isinstance(describe_persona({}), str)
