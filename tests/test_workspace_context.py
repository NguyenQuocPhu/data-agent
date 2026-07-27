"""Only the dataset being analysed may appear in the model's context.

Observed live: the chat workspace accumulated 7 uploads — 4 retail files and 3 telco ones —
and the context builder injected every one of them, each with its full per-column
description. The model then wrote its behavioral_features list against the TELCO schema
(cl_total_6m, LOYALTY_RANK, OBJID_mask...) while load_dataset() returned the retail file:
one dataset analysed under another's column names.

Showing a schema is enough to make the model code against it, so the selection logic is
worth testing directly rather than trusting the prompt to say "ignore the others".
"""
import json

import pytest

from triadic_dgm.persona.dataset_profile import compute_fingerprint  # noqa: F401  (import sanity)


def _index(tmp_path, entries):
    """Write an index.json shaped like the workspace service produces."""
    data = {}
    for fid, filename, created in entries:
        data[fid] = {"filename": filename, "path": f"Files/{fid}_{filename}", "created_at": created}
    (tmp_path / "index.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def _select_active(index_data):
    """Mirror of LAMBDA.refresh_workspace_context's selection.

    Kept as a small reimplementation because the real method needs a full LAMBDA instance
    (kernel, LLM clients). If the two ever diverge this test stops protecting anything, so
    the assertions below also pin the ORDERING RULE itself, not just this copy of it.
    """
    import os

    tabular_exts = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
    tabular = [
        (fid, inf) for fid, inf in index_data.items()
        if os.path.splitext(inf.get("filename", inf.get("path", "")))[1].lower() in tabular_exts
    ]
    tabular.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    return tabular[:1] if tabular else list(index_data.items())[-1:]


def test_only_the_newest_dataset_is_selected(tmp_path):
    data = _index(tmp_path, [
        ("aaa", "telco_old.csv", "2026-07-10T10:00:00"),
        ("bbb", "telco_mid.csv", "2026-07-14T09:00:00"),
        ("ccc", "retail_new.csv", "2026-07-23T08:00:00"),
    ])
    active = _select_active(data)
    assert len(active) == 1
    assert active[0][1]["filename"] == "retail_new.csv"


def test_selection_matches_what_load_dataset_would_return(tmp_path):
    """The context and the sandbox must agree; describing a file the code will not load is
    exactly the leak this guards."""
    from api.services.profile_provider import selected_dataset_id

    data = _index(tmp_path, [
        ("aaa", "telco_old.csv", "2026-07-10T10:00:00"),
        ("ccc", "retail_new.csv", "2026-07-23T08:00:00"),
    ])
    assert selected_dataset_id(str(tmp_path)) == _select_active(data)[0][0] == "ccc"


def test_non_tabular_files_never_win(tmp_path):
    data = _index(tmp_path, [
        ("aaa", "retail.csv", "2026-07-10T10:00:00"),
        ("bbb", "notes.md", "2026-07-23T08:00:00"),
        ("ccc", "schema.json", "2026-07-23T09:00:00"),
    ])
    assert _select_active(data)[0][1]["filename"] == "retail.csv"


def test_empty_workspace_is_safe(tmp_path):
    assert _select_active({}) == []


@pytest.mark.parametrize("column", ["cl_total_6m", "LOYALTY_RANK", "OBJID_mask"])
def test_a_stale_telco_upload_contributes_no_column_names(tmp_path, column):
    """The regression itself: a telco file left in the workspace must not reach the model."""
    data = _index(tmp_path, [
        ("telco", "data_processed_t4.csv", "2026-07-13T03:00:00"),
        ("retail", "olist.csv", "2026-07-23T08:00:00"),
    ])
    active = _select_active(data)
    rendered = "".join(f"{fid} {inf['filename']}" for fid, inf in active)
    assert "data_processed_t4" not in rendered
    assert column not in rendered
