# Phase 4 — Generic-default persona-analysis prompt (churn as auto-detected specialization)

Date: 2026-07-21
Parent spec: `docs/superpowers/specs/2026-07-20-persona-core-dataset-agnostic-design.md`
Depends on: Phase 1 (`DatasetProfile`), Phase 2 (`characterization.py` generic signal), Phase 3a+3b (feed surfaces `distinguishing_signal`/`signal_narrative`).

## 1. Problem

The persona-generation prompt (`triadic_dgm/prompts/prompts.py`) hardcodes telco churn as the
**default** analysis mode. Concretely, `PROGRAMMER_PROMPT_V2` instructs the LLM:

> MẶC ĐỊNH LÀ POST_CHURN (trừ khi có `has_churn_target` → PRE_CHURN)

So EVERY dataset run through the pipeline is analysed as "khách hàng đã rời mạng" (post-churn),
computing `churn_driver`, temporal `old_*`/`recent_*` trajectories, and churn-framed actions
("giữ chân") — even for datasets with no churn concept at all. This is the last place the system
is still hardcoded to the telco dataset that a NEW dataset actually feels.

The dataset-agnostic **capability** was already delivered by Phases 1–3ab (generic
`distinguishing_signal`/`signal_narrative` computed in Python via `characterization.py` and
surfaced in the feed). Phase 4 makes the **generation prompt** stop assuming churn.

## 2. Decisions (locked with user, 2026-07-21)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Churn analysis fate | **Conditional mode** — GENERIC is the new default; churn (POST_CHURN/PRE_CHURN) auto-activates only when a churn/target signal is detected | Reconciles "generalize prompt" with "keep telco path" (Phase 3c dropped). Telco data still gets rich churn analysis; other datasets get generic. |
| Scope | **Generation side only** — task prompt + `PROGRAMMER_PROMPT` + verifier | Enough for a new dataset to run end-to-end without telco distortion. `report_generator` internals and UI relabel are separate later work. |
| Characterization location | **Stay in Python** (`characterization.py`) — do NOT duplicate signal logic into the prompt | Single source of truth (DRY/SOLID). Generic-mode prompt only clusters + names + basic stats; the rich signal is the Python enrichment already built in Phase 2–3. |

## 3. Key facts verified in code (grounding)

- `prompts.py` §"XÁC ĐỊNH DATASET_MODE" (~lines 582–599): default = `POST_CHURN`; only flips on
  `has_churn_target` / explicit user statement. `churn_drivers` already gated:
  `... if dataset_mode == "POST_CHURN" else {}` (line ~599).
- `apply_business_rules(..., dataset_mode=...)` (line ~69) and `generate_actions(dataset_mode, ...)`
  (line ~714) branch on `dataset_mode == "POST_CHURN"`; the `else` today is the telco-flavored
  ACTIVE/PRE_CHURN framing (churn RISK), not a neutral generic branch.
- `report_generator.py` already auto-detects: `is_post_churn = any(p.get('churn_driver') for p in personas_data)`
  (line ~1738). A persona with **no** `churn_driver` → report_generator's generic branch. So
  GENERIC-mode output needs no change to report_generator to render — it degrades correctly.
- `verifier.py` leakage rules are column-name-gated: RMDT check (line ~181) fires only when
  `"RMDT" in code`; `khu_vuc` geography check (line ~188) only when `"khu_vuc" in code`. On a
  non-telco dataset these are **inert** (do not block). They are telco safety nets, not blockers.
- `build_task_prompt(features)` (`convergence_runner.py` line ~262) currently says "persona khách
  hàng churn ... churn driver". `verifier.is_business_task()` trigger keywords already include
  `persona`, `phân cụm`, `cluster`, `segment` (not only `churn`), so de-churning the task prompt
  does not break task recognition.

## 3b. Critical discovery (2026-07-21, during plan-writing) — prompt is soft guidance, not executed code

`triadic_dgm/agent/programmer.py:144-160` (`clear()`) documents a battle-tested invariant:
`PROGRAMMER_PROMPT` is sent to the LLM **RAW, with doubled braces `{{`/`}}`**, and is
**deliberately NOT `.format()`-ed**. The embedded reference functions (`apply_business_rules`,
`classify_churn_driver`, `generate_actions`, the mode-detection snippet) are therefore
**syntactically malformed** in what the LLM receives (`profile = profile or {{}}`), so the LLM
**cannot copy them verbatim and improvises its own clustering code**. Confirmed live: 358 healthy
convergence runs on the raw (doubled-brace) prompt on 07-14; switching to `.format()` (valid braces
→ LLM copies the canonical pipeline verbatim incl. fragile Stage-2 gates) made 100% of runs
hard-stop to "Clustering Failed".

**Consequences — two spec assumptions are now void:**
- The embedded functions do NOT run deterministically in production. Unit-testing them by
  extract-and-`exec` (former §5) tests something the system never executes → dropped.
- Editing the prompt's default `dataset_mode` is **soft steering** of an improvising LLM, NOT a
  deterministic guarantee. It cannot by itself guarantee a non-telco dataset emits no `churn_driver`.

**Design pivot (user-approved 2026-07-21): "prompt steering + Python enforcement".**
Prompt edits remain (best-effort steering, keeping the doubled-brace convention intact), but the
**deterministic guarantees move to the Python enrichment layer** (`characterization.py` +
`convergence_runner.enrich_personas`), which we control and can unit-test. This also reinforces the
locked decision "characterization stays in Python, not duplicated into the prompt".

## 4. Design

> Superseded-in-part by §3b: the prompt-side items below (4.1, 4.2's naming) are now **best-effort
> steering**; the **deterministic** behavior is enforced in Python (see §4.5 Python enforcement).

### 4.1 New GENERIC mode (the new default)

In `PROGRAMMER_PROMPT_V2` mode-detection block:

- Introduce `dataset_mode = "GENERIC"` as the default.
- Detect a churn/target signal → switch to POST_CHURN (or PRE_CHURN as today) when ANY of:
  - churn/target columns present (e.g. temporal `old_*`/`recent_*` pairs, or `has_churn_target`), OR
  - the user's request/conversation explicitly states the data is churned / active customers.
- If no such signal → stay `GENERIC`.
- The existing ACTIVE / BEHAVIOR_PLUS_FEE override paths (explicit active-customer statements)
  are preserved unchanged.

### 4.2 GENERIC branches in the two embedded business functions

- `apply_business_rules`: add a `GENERIC` branch — `persona_name` derived from the cluster's
  dominant generic signal (dominant domain / top deviating feature), `priority_score` from
  `support_pct` (no churn confidence), NO `churn_driver*`/`temporal_trajectory` keys emitted.
- `generate_actions`: add a `GENERIC` branch — neutral, dataset-agnostic recommendations
  (e.g. "phân tích sâu nhóm", "tiếp cận/thử nghiệm") with NO churn vocabulary ("giữ chân",
  "rời mạng").
- Ensure the telco-only heavy computations (`compute_churn_drivers`/`classify_churn_driver`,
  telco 6-domain `compute_domain_signature`, `get_temporal_trajectory`) are **skipped** in
  GENERIC mode (churn_drivers already gated; extend the same guard to domain_signature/temporal
  where they are churn-specific).

Net effect: a GENERIC persona JSON carries `persona_name`, `support`/`support_pct`,
`profile_attributes` (keyword-based, already dataset-agnostic), basic cluster stats — and **no**
`churn_driver`. Downstream: `report_generator` renders generic; the feed adds
`distinguishing_signal`/`signal_narrative` from the Python enrichment (Phase 2–3). No duplication
of characterization into the prompt.

### 4.3 De-churn the task prompt

`build_task_prompt(features)`: rewrite instruction to neutral persona analysis — "phân tích
persona / phân khúc khách hàng", "mô tả từng nhóm", drop "churn driver". Keep the feature-list
injection (Phase 1) and the trigger words `persona`/`phân cụm` so `is_business_task()` still
recognises it.

### 4.4 Verifier — no code change needed

`is_business_task()` trigger keywords already include `persona`, `cluster`, `phân cụm`, `segment`
(`verifier.py:20-21`), so the de-churned task prompt is still recognised. The RMDT / khu_vuc
leakage rules are column-name-gated (fire only when those telco names appear in generated code),
so they are inert on non-telco datasets and need no change. Phase 4 adds only a **regression test**
asserting the new task prompt is still recognised — no verifier code edit.

### 4.5 Python enforcement (the deterministic layer — where guarantees live)

This is the core of the pivot (§3b). All items are in the Python enrichment path we control and are
unit-testable.

- **Churn-signal predicate** — `has_churn_columns(columns) -> bool` in `dataset_profile.py`: True
  when the dataset carries a recognisable churn/target signal (a `rmdt`/`churn`-like target column,
  or paired temporal `old_*`/`recent_*` behavioral columns). Telco data → True; a neutral dataset
  (iris/demo-golden) → False.
- **Generic namer** — `generic_persona_name(sig: dict) -> str` in `characterization.py`: a
  deterministic, dataset-neutral name from a persona's `distinguishing_signal` (top deviating
  feature label + direction when the dominant domain is distinctive; a neutral
  "Nhóm chưa phân hoá rõ" fallback otherwise). No churn/telco vocabulary.
- **Generic-mode enforcement** — `enforce_generic_persona(personas, profile) -> None` in
  `characterization.py`: applied ONLY when `has_churn_columns(...)` is False. For each persona it
  (a) sets `persona_name = generic_persona_name(persona["distinguishing_signal"])`, and
  (b) neutralises any churn fields the LLM may have improvised (`churn_driver`,
  `churn_driver_evidence`, `churn_driver_confidence`, `temporal_trajectory`, and `narrative` →
  set to None/empty) so downstream (`report_generator` `is_post_churn`, feed) renders generic.
  Never raises; best-effort per persona.
- **Wiring** — `convergence_runner.enrich_personas`: after the existing `characterize_personas(...)`
  call, if `not has_churn_columns(profile...)` call `enforce_generic_persona(personas, profile)`.
  Telco path (churn dataset) is untouched — dual-path preserved (Phase 3c dropped).

### 4.6 Prompt steering (best-effort — keep doubled-brace convention)

Soft nudges only; MUST preserve the `{{`/`}}` doubling (do NOT single-brace — that is the
battle-tested invariant, §3b):
- Mode-detection block (~lines 582-592): make `GENERIC` the documented default; POST_CHURN/PRE_CHURN
  described as activating on a detected churn/target signal.
- `generate_actions` (~line 714): add a `GENERIC` reference branch with neutral, dataset-agnostic
  actions and no churn vocabulary.
- `build_task_prompt` (`convergence_runner.py:262`): de-churn the instruction (§4.3), keep the
  `persona`/`phân cụm` trigger words and the feature-list injection.

## 5. Testing

- **Unit (primary lever — deterministic Python):**
  - `has_churn_columns`: True on telco-ish columns (`rmdt`, `old_*`/`recent_*` pairs), False on a
    neutral column set.
  - `generic_persona_name`: distinctive signal → dataset-neutral name containing no churn/telco
    words and no "Khách hàng"; weak/empty signal → the neutral fallback.
  - `enforce_generic_persona`: on a generic dataset, a persona carrying an LLM-improvised
    `churn_driver` gets it neutralised and `persona_name` replaced from its signal; on a churn
    dataset the function is not applied and telco fields stay intact.
  - Verifier recognition: `is_business_task(build_task_prompt([...]))` is True after de-churning.
- **Prompt-invariant smoke:** `PROGRAMMER_PROMPT_V2` still has balanced doubled braces
  (`count('{{') == count('}}')`) after the edit — guards the raw-prompt invariant (§3b).
- **Acceptance (behavioral, documented run — not a fast unit test):** run the pipeline on
  `data_demo_golden.csv` (non-telco) → personas with generic names + `distinguishing_signal`, no
  `churn_driver`, no crash / no missing-telco-column error.
- **Regression:** existing convergence/feed/characterization/dataset_profile tests stay green; on a
  telco dataset `enforce_generic_persona` is NOT applied so `churn_driver` and telco naming remain.

## 6. Risks & mitigation

- **Prompt is raw guidance the LLM improvises from, NOT executed code (§3b).** So prompt edits are
  best-effort; the guarantees live in the Python enforcement layer (§4.5). Mitigate LLM
  non-determinism by making Python the enforcement point (neutralise churn fields regardless of
  what the LLM emits).
- **Doubled-brace invariant (§3b):** the prompt MUST keep `{{`/`}}` doubled — do NOT "fix" braces.
  Any new dict/set literal added to the embedded reference code must also be doubled. Guarded by the
  prompt-invariant smoke test (`count('{{') == count('}}')`).
- **Telco regression via Python enforcement:** `enforce_generic_persona` must run ONLY when
  `has_churn_columns` is False, so telco personas are never renamed/neutralised. Guarded by the
  churn-dataset regression test.
- **Duplication with `report_generator.py`:** the embedded reference functions partly mirror
  report_generator logic. Phase 4 does NOT dedupe this (Phase 3d / report_generator scope, out of
  scope).

## 7. Out of scope (future)

- `report_generator.py` internal refactor / POST_CHURN extraction (Phase 3d).
- UI relabel (`persona-cards.tsx`, `persona-dashboard.tsx`).
- Deduping embedded prompt functions against `report_generator.py`.
