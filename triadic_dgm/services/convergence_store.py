"""Plain stdlib sqlite3 persistence for the persona convergence-monitoring loop.

The repo has no ORM/DB layer anywhere — the only existing sqlite3 use
(api/services/workspace.py) is for previewing arbitrary user-uploaded .db files, unrelated
to app state. This module establishes its own small, self-contained convention.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager

from .convergence_runner import RunResult
from .persona_json import compute_fingerprint, normalize_persona_name

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    persona_count INTEGER NOT NULL DEFAULT 0,
    raw_tail TEXT
);

CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    created_at REAL NOT NULL,
    cluster_id INTEGER,
    persona_name TEXT NOT NULL,
    persona_name_normalized TEXT NOT NULL,
    persona_fingerprint TEXT,
    support INTEGER,
    support_pct REAL,
    churn_driver TEXT,
    risk TEXT,
    severity TEXT,
    priority_score REAL,
    persona_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_personas_created_at ON personas(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_personas_name_norm ON personas(persona_name_normalized, created_at DESC);
"""
# idx_personas_fingerprint is deliberately NOT in _SCHEMA: on a pre-existing DB, executescript()
# runs before the migration below adds the persona_fingerprint column, so an unconditional
# `CREATE INDEX ... (persona_fingerprint, ...)` here would fail with "no such column" on any
# DB file created before that migration. Created only after the column is guaranteed to exist
# (either via CREATE TABLE for a fresh DB, or via the ALTER TABLE migration for an old one).


@contextmanager
def _connect(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        # Migration: 'raw_tail' was added after the first release of this schema — existing DB
        # files predate it, and CREATE TABLE IF NOT EXISTS doesn't retroactively add columns.
        existing_run_cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
        if "raw_tail" not in existing_run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN raw_tail TEXT")

        # Migration: 'persona_fingerprint' (statistics-based cross-run identity, replacing
        # name-based matching) was added after the first release too. Backfill it for any
        # existing rows so runs recorded before this migration still participate in dedup/
        # comparison instead of silently falling out of the feed.
        existing_persona_cols = {row["name"] for row in conn.execute("PRAGMA table_info(personas)")}
        if "persona_fingerprint" not in existing_persona_cols:
            conn.execute("ALTER TABLE personas ADD COLUMN persona_fingerprint TEXT")
            rows = conn.execute("SELECT id, persona_json FROM personas WHERE persona_fingerprint IS NULL").fetchall()
            for row in rows:
                try:
                    p = json.loads(row["persona_json"])
                except (json.JSONDecodeError, TypeError):
                    p = {}
                conn.execute(
                    "UPDATE personas SET persona_fingerprint = ? WHERE id = ?",
                    (compute_fingerprint(p), row["id"]),
                )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_personas_fingerprint ON personas(persona_fingerprint, created_at DESC)")


def save_run(db_path: str, result: RunResult) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at, finished_at, ok, error, persona_count, raw_tail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (result.run_id, result.started_at, result.finished_at, int(result.ok), result.error, len(result.personas), result.raw_tail),
        )
        for p in result.personas:
            name = str(p.get("persona_name", ""))
            conn.execute(
                "INSERT INTO personas (run_id, created_at, cluster_id, persona_name, persona_name_normalized, "
                "persona_fingerprint, support, support_pct, churn_driver, risk, severity, priority_score, persona_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.run_id,
                    result.finished_at,
                    p.get("cluster_id"),
                    name,
                    normalize_persona_name(name),
                    compute_fingerprint(p),
                    p.get("support"),
                    p.get("support_pct"),
                    p.get("churn_driver"),
                    p.get("risk"),
                    p.get("severity"),
                    p.get("priority_score"),
                    json.dumps(p, ensure_ascii=False),
                ),
            )


def get_latest_personas(db_path: str, limit: int = 20) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM personas ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_distinct_personas(db_path: str, limit: int = 20) -> list[dict]:
    """Like get_latest_personas, but collapses repeat appearances of the same persona into a
    single row — the most recent occurrence, annotated with how many runs it has appeared in
    and when it was first seen. Matched by persona_fingerprint (support_pct + feature_means
    statistics), NOT persona_name_normalized — the LLM regenerates the clustering/naming code
    fresh every run, so the same underlying cluster gets a different display name almost every
    run even though its stats reproduce near-bit-for-bit; name-based grouping was showing one
    genuinely stable cluster as a stream of unrelated 'new' personas. Without collapsing by
    fingerprint, a converged/stable persona would also dominate the 'latest N' feed with
    identical repeats instead of showing the actual diversity of what's been observed."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.*, occ.total_occurrences, occ.first_seen
            FROM personas p
            INNER JOIN (
                SELECT persona_fingerprint, MAX(created_at) AS max_created,
                       COUNT(*) AS total_occurrences, MIN(created_at) AS first_seen
                FROM personas
                GROUP BY persona_fingerprint
            ) occ
              ON p.persona_fingerprint = occ.persona_fingerprint
             AND p.created_at = occ.max_created
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_previous_persona_by_fingerprint(db_path: str, fingerprint: str, before_created_at: float, exclude_run_id: str) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM personas WHERE persona_fingerprint = ? AND created_at < ? AND run_id != ? "
            "ORDER BY created_at DESC LIMIT 1",
            (fingerprint, before_created_at, exclude_run_id),
        ).fetchone()
        return dict(row) if row else None


def get_persona_occurrences_by_fingerprint(db_path: str, fingerprint: str, limit: int = 10) -> list[dict]:
    """All occurrences of this persona (matched by statistical fingerprint) across runs, OLDEST
    first, capped to the `limit` MOST RECENT ones — for showing how its stats evolved run over
    run (e.g. in a demo: 'this exact cluster reproduced across 6 runs with these support_pct/
    feature values each time'), not just a single latest-vs-prior delta."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM personas WHERE persona_fingerprint = ? ORDER BY created_at DESC LIMIT ?",
            (fingerprint, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_loop_status_counts(db_path: str) -> dict:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) AS errors, MAX(finished_at) AS last_run_at "
            "FROM runs"
        ).fetchone()
        return {
            "total_runs": row["total"] or 0,
            "error_runs": row["errors"] or 0,
            "last_run_at": row["last_run_at"],
        }
