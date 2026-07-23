from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
import uuid
import datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote, urlencode

import httpx
import pandas as pd
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from ..settings import PREVIEWABLE_EXTENSIONS, settings


GENERATED_INDEX_FILENAME = ".deepanalyze_generated.json"


def get_session_workspace(session_id: str) -> str:
    safe_session_id = (session_id or "default").strip() or "default"
    session_dir = Path(settings.workspace_base_dir) / safe_session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # Auto-create core workspace directories
    for folder in ["Files", "Metadata", "Experiments", "Artifacts", "Golden Path"]:
        (session_dir / folder).mkdir(parents=True, exist_ok=True)
        
    return str(session_dir)


def _split_session_relative_path(rel_path: str) -> tuple[str, str]:
    normalized = _normalize_generated_rel_path(rel_path)
    if not normalized:
        return "default", ""

    session_id, _, workspace_rel_path = normalized.partition("/")
    return (session_id or "default"), workspace_rel_path


def _build_workspace_transfer_url(rel_path: str, *, download: bool) -> str:
    session_id, workspace_rel_path = _split_session_relative_path(rel_path)
    params = {
        "session_id": session_id,
        "path": workspace_rel_path,
    }
    if download:
        params["download"] = "1"
    return f"/workspace/download?{urlencode(params, quote_via=quote)}"


def build_download_url(rel_path: str) -> str:
    return _build_workspace_transfer_url(rel_path, download=True)


def build_preview_url(rel_path: str) -> str:
    return _build_workspace_transfer_url(rel_path, download=False)


def _generated_index_path(workspace_root: Path) -> Path:
    return workspace_root / "generated" / GENERATED_INDEX_FILENAME


def _normalize_generated_rel_path(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")


def load_generated_index(session_id: str) -> set[str]:
    workspace_root = resolve_workspace_root(session_id)
    index_path = _generated_index_path(workspace_root)
    if not index_path.exists():
        return set()
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()
    normalized = {
        _normalize_generated_rel_path(str(item))
        for item in payload
        if str(item).strip()
    }
    existing: set[str] = set()
    for rel_path in normalized:
        candidate = workspace_root / rel_path
        if candidate.exists() and candidate.is_file():
            existing.add(rel_path)
    if existing != normalized:
        save_generated_index(session_id, existing)
    return existing


def save_generated_index(session_id: str, rel_paths: Iterable[str]) -> None:
    workspace_root = resolve_workspace_root(session_id)
    index_path = _generated_index_path(workspace_root)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = sorted(
        {
            _normalize_generated_rel_path(str(path))
            for path in rel_paths
            if _normalize_generated_rel_path(str(path))
        }
    )
    index_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_generated_paths(session_id: str, rel_paths: Iterable[str]) -> set[str]:
    generated = load_generated_index(session_id)
    generated.update(
        _normalize_generated_rel_path(str(path))
        for path in rel_paths
        if _normalize_generated_rel_path(str(path))
    )
    save_generated_index(session_id, generated)
    return generated


def collect_file_info(source: str | Path | Sequence[str | Path]) -> str:
    file_paths: list[Path] = []
    seen: set[Path] = set()

    if isinstance(source, (str, Path)):
        candidate = Path(source)
        if not candidate.exists():
            return ""
        if candidate.is_dir():
            file_paths = sorted(
                [
                    path
                    for path in candidate.iterdir()
                    if path.is_file() and path.name != GENERATED_INDEX_FILENAME
                ],
                key=lambda path: path.name.lower(),
            )
        elif candidate.is_file():
            if candidate.name == GENERATED_INDEX_FILENAME:
                return ""
            file_paths = [candidate]
    else:
        for item in source or []:
            candidate = Path(item)
            if (
                not candidate.exists()
                or not candidate.is_file()
                or candidate.name == GENERATED_INDEX_FILENAME
            ):
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            file_paths.append(candidate)
        file_paths.sort(key=lambda path: path.name.lower())

    parts: list[str] = []
    for index, file_path in enumerate(file_paths, start=1):
        size_str = f"{file_path.stat().st_size / 1024:.1f}KB"
        file_info = {"name": file_path.name, "size": size_str}
        parts.append(f"File {index}:\n{json.dumps(file_info, indent=4, ensure_ascii=False)}\n")
    return "\n".join(parts)


def get_file_icon(extension: str) -> str:
    ext = extension.lower()
    icons = {
        (".jpg", ".jpeg", ".png", ".gif", ".bmp"): "🖼️",
        (".pdf",): "📃",
        (".doc", ".docx"): "📌",
        (".txt",): "📝",
        (".md",): "📑",
        (".csv", ".xlsx"): "📳",
        (".json", ".sqlite"): "🗽",
        (".mp4", ".avi", ".mov"): "🎴",
        (".mp3", ".wav"): "🎍",
        (".zip", ".rar", ".tar"): "🗞️",
    }
    for extensions, icon in icons.items():
        if ext in extensions:
            return icon
    return "📧"


TABLE_EXTENSIONS = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".parquet",
    ".sqlite",
    ".db",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
}

TEXT_PREVIEW_EXTENSIONS = {
    ".txt",
    ".log",
    ".py",
    ".sql",
    ".json",
    ".yaml",
    ".yml",
}

MARKDOWN_PREVIEW_EXTENSIONS = {
    ".md",
    ".markdown",
}

SQLITE_PREVIEW_EXTENSIONS = {
    ".sqlite",
    ".db",
}

BLOCKED_UPLOAD_EXTENSIONS = {
    ".py",
}

# Extensions that are "scannable" — i.e. files Python agents might generate
SCANNABLE_AGENT_EXTENSIONS = (
    TABLE_EXTENSIONS
    | IMAGE_EXTENSIONS
    | TEXT_PREVIEW_EXTENSIONS
    | MARKDOWN_PREVIEW_EXTENSIONS
    | SQLITE_PREVIEW_EXTENSIONS
    | {".joblib", ".pkl", ".pickle", ".pdf", ".zip", ".model", ".h5", ".pt", ".pth", ".onnx", ".ipynb"}
)

# Internal files we skip when scanning
_SKIP_FILENAMES = {
    "index.json",
    ".deepanalyze_generated.json",
    "programmer_msg.json",
    "verifier_memory.json",
    "config.json",
    "system_dialogue.json",
}


def scan_and_register_generated(
    session_id: str,
    source_dir: str | Path,
    known_files_before: set[str] | None = None,
) -> list[dict]:
    """
    Quét source_dir (session_cache_path của LAMBDA), copy file mới vào
    workspace/<session_id>/generated/, và register vào .deepanalyze_generated.json.

    Args:
        session_id:          Frontend session id (hoặc "default").
        source_dir:          Thư mục LAMBDA đã ghi file (session_cache_path).
        known_files_before:  Set tên file đã biết TRƯỚC khi execute.
                             Nếu None, copy tất cả file có extension hợp lệ.

    Returns:
        Danh sách dict mô tả từng file mới {name, path, category, download_url, preview_url, size}.
    """
    source = Path(source_dir)
    if not source.exists() or not source.is_dir():
        return []

    workspace_root = resolve_workspace_root(session_id)
    gen_dir = workspace_root / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)

    new_files: list[dict] = []

    for candidate in sorted(source.iterdir()):
        if not candidate.is_file():
            continue
        if candidate.name in _SKIP_FILENAMES:
            continue
        if candidate.name.startswith("."):
            continue
        ext = candidate.suffix.lower()
        if ext not in SCANNABLE_AGENT_EXTENSIONS:
            continue
        # If we have a before-snapshot, only grab files NOT in it
        if known_files_before is not None and candidate.name in known_files_before:
            continue

        # Copy to generated/  (overwrite if same name exists — latest wins)
        dst = gen_dir / candidate.name
        try:
            shutil.copy2(str(candidate), str(dst))
        except Exception as e:
            print(f"[scan_and_register] Failed to copy {candidate}: {e}")
            continue

        rel = f"generated/{candidate.name}"
        rel_with_session = f"{session_id}/{rel}"

        file_info = {
            "name": candidate.name,
            "path": rel,
            "size": dst.stat().st_size,
            "extension": ext,
            "icon": get_file_icon(ext),
            "category": classify_file_type(dst),
            "is_generated": True,
            "download_url": build_download_url(rel_with_session),
            "preview_url": (
                build_preview_url(rel_with_session)
                if ext in PREVIEWABLE_EXTENSIONS
                else None
            ),
        }
        new_files.append(file_info)

    # Register into .deepanalyze_generated.json
    if new_files:
        register_generated_paths(session_id, [f["path"] for f in new_files])

    return new_files


def get_generated_files_for_session(session_id: str) -> list[dict]:
    """
    Trả về toàn bộ file trong workspace/<session_id>/generated/.
    Dùng cho GET /workspace/generated-files.
    """
    workspace_root = resolve_workspace_root(session_id)
    gen_dir = workspace_root / "generated"
    if not gen_dir.exists():
        return []

    files: list[dict] = []
    for f in sorted(gen_dir.iterdir()):
        if not f.is_file() or _is_internal_workspace_file(f):
            continue
        rel = f"generated/{f.name}"
        rel_with_session = f"{session_id}/{rel}"
        ext = f.suffix.lower()
        files.append({
            "name": f.name,
            "path": rel,
            "size": f.stat().st_size,
            "extension": ext,
            "icon": get_file_icon(ext),
            "category": classify_file_type(f),
            "is_generated": True,
            "download_url": build_download_url(rel_with_session),
            "preview_url": (
                build_preview_url(rel_with_session)
                if ext in PREVIEWABLE_EXTENSIONS
                else None
            ),
        })
    return files


def classify_file_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in TABLE_EXTENSIONS:
        return "table"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def _json_safe_value(value):
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    return text if len(text) <= 500 else f"{text[:500]}…"


def _build_dataframe_preview(
    dataframe: pd.DataFrame,
    *,
    title: str | None = None,
    kind: str = "table",
    max_rows: int = 100,
    max_cols: int = 30,
    extra: dict | None = None,
) -> dict:
    trimmed = dataframe.copy()
    total_rows = int(len(trimmed.index))
    total_cols = int(len(trimmed.columns))
    if total_cols > max_cols:
        trimmed = trimmed.iloc[:, :max_cols]
    row_truncated = total_rows > max_rows
    col_truncated = total_cols > max_cols
    trimmed = trimmed.head(max_rows).fillna("")
    rows = [
        [_json_safe_value(value) for value in row]
        for row in trimmed.astype(object).values.tolist()
    ]
    payload = {
        "kind": kind,
        "title": title,
        "columns": [str(column) for column in trimmed.columns.tolist()],
        "rows": rows,
        "row_count": total_rows,
        "column_count": total_cols,
        "truncated": row_truncated or col_truncated,
    }
    if extra:
        payload.update(extra)
    return payload


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    safe_page_size = max(1, min(page_size, 200))
    safe_page = max(1, page)
    return safe_page, safe_page_size


def _build_paginated_preview(
    dataframe: pd.DataFrame,
    *,
    title: str | None = None,
    kind: str = "table",
    page: int = 1,
    page_size: int = 50,
    max_cols: int = 30,
    extra: dict | None = None,
) -> dict:
    safe_page, safe_page_size = _clamp_page(page, page_size)
    total_rows = int(len(dataframe.index))
    total_cols = int(len(dataframe.columns))
    total_pages = max(1, (total_rows + safe_page_size - 1) // safe_page_size)
    safe_page = min(safe_page, total_pages)

    trimmed = dataframe.copy()
    if total_cols > max_cols:
        trimmed = trimmed.iloc[:, :max_cols]

    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    page_df = trimmed.iloc[start:end].fillna("")
    rows = [
        [_json_safe_value(value) for value in row]
        for row in page_df.astype(object).values.tolist()
    ]
    payload = {
        "kind": kind,
        "title": title,
        "columns": [str(column) for column in page_df.columns.tolist()],
        "rows": rows,
        "row_count": total_rows,
        "column_count": total_cols,
        "page": safe_page,
        "page_size": safe_page_size,
        "total_pages": total_pages,
        "truncated": total_cols > max_cols,
    }
    if extra:
        payload.update(extra)
    return payload


def preview_workspace_file(
    session_id: str,
    relative_path: str,
    *,
    page: int = 1,
    page_size: int = 50,
    table_name: str = "",
    sheet_name: str = "",
) -> dict:
    file_path = resolve_workspace_path(session_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    ext = file_path.suffix.lower()

    if ext in TEXT_PREVIEW_EXTENSIONS:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return {
            "kind": "text",
            "title": file_path.name,
            "content": content[:50000],
            "truncated": len(content) > 50000,
        }

    if ext in MARKDOWN_PREVIEW_EXTENSIONS:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return {
            "kind": "markdown",
            "title": file_path.name,
            "content": content[:50000],
            "truncated": len(content) > 50000,
        }

    if ext in {".csv", ".tsv"}:
        separator = "\t" if ext == ".tsv" else ","
        dataframe = pd.read_csv(file_path, sep=separator)
        return _build_paginated_preview(
            dataframe,
            title=file_path.name,
            page=page,
            page_size=page_size,
        )

    if ext in {".xlsx", ".xls"}:
        workbook = pd.ExcelFile(file_path)
        active_sheet = sheet_name or workbook.sheet_names[0]
        if active_sheet not in workbook.sheet_names:
            raise HTTPException(status_code=404, detail="Sheet not found")
        dataframe = workbook.parse(sheet_name=active_sheet)
        return _build_paginated_preview(
            dataframe,
            title=file_path.name,
            page=page,
            page_size=page_size,
            extra={
                "sheet_name": active_sheet,
                "sheet_names": workbook.sheet_names,
            },
        )

    if ext in SQLITE_PREVIEW_EXTENSIONS:
        with sqlite3.connect(file_path) as connection:
            cursor = connection.cursor()
            table_names = [
                row[0]
                for row in cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]
            if not table_name:
                tables: list[dict] = []
                for current_table in table_names:
                    total_rows = cursor.execute(
                        f'SELECT COUNT(*) FROM "{current_table.replace(chr(34), chr(34) * 2)}"'
                    ).fetchone()[0]
                    columns = [
                        row[1]
                        for row in cursor.execute(
                            f'PRAGMA table_info("{current_table.replace(chr(34), chr(34) * 2)}")'
                        ).fetchall()
                    ]
                    tables.append(
                        {
                            "table_name": current_table,
                            "title": current_table,
                            "row_count": int(total_rows),
                            "column_count": len(columns),
                            "columns": columns,
                        }
                    )

                return {
                    "kind": "database",
                    "view": "tables",
                    "title": file_path.name,
                    "tables": tables,
                    "table_names": table_names,
                }

            if table_name not in table_names:
                raise HTTPException(status_code=404, detail="Table not found")

            safe_table_name = table_name.replace('"', '""')
            dataframe = pd.read_sql_query(
                f'SELECT * FROM "{safe_table_name}"',
                connection,
            )
            preview = _build_paginated_preview(
                dataframe,
                title=file_path.name,
                kind="database",
                page=page,
                page_size=page_size,
                extra={
                    "view": "table",
                    "table_name": table_name,
                    "table_names": table_names,
                },
            )
            preview["total_rows"] = preview["row_count"]
            return preview

    raise HTTPException(status_code=415, detail="Preview not supported")


def get_workspace_file_response(
    session_id: str,
    relative_path: str,
    *,
    download: bool = False,
) -> FileResponse:
    file_path = resolve_workspace_path(session_id, relative_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    response_kwargs = {
        "path": file_path,
        "content_disposition_type": "attachment" if download else "inline",
    }
    if download:
        response_kwargs["filename"] = file_path.name
    return FileResponse(**response_kwargs)


def uniquify_path(target: Path) -> Path:
    if not target.exists():
        return target

    parent = target.parent
    stem = target.stem
    suffix = target.suffix
    match = re.match(r"^(.*) \((\d+)\)$", stem)
    base = stem
    start = 1
    if match:
        base = match.group(1)
        try:
            start = int(match.group(2)) + 1
        except ValueError:
            start = 1

    index = start
    while True:
        candidate = parent / f"{base} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def resolve_workspace_root(session_id: str) -> Path:
    return Path(get_session_workspace(session_id)).resolve()


def resolve_workspace_path(session_id: str, relative_path: str = "") -> Path:
    workspace_root = resolve_workspace_root(session_id)
    target = (workspace_root / (relative_path or "")).resolve()
    if target != workspace_root and workspace_root not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


def _is_internal_workspace_file(path: Path) -> bool:
    return path.name == GENERATED_INDEX_FILENAME


def _is_generated_workspace_path(rel_path: str, generated_index: set[str]) -> bool:
    normalized = _normalize_generated_rel_path(rel_path)
    return normalized in generated_index or normalized == "generated" or normalized.startswith("generated/")


def list_workspace_files(session_id: str) -> list[dict]:
    workspace_root = resolve_workspace_root(session_id)
    generated_index = load_generated_index(session_id)
    files: list[dict] = []
    all_files = [
        path
        for path in workspace_root.rglob("*")
        if path.is_file() and not _is_internal_workspace_file(path)
    ]
    for file_path in sorted(all_files, key=lambda path: _rel_path(path, workspace_root).lower()):
        rel = _rel_path(file_path, workspace_root)
        rel_path = f"{session_id}/{rel}"
        files.append(
            {
                "name": file_path.name,
                "path": rel,
                "size": file_path.stat().st_size,
                "extension": file_path.suffix.lower(),
                "icon": get_file_icon(file_path.suffix),
                "category": classify_file_type(file_path),
                "is_generated": _is_generated_workspace_path(rel, generated_index),
                "download_url": build_download_url(rel_path),
                "preview_url": (
                    build_preview_url(rel_path)
                    if file_path.suffix.lower() in PREVIEWABLE_EXTENSIONS
                    else None
                ),
            }
        )
    return files


def download_generated_bundle(session_id: str, category: str = "all") -> FileResponse:
    workspace_root = resolve_workspace_root(session_id)
    generated_root = workspace_root / "generated"
    if not generated_root.exists() or not generated_root.is_dir():
        raise HTTPException(status_code=404, detail="generated folder not found")

    normalized_category = (category or "all").strip().lower()
    if normalized_category not in {"all", "table", "image", "other"}:
        raise HTTPException(status_code=400, detail="invalid category")

    files = [
        path
        for path in generated_root.rglob("*")
        if path.is_file() and not _is_internal_workspace_file(path)
    ]
    if normalized_category != "all":
        files = [
            path for path in files if classify_file_type(path) == normalized_category
        ]

    if not files:
        raise HTTPException(status_code=404, detail="no files matched the category")

    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"deepanalyze_{normalized_category}_",
        suffix=".zip",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()

    category_dirs = {
        "table": "tables",
        "image": "images",
        "other": "others",
    }

    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive_name = file_path.relative_to(generated_root)
            if normalized_category == "all":
                classified = classify_file_type(file_path)
                archive_name = Path(category_dirs[classified]) / archive_name
            archive.write(file_path, archive_name.as_posix())

    filename = f"generated_{normalized_category}.zip"
    return FileResponse(
        path=temp_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: temp_path.unlink(missing_ok=True)),
    )


def _rel_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.name


def build_tree(
    path: Path,
    root: Path | None = None,
    session_id: str = "default",
    generated_index: set[str] | None = None,
) -> dict:
    root = root or path
    generated_index = generated_index if generated_index is not None else load_generated_index(session_id)
    node: dict = {
        "name": path.name or "workspace",
        "path": _rel_path(path, root),
        "is_dir": path.is_dir(),
    }

    if path.is_dir():
        def sort_key(candidate: Path) -> tuple[bool, bool, str]:
            return (candidate.name == "generated", not candidate.is_dir(), candidate.name.lower())

        node["children"] = [
            build_tree(child, root, session_id, generated_index)
            for child in sorted(path.iterdir(), key=sort_key)
            if not child.name.startswith(".") and not _is_internal_workspace_file(child)
        ]
        node["is_generated"] = node["path"] == "generated" or node["path"].startswith("generated/")
        return node

    rel = _rel_path(path, root)
    node["size"] = path.stat().st_size
    node["extension"] = path.suffix.lower()
    node["icon"] = get_file_icon(path.suffix)
    node["is_generated"] = _is_generated_workspace_path(rel, generated_index)
    node["download_url"] = build_download_url(f"{session_id}/{rel}")
    if path.suffix.lower() in PREVIEWABLE_EXTENSIONS:
        node["preview_url"] = build_preview_url(f"{session_id}/{rel}")
    return node


def delete_workspace_file(session_id: str, relative_path: str) -> dict:
    target = resolve_workspace_path(session_id, relative_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Folder deletion not allowed")
    target.unlink()
    return {"message": "deleted"}


def move_workspace_path(session_id: str, src: str, dst_dir: str = "") -> dict:
    source = resolve_workspace_path(session_id, src)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    target_dir = resolve_workspace_path(session_id, dst_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = uniquify_path(target_dir / source.name)
    shutil.move(str(source), str(target))
    return {
        "message": "moved",
        "new_path": target.relative_to(resolve_workspace_root(session_id)).as_posix(),
    }


def delete_workspace_dir(session_id: str, relative_path: str, recursive: bool = True) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    target = resolve_workspace_path(session_id, relative_path)
    if target == workspace_root:
        raise HTTPException(status_code=400, detail="Cannot delete workspace root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")
    if recursive:
        shutil.rmtree(target)
    else:
        target.rmdir()
    return {"message": "deleted"}


async def proxy_external_file(url: str) -> Response:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Proxy fetch failed: {exc}") from exc

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "application/octet-stream"),
        headers={"Access-Control-Allow-Origin": "*"},
        status_code=response.status_code,
    )


def get_workspace_index(workspace_root: Path) -> dict:
    index_path = workspace_root / "index.json"
    if not index_path.exists():
        return {}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_workspace_index(workspace_root: Path, index_data: dict):
    index_path = workspace_root / "index.json"
    index_path.write_text(json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8")

# --- zip uploads -------------------------------------------------------------------

#: Caps on what a single uploaded archive may expand to. A zip is untrusted input: without
#: these, a small file can expand to fill the disk (zip bomb) or write outside the workspace
#: (zip slip).
_ZIP_MAX_MEMBERS = 20
_ZIP_MAX_TOTAL_BYTES = 500 * 1024 * 1024
_ZIP_MAX_COMPRESSION_RATIO = 200


def _safe_zip_members(archive: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], list[str]]:
    """Select the tabular members of an archive that are safe to extract.

    Args:
        archive: An open ZipFile.

    Returns:
        (members to extract, human-readable reasons for what was skipped).
    """
    members: list[zipfile.ZipInfo] = []
    skipped: list[str] = []
    total = 0
    for info in archive.infolist():
        name = info.filename
        if info.is_dir():
            continue
        # Zip slip: a member may not escape the extraction directory.
        if name.startswith("/") or ".." in Path(name).parts or Path(name).is_absolute():
            skipped.append(f"{name} (đường dẫn không an toàn)")
            continue
        if Path(name).suffix.lower() not in TABULAR_EXTS:
            continue  # quietly ignore READMEs, images, licences
        if info.file_size > _ZIP_MAX_TOTAL_BYTES:
            skipped.append(f"{name} (quá lớn: {info.file_size / 1e6:.0f} MB)")
            continue
        if info.compress_size and info.file_size / info.compress_size > _ZIP_MAX_COMPRESSION_RATIO:
            skipped.append(f"{name} (tỷ lệ nén bất thường, nghi zip bomb)")
            continue
        total += info.file_size
        if total > _ZIP_MAX_TOTAL_BYTES:
            skipped.append(f"{name} (vượt tổng dung lượng cho phép)")
            break
        members.append(info)
        if len(members) >= _ZIP_MAX_MEMBERS:
            break
    return members, skipped


def extract_tabular_from_zip(content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Pull the tabular files out of a zip upload.

    Users routinely upload archives straight from a dataset site. Before this, such an
    upload was stored verbatim and then silently ignored: load_dataset() only reads
    tabular extensions, so the file sat in the workspace and the analysis quietly ran on
    whatever OTHER dataset was newest. The user believed they had supplied their data and
    could not see why the results did not match it.

    Args:
        content: Raw bytes of the uploaded archive.

    Returns:
        ([(member basename, bytes)], [reasons for anything skipped]). Both empty lists
        mean the archive held no tabular file at all.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members, skipped = _safe_zip_members(archive)
            out = []
            for info in members:
                # Flatten: nested directories are irrelevant once registered by file_id.
                out.append((Path(info.filename).name, archive.read(info)))
            return out, skipped
    except zipfile.BadZipFile:
        return [], ["file .zip hỏng hoặc không đọc được"]
    except Exception as e:
        return [], [f"không giải nén được: {e}"]


#: Separators tried when a delimited file is read, best-column-count wins. A ".csv" that
#: is actually tab-separated is common (Kaggle exports one), and reading it with the comma
#: default yields a single column whose name is the entire header line — which is then
#: described to the model as a one-column dataset. Silent, and fatal to the analysis.
_CANDIDATE_SEPARATORS = (",", "\t", ";", "|")


def sniff_separator(path: "Path | str") -> str:
    """Detect a delimited file's separator by which one yields the most columns.

    Args:
        path: File to inspect; only the first rows are read.

    Returns:
        The winning separator, defaulting to "," when nothing parses better.
    """
    best, best_cols = ",", 0
    for sep in _CANDIDATE_SEPARATORS:
        try:
            cols = len(pd.read_csv(path, sep=sep, nrows=5, engine="python").columns)
        except Exception:
            continue
        if cols > best_cols:
            best, best_cols = sep, cols
    return best


async def _save_uploads(
    workspace_root: Path,
    target_dir: Path,
    files: Iterable[UploadFile],
) -> tuple[list[dict], list[str]]:
    saved: list[dict] = []
    rejected: list[str] = []
    
    # Load current index
    index_data = get_workspace_index(workspace_root)
    
    # (filename, bytes) pairs to register. A .zip contributes its tabular members instead
    # of itself, so an archive upload behaves exactly like uploading the file inside it.
    pending: list[tuple[str, bytes]] = []
    for file in files:
        filename = file.filename or "untitled"
        ext = Path(filename).suffix.lower()
        if ext in BLOCKED_UPLOAD_EXTENSIONS:
            rejected.append(filename)
            continue

        content = await file.read()
        if ext == ".zip":
            extracted, skipped = extract_tabular_from_zip(content)
            rejected.extend(f"{filename} -> {reason}" for reason in skipped)
            if not extracted:
                # Never store an archive we cannot read: it would sit in the workspace
                # looking uploaded while load_dataset() ignores it.
                rejected.append(f"{filename} (không chứa file dữ liệu nào: {', '.join(sorted(TABULAR_EXTS))})")
                continue
            print(f"[workspace] '{filename}': giải nén {len(extracted)} file dữ liệu")
            pending.extend(extracted)
        else:
            pending.append((filename, content))

    for filename, content in pending:
        ext = Path(filename).suffix.lower()
        file_id = f"{uuid.uuid4().hex[:8]}"
        new_filename = f"{file_id}_{filename}"
        
        # Save physical file to /Files
        files_dir = workspace_root / "Files"
        files_dir.mkdir(parents=True, exist_ok=True)
        dst = files_dir / new_filename
        
        with open(dst, "wb") as buffer:
            buffer.write(content)
            
        # Extract basic metadata
        metadata = {
            "file_id": file_id,
            "filename": filename,
            "physical_path": f"Files/{new_filename}",
            "size_bytes": len(content),
            "created_at": datetime.datetime.now().isoformat()
        }
        
        # Try to extract pandas schema if it's a CSV
        if ext in [".csv", ".tsv", ".xlsx", ".xls"]:
            try:
                if ext in [".csv", ".tsv"]:
                    sep = sniff_separator(dst)
                    # Recorded so load_dataset() reads the file the same way rather than
                    # guessing from the extension, which is what got this wrong.
                    metadata["separator"] = sep
                    if sep != ("\t" if ext == ".tsv" else ","):
                        print(f"[workspace] '{filename}': separator thực tế là {sep!r}, không khớp đuôi file")
                    df = pd.read_csv(dst, sep=sep, nrows=100, engine="python")
                else:
                    df = pd.read_excel(dst, nrows=100)
                metadata["columns"] = list(df.columns)
                metadata["dtypes"] = {col: str(dt) for col, dt in df.dtypes.items()}
                # Optional: row count might require full read, skipping for performance
            except Exception as e:
                metadata["extraction_error"] = str(e)
                
        # Save metadata to /Metadata
        metadata_dir = workspace_root / "Metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        meta_dst = metadata_dir / f"{file_id}.json"
        meta_dst.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        
        # Only register tabular files in the dataset index (not JSON/images/etc.)
        # This prevents load_dataset() from accidentally picking up metadata files
        TABULAR_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
        if ext in TABULAR_EXTENSIONS:
            index_data[file_id] = {
                "filename": filename,
                "path": f"Files/{new_filename}",
                "metadata_file": f"Metadata/{file_id}.json",
                "created_at": metadata["created_at"]
            }
        
        saved.append(
            {
                "file_id": file_id,
                "name": filename,
                "size": len(content),
                "path": f"Files/{new_filename}",
            }
        )
        
    save_workspace_index(workspace_root, index_data)
    return saved, rejected


TABULAR_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}


def purge_datasets(session_id: str) -> dict:
    """Remove every registered tabular dataset from a workspace, in place.

    Only datasets are removed — generated reports, charts and other outputs are left
    alone, since they are results the user may still want.

    Called before each upload so a new dataset REPLACES the previous one rather than
    joining it. Stale datasets are not merely clutter: while several were registered, the
    model was shown all of their schemas and wrote its analysis against the wrong one
    (a telco column list applied to a retail file). One registered dataset means there is
    nothing to confuse.

    Args:
        session_id: Workspace to purge.

    Returns:
        {"removed": int, "freed_bytes": int}.
    """
    workspace_root = resolve_workspace_root(session_id)
    index_path = workspace_root / "index.json"
    if not index_path.exists():
        return {"removed": 0, "freed_bytes": 0}
    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"removed": 0, "freed_bytes": 0}

    removed, freed = 0, 0
    for file_id, info in list(index_data.items()):
        name = info.get("filename", info.get("path", ""))
        if os.path.splitext(name)[1].lower() not in TABULAR_EXTS:
            continue
        for rel in (info.get("path"), info.get("metadata_file")):
            if not rel:
                continue
            target = workspace_root / rel
            try:
                if target.exists():
                    freed += target.stat().st_size
                    target.unlink()
            except OSError as e:
                print(f"[workspace] could not remove {target}: {e}")
        del index_data[file_id]
        removed += 1

    if removed:
        index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[workspace] purged {removed} dataset(s), freed {freed / 1e6:.1f} MB from '{session_id}'")
    return {"removed": removed, "freed_bytes": freed}


async def upload_files_to_workspace(session_id: str, files: Iterable[UploadFile]) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    # A new upload REPLACES the active dataset instead of stacking on top of it.
    purged = purge_datasets(session_id)
    saved, rejected = await _save_uploads(workspace_root, workspace_root, files)
    return {
        "message": f"Successfully uploaded {len(saved)} files",
        "replaced": purged["removed"],
        "files": saved,
        "rejected": rejected,
    }


async def upload_files_to_dir(session_id: str, directory: str, files: Iterable[UploadFile]) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    target_dir = resolve_workspace_path(session_id, directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    saved, rejected = await _save_uploads(workspace_root, target_dir, files)
    return {"message": f"uploaded {len(saved)}", "files": saved, "rejected": rejected}


def clear_workspace(session_id: str) -> dict:
    workspace_root = resolve_workspace_root(session_id)
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    return {"message": "Workspace cleared successfully"}
