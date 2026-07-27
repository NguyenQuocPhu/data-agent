"""The feature set must be chosen by the pipeline, not by whichever list the model improvised.

Extracting the pipeline into Python removed the run-to-run variance in the clustering
*code*. It did not remove it from the clustering *input*: the model still picks
`behavioral_features` freshly each time, and two runs over the same 50,000-row file produced

    12 features chosen by the model  ->  k=4, silhouette 0.426, dominant 58.0%
     9 features chosen by the model  ->  k=3, silhouette 0.286, dominant 73.4%

Same data, same code, two different segmentations — the second 33% worse by the only
quality measure available. Meanwhile the pipeline's own deterministic selection scored
0.426, matching the model's best attempt and beating its worst.

Scoring both sets and keeping the higher silhouette was tried first and rejected — see
test_silhouette_alone_cannot_arbitrate below, which records why. So the deterministic rule
wins outright: on GENERIC data the pipeline uses every numeric column that varies, and the
caller's list is validated but not used. Callers wanting a subset filter the DataFrame
first, which is what the prompt already instructs.

Only on GENERIC data. On the telco path the feature list carries domain meaning no
clustering metric can see, and that path is deliberately left exactly as it was.
"""
import numpy as np
import pandas as pd

from triadic_dgm.persona.pipeline import run_persona_pipeline


def _separable(n=450):
    """Two features that separate three groups cleanly, plus two pure-noise columns."""
    rng = np.random.default_rng(11)
    third = n // 3
    signal_a = np.concatenate([rng.normal(c, 0.6, third) for c in (0, 10, 20)])
    signal_b = np.concatenate([rng.normal(c, 0.6, third) for c in (0, 10, 20)])
    return pd.DataFrame({
        "spend": signal_a,
        "visits": signal_b,
        "noise_1": rng.normal(0, 5, third * 3),
        "noise_2": rng.normal(0, 5, third * 3),
    })


def _selection(personas):
    return personas[0].get("feature_selection")


def test_a_caller_list_does_not_decide_the_segmentation_on_generic_data():
    """The production case: the model named fewer columns and got a worse segmentation."""
    personas = run_persona_pipeline(_separable(), behavioral_features=["noise_1", "noise_2"])
    assert _selection(personas) == "auto"
    assert set(personas[0]["features_used"]) == {"spend", "visits", "noise_1", "noise_2"}


def test_the_result_is_the_same_whatever_the_caller_proposes():
    """The whole point: identical data must give an identical segmentation."""
    a = run_persona_pipeline(_separable(), behavioral_features=["noise_1", "noise_2"])
    b = run_persona_pipeline(_separable(), behavioral_features=["spend", "visits"])
    c = run_persona_pipeline(_separable())
    names = [[p["persona_name"] for p in x] for x in (a, b, c)]
    assert names[0] == names[1] == names[2]


def test_silhouette_alone_cannot_arbitrate():
    """Why the two-candidate comparison was abandoned, kept as an executable record.

    Silhouette scores how compact the partition it FOUND is, not whether that structure is
    real. K-means will happily carve 2D Gaussian noise into tidy blobs, so a noise-only
    feature set outscores one containing the actual signal. Any rule of the form "cluster on
    whichever set scores higher" therefore selects noise.
    """
    from sklearn.preprocessing import StandardScaler
    from triadic_dgm.persona.pipeline import choose_k

    df = _separable()
    def sil(cols):
        X = StandardScaler().fit_transform(df[cols].to_numpy(dtype=float))
        return choose_k(X)[1]

    assert sil(["noise_1", "noise_2"]) > sil(["spend", "visits", "noise_1", "noise_2"])


def test_no_caller_list_is_reported_as_auto():
    assert _selection(run_persona_pipeline(_separable())) == "auto"


def test_the_decision_is_deterministic():
    a = run_persona_pipeline(_separable(), behavioral_features=["noise_1", "noise_2"])
    b = run_persona_pipeline(_separable(), behavioral_features=["noise_1", "noise_2"])
    assert _selection(a) == _selection(b)
    assert [p["persona_name"] for p in a] == [p["persona_name"] for p in b]


def test_subsetting_still_works_through_the_dataframe():
    """The supported way to restrict features — and it stays honoured."""
    df = _separable()[["spend", "visits"]]
    personas = run_persona_pipeline(df)
    assert set(personas[0]["features_used"]) == {"spend", "visits"}


def test_the_telco_path_always_keeps_the_caller_list():
    """Dual-path guarantee: domain meaning outranks silhouette on telco data."""
    rng = np.random.default_rng(5)
    n = 300
    df = pd.DataFrame({
        "cl_total_6m": np.concatenate([rng.normal(12, 2, n // 2), rng.normal(1, 0.4, n // 2)]),
        "complaint_total_6m": np.concatenate([rng.normal(6, 1, n // 2), rng.normal(0.2, 0.1, n // 2)]),
        "fee_total": rng.normal(500, 50, n),
        "old_usage": rng.normal(100, 10, n),
        "recent_usage": rng.normal(80, 10, n),
    })
    personas = run_persona_pipeline(df, behavioral_features=["fee_total", "old_usage"])
    assert _selection(personas) == "caller"


def test_an_unknown_column_still_fails_before_any_comparison():
    """The schema gate runs first: a wrong list is a defect to report, not to silently
    out-measure. Auto-selecting past it is exactly how the Iris-on-retail run stayed
    invisible."""
    personas = run_persona_pipeline(_separable(), behavioral_features=["Sepal.Length", "spend"])
    assert personas[0]["persona_name"] == "Không phân hoá được nhóm"
    assert "Sepal.Length" in (personas[0].get("failure_reason") or "")
