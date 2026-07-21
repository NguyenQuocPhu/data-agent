"""Unit tests for generic, unsupervised cluster characterization."""
from __future__ import annotations

from triadic_dgm.persona.characterization import (
    characterize_personas,
    compute_domain_stars,
    distinguishing_signal,
    stars_from_max_dev,
)


class _FakeProfile:
    """Minimal stand-in for DatasetProfile (only domains + labels are used here)."""

    def __init__(self, domains, labels):
        self.domains = domains
        self.labels = labels


def test_stars_ladder():
    assert stars_from_max_dev(6.0) == 5
    assert stars_from_max_dev(3.0) == 4
    assert stars_from_max_dev(1.0) == 3
    assert stars_from_max_dev(0.3) == 2
    assert stars_from_max_dev(0.0) == 1
    assert stars_from_max_dev(-1.0) == 1  # below average is never a "signal"


def test_compute_domain_stars_uses_provided_domains():
    means = {"call_total": 10.0, "visits_total": 1.0}
    global_means = {"call_total": 2.0, "visits_total": 1.0}
    domains = {"call": ["call_total"], "visits": ["visits_total"]}
    stars = compute_domain_stars(means, global_means, domains)
    assert stars["call"]["stars"] == 4  # (10-2)/2 = 4.0 -> >=2 -> 4 stars
    assert stars["visits"]["stars"] == 1  # no deviation


def test_distinguishing_signal_picks_dominant_and_is_not_churn_worded():
    means = {"call_total": 10.0, "visits_total": 1.0}
    global_means = {"call_total": 2.0, "visits_total": 1.0}
    domains = {"call": ["call_total"], "visits": ["visits_total"]}
    labels = {"call_total": "Số cuộc gọi tổng"}
    sig = distinguishing_signal(means, global_means, domains, labels)
    assert sig["dominant_domain"] == "call"
    assert sig["top_features"][0]["feature"] == "call_total"
    assert sig["top_features"][0]["label"] == "Số cuộc gọi tổng"
    low = sig["evidence"].lower()
    for banned in ("rời mạng", "churn", "cskh", "khiếu nại"):
        assert banned not in low


def test_weak_signal_yields_neutral_evidence():
    means = {"a": 1.0, "b": 1.0}
    global_means = {"a": 1.0, "b": 1.0}
    domains = {"a": ["a"], "b": ["b"]}
    sig = distinguishing_signal(means, global_means, domains, {})
    assert max(d["stars"] for d in sig["stars"].values()) <= 2
    assert sig["evidence"]  # non-empty, neutral


def test_characterize_personas_is_additive_and_generic():
    profile = _FakeProfile(
        domains={"revenue": ["revenue_sum"], "visits": ["visits_total"]},
        labels={"revenue_sum": "Doanh thu", "visits_total": "Số lượt ghé"},
    )
    personas = [
        {"persona_name": "A", "churn_driver": "KEEP_ME", "feature_means": {"revenue_sum": 900.0, "visits_total": 3.0}},
    ]
    global_means = {"revenue_sum": 100.0, "visits_total": 3.0}
    characterize_personas(personas, global_means, profile)
    p = personas[0]
    assert "distinguishing_signal" in p
    assert p["distinguishing_signal"]["dominant_domain"] == "revenue"
    assert p["churn_driver"] == "KEEP_ME"  # telco field untouched (additive)


def test_characterize_never_raises_on_bad_persona():
    profile = _FakeProfile(domains={"x": ["x"]}, labels={})
    personas = [
        {"persona_name": "bad", "feature_means": "not-a-dict"},  # degenerate
        {"persona_name": "ok", "feature_means": {"x": 5.0}},
    ]
    characterize_personas(personas, {"x": 1.0}, profile)  # must not raise
    assert "distinguishing_signal" in personas[1]


from triadic_dgm.persona.characterization import generic_persona_name


def _strong_sig():
    return {
        "dominant_domain": "usage",
        "stars": {"usage": {"stars": 4, "max_dev": 2.1}},
        "top_features": [{"feature": "usage_avg", "label": "Mức sử dụng", "deviation": 2.1}],
        "evidence": "…",
    }


def test_generic_persona_name_from_strong_signal():
    name = generic_persona_name(_strong_sig())
    assert "Mức sử dụng" in name
    assert "cao" in name
    # dataset-neutral: no telco/churn vocabulary
    assert "churn" not in name.lower()
    assert "rời mạng" not in name.lower()
    assert "Khách hàng" not in name


def test_generic_persona_name_negative_direction():
    sig = _strong_sig()
    sig["top_features"][0]["deviation"] = -1.5
    assert "thấp" in generic_persona_name(sig)


def test_generic_persona_name_weak_signal_falls_back():
    weak = {"dominant_domain": "usage", "stars": {"usage": {"stars": 1, "max_dev": 0.0}}, "top_features": [], "evidence": ""}
    assert generic_persona_name(weak) == "Nhóm chưa phân hoá rõ"


def test_generic_persona_name_none_is_safe():
    assert generic_persona_name(None) == "Nhóm chưa phân hoá rõ"


from triadic_dgm.persona.characterization import enforce_generic_persona


def test_enforce_generic_persona_neutralises_churn_and_renames():
    p = {
        "persona_name": "Khách hàng âm thầm rời mạng",
        "churn_driver": "Silent Premium Churn",
        "churn_driver_evidence": "…",
        "churn_driver_confidence": "MEDIUM",
        "temporal_trajectory": [1, 2, 3],
        "domain_signature": {"value": {"stars": 5}},
        "distinguishing_signal": {
            "dominant_domain": "usage",
            "stars": {"usage": {"stars": 4, "max_dev": 2.1}},
            "top_features": [{"feature": "usage_avg", "label": "Mức sử dụng", "deviation": 2.1}],
            "evidence": "…",
        },
    }
    enforce_generic_persona([p], profile=object())
    assert p["churn_driver"] is None
    assert p["churn_driver_evidence"] is None
    assert p["churn_driver_confidence"] is None
    assert p["temporal_trajectory"] == []
    assert p["domain_signature"] == {}
    assert "rời mạng" not in p["persona_name"].lower()
    assert "Mức sử dụng" in p["persona_name"]


def test_enforce_generic_persona_is_best_effort():
    # A degenerate persona (no signal) must not raise and must still null churn.
    p = {"persona_name": "x", "churn_driver": "Y"}
    enforce_generic_persona([p], profile=object())
    assert p["churn_driver"] is None
    assert p["persona_name"] == "Nhóm chưa phân hoá rõ"


def test_enforce_generic_persona_empty_list_is_noop():
    enforce_generic_persona([], profile=object())  # must not raise
