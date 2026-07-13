"""Headless (non-streaming) driver for a single persona-generation pipeline run.

Mirrors what api/routers/chat.py:170-188 does for one chat turn, but drains
TriadicAgent.stream_workflow() to completion instead of streaming it to an SSE client —
there is no non-streaming wrapper anywhere in the codebase, so this must iterate the
generator itself.
"""

from __future__ import annotations

import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from triadic_dgm.engine import TriadicAgent

from .persona_json import describe_persona, extract_persona_list

if TYPE_CHECKING:
    from .report_generator import ReportGenerator

DEFAULT_TASK_PROMPT = (
    "Hãy phân tích persona khách hàng churn dựa trên dữ liệu hiện có: thực hiện phân cụm "
    "khách hàng (clustering) và tạo ra các persona mô tả từng nhóm, kèm churn driver, "
    "support/support_pct và các chỉ số nghiệp vụ liên quan."
)  # Chứa các từ khoá "phân cụm"/"persona"/"churn" để SemanticVerifier.is_business_task()
   # (triadic_dgm/agent/verifier.py) nhận diện đúng như 1 câu hỏi thật của user.


@dataclass
class RunResult:
    run_id: str
    started_at: float
    finished_at: float
    ok: bool
    personas: list[dict] = field(default_factory=list)
    error: str | None = None
    raw_tail: str = ""


def _compute_global_means(personas: list[dict], report_gen: "ReportGenerator") -> dict:
    total_customers = sum(p.get('support', 0) for p in personas)
    all_features: set = set()
    for p in personas:
        all_features.update(report_gen._get_means(p).keys())
    global_means = {}
    for f in all_features:
        total_val = sum(report_gen._get_means(p).get(f, 0) * p.get('support', 0) for p in personas)
        global_means[f] = total_val / total_customers if total_customers > 0 else 0
    return global_means


def enrich_personas(personas: list[dict], report_gen: "ReportGenerator | None") -> None:
    """Attach a rich, deterministic narrative + top-5 feature-deviation stats table to each
    persona, mutating the dicts in place — reuses ReportGenerator's pure-Python composer
    methods (the SAME ones the full report uses, no LLM call) so the convergence feed shows
    the same quality of description as a real report instead of a generic one-liner. Never
    raises: any failure (missing fields, private-method drift) just leaves narrative/
    stats_table empty — callers fall back to persona_json.describe_persona for display."""
    if not report_gen or not personas:
        return
    try:
        global_means = _compute_global_means(personas, report_gen)
    except Exception:
        global_means = {}
    for p in personas:
        try:
            story = report_gen._build_persona_story(p, global_means) if p.get('churn_driver') else None
            if not story:
                story = report_gen._compose_deterministic_insight(p, global_means)
            p['narrative'] = story or describe_persona(p)
        except Exception:
            p['narrative'] = describe_persona(p)
        try:
            means = report_gen._get_means(p)
            deviations = report_gen._ranked_deviations(means, global_means) if means else []
            stats_table = []
            for f, val, g_val, _dev in deviations[:5]:
                # Same Dev % formula as report_generator.py's "Cluster Feature Statistics"
                # appendix table (render_markdown), so the two surfaces agree.
                delta_pct = ((val - g_val) / abs(g_val)) * 100 if g_val != 0 else (100 if val > 0 else 0)
                stats_table.append({
                    "feature": f,
                    "value": round(float(val), 4),
                    "benchmark": round(float(g_val), 4),
                    "dev_pct": round(float(delta_pct), 1),
                })
            p['stats_table'] = stats_table
        except Exception:
            p['stats_table'] = []


def run_once(
    agent: TriadicAgent,
    task_prompt: str = DEFAULT_TASK_PROMPT,
    report_gen: "ReportGenerator | None" = None,
    setup_code: str | None = None,
) -> RunResult:
    """Reset the agent, run one full pipeline turn against whatever dataset its workspace
    auto-selects, and extract the resulting persona list. Never raises — a bad run (LLM
    error, kernel crash, malformed JSON) is reported via RunResult.ok=False so callers
    (the background loop) can log and continue instead of dying.

    setup_code, if given, is re-run right after agent.clear() — clear() rebuilds the kernel
    PROCESS from scratch, which wipes out any function (e.g. load_dataset()) injected before
    this call. Without re-injecting it every time, the pipeline's generated code silently
    falls back to whatever tiny improvised data it can cobble together instead of failing
    loudly, which looked like a "successful" run with nonsense results."""
    run_id = uuid.uuid4().hex
    started_at = time.time()
    try:
        agent.clear()
        if setup_code:
            agent.run_code(setup_code)
        gradio_history = [{"role": "user", "content": task_prompt}]
        agent.programmer.messages.append({"role": "user", "content": task_prompt})

        for _ in agent.stream_workflow(gradio_history, code=None):
            pass

        transcript = gradio_history[-1]["content"] if gradio_history else ""
        personas = extract_persona_list(transcript)
        enrich_personas(personas, report_gen)
        return RunResult(
            run_id=run_id,
            started_at=started_at,
            finished_at=time.time(),
            ok=True,
            personas=personas,
            error=None if personas else "No persona JSON found in transcript",
            raw_tail=transcript[-2000:],
        )
    except Exception as e:
        return RunResult(
            run_id=run_id,
            started_at=started_at,
            finished_at=time.time(),
            ok=False,
            personas=[],
            error=f"{type(e).__name__}: {e}",
            raw_tail=traceback.format_exc()[-2000:],
        )
