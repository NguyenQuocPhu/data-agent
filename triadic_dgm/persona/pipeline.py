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

from triadic_dgm.persona.characterization import name_by_top_feature
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



#: Above this share of zeros across the WHOLE selected matrix, clustering has nothing to
#: separate. Checked on the aggregate only: behavioural data legitimately has individual
#: columns that are 90-99% zero, and treating one sparse column as grounds to abort was a
#: real failure mode.
_MAX_ZERO_FRACTION = 0.99


def _sample_persona_text(name: str, means: dict, global_mean: dict, top_n: int = 3) -> str:
    """One Vietnamese sentence describing a cluster's standout features.

    Consumed by SemanticVerifier (triadic_dgm/agent/verifier.py) and the dashboard, so it
    must always be a non-empty string and must never contain "nan" — a NaN leaking in here
    used to surface verbatim in the UI.
    """
    devs = []
    for f, v in means.items():
        g = global_mean.get(f, 0)
        if not isinstance(v, (int, float)) or v != v:  # NaN-safe
            continue
        dev = (v - g) / abs(g) if g else 0.0
        devs.append((f, dev))
    devs.sort(key=lambda x: -abs(x[1]))
    bits = [
        f"{f} {'cao hơn' if d >= 0 else 'thấp hơn'} trung bình {abs(d) * 100:.0f}%"
        for f, d in devs[:top_n] if abs(d) >= 0.1
    ]
    text = f"{name}: " + ("; ".join(bits) if bits else "không lệch rõ rệt so với mặt bằng chung")
    return text.replace("nan", "0")


def hidden_drivers(X_raw: pd.DataFrame, labels, features: list[str]) -> dict[str, float]:
    """Which raw features actually separate the clusters, via a shallow decision tree.

    Depth and leaf size are capped so a single outlier cannot become a "driver", and
    classes are balanced so small clusters still register. Only features above 5%
    importance are returned — below that the tree is describing noise. Best-effort.

    Args:
        X_raw: Unscaled feature matrix.
        labels: Cluster assignment per row.
        features: Column names matching X_raw.

    Returns:
        Feature -> importance, descending; empty when nothing clears the threshold.
    """
    try:
        from sklearn.tree import DecisionTreeClassifier

        dt = DecisionTreeClassifier(
            max_depth=3, min_samples_leaf=500, class_weight="balanced", random_state=SEED
        )
        dt.fit(X_raw, labels)
        imp = pd.Series(dt.feature_importances_, index=features)
        imp = imp[imp > 0.05].sort_values(ascending=False)
        return {k: round(float(v), 4) for k, v in imp.items()}
    except Exception as e:
        print(f"[PIPELINE] hidden_drivers skipped: {e}")
        return {}


def save_cluster_chart(personas: list[dict], out_dir: str = "workspace/generated/reports") -> str:
    """Write the cluster-size bar chart and return the markdown line that displays it.

    Kept out of run_persona_pipeline because it performs file I/O against a caller-chosen
    path. Best-effort: returns "" if plotting is unavailable, so a missing chart never
    costs the caller its personas.
    """
    try:
        import os

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "cluster_distribution.png")
        plt.figure(figsize=(10, 6))
        sns.barplot(x=[p["persona_name"] for p in personas], y=[p["support"] for p in personas])
        plt.xticks(rotation=45, ha="right")
        plt.title("Cluster Distribution")
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        return f"![Cluster Distribution](/file?path={path})"
    except Exception as e:
        print(f"[PIPELINE] cluster chart skipped: {e}")
        return ""


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


def _auto_features(data: pd.DataFrame, cluster_col: str) -> list[str]:
    """Every numeric column that actually varies — the pipeline's own deterministic choice."""
    numeric = data.select_dtypes(include="number")
    return [c for c in numeric.columns if c != cluster_col and numeric[c].nunique(dropna=True) > 1]


def _prepare_matrix(data: pd.DataFrame, feats: list[str]):
    """Coerce ``feats`` to a scaled matrix, or None if the set cannot be clustered on.

    Returns None rather than raising so a candidate feature set that turns out unusable
    (too few columns, almost entirely zeros) simply loses the comparison.
    """
    if len(feats) < 2:
        return None
    raw = data[feats].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if float((raw == 0).to_numpy().mean()) > _MAX_ZERO_FRACTION:
        return None
    return raw, StandardScaler().fit_transform(raw.to_numpy(dtype=float))


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
        "sample_persona_text": f"Không phân hoá được nhóm ({reason}).",
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

    # A caller that names features is making a claim about this dataset's schema. Check it
    # instead of quietly repairing it: the old code filtered the list down to whatever
    # existed and auto-selected when nothing did, so a feature list copied from a DIFFERENT
    # dataset still produced a confident, plausible report. Observed live — a model emitted
    # Iris column names for a retail upload, all four were dropped, and the run "succeeded".
    if behavioral_features:
        missing = [f for f in behavioral_features if f not in data.columns]
        if missing:
            return _failed_persona(
                data,
                f"unknown_columns: {', '.join(missing)} — không tồn tại trong dataset này "
                f"(các cột thực có: {', '.join(map(str, data.columns[:20]))}"
                f"{'…' if len(data.columns) > 20 else ''})",
            )
        non_numeric = [f for f in behavioral_features if not pd.api.types.is_numeric_dtype(data[f])]
        if non_numeric:
            return _failed_persona(
                data,
                f"non_numeric_columns: {', '.join(non_numeric)} — tồn tại nhưng không phải "
                f"kiểu số, không dùng để phân cụm được",
            )

    mode = dataset_mode or detect_dataset_mode(data.columns)
    auto_feats = _auto_features(data, cluster_col)
    caller_feats = list(behavioral_features or [])

    # On GENERIC data the pipeline picks the features, not the caller.
    #
    # The caller is an LLM improvising a list per run. Two runs over the same 50k file gave
    # silhouette 0.426 (12 features) and 0.286 (9 features) — one dataset, two segmentations,
    # the second a third worse purely because the model named fewer columns that time. The
    # pipeline's own selection scored 0.426, matching the model's best attempt.
    #
    # Scoring both and keeping the higher silhouette was tried and rejected: silhouette
    # measures how compact the partition it FOUND is, not whether that structure is real, so
    # two pure-noise columns scored 0.351 against 0.308 for a set containing the actual
    # signal. A measure that prefers noise cannot arbitrate.
    #
    # So the deterministic rule wins: use every numeric column that varies. Callers wanting a
    # subset filter the DataFrame before calling, which is what the prompt already instructs.
    # The caller's list is still validated above — catching a list copied from another
    # dataset is its real value — and what was actually used is recorded on every persona.
    #
    # Unchanged on the telco path: there the column list carries domain meaning, and that
    # path is deliberately left exactly as it was.
    if mode == "GENERIC" and auto_feats:
        feats, feature_selection = auto_feats, "auto"
        if caller_feats and caller_feats != auto_feats:
            print(f"[PIPELINE] feature set: bỏ qua {len(caller_feats)} feature do caller đề xuất, "
                  f"dùng {len(auto_feats)} cột số biến thiên của dataset (tất định)")
    else:
        feats = caller_feats or auto_feats
        feature_selection = "caller" if caller_feats else "auto"

    if len(feats) < 2:
        return _failed_persona(data, "insufficient_numeric_features")
    prepared = _prepare_matrix(data, feats)
    if prepared is None:
        zero_fraction = float(
            (data[feats].apply(pd.to_numeric, errors="coerce").fillna(0.0) == 0).to_numpy().mean()
        )
        return _failed_persona(data, f"zero_inflated_{zero_fraction:.3f}")
    X_raw, X = prepared

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
            # "caller" = the feature list supplied to this call was used; "auto" = the
            # pipeline's own selection scored better and replaced it. Surfaced so a reader
            # can see WHICH set produced the segmentation in front of them.
            "feature_selection": feature_selection,
            "features_used": list(feats),
            "recommended_actions": generate_actions(mode, name, meta["severity"], meta["risk"], profile),
            "sample_persona_text": _sample_persona_text(name, means, global_mean),
        })

    # Name generic personas from their own measured deviations, HERE rather than in the
    # report renderer. The rule engine's ladder is entirely telco predicates, so on any other
    # dataset every cluster fell to one fallback string: a real 50k-row retail upload came
    # out as "Khách hàng ổn định - Nhóm 1..4". The report looked right only because it
    # re-named personas itself; the dashboard, feed and database all showed the four
    # identical names. Anomalies keep their own label, and the report may still upgrade a raw
    # column name to a human one.
    if mode == "GENERIC":
        generic_names = name_by_top_feature(personas, global_mean)
        for p, new_name in zip(personas, generic_names):
            if new_name and not p["is_anomaly"]:
                p["persona_name"] = new_name
                p["sample_persona_text"] = _sample_persona_text(
                    new_name, p["feature_means"], global_mean
                )
        deduped = _dedupe_names({p["cluster_id"]: p["persona_name"] for p in personas})
        for p in personas:
            p["persona_name"] = deduped[p["cluster_id"]]

    drivers = hidden_drivers(X_raw, data[cluster_col], feats)
    if drivers:
        print("[PIPELINE] hidden drivers (>5% importance): " + ", ".join(
            f"{k}={v}" for k, v in drivers.items()))
    else:
        print("[PIPELINE] hidden drivers: không feature nào vượt 5% importance")

    print(
        f"[PIPELINE] mode={mode} k={len(cluster_sizes)} silhouette={best_sil:.3f} "
        f"dominant={dominant_pct * 100:.1f}% quality={quality} features={len(feats)}"
    )
    return personas
