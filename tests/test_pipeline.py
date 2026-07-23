"""The persona core is now code, so it can finally be tested.

Every assertion here was previously unreachable: the logic existed only as text inside
PROGRAMMER_PROMPT_V2, retyped by the sandbox LLM on each run.
"""
import numpy as np
import pandas as pd
import pytest

from triadic_dgm.persona.pipeline import (
    choose_k,
    detect_dataset_mode,
    run_persona_pipeline,
    segmentation_quality,
)

_REQUIRED_KEYS = {
    "cluster_id", "support", "support_pct", "feature_means", "evidence", "persona_type",
    "severity", "risk", "persona_name", "priority_score", "domain_signature",
    "profile_attributes", "risk_tier", "segmentation_quality", "recommended_actions",
}


def _separable(n=900, seed=1):
    """Three groups that are genuinely distinct on two axes."""
    rng = np.random.default_rng(seed)
    g = np.repeat([0, 1, 2], n // 3)
    return pd.DataFrame({
        "spend": rng.normal(10, 1, n) + g * 25,
        "visits": rng.normal(5, 1, n) + g * 12,
        "noise": rng.normal(0, 1, n),
    })


# --- dataset mode -------------------------------------------------------------------

def test_generic_is_the_default():
    assert detect_dataset_mode(["spend", "visits", "fee_avg"]) == "GENERIC"


def test_paired_old_recent_columns_mean_post_churn():
    assert detect_dataset_mode(["old_call", "recent_call", "x"]) == "POST_CHURN"


def test_a_lone_old_column_is_not_enough():
    assert detect_dataset_mode(["old_call", "x"]) == "GENERIC"


def test_explicit_churn_target_means_pre_churn():
    assert detect_dataset_mode(["RMDT", "x"]) == "PRE_CHURN"


def test_fee_columns_alone_never_imply_an_active_base():
    """Historic fee/ARPU columns exist perfectly well in a set of customers who already
    left; treating them as evidence produced 'future churn risk' scores for churned rows."""
    assert detect_dataset_mode(["fee_total", "fee_avg", "arpu"]) == "GENERIC"


# --- k selection and quality --------------------------------------------------------

def test_choose_k_finds_the_real_group_count():
    from sklearn.preprocessing import StandardScaler

    df = _separable()[["spend", "visits"]]
    X = StandardScaler().fit_transform(df.to_numpy(dtype=float))
    k, sil, labels = choose_k(X)
    assert k == 3
    assert sil > 0.8
    assert len(labels) == len(df)


def test_a_pure_noise_feature_pushes_k_selection_upward():
    """Measured, not assumed: adding one N(0,1) column to cleanly-3-group data makes k=6
    score higher than k=3 (0.510 vs 0.478), because silhouette rewards carving the noise
    axis. Not a bug in choose_k — silhouette is the stated criterion — but it is why
    behavioral feature selection must drop uninformative columns before clustering."""
    from sklearn.preprocessing import StandardScaler

    X = StandardScaler().fit_transform(_separable().to_numpy(dtype=float))
    assert choose_k(X)[0] > 3


def test_choose_k_is_deterministic():
    from sklearn.preprocessing import StandardScaler

    X = StandardScaler().fit_transform(_separable().to_numpy(dtype=float))
    assert choose_k(X)[:2] == choose_k(X)[:2]


@pytest.mark.parametrize("sil,dom,expected", [
    (0.8, 0.9, "OUTLIER_DRIVEN"),
    (0.10, 0.4, "WEAK"),
    (0.4, 0.5, "NORMAL"),
])
def test_segmentation_quality_labels(sil, dom, expected):
    assert segmentation_quality(sil, dom) == expected


# --- the pipeline itself ------------------------------------------------------------

def test_produces_well_formed_personas():
    personas = run_persona_pipeline(_separable())
    assert len(personas) >= 3
    for p in personas:
        assert _REQUIRED_KEYS <= set(p)
        assert p["recommended_actions"]
    assert sum(p["support_pct"] for p in personas) == pytest.approx(1.0)
    assert sum(p["support"] for p in personas) == 900


def test_is_deterministic_across_runs():
    """The whole point of moving this out of the prompt: same data, same result."""
    a = run_persona_pipeline(_separable().copy())
    b = run_persona_pipeline(_separable().copy())
    assert [p["persona_name"] for p in a] == [p["persona_name"] for p in b]
    assert [p["support"] for p in a] == [p["support"] for p in b]


def test_persona_names_are_unique():
    for p in run_persona_pipeline(_separable()):
        pass
    names = [p["persona_name"] for p in run_persona_pipeline(_separable())]
    assert len(names) == len(set(names))


def test_a_dominant_cluster_is_split_rather_than_reported_as_failure():
    """Regression: an 86.5% dominant cluster used to abort the run outright, because
    Stage-2 looked for telco profile columns and found none on a non-telco dataset."""
    rng = np.random.default_rng(3)
    n = 1200
    # 90% of rows in one blob, but that blob has real internal structure.
    inner = np.repeat([0, 1], int(n * 0.9) // 2)
    big = pd.DataFrame({
        "spend": rng.normal(10, 1, len(inner)) + inner * 9,
        "visits": rng.normal(5, 1, len(inner)) + inner * 7,
        "ratio": rng.normal(1, 0.1, len(inner)),
    })
    small = pd.DataFrame({
        "spend": rng.normal(90, 2, n - len(inner)),
        "visits": rng.normal(70, 2, n - len(inner)),
        "ratio": rng.normal(4, 0.1, n - len(inner)),
    })
    df = pd.concat([big, small], ignore_index=True)
    personas = run_persona_pipeline(df)
    assert len(personas) >= 2
    assert max(p["support_pct"] for p in personas) < 0.8
    assert all(p.get("failure_reason") is None for p in personas)


def test_unsplittable_data_returns_a_stated_failure_not_an_exception():
    """The report layer needs valid JSON; a raised exception only feeds the repair loop."""
    df = pd.DataFrame({"a": [1.0] * 50, "b": [2.0] * 50})
    personas = run_persona_pipeline(df)
    assert len(personas) == 1
    assert personas[0]["failure_reason"]
    # Dataset-neutral: the old wording blamed "khách hàng" and asserted a cause it had
    # not established.
    assert "khách hàng" not in personas[0]["persona_name"].lower()


def test_empty_input_is_safe():
    personas = run_persona_pipeline(pd.DataFrame())
    assert len(personas) == 1 and personas[0]["failure_reason"] == "empty_dataset"


def test_non_numeric_columns_are_ignored_not_fatal():
    df = _separable()
    df["label"] = "text"
    personas = run_persona_pipeline(df)
    assert len(personas) >= 3


def test_explicit_feature_list_is_respected():
    df = _separable()
    personas = run_persona_pipeline(df, behavioral_features=["spend", "visits"])
    assert all("noise" not in p["feature_means"] for p in personas)
