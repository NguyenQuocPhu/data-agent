import re
from triadic_dgm.prompts import prompts


def _v2_body() -> str:
    src = open(prompts.__file__, encoding="utf-8").read()
    m = re.search(r"PROGRAMMER_PROMPT_V2 = '''(.*?)'''", src, re.S)
    assert m, "PROGRAMMER_PROMPT_V2 triple-single-quoted block not found"
    return m.group(1)


def test_programmer_prompt_braces_balanced_and_doubled():
    """Every brace in the raw prompt must be doubled.

    This also required >= 50 doubled pairs, because the prompt embedded ~800 lines of
    Python whose dict literals supplied them. That code now lives in
    triadic_dgm/persona/pipeline.py and only a placeholder remains, so the threshold is
    gone. Its replacement is stricter, not weaker: no unpaired brace may survive anywhere,
    which is the corruption the count was only a proxy for.
    """
    body = _v2_body()
    assert body.count("{{") == body.count("}}")
    # LAMBDA.py formats this prompt (PROGRAMMER_PROMPT.format(working_path=...)), so a
    # SINGLE brace is a real format field: any stray one raises KeyError at request time.
    # Only the placeholders that are actually substituted may appear undoubled.
    leftover = body.replace("{{", "").replace("}}", "")
    for placeholder in ("{working_path}",):
        leftover = leftover.replace(placeholder, "")
    assert "{" not in leftover and "}" not in leftover, "unpaired single brace in the raw prompt"


def test_programmer_prompt_documents_generic_default():
    # Soft-steering assertion: the mode block now names GENERIC as the default.
    assert "GENERIC" in _v2_body()


def test_prompt_mandates_the_fixed_pipeline():
    """The prompt must tell the model to CALL the pipeline, not describe how to rebuild it."""
    body = _v2_body()
    assert "run_persona_pipeline" in body
    assert "[JSON_START_PERSONA]" in body


def test_prompt_forbids_splitting_the_analysis_across_turns():
    """The pipeline call must not be deferred to a turn that never comes.

    The prompt said "gõ ĐÚNG đoạn dưới đây và DỪNG" — meaning "do not also retype the long
    functions below" — while the header said to wait for the sandbox result. Read together,
    the model emitted one block that loaded the data, chose features, wrote
    intermediate_features.csv, and stopped, expecting a second turn. There is no second
    turn: report generation runs straight after the execution, so the user got
    `[LLM ERROR: ...]` instead of a report on a run where clustering would have worked.
    """
    body = _v2_body()
    assert "và DỪNG" not in body, "the ambiguous stop instruction is back"
    assert "MỘT KHỐI CODE DUY NHẤT" in body
    assert "KHÔNG CHIA LƯỢT" in body


def test_prompt_no_longer_embeds_the_pipeline_implementation():
    """Regression guard for the whole point of the extraction.

    While these definitions lived in the prompt, the sandbox LLM retyped them on every run
    — non-deterministic, untestable, and drifting further with each repair attempt until
    the retries ran out and the user got no report at all. Re-embedding any of them would
    quietly restore that failure mode.
    """
    body = _v2_body()
    for symbol in (
        "def apply_business_rules",
        "def compute_domain_signature",
        "def compute_profile_attributes",
        "def try_substage_cluster",
        "def classify_churn_driver",
        "def generate_actions",
        "DOMAIN_KEYWORD_GROUPS",
        "stage2_keyword_groups",
    ):
        assert symbol not in body, f"{symbol} is back in the prompt; it belongs in pipeline.py"


def test_prompt_carries_no_telco_column_names():
    """The prompt must not presuppose one dataset's schema.

    Each of these was a hardcoded telco column that silently disabled a stage on any other
    dataset instead of erroring — the defect behind "Clustering Failed" being reported for
    data that split perfectly well.

    The second group was added after this test passed while the prompt still named a
    dataset: the list was the only thing holding the line, and it was incomplete. These are
    the identifiers that were actually observed reaching the model.
    """
    body = _v2_body().lower()
    for column in ("high_spender", "loyalty_rank", "fee_avg", "segment_downgrade_count",
                   "cnt_dao_dong", "vip_type", "complaint_total", "cl_total",
                   "cuoc_hang_thang", "rmdt", "ctbdv", "total_cl_t12"):
        assert column not in body, f"telco column '{column}' is hardcoded in the prompt"


def test_prompt_names_no_customer_and_no_dataset_shape():
    """Naming the client or the column count tells the model what data it is looking at.

    The prompt opened with "FTEL BUSINESS POC — COMPREHENSIVE CLUSTERING (V3: TIME-SERIES
    113 COLUMNS)". A user analysing a 17-column retail export was handed that banner before
    any other instruction, and the model reconciled the mismatch by inventing the missing
    columns from the telecom schema it had been told about.
    """
    body = _v2_body().lower()
    assert "ftel" not in body, "the prompt names the client the POC was built for"
    assert "113 columns" not in body, "the prompt asserts a column count of its own"


def test_prompt_quotes_no_revenue_figure():
    """An anti-hallucination rule must not supply the number it forbids.

    The prompt said "TUYỆT ĐỐI KHÔNG ĐƯỢC tự hardcode ARPU = 609,620" — which is the only
    place that figure appears anywhere in the system. Naming it is what makes it available.
    """
    assert "609,620" not in _v2_body()


def test_churn_appears_only_as_a_pipeline_mode():
    """`PRE_CHURN`/`POST_CHURN` are dataset modes the pipeline selects from real columns, so
    they are legitimate. A bare "churn" is an assumption about data that may have no such
    concept, and it survived every earlier cleanup precisely because the mode names made a
    plain substring check look noisy."""
    body = _v2_body()
    for match in re.finditer(r"[A-Za-z_]*churn[A-Za-z_]*", body, re.I):
        token = match.group(0).upper()
        assert token in ("PRE_CHURN", "POST_CHURN", "CHURN_DRIVER"), (
            f"bare '{match.group(0)}' presupposes a churn concept in the data"
        )
