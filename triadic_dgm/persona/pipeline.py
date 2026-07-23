"""One fixed entry point for the persona pipeline's core.

Everything from "pick features" to "emit persona dicts" used to live as prose + code inside
``PROGRAMMER_PROMPT_V2``, retyped by the sandbox LLM on every run. That made the core
non-deterministic (same data, different code), untestable (it was a string), and fragile
under repair: any error sent the loop rewriting the script from memory, drifting further
each retry until the retries ran out and the user got no report at all.

This module is the "fixed core" half of that split. The LLM no longer writes clustering or
rule-engine code; it calls :func:`run_persona_pipeline` and keeps doing what actually needs
language — interpreting and narrating the result. It may still write extra code around this
call for a request the default path does not cover.

The rule-engine, profiling and Stage-2 functions this orchestrates were ported verbatim, so
the telco path is unchanged. What is new is that the ORDER of steps is now code instead of
instructions the model may reorder, skip or half-apply.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from triadic_dgm.persona.clustering import try_substage_cluster
from triadic_dgm.persona.profiling import (
    compute_churn_drivers,
    compute_domain_signature,
    compute_profile_attributes,
    compute_profile_global_means,
)
from triadic_dgm.persona.rules import apply_business_rules, classify_risk_tier, generate_actions

SEED = 42
_K_RANGE = (3, 7)
_SILHOUETTE_SAMPLE = 5000

#: Above this share in one cluster, the split carries no information and the run is reported
#: as failed rather than dressed up as three personas that are really one.
_HARD_STOP_DOMINANT = 0.8
#: Above this share, Stage-2 is attempted on the dominant cluster first.
_STAGE2_TRIGGER = 0.5


def detect_dataset_mode(columns) -> str:
    """Classify the dataset without guessing beyond what the columns prove.

    GENERIC is the safe default. POST_CHURN needs paired ``old_*``/``recent_*`` columns (the
    before/after churn signature); PRE_CHURN needs an explicit churn target. Historic fee or
    ARPU columns are NOT evidence of an active customer base — they exist perfectly well in a
    set of customers who have already left, and treating them as evidence produced the
    nonsense of scoring "future churn risk" for people who had already churned.

    Args:
        columns: The dataset's column names.

    Returns:
        One of "PRE_CHURN", "POST_CHURN", "GENERIC".
    """
    lower = [str(c).lower() for c in columns]
    if "rmdt" in lower:
        return "PRE_CHURN"
    has_old = any(c.startswith("old_") for c in lower)
    has_recent = any(c.startswith("recent_") for c in lower)
    if has_old and has_recent:
        return "POST_CHURN"
    return "GENERIC"


def choose_k(X: np.ndarray, k_range: tuple[int, int] = _K_RANGE) -> tuple[int, float, np.ndarray]:
    """Pick the k with the best silhouette over ``k_range``.

    Args:
        X: Scaled feature matrix.
        k_range: Half-open (min_k, max_k) range to search.

    Returns:
        (best_k, best_silhouette, labels).
    """
    best = (k_range[0], -1.0, None)
    for k in range(*k_range):
        if k >= len(X):
            break
        labels = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit_predict(X)
        if len(set(labels)) < 2:
            continue
        score = float(silhouette_score(X, labels, sample_size=min(_SILHOUETTE_SAMPLE, len(X)), random_state=SEED))
        if score > best[1]:
            best = (k, score, labels)
    if best[2] is None:  # degenerate data: one cluster for everything
        best = (1, -1.0, np.zeros(len(X), dtype=int))
    return best


def segmentation_quality(silhouette: float, dominant_pct: float) -> str:
    """Label the split's usefulness: OUTLIER_DRIVEN, WEAK or NORMAL."""
    if silhouette > 0.7 and dominant_pct > 0.8:
        return "OUTLIER_DRIVEN"
    if silhouette < 0.15:
        return "WEAK"
    return "NORMAL"


def _dedupe_names(base_names: dict) -> dict:
    """Suffix repeated persona names so two clusters never render identically."""
    counts = Counter(base_names.values())
    seen: dict[str, int] = {}
    final = {}
    for cid, name in base_names.items():
        if counts[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            final[cid] = f"{name} - Nhóm {seen[name]}"
        else:
            final[cid] = name
    return final


def _failed_persona(data: pd.DataFrame, reason: str) -> list[dict]:
    """The single persona emitted when the data genuinely does not split.

    Worth emitting rather than raising: the report layer needs valid JSON, and a stated
    failure is more useful than an exception the repair loop will chase. The wording stays
    dataset-neutral — the previous version blamed "khách hàng" and asserted the dataset
    lacked variance, which was wrong whenever the real cause was a missing column set.
    """
    n = len(data)
    return [{
        "cluster_id": 0,
        "persona_name": "Không phân hoá được nhóm",
        "support": int(n),
        "support_pct": 1.0,
        "confidence": "LOW",
        "persona_type": "MAINSTREAM",
        "severity": None,
        "risk": None,
        "risk_tier": None,
        "priority_score": 10,
        "feature_means": {},
        "evidence": {},
        "profile_attributes": {},
        "domain_signature": {},
        "temporal_trajectory": [],
        "segmentation_quality": "WEAK",
        "recommended_actions": [
            "Thu thập thêm biến mô tả hành vi để phân nhóm hiệu quả hơn",
        ],
        "is_anomaly": False,
        "failure_reason": reason,
    }]


def run_persona_pipeline(
    data: pd.DataFrame,
    behavioral_features: list[str] | None = None,
    dataset_mode: str | None = None,
    cluster_col: str = "cluster",
) -> list[dict[str, Any]]:
    """Cluster ``data`` and return the persona dicts the report layer consumes.

    Deterministic for a given (data, features): fixed seed, fixed k search, fixed rule
    engine. Mutates ``data`` only by adding ``cluster_col``.

    Args:
        data: The dataset, one row per entity.
        behavioral_features: Columns to cluster on. Defaults to every numeric column with
            more than one distinct value.
        dataset_mode: Override for :func:`detect_dataset_mode`.
        cluster_col: Name of the cluster-label column to add.

    Returns:
        A list of persona dicts. On a genuinely unsplittable dataset, a single persona
        describing that outcome — never an exception, because the caller needs valid JSON.
    """
    if data is None or len(data) == 0:
        return _failed_persona(pd.DataFrame(), "empty_dataset")

    feats = [
        f for f in (behavioral_features or [])
        if f in data.columns and pd.api.types.is_numeric_dtype(data[f])
    ]
    if not feats:
        numeric = data.select_dtypes(include="number")
        feats = [c for c in numeric.columns if c != cluster_col and numeric[c].nunique(dropna=True) > 1]
    if len(feats) < 2:
        return _failed_persona(data, "insufficient_numeric_features")

    mode = dataset_mode or detect_dataset_mode(data.columns)
    X_raw = data[feats].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    X = StandardScaler().fit_transform(X_raw.to_numpy(dtype=float))

    best_k, best_sil, labels = choose_k(X)
    data[cluster_col] = labels

    sizes = data[cluster_col].value_counts()
    dominant_pct = float(sizes.max()) / len(data)

    stage2_triggered = False
    if dominant_pct > _STAGE2_TRIGGER:
        dominant_cid = int(sizes.idxmax())
        data, stage2_triggered, stage2_info = try_substage_cluster(data, dominant_cid, cluster_col=cluster_col)
        print(f"[STAGE-2] cluster {dominant_cid} ({dominant_pct * 100:.1f}%): {stage2_info}")
        sizes = data[cluster_col].value_counts()
        dominant_pct = float(sizes.max()) / len(data)

    if dominant_pct > _HARD_STOP_DOMINANT and not stage2_triggered:
        return _failed_persona(data, f"dominant_cluster_{dominant_pct:.2f}")

    cluster_sizes = sizes.sort_index().to_dict()
    quality = segmentation_quality(best_sil, dominant_pct)

    profile_attributes = compute_profile_attributes(data, cluster_col=cluster_col)
    profile_global = compute_profile_global_means(profile_attributes, cluster_sizes)
    domain_sig = compute_domain_signature(data, cluster_col=cluster_col)
    churn_drivers = (
        compute_churn_drivers(data, domain_sig, cluster_col=cluster_col)
        if mode == "POST_CHURN" else {}
    )

    cluster_stats = data.groupby(cluster_col)[feats].mean()
    global_mean = {f: float(X_raw[f].mean()) for f in feats}

    metadata, base_names = {}, {}
    for cid, row in cluster_stats.iterrows():
        support_pct = cluster_sizes[cid] / len(data)
        meta = apply_business_rules(
            row.to_dict(), support_pct, profile_attributes.get(cid, {}), profile_global,
            mode, churn_drivers.get(cid, {}), domain_sig.get(cid, {}),
        )
        metadata[cid] = meta
        base_names[cid] = meta["persona_name"]
    final_names = _dedupe_names(base_names)

    personas: list[dict[str, Any]] = []
    for cid in sorted(cluster_sizes):
        meta = metadata[cid]
        means = {k: float(v) for k, v in cluster_stats.loc[cid].to_dict().items()}
        profile = profile_attributes.get(cid, {})
        evidence = {
            f: round(v, 4) for f, v in means.items()
            if (global_mean.get(f, 0) and abs(v - global_mean[f]) / abs(global_mean[f]) >= 0.2)
            or (not global_mean.get(f, 0) and v > 0)
        }
        is_anomaly = meta["persona_type"] == "ANOMALY"
        name = "Hành vi bất thường" if is_anomaly else final_names[cid]
        personas.append({
            "cluster_id": int(cid),
            "support": int(cluster_sizes[cid]),
            "support_pct": cluster_sizes[cid] / len(data),
            "feature_means": means,
            "evidence": evidence or means,
            "persona_type": meta["persona_type"],
            "severity": meta["severity"],
            "risk": meta["risk"],
            "persona_name": name,
            "priority_score": meta["priority_score"],
            "confidence": "LOW" if is_anomaly else "HIGH",
            "churn_driver": meta.get("churn_driver"),
            "churn_driver_evidence": meta.get("churn_driver_evidence"),
            "churn_driver_confidence": meta.get("churn_driver_confidence"),
            "temporal_trajectory": meta.get("temporal_trajectory", []),
            "onset_sequence": churn_drivers.get(cid, {}).get("onset_sequence", []),
            "domain_signature": domain_sig.get(cid, {}),
            "profile_attributes": profile,
            "risk_tier": classify_risk_tier(meta, profile),
            "is_anomaly": is_anomaly,
            "segmentation_quality": quality,
            "recommended_actions": generate_actions(mode, name, meta["severity"], meta["risk"], profile),
        })

    print(
        f"[PIPELINE] mode={mode} k={len(cluster_sizes)} silhouette={best_sil:.3f} "
        f"dominant={dominant_pct * 100:.1f}% quality={quality} features={len(feats)}"
    )
    return personas
