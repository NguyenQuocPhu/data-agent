"""Integration: enrich_personas routes non-churn datasets to the generic path."""
from triadic_dgm.services import convergence_runner
from triadic_dgm.persona.dataset_profile import DatasetProfile


class _FakeReportGen:
    """Minimal ReportGenerator stand-in: only what enrich_personas touches."""

    def _get_means(self, p):
        return p.get("feature_means", {})

    def generate_llm_narrative(self, *a, **k):
        raise RuntimeError("no LLM in test")  # force deterministic fallback

    def _build_persona_story(self, *a, **k):
        return None


def _generic_profile():
    return DatasetProfile(
        dataset_name="demo",
        fingerprint="deadbeef",
        labels={"sepal_length": "Sepal length", "petal_width": "Petal width"},
        behavioral_features=["sepal_length", "petal_width"],
        domains={"sepal": ["sepal_length"], "petal": ["petal_width"]},
    )


def test_enrich_personas_generic_dataset_neutralises_churn():
    personas = [
        {"cluster_id": 0, "support": 100, "support_pct": 0.6,
         "feature_means": {"sepal_length": 6.5, "petal_width": 2.0}},
        {"cluster_id": 1, "support": 60, "support_pct": 0.4,
         "feature_means": {"sepal_length": 4.8, "petal_width": 0.2}},
    ]
    convergence_runner.enrich_personas(personas, _FakeReportGen(), profile=_generic_profile())
    for p in personas:
        assert p.get("churn_driver") is None
        assert p.get("persona_name")  # a generic name was set
        assert "rời mạng" not in str(p.get("persona_name", "")).lower()
        assert "distinguishing_signal" in p
