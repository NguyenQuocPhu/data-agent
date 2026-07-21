# Phase 4 — Generic-default persona analysis (prompt steering + Python enforcement) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the persona pipeline analyse ANY dataset as generic persona analysis by default, with telco churn as an auto-detected specialization — enforced deterministically in the Python enrichment layer, with the prompt only softly steered.

**Architecture:** The prompt (`PROGRAMMER_PROMPT`) is sent raw with doubled braces and the LLM improvises from it (battle-tested; see spec §3b) — so it is soft guidance, NOT a guarantee. The deterministic guarantee lives in `triadic_dgm/services/convergence_runner.py::enrich_personas`, which already overwrites `churn_driver`/`domain_signature` in Python for every persona. Phase 4 adds a churn-dataset predicate and, for non-churn datasets, an ADDITIVE post-step that names personas from the generic `distinguishing_signal` (Phase 2) and neutralises churn fields. Telco datasets are untouched (dual-path preserved; Phase 3c dropped).

**Tech Stack:** Python 3.10+, pytest, pandas (test fixtures only). No new dependencies.

## Global Constraints

- **Doubled-brace invariant:** `PROGRAMMER_PROMPT_V2` in `triadic_dgm/prompts/prompts.py` is sent RAW to the LLM (never `.format()`-ed). Every `{`/`}` inside it MUST stay doubled (`{{`/`}}`). Do NOT single-brace anything. (Ref: `triadic_dgm/agent/programmer.py:144-160`.)
- **Additive only:** Do NOT modify or gate the existing deterministic telco block in `enrich_personas`. New behavior is added AFTER it and only applies when `has_churn_columns(...)` is False.
- **Never-raise enrichment:** All new enrichment functions are best-effort per persona (wrapped so one bad persona never blocks a run), matching the existing `enrich_personas` style.
- **No churn/telco vocabulary in generic outputs:** generic persona names/actions must contain no "churn", "rời mạng", and not the word "Khách hàng".
- **Google-style docstrings + typing** on all new functions (CLAUDE.md).
- **DO NOT modify `data/`** (CLAUDE.md). `data_demo_golden.csv` lives at repo root (not in `data/`) and is read-only test fixture use — reading it is fine.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: `has_churn_columns` predicate

**Files:**
- Modify: `triadic_dgm/persona/dataset_profile.py` (add module-level function at end)
- Test: `tests/test_dataset_profile.py` (append)

**Interfaces:**
- Produces: `has_churn_columns(columns: Iterable[str]) -> bool` — True when the dataset carries a telco-churn signal (a `rmdt`/`churn`-like column, OR paired temporal `old_*` + `recent_*` behavioral columns).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dataset_profile.py`:

```python
from triadic_dgm.persona.dataset_profile import has_churn_columns


def test_has_churn_columns_true_on_churn_target():
    assert has_churn_columns(["age", "arpu", "RMDT"]) is True


def test_has_churn_columns_true_on_temporal_pairs():
    assert has_churn_columns(["old_complaint", "recent_complaint", "usage"]) is True


def test_has_churn_columns_false_on_neutral_dataset():
    assert has_churn_columns(["sepal_length", "sepal_width", "petal_length"]) is False


def test_has_churn_columns_false_on_recent_only():
    # A lone recent_* without a matching old_* is not a churn trajectory signal.
    assert has_churn_columns(["recent_visits", "spend"]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_dataset_profile.py -k has_churn_columns -q`
Expected: FAIL with `ImportError: cannot import name 'has_churn_columns'`

- [ ] **Step 3: Write minimal implementation**

Add at the END of `triadic_dgm/persona/dataset_profile.py`:

```python
_CHURN_TARGET_TOKENS = ("rmdt", "churn")


def has_churn_columns(columns) -> bool:
    """Detect whether a dataset carries a telco-churn / target signal.

    Used to decide (deterministically, in Python) whether the persona pipeline
    should keep the legacy telco churn path for this dataset or enforce the
    generic, dataset-agnostic path. This is the enforcement predicate for
    Phase 4 — the prompt's own mode guess is only soft steering.

    Args:
        columns: Iterable of raw column names (any case).

    Returns:
        True if a churn/target column is present (name contains ``rmdt`` or
        ``churn``) OR the dataset has paired temporal ``old_*`` and ``recent_*``
        behavioral columns (the churn-trajectory signature the telco path needs);
        False otherwise (treat as a generic dataset).
    """
    cols = [str(c).lower() for c in columns]
    if any(tok in c for c in cols for tok in _CHURN_TARGET_TOKENS):
        return True
    has_old = any(c.startswith("old_") or "_old" in c for c in cols)
    has_recent = any(c.startswith("recent_") or "_recent" in c for c in cols)
    return has_old and has_recent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_dataset_profile.py -k has_churn_columns -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add triadic_dgm/persona/dataset_profile.py tests/test_dataset_profile.py
git commit -m "feat(profile): has_churn_columns predicate for generic-vs-telco routing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `generic_persona_name`

**Files:**
- Modify: `triadic_dgm/persona/characterization.py` (add function after `compose_signal_narrative`)
- Test: `tests/test_characterization.py` (append)

**Interfaces:**
- Consumes: a persona's `distinguishing_signal` dict shape from Task-of-Phase-2 `distinguishing_signal(...)`: `{"dominant_domain": str|None, "stars": {dom: {"stars": int, "max_dev": float}}, "top_features": [{"feature": str, "label": str, "deviation": float}], "evidence": str}`.
- Produces: `generic_persona_name(sig: dict | None) -> str` — a deterministic, dataset-neutral persona name (no churn/telco vocabulary, never the word "Khách hàng").

- [ ] **Step 1: Write the failing test**

Append to `tests/test_characterization.py`:

```python
from triadic_dgm.persona.characterization import generic_persona_name


def _strong_sig():
    return {
        "dominant_domain": "usage",
        "stars": {"usage": {"stars": 4, "max_dev": 2.1}},
        "top_features": [{"feature": "usage_avg", "label": "Mức sử dụng", "deviation": 2.1}],
        "evidence": "…",
    }


def test_generic_persona_name_from_strong_signal():
    name = generic_persona_name(_strong_sig())
    assert "Mức sử dụng" in name
    assert "cao" in name
    # dataset-neutral: no telco/churn vocabulary
    assert "churn" not in name.lower()
    assert "rời mạng" not in name.lower()
    assert "Khách hàng" not in name


def test_generic_persona_name_negative_direction():
    sig = _strong_sig()
    sig["top_features"][0]["deviation"] = -1.5
    assert "thấp" in generic_persona_name(sig)


def test_generic_persona_name_weak_signal_falls_back():
    weak = {"dominant_domain": "usage", "stars": {"usage": {"stars": 1, "max_dev": 0.0}}, "top_features": [], "evidence": ""}
    assert generic_persona_name(weak) == "Nhóm chưa phân hoá rõ"


def test_generic_persona_name_none_is_safe():
    assert generic_persona_name(None) == "Nhóm chưa phân hoá rõ"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_characterization.py -k generic_persona_name -q`
Expected: FAIL with `ImportError: cannot import name 'generic_persona_name'`

- [ ] **Step 3: Write minimal implementation**

Add to `triadic_dgm/persona/characterization.py` after `compose_signal_narrative`:

```python
def generic_persona_name(sig: dict | None) -> str:
    """Deterministic, dataset-neutral persona name from a distinguishing_signal.

    Names the persona after its single most-deviating feature and direction when
    the dominant domain is distinctive (>= 3 stars), else a neutral fallback.
    Contains NO churn/telco vocabulary. Best-effort: never raises.

    Args:
        sig: A persona's ``distinguishing_signal`` dict (see
            :func:`distinguishing_signal`), or None.

    Returns:
        A short, dataset-agnostic Vietnamese persona name; the neutral
        "Nhóm chưa phân hoá rõ" when no distinctive signal is present.
    """
    fallback = "Nhóm chưa phân hoá rõ"
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
            label = t.get("label") or t.get("feature") or dom
            direction = "cao" if t.get("deviation", 0) >= 0 else "thấp"
            return f"Nhóm {label} {direction}"
        return fallback
    except Exception:
        return fallback
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_characterization.py -k generic_persona_name -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add triadic_dgm/persona/characterization.py tests/test_characterization.py
git commit -m "feat(persona): generic_persona_name from distinguishing_signal (dataset-neutral)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `enforce_generic_persona`

**Files:**
- Modify: `triadic_dgm/persona/characterization.py` (add function after `generic_persona_name`)
- Test: `tests/test_characterization.py` (append)

**Interfaces:**
- Consumes: `generic_persona_name` (Task 2); each persona is expected to already carry a `distinguishing_signal` (attached by `characterize_personas`).
- Produces: `enforce_generic_persona(personas: list[dict], profile) -> None` — mutates in place: sets a generic `persona_name` and neutralises all telco churn fields. Best-effort per persona; never raises.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_characterization.py`:

```python
from triadic_dgm.persona.characterization import enforce_generic_persona


def test_enforce_generic_persona_neutralises_churn_and_renames():
    p = {
        "persona_name": "Khách hàng âm thầm rời mạng",
        "churn_driver": "Silent Premium Churn",
        "churn_driver_evidence": "…",
        "churn_driver_confidence": "MEDIUM",
        "temporal_trajectory": [1, 2, 3],
        "domain_signature": {"value": {"stars": 5}},
        "distinguishing_signal": {
            "dominant_domain": "usage",
            "stars": {"usage": {"stars": 4, "max_dev": 2.1}},
            "top_features": [{"feature": "usage_avg", "label": "Mức sử dụng", "deviation": 2.1}],
            "evidence": "…",
        },
    }
    enforce_generic_persona([p], profile=object())
    assert p["churn_driver"] is None
    assert p["churn_driver_evidence"] is None
    assert p["churn_driver_confidence"] is None
    assert p["temporal_trajectory"] == []
    assert p["domain_signature"] == {}
    assert "rời mạng" not in p["persona_name"].lower()
    assert "Mức sử dụng" in p["persona_name"]


def test_enforce_generic_persona_is_best_effort():
    # A degenerate persona (no signal) must not raise and must still null churn.
    p = {"persona_name": "x", "churn_driver": "Y"}
    enforce_generic_persona([p], profile=object())
    assert p["churn_driver"] is None
    assert p["persona_name"] == "Nhóm chưa phân hoá rõ"


def test_enforce_generic_persona_empty_list_is_noop():
    enforce_generic_persona([], profile=object())  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_characterization.py -k enforce_generic_persona -q`
Expected: FAIL with `ImportError: cannot import name 'enforce_generic_persona'`

- [ ] **Step 3: Write minimal implementation**

Add to `triadic_dgm/persona/characterization.py` after `generic_persona_name`:

```python
def enforce_generic_persona(personas: list[dict], profile) -> None:
    """Force personas onto the generic, dataset-agnostic path, in place.

    Applied by the enrichment layer ONLY for non-churn datasets
    (see :func:`triadic_dgm.persona.dataset_profile.has_churn_columns`). For
    each persona it sets a generic ``persona_name`` from the persona's
    ``distinguishing_signal`` and neutralises every telco churn field so
    downstream (report_generator ``is_post_churn`` detection, feed, UI) renders
    generically regardless of what the improvising LLM emitted. This is the
    deterministic guarantee behind Phase 4. Best-effort per persona; never raises.

    Args:
        personas: Persona dicts to mutate in place.
        profile: Active DatasetProfile (accepted for symmetry / future use).
    """
    if not personas:
        return
    for p in personas:
        try:
            p["persona_name"] = generic_persona_name(p.get("distinguishing_signal"))
            p["churn_driver"] = None
            p["churn_driver_evidence"] = None
            p["churn_driver_confidence"] = None
            p["temporal_trajectory"] = []
            p["domain_signature"] = {}
        except Exception:
            continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_characterization.py -k enforce_generic_persona -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add triadic_dgm/persona/characterization.py tests/test_characterization.py
git commit -m "feat(persona): enforce_generic_persona neutralises churn + applies generic name

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Wire generic enforcement into `enrich_personas`

**Files:**
- Modify: `triadic_dgm/services/convergence_runner.py` (imports + one additive block inside `enrich_personas`)
- Test: `tests/test_enrich_generic.py` (create)

**Interfaces:**
- Consumes: `has_churn_columns` (Task 1), `enforce_generic_persona` (Task 3).
- Behavior: In `enrich_personas`, immediately AFTER the `characterize_personas(...)` block and BEFORE `llm_narrative_by_cluster: dict = {}`, add generic enforcement gated on a non-churn profile. The existing deterministic telco block is left EXACTLY as-is (additive — its churn output is simply overwritten to None for generic datasets).

- [ ] **Step 1: Write the failing test**

Create `tests/test_enrich_generic.py`:

```python
"""Integration: enrich_personas routes non-churn datasets to the generic path."""
from triadic_dgm.services import convergence_runner
from triadic_dgm.persona.dataset_profile import DatasetProfile


class _FakeReportGen:
    """Minimal ReportGenerator stand-in: only what enrich_personas touches."""

    def _get_means(self, p):
        return p.get("feature_means", {})

    def generate_llm_narrative(self, *a, **k):
        raise RuntimeError("no LLM in test")  # force deterministic fallback

    def _build_persona_story(self, *a, **k):
        return None


def _generic_profile():
    return DatasetProfile(
        dataset_name="demo",
        fingerprint="deadbeef",
        labels={"sepal_length": "Sepal length", "petal_width": "Petal width"},
        behavioral_features=["sepal_length", "petal_width"],
        domains={"sepal": ["sepal_length"], "petal": ["petal_width"]},
    )


def test_enrich_personas_generic_dataset_neutralises_churn():
    personas = [
        {"cluster_id": 0, "support": 100, "support_pct": 0.6,
         "feature_means": {"sepal_length": 6.5, "petal_width": 2.0}},
        {"cluster_id": 1, "support": 60, "support_pct": 0.4,
         "feature_means": {"sepal_length": 4.8, "petal_width": 0.2}},
    ]
    convergence_runner.enrich_personas(personas, _FakeReportGen(), profile=_generic_profile())
    for p in personas:
        assert p.get("churn_driver") is None
        assert p.get("persona_name")  # a generic name was set
        assert "rời mạng" not in str(p.get("persona_name", "")).lower()
        assert "distinguishing_signal" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_enrich_generic.py -q`
Expected: FAIL — `churn_driver` is not None (the telco block set it and nothing neutralised it yet).

- [ ] **Step 3a: Add imports**

In `triadic_dgm/services/convergence_runner.py`, find the existing characterization import (it already imports `characterize_personas`) and extend it, and add the profile import. The existing line looks like:

```python
from triadic_dgm.persona.characterization import characterize_personas
```

Replace with:

```python
from triadic_dgm.persona.characterization import characterize_personas, enforce_generic_persona
from triadic_dgm.persona.dataset_profile import has_churn_columns
```

(If `characterize_personas` is imported on a multi-name line or differently, keep the existing style — just add `enforce_generic_persona` to it and add the `has_churn_columns` import near the other `dataset_profile` imports.)

- [ ] **Step 3b: Add the additive enforcement block**

In `enrich_personas`, locate this existing block:

```python
    if profile is not None:
        try:
            characterize_personas(personas, global_means, profile, means_getter=report_gen._get_means)
        except Exception as e:
            print(f"[convergence] characterize_personas failed (non-fatal): {e}")

    llm_narrative_by_cluster: dict = {}
```

Insert the new block BETWEEN the `characterize_personas` block and `llm_narrative_by_cluster`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_enrich_generic.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full enrichment/characterization/feed regression + import smoke**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_characterization.py tests/test_dataset_profile.py tests/test_feed_generic.py tests/test_narrative.py tests/test_enrich_generic.py -q && python3 -c "from triadic_dgm.services import convergence_runner; print('import OK')"`
Expected: PASS (all green) + `import OK`

- [ ] **Step 6: Commit**

```bash
git add triadic_dgm/services/convergence_runner.py tests/test_enrich_generic.py
git commit -m "feat(convergence): route non-churn datasets to generic persona path (additive)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: De-churn the task prompt (best-effort steering)

**Files:**
- Modify: `triadic_dgm/services/convergence_runner.py` (`build_task_prompt` body + docstring)
- Test: `tests/test_task_prompt.py` (create)

**Interfaces:**
- Behavior unchanged signature: `build_task_prompt(features: list[str]) -> str`. New: contains no "churn"; still recognised by `SemanticVerifier.is_business_task`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_prompt.py`:

```python
from triadic_dgm.services.convergence_runner import build_task_prompt
from triadic_dgm.agent.verifier import SemanticVerifier


def test_task_prompt_has_no_churn_word():
    assert "churn" not in build_task_prompt(["f1", "f2"]).lower()


def test_task_prompt_still_lists_features_in_order():
    p = build_task_prompt(["alpha", "beta"])
    assert "alpha, beta" in p


def test_task_prompt_still_recognised_as_business_task():
    # SemanticVerifier.__init__ only stores an openai client config (no network);
    # is_business_task is pure keyword matching.
    v = SemanticVerifier(api_key="test-key-unused")
    assert v.is_business_task(build_task_prompt(["f1"])) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_task_prompt.py -q`
Expected: FAIL on `test_task_prompt_has_no_churn_word` (current prompt says "churn").

- [ ] **Step 3: Rewrite `build_task_prompt`**

In `triadic_dgm/services/convergence_runner.py`, replace the `build_task_prompt` body and de-churn its docstring. New version:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_task_prompt.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add triadic_dgm/services/convergence_runner.py tests/test_task_prompt.py
git commit -m "feat(convergence): de-churn build_task_prompt (dataset-agnostic wording)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Prompt steering — GENERIC default + generic actions branch

**Files:**
- Modify: `triadic_dgm/prompts/prompts.py` (mode-detection block ~lines 582-592; `generate_actions` ~line 714)
- Test: `tests/test_prompt_invariant.py` (create)

**Interfaces:**
- Behavior: soft steering only (LLM improvises; see Global Constraints). The hard guarantee is Task 4. This task's tests assert the doubled-brace invariant is preserved and no single-brace regression was introduced.

**CRITICAL:** Keep every brace doubled (`{{`/`}}`). Do NOT single-brace.

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompt_invariant.py`:

```python
import re
from triadic_dgm.prompts import prompts


def _v2_body() -> str:
    src = open(prompts.__file__, encoding="utf-8").read()
    m = re.search(r"PROGRAMMER_PROMPT_V2 = '''(.*?)'''", src, re.S)
    assert m, "PROGRAMMER_PROMPT_V2 triple-single-quoted block not found"
    return m.group(1)


def test_programmer_prompt_braces_balanced_and_doubled():
    body = _v2_body()
    # The raw prompt convention: every brace is doubled. Counts must match and be non-trivial.
    assert body.count("{{") == body.count("}}")
    assert body.count("{{") >= 50  # guards against an accidental single-brace edit


def test_programmer_prompt_documents_generic_default():
    # Soft-steering assertion: the mode block now names GENERIC as the default.
    assert "GENERIC" in _v2_body()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_prompt_invariant.py -q`
Expected: FAIL on `test_programmer_prompt_documents_generic_default` ("GENERIC" not yet present).

- [ ] **Step 3a: Steer the mode-detection block**

In `triadic_dgm/prompts/prompts.py`, find the mode-detection code block (currently):

```python
if has_churn_target:
    dataset_mode = "PRE_CHURN"
else:
    dataset_mode = "POST_CHURN"
```

Replace it with (note: this is reference code inside the raw prompt — plain single braces are fine here because this specific snippet has none; keep it exactly as shown):

```python
has_churn_signal = has_churn_target or any(
    str(c).lower().startswith("old_") for c in data.columns
) and any(str(c).lower().startswith("recent_") for c in data.columns)

if has_churn_target:
    dataset_mode = "PRE_CHURN"
elif has_churn_signal:
    dataset_mode = "POST_CHURN"
else:
    dataset_mode = "GENERIC"
```

Then, in the surrounding Vietnamese instruction text just above it (the paragraph starting "XÁC ĐỊNH DATASET_MODE ..."), change the sentence "MẶC ĐỊNH LÀ POST_CHURN" to state that the default is now `GENERIC`, and POST_CHURN activates only when a churn/target signal (`has_churn_target`, or paired `old_*`/`recent_*` columns) is detected or the user explicitly says the data is churned. Keep all existing `{{`/`}}` in that paragraph untouched.

- [ ] **Step 3b: Add a GENERIC branch to `generate_actions`**

In `generate_actions` (reference code in the prompt), the current structure is `if dataset_mode == "POST_CHURN": ... else: ...`. Add a GENERIC branch BEFORE the `else`. Find:

```python
    if dataset_mode == "POST_CHURN":
```

...and its matching `else:` (the ACTIVE/PRE_CHURN branch). Insert, immediately before that `else:`:

```python
    elif dataset_mode == "GENERIC":
        actions.extend([
            "Phân tích sâu các đặc điểm nổi bật của nhóm để hiểu hành vi đặc trưng",
            "Xây dựng chiến lược tiếp cận phù hợp với đặc trưng của nhóm",
        ])
```

(No braces are introduced by this snippet, so no doubling concern. Do not alter surrounding lines.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_prompt_invariant.py -q && python3 -c "import triadic_dgm.prompts.prompts as p; print('prompt import OK, PROGRAMMER_PROMPT len', len(p.PROGRAMMER_PROMPT))"`
Expected: PASS (2 passed) + `prompt import OK, ...`

- [ ] **Step 5: Commit**

```bash
git add triadic_dgm/prompts/prompts.py tests/test_prompt_invariant.py
git commit -m "feat(prompt): steer default to GENERIC mode + generic actions branch (soft, braces intact)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Acceptance — deterministic end-to-end on `data_demo_golden.csv`

**Files:**
- Test: `tests/test_phase4_acceptance.py` (create)

**Interfaces:**
- Consumes: `build_profile`/`load_or_build_cached` from `dataset_profile.py` (Phase 1), `enrich_personas` (Task 4). Verifies the whole DETERMINISTIC Python path on a real non-telco CSV, without any LLM call.

**Note:** This validates the Phase 4 guarantee end-to-end for the layer we control. A full live-LLM convergence run on the demo dataset is a separate MANUAL smoke (documented in Step 4) — it needs the agent/sandbox/LLM and is not a fast unit test.

- [ ] **Step 1: Write the acceptance test**

Create `tests/test_phase4_acceptance.py`:

```python
"""Phase 4 acceptance: a real non-telco CSV runs the deterministic path generically."""
import os
import pandas as pd
import pytest

from triadic_dgm.persona.dataset_profile import build_profile, has_churn_columns
from triadic_dgm.services import convergence_runner

_CSV = os.path.join(os.path.dirname(__file__), "..", "data_demo_golden.csv")


class _FakeReportGen:
    def _get_means(self, p):
        return p.get("feature_means", {})

    def generate_llm_narrative(self, *a, **k):
        raise RuntimeError("no LLM in acceptance test")

    def _build_persona_story(self, *a, **k):
        return None


@pytest.mark.skipif(not os.path.exists(_CSV), reason="data_demo_golden.csv fixture not present")
def test_demo_golden_is_generic_and_produces_clean_personas():
    df = pd.read_csv(_CSV)
    profile = build_profile(df)

    # The demo dataset must be recognised as NON-churn.
    assert has_churn_columns(profile.labels.keys()) is False

    # Simulate two clusters the way the pipeline hands them to enrich_personas.
    feats = profile.behavioral_features[:4] or list(profile.labels.keys())[:4]
    gmean = {f: float(df[f].mean()) for f in feats if f in df.columns}
    hi = {f: gmean[f] * 1.8 for f in gmean}
    lo = {f: gmean[f] * 0.4 for f in gmean}
    personas = [
        {"cluster_id": 0, "support": 100, "support_pct": 0.6, "feature_means": hi},
        {"cluster_id": 1, "support": 60, "support_pct": 0.4, "feature_means": lo},
    ]

    convergence_runner.enrich_personas(personas, _FakeReportGen(), profile=profile)

    for p in personas:
        assert p.get("churn_driver") is None
        assert p.get("temporal_trajectory") == []
        assert p.get("distinguishing_signal") is not None
        name = str(p.get("persona_name", ""))
        assert name and "rời mạng" not in name.lower() and "churn" not in name.lower()
```

- [ ] **Step 2: Run the acceptance test**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_phase4_acceptance.py -q`
Expected: PASS (1 passed). If `data_demo_golden.csv` is absent the test SKIPS (not a failure) — in that case note it in the review.

- [ ] **Step 3: Run the WHOLE Phase 4 + regression suite**

Run: `cd /home/anlnm/anlnm/data-agent/data-agent && python3 -m pytest tests/test_dataset_profile.py tests/test_characterization.py tests/test_enrich_generic.py tests/test_task_prompt.py tests/test_prompt_invariant.py tests/test_phase4_acceptance.py tests/test_feed_generic.py tests/test_narrative.py -q`
Expected: PASS (all green).

- [ ] **Step 4: Document the manual live-LLM smoke (no code)**

Record in the task report (do NOT run automatically — needs the live agent/sandbox/LLM, and per project memory the convergence loop runs in a Docker image that needs a rebuild to pick up host edits): to verify end-to-end with the real LLM, run one convergence iteration against `data_demo_golden.csv` and confirm the produced feed shows generic persona names + `signal_narrative` and no `churn_driver`. State clearly in the report that this manual smoke was NOT executed here.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase4_acceptance.py
git commit -m "test(phase4): deterministic acceptance on data_demo_golden.csv (generic path)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §4.5 churn-signal predicate → Task 1. ✓
- §4.5 generic namer → Task 2. ✓
- §4.5 generic-mode enforcement (name + neutralise churn) → Task 3. ✓
- §4.5 wiring in `enrich_personas` (gated on `has_churn_columns`) → Task 4. ✓
- §4.4 verifier: no code change, recognition regression test → Task 5. ✓
- §4.3 / §4.6 de-churn task prompt → Task 5. ✓
- §4.6 prompt steering (GENERIC default + generic actions) → Task 6. ✓
- §5 prompt-invariant smoke (balanced doubled braces) → Task 6. ✓
- §5 acceptance on `data_demo_golden.csv` (deterministic) + manual live-LLM note → Task 7. ✓
- §5 regression (telco path intact; existing suites green) → Task 4 Step 5 + Task 7 Step 3. Telco non-regression is structural: `enforce_generic_persona` runs only when `has_churn_columns` is False, and Task 4 leaves the telco block byte-identical. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code and an exact command with expected output. ✓

**Type consistency:** `has_churn_columns(columns) -> bool` (Task 1) consumed in Task 4 with `getattr(profile, "labels", {}).keys()`. `generic_persona_name(sig) -> str` (Task 2) consumed by `enforce_generic_persona` (Task 3). `enforce_generic_persona(personas, profile) -> None` (Task 3) consumed in Task 4. `DatasetProfile(...)` fields in tests match the dataclass (`dataset_name, fingerprint, labels, behavioral_features, domains`). ✓
