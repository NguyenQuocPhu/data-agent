"""Lock in that the RENDERED markdown report contains no telco vocabulary for a generic dataset.

The persona *fields* being neutralised (test_characterization.py) is not enough on its own:
report_generator composes prose from keyword-driven helpers that, on a non-telco dataset, match
nothing and then silently fall into their "low/stable/quiet" branches — printing telco claims as
FACT (observed live on a marketing dataset: "ARPU/cước phí ở mức trung bình hoặc thấp",
"Ít khi liên hệ CSKH hoặc khiếu nại"). These tests render the real markdown and assert on it.
"""
import json

import pytest

from triadic_dgm.persona.characterization import enforce_generic_persona
from triadic_dgm.services.report_generator import ReportGenerator

# Vocabulary that must never appear in a report for a dataset with no such concept.
_TELCO_TERMS = [
    "arpu", "churn", "cskh", "rời mạng", "khiếu nại", "sự cố kỹ thuật",
    "cước phí", "thuê bao", "rmdt",
]


def _generic_personas():
    personas = []
    specs = [
        ("A", 800, {"MntWines": 600.0, "NumWebPurchases": 8.0, "Income": 78000.0}, 1.5),
        ("B", 1200, {"MntWines": 120.0, "NumWebPurchases": 3.0, "Income": 41000.0}, -0.6),
    ]
    for i, (label, sup, feats, dev) in enumerate(specs):
        personas.append({
            "cluster_id": i,
            "persona_name": f"Cụm {label}",
            "support": sup,
            "support_pct": sup / 2000,
            "arpu": 0,
            "churn_rate": 0,
            "confidence": "HIGH",
            "persona_type": "SEGMENT",
            # Values the LLM-side rule engine would have produced on non-telco data
            # (telco keywords match nothing -> everything collapses to LOW).
            "severity": "LOW",
            "risk": "LOW",
            "risk_tier": "Nhóm bị động – theo dõi & cảnh báo",
            "priority_score": 40 - i,
            "feature_means": feats,
            "evidence": feats,
            "profile_attributes": {},
            "recommended_actions": [
                "Phân tích sâu các đặc điểm nổi bật của nhóm để hiểu hành vi đặc trưng",
                "Xây dựng chiến lược tiếp cận phù hợp với đặc trưng của nhóm",
            ],
            "domain_signature": {},
            "segmentation_quality": "NORMAL",
            "distinguishing_signal": {
                "dominant_domain": "usage",
                "stars": {"usage": {"stars": 4, "max_dev": abs(dev)}},
                "top_features": [
                    {"feature": list(feats)[0], "label": list(feats)[0], "deviation": dev}
                ],
                "evidence": "Chi tiêu khác biệt so với trung bình",
            },
        })
    enforce_generic_persona(personas, profile=None)
    return personas


def _render(personas):
    raw = "[JSON_START_PERSONA]" + json.dumps(personas, ensure_ascii=False) + "[JSON_END_PERSONA]"
    rg = ReportGenerator(api_key="x", base_url="http://localhost:1", model_name="m")
    # Deterministic path only — the LLM narrative is not what we're testing.
    rg.generate_llm_narrative = lambda *a, **k: rg._fallback_narrative()
    md = rg.render_markdown(raw)
    # The appendix echoes the input JSON verbatim; only the composed report is under test.
    return md.split("### Raw Facts")[0]


def test_enforce_generic_persona_sets_explicit_mode_marker():
    personas = _generic_personas()
    assert all(p["dataset_mode"] == "GENERIC" for p in personas)


@pytest.mark.parametrize("term", _TELCO_TERMS)
def test_generic_report_contains_no_telco_vocabulary(term):
    body = _render(_generic_personas()).lower()
    assert term not in body, f"telco term '{term}' leaked into a generic report"


def test_generic_report_omits_nulled_severity_and_risk():
    body = _render(_generic_personas())
    assert "Severity" not in body
    assert "Risk Tier Grouping" not in body
    # A nulled field must be omitted, never printed as a literal None/N/A.
    assert "None" not in body


def test_generic_report_roadmap_has_no_tbd_owner():
    body = _render(_generic_personas())
    assert "Business Roadmap" in body
    assert "TBD" not in body, "generic actions are missing ROADMAP_METADATA entries"


def test_generic_report_still_describes_the_persona():
    body = _render(_generic_personas())
    # The profile section must be replaced by real signal, not simply deleted.
    assert "MntWines" in body
    assert "trung bình toàn tập" in body


# --- LLM narrative path -------------------------------------------------------------------

def _contaminated_narrative():
    """What a model can still emit despite the generic prompt: telco vocabulary it was never
    given data for, mixed in with legitimate sentences."""
    from triadic_dgm.schemas.report_schema import (
        ExecutiveSummaryNarrative, PersonaNarrative, ReportNarrative,
    )
    return ReportNarrative(
        executive_summary=ExecutiveSummaryNarrative(
            executive_overview=(
                "Tập dữ liệu phân hoá thành hai nhóm rõ rệt. "
                "Nhóm lớn có nguy cơ rời mạng cao và cần giữ chân ngay."
            )
        ),
        personas_analysis=[
            PersonaNarrative(
                cluster_id=0,
                business_interpretation=(
                    "Nhóm này nổi bật ở mức chi tiêu cao hơn mặt bằng chung. "
                    "ARPU của nhóm cũng cao hơn trung bình."
                ),
                operational_impact="Cần triển khai chương trình bán chéo để tăng doanh thu.",
            )
        ],
        conclusion="Phân khúc cho thấy sự khác biệt đo được giữa các nhóm.",
    )


def test_generic_narrative_sanitiser_drops_telco_sentences():
    from triadic_dgm.services.report_generator import _sanitize_generic_narrative

    n = _contaminated_narrative()
    _sanitize_generic_narrative(n)

    # Legitimate, data-grounded sentences survive.
    assert "phân hoá thành hai nhóm" in n.executive_summary.executive_overview
    assert "chi tiêu cao hơn mặt bằng chung" in n.personas_analysis[0].business_interpretation
    assert n.conclusion  # untouched, contained nothing forbidden

    # Every telco assertion is gone.
    joined = " ".join([
        n.executive_summary.executive_overview,
        n.personas_analysis[0].business_interpretation,
        n.personas_analysis[0].operational_impact,
        n.conclusion,
    ]).lower()
    for term in ("rời mạng", "giữ chân", "arpu", "bán chéo"):
        assert term not in joined, f"'{term}' survived sanitisation"


def test_generic_dataset_uses_the_telco_free_prompt():
    personas = _generic_personas()
    rg = ReportGenerator(api_key="x", base_url="http://localhost:1", model_name="m")
    prompt = rg._build_prompt(personas, {})
    # The telco prompt's signature few-shot blocks must not be present.
    assert "churn_story_facts" not in prompt
    assert "Net Pay" not in prompt
    assert "BỐI CẢNH QUAN TRỌNG" in prompt


def test_telco_dataset_still_uses_the_original_prompt():
    personas = _generic_personas()
    for p in personas:  # simulate a telco run: no GENERIC marker
        p.pop("dataset_mode", None)
        p["churn_driver"] = "Silent Premium Churn"
        p["churn_driver_confidence"] = "MEDIUM"
    rg = ReportGenerator(api_key="x", base_url="http://localhost:1", model_name="m")
    prompt = rg._build_prompt(personas, {})
    assert "BỐI CẢNH QUAN TRỌNG" not in prompt
    assert "Consultant tại Deloitte" in prompt
