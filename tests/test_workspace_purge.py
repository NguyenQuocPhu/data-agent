"""A dataset must only be in play if it was uploaded for the current analysis.

A leftover dataset is not passive clutter: its schema gets described to the model, and the
model writes its analysis against whatever schema it is shown. That is how a stale telco
file produced a telco column list for a retail dataset.
"""
import asyncio
import json

import pytest

from api.services import workspace as ws


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A workspace directory with an index, wired into the service's path resolution."""
    root = tmp_path / "default"
    (root / "Files").mkdir(parents=True)
    (root / "Metadata").mkdir(parents=True)
    monkeypatch.setattr(ws, "resolve_workspace_root", lambda session_id: root)
    return root


def _register(root, file_id, filename, content=b"a,b\n1,2\n", with_metadata=True):
    data_path = root / "Files" / f"{file_id}_{filename}"
    data_path.write_bytes(content)
    entry = {"filename": filename, "path": f"Files/{file_id}_{filename}", "created_at": "2026-01-01"}
    if with_metadata:
        meta = root / "Metadata" / f"{file_id}.json"
        meta.write_text("{}", encoding="utf-8")
        entry["metadata_file"] = f"Metadata/{file_id}.json"
    index_path = root / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    index[file_id] = entry
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return data_path


def _index(root):
    return json.loads((root / "index.json").read_text())


def test_purge_removes_datasets_files_and_index_entries(workspace):
    a = _register(workspace, "aaa", "telco.csv")
    b = _register(workspace, "bbb", "retail.csv")

    result = ws.purge_datasets("default")

    assert result["removed"] == 2
    assert result["freed_bytes"] > 0
    assert not a.exists() and not b.exists()
    assert _index(workspace) == {}


def test_purge_removes_the_metadata_sidecar_too(workspace):
    _register(workspace, "aaa", "telco.csv")
    ws.purge_datasets("default")
    assert not (workspace / "Metadata" / "aaa.json").exists()


def test_purge_leaves_generated_outputs_alone(workspace):
    """Reports and charts are results the user may still want; only datasets go."""
    _register(workspace, "aaa", "telco.csv")
    _register(workspace, "bbb", "report.md", content=b"# report", with_metadata=False)

    ws.purge_datasets("default")

    assert (workspace / "Files" / "bbb_report.md").exists()
    assert list(_index(workspace)) == ["bbb"]


def test_purge_is_idempotent_and_safe_when_empty(workspace):
    assert ws.purge_datasets("default") == {"removed": 0, "freed_bytes": 0}
    _register(workspace, "aaa", "telco.csv")
    ws.purge_datasets("default")
    assert ws.purge_datasets("default")["removed"] == 0


def test_purge_survives_a_missing_file_on_disk(workspace):
    """An index entry whose file was deleted out of band must not break the purge."""
    path = _register(workspace, "aaa", "telco.csv")
    path.unlink()
    assert ws.purge_datasets("default")["removed"] == 1
    assert _index(workspace) == {}


def test_purge_survives_a_corrupt_index(workspace):
    (workspace / "index.json").write_text("{not json", encoding="utf-8")
    assert ws.purge_datasets("default") == {"removed": 0, "freed_bytes": 0}


def test_upload_replaces_the_previous_dataset(workspace, monkeypatch):
    """The point of the whole change: after an upload, exactly one dataset is registered.

    Driven with asyncio.run rather than pytest-asyncio, which is not installed here.
    """
    _register(workspace, "old", "telco.csv")

    async def _fake_save(root, target, files):
        _register(workspace, "new", "retail.csv")
        return [{"file_id": "new", "name": "retail.csv"}], []

    monkeypatch.setattr(ws, "_save_uploads", _fake_save)
    result = asyncio.run(ws.upload_files_to_workspace("default", []))

    assert result["replaced"] == 1
    assert list(_index(workspace)) == ["new"]
