# Notebook observation loop (PoC)

The backend chat path uses one decision agent and one broad execution tool: the existing
stateful Jupyter kernel. It no longer asks the model to generate the complete analysis and
persona pipeline in one script.

```text
user message
    -> DecisionAgent
        -> ASK_USER ----------- pause until the next user turn
        -> PROPOSE_PLAN ------- pause until approval/revision
        -> EXECUTE_PYTHON ----- run one cell in the live notebook
                                  |
                                  +-- NOTEBOOK_OBSERVATION -> DecisionAgent
        -> FINAL_ANSWER ------- finish
```

## Action contract

Every model turn returns exactly one JSON object:

- `ASK_USER`: `question` and 2–4 distinct `options` are required. The UI adds `Other`.
- `PROPOSE_PLAN`: a non-empty `plan` array is required.
- `EXECUTE_PYTHON`: `code` is required; `description` is optional.
- `FINAL_ANSWER`: `answer` is required.

`EXECUTE_PYTHON` is intentionally broad. Code can import libraries, inspect the workspace,
reuse notebook variables, define and call functions, generate plots, and save artifacts. The
controller does not route Python operations into separate fixed tools.

After every cell, the controller appends a real observation containing success/failure and
kernel output to the same agent conversation. A traceback therefore enters the normal loop;
there is no separate hard-coded Programmer repair loop in this path.

## Context budget and compaction

The hosted model exposes a 32k-token total context window. Each decision reserves at most
6k output tokens and keeps a 2k safety margin. When the accumulated prompt reaches an
estimated 20k tokens, old action/observation turns are summarized into one
`[COMPACTED_WORKING_MEMORY]` system message. The four newest messages remain verbatim.

The summary preserves the user goal, decisions, dataset/schema references, accepted plan,
live notebook variables and files, verified results, unresolved errors, and next step. Full
old code and verbose cell output are omitted because the stateful Jupyter kernel retains the
actual execution state. If the summary request fails, a bounded head/tail excerpt is retained
instead, so compaction failure does not abort the agent loop.

The chat header shows a live context ring fed by backend SSE telemetry. It displays usage
against the 32k window, changes from green to amber/red near the 20k compaction threshold,
and shows how many compactions have occurred. Hovering it reveals exact token estimates.

## Main implementation points

- `triadic_dgm/agent/action_protocol.py`: parsing and validation.
- `triadic_dgm/agent/programmer.py`: `DecisionAgent` model client (`Programmer` remains an alias
  for compatibility).
- `triadic_dgm/prompts/prompts.py`: observation-loop control prompt.
- `triadic_dgm/engine.py`: action dispatcher and notebook observation loop.
- `api/routers/chat.py`: SSE rendering and human pause status.

The old implementation remains available as `TriadicAgent.stream_workflow_legacy()` during
the PoC transition.

## Human decision bar

When `ASK_USER` pauses the loop, the backend emits a structured `human_decision` SSE event
instead of encoding buttons in Markdown. The chat composer displays the model-generated
options and appends an `Other` button with a free-text input. Selecting or typing an answer
sends a normal user turn back to the same preserved agent conversation, which resumes the
observation loop. Older plain chat questions remain readable, while malformed `ASK_USER`
actions are returned to the model for protocol correction.

## ML framework boundary

The user-facing H2O ML Studio remains separate from this observation loop. The notebook
environment instead provides FLAML as an optional Agent capability: the Agent can prepare a
pandas DataFrame in memory and call `flaml.AutoML.fit()` directly without registering it with
the H2O service. The prompt does not force AutoML, and it tells the Agent to keep an untouched
test set and apply learned preprocessing/resampling to training data only. H2O remains the
managed website workflow and must not be started from the Agent notebook.

The backend intentionally installs `flaml`, `lightgbm`, the minimal official `xgboost-cpu`
package and scikit-learn rather than the GPU-heavy `flaml[automl]` dependency resolution.
Agent runs can use `lgbm`, `xgboost`, `rf` and `extra_tree`; CatBoost remains optional and is
not part of the PoC image.

## Repository layout

The customized RLM runtime is checked into `vendor/rlm` using `git subtree`. The backend
loads that source through `PYTHONPATH=/app/vendor/rlm:/app`; it does not require a sibling
`../rlm` checkout. A fresh clone of this repository therefore contains the agent wrapper,
the H2O framework, and the exact RLM implementation used at runtime.
