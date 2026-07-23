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

from triadic_dgm.persona.dataset_profile import DatasetProfile
from triadic_dgm.persona.vocabulary import GENERIC_FALLBACK_ACTIONS


def stars_from_max_dev(max_dev: float) -> int:
    """Map a domain's largest relative deviation to a 1-5 star rating.

    Mirrors the thresholds used by the legacy telco path so ratings stay
    comparable. Rated on MAGNITUDE: being distinctively below the population
    average is a persona just as much as being above it. Observed live on a
    retail dataset — the largest cluster (86.5% of rows) was defined by zero
    late deliveries against an 8% average and below-average spend, scored 1 star
    for having no positive deviation, and fell through to the unnamed fallback
    "Nhóm chưa phân hoá rõ".

    The ladder stays asymmetric by nature rather than by rule: a non-negative
    quantity can deviate arbitrarily far upward (+1128% was observed) but never
    below -100%, so a "low" domain tops out at 3 stars — enough to earn a name,
    not enough to outrank a genuinely extreme high one.

    Args:
        max_dev: Relative deviation (v-g)/|g| of a domain's most-deviating
            column. Sign is ignored.

    Returns:
        Star rating in the range 1-5 (higher = more distinctive).
    """
    magnitude = abs(max_dev)
    if magnitude >= 5.0:
        return 5
    if magnitude >= 2.0:
        return 4
    if magnitude >= 0.75:
        return 3
    if magnitude >= 0.25:
        return 2
    return 1


def compute_domain_stars(
    means: dict, global_means: dict, domains: dict[str, list[str]]
) -> dict[str, dict]:
    """Rate each domain by how far its columns deviate from the global mean.

    Selects the member column deviating the most in EITHER direction and keeps
    that deviation's sign, so downstream naming can say "cao" or "thấp" while the
    rating itself is magnitude-based (see :func:`stars_from_max_dev`).

    Args:
        means: This cluster's per-feature mean values.
        global_means: Whole-dataset per-feature mean values.
        domains: Domain name -> member column list (from DatasetProfile.domains).

    Returns:
        Domain name -> {"stars": int, "max_dev": float}, where ``max_dev`` is
        signed and ``stars`` reflects its magnitude.
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
            if abs(dev) > abs(max_dev):
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

    # Tie-break on magnitude, not signed value — max_dev is now signed, so comparing it
    # raw would rank any positive deviation above a larger negative one at the same star
    # level, quietly reintroducing the above-average-only bias this rating just dropped.
    dominant = max(stars, key=lambda d: (stars[d]["stars"], abs(stars[d]["max_dev"])))
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


def _lower_first(label: str) -> str:
    """Lowercase a label's first letter so it reads naturally mid-sentence.

    "Tỷ lệ giao hàng trễ" -> "Nhóm tỷ lệ giao hàng trễ cao". Acronyms are left alone:
    an all-caps first word ("ARPU", "CSAT") is a name, not a capitalised sentence start.

    Args:
        label: Human label for a feature.

    Returns:
        The label with its first character lowercased where appropriate.
    """
    if not label:
        return label
    first_word = label.split(maxsplit=1)[0]
    if len(first_word) > 1 and first_word.isupper():
        return label
    return label[0].lower() + label[1:]


#: Smallest relative deviation a feature may have and still be worth naming a persona
#: after. Matches the threshold ``distinguishing_signal`` already uses to decide a feature
#: is worth listing as evidence — a feature too weak to mention is too weak to be a name.
_MIN_NAMING_DEVIATION = 0.1


def _signal_strength(persona: dict) -> float:
    """Magnitude of a persona's strongest feature deviation; 0.0 when unavailable."""
    try:
        top = (persona.get("distinguishing_signal") or {}).get("top_features") or []
        return abs(float(top[0].get("deviation", 0.0))) if top else 0.0
    except (AttributeError, IndexError, TypeError, ValueError):
        return 0.0


def assign_generic_persona_names(personas: list[dict]) -> list[str]:
    """Name every persona, preferring a feature no other persona has claimed.

    :func:`generic_persona_name` sees one persona at a time, so two clusters split by the
    same dominant axis both get named after it — observed on Olist, where the 86.5% and
    7.9% clusters came out "Nhóm tỷ lệ giao hàng trễ thấp" and "Nhóm tỷ lệ giao hàng trễ
    cao". Technically distinguishable, but it reads as a naming failure and buries what
    else separates the groups.

    Personas are processed strongest-signal-first so the cluster with the most extreme
    claim on a feature keeps it, and weaker ones fall to their next-best unclaimed
    feature. A persona whose features are all claimed keeps its top feature anyway —
    a repeated name beats an unnamed group.

    Args:
        personas: Persona dicts carrying ``distinguishing_signal``. Not mutated.

    Returns:
        Names positionally aligned with ``personas``. Best-effort: never raises.
    """
    names: list[str] = [_FALLBACK_NAME] * len(personas)
    claimed: set[str] = set()
    try:
        order = sorted(range(len(personas)), key=lambda i: -_signal_strength(personas[i]))
    except Exception:
        order = list(range(len(personas)))
    for i in order:
        try:
            names[i] = generic_persona_name(
                personas[i].get("distinguishing_signal"), claimed=claimed
            )
        except Exception:
            continue
    return names


_FALLBACK_NAME = "Nhóm chưa phân hoá rõ"


def generic_persona_name(sig: dict | None, claimed: set[str] | None = None) -> str:
    """Deterministic, dataset-neutral persona name from a distinguishing_signal.

    Names the persona after its most-deviating feature and direction when the dominant
    domain is distinctive (>= 3 stars), else a neutral fallback. Contains NO churn/telco
    vocabulary. Best-effort: never raises.

    Args:
        sig: A persona's ``distinguishing_signal`` dict (see
            :func:`distinguishing_signal`), or None.
        claimed: Optional mutable set of feature names already used to name another
            persona. When given, the first top-feature that is unclaimed and deviates by
            at least :data:`_MIN_NAMING_DEVIATION` is preferred, and the chosen feature is
            added to the set. Pass None (the default) for standalone naming.

    Returns:
        A short, dataset-agnostic Vietnamese persona name; the neutral
        "Nhóm chưa phân hoá rõ" when no distinctive signal is present.
    """
    fallback = _FALLBACK_NAME
    try:
        if not isinstance(sig, dict) or not sig:
            return fallback
        dom = sig.get("dominant_domain")
        stars = sig.get("stars") or {}
        dom_info = stars.get(dom) if isinstance(stars, dict) else None
        dom_stars = dom_info.get("stars", 0) if isinstance(dom_info, dict) else 0
        top = sig.get("top_features") or []
        if dom and dom_stars >= 3 and top:
            t = top[0]
            if claimed is not None:
                for cand in top:
                    feat = str(cand.get("feature", ""))
                    if feat and feat not in claimed and abs(
                        float(cand.get("deviation", 0.0))
                    ) >= _MIN_NAMING_DEVIATION:
                        t = cand
                        break
                claimed.add(str(t.get("feature", "")))
            label = t.get("label") or t.get("feature") or dom
            direction = "cao" if t.get("deviation", 0) >= 0 else "thấp"
            return f"Nhóm {_lower_first(str(label))} {direction}"
        return fallback
    except Exception:
        return fallback


def _generic_priority_score(sig: dict | None, support_pct: float | None) -> int:
    """Rank a generic persona by distinctiveness, with size as tiebreaker.

    Args:
        sig: The persona's ``distinguishing_signal`` dict, or None.
        support_pct: Share of the population in this persona (0-1).

    Returns:
        An integer in [10, 99]; higher means more distinctive. Falls back to a
        size-only score when no usable signal is present. Never raises.
    """
    try:
        pct = float(support_pct or 0.0)
    except (TypeError, ValueError):
        pct = 0.0
    stars = 0
    try:
        if isinstance(sig, dict):
            dom_info = (sig.get("stars") or {}).get(sig.get("dominant_domain"))
            if isinstance(dom_info, dict):
                stars = int(dom_info.get("stars", 0))
    except (TypeError, ValueError, AttributeError):
        stars = 0
    return int(max(10, min(99, round(20 + stars * 12 + pct * 10))))


def enforce_generic_persona(personas: list[dict], profile: DatasetProfile | None) -> None:
    """Force personas onto the generic, dataset-agnostic path, in place.

    Applied by the enrichment layer ONLY for non-churn datasets
    (see :func:`triadic_dgm.persona.dataset_profile.has_churn_columns`). For
    each persona it sets a generic ``persona_name`` from the persona's
    ``distinguishing_signal`` and neutralises every telco churn field so
    downstream (report_generator ``is_post_churn`` detection, feed, UI) renders
    generically regardless of what the improvising LLM emitted. This is the
    deterministic guarantee behind Phase 4. Best-effort per persona; never raises.

    Also neutralises ``severity``/``risk``/``risk_tier``: the LLM's
    ``apply_business_rules``/``classify_risk_tier`` derive all three from
    telco keyword matches (complaint/call/cl_total) and telco profile keys
    (high_spender_pct, tier_downgrade_rate, ...) that never fire on non-telco
    data, so they always collapse to the same constant values (severity/risk
    "LOW", risk_tier "Nhóm bị động – theo dõi & cảnh báo") — technically true
    but meaningless labels that render as noise (or dump every persona into
    one bucket) on a dataset with no severity/risk/risk-tier concept. Nulling
    them lets the report/UI layer drop those fields instead of showing a
    constant, uninformative value.

    Args:
        personas: Persona dicts to mutate in place.
        profile: Active DatasetProfile (accepted for symmetry / future use).
    """
    if not personas:
        return
    # Named in one coordinated pass, not per persona: the choice of which feature to name
    # a cluster after depends on what the other clusters already took.
    names = assign_generic_persona_names(personas)
    for p, generic_name in zip(personas, names):
        try:
            # Explicit mode marker: downstream renderers (report_generator, feed, UI) must be able
            # to tell "generic dataset" apart from "telco dataset that happens to score LOW on
            # everything". Without it they fall back to telco keyword heuristics that silently
            # match nothing and then assert telco facts as true (e.g. "ARPU ở mức thấp",
            # "ít khi liên hệ CSKH") about a dataset that has no such columns at all.
            p["dataset_mode"] = "GENERIC"
            p["persona_name"] = generic_name
            p["churn_driver"] = None
            p["churn_driver_evidence"] = None
            p["churn_driver_confidence"] = None
            p["temporal_trajectory"] = []
            p["domain_signature"] = {}
            p["severity"] = None
            p["risk"] = None
            p["risk_tier"] = None

            # profile_attributes is built by keyword-matching telco column names
            # (high_spender/fee_avg/segment_*_count/loyalty_rank/csat/goi_cuoc...).
            # On a non-telco dataset the matches are absent or accidental, yet ~20
            # render sites in report_generator phrase whatever is there in telco
            # prose — including asserting a NUMBER that was never measured
            # (observed live on a wine-marketing dataset: "Nhóm này có mức cước
            # trung bình khoảng 0 nghìn đồng/tháng", printed four times). The
            # generic profile section is built from distinguishing_signal instead,
            # so dropping this loses nothing.
            p["profile_attributes"] = {}

            # recommended_actions comes from generate_actions(), branching on the
            # sandbox LLM's OWN dataset_mode guess — independent of the Python-side
            # has_churn_columns() decision that triggered this function. When they
            # disagree (LLM reads a non-telco dataset as POST_CHURN) the churn
            # fields end up nulled while the Business Roadmap still renders the
            # telco playbook. Replaced wholesale rather than filtered, for two
            # reasons: (1) every input generate_actions() branches on — persona
            # name, severity, risk, profile_attributes — is a field this function
            # just established as meaningless here, so nothing it produced is
            # worth salvaging; (2) filtering by vocabulary provably misses items
            # whose own wording is neutral but whose ROADMAP_METADATA entry is not
            # (observed: "Phân tích đối thủ cạnh tranh và chính sách giá" passes
            # any term filter, then renders KPI "High-Value Churn Rate" on a
            # wine-retail dataset). No-op when the LLM did classify GENERIC.
            p["recommended_actions"] = list(GENERIC_FALLBACK_ACTIONS)

            # priority_score comes from apply_business_rules, whose thresholds read
            # complaint/call/cl_total — all zero here, so every persona lands on the
            # same constant base and ranking degenerates to cluster size alone. Rank
            # by how distinctive a persona actually is (dominant-domain deviation),
            # keeping size as the tiebreaker.
            p["priority_score"] = _generic_priority_score(
                p.get("distinguishing_signal"), p.get("support_pct")
            )
        except Exception:
            continue


def apply_dataset_profile(
    personas: list[dict],
    global_means: dict,
    profile: DatasetProfile | None,
    means_getter: Callable[[dict], dict] | None = None,
) -> None:
    """Run the full profile-driven persona enrichment, in place.

    The two steps a report needs before rendering: attach a dataset-agnostic
    ``distinguishing_signal`` to every persona, then — only for a dataset with no churn
    columns — force them onto the generic path.

    Exists so the churn gate lives in exactly ONE place. It was previously inlined in the
    convergence runner, and the report path had no equivalent at all, which is how a
    non-telco dataset reached users as a full telco report.

    Args:
        personas: Persona dicts to mutate in place.
        global_means: Whole-population per-feature means.
        profile: Active DatasetProfile; None disables enrichment entirely.
        means_getter: Optional accessor for a persona's feature means.

    Returns:
        None. Best-effort at every step — never raises, never drops a persona.
    """
    if not personas or profile is None:
        return
    try:
        characterize_personas(personas, global_means, profile, means_getter=means_getter)
    except Exception as e:
        print(f"[persona] characterize_personas failed (non-fatal): {e}")
    try:
        from triadic_dgm.persona.dataset_profile import has_churn_columns

        if has_churn_columns(getattr(profile, "labels", {}).keys()):
            return
    except Exception as e:
        print(f"[persona] churn-column detection failed, leaving telco path (non-fatal): {e}")
        return
    try:
        enforce_generic_persona(personas, profile)
    except Exception as e:
        print(f"[persona] enforce_generic_persona failed (non-fatal): {e}")
