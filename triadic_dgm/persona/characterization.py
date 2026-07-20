"""Generic, unsupervised cluster characterization for the persona pipeline.

Computes, for each cluster, a `distinguishing_signal`: which behavioral domain
stands out most (by cluster-vs-global feature deviation), the top deviating
features with their human labels, and a short evidence sentence — all derived
from the active DatasetProfile's domains/labels, with NO churn/telco vocabulary.

This is ADDITIVE: it attaches a new `distinguishing_signal` field and never
touches the legacy telco fields (`churn_driver`, `domain_signature`), which the
report/feed/UI/DB still consume until Phase 3 cuts them over.
"""
from __future__ import annotations

from typing import Callable


def stars_from_max_dev(max_dev: float) -> int:
    """Map a domain's max signed relative deviation to a 1-5 star rating.

    Mirrors the thresholds used by the legacy telco path so ratings stay
    comparable. Deviation below the global average (negative) is never a
    "signal" and floors at 1 star.

    Args:
        max_dev: Max signed relative deviation (v-g)/|g| across a domain's
            columns, already floored at 0 by the caller for below-average.

    Returns:
        Star rating in the range 1-5 (higher = more distinctive).
    """
    if max_dev >= 5.0:
        return 5
    if max_dev >= 2.0:
        return 4
    if max_dev >= 0.75:
        return 3
    if max_dev >= 0.25:
        return 2
    return 1


def compute_domain_stars(
    means: dict, global_means: dict, domains: dict[str, list[str]]
) -> dict[str, dict]:
    """Rate each domain by how far its columns deviate above the global mean.

    Args:
        means: This cluster's per-feature mean values.
        global_means: Whole-dataset per-feature mean values.
        domains: Domain name -> member column list (from DatasetProfile.domains).

    Returns:
        Domain name -> {"stars": int, "max_dev": float}.
    """
    signature: dict[str, dict] = {}
    for dom, cols in domains.items():
        max_dev = 0.0
        for f in cols:
            v = means.get(f)
            if not isinstance(v, (int, float)):
                continue
            g = global_means.get(f, 0)
            dev = (v - g) / abs(g) if g else 0.0
            if dev > max_dev:
                max_dev = dev
        signature[dom] = {"stars": stars_from_max_dev(max_dev), "max_dev": round(max_dev, 4)}
    return signature


def _top_features(means: dict, global_means: dict, labels: dict, top_n: int = 3) -> list[dict]:
    devs: list[tuple[str, float]] = []
    for f, v in means.items():
        if not isinstance(v, (int, float)):
            continue
        g = global_means.get(f, 0)
        dev = (v - g) / abs(g) if g else 0.0
        devs.append((str(f), dev))
    devs.sort(key=lambda x: abs(x[1]), reverse=True)
    return [
        {"feature": f, "label": labels.get(f, f), "deviation": round(d, 4)}
        for f, d in devs[:top_n]
    ]


def distinguishing_signal(
    means: dict,
    global_means: dict,
    domains: dict[str, list[str]],
    labels: dict[str, str] | None = None,
) -> dict:
    """Describe what makes a cluster distinct, generically (no churn vocabulary).

    Args:
        means: This cluster's per-feature mean values.
        global_means: Whole-dataset per-feature mean values.
        domains: Domain name -> member column list (DatasetProfile.domains).
        labels: Column -> human label (DatasetProfile.labels); optional.

    Returns:
        {"dominant_domain": str | None, "stars": dict, "top_features": list,
         "evidence": str}. `evidence` is a short, dataset-neutral sentence built
        from the top deviating features' labels.
    """
    labels = labels or {}
    stars = compute_domain_stars(means, global_means, domains)
    top = _top_features(means, global_means, labels)
    if not stars:
        return {"dominant_domain": None, "stars": stars, "top_features": top, "evidence": ""}

    dominant = max(stars, key=lambda d: (stars[d]["stars"], stars[d]["max_dev"]))
    dom_stars = stars[dominant]["stars"]

    if dom_stars <= 2:
        evidence = "Nhóm này không có tín hiệu hành vi nào nổi bật rõ rệt so với mặt bằng chung."
    else:
        bits = [
            f"{t['label']} ({'+' if t['deviation'] >= 0 else ''}{t['deviation'] * 100:.0f}% so với trung bình)"
            for t in top
            if abs(t["deviation"]) >= 0.1
        ]
        if bits:
            evidence = f"Nhóm nổi bật nhất ở '{dominant}': " + "; ".join(bits) + "."
        else:
            evidence = f"Nhóm nổi bật nhất ở nhóm chỉ số '{dominant}'."

    return {"dominant_domain": dominant, "stars": stars, "top_features": top, "evidence": evidence}


def characterize_personas(
    personas: list[dict],
    global_means: dict,
    profile,
    means_getter: Callable[[dict], dict] | None = None,
) -> None:
    """Attach a generic `distinguishing_signal` to each persona, in place.

    ADDITIVE and best-effort: never raises, never touches legacy telco fields.
    A degenerate persona (e.g. feature_means is a string) is skipped, not fatal.

    Args:
        personas: Persona dicts to mutate.
        global_means: Whole-dataset per-feature means.
        profile: Active DatasetProfile (uses `.domains` and `.labels`).
        means_getter: Optional callable to extract a persona's feature means;
            defaults to reading `feature_means`/`evidence` off the dict.
    """
    if not personas or profile is None:
        return
    domains = getattr(profile, "domains", {}) or {}
    labels = getattr(profile, "labels", {}) or {}
    for p in personas:
        try:
            means = means_getter(p) if means_getter else (p.get("feature_means") or p.get("evidence") or {})
            if not isinstance(means, dict) or not means:
                continue
            p["distinguishing_signal"] = distinguishing_signal(means, global_means, domains, labels)
        except Exception:
            continue


def compose_signal_narrative(persona: dict) -> str:
    """Generic, deterministic persona narrative derived from its distinguishing_signal.

    Dataset-agnostic — no churn/telco vocabulary. States group size and the
    standout evidence already computed (with embedded labels). Best-effort:
    returns "" when no usable signal is present, never raises.

    Args:
        persona: A persona dict expected to carry a "distinguishing_signal".

    Returns:
        A short Vietnamese description, or "" if the signal is missing/empty.
    """
    try:
        sig = persona.get("distinguishing_signal")
        if not isinstance(sig, dict) or not sig:
            return ""
        parts: list[str] = []
        support = persona.get("support")
        pct = persona.get("support_pct")
        pct_str = f"{pct * 100:.1f}%" if isinstance(pct, (int, float)) else None
        size_bits = [
            b
            for b in (
                pct_str and f"khoảng {pct_str} tổng thể",
                support and f"~{support:,} bản ghi".replace(",", "."),
            )
            if b
        ]
        if size_bits:
            parts.append(f"Nhóm này chiếm {' — '.join(size_bits)}.")
        evidence = str(sig.get("evidence") or "").strip()
        if evidence:
            parts.append(evidence)
        return " ".join(parts)
    except Exception:
        return ""
