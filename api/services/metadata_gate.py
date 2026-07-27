"""Decide whether a data dictionary on disk describes the dataset actually loaded.

The chat route appends any ``*metadata*.json`` it finds to the user's message, telling the
model to obey it strictly. That is a genuinely useful feature — a column dictionary is
exactly what an analyst wants the model to have — but it was ungated, so a dictionary left
in the repository from an earlier project was handed to every later analysis.

The gate here is a *match* test, not a vocabulary test. A dictionary is wrong for this run
when it describes columns the loaded dataframe does not have, whatever domain it belongs
to; that also protects a third dataset from a second one's dictionary, which a hardcoded
vocabulary list never would.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any, Iterable, Sequence

#: Share of a dictionary's described columns that must exist in the active dataset before
#: it is considered to describe that dataset. Half is deliberately lenient — dictionaries
#: routinely document only the interesting columns, and may be written before a
#: preprocessing step drops some — while still rejecting a wholly foreign schema, whose
#: overlap is normally zero and at most a stray ``customer_id``.
MIN_COLUMN_OVERLAP: float = 0.5


def described_columns(metadata: Any) -> set[str]:
    """Extract the set of column names a data dictionary describes, lowercased.

    Handles the three shapes this repository produces and consumes:
    a list of ``{"column": ...}`` / ``{"name": ...}`` entries (what ``generate_metadata.py``
    writes), a ``{"columns": [...]}`` wrapper whose entries are strings or dicts, and a
    plain ``{column: description}`` mapping.

    Args:
        metadata: Parsed JSON of a metadata file.

    Returns:
        Lowercased column names; empty if the shape is unrecognised.
    """
    def _name(entry: Any) -> str | None:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            for key in ("column", "name", "field", "col"):
                value = entry.get(key)
                if isinstance(value, str):
                    return value
        return None

    entries: Iterable[Any]
    if isinstance(metadata, list):
        entries = metadata
    elif isinstance(metadata, dict):
        inner = metadata.get("columns") or metadata.get("fields")
        if isinstance(inner, list):
            entries = inner
        else:
            # A plain {column: description} mapping. Values are descriptions, not columns.
            entries = list(metadata)
    else:
        return set()

    return {n.strip().lower() for n in map(_name, entries) if n and n.strip()}


def describes_active_dataset(metadata: Any, active_columns: Sequence[str] | None,
                             min_overlap: float = MIN_COLUMN_OVERLAP) -> bool:
    """Report whether ``metadata`` documents the dataset currently loaded.

    Args:
        metadata: Parsed JSON of a metadata file.
        active_columns: Columns of the active dataset. ``None`` (the column peek failed)
            and ``[]`` (nothing readable is registered) both answer False: an unverifiable
            dictionary is precisely the case that caused the bug, and staying silent costs
            the model only a description — it still has the real dataframe in hand.
        min_overlap: Required share of described columns present in the dataset.

    Returns:
        True only when the dictionary is provably about this data.
    """
    if not active_columns:
        return False
    described = described_columns(metadata)
    if not described:
        return False
    present = {str(c).strip().lower() for c in active_columns}
    return len(described & present) / len(described) >= min_overlap


def collect_matching_metadata(search_dir: str, active_columns: Sequence[str] | None) -> str:
    """Gather the metadata files in ``search_dir`` that describe the active dataset.

    Args:
        search_dir: Directory to scan for ``*metadata*.json`` (non-recursive).
        active_columns: Columns of the active dataset, or None if unknown.

    Returns:
        A block of text ready to append to the prompt, or "" when nothing matches. A
        malformed or unreadable file is skipped rather than raised on — a broken file left
        in the working directory must not take the chat endpoint down.
    """
    if not active_columns:
        return ""

    blocks: list[str] = []
    for path in sorted(glob.glob(os.path.join(search_dir, "*metadata*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            parsed = json.loads(raw)
        except (OSError, ValueError):
            continue
        if not describes_active_dataset(parsed, active_columns):
            continue
        blocks.append(f"\n--- Metadata từ file: {os.path.basename(path)} ---\n{raw}\n")

    return "".join(blocks)
