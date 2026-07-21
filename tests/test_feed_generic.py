"""The convergence feed must surface the generic distinguishing_signal + signal_narrative."""
from __future__ import annotations

import time

from triadic_dgm.services.convergence_feed import build_feed_items, render_markdown
from triadic_dgm.services.convergence_runner import RunResult
from triadic_dgm.services.convergence_store import init_db, save_run


def _seed(db_path: str) -> None:
    init_db(db_path)
    persona = {
        "persona_name": "Nhóm doanh thu cao",
        "cluster_id": 0,
        "support": 1200,
        "support_pct": 0.42,
        "feature_means": {"revenue_sum": 900.0},
        "distinguishing_signal": {
            "dominant_domain": "revenue",
            "stars": {"revenue": {"stars": 4, "max_dev": 3.0}},
            "top_features": [{"feature": "revenue_sum", "label": "Doanh thu", "deviation": 3.0}],
            "evidence": "Nhóm nổi bật nhất ở 'revenue': Doanh thu (+300% so với trung bình).",
        },
    }
    now = time.time()
    save_run(db_path, RunResult(run_id="r1", started_at=now, finished_at=now, ok=True, personas=[persona]))


def test_feed_item_exposes_distinguishing_signal_and_narrative(tmp_path):
    db = str(tmp_path / "conv.db")
    _seed(db)
    items = build_feed_items(db, limit=10)
    assert items, "expected at least one feed item"
    item = items[0]
    assert item["distinguishing_signal"]["dominant_domain"] == "revenue"
    assert "Doanh thu" in item["signal_narrative"]
    assert "rời mạng" not in item["signal_narrative"].lower()


def test_markdown_renders_without_error(tmp_path):
    db = str(tmp_path / "conv.db")
    _seed(db)
    md = render_markdown(build_feed_items(db, limit=10))
    assert "Persona Convergence Feed" in md
