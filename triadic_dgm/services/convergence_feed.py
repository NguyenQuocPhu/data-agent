"""Shared logic for turning stored convergence-loop persona rows into display-ready items
and a markdown summary — used by both the API router (JSON feed) and the loop itself
(persisted .md snapshot), so the two never drift apart.
"""

from __future__ import annotations

import json

from .convergence_store import (
    get_latest_distinct_personas,
    get_persona_occurrences_by_fingerprint,
    get_previous_persona_by_fingerprint,
)
from .persona_json import (
    PROFILE_ATTR_LABELS,
    clean_display_persona_name,
    describe_persona,
    format_loyalty_rank_avg,
    get_feature_label,
    get_profile_attr_label,
)
from triadic_dgm.persona.characterization import compose_signal_narrative

CONVERGENCE_THRESHOLD_PCT_POINTS = 5.0


def _format_pct(pct: float | None) -> str:
    return f"{pct * 100:.1f}%" if isinstance(pct, (int, float)) else "—"


def _format_time(ts: float | None) -> str:
    if not ts:
        return "—"
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _build_comparison(db_path: str, row: dict, current_stats_table: list[dict]) -> dict | None:
    """When this persona has appeared before, build a real feature-by-feature comparison
    table (current run vs prior run) — not just a single support_pct delta badge. Compares
    the same top-deviation features already surfaced in current_stats_table against the
    prior occurrence's raw feature_means, so the reader can see exactly which numbers moved
    and by how much, not just 'it converged/diverged'.

    Matched via persona_fingerprint (statistics), not persona_name_normalized — see
    get_latest_distinct_personas for why name-based matching undercounts convergence."""
    prior = get_previous_persona_by_fingerprint(
        db_path,
        row["persona_fingerprint"],
        before_created_at=row["created_at"],
        exclude_run_id=row["run_id"],
    )
    if prior is None or row.get("support_pct") is None or prior.get("support_pct") is None:
        return None
    delta_points = (row["support_pct"] - prior["support_pct"]) * 100

    try:
        prior_full = json.loads(prior["persona_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        prior_full = {}
    prior_means = prior_full.get("feature_means") or prior_full.get("evidence") or {}

    feature_comparison = []
    for s in current_stats_table:
        prior_val = prior_means.get(s["feature"])
        if not isinstance(prior_val, (int, float)):
            continue
        cur_val = s["value"]
        feature_comparison.append(
            {
                "feature": s["feature"],
                "label": get_feature_label(s["feature"]),
                "prior_value": round(float(prior_val), 4),
                "current_value": cur_val,
                "delta": round(float(cur_val) - float(prior_val), 4),
            }
        )

    return {
        "prior_run_id": prior["run_id"],
        "prior_created_at": prior["created_at"],
        "prior_support_pct": prior["support_pct"],
        "delta_support_pct_points": round(delta_points, 2),
        "status": "diverging" if abs(delta_points) > CONVERGENCE_THRESHOLD_PCT_POINTS else "converged",
        "feature_comparison": feature_comparison,
    }


def _build_history(db_path: str, row: dict, current_stats_table: list[dict], limit: int = 10) -> dict | None:
    """Full multi-run history for a persona (matched by fingerprint) — support_pct + the same
    top-deviation features shown in current_stats_table, one column per run it has appeared
    in (oldest -> newest, capped to `limit`). A single prior-vs-current delta (_build_comparison)
    hides HOW MANY runs actually agree — e.g. a persona seen 6 times could have been identical
    on 5 of them and only just started drifting on the 6th, which a 2-point diff can't show.
    User explicitly asked to see how the stats differ 'qua các lần chạy' (across runs), not
    just the latest vs the one before it."""
    occurrences = get_persona_occurrences_by_fingerprint(db_path, row["persona_fingerprint"], limit=limit)
    if len(occurrences) < 2:
        return None

    all_features = [s["feature"] for s in current_stats_table]
    # Split into 2 groups instead of 1 flat list — profile_attributes (ARPU/loyalty/tier) are
    # explicitly NOT part of clustering (LOYALTY_*/fee_* excluded from FIXED_BEHAVIORAL_FEATURES),
    # they only feed the narrative as supporting context. Mixing them into 1 table implied they
    # carry equal weight in forming the cluster, which they don't.
    cluster_features = [f for f in all_features if f not in PROFILE_ATTR_LABELS]
    profile_features = [f for f in all_features if f in PROFILE_ATTR_LABELS]

    runs = []
    for occ in occurrences:
        try:
            full = json.loads(occ["persona_json"])
        except (json.JSONDecodeError, TypeError):
            full = {}
        means = full.get("feature_means") or full.get("evidence") or {}
        profile = full.get("profile_attributes") or {}
        values: dict = {}
        display_values: dict = {}
        for f in cluster_features:
            v = means.get(f)
            values[f] = round(float(v), 4) if isinstance(v, (int, float)) else None
        for f in profile_features:
            v = profile.get(f)
            values[f] = round(float(v), 4) if isinstance(v, (int, float)) else None
            if f == "loyalty_rank_avg" and isinstance(v, (int, float)):
                # Categorical tier code, not continuous — same mapping as the single-run
                # stats_table (convergence_runner.enrich_personas' value_display/benchmark_display).
                display_values[f] = format_loyalty_rank_avg(float(v))
        runs.append(
            {
                "run_id": occ["run_id"],
                "created_at": occ["created_at"],
                "support_pct": occ["support_pct"],
                "persona_name": clean_display_persona_name(occ["persona_name"]),
                "values": values,
                "display_values": display_values,
                # Narrative is now LLM-generated per run (convergence_runner.enrich_personas) —
                # unlike feature_means (deterministic Python), the LLM call could in principle
                # reword this differently each time even when the underlying stats are frozen.
                # Surfacing it per-occurrence lets the UI show whether wording actually drifts
                # or stays stable, instead of only ever showing the latest run's description.
                "narrative": full.get("narrative") or describe_persona(full),
            }
        )
    all_narratives_identical = len({r["narrative"] for r in runs}) <= 1
    feature_labels = {f: get_feature_label(f) for f in cluster_features}
    feature_labels.update({f: get_profile_attr_label(f) for f in profile_features})

    def _group_stable(features: list[str]) -> bool:
        # True if every feature in this group has the SAME value across every run returned —
        # if so, repeating it N times (once per run column) is pure noise; a single compact
        # {value, benchmark, dev_pct} row (like the first-appearance stats_table) says the same
        # thing with 1/Nth the clutter. Only genuinely diverging features earn the wide table.
        return all(len({r["values"].get(f) for r in runs}) <= 1 for f in features)

    return {
        "cluster_features": cluster_features,
        "profile_features": profile_features,
        "feature_labels": feature_labels,
        "runs": runs,
        "narratives_identical": all_narratives_identical,
        "cluster_stable": _group_stable(cluster_features),
        "profile_stable": _group_stable(profile_features),
    }


def _persona_has_profile_block(full: dict) -> bool:
    """A persona is 'complete' for display when its post-hoc profiling block is present.
    profile_attributes (ARPU/loyalty/tier + domain_signature-derived stats) is the part that
    the pipeline INTERMITTENTLY fails to populate — the LLM regenerates the whole clustering
    script each run and some runs simply never compute/attach it (confirmed: on 07-14, a run
    with 3 healthy clusters had profile_attributes on all 3, the very next run had it on none;
    neither correlates with any code change). feature_means/support_pct are always present, so
    they don't gate completeness."""
    return bool(full.get("profile_attributes"))


def _backfill_incomplete_persona(db_path: str, row: dict, full: dict) -> dict | None:
    """If this persona's LATEST occurrence is missing its profile block, display the most
    recent occurrence of the SAME cluster (matched by fingerprint) that DOES have one, merged
    into `full` in place. Legitimate, not fabrication: an identical fingerprint means the same
    support_pct + feature_means statistics, i.e. the same underlying cluster — so its ARPU/
    loyalty/domain profile is a stable property that an empty run just failed to recompute, not
    a real change. Keeps the current run's live support_pct/feature_means; only fills the
    profile-side fields. Returns {run_id, created_at} of the source occurrence for a UI note,
    or None if nothing was back-filled."""
    if _persona_has_profile_block(full):
        return None
    occurrences = get_persona_occurrences_by_fingerprint(db_path, row["persona_fingerprint"], limit=20)
    for occ in reversed(occurrences):  # newest first
        if occ["run_id"] == row["run_id"]:
            continue
        try:
            complete = json.loads(occ["persona_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not _persona_has_profile_block(complete):
            continue
        for k in ("profile_attributes", "domain_signature", "stats_table", "distinguishing_signal"):
            if complete.get(k):
                full[k] = complete[k]
        if not full.get("churn_driver") and complete.get("churn_driver"):
            full["churn_driver"] = complete["churn_driver"]
        if not full.get("narrative") and complete.get("narrative"):
            full["narrative"] = complete["narrative"]
        return {"run_id": occ["run_id"], "created_at": occ["created_at"]}
    return None


def build_feed_items(db_path: str, limit: int = 20) -> list[dict]:
    """One row per DISTINCT persona (by normalized name) — the latest occurrence, not every
    raw appearance. A genuinely converged persona would otherwise repeat identically across
    consecutive runs and crowd out everything else in a 'latest N' feed; total_occurrences/
    first_seen_at let the UI show 'stable across N runs' instead."""
    rows = get_latest_distinct_personas(db_path, limit=limit)
    items = []
    for row in rows:
        try:
            full = json.loads(row["persona_json"])
        except (json.JSONDecodeError, TypeError):
            full = {}
        # The profiling block (profile_attributes/domain_signature/churn_driver) is populated
        # INTERMITTENTLY by the pipeline — if the latest run dropped it, show the last complete
        # snapshot of this same cluster instead of a stripped-down card (per user request:
        # "feed giữ bản đầy đủ gần nhất"). Mutates `full` in place before it feeds stats_table/
        # description/history/comparison below, so every downstream view stays consistent.
        backfilled_from = _backfill_incomplete_persona(db_path, row, full)
        stats_table = full.get("stats_table", [])
        items.append(
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "cluster_id": row["cluster_id"],
                "persona_name": clean_display_persona_name(row["persona_name"]),
                "support": row["support"],
                "support_pct": row["support_pct"],
                # Prefer the (possibly back-filled) persona_json churn_driver over the DB column,
                # which reflects only the latest — possibly incomplete — occurrence.
                "churn_driver": full.get("churn_driver") or row["churn_driver"],
                "risk": row["risk"],
                "severity": row["severity"],
                "priority_score": row["priority_score"],
                "total_occurrences": row["total_occurrences"],
                "first_seen_at": row["first_seen"],
                # Transparency: non-null when the profile block shown came from an earlier run
                # because this run's was empty. UI/markdown surface it so the number isn't
                # silently presented as belonging to the latest run.
                "profile_backfilled_from": backfilled_from,
                # narrative/stats_table were pre-computed once at run time (convergence_runner.
                # enrich_personas, reusing ReportGenerator's deterministic composer methods) and
                # persisted inside persona_json — describe_persona is only a last-resort fallback
                # for rows saved before that enrichment existed.
                "description": full.get("narrative") or describe_persona(full),
                # Generic, dataset-agnostic signal (Phase 3a) — surfaced ALONGSIDE the legacy
                # telco churn_driver/narrative so any dataset (not just telco) has a meaningful,
                # non-churn description available to the API/UI.
                "distinguishing_signal": full.get("distinguishing_signal"),
                "signal_narrative": compose_signal_narrative(full),
                # stats_table now includes BOTH the top-5 behavioral-feature deviations AND any
                # profile_attributes (ARPU/loyalty/tier) in one unified {value, benchmark, dev_pct}
                # table (convergence_runner.enrich_personas) — so a narrative claim referencing
                # ARPU/loyalty always has a visible, comparable row instead of a separate box.
                "stats_table": stats_table,
                "persona": full,
                "comparison": _build_comparison(db_path, row, stats_table),
                "history": _build_history(db_path, row, stats_table),
            }
        )
    return items


def render_markdown(items: list[dict], status: dict | None = None) -> str:
    """Render a CONCISE convergence dashboard — the 'file markdown' shown at the top of the
    /convergence page, regenerated after every loop run. Deliberately a summary table, not a
    duplicate of the full per-persona cards already shown below it on the page: one row per
    persona (name, latest %, converged/diverging/new, how many runs it's been seen in) plus
    loop health (run/error counts), so it answers 'is this converging, and is the loop
    healthy' at a glance instead of repeating the same detail twice."""
    from datetime import datetime

    lines = ["# Persona Convergence Feed", ""]

    if status:
        health = (
            f"{'Đang chạy' if status.get('running') else 'Đã dừng'} · "
            f"{status.get('run_count', 0)} lượt chạy · {status.get('error_count', 0)} lỗi · "
            f"lượt gần nhất: {_format_time(status.get('last_run_at'))}"
        )
        lines.append(f"_Vòng lặp: {health}_")
        lines.append("")

    lines.append(
        f"_Cập nhật lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {len(items)} persona duy nhất đang theo dõi._"
    )
    lines.append("")

    if not items:
        lines.append("_Chưa có persona nào được sinh ra._")
        return "\n".join(lines)

    lines.append("## Tóm tắt hội tụ")
    lines.append("")
    lines.append("| Persona | Support % gần nhất | Trạng thái | Số lượt thấy | Lần đầu thấy |")
    lines.append("|---|---|---|---|---|")
    for item in items:
        comp = item.get("comparison")
        if comp:
            status_str = (
                f"▲ Hội tụ ({comp['delta_support_pct_points']:+.1f}pp)"
                if comp["status"] == "converged"
                else f"▼ Dao động ({comp['delta_support_pct_points']:+.1f}pp)"
            )
        else:
            status_str = "🆕 Mới"
        occ = item.get("total_occurrences") or 1
        lines.append(
            f"| {item['persona_name']} | {_format_pct(item.get('support_pct'))} | {status_str} | "
            f"{occ} | {_format_time(item.get('first_seen_at'))} |"
        )
    lines.append("")
    lines.append("_Mô tả chi tiết và bảng feature từng persona: xem danh sách thẻ bên dưới trang._")

    repeated = [item for item in items if item.get("history")]
    if repeated:
        lines.append("")
        lines.append("## So sánh thống kê các persona đã trùng lặp qua nhiều lần chạy")
        lines.append("")
        for item in repeated:
            hist = item["history"]
            runs = hist["runs"]
            lines.append(f"### {item['persona_name']} ({len(runs)} lần chạy gần nhất)")
            lines.append("")
            sig_text = item.get("signal_narrative") or ""
            if sig_text:
                lines.append(f"_Tín hiệu nổi bật (generic): {sig_text}_")
                lines.append("")
            bf = item.get("profile_backfilled_from")
            if bf:
                lines.append(
                    f"_ⓘ Lần chạy mới nhất không tính được nhóm chỉ số phụ (ARPU/loyalty/churn driver) — "
                    f"đang hiển thị bản đầy đủ gần nhất của cùng cụm này (lượt {_format_time(bf.get('created_at'))}). "
                    f"Support % vẫn của lần chạy mới nhất._"
                )
                lines.append("")
            header_cols = " | ".join(_format_time(r["created_at"]) for r in runs)
            stats_by_feature = {s["feature"]: s for s in item.get("stats_table", [])}

            def _render_compact(title: str, features: list[str]) -> None:
                # Every value identical across all N runs — repeating it N times is pure noise.
                # Show the SAME compact {value, benchmark, dev_pct} shape as a first-appearance
                # card instead, plus a 1-line note that it's been constant across N runs.
                if not features:
                    return
                lines.append(f"**{title}** _(giống hệt nhau ở cả {len(runs)} lần chạy — không lặp lại từng cột)_")
                lines.append("")
                lines.append("| Feature | Trung bình trong cụm | Trung bình trên toàn bộ data | Chênh lệch |")
                lines.append("|---|---|---|---|")
                for f in features:
                    s = stats_by_feature.get(f)
                    if not s:
                        continue
                    label = hist["feature_labels"].get(f)
                    row_name = f"{f} ({label})" if label and label != f else f
                    val = s.get("value_display", s["value"])
                    bench = s.get("benchmark_display", s["benchmark"])
                    dev = s.get("dev_pct")
                    dev_str = f"{dev:+.1f}%" if isinstance(dev, (int, float)) else "—"
                    lines.append(f"| {row_name} | {val} | {bench} | {dev_str} |")
                lines.append("")

            def _render_wide(title: str, features: list[str]) -> None:
                if not features:
                    return
                lines.append(f"**{title}**")
                lines.append("")
                lines.append(f"| Feature | {header_cols} |")
                lines.append("|---|" + "---|" * len(runs))
                lines.append(
                    "| **support_pct** | " + " | ".join(_format_pct(r["support_pct"]) for r in runs) + " |"
                )
                for f in features:
                    value_cols = " | ".join(
                        (
                            r["display_values"].get(f)
                            or (str(r["values"][f]) if r["values"].get(f) is not None else "—")
                        )
                        for r in runs
                    )
                    label = hist["feature_labels"].get(f)
                    row_name = f"{f} ({label})" if label and label != f else f
                    lines.append(f"| {row_name} | {value_cols} |")
                lines.append("")

            if hist.get("cluster_stable"):
                _render_compact("Feature đóng góp phân cụm (dùng để train KMeans)", hist["cluster_features"])
            else:
                _render_wide("Feature đóng góp phân cụm (dùng để train KMeans)", hist["cluster_features"])
            if hist.get("profile_stable"):
                _render_compact(
                    "Feature đóng góp phân tích persona (ARPU/loyalty/tier — KHÔNG dùng để phân cụm)",
                    hist["profile_features"],
                )
            else:
                _render_wide(
                    "Feature đóng góp phân tích persona (ARPU/loyalty/tier — KHÔNG dùng để phân cụm)",
                    hist["profile_features"],
                )

            if hist.get("narratives_identical"):
                lines.append(f"_Mô tả (narrative) GIỐNG HỆT NHAU ở cả {len(runs)} lần chạy trên:_")
                lines.append("")
                lines.append(f"> {runs[-1]['narrative']}")
            else:
                lines.append("_Mô tả (narrative) qua từng lần chạy — LỆCH NHAU dù chỉ số thống kê giống nhau:_")
                lines.append("")
                for r in runs:
                    lines.append(f"- **{_format_time(r['created_at'])}**: {r['narrative']}")
            lines.append("")

    return "\n".join(lines)
