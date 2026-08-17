"""Asynchronous experiment orchestration and durable manifests."""

from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import InvalidExperimentError
from .experiment import ExperimentConfig, H2OExperiment
from .runtime import H2ORuntime


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentManager:
    """Run H2O jobs off the request thread and persist their complete state.

    A single worker is the safe PoC default: H2O can parallelize an individual job across
    its cores, while unconstrained concurrent AutoML jobs can easily exhaust the JVM heap.
    Increase ``H2O_MAX_CONCURRENT_EXPERIMENTS`` only with explicit resource limits.
    """

    def __init__(
        self,
        runtime: H2ORuntime | None = None,
        *,
        max_workers: int | None = None,
    ) -> None:
        self.runtime = runtime or H2ORuntime()
        workers = max_workers or int(os.getenv("H2O_MAX_CONCURRENT_EXPERIMENTS", "1"))
        self._executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="h2o-ml")
        self._lock = threading.RLock()

    def submit(
        self,
        *,
        dataset_path: str | Path,
        output_root: str | Path,
        config: ExperimentConfig,
        dataset_id: str,
        dataset_name: str,
        session_id: str,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Persist and enqueue an experiment, returning immediately."""

        config.validate()
        experiment_id = uuid.uuid4().hex[:12]
        experiment_dir = Path(output_root).resolve() / experiment_id
        experiment_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "id": experiment_id,
            "status": "queued",
            "session_id": session_id,
            "dataset_id": dataset_id,
            "dataset_name": dataset_name,
            "created_at": _utc_now(),
            "started_at": None,
            "completed_at": None,
            "config": asdict(config),
            "result": None,
            "error": None,
        }
        self._write_manifest(experiment_dir, manifest)
        self._executor.submit(
            self._run,
            experiment_dir,
            Path(dataset_path).resolve(),
            config,
            on_complete,
        )
        return self._public_manifest(manifest, experiment_dir)

    def get(self, output_root: str | Path, experiment_id: str) -> dict[str, Any]:
        """Load one public experiment manifest."""

        experiment_dir = self._safe_experiment_dir(output_root, experiment_id)
        manifest = self._read_manifest(experiment_dir)
        if manifest is None:
            raise InvalidExperimentError("Không tìm thấy experiment.")
        return self._public_manifest(manifest, experiment_dir)

    def list(self, output_root: str | Path, limit: int = 50) -> list[dict[str, Any]]:
        """List newest persisted experiments."""

        root = Path(output_root).resolve()
        if not root.exists():
            return []
        manifests: list[dict[str, Any]] = []
        for path in root.glob("*/manifest.json"):
            manifest = self._read_manifest(path.parent)
            if manifest:
                manifests.append(self._public_manifest(manifest, path.parent))
        manifests.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return manifests[:limit]

    def predict(
        self,
        *,
        output_root: str | Path,
        experiment_id: str,
        dataset_path: str | Path,
        dataset_name: str,
    ) -> dict[str, Any]:
        """Score a dataset with a completed experiment and persist the predictions."""

        experiment_dir = self._safe_experiment_dir(output_root, experiment_id)
        manifest = self._read_manifest(experiment_dir)
        if manifest is None:
            raise InvalidExperimentError("Không tìm thấy experiment.")
        if manifest.get("status") != "completed":
            raise InvalidExperimentError("Chỉ experiment đã hoàn tất mới có thể predict.")
        result = manifest.get("result") or {}
        model_path = (result.get("artifacts") or {}).get("binary_model")
        if not model_path or not Path(model_path).exists():
            raise InvalidExperimentError("Không tìm thấy binary model của experiment.")

        h2o = self.runtime.client()
        model = h2o.load_model(str(Path(model_path).resolve()))
        frame = H2OExperiment._import_frame(h2o, Path(dataset_path).resolve())
        predictions = model.predict(frame)
        prediction_id = uuid.uuid4().hex[:10]
        prediction_dir = experiment_dir / "predictions"
        prediction_dir.mkdir(parents=True, exist_ok=True)
        output_path = prediction_dir / f"{prediction_id}.csv"
        h2o.download_csv(predictions, str(output_path))

        record = {
            "id": prediction_id,
            "dataset_name": dataset_name,
            "created_at": _utc_now(),
            "rows": int(predictions.nrows),
            "artifact": str(output_path),
        }
        manifest.setdefault("predictions", []).append(record)
        self._write_manifest(experiment_dir, manifest)
        public_record = dict(record)
        public_record["artifact"] = str(output_path.relative_to(experiment_dir))
        return public_record

    def _run(
        self,
        experiment_dir: Path,
        dataset_path: Path,
        config: ExperimentConfig,
        on_complete: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        manifest = self._read_manifest(experiment_dir)
        if manifest is None:
            return
        manifest.update({"status": "running", "started_at": _utc_now()})
        self._write_manifest(experiment_dir, manifest)
        try:
            result = H2OExperiment(config, runtime=self.runtime).fit(dataset_path, experiment_dir)
            manifest.update(
                {
                    "status": "completed",
                    "completed_at": _utc_now(),
                    "result": result.to_dict(),
                }
            )
        except Exception as exc:
            (experiment_dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            manifest.update(
                {
                    "status": "failed",
                    "completed_at": _utc_now(),
                    "error": str(exc),
                }
            )
        self._write_manifest(experiment_dir, manifest)
        if on_complete is not None:
            try:
                on_complete(self._public_manifest(manifest, experiment_dir))
            except Exception:
                pass

    def _write_manifest(self, experiment_dir: Path, manifest: dict[str, Any]) -> None:
        with self._lock:
            target = experiment_dir / "manifest.json"
            temporary = experiment_dir / ".manifest.json.tmp"
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(target)

    def _read_manifest(self, experiment_dir: Path) -> dict[str, Any] | None:
        with self._lock:
            path = experiment_dir / "manifest.json"
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None

    @staticmethod
    def _safe_experiment_dir(output_root: str | Path, experiment_id: str) -> Path:
        root = Path(output_root).resolve()
        candidate = (root / experiment_id).resolve()
        if candidate.parent != root or not experiment_id or any(
            character not in "0123456789abcdef" for character in experiment_id.lower()
        ):
            raise InvalidExperimentError("Experiment id không hợp lệ.")
        return candidate

    @staticmethod
    def _public_manifest(manifest: dict[str, Any], experiment_dir: Path) -> dict[str, Any]:
        payload = dict(manifest)
        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("artifacts"), dict):
            normalized: dict[str, str] = {}
            for name, artifact in result["artifacts"].items():
                try:
                    normalized[name] = str(Path(artifact).resolve().relative_to(experiment_dir))
                except (ValueError, OSError):
                    continue
            result = dict(result)
            result["artifacts"] = normalized
            payload["result"] = result
        predictions = []
        for prediction in payload.get("predictions") or []:
            public_prediction = dict(prediction)
            artifact = public_prediction.get("artifact")
            if artifact:
                try:
                    public_prediction["artifact"] = str(
                        Path(artifact).resolve().relative_to(experiment_dir)
                    )
                except (ValueError, OSError):
                    public_prediction.pop("artifact", None)
            predictions.append(public_prediction)
        payload["predictions"] = predictions
        return payload
