"""Headless (non-streaming) driver for a single persona-generation pipeline run.

Mirrors what api/routers/chat.py:170-188 does for one chat turn, but drains
TriadicAgent.stream_workflow() to completion instead of streaming it to an SSE client —
there is no non-streaming wrapper anywhere in the codebase, so this must iterate the
generator itself.
"""

from __future__ import annotations

import re
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from triadic_dgm.engine import TriadicAgent
from triadic_dgm.persona.characterization import characterize_personas, enforce_generic_persona
from triadic_dgm.persona.dataset_profile import has_churn_columns

from .persona_json import (
    describe_persona,
    extract_persona_list,
    format_loyalty_rank_avg,
    get_feature_label,
    get_profile_attr_label,
)

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

# ─────────────────────────────────────────────────────────────────────────────────────────
# DETERMINISTIC churn_driver / domain_signature — computed at enrich time from the (fixed)
# feature_means, NOT trusted from the LLM's per-run improvised code. Confirmed on live data:
# in "improvise" mode the sandbox LLM does NOT faithfully run prompts.py's classify_churn_driver
# / compute_domain_signature — it stores a malformed domain_signature ({'stars': 1}) and/or
# invents free-text labels ("No clear driver (Demo)", "No clear driver (Synthetic Data)") even
# when complaint deviates +3809% or call/missed +1975%. That made the churn_driver field
# contradict the very feature table shown next to it. Since the convergence loop's feature set
# is FIXED, re-deriving these deterministically here gives a stable, self-consistent label that
# always matches the displayed deviations. Mirrors the in-prompt logic in prompts.py (which
# lives inside a {{double-brace}} template string and can't be imported as a real dict).
_DOMAIN_KEYWORD_GROUPS = {
    "complaint": ["complaint_total", "complaint_avg", "complaint_recent", "complaint_trend", "complaint_std", "active_complaint_months", "old_complaint", "no_complaint"],
    "call": ["call_total", "call_avg", "call_std", "call_trend", "old_call", "recent_call", "call_cv", "active_call_months", "no_call"],
    "missed": ["missed_total", "missed_avg", "missed_std", "missed_trend", "old_missed", "recent_missed", "active_missed_months", "no_missed"],
    "technical": ["cl_total", "cl_avg", "cl_std", "cl_trend", "old_cl", "recent_cl", "active_cl_months", "no_cl"],
    "usage": ["spending_decline", "spending_growth", "usage_decline", "usage_unstable", "segment_downgrade", "segment_upgrade", "cnt_dao_dong", "cnt_giam", "status_worsening"],
    "value": ["high_spender", "fee_total", "fee_avg", "loyalty_rank", "loyalty_point", "segment_avg"],
}

# Star thresholds mirror prompts.py compute_domain_signature: max_dev is the max SIGNED relative
# deviation (v-g)/|g| across a domain's columns, floored at 0 — so a domain that is only BELOW
# average (e.g. complaint -100%) scores 1 star, never counts as "nổi bật". CÀNG CAO càng xấu for
# complaint/call/missed/technical, so only positive deviation is a risk signal.
def _stars_from_max_dev(max_dev: float) -> int:
    return 5 if max_dev >= 5.0 else 4 if max_dev >= 2.0 else 3 if max_dev >= 0.75 else 2 if max_dev >= 0.25 else 1


def _compute_domain_stars(means: dict, global_means: dict) -> dict:
    """Per-domain star rating from cluster-vs-global feature deviations — the deterministic
    replacement for the LLM's unreliable domain_signature. Returns {domain: {'stars': n}}."""
    signature: dict = {}
    for dom, keywords in _DOMAIN_KEYWORD_GROUPS.items():
        max_dev = 0.0
        for f, v in means.items():
            if not isinstance(v, (int, float)):
                continue
            fl = str(f).lower()
            if not any(kw in fl for kw in keywords):
                continue
            g = global_means.get(f, 0)
            dev = (v - g) / abs(g) if g else 0.0
            if dev > max_dev:
                max_dev = dev
        signature[dom] = {"stars": _stars_from_max_dev(max_dev)}
    return signature


# Evidence texts copied verbatim from prompts.py's classify_churn_driver so the deterministic
# label reads identically to the canonical rule engine (minus the temporal sub-branching, which
# needs raw per-customer rows the convergence store doesn't keep).
_CHURN_DRIVER_RULES_EVIDENCE = {
    "Khách hàng giá trị cao nhưng trải nghiệm suy giảm": 'Nhóm chi tiêu cao với hành vi sử dụng dịch vụ suy giảm rõ rệt, nhưng KHÔNG phát sinh khiếu nại hay liên hệ CSKH trước khi rời mạng — dấu hiệu "rời mạng trong im lặng" ở nhóm giá trị cao, nhiều khả năng đã chuyển sang đối thủ thay vì phản ánh vấn đề.',
    "Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để": "Tần suất liên hệ CSKH cao đi kèm sự cố kỹ thuật và khiếu nại đều tăng mạnh cùng lúc — cho thấy vấn đề kỹ thuật lặp lại nhiều lần mà không được giải quyết dứt điểm qua các lần liên hệ.",
    "Sự cố/khiếu nại cấp tính ngay trước khi rời mạng": "Khiếu nại/sự cố tăng mạnh ở giai đoạn gần rời mạng so với mặt bằng chung — dấu hiệu bất mãn về trải nghiệm dịch vụ là nguyên nhân nổi bật nhất dẫn tới rời mạng.",
    "Tăng liên hệ CSKH/cuộc gọi nhỡ trước khi rời mạng": "Tần suất liên hệ CSKH/cuộc gọi nhỡ tăng cao gần thời điểm rời mạng — dữ liệu chỉ phản ánh SỐ LẦN liên hệ, không xác định được các lần liên hệ này đã được xử lý thoả đáng hay chưa.",
    "Khách hàng giá trị cao, chủ động rời mạng": "Nhóm chi tiêu cao, hành vi sử dụng dịch vụ vẫn ổn định và không phát sinh khiếu nại/sự cố — nguyên nhân rời mạng nhiều khả năng đến từ yếu tố NGOÀI trải nghiệm dịch vụ (giá cước, ưu đãi đối thủ cạnh tranh...).",
    "Khách hàng âm thầm rời mạng": "Không phát sinh khiếu nại hay liên hệ CSKH đáng kể, nhưng hành vi sử dụng dịch vụ suy giảm dần trước khi rời mạng — dấu hiệu \"rời mạng trong im lặng\" thay vì phản ánh qua kênh CSKH trước.",
    "Không rõ nguyên nhân hành vi (có thể do giá cước/cạnh tranh/khác)": "Không phát hiện dấu hiệu khiếu nại hoặc sự cố đáng kể trong lịch sử tương tác — nguyên nhân rời mạng nhiều khả năng đến từ yếu tố NGOÀI hành vi tương tác (giá cước, đối thủ cạnh tranh, chuyển vùng...), không đủ dữ liệu hành vi để kết luận thêm.",
}


def _classify_churn_driver_from_stars(stars: dict) -> tuple[str, str, str]:
    """Star-based rule ladder mirroring prompts.py classify_churn_driver (rules ordered
    most-specific first, so a broad rule never swallows a special combination). Returns
    (driver, evidence, confidence). Skips the temporal sub-branch of rule 3 (needs raw rows),
    defaulting to the acute-onset evidence — the DRIVER label itself depends only on stars."""
    def sc(dom: str) -> int:
        info = stars.get(dom)
        return info.get("stars", 1) if isinstance(info, dict) else 1

    s_complaint, s_call, s_missed = sc("complaint"), sc("call"), sc("missed")
    s_technical, s_usage, s_value = sc("technical"), sc("usage"), sc("value")

    def out(driver: str, confidence: str = "MEDIUM") -> tuple[str, str, str]:
        return driver, _CHURN_DRIVER_RULES_EVIDENCE.get(driver, ""), confidence

    # 1. Silent premium churn: giá trị cao + usage suy giảm, hoàn toàn không complaint/call/missed
    if s_value >= 4 and s_usage >= 3 and s_complaint <= 2 and s_call <= 2 and s_missed <= 2:
        return out("Khách hàng giá trị cao nhưng trải nghiệm suy giảm")
    # 2. Support failure: gọi nhiều + phàn nàn + sự cố kỹ thuật cùng lúc
    if s_call >= 4 and s_complaint >= 3 and s_technical >= 3:
        return out("Khách hàng gặp sự cố kỹ thuật không được xử lý triệt để")
    # 3. Bất mãn thuần tuý (complaint là domain nổi bật nhất)
    if s_complaint >= 4 and s_complaint > s_call and s_complaint > s_missed:
        return out("Sự cố/khiếu nại cấp tính ngay trước khi rời mạng")
    # 4. Liên hệ CSKH/cuộc gọi nhỡ tăng cao (call/missed nổi bật nhất)
    if (s_call >= 3 or s_missed >= 3) and max(s_call, s_missed) >= s_complaint and max(s_call, s_missed) >= s_technical:
        return out("Tăng liên hệ CSKH/cuộc gọi nhỡ trước khi rời mạng")
    # 5. Giá trị cao, chủ động rời mạng (mọi domain khác thấp)
    if s_value >= 4 and s_complaint <= 2 and s_call <= 2 and s_usage <= 2:
        return out("Khách hàng giá trị cao, chủ động rời mạng")
    # 6. Âm thầm rời mạng (usage suy giảm, giá trị không cao, không phàn nàn)
    if s_usage >= 3 and s_value <= 2 and s_complaint <= 2 and s_call <= 2:
        return out("Khách hàng âm thầm rời mạng")
    return out("Không rõ nguyên nhân hành vi (có thể do giá cước/cạnh tranh/khác)", "LOW")


# Statistical-aggregation suffixes/prefixes that turn ONE underlying signal into several
# near-collinear columns (call_total_6m / call_avg_6m / call_std / call_trend / call_cv /
# active_call_months are all just "call volume" — avg = total/months, std scales with the mean,
# so their relative deviations come out nearly identical). Collapsing to a root lets the feature
# table show 5 DISTINCT signals instead of 5 restatements of the strongest domain (user:
# "chênh lệch % các feature đều giống nhau").
def _feature_root(feature: str) -> str:
    r = str(feature).lower()
    r = re.sub(r"_(total|avg|std|trend|cv|ratio)(_6m)?$", "", r)
    r = re.sub(r"^(active|old|recent|no)_", "", r)
    r = re.sub(r"_months$", "", r)
    r = re.sub(r"_6m$", "", r)
    return r or str(feature).lower()


# Vietnamese majority quantifiers the narrative LLM sometimes attaches to a sub-50% proportion
# ("phần lớn thuộc nhóm chi tiêu cao (tỷ lệ 42%)" — 42% is not a majority). Softened to a neutral
# "một tỷ lệ đáng kể" only when a <50% figure sits in the same clause, so a genuine majority
# claim (>=50%) is left untouched.
_MAJORITY_QUANTIFIER_RE = re.compile(r"(phần lớn|đa số|hầu hết|phần đông|chủ yếu)", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def _soften_overstated_majority(text: str) -> str:
    """If a majority quantifier and a <50% percentage occur in the same clause, replace the
    quantifier with 'một tỷ lệ đáng kể'. Conservative: leaves the sentence untouched when the
    nearby percentage is >=50% (a real majority) or when no percentage is near the quantifier."""
    if not text or not _MAJORITY_QUANTIFIER_RE.search(text):
        return text

    def _fix_clause(clause: str) -> str:
        if not _MAJORITY_QUANTIFIER_RE.search(clause):
            return clause
        pcts = [float(m.group(1).replace(",", ".")) for m in _PERCENT_RE.finditer(clause)]
        # Only soften when EVERY percentage cited in this clause is a minority (<50). If the
        # clause has no percentage, we can't verify the claim — leave it alone.
        if pcts and all(p < 50 for p in pcts):
            return _MAJORITY_QUANTIFIER_RE.sub("một tỷ lệ đáng kể", clause)
        return clause

    # Split on clause-ish boundaries (sentence + comma) so a fix stays local to the claim.
    parts = re.split(r"([.,;]\s*)", text)
    return "".join(_fix_clause(p) if i % 2 == 0 else p for i, p in enumerate(parts))


# Theme keywords for detecting when an LLM-generated persona_name CONTRADICTS the deterministic
# churn_driver (user chose: keep the LLM's diverse names, override ONLY on contradiction). The
# name's claimed theme is checked against the actual domain STARS (reliable), not against the
# driver text — so a name like "Khách hàng âm thầm rời mạng" (claims silent/no-contact) is only
# flagged when a risk domain is actually strong (call/missed 5⭐ here), and stays valid for a
# genuinely usage-driven silent-churn cluster. Order matters: most-specific themes first.
_NAME_THEME_KEYWORDS = [
    ("silent", ["âm thầm", "im lặng", "lặng lẽ"]),
    ("stable", ["ổn định", "trung thành", "hài lòng", "bình thường"]),
    ("unknown", ["không rõ", "chưa rõ", "no clear", "chưa xác định", "đặc trưng", "đa dạng"]),
    ("complaint", ["khiếu nại", "phàn nàn", "bất mãn", "than phiền", "complaint"]),
    ("technical", ["sự cố", "kỹ thuật", "technical"]),
    ("premium", ["giá trị cao", "chi tiêu cao", "cao cấp", "vip", "premium"]),
    ("usage", ["giảm sử dụng", "suy giảm sử dụng", "ngừng sử dụng", "giảm chi tiêu"]),
    ("contact", ["cskh", "cuộc gọi", "tổng đài", "liên hệ", "call", "gọi nhỡ"]),
]


def _persona_name_theme(name: str) -> str | None:
    nl = (name or "").lower()
    for theme, kws in _NAME_THEME_KEYWORDS:
        if any(kw in nl for kw in kws):
            return theme
    return None


def _name_contradicts_stars(name: str, stars: dict) -> bool:
    """True when the LLM persona_name asserts a story the domain stars refute. Uses stars (the
    same reliable signal behind the deterministic churn_driver), so multi-domain drivers aren't
    over-flagged: a domain-specific name is only 'wrong' when that domain is actually weak, and a
    calm/vague name is only 'wrong' when a real risk signal is present."""
    theme = _persona_name_theme(name)
    if theme is None:
        return False  # generic name (e.g. "Nhóm 2") — not a contradiction, keep it

    def st(dom: str) -> int:
        info = stars.get(dom)
        return info.get("stars", 1) if isinstance(info, dict) else 1

    strong_risk = max(st("complaint"), st("call"), st("missed"), st("technical")) >= 4
    if theme in ("silent", "stable", "unknown"):
        # Name claims calm/no-clear-signal, but a strong risk domain exists → contradiction.
        return strong_risk
    domain_for_theme = {
        "contact": max(st("call"), st("missed")),
        "complaint": st("complaint"),
        "technical": st("technical"),
        "premium": st("value"),
        "usage": st("usage"),
    }
    # Name names a specific driver domain, but that domain is weak (< 3⭐) → contradiction.
    return domain_for_theme.get(theme, 3) < 3


_NHOM_SUFFIX_TAIL_RE = re.compile(r"\s*[-–]\s*(Nhóm\s*\d+|\d+)\s*$", re.IGNORECASE)


def _align_name_with_driver(original_name: str, churn_driver: str) -> str:
    """Replace a contradictory name with the deterministic churn_driver, preserving any trailing
    '- Nhóm N' disambiguation suffix the pipeline added so two clusters sharing a driver stay
    distinguishable."""
    if not churn_driver:
        return original_name
    m = _NHOM_SUFFIX_TAIL_RE.search(original_name or "")
    suffix = f" - {m.group(1)}" if m else ""
    return f"{churn_driver}{suffix}"


def build_task_prompt(features: list[str]) -> str:
    """Build the convergence task prompt for a GIVEN behavioral feature set.

    Feature list is dataset-derived (DatasetProfile.behavioral_features), not the
    hardcoded telco constant — so the same loop works on any dataset. Keeps the
    'phân cụm'/'persona' trigger words so SemanticVerifier.is_business_task()
    (triadic_dgm/agent/verifier.py) recognises it as a genuine user request.
    Dataset-agnostic wording (no churn framing); telco churn analysis is now an
    auto-detected specialization, not the default (Phase 4).

    Args:
        features: Ordered list of behavioral feature column names to force KMeans
            to train on, typically ``DatasetProfile.behavioral_features``.

    Returns:
        The fully-assembled Vietnamese task prompt string embedding ``features``.
    """
    return (
        "Hãy phân tích persona/phân khúc khách hàng dựa trên dữ liệu hiện có: thực hiện phân cụm "
        "(clustering) và tạo ra các persona mô tả từng nhóm, kèm đặc điểm nổi bật của từng nhóm, "
        "support/support_pct và các chỉ số liên quan.\n\n"
        "BẮT BUỘC: dùng CHÍNH XÁC danh sách behavioral_features sau để train KMeans (KHÔNG thêm, "
        "KHÔNG bớt, KHÔNG tự chọn cột khác thay thế), theo đúng thứ tự này:\n"
        + ", ".join(features)
        + "\nĐây là yêu cầu bắt buộc để đảm bảo kết quả phân cụm ổn định, có thể so sánh được giữa các lần chạy."
    )


# Fallback prompt when no DatasetProfile is supplied (keeps existing behavior).
DEFAULT_TASK_PROMPT = build_task_prompt(FIXED_BEHAVIORAL_FEATURES)


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


def _compute_global_profile_means(personas: list[dict]) -> dict:
    """Same weighted-average idea as _compute_global_means, but over profile_attributes
    (ARPU/loyalty/tier — computed by the pipeline's compute_profile_attributes, deliberately
    OUTSIDE feature_means since LOYALTY_*/fee_* are excluded from clustering). Without this,
    ARPU/loyalty had no benchmark to compare against, so they could only be shown as bare
    numbers in a separate box instead of a proper 'cluster vs whole dataset' row like every
    other feature — which is exactly what made them look unverifiable/made-up next to the
    real stats_table."""
    total_customers = sum(p.get('support', 0) for p in personas)
    if total_customers <= 0:
        return {}
    keys: set = set()
    for p in personas:
        attrs = p.get('profile_attributes') or {}
        keys.update(k for k, v in attrs.items() if isinstance(v, (int, float)))
    global_means = {}
    for k in keys:
        total_val = sum((p.get('profile_attributes') or {}).get(k, 0) * p.get('support', 0) for p in personas if isinstance((p.get('profile_attributes') or {}).get(k), (int, float)))
        global_means[k] = total_val / total_customers
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


def enrich_personas(personas: list[dict], report_gen: "ReportGenerator | None", profile=None) -> None:
    """Attach a rich narrative + top-5 feature-deviation stats table to each persona,
    mutating the dicts in place. Narrative is generated via ReportGenerator.generate_llm_narrative
    (the SAME LLM call the full report uses, batched batch_size=3) — the user explicitly asked
    for real LLM-written descriptions here instead of the deterministic template composer,
    after noticing the previous rule-based text read as templated ("giống rulebase hơn là
    LLM"). If the LLM call fails entirely (timeout/gateway error — this loop runs every few
    minutes, so it WILL happen occasionally), falls back to the deterministic composer
    (_build_persona_story / _compose_rich_fallback_narrative / describe_persona) so one bad
    LLM call never blocks a whole run's feed update. Never raises.

    Args:
        personas: Persona dicts to mutate in place.
        report_gen: ReportGenerator used for narrative generation and mean lookups;
            a falsy value is a no-op.
        profile: Optional active DatasetProfile. When given, additionally attaches a
            generic, dataset-agnostic ``distinguishing_signal`` field to each persona
            (Phase 2) alongside the legacy telco ``churn_driver``/``domain_signature``
            fields above, which remain untouched. Defaults to ``None`` (no-op, existing
            behavior unchanged).
    """
    if not report_gen or not personas:
        return
    try:
        global_means = _compute_global_means(personas, report_gen)
    except Exception:
        global_means = {}
    try:
        global_profile_means = _compute_global_profile_means(personas)
    except Exception:
        global_profile_means = {}

    # DETERMINISTIC churn_driver / domain_signature — overwrite whatever the sandbox LLM
    # produced (often malformed/generic, see _DOMAIN_KEYWORD_GROUPS note) with a label derived
    # straight from the fixed feature deviations, BEFORE narrative generation so the narrative
    # (and _build_persona_story fallback) sees the corrected driver.
    for p in personas:
        try:
            means = report_gen._get_means(p)
            if not means:
                continue
            stars = _compute_domain_stars(means, global_means)
            driver, evidence, confidence = _classify_churn_driver_from_stars(stars)
            p["domain_signature"] = stars
            p["churn_driver"] = driver
            p["churn_driver_evidence"] = evidence
            p["churn_driver_confidence"] = confidence
            # Only override the LLM's persona_name when it CONTRADICTS the data (user chose to
            # keep diverse valid names, fix contradictions only) — e.g. "Khách hàng âm thầm rời
            # mạng" on a call/missed 5⭐ cluster. Compatible/generic names are left as the LLM set.
            original_name = p.get("persona_name", "")
            if _name_contradicts_stars(original_name, stars):
                p["persona_name"] = _align_name_with_driver(original_name, driver)
        except Exception:
            # Leave the persona's original churn_driver/domain_signature untouched on any error
            # — never let this best-effort enrichment drop a persona from the run.
            continue

    # ADDITIVE (Phase 2): generic, dataset-agnostic distinguishing_signal alongside the
    # legacy telco churn_driver/domain_signature (untouched). Uses report_gen._get_means so
    # it reads the same means the telco path used. Best-effort — never blocks a run.
    if profile is not None:
        try:
            characterize_personas(personas, global_means, profile, means_getter=report_gen._get_means)
        except Exception as e:
            print(f"[convergence] characterize_personas failed (non-fatal): {e}")

    # Phase 4 (deterministic guarantee): for a NON-churn dataset, force personas onto the
    # generic path — name them from distinguishing_signal and null the telco churn fields the
    # deterministic block above (and/or the improvising LLM) may have set. Runs BEFORE narrative
    # generation so the fallback composer sees churn_driver=None and stays generic. Telco
    # datasets (has_churn_columns True) are untouched — dual-path preserved (Phase 3c dropped).
    if profile is not None and not has_churn_columns(getattr(profile, "labels", {}).keys()):
        try:
            enforce_generic_persona(personas, profile)
        except Exception as e:
            print(f"[convergence] enforce_generic_persona failed (non-fatal): {e}")

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
        # Soften any "phần lớn/đa số ... <50%" overstatement the LLM narrative may contain
        # (user: a 42% high_spender_pct was described as "phần lớn thuộc nhóm chi tiêu cao").
        # No-op when the claim is a genuine >=50% majority or has no nearby percentage.
        try:
            p['narrative'] = _soften_overstated_majority(p.get('narrative', ''))
        except Exception:
            pass
        try:
            stats_table = []
            # profile_attributes (ARPU/loyalty/tier) FIRST — same {value, benchmark, dev_pct}
            # shape as the behavioral features below, in ONE table, instead of a separate
            # unverifiable-looking box: user explicitly asked "sao k đưa xuống chung bảng
            # luôn" after seeing ARPU/loyalty floating above the feature table with no
            # benchmark to compare against.
            profile = p.get('profile_attributes') or {}
            for k, val in profile.items():
                if not isinstance(val, (int, float)) or k not in global_profile_means:
                    continue
                g_val = global_profile_means[k]
                delta_pct = ((val - g_val) / abs(g_val)) * 100 if g_val != 0 else (100 if val > 0 else 0)
                row = {
                    "feature": k,
                    "label": get_profile_attr_label(k),
                    "value": round(float(val), 4),
                    "benchmark": round(float(g_val), 4),
                    "dev_pct": round(float(delta_pct), 1),
                    "is_profile_attr": True,
                }
                if k == "loyalty_rank_avg":
                    # Categorical tier code, not a continuous metric — a bare float average
                    # ("1.03") is meaningless without mapping to the actual tier name.
                    row["value_display"] = format_loyalty_rank_avg(val)
                    row["benchmark_display"] = format_loyalty_rank_avg(g_val)
                stats_table.append(row)

            means = report_gen._get_means(p)
            deviations = report_gen._ranked_deviations(means, global_means) if means else []
            # Dedupe near-collinear restatements of the same signal (call_total/call_avg/call_std
            # all share root "call" with near-identical dev%) — keep only the strongest per root,
            # so the top-5 shown are 5 DISTINCT signals across domains instead of one domain
            # repeated 5×. deviations is already ranked by |dev|, so the first per root is strongest.
            seen_roots: set = set()
            deduped_deviations = []
            for tup in deviations:
                root = _feature_root(tup[0])
                if root in seen_roots:
                    continue
                seen_roots.add(root)
                deduped_deviations.append(tup)
                if len(deduped_deviations) >= 5:
                    break
            for f, val, g_val, _dev in deduped_deviations:
                # Same Dev % formula as report_generator.py's "Cluster Feature Statistics"
                # appendix table (render_markdown), so the two surfaces agree.
                delta_pct = ((val - g_val) / abs(g_val)) * 100 if g_val != 0 else (100 if val > 0 else 0)
                stats_table.append({
                    "feature": f,
                    "label": get_feature_label(f),
                    "value": round(float(val), 4),
                    "benchmark": round(float(g_val), 4),
                    "dev_pct": round(float(delta_pct), 1),
                    "is_profile_attr": False,
                })
            p['stats_table'] = stats_table
        except Exception:
            p['stats_table'] = []


def run_once(
    agent: TriadicAgent,
    task_prompt: str = DEFAULT_TASK_PROMPT,
    report_gen: "ReportGenerator | None" = None,
    setup_code: str | None = None,
    profile=None,
) -> RunResult:
    """Reset the agent, run one full pipeline turn against whatever dataset its workspace
    auto-selects, and extract the resulting persona list. Never raises — a bad run (LLM
    error, kernel crash, malformed JSON) is reported via RunResult.ok=False so callers
    (the background loop) can log and continue instead of dying.

    setup_code, if given, is re-run right after agent.clear() — clear() rebuilds the kernel
    PROCESS from scratch, which wipes out any function (e.g. load_dataset()) injected before
    this call. Without re-injecting it every time, the pipeline's generated code silently
    falls back to whatever tiny improvised data it can cobble together instead of failing
    loudly, which looked like a "successful" run with nonsense results.

    Args:
        agent: The TriadicAgent instance to reset and drive for this run.
        task_prompt: The chat turn's user prompt (defaults to the fixed telco prompt).
        report_gen: Passed through to enrich_personas for narrative/means generation.
        setup_code: Optional code re-injected after agent.clear() (e.g. load_dataset()).
        profile: Optional active DatasetProfile, passed through to enrich_personas so it
            can additionally attach a generic distinguishing_signal (Phase 2). Defaults to
            ``None`` (existing behavior unchanged).
    """
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
        enrich_personas(personas, report_gen, profile=profile)
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
