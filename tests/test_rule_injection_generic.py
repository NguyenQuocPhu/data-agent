"""A learned rule must never describe a dataset the user did not upload.

The RIMRULE archive stores heuristics extracted from past debugging sessions. Every one of
those sessions ran against one telecom dataset, so 83 of the archive's 284 rules name that
dataset's columns (`RMDT`, `cuoc_hang_thang`), its metrics (ARPU), or the company itself
(FTEL). `api/routers/chat.py` injects the top 5 by MDL score verbatim into the prompt
whenever the user's question mentions clustering — in the authoritative voice of "mistakes
made in the past, do not repeat them".

Observed live: with a 17-column retail dataset uploaded, two of the five injected rules
asserted the data had `RMDT` and an ARPU concept. The model believed them and emitted
`behavioral_features = ['cl_total_6m', 'cl_avg_6m', ...]`, then died on
`ValueError: No valid behavioral features found`. It was not hallucinating — it was
repeating what it had been told about the data.

The gate belongs here rather than in the prompt: prompt wording is best-effort steering an
improvising model may ignore, whereas a rule that is never injected cannot be believed.
"""
import pytest

from triadic_dgm.memory.rimrule_memory import Rule, RimruleMemoryBank

# Columns of a real non-telecom upload (Olist retail), trimmed.
RETAIL_COLUMNS = [
    "customer_id", "order_count", "total_payment", "avg_review_score",
    "days_since_last_order", "distinct_categories", "avg_freight_value",
]
# Columns of the telecom dataset the archive's rules were actually learned on.
TELCO_COLUMNS = ["OBJID_mask", "RMDT", "cuoc_hang_thang", "cl_total_6m", "complaint_total_6m"]


def _bank(*nl_rules: str) -> RimruleMemoryBank:
    """A memory bank holding exactly the given rules, with no archive on disk."""
    bank = RimruleMemoryBank(archive_path="/nonexistent/never-written.json")
    bank.rules = [
        Rule(nl_rule=t, domain="python", qualifier=["semantic_error"],
             action=["fix"], strength="strong", tool_category="analysis")
        for t in nl_rules
    ]
    return bank


# Verbatim from dgm_agent_v2/rimrule_archive.json — these are the real offenders.
RULE_RMDT = ("Semantic check failed: ⚠ Data Leakage: Biến mục tiêu `RMDT` đang được dùng làm "
             "feature cho thuật toán phân cụm. BẮT BUỘC phải drop `RMDT` khỏi tập dữ liệu "
             "huấn luyện KMeans!")
RULE_FTEL = ("Semantic check failed: ⚠ Ảo Giác Nhân Quả: Tập dữ liệu FTEL này CHỈ có các biến "
             "hành vi kỹ thuật. Bạn phải giải thích dựa trên dữ liệu thật!")
RULE_ARPU = ("Semantic check failed: ⚠ Gate 8: Dataset không có biến doanh thu (ARPU=0). "
             "Bắt buộc ép chạy 100% ở ROOT CAUSE MODE.")
RULE_CUOC = ("`cuoc_hang_thang` đã bị drop ở Step 1 nhưng Step 8 vẫn tính ARPU từ cột này.")

# Genuinely dataset-agnostic rules — these carry the real value and must always survive.
RULE_JSON = ("Semantic check failed: ⚠ Không tìm thấy JSON Output hợp lệ cho Persona. BẮT BUỘC "
             "phải dùng print('[JSON_START_PERSONA]'), print(json.dumps(personas)), "
             "print('[JSON_END_PERSONA]').")
RULE_DUP = ("Semantic check failed: ⚠ Gate 10: Bị trùng tên Persona giữa các cụm. BẮT BUỘC phải "
            "phân cấp để đảm bảo KHÔNG CÓ TÊN NÀO TRÙNG NHAU.")
RULE_KEYERR = "Tránh KeyError: kiểm tra cột tồn tại bằng `if col in data.columns` trước khi truy cập."


def test_a_retail_upload_gets_no_telco_identifier():
    """The whole point: nothing in the injected block may name a column this data lacks."""
    bank = _bank(RULE_RMDT, RULE_FTEL, RULE_ARPU, RULE_CUOC, RULE_JSON)
    out = bank.retrieve_rules_symbolic("python", top_k=5, active_columns=RETAIL_COLUMNS).lower()

    for identifier in ("rmdt", "ftel", "arpu", "cuoc_hang_thang"):
        assert identifier not in out, f"'{identifier}' leaked into a retail analysis"


def test_the_dataset_agnostic_rules_still_get_through():
    """Filtering must not throw away the rules that are actually useful everywhere."""
    bank = _bank(RULE_RMDT, RULE_JSON, RULE_DUP, RULE_KEYERR)
    out = bank.retrieve_rules_symbolic("python", top_k=5, active_columns=RETAIL_COLUMNS)

    assert "[JSON_START_PERSONA]" in out
    assert "TRÙNG NHAU" in out
    assert "KeyError" in out


def test_the_telco_path_is_untouched():
    """Dual-path guarantee: on the telecom dataset those rules are correct, so they stay."""
    bank = _bank(RULE_RMDT, RULE_CUOC, RULE_JSON)
    out = bank.retrieve_rules_symbolic("python", top_k=5, active_columns=TELCO_COLUMNS)

    assert "RMDT" in out
    assert "cuoc_hang_thang" in out


def test_filtering_happens_before_the_top_k_cut():
    """Contaminated rules must not consume the k slots.

    Ranking is by MDL score, and the short telco rules score high — so slicing first would
    hand a retail user two dead rules and drop two useful ones that were ranked below them.
    """
    bank = _bank(RULE_RMDT, RULE_FTEL, RULE_JSON, RULE_DUP, RULE_KEYERR)
    out = bank.retrieve_rules_symbolic("python", top_k=3, active_columns=RETAIL_COLUMNS)

    assert out.count("- Rule ") == 3, "clean rules were displaced by filtered-out ones"


def test_unknown_columns_leave_behaviour_unchanged():
    """`active_columns=None` is the existing contract used by the evolution loop.

    verifier.py and solver_agent.py call this while debugging the telecom dataset itself;
    silently filtering there would remove the very rules they need.
    """
    bank = _bank(RULE_RMDT, RULE_JSON)
    out = bank.retrieve_rules_symbolic("python", top_k=5)

    assert "RMDT" in out


def test_an_empty_column_list_is_treated_as_not_telco():
    """A workspace with no readable dataset must not be given telco assertions either.

    `_active_dataset_columns()` returns None when nothing is uploaded; chat.py turns that
    into `[]`. Empty must mean "no telco columns present", not "unknown, allow anything" —
    otherwise the leak returns whenever the column peek fails.
    """
    bank = _bank(RULE_RMDT, RULE_JSON)
    out = bank.retrieve_rules_symbolic("python", top_k=5, active_columns=[])

    assert "RMDT" not in out
    assert "[JSON_START_PERSONA]" in out


def test_no_rules_at_all_returns_empty_not_an_error():
    bank = _bank()
    assert bank.retrieve_rules_symbolic("python", top_k=5, active_columns=RETAIL_COLUMNS) == ""


def test_every_rule_filtered_out_still_returns_a_usable_block():
    """All-contaminated archive on a retail upload: the caller must get something valid.

    chat.py substitutes "No past mistakes recorded yet." on a falsy result, so returning an
    empty string here is correct — what must never happen is a header with zero rules under
    it, which reads to the model as an empty promise.
    """
    bank = _bank(RULE_RMDT, RULE_FTEL, RULE_ARPU)
    out = bank.retrieve_rules_symbolic("python", top_k=5, active_columns=RETAIL_COLUMNS)

    assert out == "" or "- Rule " in out
