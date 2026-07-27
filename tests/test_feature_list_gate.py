"""A feature list naming columns the data lacks must fail loudly, not be silently replaced.

`run_persona_pipeline` filtered the caller's `behavioral_features` down to those that exist
and, when nothing survived, quietly fell back to auto-selecting numeric columns. That
fallback is what hid the defect this whole effort has been chasing.

Observed live on an Olist upload: the model emitted

    # For Iris dataset, the numeric features are Sepal Length, Sepal Width...
    behavioral_features = ['Sepal.Length', 'Sepal.Width', 'Petal.Length', 'Petal.Width']

Not one of those columns exists in the data. The pipeline dropped all four, auto-selected
its own, and returned a plausible-looking result — so the run "succeeded" while the model's
stated reasoning was about a different dataset entirely. A silent rescue that produces a
credible report is worse than a crash: nobody goes looking.

The pipeline still never raises — the report layer needs valid JSON — so the failure comes
back as a persona stating what went wrong.
"""
import pandas as pd
import pytest

from triadic_dgm.persona.pipeline import run_persona_pipeline


def _frame(n=200):
    import numpy as np
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "total_spend": rng.normal(100, 30, n),
        "order_count": rng.integers(1, 20, n).astype(float),
        "avg_review_score": rng.normal(4, 0.6, n),
        "customer_id": [f"c{i}" for i in range(n)],
    })


def test_a_wholly_foreign_feature_list_is_rejected():
    """The Iris-on-Olist case, verbatim."""
    personas = run_persona_pipeline(
        _frame(), behavioral_features=["Sepal.Length", "Sepal.Width", "Petal.Length"]
    )

    assert len(personas) == 1
    reason = personas[0].get("failure_reason") or ""
    assert "Sepal.Length" in reason, "the failure must name the columns that do not exist"
    assert personas[0]["support"] == 200


def test_a_partially_foreign_feature_list_is_also_rejected():
    """One wrong name means the model was reasoning about a schema it does not have.

    Deliberately strict. Accepting the valid subset is how a run half-based on another
    dataset still produces a confident report.
    """
    personas = run_persona_pipeline(
        _frame(), behavioral_features=["total_spend", "order_count", "cl_total_6m"]
    )

    reason = personas[0].get("failure_reason") or ""
    assert "cl_total_6m" in reason
    # The message also lists the columns that DO exist, which is the useful half of it —
    # so check the accusation itself, not the whole string.
    accused = reason.split("—")[0]
    assert "cl_total_6m" in accused
    assert "total_spend" not in accused, "a column that exists must not be blamed"


def test_the_failure_names_every_missing_column_not_just_the_first():
    personas = run_persona_pipeline(
        _frame(), behavioral_features=["total_spend", "fee_total", "OBJID_mask"]
    )
    reason = personas[0].get("failure_reason") or ""
    assert "fee_total" in reason and "OBJID_mask" in reason


def test_a_valid_feature_list_still_works():
    personas = run_persona_pipeline(
        _frame(), behavioral_features=["total_spend", "order_count", "avg_review_score"]
    )
    assert len(personas) > 1
    assert sum(p["support"] for p in personas) == 200


def test_omitting_the_feature_list_still_auto_selects():
    """Auto-selection is legitimate when the caller makes no claim; it is only wrong as a
    silent substitute for a claim that turned out false."""
    personas = run_persona_pipeline(_frame())
    assert len(personas) > 1


def test_a_non_numeric_existing_column_is_not_reported_as_missing():
    """`customer_id` exists but cannot be clustered on — a different problem, different
    message. Conflating the two would send the reader looking for a typo that isn't there."""
    personas = run_persona_pipeline(
        _frame(), behavioral_features=["total_spend", "order_count", "customer_id"]
    )
    reason = personas[0].get("failure_reason") or ""
    assert "customer_id" not in reason or "kiểu số" in reason
