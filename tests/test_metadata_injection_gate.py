"""A data dictionary must only be shown to the model when it describes the loaded data.

`api/routers/chat.py` globs the repository root for `*metadata*.json` and appends whatever
it finds to the user's message under the heading "tuân thủ chặt chẽ metadata sau đây cho dữ
liệu" — strictly obey this metadata for the data.

One such file sits at the repo root permanently: `data_processed_t4_metadata.json`, the
11.8 KB data dictionary of the telecom dataset, naming `cl_total_6m`, `cl_avg_6m`,
`complaint_total_6m`, `fee_total`, `OBJID`, `LOYALTY_RANK`. It was injected into every chat
regardless of what the user had uploaded.

That is where `behavioral_features = ['cl_total_6m', 'cl_avg_6m', ...]` came from on a
17-column retail upload. The model's own commentary said "based on metadata provided", and
it was telling the truth: it had been handed a dictionary for a different dataset and told
to obey it.

The gate is a match test rather than a vocabulary test on purpose. It is not the telecom
domain that makes a dictionary wrong here — it is describing columns the data does not have.
The same gate protects a third dataset from a second dataset's dictionary.
"""
import json

import pytest

from api.services.metadata_gate import (
    collect_matching_metadata,
    described_columns,
    describes_active_dataset,
)

TELCO_DICT = [
    {"column": "cl_total_6m", "type": "int", "description": "Tổng số Yêu cầu hỗ trợ kĩ thuật"},
    {"column": "cl_avg_6m", "type": "float", "description": "Trung bình CL mỗi tháng"},
    {"column": "complaint_total_6m", "type": "int", "description": "Tổng khiếu nại"},
    {"column": "fee_total", "type": "float", "description": "Tổng cước"},
    {"column": "OBJID_mask", "type": "str", "description": "Định danh thuê bao"},
]
TELCO_COLUMNS = ["cl_total_6m", "cl_avg_6m", "complaint_total_6m", "fee_total", "OBJID_mask"]
RETAIL_COLUMNS = ["customer_id", "order_count", "total_payment", "avg_review_score",
                  "days_since_last_order", "distinct_categories"]


def test_reads_the_column_list_of_a_list_shaped_dictionary():
    """Names are normalised to lowercase so the comparison is case-insensitive."""
    assert described_columns(TELCO_DICT) == {
        "cl_total_6m", "cl_avg_6m", "complaint_total_6m", "fee_total", "objid_mask",
    }


def test_reads_a_dict_shaped_dictionary():
    """`{"columns": [...]}` and `{col: description}` are both in use across this repo."""
    assert described_columns({"columns": ["a", "b"]}) == {"a", "b"}
    assert described_columns({"columns": [{"name": "a"}, {"column": "b"}]}) == {"a", "b"}
    assert described_columns({"a": "mô tả a", "b": "mô tả b"}) == {"a", "b"}


def test_a_foreign_dictionary_is_rejected():
    """The actual production failure, stated as a test."""
    assert describes_active_dataset(TELCO_DICT, RETAIL_COLUMNS) is False


def test_the_matching_dictionary_is_accepted():
    """Dual-path guarantee: the telecom analysis keeps its data dictionary."""
    assert describes_active_dataset(TELCO_DICT, TELCO_COLUMNS) is True


def test_case_and_whitespace_do_not_break_the_match():
    assert describes_active_dataset(TELCO_DICT, [c.upper() + " " for c in TELCO_COLUMNS]) is True


def test_a_single_coincidental_column_is_not_enough():
    """`customer_id` appears in most datasets; one hit must not admit a whole dictionary."""
    dictionary = [{"column": "customer_id"}] + TELCO_DICT
    assert describes_active_dataset(dictionary, ["customer_id", "order_count"]) is False


def test_a_dictionary_covering_a_subset_is_accepted():
    """Dictionaries commonly document only the interesting columns, not every one."""
    assert describes_active_dataset(
        [{"column": "cl_total_6m"}, {"column": "fee_total"}], TELCO_COLUMNS
    ) is True


def test_unknown_active_columns_reject_rather_than_guess():
    """`_active_dataset_columns()` returns None when the peek fails.

    Injecting on an unverifiable dataset is what the old code did, and it is the failure
    mode itself. Silence is the safe direction: the model still has the real dataframe.
    """
    assert describes_active_dataset(TELCO_DICT, None) is False
    assert describes_active_dataset(TELCO_DICT, []) is False


def test_an_empty_dictionary_is_rejected():
    assert describes_active_dataset([], TELCO_COLUMNS) is False
    assert describes_active_dataset({}, TELCO_COLUMNS) is False


# --- the collector -------------------------------------------------------------------

def test_collect_skips_the_foreign_dictionary_and_keeps_the_matching_one(tmp_path):
    (tmp_path / "data_processed_t4_metadata.json").write_text(
        json.dumps(TELCO_DICT, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "retail_metadata.json").write_text(
        json.dumps([{"column": "order_count", "description": "Số đơn"},
                    {"column": "total_payment", "description": "Tổng chi"}], ensure_ascii=False),
        encoding="utf-8")

    out = collect_matching_metadata(str(tmp_path), RETAIL_COLUMNS)

    assert "cl_total_6m" not in out
    assert "order_count" in out
    assert "retail_metadata.json" in out


def test_collect_returns_empty_when_nothing_matches(tmp_path):
    (tmp_path / "x_metadata.json").write_text(json.dumps(TELCO_DICT), encoding="utf-8")
    assert collect_matching_metadata(str(tmp_path), RETAIL_COLUMNS) == ""


def test_collect_survives_a_malformed_file(tmp_path):
    (tmp_path / "broken_metadata.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "good_metadata.json").write_text(
        json.dumps([{"column": "order_count"}]), encoding="utf-8")

    out = collect_matching_metadata(str(tmp_path), RETAIL_COLUMNS)

    assert "order_count" in out


def test_collect_on_a_directory_with_no_metadata_returns_empty(tmp_path):
    assert collect_matching_metadata(str(tmp_path), RETAIL_COLUMNS) == ""
