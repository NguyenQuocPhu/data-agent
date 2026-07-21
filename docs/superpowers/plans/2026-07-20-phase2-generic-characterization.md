# Phase 2: Generic Cluster Characterization (additive) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm khả năng đặc trưng cụm **generic, thuần unsupervised** (`distinguishing_signal`) tính từ `DatasetProfile.domains` — chạy cho bất kỳ dataset nào — mà KHÔNG đụng tới path telco (`churn_driver`/`domain_signature`) đang được report/feed/UI/DB tiêu thụ.

**Architecture:** Cách tiếp cận **additive**. Module mới `triadic_dgm/persona/characterization.py` tính, cho mỗi persona, một `distinguishing_signal` (domain trội theo độ lệch feature-vs-global, top feature kèm nhãn, evidence text generic — không từ vựng churn). Gắn vào field MỚI `persona["distinguishing_signal"]`. Path telco cũ vẫn chạy nguyên vẹn song song; Phase 3 sau này mới cutover downstream sang field mới rồi xoá path telco.

**Tech Stack:** Python 3.10+, pytest 9.1, pandas 2.3 (chỉ cần cho fixture test).

## Global Constraints

- Strict Python typing + Google-style docstrings (Args:/Returns:) cho mọi function/class public (CLAUDE.md).
- **KHÔNG đụng** `churn_driver`, `domain_signature`, `churn_driver_evidence`, `churn_driver_confidence` — path telco phải chạy nguyên vẹn (report/feed/UI/DB phụ thuộc). Phase 2 chỉ THÊM field `distinguishing_signal`.
- **KHÔNG** sửa `report_generator.py`, `convergence_feed.py`, `convergence_store.py`, DB schema, UI (đó là Phase 3).
- Evidence text KHÔNG chứa từ vựng churn/telco ("rời mạng", "churn driver", "CSKH"...) — phải generic, suy từ `profile.labels`.
- `distinguishing_signal` computation phải never-raise ở tầng persona (một persona lỗi không được làm hỏng cả run) — mirror pattern của `enrich_personas`.
- Chạy test: `python3 -m pytest tests/test_characterization.py -v`.

---

## File Structure

- Create: `triadic_dgm/persona/characterization.py` — tính domain stars + `distinguishing_signal` generic (SRP: chỉ đặc trưng cụm).
- Create: `tests/test_characterization.py` — unit tests.
- Modify: `triadic_dgm/services/convergence_runner.py` — `enrich_personas` + `run_once` nhận `profile`, gọi `characterize_personas` sau block telco (additive).
- Modify: `api/services/convergence_loop.py` — truyền `profile=self._profile` vào `run_once`.

---

## Task 1: `characterization.py` module + tests

**Files:**
- Create: `triadic_dgm/persona/characterization.py`
- Test: `tests/test_characterization.py`

**Interfaces:**
- Consumes: `DatasetProfile.domains: dict[str, list[str]]`, `DatasetProfile.labels: dict[str, str]` (từ Phase 1).
- Produces:
  - `stars_from_max_dev(max_dev: float) -> int`
  - `compute_domain_stars(means: dict, global_means: dict, domains: dict[str, list[str]]) -> dict[str, dict]`
  - `distinguishing_signal(means: dict, global_means: dict, domains: dict[str, list[str]], labels: dict[str, str] | None = None) -> dict`
  - `characterize_personas(personas: list[dict], global_means: dict, profile, means_getter=None) -> None`
  - Field mới trên mỗi persona: `p["distinguishing_signal"] = {"dominant_domain", "stars", "top_features", "evidence"}`.

- [ ] **Step 1: Viết test thất bại**

Create `tests/test_characterization.py`:

```python
"""Unit tests for generic, unsupervised cluster characterization."""
from __future__ import annotations

from triadic_dgm.persona.characterization import (
    characterize_personas,
    compute_domain_stars,
    distinguishing_signal,
    stars_from_max_dev,
)


class _FakeProfile:
    """Minimal stand-in for DatasetProfile (only domains + labels are used here)."""

    def __init__(self, domains, labels):
        self.domains = domains
        self.labels = labels


def test_stars_ladder():
    assert stars_from_max_dev(6.0) == 5
    assert stars_from_max_dev(3.0) == 4
    assert stars_from_max_dev(1.0) == 3
    assert stars_from_max_dev(0.3) == 2
    assert stars_from_max_dev(0.0) == 1
    assert stars_from_max_dev(-1.0) == 1  # below average is never a "signal"


def test_compute_domain_stars_uses_provided_domains():
    means = {"call_total": 10.0, "visits_total": 1.0}
    global_means = {"call_total": 2.0, "visits_total": 1.0}
    domains = {"call": ["call_total"], "visits": ["visits_total"]}
    stars = compute_domain_stars(means, global_means, domains)
    assert stars["call"]["stars"] == 4  # (10-2)/2 = 4.0 -> >=2 -> 4 stars
    assert stars["visits"]["stars"] == 1  # no deviation


def test_distinguishing_signal_picks_dominant_and_is_not_churn_worded():
    means = {"call_total": 10.0, "visits_total": 1.0}
    global_means = {"call_total": 2.0, "visits_total": 1.0}
    domains = {"call": ["call_total"], "visits": ["visits_total"]}
    labels = {"call_total": "Số cuộc gọi tổng"}
    sig = distinguishing_signal(means, global_means, domains, labels)
    assert sig["dominant_domain"] == "call"
    assert sig["top_features"][0]["feature"] == "call_total"
    assert sig["top_features"][0]["label"] == "Số cuộc gọi tổng"
    low = sig["evidence"].lower()
    for banned in ("rời mạng", "churn", "cskh", "khiếu nại"):
        assert banned not in low


def test_weak_signal_yields_neutral_evidence():
    means = {"a": 1.0, "b": 1.0}
    global_means = {"a": 1.0, "b": 1.0}
    domains = {"a": ["a"], "b": ["b"]}
    sig = distinguishing_signal(means, global_means, domains, {})
    assert max(d["stars"] for d in sig["stars"].values()) <= 2
    assert sig["evidence"]  # non-empty, neutral


def test_characterize_personas_is_additive_and_generic():
    profile = _FakeProfile(
        domains={"revenue": ["revenue_sum"], "visits": ["visits_total"]},
        labels={"revenue_sum": "Doanh thu", "visits_total": "Số lượt ghé"},
    )
    personas = [
        {"persona_name": "A", "churn_driver": "KEEP_ME", "feature_means": {"revenue_sum": 900.0, "visits_total": 3.0}},
    ]
    global_means = {"revenue_sum": 100.0, "visits_total": 3.0}
    characterize_personas(personas, global_means, profile)
    p = personas[0]
    assert "distinguishing_signal" in p
    assert p["distinguishing_signal"]["dominant_domain"] == "revenue"
    assert p["churn_driver"] == "KEEP_ME"  # telco field untouched (additive)


def test_characterize_never_raises_on_bad_persona():
    profile = _FakeProfile(domains={"x": ["x"]}, labels={})
    personas = [
        {"persona_name": "bad", "feature_means": "not-a-dict"},  # degenerate
        {"persona_name": "ok", "feature_means": {"x": 5.0}},
    ]
    characterize_personas(personas, {"x": 1.0}, profile)  # must not raise
    assert "distinguishing_signal" in personas[1]
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python3 -m pytest tests/test_characterization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triadic_dgm.persona.characterization'`.

- [ ] **Step 3: Viết implementation**

Create `triadic_dgm/persona/characterization.py`:

```python
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
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `python3 -m pytest tests/test_characterization.py -v`
Expected: PASS toàn bộ 6 test.

- [ ] **Step 5: Commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
git add triadic_dgm/persona/characterization.py tests/test_characterization.py
git commit -q -m "feat(persona): generic unsupervised distinguishing_signal (additive)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```

## Task 2: Wire profile → enrich → characterize (additive, keep telco path)

**Files:**
- Modify: `triadic_dgm/services/convergence_runner.py`
- Modify: `api/services/convergence_loop.py`

**Interfaces:**
- Consumes: `characterize_personas(personas, global_means, profile, means_getter)` (Task 1); existing `enrich_personas(personas, report_gen)` and `run_once(agent, task_prompt, report_gen, setup_code)`.
- Produces: `enrich_personas(personas, report_gen, profile=None)` and `run_once(..., profile=None)` gaining an optional `profile` param.

- [ ] **Step 1: Thêm import trong `convergence_runner.py`**

Cạnh dòng `from .persona_json import (` (đầu file), thêm:

```python
from triadic_dgm.persona.characterization import characterize_personas
```

- [ ] **Step 2: Cho `enrich_personas` nhận `profile` và gọi characterize (additive)**

Trong `triadic_dgm/services/convergence_runner.py`, đổi chữ ký hàm:

```python
def enrich_personas(personas: list[dict], report_gen: "ReportGenerator | None") -> None:
```
thành:

```python
def enrich_personas(personas: list[dict], report_gen: "ReportGenerator | None", profile=None) -> None:
```

Sau đó, ngay TRƯỚC dòng `llm_narrative_by_cluster: dict = {}` (tức sau vòng for gán `churn_driver`/`domain_signature`, trước bước sinh narrative), chèn khối additive:

```python
    # ADDITIVE (Phase 2): generic, dataset-agnostic distinguishing_signal alongside the
    # legacy telco churn_driver/domain_signature (untouched). Uses report_gen._get_means so
    # it reads the same means the telco path used. Best-effort — never blocks a run.
    if profile is not None:
        try:
            characterize_personas(personas, global_means, profile, means_getter=report_gen._get_means)
        except Exception as e:
            print(f"[convergence] characterize_personas failed (non-fatal): {e}")
```

- [ ] **Step 3: Cho `run_once` nhận `profile` và chuyển xuống `enrich_personas`**

Trong cùng file, đổi chữ ký `run_once`:

```python
def run_once(
    agent: TriadicAgent,
    task_prompt: str = DEFAULT_TASK_PROMPT,
    report_gen: "ReportGenerator | None" = None,
    setup_code: str | None = None,
) -> RunResult:
```
thành (thêm `profile`):

```python
def run_once(
    agent: TriadicAgent,
    task_prompt: str = DEFAULT_TASK_PROMPT,
    report_gen: "ReportGenerator | None" = None,
    setup_code: str | None = None,
    profile=None,
) -> RunResult:
```

Và đổi lời gọi `enrich_personas(personas, report_gen)` (trong thân `run_once`) thành:

```python
        enrich_personas(personas, report_gen, profile=profile)
```

- [ ] **Step 4: Truyền `profile` từ loop vào `run_once`**

Trong `api/services/convergence_loop.py`, ở `_loop()`, cả HAI nhánh gọi `run_once` (nhánh có `task_prompt` và nhánh fallback) thêm `profile=self._profile`. Kết quả:

```python
                task_prompt = (
                    build_task_prompt(self._profile.behavioral_features)
                    if self._profile and self._profile.behavioral_features
                    else None
                )
                if task_prompt is not None:
                    result = run_once(self._agent, task_prompt=task_prompt, report_gen=self._report_gen, setup_code=self._tool_layer_code, profile=self._profile)
                else:
                    result = run_once(self._agent, report_gen=self._report_gen, setup_code=self._tool_layer_code, profile=self._profile)
```

- [ ] **Step 5: Smoke test — enrich thêm distinguishing_signal, telco field còn nguyên**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
python3 -c "
from triadic_dgm.services.convergence_runner import enrich_personas
import inspect
sig = inspect.signature(enrich_personas)
assert 'profile' in sig.parameters, 'enrich_personas must accept profile'
from triadic_dgm.services.convergence_runner import run_once
assert 'profile' in inspect.signature(run_once).parameters, 'run_once must accept profile'
import api.services.convergence_loop
print('signatures + loop import OK')
"
```
Expected: `signatures + loop import OK`.

- [ ] **Step 6: Xác nhận test cũ vẫn xanh + commit**

```bash
cd /home/anlnm/anlnm/data-agent/data-agent
python3 -m pytest tests/test_characterization.py tests/test_dataset_profile.py -q
git add triadic_dgm/services/convergence_runner.py api/services/convergence_loop.py
git commit -q -m "feat(convergence): attach generic distinguishing_signal via profile (additive, telco path intact)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git log -1 --oneline
```
Expected: tất cả test PASS, commit hiển thị.

---

## Self-Review Notes (đối chiếu spec)

- Spec Phase 2 (điều chỉnh additive): ✅ Task 1 (signal generic từ profile.domains) + Task 2 (wire, giữ telco path).
- Global constraint "không đụng churn_driver/report/feed/DB": ✅ chỉ thêm field `distinguishing_signal`, thêm param optional `profile` (mặc định None → hành vi cũ nguyên vẹn).
- "Evidence không từ vựng churn": ✅ test `test_distinguishing_signal_picks_dominant_and_is_not_churn_worded` khẳng định.
- "Never raises": ✅ `characterize_personas` bọc try/except mỗi persona + test `test_characterize_never_raises_on_bad_persona`.
- Nghiệm thu generalize để dành cuối Phase 4 (chạy end-to-end trên golden data). Phase 2 chỉ chứng minh signal generic đúng qua unit test.
