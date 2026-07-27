"""A failed report must say what actually went wrong.

The validator asserted `total_customers > 0` with the message "Total support must be greater
than 0". When that fired in production it was reported to the user as
`[LLM ERROR: Total support must be greater than 0]`, which reads as "the dataset is empty" —
it is not. The dataset had 50,000 rows and clustering had already succeeded.

What had actually happened is that the persona objects reaching the report carried no
`support` field at all, because the sandbox emitted hand-written JSON instead of the output
of `run_persona_pipeline`. Diagnosing that from the message took six rounds of log
archaeology. The message is the fix: it must name the missing field and show which keys the
objects do have, so the next occurrence is readable at a glance.
"""
import pytest

from triadic_dgm.services.report_generator import ReportValidator


def _persona(**overrides):
    p = {"persona_name": "Nhóm A", "support": 100, "support_pct": 0.25,
         "recommended_actions": [], "feature_means": {}}
    p.update(overrides)
    return p


def test_a_healthy_persona_list_passes():
    ReportValidator.validate([_persona(), _persona(support=300)])


def test_an_empty_list_is_not_an_error():
    """No personas is handled upstream by render_markdown's own message; validate must not
    turn it into an exception here."""
    ReportValidator.validate([])


def test_personas_without_support_name_the_missing_field():
    personas = [
        {"persona_name": "Nhóm A", "support_pct": 0.6, "feature_means": {}},
        {"persona_name": "Nhóm B", "support_pct": 0.4, "feature_means": {}},
    ]
    with pytest.raises(ValueError) as excinfo:
        ReportValidator.validate(personas)

    message = str(excinfo.value)
    assert "support" in message
    assert "2" in message, "the message should say how many personas were seen"
    # The keys actually present are what identifies the producer of the bad JSON.
    assert "support_pct" in message


def test_the_old_misleading_wording_is_gone():
    """"Total support must be greater than 0" reads as an empty dataset and cost hours."""
    with pytest.raises(ValueError) as excinfo:
        ReportValidator.validate([{"persona_name": "A", "feature_means": {}}])
    assert "Total support must be greater than 0" not in str(excinfo.value)


def test_zero_support_on_every_persona_is_reported_the_same_way():
    """Present-but-zero is the same defect as absent: no population to report on."""
    with pytest.raises(ValueError) as excinfo:
        ReportValidator.validate([_persona(support=0), _persona(support=0)])
    assert "support" in str(excinfo.value)


def test_one_populated_persona_is_enough_to_proceed():
    """A legitimately empty cluster alongside a populated one must not block the report."""
    ReportValidator.validate([_persona(support=0), _persona(support=50)])
