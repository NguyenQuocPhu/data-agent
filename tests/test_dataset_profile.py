"""Unit tests for the dataset-agnostic DatasetProfile builder."""
from __future__ import annotations

import pandas as pd
import pytest

from triadic_dgm.persona.dataset_profile import (
    DatasetProfile,
    build_profile,
    compute_fingerprint,
    infer_domains,
    load_or_build_cached,
    select_behavioral_features,
)


def _telco_like_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_id": [1, 2, 3, 4],
            "call_total_6m": [0, 5, 10, 2],
            "call_avg_6m": [0.0, 0.8, 1.6, 0.3],
            "complaint_total_6m": [0, 1, 0, 3],
            "constant_col": [7, 7, 7, 7],
            "region": ["N", "S", "N", "S"],  # non-numeric
        }
    )


def _retail_like_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": [10, 11, 12, 13],
            "visits_total": [3, 8, 1, 12],
            "visits_avg": [0.5, 1.3, 0.2, 2.0],
            "revenue_sum": [100.0, 250.0, 30.0, 900.0],
        }
    )


def test_fingerprint_is_stable_and_order_independent():
    a = compute_fingerprint(["b", "a", "c"], 100)
    b = compute_fingerprint(["c", "b", "a"], 100)
    assert a == b
    assert a != compute_fingerprint(["a", "b", "c"], 101)


def test_select_features_drops_id_constant_and_nonnumeric():
    feats = select_behavioral_features(_telco_like_df())
    assert "customer_id" not in feats  # id-like
    assert "constant_col" not in feats  # constant
    assert "region" not in feats  # non-numeric
    assert "call_total_6m" in feats and "complaint_total_6m" in feats
    assert feats == sorted(feats)  # stable order


def test_infer_domains_groups_by_root_generically():
    domains = infer_domains(["call_total_6m", "call_avg_6m", "complaint_total_6m"])
    assert domains["call"] == ["call_total_6m", "call_avg_6m"]
    assert domains["complaint"] == ["complaint_total_6m"]


def test_build_profile_on_non_telco_dataset_has_no_telco_assumptions():
    profile = build_profile(_retail_like_df(), dataset_name="retail")
    assert isinstance(profile, DatasetProfile)
    assert "user_id" not in profile.behavioral_features
    assert set(profile.behavioral_features) == {"visits_total", "visits_avg", "revenue_sum"}
    assert "visits" in profile.domains and "revenue" in profile.domains
    assert profile.label("visits_total") == "visits_total"  # falls back to raw name


def test_cache_freezes_features_across_calls(tmp_path):
    df = _telco_like_df()
    cache_dir = str(tmp_path / "profiles")
    p1 = load_or_build_cached(df, cache_dir, dataset_name="telco")
    # Even if selection logic were to change, a second call with the same fingerprint
    # must return the frozen feature set from cache.
    p2 = load_or_build_cached(df, cache_dir, dataset_name="telco")
    assert p1.fingerprint == p2.fingerprint
    assert p1.behavioral_features == p2.behavioral_features
    import os
    assert os.path.exists(os.path.join(cache_dir, f"{p1.fingerprint}.json"))


def test_cache_is_actually_read_from_disk(tmp_path):
    """Prove load_or_build_cached reads the frozen file, not just recomputes:
    tamper the cached feature list on disk and confirm the tampered value is returned."""
    import json
    import os

    df = _telco_like_df()
    cache_dir = str(tmp_path / "profiles")
    p1 = load_or_build_cached(df, cache_dir, dataset_name="telco")
    cache_file = os.path.join(cache_dir, f"{p1.fingerprint}.json")
    data = json.load(open(cache_file, encoding="utf-8"))
    data["behavioral_features"] = ["TAMPERED"]
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    p2 = load_or_build_cached(df, cache_dir, dataset_name="telco")
    assert p2.behavioral_features == ["TAMPERED"]


def test_corrupt_cache_is_rebuilt(tmp_path):
    """A cache file containing invalid JSON must be caught and rebuilt, not raised."""
    import json
    import os

    df = _telco_like_df()
    cache_dir = str(tmp_path / "profiles")
    os.makedirs(cache_dir, exist_ok=True)
    fp = load_or_build_cached(df, cache_dir, dataset_name="telco").fingerprint
    cache_file = os.path.join(cache_dir, f"{fp}.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write("{ this is not valid json ")
    rebuilt = load_or_build_cached(df, cache_dir, dataset_name="telco")
    assert rebuilt.behavioral_features  # rebuilt, non-empty
    json.load(open(cache_file, encoding="utf-8"))  # file is valid JSON again


def test_build_task_prompt_embeds_given_features():
    from triadic_dgm.services.convergence_runner import build_task_prompt

    prompt = build_task_prompt(["visits_total", "revenue_sum"])
    assert "visits_total" in prompt and "revenue_sum" in prompt
    # generic call must NOT force the telco fixed list
    assert "cl_total_6m" not in prompt
    # keeps the business-task trigger words the verifier relies on
    assert "phân cụm" in prompt and "persona" in prompt


def test_has_churn_columns_true_on_churn_target():
    from triadic_dgm.persona.dataset_profile import has_churn_columns

    assert has_churn_columns(["age", "arpu", "RMDT"]) is True


def test_has_churn_columns_true_on_temporal_pairs():
    from triadic_dgm.persona.dataset_profile import has_churn_columns

    assert has_churn_columns(["old_complaint", "recent_complaint", "usage"]) is True


def test_has_churn_columns_false_on_neutral_dataset():
    from triadic_dgm.persona.dataset_profile import has_churn_columns

    assert has_churn_columns(["sepal_length", "sepal_width", "petal_length"]) is False


def test_has_churn_columns_false_on_recent_only():
    from triadic_dgm.persona.dataset_profile import has_churn_columns

    # A lone recent_* without a matching old_* is not a churn trajectory signal.
    assert has_churn_columns(["recent_visits", "spend"]) is False
