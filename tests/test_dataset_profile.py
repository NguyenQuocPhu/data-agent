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
