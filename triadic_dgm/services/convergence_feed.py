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
from .persona_json import clean_display_persona_name, describe_persona

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

    top_features = [s["feature"] for s in current_stats_table]
    runs = []
    for occ in occurrences:
        try:
            full = json.loads(occ["persona_json"])
        except (json.JSONDecodeError, TypeError):
            full = {}
        means = full.get("feature_means") or full.get("evidence") or {}
        values = {}
        for f in top_features:
            v = means.get(f)
            values[f] = round(float(v), 4) if isinstance(v, (int, float)) else None
        runs.append(
            {
                "run_id": occ["run_id"],
                "created_at": occ["created_at"],
                "support_pct": occ["support_pct"],
                "persona_name": clean_display_persona_name(occ["persona_name"]),
                "values": values,
                # Narrative is now LLM-generated per run (convergence_runner.enrich_personas) —
                # unlike feature_means (deterministic Python), the LLM call could in principle
                # reword this differently each time even when the underlying stats are frozen.
                # Surfacing it per-occurrence lets the UI show whether wording actually drifts
                # or stays stable, instead of only ever showing the latest run's description.
                "narrative": full.get("narrative") or describe_persona(full),
            }
        )
    all_narratives_identical = len({r["narrative"] for r in runs}) <= 1
    return {"features": top_features, "runs": runs, "narratives_identical": all_narratives_identical}


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
        stats_table = full.get("stats_table", [])
        items.append(
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "cluster_id": row["cluster_id"],
                "persona_name": clean_display_persona_name(row["persona_name"]),
                "support": row["support"],
                "support_pct": row["support_pct"],
                "churn_driver": row["churn_driver"],
                "risk": row["risk"],
                "severity": row["severity"],
                "priority_score": row["priority_score"],
                "total_occurrences": row["total_occurrences"],
                "first_seen_at": row["first_seen"],
                # narrative/stats_table were pre-computed once at run time (convergence_runner.
                # enrich_personas, reusing ReportGenerator's deterministic composer methods) and
                # persisted inside persona_json — describe_persona is only a last-resort fallback
                # for rows saved before that enrichment existed.
                "description": full.get("narrative") or describe_persona(full),
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
            header_cols = " | ".join(_format_time(r["created_at"]) for r in runs)
            lines.append(f"| Feature | {header_cols} |")
            lines.append("|---|" + "---|" * len(runs))
            support_cols = " | ".join(_format_pct(r["support_pct"]) for r in runs)
            lines.append(f"| **support_pct** | {support_cols} |")
            for f in hist["features"]:
                value_cols = " | ".join(
                    (str(r["values"][f]) if r["values"].get(f) is not None else "—") for r in runs
                )
                lines.append(f"| {f} | {value_cols} |")
            lines.append("")

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
