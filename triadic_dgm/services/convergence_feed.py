"""Shared logic for turning stored convergence-loop persona rows into display-ready items
and a markdown summary — used by both the API router (JSON feed) and the loop itself
(persisted .md snapshot), so the two never drift apart.
"""

from __future__ import annotations

import json

from .convergence_store import get_latest_distinct_personas, get_previous_persona_by_name
from .persona_json import describe_persona

CONVERGENCE_THRESHOLD_PCT_POINTS = 5.0


def _format_pct(pct: float | None) -> str:
    return f"{pct * 100:.1f}%" if isinstance(pct, (int, float)) else "—"


def _format_time(ts: float | None) -> str:
    if not ts:
        return "—"
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _build_comparison(db_path: str, row: dict) -> dict | None:
    prior = get_previous_persona_by_name(
        db_path,
        row["persona_name_normalized"],
        before_created_at=row["created_at"],
        exclude_run_id=row["run_id"],
    )
    if prior is None or row.get("support_pct") is None or prior.get("support_pct") is None:
        return None
    delta_points = (row["support_pct"] - prior["support_pct"]) * 100
    return {
        "prior_run_id": prior["run_id"],
        "prior_created_at": prior["created_at"],
        "prior_support_pct": prior["support_pct"],
        "delta_support_pct_points": round(delta_points, 2),
        "status": "diverging" if abs(delta_points) > CONVERGENCE_THRESHOLD_PCT_POINTS else "converged",
    }


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
        items.append(
            {
                "run_id": row["run_id"],
                "created_at": row["created_at"],
                "cluster_id": row["cluster_id"],
                "persona_name": row["persona_name"],
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
                "stats_table": full.get("stats_table", []),
                "persona": full,
                "comparison": _build_comparison(db_path, row),
            }
        )
    return items


def render_markdown(items: list[dict]) -> str:
    """Render the latest persona feed as a standalone markdown document — the 'file markdown'
    shown at the top of the /convergence page, regenerated after every loop run."""
    from datetime import datetime

    lines = [
        "# Persona Convergence Feed",
        "",
        f"_Cập nhật lúc {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {len(items)} persona gần nhất từ vòng lặp chạy nền trên dataset cố định._",
        "",
    ]
    if not items:
        lines.append("_Chưa có persona nào được sinh ra._")
        return "\n".join(lines)

    for item in items:
        comp = item.get("comparison")
        if comp:
            arrow = "▲ Hội tụ" if comp["status"] == "converged" else "▼ Đang dao động"
            comp_str = f"{arrow} ({comp['delta_support_pct_points']:+.1f}pp so với lần trước)"
        else:
            comp_str = "Lần xuất hiện đầu tiên"

        occ = item.get("total_occurrences") or 1
        occ_str = f" · Đã xuất hiện {occ} lượt kể từ {_format_time(item.get('first_seen_at'))}" if occ > 1 else ""

        lines.append(f"## {item['persona_name']}")
        lines.append(
            f"Run `{item['run_id'][:8]}` · {_format_time(item['created_at'])} · {comp_str}{occ_str}"
        )
        lines.append("")
        lines.append(
            f"**Support:** {item.get('support', '—')} ({_format_pct(item.get('support_pct'))}) "
            f"· **Risk:** {item.get('risk') or 'N/A'} · **Severity:** {item.get('severity') or 'N/A'}"
        )
        lines.append("")
        if item.get("description"):
            lines.append(item["description"])
            lines.append("")
        stats = item.get("stats_table") or []
        if stats:
            lines.append("| Feature | Value | Benchmark | Dev % |")
            lines.append("|---|---|---|---|")
            for s in stats:
                dev = s.get("dev_pct")
                dev_str = f"{dev:+.1f}%" if isinstance(dev, (int, float)) else "—"
                lines.append(f"| {s['feature']} | {s['value']} | {s['benchmark']} | {dev_str} |")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
