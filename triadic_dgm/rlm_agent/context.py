"""Build canonical persistent-RLM context payloads for the data agent."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .types import ContextSnapshot, ControlEvent


TABULAR_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}


class ContextBuilder:
    def __init__(self, workspace_base: str | Path, max_files: int = 200):
        self.workspace_base = Path(workspace_base).resolve()
        self.max_files = max_files

    def workspace_root(self, session_id: str) -> Path:
        safe = "".join(ch for ch in (session_id or "default") if ch.isalnum() or ch in "._-")
        safe = safe.strip(".-") or "default"
        root = (self.workspace_base / safe).resolve()
        if root != self.workspace_base and self.workspace_base not in root.parents:
            raise ValueError("Invalid workspace session id")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def build(
        self,
        user_message: str,
        session_id: str,
        context_index: int,
        pending_control: ControlEvent | None = None,
        selected_skill: dict[str, Any] | None = None,
    ) -> ContextSnapshot:
        root = self.workspace_root(session_id)
        if context_index == 0:
            index = self._load_index(root)
            active_id, active_entry = self._active_dataset(index)
            payload: dict[str, Any] = {
                "type": "user_request",
                "request": user_message,
                "datasets": self._dataset_contents(root, index),
                "active_dataset": self._dataset_summary(root, active_id, active_entry),
            }
        else:
            payload = {
                "type": "human_response" if pending_control else "user_request",
                "request": user_message,
                "human_response": {
                    "for": pending_control.to_dict(),
                    "content": user_message,
                } if pending_control else None,
            }
        if selected_skill is not None:
            payload["selected_skill"] = selected_skill
        return ContextSnapshot(
            session_id=session_id,
            context_index=context_index,
            payload=payload,
        )

    @classmethod
    def _dataset_contents(
        cls,
        root: Path,
        index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return every registered tabular dataset with its complete file content."""
        entries = [
            (file_id, entry)
            for file_id, entry in index.items()
            if Path(str(entry.get("filename") or entry.get("path") or "")).suffix.lower()
            in TABULAR_EXTENSIONS
        ]
        entries.sort(key=lambda pair: str(pair[1].get("created_at", "")))
        datasets: list[dict[str, Any]] = []
        for file_id, entry in entries:
            relative = str(entry.get("path") or "")
            path = (root / relative).resolve()
            if not relative or root not in path.parents or not path.is_file():
                continue
            suffix = path.suffix.lower()
            metadata = cls._metadata(root, entry)
            raw = path.read_bytes()
            dataset: dict[str, Any] = {
                "id": file_id,
                "filename": entry.get("filename") or path.name,
                "format": suffix.lstrip("."),
                "size_bytes": len(raw),
                "metadata": metadata,
            }
            if suffix in {".csv", ".tsv"}:
                content, encoding = cls._decode_text(raw, metadata.get("encoding"))
                dataset.update({
                    "representation": "text",
                    "encoding": encoding,
                    "content": content,
                })
            else:
                dataset.update({
                    "representation": "base64",
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode("ascii"),
                })
            datasets.append(dataset)
        return datasets

    @staticmethod
    def _decode_text(raw: bytes, preferred: Any = None) -> tuple[str, str]:
        candidates = ([str(preferred)] if preferred else []) + [
            "utf-8", "utf-8-sig", "cp1258", "latin-1"
        ]
        seen: set[str] = set()
        for encoding in candidates:
            if not encoding or encoding in seen:
                continue
            seen.add(encoding)
            try:
                return raw.decode(encoding), encoding
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("latin-1"), "latin-1"

    @staticmethod
    def _metadata(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
        relative = entry.get("metadata_file")
        if not relative:
            return {}
        path = (root / str(relative)).resolve()
        if root not in path.parents or not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _load_index(root: Path) -> dict[str, dict[str, Any]]:
        path = root / "index.json"
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _active_dataset(
        index: dict[str, dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any] | None]:
        entries = [
            (file_id, entry)
            for file_id, entry in index.items()
            if Path(str(entry.get("filename") or entry.get("path") or "")).suffix.lower()
            in TABULAR_EXTENSIONS
        ]
        if not entries:
            return None, None
        entries.sort(key=lambda pair: str(pair[1].get("created_at", "")), reverse=True)
        return entries[0]

    @staticmethod
    def _dataset_summary(
        root: Path,
        file_id: str | None,
        entry: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not file_id or not entry:
            return None
        relative = str(entry.get("path", ""))
        path = (root / relative).resolve()
        summary: dict[str, Any] = {
            "id": file_id,
            "filename": entry.get("filename") or path.name,
            "path": relative,
            "size_bytes": path.stat().st_size if path.exists() else None,
        }
        metadata = ContextBuilder._metadata(root, entry)
        for key in ("rows", "columns", "dtypes", "separator", "encoding"):
            if key in metadata:
                summary[key] = metadata[key]
        return summary
