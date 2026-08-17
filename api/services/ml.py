"""Website-facing service layer for the standalone H2O framework."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from h2o_framework import ExperimentConfig, ExperimentManager
from h2o_framework.errors import InvalidExperimentError

from . import workspace as workspace_service


SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".parquet", ".xlsx", ".xls"}
EXPERIMENTS_RELATIVE_ROOT = Path("Experiments") / "H2O"
experiment_manager = ExperimentManager()


async def upload_datasets(session_id: str, files: list[UploadFile]) -> dict[str, Any]:
    """Store ML inputs without refreshing or otherwise mutating the chat Agent."""

    return await workspace_service.upload_files_to_workspace(session_id, files)


def list_datasets(session_id: str) -> list[dict[str, Any]]:
    """List uploaded tabular datasets that H2O Studio can consume."""

    workspace_root = workspace_service.resolve_workspace_root(session_id)
    index = workspace_service.get_workspace_index(workspace_root)
    datasets: list[dict[str, Any]] = []
    for file_id, entry in index.items():
        path = _entry_path(workspace_root, entry)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS or not path.exists():
            continue
        metadata = _load_metadata(workspace_root, entry)
        datasets.append(
            {
                "id": file_id,
                "name": entry.get("filename") or path.name,
                "size": path.stat().st_size,
                "created_at": entry.get("created_at"),
                "columns": metadata.get("columns", []),
                "dtypes": metadata.get("dtypes", {}),
                "row_count": metadata.get("row_count"),
            }
        )
    datasets.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return datasets


def get_dataset(session_id: str, dataset_id: str) -> dict[str, Any]:
    """Return one dataset with schema information."""

    for dataset in list_datasets(session_id):
        if dataset["id"] == dataset_id:
            if not dataset["columns"]:
                workspace_root, _, path = _resolve_dataset(session_id, dataset_id)
                dataset.update(_inspect_schema(path))
            return dataset
    raise HTTPException(status_code=404, detail="Dataset không tồn tại trong workspace.")


def create_experiment(
    *,
    session_id: str,
    dataset_id: str,
    config: ExperimentConfig,
) -> dict[str, Any]:
    """Queue a new H2O experiment."""

    workspace_root, entry, dataset_path = _resolve_dataset(session_id, dataset_id)
    output_root = workspace_root / EXPERIMENTS_RELATIVE_ROOT
    try:
        manifest = experiment_manager.submit(
            dataset_path=dataset_path,
            output_root=output_root,
            config=config,
            dataset_id=dataset_id,
            dataset_name=entry.get("filename") or dataset_path.name,
            session_id=session_id,
        )
    except InvalidExperimentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _with_artifact_urls(manifest, session_id)


def list_experiments(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List persisted H2O experiments for a workspace session."""

    root = workspace_service.resolve_workspace_root(session_id) / EXPERIMENTS_RELATIVE_ROOT
    return [
        _with_artifact_urls(item, session_id)
        for item in experiment_manager.list(root, limit=limit)
    ]


def get_experiment(session_id: str, experiment_id: str) -> dict[str, Any]:
    """Read one H2O experiment."""

    root = workspace_service.resolve_workspace_root(session_id) / EXPERIMENTS_RELATIVE_ROOT
    try:
        manifest = experiment_manager.get(root, experiment_id)
    except InvalidExperimentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _with_artifact_urls(manifest, session_id)


def predict(
    *,
    session_id: str,
    experiment_id: str,
    dataset_id: str,
) -> dict[str, Any]:
    """Score an uploaded dataset using a completed experiment."""

    workspace_root, entry, dataset_path = _resolve_dataset(session_id, dataset_id)
    root = workspace_root / EXPERIMENTS_RELATIVE_ROOT
    try:
        prediction = experiment_manager.predict(
            output_root=root,
            experiment_id=experiment_id,
            dataset_path=dataset_path,
            dataset_name=entry.get("filename") or dataset_path.name,
        )
    except InvalidExperimentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    relative = EXPERIMENTS_RELATIVE_ROOT / experiment_id / prediction["artifact"]
    prediction["download_url"] = workspace_service.build_download_url(
        f"{session_id}/{relative.as_posix()}"
    )
    prediction["preview_url"] = workspace_service.build_preview_url(
        f"{session_id}/{relative.as_posix()}"
    )
    return prediction


def _resolve_dataset(session_id: str, dataset_id: str) -> tuple[Path, dict, Path]:
    workspace_root = workspace_service.resolve_workspace_root(session_id)
    index = workspace_service.get_workspace_index(workspace_root)
    entry = index.get(dataset_id)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="Dataset không tồn tại trong workspace.")
    path = _entry_path(workspace_root, entry)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Định dạng dataset chưa được H2O Studio hỗ trợ.")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File dataset không còn trên ổ đĩa.")
    return workspace_root, entry, path


def _entry_path(workspace_root: Path, entry: dict) -> Path:
    relative = str(entry.get("path") or "")
    path = (workspace_root / relative).resolve()
    if workspace_root != path and workspace_root not in path.parents:
        raise HTTPException(status_code=400, detail="Dataset path không hợp lệ.")
    return path


def _load_metadata(workspace_root: Path, entry: dict) -> dict[str, Any]:
    relative = entry.get("metadata_file")
    if not relative:
        return {}
    path = (workspace_root / str(relative)).resolve()
    if workspace_root not in path.parents or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _inspect_schema(path: Path) -> dict[str, Any]:
    """Fallback schema inspection for older uploads without metadata sidecars."""

    import pandas as pd

    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        frame = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",", nrows=1000)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path, nrows=1000)
    else:
        frame = pd.read_parquet(path).head(1000)
    return {
        "columns": [str(column) for column in frame.columns],
        "dtypes": {str(column): str(dtype) for column, dtype in frame.dtypes.items()},
    }


def _with_artifact_urls(manifest: dict[str, Any], session_id: str) -> dict[str, Any]:
    payload = dict(manifest)
    result = payload.get("result")
    if isinstance(result, dict):
        result = dict(result)
        artifacts = {}
        for name, path in (result.get("artifacts") or {}).items():
            relative = EXPERIMENTS_RELATIVE_ROOT / payload["id"] / path
            workspace_key = f"{session_id}/{relative.as_posix()}"
            artifacts[name] = {
                "path": relative.as_posix(),
                "download_url": workspace_service.build_download_url(workspace_key),
                "preview_url": (
                    workspace_service.build_preview_url(workspace_key)
                    if relative.suffix.lower() in {".csv", ".json"}
                    else None
                ),
            }
        result["artifacts"] = artifacts
        payload["result"] = result
    predictions = []
    for prediction in payload.get("predictions") or []:
        public_prediction = dict(prediction)
        artifact = public_prediction.get("artifact")
        if artifact:
            relative = EXPERIMENTS_RELATIVE_ROOT / payload["id"] / artifact
            workspace_key = f"{session_id}/{relative.as_posix()}"
            public_prediction["download_url"] = workspace_service.build_download_url(workspace_key)
            public_prediction["preview_url"] = workspace_service.build_preview_url(workspace_key)
        predictions.append(public_prediction)
    payload["predictions"] = predictions
    return payload
