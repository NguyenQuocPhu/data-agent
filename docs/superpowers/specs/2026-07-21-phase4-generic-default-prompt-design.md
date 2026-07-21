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

## 4. Design

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

### 4.4 Verifier — keep telco safety nets, don't block generic

The RMDT / khu_vuc leakage rules stay (they only fire on telco column names, inert elsewhere).
Optionally guard them behind an explicit "telco columns present" condition for clarity, but no
behavioral change for non-telco datasets is required. Trigger keywords remain a superset that
includes generic words (`persona`, `cluster`, `phân cụm`, `segment`); `churn` stays harmlessly.

## 5. Testing

- **Unit (primary lever):** extract the pure embedded functions (`apply_business_rules`,
  `generate_actions`, and the mode-detection snippet) and `exec`/import them in a test.
  Assert: a non-churn/no-target column set → `GENERIC`; churn/target columns → `POST_CHURN`;
  the GENERIC branch of `generate_actions`/`apply_business_rules` contains no churn vocabulary and
  emits no `churn_driver` key.
- **Prompt-parse smoke:** the embedded function bodies still parse/exec cleanly after the edit
  (guards against breaking the giant `.format()` string).
- **Acceptance (main):** run the pipeline on `data_demo_golden.csv` (non-telco) → personas with
  generic names + `distinguishing_signal`, no `churn_driver`, no crash / no missing-telco-column
  error.
- **Regression:** a telco dataset still resolves to `POST_CHURN`, `churn_driver` present; existing
  convergence/feed/characterization tests stay green. Byte-compare the POST_CHURN branch output to
  confirm telco path unchanged.

## 6. Risks & mitigation

- **Prompt is an un-compiled `.format()` string the LLM executes.** Mitigate with surgical edits
  (add branches + flip default; no restructuring), the prompt-parse smoke test, and telco
  byte-comparison.
- **`{`/`}` escaping in the prompt string:** any new dict/set literal added to the embedded code
  must be doubled (`{{`/`}}`) to survive `.format()`. Covered by the parse smoke test.
- **Duplication with `report_generator.py`:** the embedded functions partly mirror
  report_generator logic. Phase 4 does NOT dedupe this (that is Phase 3d / report_generator scope,
  explicitly out of scope); it only adds the GENERIC branch in-prompt.

## 7. Out of scope (future)

- `report_generator.py` internal refactor / POST_CHURN extraction (Phase 3d).
- UI relabel (`persona-cards.tsx`, `persona-dashboard.tsx`).
- Deduping embedded prompt functions against `report_generator.py`.
