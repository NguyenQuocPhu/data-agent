"""A percentage deviation is only meaningful against a positive baseline.

The report stated, of a retail dataset:

    Số ngày chênh lệch giao hàng: cao hơn trung bình toàn tập 187%
    avg_delivery_delay_days | 9.74 | -11.18 | +187.1%

The column is a *signed* delay: negative means delivered early. Its population mean is
-11.18 (min -146, max +175.9). "187% above a mean of -11.18" is arithmetic without meaning —
the quantity crossed zero, so there is no magnitude to be a percentage of. The report
asserted it as a fact, which is exactly the class of unfounded claim this system exists to
prevent.

Three call sites computed `(v - g) / abs(g)` independently, so they are routed through one
function here — the same reason `vocabulary.py` exists.
"""
import pytest

from triadic_dgm.persona.characterization import relative_deviation


def test_an_ordinary_positive_baseline_is_unchanged():
    assert relative_deviation(150.0, 100.0) == pytest.approx(0.5)
    assert relative_deviation(50.0, 100.0) == pytest.approx(-0.5)


def test_a_negative_baseline_has_no_meaningful_percentage():
    """The production case: mean -11.18, cluster value 9.74."""
    assert relative_deviation(9.74, -11.18) is None


def test_a_zero_baseline_has_no_meaningful_percentage():
    assert relative_deviation(5.0, 0.0) is None
    assert relative_deviation(0.0, 0.0) is None


def test_a_negative_value_over_a_positive_baseline_is_fine():
    """Only the BASELINE must be positive; the value may be anything.

    A cluster mean of -5 against a population mean of +10 is a real, describable 150% drop.
    """
    assert relative_deviation(-5.0, 10.0) == pytest.approx(-1.5)


def test_non_numeric_input_is_rejected_rather_than_raising():
    assert relative_deviation(None, 10.0) is None
    assert relative_deviation(10.0, None) is None
    assert relative_deviation("x", 10.0) is None


def test_a_rate_baseline_still_works():
    """late_delivery_rate 0.99 vs 0.08 is a genuine +1127%, and must survive."""
    assert relative_deviation(0.99, 0.08) == pytest.approx(11.375)


# --- the consumers -------------------------------------------------------------------

def test_profile_bullets_state_absolutes_when_the_percentage_is_meaningless():
    """The reader must still learn the number — just not a false percentage."""
    from triadic_dgm.services.report_generator import ReportGenerator

    gen = ReportGenerator.__new__(ReportGenerator)
    persona = {"distinguishing_signal": {"top_features": [
        {"feature": "avg_delivery_delay_days", "label": "Số ngày chênh lệch giao hàng",
         "deviation": None, "value": 9.74, "baseline": -11.18},
        {"feature": "total_spend", "label": "Tổng chi tiêu", "deviation": 0.42},
    ]}}

    bullets = gen._build_generic_profile_bullets(persona)

    joined = " ".join(bullets)
    assert "187" not in joined
    assert "9.74" in joined and "-11.18" in joined, "absolute values replace the percentage"
    assert "Tổng chi tiêu: cao hơn trung bình toàn tập 42%" in joined


def test_top_features_carry_none_for_an_unusable_baseline():
    from triadic_dgm.persona.characterization import _top_features

    top = _top_features(
        means={"delay": 9.74, "spend": 150.0},
        global_means={"delay": -11.18, "spend": 100.0},
        labels={},
    )
    by_feature = {t["feature"]: t for t in top}

    assert by_feature["delay"]["deviation"] is None
    assert by_feature["delay"]["value"] == pytest.approx(9.74)
    assert by_feature["delay"]["baseline"] == pytest.approx(-11.18)
    assert by_feature["spend"]["deviation"] == pytest.approx(0.5)


def test_a_feature_with_no_usable_percentage_does_not_win_the_ranking():
    """Ranking is by |deviation|; an unusable one must not sort as if it were huge."""
    from triadic_dgm.persona.characterization import _top_features

    top = _top_features(
        means={"delay": 9.74, "spend": 150.0},
        global_means={"delay": -11.18, "spend": 100.0},
        labels={},
        top_n=1,
    )
    assert top[0]["feature"] == "spend"
