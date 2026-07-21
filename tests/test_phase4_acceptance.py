"""Phase 4 acceptance: the deterministic Python path renders a non-telco dataset generically.

NOTE: data_demo_golden.csv is itself telco-shaped (paired old_*/recent_* columns), so it is
NOT a valid non-telco fixture — has_churn_columns correctly returns True for it. This test
therefore builds an in-memory, genuinely non-telco DataFrame and exercises the full
deterministic Phase 1->4 chain (build_profile -> has_churn_columns -> enrich_personas) on it,
with NO LLM call. A second test locks in that the demo CSV routes to the telco path.
"""
import os

import numpy as np
import pandas as pd
import pytest

from triadic_dgm.persona.dataset_profile import build_profile, has_churn_columns
from triadic_dgm.services import convergence_runner

_CSV = os.path.join(os.path.dirname(__file__), "..", "data_demo_golden.csv")


class _FakeReportGen:
    def _get_means(self, p):
        return p.get("feature_means", {})

    def generate_llm_narrative(self, *a, **k):
        raise RuntimeError("no LLM in acceptance test")

    def _build_persona_story(self, *a, **k):
        return None


def _non_telco_frame():
    rng = np.random.default_rng(42)
    n = 300
    return pd.DataFrame(
        {
            "sepal_length": rng.normal(6.0, 0.8, n),
            "sepal_width": rng.normal(3.0, 0.4, n),
            "petal_length": rng.normal(4.0, 1.5, n),
            "petal_width": rng.normal(1.2, 0.7, n),
        }
    )


def test_non_telco_dataset_is_generic_and_produces_clean_personas():
    df = _non_telco_frame()
    profile = build_profile(df)

    # A genuinely non-telco dataset must be recognised as NON-churn.
    assert has_churn_columns(profile.labels.keys()) is False

    feats = profile.behavioral_features[:4] or list(df.columns)[:4]
    gmean = {f: float(df[f].mean()) for f in feats}
    hi = {f: gmean[f] * 1.8 for f in gmean}
    lo = {f: gmean[f] * 0.4 for f in gmean}
    personas = [
        {"cluster_id": 0, "support": 200, "support_pct": 0.66, "feature_means": hi},
        {"cluster_id": 1, "support": 100, "support_pct": 0.34, "feature_means": lo},
    ]

    convergence_runner.enrich_personas(personas, _FakeReportGen(), profile=profile)

    for p in personas:
        assert p.get("churn_driver") is None
        assert p.get("temporal_trajectory") == []
        assert p.get("distinguishing_signal") is not None
        name = str(p.get("persona_name", ""))
        assert name and "rời mạng" not in name.lower() and "churn" not in name.lower()


@pytest.mark.skipif(not os.path.exists(_CSV), reason="data_demo_golden.csv fixture not present")
def test_demo_golden_csv_routes_to_telco_path():
    # Regression guard for the Task 7 finding: the demo CSV is telco-shaped
    # (paired old_*/recent_* columns), so it must be detected as a churn dataset.
    df = pd.read_csv(_CSV)
    profile = build_profile(df)
    assert has_churn_columns(profile.labels.keys()) is True
