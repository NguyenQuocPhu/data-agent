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

# Cột hành vi cố định cho riêng convergence loop — KHÔNG đụng đến prompts.py (dùng chung cho
# chat tương tác thật, nơi feature selection tự do là đúng vì mỗi dataset người dùng tải lên
# khác nhau). Gốc rễ của việc "hội tụ" không bao giờ xảy ra giữa các run (xác nhận trực tiếp
# trên dữ liệu thật): prompts.py CHỈ ép loại trừ vài cột (fee_/segment_/cnt_/ARPU...), không
# cố định danh sách được CHỌN — nên mỗi run, code sinh ra tự chọn lại 1 tập con feature khác
# nhau (vd 2 run có cùng support=1.403 khách hàng nhưng feature_means dùng 2 bộ cột hành vi
# khác nhau: 1 run có cl_trend+cl_recent_only, run kia có call_avg_6m+complaint_avg_6m thay
# thế) → feature space khác → KMeans (dù cùng random_state=42) học ra ranh giới cụm khác →
# số cụm tối ưu theo silhouette cũng đổi (3-6 cụm tùy run). Vì dataset của convergence loop
# CỐ ĐỊNH (không phải nhiều dataset khác nhau như chat thật), ép 1 danh sách feature cố định
# loại bỏ hẳn trục biến thiên này mà không ảnh hưởng đến hành vi của chat tương tác thật.
FIXED_BEHAVIORAL_FEATURES = [
    "cl_total_6m", "cl_avg_6m", "cl_std", "cl_trend", "active_cl_months",
    "complaint_total_6m", "complaint_avg_6m", "complaint_std", "complaint_trend", "active_complaint_months",
    "call_total_6m", "call_avg_6m", "call_std", "call_cv", "call_trend", "active_call_months",
    "missed_total_6m", "missed_avg_6m", "missed_ratio_6m",
    "spending_decline", "spending_growth", "high_spender",
]

DEFAULT_TASK_PROMPT = (
    "Hãy phân tích persona khách hàng churn dựa trên dữ liệu hiện có: thực hiện phân cụm "
    "khách hàng (clustering) và tạo ra các persona mô tả từng nhóm, kèm churn driver, "
    "support/support_pct và các chỉ số nghiệp vụ liên quan.\n\n"
    "BẮT BUỘC: dùng CHÍNH XÁC danh sách behavioral_features sau để train KMeans (KHÔNG thêm, "
    "KHÔNG bớt, KHÔNG tự chọn cột khác thay thế), theo đúng thứ tự này:\n"
    + ", ".join(FIXED_BEHAVIORAL_FEATURES)
    + "\nĐây là yêu cầu bắt buộc để đảm bảo kết quả phân cụm ổn định, có thể so sánh được giữa các lần chạy."
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


def _compose_rich_fallback_narrative(p: dict, global_means: dict, report_gen: "ReportGenerator") -> str:
    """Narrative for personas without a churn_driver (so _build_persona_story is unavailable) —
    _compose_deterministic_insight alone only yields a single value_sentence, which reads as
    thin/generic ('mô tả ngắn quá, không thấy đặc trưng'). Adds an opening sentence (size) and
    the same evidence bullets (_get_evidence_bullets) the full report's 'Business Signals' list
    uses, so the persona's actual distinguishing behavior shows up regardless of churn_driver."""
    support = p.get("support") or 0
    pct = (p.get("support_pct") or 0) * 100
    name = p.get("persona_name", "Nhóm này")
    opening = f'Khoảng {support:,} khách hàng ({pct:.1f}%) thuộc nhóm "{name}".'.replace(",", ".")

    try:
        value_sentence = report_gen._compose_profile_value_sentence(
            report_gen._build_profile_context(p), (p.get("profile_attributes") or {}).get("service_composition")
        )
    except Exception:
        value_sentence = ""

    try:
        bullets = report_gen._get_evidence_bullets(p, global_means, top_n=3)
        evidence_sentence = " ".join(b.rstrip(".") + "." for b in bullets if b)
    except Exception:
        evidence_sentence = ""

    return " ".join(s for s in (opening, value_sentence, evidence_sentence) if s)


def enrich_personas(personas: list[dict], report_gen: "ReportGenerator | None") -> None:
    """Attach a rich narrative + top-5 feature-deviation stats table to each persona,
    mutating the dicts in place. Narrative is generated via ReportGenerator.generate_llm_narrative
    (the SAME LLM call the full report uses, batched batch_size=3) — the user explicitly asked
    for real LLM-written descriptions here instead of the deterministic template composer,
    after noticing the previous rule-based text read as templated ("giống rulebase hơn là
    LLM"). If the LLM call fails entirely (timeout/gateway error — this loop runs every few
    minutes, so it WILL happen occasionally), falls back to the deterministic composer
    (_build_persona_story / _compose_rich_fallback_narrative / describe_persona) so one bad
    LLM call never blocks a whole run's feed update. Never raises."""
    if not report_gen or not personas:
        return
    try:
        global_means = _compute_global_means(personas, report_gen)
    except Exception:
        global_means = {}

    llm_narrative_by_cluster: dict = {}
    try:
        narrative = report_gen.generate_llm_narrative(personas, global_means, batch_size=3)
        llm_narrative_by_cluster = {n.cluster_id: n for n in narrative.personas_analysis}
    except Exception as e:
        print(f"[convergence] LLM narrative generation failed, falling back to deterministic composer: {e}")

    for p in personas:
        llm_n = llm_narrative_by_cluster.get(p.get('cluster_id'))
        llm_text = getattr(llm_n, 'business_interpretation', None) if llm_n else None
        if llm_text:
            p['narrative'] = llm_text
            p['narrative_source'] = 'llm'
        else:
            try:
                story = report_gen._build_persona_story(p, global_means) if p.get('churn_driver') else None
                if not story:
                    story = _compose_rich_fallback_narrative(p, global_means, report_gen)
                p['narrative'] = story or describe_persona(p)
            except Exception:
                p['narrative'] = describe_persona(p)
            p['narrative_source'] = 'deterministic'
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
