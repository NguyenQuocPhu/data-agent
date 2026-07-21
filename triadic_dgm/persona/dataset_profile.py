"""Auto-inferred, dataset-agnostic profile for the persona pipeline.

Replaces the hardcoded telco/churn couplings (FIXED_BEHAVIORAL_FEATURES,
_DOMAIN_KEYWORD_GROUPS, data_processed_t4_metadata.json). A DatasetProfile is
built ONCE per dataset — keyed by a fingerprint of its columns + row count —
frozen to cache/convergence/profiles/<fingerprint>.json and reloaded on later
runs, so the convergence loop sees a stable feature space (reproducible
clustering) for ANY dataset, not just the telco one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

# Column-name tokens that denote identifiers/keys, never behavioral signals.
_ID_NAME_RE = re.compile(
    r"(^|_)(id|uuid|guid|code|msisdn|phone|account|contract|customer|index)(_|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DatasetProfile:
    """Immutable, auto-inferred description of the active dataset.

    Attributes:
        dataset_name: Human-facing dataset name (from metadata or file stem).
        fingerprint: Stable hash of (sorted columns, row count); the cache key.
        labels: Map of raw column name -> human-readable label (any language).
        behavioral_features: Frozen, sorted numeric feature list for clustering.
        domains: Generic domain root -> member columns (auto-grouped by name).
    """

    dataset_name: str
    fingerprint: str
    labels: dict[str, str]
    behavioral_features: list[str]
    domains: dict[str, list[str]]

    def label(self, column: str) -> str:
        """Return the human label for a column, falling back to the raw name."""
        return self.labels.get(column, column)


def compute_fingerprint(columns, n_rows: int) -> str:
    """Stable 16-hex-char id derived from the dataset's columns + row count.

    Args:
        columns: Sequence of column names (order irrelevant; will be sorted).
        n_rows: Number of rows in the dataset.

    Returns:
        A 16-character hexadecimal string uniquely identifying this dataset structure.
    """
    raw = json.dumps([sorted(map(str, columns)), int(n_rows)], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def build_metadata(df: pd.DataFrame, dataset_name: str = "dataset") -> dict:
    """Auto-generate column metadata from a DataFrame.

    Generalizes the old generate_metadata.py. Descriptions default to the column
    name, so a dataset with no curated labels still yields a usable profile.

    Args:
        df: Input DataFrame to introspect.
        dataset_name: Human-facing name for the dataset (default: "dataset").

    Returns:
        A dictionary with keys "dataset_name" and "columns" (list of column metadata dicts).
    """
    columns: list[dict] = []
    for col in df.columns:
        series = df[col]
        non_null = series.dropna()
        sample = "" if non_null.empty else str(non_null.iloc[0])
        dtype = "string"
        if pd.api.types.is_integer_dtype(series):
            dtype = "int"
        elif pd.api.types.is_float_dtype(series):
            dtype = "float"
        columns.append(
            {"column": str(col), "type": dtype, "sample": sample, "description": str(col)}
        )
    return {"dataset_name": dataset_name, "columns": columns}


def _labels_from_metadata(metadata: dict) -> dict[str, str]:
    """Extract human-readable labels from metadata column descriptions."""
    return {
        c["column"]: (c.get("description") or c["column"])
        for c in metadata.get("columns", [])
        if c.get("column")
    }


def select_behavioral_features(df: pd.DataFrame) -> list[str]:
    """Pick numeric, non-identifier, non-constant, low-missing columns.

    Returns a sorted list for a stable, reproducible feature order.

    Args:
        df: Input DataFrame to analyze.

    Returns:
        Sorted list of column names suitable for behavioral clustering.
    """
    numeric = df.select_dtypes(include="number")
    n = len(df)
    features: list[str] = []
    for col in numeric.columns:
        name = str(col)
        if _ID_NAME_RE.search(name):
            continue
        series = numeric[col]
        if series.nunique(dropna=True) <= 1:  # constant / all-null
            continue
        if n and series.isna().mean() > 0.5:  # >50% missing
            continue
        features.append(name)
    return sorted(features)


def _feature_root(feature: str) -> str:
    """Collapse aggregation suffixes/prefixes so near-collinear columns
    (call_total_6m, call_avg_6m, call_std ...) share one domain root."""
    r = str(feature).lower()
    r = re.sub(r"_(total|avg|std|trend|cv|ratio|count|sum|mean|min|max)(_6m)?$", "", r)
    r = re.sub(r"^(active|old|recent|no|num|n)_", "", r)
    r = re.sub(r"_(months|6m)$", "", r)
    return r or str(feature).lower()


def infer_domains(features: list[str]) -> dict[str, list[str]]:
    """Group features by shared root token.

    Domain names come from the dataset's own column names (generic), never a
    hardcoded telco domain list.

    Args:
        features: List of behavioral feature column names.

    Returns:
        Mapping from domain root (str) to list of member feature names.
    """
    domains: dict[str, list[str]] = {}
    for f in features:
        domains.setdefault(_feature_root(f), []).append(f)
    return domains


def build_profile(
    df: pd.DataFrame, metadata: dict | None = None, dataset_name: str = "dataset"
) -> DatasetProfile:
    """Build a DatasetProfile from a DataFrame (+ optional curated metadata).

    Args:
        df: Input DataFrame to profile.
        metadata: Optional curated metadata dict (see build_metadata). If None, auto-generated.
        dataset_name: Human-facing dataset name (default: "dataset").

    Returns:
        An immutable DatasetProfile with computed features and domains.
    """
    if metadata is None:
        metadata = build_metadata(df, dataset_name=dataset_name)
    name = metadata.get("dataset_name", dataset_name)
    labels = _labels_from_metadata(metadata)
    features = select_behavioral_features(df)
    domains = infer_domains(features)
    fingerprint = compute_fingerprint(list(df.columns), len(df))
    return DatasetProfile(name, fingerprint, labels, features, domains)


def _to_dict(profile: DatasetProfile) -> dict:
    """Serialize a DatasetProfile to a JSON-compatible dictionary."""
    return {
        "dataset_name": profile.dataset_name,
        "fingerprint": profile.fingerprint,
        "labels": profile.labels,
        "behavioral_features": profile.behavioral_features,
        "domains": profile.domains,
    }


def _from_dict(data: dict) -> DatasetProfile:
    """Deserialize a DatasetProfile from a JSON-compatible dictionary."""
    return DatasetProfile(
        dataset_name=data["dataset_name"],
        fingerprint=data["fingerprint"],
        labels=dict(data.get("labels", {})),
        behavioral_features=list(data.get("behavioral_features", [])),
        domains={k: list(v) for k, v in data.get("domains", {}).items()},
    )


def load_or_build_cached(
    df: pd.DataFrame,
    cache_dir: str,
    metadata: dict | None = None,
    dataset_name: str = "dataset",
) -> DatasetProfile:
    """Return the frozen profile for this dataset, building + caching on first sight.

    The fingerprint-keyed cache is what keeps the behavioral feature set STABLE
    across convergence runs — the reproducibility mechanism that replaces the old
    hardcoded FIXED_BEHAVIORAL_FEATURES.

    Args:
        df: Input DataFrame to profile.
        cache_dir: Directory path where fingerprint-keyed profiles are stored.
        metadata: Optional curated metadata dict.
        dataset_name: Human-facing dataset name (default: "dataset").

    Returns:
        A DatasetProfile, either loaded from cache or newly built and cached.
    """
    fingerprint = compute_fingerprint(list(df.columns), len(df))
    path = os.path.join(cache_dir, f"{fingerprint}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _from_dict(json.load(f))
        except (OSError, json.JSONDecodeError, KeyError):
            pass  # corrupt cache -> rebuild below
    profile = build_profile(df, metadata=metadata, dataset_name=dataset_name)
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_dict(profile), f, ensure_ascii=False, indent=2)
    return profile


_CHURN_TARGET_TOKENS = ("rmdt", "churn")


def has_churn_columns(columns: Iterable[str]) -> bool:
    """Detect whether a dataset carries a telco-churn / target signal.

    Used to decide (deterministically, in Python) whether the persona pipeline
    should keep the legacy telco churn path for this dataset or enforce the
    generic, dataset-agnostic path. This is the enforcement predicate for
    Phase 4 — the prompt's own mode guess is only soft steering.

    Args:
        columns: Iterable of raw column names (any case).

    Returns:
        True if a churn/target column is present (name contains ``rmdt`` or
        ``churn``) OR the dataset has paired temporal ``old_*`` and ``recent_*``
        behavioral columns (the churn-trajectory signature the telco path needs);
        False otherwise (treat as a generic dataset).
    """
    cols = [str(c).lower() for c in columns]
    if any(tok in c for c in cols for tok in _CHURN_TARGET_TOKENS):
        return True
    has_old = any(c.startswith("old_") or "_old" in c for c in cols)
    has_recent = any(c.startswith("recent_") or "_recent" in c for c in cols)
    return has_old and has_recent
