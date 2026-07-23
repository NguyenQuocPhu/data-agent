"""Background loop that repeatedly runs the persona pipeline against a fixed dataset,
persisting each run's personas for convergence monitoring across runs.

Runs on its own dedicated TriadicAgent instance (own kernel, own working dir, own RIMRULE
archive) — never the shared `lambda_instance.conv` singleton every interactive chat request
uses, since TriadicAgent.clear()/stream_workflow() are not safe to run concurrently with a
live user conversation (they mutate shared in-place state: messages, kernel, working files).
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time

import pandas as pd

from triadic_dgm.engine import TriadicAgent
from triadic_dgm.persona.dataset_profile import load_or_build_cached
from triadic_dgm.services.convergence_feed import build_feed_items, render_markdown
from triadic_dgm.services.convergence_runner import build_task_prompt, run_once
from triadic_dgm.services.convergence_store import init_db, save_run
from triadic_dgm.services.report_generator import ReportGenerator

from .workspace import resolve_workspace_root

CONVERGENCE_SESSION_ID = "convergence"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "cache", "convergence", "convergence.db")
DEFAULT_SESSION_CACHE_PATH = os.path.join(REPO_ROOT, "cache", "convergence", "kernel_cache")
DEFAULT_PROFILES_DIR = os.path.join(REPO_ROOT, "cache", "convergence", "profiles")

# Idle-loop responsiveness for stop() — NOT a run cadence delay. The next run starts
# immediately after the previous one finishes (per the "continuous loop" requirement);
# this timeout only bounds how quickly stop() can interrupt an idle wait.
_STOP_POLL_INTERVAL = 0.5


def _build_tool_layer_code(workspace_root: str) -> str:
    """Same load_dataset()/list_datasets() injection api/dependencies.py performs for the
    'default' workspace, parameterized for the dedicated 'convergence' workspace instead.
    Deliberately duplicated rather than imported from dependencies.py — that module builds
    it as a module-level f-string tied to the 'default' workspace at import time, not a
    reusable function; duplicating a small, stable code-gen template is lower-risk than
    refactoring a working, already-injected script."""
    safe_workspace_dir = str(workspace_root).replace("\\", "/")
    _SAFE_REPO_ROOT_CONV = str(REPO_ROOT).replace("\\", "/")
    return f"""
import sys
# Put the repo on the sandbox kernel's path: it runs with cwd set to the session cache
# directory, so `import triadic_dgm` fails without this. The generated code needs it to call
# run_persona_pipeline() instead of retyping the clustering/rule-engine script every run.
if r'{_SAFE_REPO_ROOT_CONV}' not in sys.path:
    sys.path.insert(0, r'{_SAFE_REPO_ROOT_CONV}')

import json
import pandas as pd
import os

_DATASET_CACHE = dict()

def load_dataset(file_id=None):
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        raise ValueError("No index.json found in convergence workspace. Upload the fixed dataset first.")

    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)

    if not index_data:
        raise ValueError("No datasets available in convergence workspace.")

    if file_id is None:
        tabular_exts = {{'.csv', '.tsv', '.xlsx', '.xls', '.parquet'}}
        tabular_entries = [
            (fid, info) for fid, info in index_data.items()
            if os.path.splitext(info.get('filename', info.get('path', '')))[1].lower() in tabular_exts
        ]
        if tabular_entries:
            tabular_entries.sort(key=lambda x: x[1].get('created_at', ''), reverse=True)
            file_id = tabular_entries[0][0]
        else:
            file_id = list(index_data.keys())[-1]
        print(f"[convergence] Auto-selecting fixed dataset: {{index_data[file_id].get('filename', file_id)}}")

    if file_id in index_data:
        matched_id = file_id
    else:
        raise ValueError(f"File '{{file_id}}' not found in convergence workspace.")

    if matched_id in _DATASET_CACHE:
        return _DATASET_CACHE[matched_id]

    file_path = os.path.join(workspace_root, index_data[matched_id]['path'])
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.csv', '.tsv']:
        df = pd.read_csv(file_path, sep='\\t' if ext == '.tsv' else ',')
    elif ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    else:
        raise ValueError("Unsupported extension " + ext)

    _DATASET_CACHE[matched_id] = df
    print(f"[convergence] Loaded '{{index_data[matched_id].get('filename', matched_id)}}': {{len(df)}} rows")
    return df

def list_datasets():
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        print("No datasets available.")
        return
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    for fid, info in index_data.items():
        print(f"  - load_dataset('{{fid}}')  # {{info.get('filename', fid)}}")
"""


def _load_convergence_dataframe(workspace_root: str) -> "pd.DataFrame | None":
    """Read the convergence workspace's auto-selected tabular dataset into a DataFrame.

    Runs outside the sandbox (unlike the injected ``load_dataset()``) so a
    ``DatasetProfile`` can be built from the data before any agent run. Mirrors the
    file-selection logic in ``_build_tool_layer_code``'s injected ``load_dataset()``.

    Args:
        workspace_root: Absolute path to the convergence session's workspace directory
            (must contain an ``index.json`` produced by the upload/index step).

    Returns:
        The loaded DataFrame, or None if no usable tabular dataset is found or it
        fails to load.
    """
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        return None
    with open(index_path, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    if not index_data:
        return None
    tabular_exts = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
    entries = [
        (fid, info) for fid, info in index_data.items()
        if os.path.splitext(info.get("filename", info.get("path", "")))[1].lower() in tabular_exts
    ]
    if not entries:
        return None
    entries.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    info = entries[0][1]
    file_path = os.path.join(workspace_root, info["path"])
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".csv", ".tsv"):
            return pd.read_csv(file_path, sep="\t" if ext == ".tsv" else ",")
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(file_path)
    except Exception:
        return None
    return None


def _selected_dataset_id(workspace_root: str) -> "str | None":
    """Return the file_id ``load_dataset()`` would auto-select right now.

    Reads only index.json, never the data file, so it is cheap enough to call once per
    loop iteration. Must mirror the ordering in ``_build_tool_layer_code``'s injected
    ``load_dataset()`` and ``_load_convergence_dataframe`` — if it drifts, the staleness
    check silently stops firing.

    Args:
        workspace_root: Absolute path to the convergence session's workspace directory.

    Returns:
        The selected file_id, or None when no usable tabular dataset is registered.
    """
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception:
        return None
    if not index_data:
        return None
    tabular_exts = {".csv", ".tsv", ".xlsx", ".xls", ".parquet"}
    entries = [
        (fid, info) for fid, info in index_data.items()
        if os.path.splitext(info.get("filename", info.get("path", "")))[1].lower() in tabular_exts
    ]
    if not entries:
        return None
    entries.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    return entries[0][0]


class ConvergenceLoop:
    def __init__(self, base_config: dict, db_path: str = DEFAULT_DB_PATH, session_cache_path: str = DEFAULT_SESSION_CACHE_PATH):
        self._base_config = base_config
        self.db_path = db_path
        self.session_cache_path = session_cache_path
        self._agent: TriadicAgent | None = None
        self._report_gen: ReportGenerator | None = None
        self._tool_layer_code: str | None = None
        self._profile = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._run_count = 0
        self._error_count = 0
        self._last_run_at: float | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._running:
            return
        os.makedirs(self.session_cache_path, exist_ok=True)
        init_db(self.db_path)

        config = copy.deepcopy(self._base_config)
        config["session_cache_path"] = self.session_cache_path
        config.pop("chat_history_display", None)
        config.pop("figure_list", None)

        self._agent = TriadicAgent(config)
        # Used for both its LLM-backed narrative generation (generate_llm_narrative — same
        # call the full report makes) and its pure-Python deterministic composer methods as a
        # fallback when that call fails (see convergence_runner.enrich_personas).
        self._report_gen = ReportGenerator(
            api_key=config["api_key"],
            base_url=config["base_url_programmer"],
            model_name=config["programmer_model"],
        )

        # Point load_dataset() at the dedicated 'convergence' workspace (fixed dataset)
        # instead of 'default'. Stashed on self so run_once() can re-inject it after every
        # agent.clear() call — clear() tears down and rebuilds the kernel PROCESS from
        # scratch (engine.py TriadicAgent.clear()), which wipes this injection out entirely.
        # Confirmed on a live run: without re-injection, load_dataset() is undefined on every
        # run after the first, the generated code's repair attempt falls back to some tiny
        # improvised in-memory sample (~6 rows) instead of the real ~54k-row fixed dataset —
        # silently producing garbage "personas" that look superficially valid.
        workspace_root = resolve_workspace_root(CONVERGENCE_SESSION_ID)
        self._workspace_root = str(workspace_root)
        self._tool_layer_code = _build_tool_layer_code(str(workspace_root))
        self._agent.run_code(self._tool_layer_code)
        self._active_dataset_id = _selected_dataset_id(str(workspace_root))

        # Build & freeze a DatasetProfile for whatever dataset the workspace holds,
        # so the loop's clustering features are dataset-derived, not hardcoded telco.
        try:
            df = _load_convergence_dataframe(str(workspace_root))
            if df is not None:
                self._profile = load_or_build_cached(
                    df, DEFAULT_PROFILES_DIR,
                    label_enricher=self._build_label_enricher(config),
                    derived_enricher=lambda d, pr: self._select_derived_features(d, pr, config),
                )
                print(f"[convergence] DatasetProfile: {len(self._profile.behavioral_features)} features, fp={self._profile.fingerprint}")
        except Exception as e:
            print(f"[convergence] DatasetProfile build failed, using fallback prompt: {e}")
            self._profile = None

        # Isolate this agent's RIMRULE archive from the live chat product's — both would
        # otherwise default to the same relative path (dgm_agent_v2/rimrule_archive.json)
        # in this process/cwd and silently clobber each other's learned-rules file.
        self._agent.verifier.memory_bank.archive_path = os.path.join(
            self.session_cache_path, "rimrule_archive_convergence.json"
        )
        self._agent.verifier.memory_bank.rules = []
        self._agent.verifier.memory_bank._load_archive()

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[convergence] Background loop started.")

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._running = False
        print("[convergence] Background loop stopped.")

    def _build_label_enricher(self, config: dict):
        """Return a label_enricher for load_or_build_cached, or None if unavailable.

        Runs only on a profile cache miss (once per dataset fingerprint), so the
        continuously-running loop never pays for an inference per iteration.
        """
        try:
            import instructor
            from openai import OpenAI

            from triadic_dgm.persona.dataset_profile import has_churn_columns
            from triadic_dgm.persona.label_inference import infer_column_labels
        except Exception as e:
            print(f"[convergence] label inference unavailable: {e}")
            return None

        api_key = config.get("api_key")
        base_url = config.get("base_url_programmer")
        model_name = config.get("programmer_model")
        if not (api_key and model_name):
            return None

        def _enricher(df, profile):
            return infer_column_labels(
                df,
                client_factory=lambda: instructor.from_openai(
                    OpenAI(api_key=api_key, base_url=base_url), mode=instructor.Mode.JSON
                ),
                model_name=model_name,
                dataset_name=profile.dataset_name,
                # A dataset that genuinely carries churn columns SHOULD be labelled with
                # telco vocabulary; only a dataset without them would have to invent it.
                allow_domain_terms=has_churn_columns(profile.labels.keys()),
            )

        return _enricher

    def _select_derived_features(self, df, profile, config: dict):
        """Propose derived features with an LLM, keep only the measured winners.

        Returns (derived_features, behavioral_features, labels). On any failure the
        profile's existing feature list is returned unchanged — a run on raw columns beats
        no run. Labels are validated like any other: a derived feature left unlabelled
        would put a raw identifier back into persona names.
        """
        base = list(profile.behavioral_features)
        try:
            import instructor
            from openai import OpenAI

            from triadic_dgm.persona.derived_features import (
                resulting_feature_list,
                select_derived_features,
            )
            from triadic_dgm.persona.dataset_profile import has_churn_columns
            from triadic_dgm.persona.label_inference import propose_derived_features, validate_labels

            api_key = config.get("api_key")
            model_name = config.get("programmer_model")
            if not (api_key and model_name) or len(base) < 2:
                return {}, base, {}
            candidates = propose_derived_features(
                df, base,
                client_factory=lambda: instructor.from_openai(
                    OpenAI(api_key=api_key, base_url=config.get("base_url_programmer")),
                    mode=instructor.Mode.JSON,
                ),
                model_name=model_name,
                labels=profile.labels,
            )
            if not candidates:
                return {}, base, {}
            accepted = select_derived_features(df, base, candidates)
            proposed_labels = {
                c.name: c.label for c in candidates if c.name in accepted and c.label
            }
            labels = validate_labels(
                proposed_labels, list(accepted),
                allow_domain_terms=has_churn_columns(profile.labels.keys()),
            )
            return accepted, resulting_feature_list(base, candidates, accepted), labels
        except Exception as e:
            print(f"[convergence] derived-feature selection skipped: {e}")
            return {}, base, {}

    def _refresh_profile_if_dataset_changed(self) -> None:
        """Rebuild the frozen DatasetProfile when the workspace's dataset has been swapped.

        The profile is built once in ``start()``, but the sandbox's ``load_dataset()``
        re-reads index.json on every run — so uploading a new dataset while the loop is
        running makes the two diverge silently. Observed live: a non-telco dataset analysed
        against a stale telco profile, whose labels still satisfy ``has_churn_columns``,
        which is the exact gate ``enrich_personas`` uses to decide whether to apply the
        generic path — so Phase 4 was skipped entirely and the report came out full of
        telco vocabulary for data that had no such columns. Best-effort: on any failure the
        previous profile is kept, since a stale profile still beats no profile.
        """
        try:
            current_id = _selected_dataset_id(getattr(self, "_workspace_root", ""))
        except Exception:
            return
        if current_id is None or current_id == getattr(self, "_active_dataset_id", None):
            return
        print(f"[convergence] Dataset changed ({self._active_dataset_id} -> {current_id}); rebuilding DatasetProfile")
        try:
            df = _load_convergence_dataframe(self._workspace_root)
            if df is not None:
                self._profile = load_or_build_cached(
                    df, DEFAULT_PROFILES_DIR,
                    label_enricher=self._build_label_enricher(self._base_config),
                    derived_enricher=lambda d, pr: self._select_derived_features(d, pr, self._base_config),
                )
                self._active_dataset_id = current_id
                print(f"[convergence] DatasetProfile rebuilt: {len(self._profile.behavioral_features)} features, fp={self._profile.fingerprint}")
        except Exception as e:
            print(f"[convergence] DatasetProfile rebuild failed, keeping previous: {e}")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._refresh_profile_if_dataset_changed()
                task_prompt = (
                    build_task_prompt(
                        self._profile.behavioral_features,
                        getattr(self._profile, "derived_features", None),
                    )
                    if self._profile and self._profile.behavioral_features
                    else None
                )
                if task_prompt is not None:
                    result = run_once(self._agent, task_prompt=task_prompt, report_gen=self._report_gen, setup_code=self._tool_layer_code, profile=self._profile)
                else:
                    result = run_once(self._agent, report_gen=self._report_gen, setup_code=self._tool_layer_code, profile=self._profile)
                try:
                    save_run(self.db_path, result)
                except Exception as save_err:
                    print(f"[convergence] Failed to persist run: {save_err}")

                self._run_count += 1
                self._last_run_at = result.finished_at
                # Treat "no personas produced" the same as a hard failure for observability —
                # result.ok only reflects "no Python exception," but a run that completes
                # cleanly with 0 personas (e.g. pipeline hits its internal hard-stop path and
                # the repair loop's fix ends up not re-printing the JSON block) is just as
                # useless to the convergence feed as a crash.
                if not result.ok or not result.personas:
                    self._error_count += 1
                    self._last_error = result.error
                    print(f"[convergence] Run {result.run_id} produced no usable personas: {result.error}")
                else:
                    # Clear any stale error from a previous run — without this, last_error
                    # sticks forever after the first failure even once the loop recovers,
                    # making the status feed permanently look unhealthy.
                    self._last_error = None
                    print(f"[convergence] Run {result.run_id} ok: {len(result.personas)} personas.")

                try:
                    self._write_markdown_snapshot()
                except Exception as md_err:
                    print(f"[convergence] Failed to write markdown snapshot: {md_err}")
            except Exception as loop_err:
                # Should be unreachable (run_once never raises), but guarantees the loop
                # thread itself can never die from a single bad iteration.
                self._error_count += 1
                self._last_error = f"{type(loop_err).__name__}: {loop_err}"
                print(f"[convergence] Unexpected loop error: {loop_err}")

            self._stop_event.wait(timeout=_STOP_POLL_INTERVAL)

    def _write_markdown_snapshot(self) -> None:
        """Persist the latest-20 persona feed as an actual .md file — 'file markdown' the user
        asked to see at the top of the convergence page, not just JSON the frontend renders.
        Saved under the 'convergence' session's own generated/ folder (same host-visible
        workspace/ bind mount every other export in this app uses)."""
        workspace_root = resolve_workspace_root(CONVERGENCE_SESSION_ID)
        generated_dir = os.path.join(str(workspace_root), "generated")
        os.makedirs(generated_dir, exist_ok=True)
        md = render_markdown(build_feed_items(self.db_path, limit=20), status=self.status())
        with open(os.path.join(generated_dir, "convergence_personas_latest.md"), "w", encoding="utf-8") as f:
            f.write(md)

    def status(self) -> dict:
        return {
            "running": self._running,
            "run_count": self._run_count,
            "error_count": self._error_count,
            "last_run_at": self._last_run_at,
            "last_error": self._last_error,
        }


def _load_base_config() -> dict:
    from api.dependencies import lambda_instance

    return lambda_instance.config


convergence_loop = ConvergenceLoop(base_config=_load_base_config())
