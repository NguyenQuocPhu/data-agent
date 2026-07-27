"""The LLM proposes labels; Python decides which are safe to display.

These tests cover the deterministic half only — no network. A label that fails validation
must leave the column with its raw name, because a truthful identifier beats a confident
wrong label in a persona name.
"""
import pandas as pd
import pytest

from triadic_dgm.persona.dataset_profile import load_or_build_cached
from triadic_dgm.persona.label_inference import infer_column_labels, validate_labels

_COLS = ["late_delivery_rate", "avg_item_price", "total_spend"]


def test_accepts_plain_readable_labels():
    out = validate_labels(
        {"late_delivery_rate": "Tỷ lệ giao hàng trễ", "avg_item_price": "Giá trung bình mỗi món"},
        _COLS, allow_domain_terms=False,
    )
    assert out == {
        "late_delivery_rate": "Tỷ lệ giao hàng trễ",
        "avg_item_price": "Giá trung bình mỗi món",
    }


def test_drops_hallucinated_columns():
    out = validate_labels({"column_that_does_not_exist": "Bất kỳ"}, _COLS, allow_domain_terms=False)
    assert out == {}


@pytest.mark.parametrize("bad", ["", "   ", "x" * 60])
def test_drops_empty_and_overlong_labels(bad):
    assert validate_labels({"total_spend": bad}, _COLS, allow_domain_terms=False) == {}


def test_drops_label_identical_to_column_name():
    """No information gained — the identity fallback already covers it."""
    assert validate_labels({"total_spend": "total_spend"}, _COLS, allow_domain_terms=False) == {}


def test_rejects_invented_telco_vocabulary_on_a_generic_dataset():
    """The model must not turn `total_spend` into ARPU on a dataset with no such concept."""
    out = validate_labels(
        {"total_spend": "ARPU trung bình", "avg_item_price": "Giá trung bình mỗi món"},
        _COLS, allow_domain_terms=False,
    )
    assert "total_spend" not in out
    assert out["avg_item_price"] == "Giá trung bình mỗi món"


def test_allows_telco_vocabulary_when_the_dataset_really_is_telco():
    out = validate_labels(
        {"total_spend": "ARPU trung bình"}, _COLS, allow_domain_terms=True,
    )
    assert out == {"total_spend": "ARPU trung bình"}


def test_normalises_whitespace_and_trailing_period():
    out = validate_labels({"total_spend": "  Tổng   chi tiêu.  "}, _COLS, allow_domain_terms=False)
    assert out == {"total_spend": "Tổng chi tiêu"}


def test_infer_returns_empty_when_the_llm_is_unreachable():
    """Total failure must degrade to the previous behaviour, not raise."""
    df = pd.DataFrame({c: [1.0, 2.0] for c in _COLS})

    def _boom():
        raise ConnectionError("no network")

    assert infer_column_labels(df, client_factory=_boom, model_name="m") == {}


# --- integration with the profile cache --------------------------------------------

def test_enricher_fills_raw_names_but_never_overrides_curated_labels(tmp_path):
    df = pd.DataFrame({"total_spend": [1.0, 2.0], "avg_item_price": [3.0, 4.0]})
    metadata = {
        "dataset_name": "d",
        "columns": [
            # curated label present -> must win
            {"column": "total_spend", "type": "float", "sample": "1", "description": "Doanh thu"},
            # raw name placeholder -> enricher may fill
            {"column": "avg_item_price", "type": "float", "sample": "3", "description": "avg_item_price"},
        ],
    }
    profile = load_or_build_cached(
        df, str(tmp_path), metadata=metadata,
        label_enricher=lambda d, p: {"total_spend": "KHÔNG ĐƯỢC GHI ĐÈ", "avg_item_price": "Giá mỗi món"},
    )
    assert profile.labels["total_spend"] == "Doanh thu"
    assert profile.labels["avg_item_price"] == "Giá mỗi món"


def test_enricher_failure_leaves_the_profile_usable(tmp_path):
    df = pd.DataFrame({"total_spend": [1.0, 2.0]})

    def _boom(d, p):
        raise RuntimeError("inference exploded")

    profile = load_or_build_cached(df, str(tmp_path), label_enricher=_boom)
    assert profile.label("total_spend") == "total_spend"


def test_enricher_is_not_called_on_a_cache_hit(tmp_path):
    """The convergence loop runs continuously; paying for inference per run is not viable."""
    df = pd.DataFrame({"total_spend": [1.0, 2.0]})
    calls = []

    def _enricher(d, p):
        calls.append(1)
        return {"total_spend": "Tổng chi tiêu"}

    first = load_or_build_cached(df, str(tmp_path), label_enricher=_enricher)
    second = load_or_build_cached(df, str(tmp_path), label_enricher=_enricher)
    assert len(calls) == 1
    assert first.labels == second.labels == {"total_spend": "Tổng chi tiêu"}
