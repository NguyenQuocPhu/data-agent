"""Build the frozen DatasetProfile for a workspace, shared by chat and the convergence loop.

Both paths analyse whatever tabular file a workspace holds, and both need the same frozen
profile: labels for readable persona names, and the churn-column check that decides whether
the generic path applies. Keeping one builder means the two cannot drift — a divergence
here is not cosmetic, it decides whether a non-telco dataset renders as a telco report.

Profiles are fingerprint-keyed on disk, so the LLM-backed enrichment (labels, derived
features) runs once per dataset and every later request is a cache read.
"""
from __future__ import annotations

import json
import os

import pandas as pd

from triadic_dgm.persona.dataset_profile import has_churn_columns, load_or_build_cached

_TABULAR_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}


def selected_dataset_id(workspace_root: str) -> "str | None":
    """Return the file_id the injected ``load_dataset()`` would auto-select.

    Reads only index.json, never the data file. Must mirror the ordering used by the
    injected ``load_dataset()``; if it drifts, staleness checks stop firing.

    Args:
        workspace_root: Absolute path to a session workspace directory.

    Returns:
        The selected file_id, or None when no usable tabular dataset is registered.
    """
    index_path = os.path.join(workspace_root or "", "index.json")
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception:
        return None
    entries = [
        (fid, info) for fid, info in (index_data or {}).items()
        if os.path.splitext(info.get("filename", info.get("path", "")))[1].lower() in _TABULAR_EXTS
    ]
    if not entries:
        return None
    entries.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    return entries[0][0]


def load_dataframe(workspace_root: str) -> "pd.DataFrame | None":
    """Read the workspace's auto-selected tabular dataset. Returns None on any failure."""
    index_path = os.path.join(workspace_root or "", "index.json")
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
        fid = selected_dataset_id(workspace_root)
        if not fid or fid not in index_data:
            return None
        file_path = os.path.join(workspace_root, index_data[fid]["path"])
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".csv", ".tsv"):
            return pd.read_csv(file_path, sep="\t" if ext == ".tsv" else ",")
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(file_path)
    except Exception:
        return None
    return None


def build_label_enricher(config: dict):
    """Return a label_enricher for ``load_or_build_cached``, or None when unavailable."""
    try:
        import instructor
        from openai import OpenAI

        from triadic_dgm.persona.label_inference import infer_column_labels
    except Exception as e:
        print(f"[profile] label inference unavailable: {e}")
        return None

    api_key = config.get("api_key")
    base_url = config.get("base_url_programmer")
    model_name = config.get("programmer_model")
    if not (api_key and model_name):
        return None

    def _enricher(df, profile):
        return infer_column_labels(
            df,
            client_factory=lambda: instructor.from_openai(
                OpenAI(api_key=api_key, base_url=base_url), mode=instructor.Mode.JSON
            ),
            model_name=model_name,
            dataset_name=profile.dataset_name,
            # A dataset that genuinely carries churn columns SHOULD be labelled with telco
            # vocabulary; only one without them would have to invent it.
            allow_domain_terms=has_churn_columns(profile.labels.keys()),
        )

    return _enricher


def build_derived_enricher(config: dict):
    """Return a derived_enricher for ``load_or_build_cached``, or None when unavailable.

    The enricher proposes derived features with an LLM and keeps only those that measurably
    improve the clustering (see :mod:`triadic_dgm.persona.derived_features`).
    """
    try:
        import instructor
        from openai import OpenAI

        from triadic_dgm.persona.derived_features import (
            resulting_feature_list,
            select_derived_features,
        )
        from triadic_dgm.persona.label_inference import propose_derived_features, validate_labels
    except Exception as e:
        print(f"[profile] derived-feature selection unavailable: {e}")
        return None

    api_key = config.get("api_key")
    base_url = config.get("base_url_programmer")
    model_name = config.get("programmer_model")
    if not (api_key and model_name):
        return None

    def _enricher(df, profile):
        base = list(profile.behavioral_features)
        try:
            if len(base) < 2:
                return {}, base, {}
            candidates = propose_derived_features(
                df, base,
                client_factory=lambda: instructor.from_openai(
                    OpenAI(api_key=api_key, base_url=base_url), mode=instructor.Mode.JSON
                ),
                model_name=model_name,
                labels=profile.labels,
            )
            if not candidates:
                return {}, base, {}
            accepted = select_derived_features(df, base, candidates)
            labels = validate_labels(
                {c.name: c.label for c in candidates if c.name in accepted and c.label},
                list(accepted),
                allow_domain_terms=has_churn_columns(profile.labels.keys()),
            )
            return accepted, resulting_feature_list(base, candidates, accepted), labels
        except Exception as e:
            print(f"[profile] derived-feature selection skipped: {e}")
            return {}, base, {}

    return _enricher


def load_profile(workspace_root: str, config: dict, profiles_dir: str, with_derived: bool = True):
    """Load (or build and cache) the DatasetProfile for a workspace's active dataset.

    Args:
        workspace_root: Session workspace directory holding index.json.
        config: Runtime config carrying api_key / programmer_model / base_url_programmer.
        profiles_dir: Directory for fingerprint-keyed profile JSON.
        with_derived: Whether to run derived-feature selection on a cache miss. Off for
            callers that cannot make the sandbox materialise the derived columns.

    Returns:
        A DatasetProfile, or None when no dataset is available or profiling fails.
    """
    try:
        df = load_dataframe(workspace_root)
        if df is None or df.empty:
            return None
        return load_or_build_cached(
            df,
            profiles_dir,
            label_enricher=build_label_enricher(config),
            derived_enricher=build_derived_enricher(config) if with_derived else None,
        )
    except Exception as e:
        print(f"[profile] build failed for {workspace_root}: {e}")
        return None
