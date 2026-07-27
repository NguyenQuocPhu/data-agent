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
    # Wording whose telco-ness is not in the sentence itself but in what it presumes:
    # a ROADMAP_METADATA KPI ("High-Value Churn Rate"), a subscriber-base noun, or the
    # unit "KH" on rows that may not be customers at all.
    "exit survey", "win-back", "tổng đàn", " kh ", "cước",
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
            # The sandbox pipeline computes these by keyword-matching telco column
            # names, so a non-telco dataset yields absent/accidental values that the
            # report still phrases in telco prose. An empty dict here would make this
            # whole file pass while the live report leaked (which is what happened:
            # "Nhóm này có mức cước trung bình khoảng 0 nghìn đồng/tháng").
            "profile_attributes": {"avg_fee": 0.0, "tier_downgrade_rate": 0.0},
            # generate_actions() branches on the LLM's OWN dataset_mode guess, which is
            # independent of the Python-side has_churn_columns() decision. These are what
            # it emits when the two disagree — the realistic worst case, not the happy path.
            "recommended_actions": [
                "Phân tích đối thủ cạnh tranh và chính sách giá",
                "Khảo sát nguyên nhân rời mạng (Exit Survey) cho nhóm giá trị cao",
                "Chạy chiến dịch Win-back Campaign nếu khách hàng tiềm năng",
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


def test_generic_report_drops_telco_playbook_actions():
    """The roadmap must not carry over the telco playbook — including entries whose own
    wording is neutral but whose ROADMAP_METADATA attaches a telco KPI."""
    body = _render(_generic_personas())
    assert "chính sách giá" not in body
    assert "High-Value Churn Rate" not in body
    # ...and it must still say something, not just go blank.
    assert "Phân tích sâu các đặc điểm nổi bật" in body


def test_generic_report_counts_records_not_customers():
    body = _render(_generic_personas())
    assert "bản ghi" in body
    assert "CHÂN DUNG KHÁCH HÀNG" not in body
    assert "Customer Profile" not in body


def test_enforce_generic_persona_drops_telco_profile_attributes():
    personas = _generic_personas()
    assert all(p["profile_attributes"] == {} for p in personas)


def test_generic_priority_score_ranks_by_distinctiveness_not_size():
    """apply_business_rules' telco thresholds all read zero here, collapsing every persona
    onto one constant base so ranking degenerated to cluster size. A more distinctive but
    smaller persona must be able to outrank a bland larger one."""
    personas = _generic_personas()
    big_bland, small_sharp = personas[1], personas[0]
    big_bland["support_pct"], small_sharp["support_pct"] = 0.9, 0.1
    big_bland["distinguishing_signal"]["stars"]["usage"]["stars"] = 1
    small_sharp["distinguishing_signal"]["stars"]["usage"]["stars"] = 5
    enforce_generic_persona(personas, profile=None)
    assert small_sharp["priority_score"] > big_bland["priority_score"]


def test_generic_priority_score_survives_a_missing_signal():
    p = {"support_pct": 0.5}
    enforce_generic_persona([p], profile=None)
    assert isinstance(p["priority_score"], int)


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


# --- the chat path reaches render_markdown without a profile argument ----------------

def _raw_sandbox_personas():
    """Personas exactly as the sandbox emits them: telco names, severity/risk, telco
    profile_attributes and actions — no dataset_mode marker."""
    specs = [
        ("Khách hàng ổn định (Mức 1)", 800, {"MntWines": 600.0, "Income": 78000.0}),
        ("Khách hàng ổn định (Mức 2)", 1200, {"MntWines": 120.0, "Income": 41000.0}),
    ]
    return [
        {
            "cluster_id": i, "persona_name": n, "support": s, "support_pct": s / 2000,
            "confidence": "HIGH", "persona_type": "SEGMENT", "severity": "LOW", "risk": "LOW",
            "risk_tier": "Nhóm bị động – theo dõi & cảnh báo", "priority_score": 20,
            "profile_attributes": {"avg_fee": 0.0},
            "recommended_actions": ["Khảo sát nguyên nhân rời mạng (Exit Survey) cho nhóm giá trị cao"],
            "domain_signature": {}, "segmentation_quality": "NORMAL",
            "feature_means": m, "evidence": m,
        }
        for i, (n, s, m) in enumerate(specs)
    ]


class _FakeProfile:
    dataset_name = "d"
    fingerprint = "f"
    labels = {"MntWines": "Chi tiêu rượu vang", "Income": "Thu nhập"}
    behavioral_features = ["MntWines", "Income"]
    domains = {"mntwines": ["MntWines"], "income": ["Income"]}
    derived_features: dict = {}


def _render_via_resolver(personas, profile):
    """Render the way engine.stream_workflow does — no profile argument at all."""
    from triadic_dgm.services import report_generator as rg_mod

    raw = "[JSON_START_PERSONA]" + json.dumps(personas, ensure_ascii=False) + "[JSON_END_PERSONA]"
    rg = ReportGenerator(api_key="x", base_url="http://localhost:1", model_name="m")
    rg.generate_llm_narrative = lambda *a, **k: rg._fallback_narrative()
    rg_mod.set_profile_resolver(lambda: profile)
    try:
        return rg.generate_markdown_report(raw).split("### Raw Facts")[0]
    finally:
        rg_mod.set_profile_resolver(None)


@pytest.mark.parametrize("term", ["arpu", "cước", "cskh", "rời mạng", "exit survey", "tổng đàn"])
def test_chat_path_applies_the_generic_path_via_the_resolver(term):
    """engine.stream_workflow calls generate_markdown_report(raw) with no profile, so the
    registered resolver is the only thing that can trigger the generic path there."""
    body = _render_via_resolver(_raw_sandbox_personas(), _FakeProfile())
    assert term not in body.lower()


def test_chat_path_renames_personas_from_inferred_labels():
    body = _render_via_resolver(_raw_sandbox_personas(), _FakeProfile())
    assert "Khách hàng ổn định (Mức" not in body
    assert "Chi tiêu rượu vang" in body or "Thu nhập" in body


def test_no_resolver_keeps_the_previous_behaviour():
    """A deployment that never registers one must still render, unchanged."""
    from triadic_dgm.services import report_generator as rg_mod

    rg_mod.set_profile_resolver(None)
    body = _render_via_resolver(_raw_sandbox_personas(), None)
    assert "Khách hàng ổn định (Mức 1)" in body


def test_failing_resolver_degrades_instead_of_breaking_the_report():
    from triadic_dgm.services import report_generator as rg_mod

    def _boom():
        raise RuntimeError("profile store down")

    raw = "[JSON_START_PERSONA]" + json.dumps(_raw_sandbox_personas(), ensure_ascii=False) + "[JSON_END_PERSONA]"
    rg = ReportGenerator(api_key="x", base_url="http://localhost:1", model_name="m")
    rg.generate_llm_narrative = lambda *a, **k: rg._fallback_narrative()
    rg_mod.set_profile_resolver(_boom)
    try:
        body = rg.generate_markdown_report(raw)
    finally:
        rg_mod.set_profile_resolver(None)
    assert "Business Roadmap" in body  # rendered anyway
