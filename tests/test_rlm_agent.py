from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from triadic_dgm.rlm_agent.agent import RLMDataAgent, _TrackingLMHandler
from triadic_dgm.rlm_agent.context import ContextBuilder
from triadic_dgm.rlm_agent.controls import (
    control_setup_code,
    decode_control,
    encode_control,
)
from triadic_dgm.rlm_agent.events import (
    TrajectoryEventLogger,
    extract_analysis_text,
    summarize_iteration,
)
from rlm import RLM
from rlm.core.types import REPLResult
from rlm.utils.prompts import RLM_SYSTEM_PROMPT, build_user_prompt

from triadic_dgm.rlm_agent.prompt import DATA_AGENT_ADDENDUM, RLM_DATA_AGENT_PROMPT
from triadic_dgm.rlm_agent.policy import HumanControlPolicy
from triadic_dgm.rlm_agent.skill_registry import (
    list_skills,
    load_selected_skill,
    read_skill,
)
from triadic_dgm.rlm_agent.types import (
    AgentEvent,
    ControlEvent,
    PendingNotebookAction,
)
from triadic_dgm.rlm_agent.tools import build_notebook_setup_code


class _Usage:
    def to_dict(self):
        return {"model_usage_summaries": {}}


def test_control_envelope_round_trip():
    control = ControlEvent(
        kind="ask_user",
        question="Which target?",
        options=("Churn", "Revenue"),
    )
    assert decode_control(encode_control(control)) == control
    assert decode_control("ordinary final answer") is None

    approval = ControlEvent(
        kind="action_approval",
        question="Allow a sub-LLM call?",
        options=("Approve once", "Deny"),
        action="sub_llm",
        reason="Semantic extraction",
        request_id="approval-1",
        details={"methods": ["llm_query"]},
    )
    assert decode_control(encode_control(approval)) == approval


def test_rlm_prompt_uses_canonical_context_protocol():
    assert RLM_DATA_AGENT_PROMPT == (
        f"{RLM_SYSTEM_PROMPT.rstrip()}\n\n{DATA_AGENT_ADDENDUM}"
    )
    assert RLM_DATA_AGENT_PROMPT.startswith(RLM_SYSTEM_PROMPT.rstrip())
    assert "write code in ```repl``` blocks" in RLM_DATA_AGENT_PROMPT
    assert "`context` always aliases immutable `context_0`" in DATA_AGENT_ADDENDUM
    assert "propose_plan" not in DATA_AGENT_ADDENDUM
    assert "plan_review" not in DATA_AGENT_ADDENDUM
    assert "request_subllm_approval" not in DATA_AGENT_ADDENDUM
    assert "that exact block is executed" in DATA_AGENT_ADDENDUM
    assert "`scikit-learn` (imported as `sklearn`)" in DATA_AGENT_ADDENDUM
    assert "from flaml import AutoML" in DATA_AGENT_ADDENDUM
    assert "`pyarrow` for Arrow/Parquet" in DATA_AGENT_ADDENDUM
    assert "`duckdb` for" in DATA_AGENT_ADDENDUM
    assert "`pandera`" in DATA_AGENT_ADDENDUM
    assert "`matplotlib` and `seaborn`" in DATA_AGENT_ADDENDUM
    assert "they do not require human approval" in DATA_AGENT_ADDENDUM
    assert '`analyze`' in DATA_AGENT_ADDENDUM
    assert '`explore-data`' in DATA_AGENT_ADDENDUM
    assert '`validate-data`' in DATA_AGENT_ADDENDUM
    assert '`statistical-analysis`' in DATA_AGENT_ADDENDUM
    assert '`data-visualization`' in DATA_AGENT_ADDENDUM
    assert 'print(read_skill("..."))' in DATA_AGENT_ADDENDUM
    assert "contains `selected_skill`" in DATA_AGENT_ADDENDUM
    assert "Resolve turn intent in this order" in DATA_AGENT_ADDENDUM
    assert "a skill never replaces the current request" in DATA_AGENT_ADDENDUM
    assert "`history`: prior completed RLM trajectories" in RLM_SYSTEM_PROMPT
    removed_alias = "current_" + "context"
    assert removed_alias not in RLM_DATA_AGENT_PROMPT


def test_later_turn_prompt_prioritizes_new_context_then_history():
    content = build_user_prompt(
        iteration=0,
        context_count=2,
        history_count=1,
        max_iterations=8,
    )["content"]

    assert "new input in `context_1`" in content
    assert "use `context_0` as immutable background" in content
    assert "latest relevant `history`" in content
    assert content.index("`context_1`") < content.index("`context_0`")


def test_data_agent_root_prompt_distinguishes_new_request_from_hitl():
    new_request = RLMDataAgent._build_root_prompt(
        {
            "type": "user_request",
            "request": "Validate the previous analysis",
            "selected_skill": {"name": "validate-data"},
        },
        context_index=1,
    )
    assert "current task" in new_request
    assert "`context_1['request']`" in new_request
    assert "Do not substitute the original request" in new_request
    assert "latest relevant `history`" in new_request
    assert "workflow guidance" in new_request

    human_response = RLMDataAgent._build_root_prompt(
        {
            "type": "human_response",
            "request": "Approve once",
            "human_response": {"content": "Approve once"},
        },
        context_index=2,
    )
    assert "Continue the paused task" in human_response
    assert "`context_2['human_response']`" in human_response
    assert "current task is the new user request" not in human_response


def test_notebook_skill_catalog_reads_only_installed_skill_entrypoints(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = tmp_path / "repo"
    skill_root = repo / "triadic_dgm" / "rlm_agent" / "skills"
    (skill_root / "analyze").mkdir(parents=True)
    (skill_root / "analyze" / "SKILL.md").write_text(
        "---\nname: analyze\ndescription: Validate data answers.\n---\n# Analyze\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    namespace = {}
    exec(build_notebook_setup_code(workspace, repo), namespace, namespace)

    assert namespace["list_skills"]() == [{
        "name": "analyze",
        "description": "Validate data answers.",
        "argument_hint": "",
        "user_invocable": True,
    }]
    assert "# Analyze" in namespace["read_skill"]("analyze")
    try:
        namespace["read_skill"]("../analyze")
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("read_skill accepted a path instead of a catalog name")


def test_installed_skill_registry_separates_menu_and_internal_skills():
    all_skills = {item["name"]: item for item in list_skills()}
    menu_skills = {
        item["name"] for item in list_skills(user_invocable_only=True)
    }

    assert set(all_skills) == {
        "analyze",
        "explore-data",
        "validate-data",
        "statistical-analysis",
        "data-visualization",
    }
    assert menu_skills == {"analyze", "explore-data", "validate-data"}
    assert all_skills["analyze"]["argument_hint"] == "<question>"
    assert "# /analyze" in read_skill("analyze")
    selected = load_selected_skill("validate-data")
    assert selected is not None
    assert selected["name"] == "validate-data"
    assert "# /validate-data" in selected["instructions"]
    try:
        load_selected_skill("statistical-analysis")
    except ValueError as exc:
        assert "not user-invocable" in str(exc)
    else:
        raise AssertionError("internal skill was accepted as a slash command")


def test_context_builder_embeds_full_explicit_skill_in_new_turn(tmp_path):
    selected = load_selected_skill("explore-data")
    snapshot = ContextBuilder(tmp_path).build(
        user_message="Explore the uploaded file",
        session_id="skill-context",
        context_index=0,
        selected_skill=selected,
    )

    assert snapshot.payload["request"] == "Explore the uploaded file"
    assert snapshot.payload["selected_skill"]["name"] == "explore-data"
    assert "# /explore-data" in snapshot.payload["selected_skill"]["instructions"]


def test_rlm_context_usage_matches_public_ui_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {},
    }, tmp_path / "cache")

    usage = agent.context_usage()

    assert isinstance(agent, RLM)
    assert not hasattr(agent, "runtime")
    assert not (Path(__file__).parents[1] / "triadic_dgm" / "rlm_agent" / "runtime.py").exists()
    assert usage["context_limit"] == 30000
    assert usage["remaining_tokens"] == 30000
    assert usage["compaction_progress_percent"] == 0.0
    assert usage["compaction_count"] == 0


def test_configured_context_limit_drives_real_compaction_and_output_reserves(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    monkeypatch.setattr(
        "triadic_dgm.rlm_agent.agent.count_tokens",
        lambda _history, _model: 23_500,
    )
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {
            "model_context_tokens": 30_000,
            "compaction_threshold_pct": 0.80,
            "max_output_tokens": 2_048,
            "sub_max_output_tokens": 4_096,
        },
    }, tmp_path / "cache")

    assert agent._get_compaction_status([{"role": "user", "content": "x"}]) == (
        23_500,
        24_000,
        30_000,
    )
    assert agent.backend_kwargs["sampling_args"]["max_tokens"] == 2_048
    assert agent.other_backend_kwargs[0]["sampling_args"]["max_tokens"] == 4_096

    usage = agent._context_usage_for_history(
        [{"role": "user", "content": "x"}], phase="before_model", iteration=1
    )
    assert usage["estimated_tokens"] == 23_500
    assert usage["source"] == "rlm_count_tokens"
    assert usage["compaction_count"] == 0


def test_rlm_context_usage_counts_actual_compactions_not_history_entries(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {},
    }, tmp_path / "cache")
    monkeypatch.setattr(
        RLM,
        "_compact_history",
        lambda _self, _handler, _environment, history, _count: history[:2],
    )

    compacted = agent._compact_history(
        object(), object(), [{"role": "user", "content": "x"}], 1
    )

    assert compacted == [{"role": "user", "content": "x"}]
    assert agent.context_usage()["compaction_count"] == 1
    # An ordinary REPL journal entry must not change the reported count.
    agent._publish_context_usage(compacted, phase="after_iteration", iteration=1)
    assert agent.context_usage()["compaction_count"] == 1


def test_max_depth_one_still_registers_tracked_subcall_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    captured = {}
    fake_environment = SimpleNamespace()

    def fake_get_environment(environment_type, kwargs):
        captured["type"] = environment_type
        captured["kwargs"] = kwargs
        return fake_environment

    monkeypatch.setattr("triadic_dgm.rlm_agent.agent.get_environment", fake_get_environment)
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {"max_depth": 1},
    }, tmp_path / "cache")

    assert agent._ensure_environment() is fake_environment
    assert captured["kwargs"]["subcall_fn"] == agent._subcall
    assert captured["kwargs"]["compaction"] is True


def test_trajectory_logger_recovers_after_workspace_clear(tmp_path):
    log_dir = tmp_path / "workspace" / "rlm_logs"
    logger = TrajectoryEventLogger(log_dir)
    shutil.rmtree(tmp_path / "workspace")

    logger.start_turn("turn-after-clear", lambda _event: None)
    logger.log_metadata({"model": "test"})
    logger.finish_turn()

    assert (log_dir / "turn-after-clear.jsonl").exists()


def test_trajectory_logger_recovers_when_workspace_is_cleared_after_turn_starts(tmp_path):
    log_dir = tmp_path / "workspace" / "rlm_logs"
    logger = TrajectoryEventLogger(log_dir)
    logger.start_turn("turn-cleared-during-run", lambda _event: None)

    shutil.rmtree(tmp_path / "workspace")
    logger.log_metadata({"model": "test"})
    logger.finish_turn()

    assert (log_dir / "turn-cleared-during-run.jsonl").exists()


def test_iteration_summary_describes_actions_without_copying_response():
    iteration = SimpleNamespace(
        response="private model scratchpad that must not be rendered",
        code_blocks=[SimpleNamespace(
            code="df = load_dataset()\nprint(context_0['request'])\nprint(df.shape)",
            result=SimpleNamespace(final_answer=None),
        )],
    )

    summary = summarize_iteration(iteration)

    assert "private model scratchpad" not in summary
    assert "proposed 1 REPL cell" in summary
    assert "context_0" in summary
    assert "load_dataset" in summary
    assert "print" in summary


def test_analysis_text_excludes_repl_code_blocks():
    response = (
        "First, I need to inspect the original request and available data.\n"
        "```repl\nprint(context_0)\n```"
    )

    assert extract_analysis_text(response) == (
        "First, I need to inspect the original request and available data."
    )


def test_analysis_text_only_uses_prose_before_first_repl_block():
    response = (
        "I will inspect the context first.\n"
        "```repl\nprint(context)\n```\n"
        "This trailing text is not the pre-code analysis."
    )

    assert extract_analysis_text(response) == "I will inspect the context first."


def test_trajectory_analysis_event_includes_raw_model_response_and_summary(tmp_path):
    emitted = []
    logger = TrajectoryEventLogger(tmp_path / "logs")
    logger.start_turn("turn-visible-response", emitted.append)
    logger.log(SimpleNamespace(
        response="I will inspect the active dataset.\n```repl\nprint(context_0)\n```",
        code_blocks=[SimpleNamespace(
            code="print(context_0)",
            result=SimpleNamespace(stdout="{}", stderr="", final_answer=None),
        )],
        to_dict=lambda: {},
    ))
    logger.finish_turn()

    analysis = next(event for event in emitted if event.type == "analysis")
    assert analysis.data["content"] == "I will inspect the active dataset."
    assert "Context accessed: context_0" in analysis.data["decision_summary"]


def test_trajectory_emits_full_subllm_result_separately(tmp_path):
    emitted = []
    logger = TrajectoryEventLogger(tmp_path / "logs")
    logger.start_turn("turn-subllm", emitted.append)
    call = SimpleNamespace(
        root_model="child-model",
        prompt="Classify every supplied record",
        response="Complete child response without truncation",
        usage_summary=_Usage(),
        execution_time=1.25,
        error=None,
    )
    logger.log(SimpleNamespace(
        response="I will delegate this semantic step.\n```repl\nresult = llm_query('x')\n```",
        code_blocks=[SimpleNamespace(
            code="result = llm_query('x')",
            result=SimpleNamespace(
                stdout="",
                stderr="",
                final_answer=None,
                rlm_calls=[call],
            ),
        )],
        to_dict=lambda: {},
    ))
    logger.finish_turn()

    subcall = next(event for event in emitted if event.type == "subcall_result")
    assert subcall.data["prompt"] == "Classify every supplied record"
    assert subcall.data["response"] == "Complete child response without truncation"


def test_kernel_control_functions_finish_through_answer():
    namespace = {"answer": {"content": "", "ready": False}}
    exec(control_setup_code(), namespace, namespace)

    namespace["ask_user"]("Which target?", ["Churn", "Revenue"])

    assert namespace["answer"]["ready"] is True
    parsed = decode_control(namespace["answer"]["content"])
    assert parsed is not None
    assert parsed.kind == "ask_user"
    assert parsed.options == ("Churn", "Revenue")
    assert "propose_plan" not in namespace


def test_policy_requires_one_shot_human_approval_for_subllm():
    policy = HumanControlPolicy()
    code = "result = llm_query('classify this text')\nprint(result)"

    blocked = policy.evaluate([code])
    assert blocked.allowed is False
    assert blocked.control is not None
    assert blocked.control.kind == "action_approval"
    assert blocked.control.action == "sub_llm"

    assert policy.apply_human_response(blocked.control, "Approve once") is True
    assert policy.evaluate([code]).allowed is True
    assert policy.evaluate([code]).allowed is False

    alias_bypass = "query = llm_query\nprint(query('classify this'))"
    assert policy.evaluate([alias_bypass]).control is not None


def test_approved_subllm_cell_executes_once_and_continues_same_root_trajectory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {"max_iterations": 3},
    }, tmp_path / "cache")
    blocked_code = "result = llm_query('classify rows')\nprint(result)"
    blocked_response = (
        "I will delegate classification.\n"
        f"```repl\n{blocked_code}\n```"
    )
    original_history = [
        {"role": "system", "content": "RLM system"},
        {"role": "user", "content": "Task metadata"},
        {"role": "user", "content": "Turn 1/3:"},
    ]

    class FakeHandler:
        def __init__(self):
            self.prompts = []

        def completion(self, prompt):
            self.prompts.append(deepcopy(prompt))
            return (
                "I have the delegated result and can answer.\n"
                "```repl\nanswer['content'] = 'done'\nanswer['ready'] = True\n```"
            )

        def get_usage_summary(self):
            return _Usage()

    class FakeEnvironment:
        def __init__(self):
            self.executed = []
            self.histories = []

        def execute_code(self, code):
            self.executed.append(code)
            if "llm_query" in code:
                return REPLResult(
                    stdout="classified rows\n",
                    stderr="",
                    locals={},
                    rlm_calls=[],
                )
            return REPLResult(
                stdout="",
                stderr="",
                locals={},
                rlm_calls=[],
                final_answer="done",
            )

        def update_handler_address(self, _address):
            pass

        def add_context(self, _payload, context_index=None):
            raise AssertionError("approval resume must not add a new RLM context")

        def get_context_count(self):
            return 1

        def add_history(self, history, history_index=None):
            self.histories.append(deepcopy(history))
            return len(self.histories) - 1

        def get_history_count(self):
            return len(self.histories)

    initial_handler = SimpleNamespace(completion=lambda _prompt: blocked_response)
    initial_environment = SimpleNamespace()
    blocked_iteration = agent._completion_turn(
        original_history,
        initial_handler,
        initial_environment,
    )
    control = decode_control(blocked_iteration.code_blocks[0].result.final_answer)
    assert control is not None
    assert control.action == "sub_llm"
    assert agent._pending_notebook_action is not None
    assert not hasattr(initial_environment, "executed")

    assert agent.policy.apply_human_response(control, "Approve once") is True
    handler = FakeHandler()
    environment = FakeEnvironment()

    @contextmanager
    def fake_spawn(_prompt, *, add_context=True):
        assert add_context is False
        yield handler, environment

    monkeypatch.setattr(agent, "_spawn_completion_context", fake_spawn)
    completion = agent._resume_approved_action(agent._pending_notebook_action)

    assert environment.executed == [
        blocked_code,
        "answer['content'] = 'done'\nanswer['ready'] = True",
    ]
    assert completion.response == "done"
    assert len(handler.prompts) == 1
    continued_prompt = handler.prompts[0]
    assert {"role": "assistant", "content": blocked_response} in continued_prompt
    assert any(
        message["role"] == "user"
        and "REPL output:" in message["content"]
        and "classified rows" in message["content"]
        for message in continued_prompt
    )


def test_stream_approval_routes_saved_cell_to_resume_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {},
    }, tmp_path / "cache")
    control = ControlEvent(
        kind="action_approval",
        question="Allow the sub-LLM call?",
        options=("Approve once", "Deny"),
        action="sub_llm",
        request_id="approval-test",
    )
    pending = PendingNotebookAction(
        code="print(llm_query('classify'))",
        model_response="Delegating.\n```repl\nprint(llm_query('classify'))\n```",
        message_history=[{"role": "system", "content": "RLM"}],
        iteration_number=2,
    )
    agent._pending_control = control
    agent._pending_notebook_action = pending
    captured = {}

    def fake_complete(
        payload,
        context_index,
        run_id,
        sink,
        resume_action=None,
    ):
        captured["resume_action"] = resume_action
        return SimpleNamespace(
            response="continued",
            usage_summary=_Usage(),
            execution_time=0.1,
            metadata=None,
        )

    monkeypatch.setattr(agent, "_complete_request", fake_complete)
    monkeypatch.setattr(agent, "next_context_index", lambda: 1)

    events = list(agent.stream_turn("Approve once", "user-1"))

    assert captured["resume_action"] is pending
    assert agent._pending_notebook_action is None
    assert any(event.type == "final_answer" for event in events)


def test_direct_llm_handler_forwards_exact_prompt_and_records_depth_one_only():
    class FakeClient:
        model_name = "fake-model"

        def completion(self, prompt):
            return f"response:{prompt}"

        async def acompletion(self, prompt):
            return f"response:{prompt}"

        def get_last_usage(self):
            return SimpleNamespace()

        def get_usage_summary(self):
            return _Usage()

    client = FakeClient()
    recorded = []
    handler = _TrackingLMHandler(
        client,
        other_backend_client=None,
        record=recorded.append,
    )

    assert handler.get_client(depth=0) is client
    assert handler.get_client(depth=1).completion("classify") == "response:classify"
    assert recorded[0].prompt == "classify"
    assert recorded[0].response == "response:classify"
    assert recorded[0].call_type == "llm_query"


def test_rlm_subcall_forwards_exact_prompt_to_upstream_framework(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    captured = {}

    def fake_upstream_subcall(_self, prompt, model=None):
        captured["prompt"] = prompt
        captured["model"] = model
        return SimpleNamespace(error=None)

    monkeypatch.setattr(RLM, "_subcall", fake_upstream_subcall)
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {},
    }, tmp_path / "cache")

    result = agent._subcall("compare these two models", model="child-model")

    assert captured == {
        "prompt": "compare these two models",
        "model": "child-model",
    }
    assert result.call_type == "rlm_query"


def test_policy_does_not_treat_explicit_denial_as_approval():
    policy = HumanControlPolicy()
    code = "print(rlm_query('greet'))"
    blocked = policy.evaluate([code])
    assert blocked.control is not None

    assert policy.apply_human_response(blocked.control, "Deny, do not call another model") is False
    assert policy.evaluate([code]).allowed is False


def test_policy_does_not_gate_training_writes_or_dataframe_mutation():
    policy = HumanControlPolicy()
    cells = [
        "model.fit(X, y)",
        "pred.to_csv('predictions.csv')",
        "df['Total_Spending'] = df['Spa'] + df['VRDeck']",
        "df.drop(columns=['unused'], inplace=True)",
    ]

    for code in cells:
        assert policy.evaluate([code]).allowed is True

    state = policy.state()
    assert set(state) == {"approved_actions", "approval_scope"}


def test_policy_blocks_duplicate_successful_notebook_action():
    policy = HumanControlPolicy()
    code = "print(context_0)"
    assert policy.evaluate([code]).allowed is True
    policy.record_execution(code, stderr="")

    repeated = policy.evaluate([code])

    assert repeated.allowed is False
    assert "NO_PROGRESS" in repeated.message


def test_context_zero_contains_complete_dataset_and_later_context_does_not_replace_it(tmp_path):
    root = tmp_path / "session-a"
    files = root / "Files"
    metadata = root / "Metadata"
    files.mkdir(parents=True)
    metadata.mkdir()
    (files / "customers.csv").write_text("age,churn\n20,0\n", encoding="utf-8")
    (metadata / "customers.json").write_text(json.dumps({
        "rows": 1,
        "columns": ["age", "churn"],
        "dtypes": {"age": "int64", "churn": "int64"},
        "separator": ",",
    }), encoding="utf-8")
    (root / "index.json").write_text(json.dumps({
        "data-1": {
            "filename": "customers.csv",
            "path": "Files/customers.csv",
            "metadata_file": "Metadata/customers.json",
            "created_at": "2026-08-13T08:00:00",
        }
    }), encoding="utf-8")

    builder = ContextBuilder(tmp_path)
    snapshot = builder.build(
        "Analyze churn",
        session_id="session-a",
        context_index=0,
    )

    assert snapshot.payload["active_dataset"]["id"] == "data-1"
    assert snapshot.payload["active_dataset"]["columns"] == ["age", "churn"]
    assert snapshot.payload["request"] == "Analyze churn"
    assert snapshot.payload["datasets"][0]["content"] == "age,churn\n20,0\n"

    control = ControlEvent(
        kind="ask_user",
        question="Which metric?",
        options=("Accuracy", "F1"),
    )
    feedback = builder.build(
        "Add cross-validation",
        session_id="session-a",
        context_index=1,
        pending_control=control,
    )
    assert feedback.payload["type"] == "human_response"
    assert feedback.payload["human_response"]["content"] == "Add cross-validation"
    assert "datasets" not in feedback.payload


def test_rlm_agent_source_has_no_custom_latest_context_alias():
    package_root = Path(__file__).parents[1] / "triadic_dgm" / "rlm_agent"
    checked = ["agent.py", "prompt.py", "policy.py", "context.py"]
    removed_alias = "current_" + "context"
    for filename in checked:
        assert removed_alias not in (package_root / filename).read_text(encoding="utf-8")


def test_agent_uses_one_rlm_loop_and_resumes_human_control(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPANALYZE_WORKSPACE_BASE", str(tmp_path / "workspace"))
    agent = RLMDataAgent({
        "api_key": "test",
        "base_url_programmer": "http://example.test/v1",
        "programmer_model": "test-model",
        "rlm": {},
    }, tmp_path / "cache")
    control = ControlEvent(
        kind="ask_user",
        question="Which target?",
        options=("Churn", "Revenue"),
    )
    responses = iter([encode_control(control), "Training completed."])
    payloads = []

    def fake_complete(payload, context_index, run_id, sink, resume_action=None):
        assert resume_action is None
        payloads.append(payload)
        sink(AgentEvent("iteration_started", {"iteration": 1, "depth": 0}))
        return SimpleNamespace(
            response=next(responses),
            usage_summary=_Usage(),
            execution_time=0.1,
            metadata=None,
        )

    monkeypatch.setattr(agent, "_complete_request", fake_complete)
    monkeypatch.setattr(agent, "next_context_index", lambda: len(payloads))

    first_events = [event.to_dict() for event in agent.stream_turn("Train a model", "user-1")]
    assert any(event["type"] == "human_decision" for event in first_events)
    assert agent.observation_paused is True

    second_events = [event.to_dict() for event in agent.stream_turn("Churn", "user-1")]
    assert any(event["type"] == "final_answer" for event in second_events)
    assert payloads[1]["type"] == "human_response"
    assert payloads[1]["human_response"]["content"] == "Churn"
    assert agent.observation_paused is False
