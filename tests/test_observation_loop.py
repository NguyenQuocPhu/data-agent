import json
from types import SimpleNamespace

import pytest

from triadic_dgm.agent.action_protocol import ActionProtocolError, parse_agent_action
from triadic_dgm.agent.programmer import DecisionAgent
from triadic_dgm.engine import TriadicAgent
from triadic_dgm.prompts.prompts import OBSERVATION_AGENT_PROMPT


def test_action_protocol_accepts_fenced_json():
    action = parse_agent_action(
        '```json\n{"action":"EXECUTE_PYTHON","description":"inspect",'
        '"code":"df = load_dataset()\\nprint(df.shape)"}\n```'
    )
    assert action.action == "EXECUTE_PYTHON"
    assert action.description == "inspect"
    assert "print(df.shape)" in action.code


def test_action_protocol_accepts_human_decision_options():
    action = parse_agent_action(
        '{"action":"ASK_USER","question":"Which target?",'
        '"options":["Revenue","Churn","Other"]}'
    )

    assert action.action == "ASK_USER"
    assert action.question == "Which target?"
    assert action.options == ("Revenue", "Churn")


@pytest.mark.parametrize(
    "payload",
    [
        '{"action":"ASK_USER"}',
        '{"action":"ASK_USER","question":"Which target?","options":["Revenue"]}',
        '{"action":"PROPOSE_PLAN","plan":[]}',
        '{"action":"EXECUTE_PYTHON","code":""}',
        '{"action":"FINAL_ANSWER","answer":""}',
        '{"action":"SHELL","code":"pwd"}',
    ],
)
def test_action_protocol_rejects_invalid_or_incomplete_actions(payload):
    with pytest.raises(ActionProtocolError):
        parse_agent_action(payload)


def test_prompt_defines_one_notebook_tool_without_forcing_persona():
    assert "EXECUTE_PYTHON" in OBSERVATION_AGENT_PROMPT
    assert "exactly one JSON object" in OBSERVATION_AGENT_PROMPT
    assert "Do not automatically run clustering" in OBSERVATION_AGENT_PROMPT
    assert "from flaml import AutoML" in OBSERVATION_AGENT_PROMPT
    assert "not a mandatory step" in OBSERVATION_AGENT_PROMPT
    assert "`lgbm`, `xgboost`, `rf`, and `extra_tree`" in OBSERVATION_AGENT_PROMPT
    assert "do not start or connect an" in OBSERVATION_AGENT_PROMPT
    assert "Bash" not in OBSERVATION_AGENT_PROMPT


class _FakeDecisionAgent:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = [{"role": "system", "content": "test"}]
        self.calls = 0

    def decide_next_action(self):
        self.calls += 1
        return next(self.responses)


def _bare_agent(responses):
    agent = TriadicAgent.__new__(TriadicAgent)
    agent.config = {"agent_max_steps": 5}
    agent.decision_agent = _FakeDecisionAgent(responses)
    agent.programmer = agent.decision_agent
    agent.observation_paused = False
    agent.observation_pause_reason = None
    return agent


def test_observation_is_returned_to_same_agent_before_next_decision():
    agent = _bare_agent(
        [
            json.dumps({
                "action": "EXECUTE_PYTHON",
                "description": "inspect rows",
                "code": "print(len(df))",
            }),
            json.dumps({"action": "FINAL_ANSWER", "answer": "There are 12 rows."}),
        ]
    )
    agent._run_notebook_action = lambda code, step: (
        {"type": "NOTEBOOK_OBSERVATION", "step": step, "success": True, "output": "12"},
        "12",
    )

    history = [{"role": "user", "content": "How many rows?"}]
    for _ in agent.stream_workflow(history):
        pass

    assert agent.decision_agent.calls == 2
    observations = [
        message["content"] for message in agent.programmer.messages
        if message["role"] == "user" and message["content"].startswith("[NOTEBOOK_OBSERVATION]")
    ]
    assert len(observations) == 1
    assert '"output": "12"' in observations[0]
    assert "There are 12 rows." in history[-1]["content"]


def test_human_actions_pause_the_loop():
    agent = _bare_agent(
        [json.dumps({
            "action": "ASK_USER",
            "question": "Which target column?",
            "options": ["Revenue", "Churn"],
        })]
    )
    history = [{"role": "user", "content": "Train a model"}]

    for _ in agent.stream_workflow(history):
        pass

    assert agent.observation_paused is True
    assert agent.observation_pause_reason == "user_input"
    assert agent.pending_human_decision == {
        "kind": "ask_user",
        "question": "Which target column?",
        "options": ["Revenue", "Churn"],
    }
    assert "Which target column?" in history[-1]["content"]


def test_empty_output_cell_is_still_successful():
    agent = TriadicAgent.__new__(TriadicAgent)
    agent.run_code = lambda code: ([], "Summary of console output:\n", "")
    agent.check_folder = lambda: (False, "")

    observation, visible = agent._run_notebook_action("x = 1", 1)

    assert observation["success"] is True
    assert "Summary of console output" in visible


def test_decision_agent_budget_matches_32k_gateway():
    agent = DecisionAgent(api_key="test")
    agent.messages = [
        {"role": "system", "content": "control"},
        {"role": "user", "content": "x" * 24000},
    ]

    assert agent.MODEL_CONTEXT_LIMIT == 32000
    assert agent._compute_max_tokens() == 6000
    assert (
        agent._estimate_message_tokens(agent._build_request_messages())
        + agent._compute_max_tokens()
        + agent.CONTEXT_SAFETY_MARGIN
        <= agent.MODEL_CONTEXT_LIMIT
    )
    usage = agent.context_usage()
    assert usage["context_limit"] == 32000
    assert usage["compaction_trigger_tokens"] == 20000
    assert usage["compaction_count"] == 0
    assert usage["used_percent"] > 0


def test_context_compaction_summarizes_old_turns_and_keeps_recent_messages():
    agent = DecisionAgent(api_key="test")
    old_messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"old-{index}:" + "x" * 6000}
        for index in range(8)
    ]
    recent_messages = [
        {"role": "assistant", "content": "latest action"},
        {"role": "user", "content": "latest observation"},
        {"role": "assistant", "content": "latest decision"},
        {"role": "user", "content": "latest user decision"},
    ]
    agent.messages = [
        {"role": "system", "content": "control prompt"},
        *old_messages,
        *recent_messages,
    ]

    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Goal: analyze file A. Notebook variable df exists."))]
        )

    agent.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    assert agent._compact_context_if_needed() is True
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == agent.COMPACTION_MAX_OUTPUT_TOKENS
    assert agent.messages[0] == {"role": "system", "content": "control prompt"}
    assert all(message["role"] != "system" for message in agent.messages[1:])
    assert agent.working_memory.startswith(agent.COMPACTION_MARKER)
    assert agent.messages[-4:] == recent_messages
    assert all("old-" not in message["content"] for message in agent.messages)
    request_messages = agent._build_request_messages()
    assert [message["role"] for message in request_messages].count("system") == 1
    assert request_messages[0]["role"] == "system"
    assert agent.COMPACTION_MARKER in request_messages[0]["content"]
    assert agent._estimate_message_tokens(request_messages) < agent.COMPACTION_TRIGGER_TOKENS
    assert agent.context_usage()["compaction_count"] == 1


def test_context_compaction_has_bounded_fallback_when_summary_call_fails():
    agent = DecisionAgent(api_key="test")
    agent.messages = [
        {"role": "system", "content": "control prompt"},
        *[
            {"role": "user" if index % 2 == 0 else "assistant", "content": "z" * 7000}
            for index in range(8)
        ],
    ]

    def failing_create(**kwargs):
        raise RuntimeError("gateway unavailable")

    agent.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=failing_create))
    )

    assert agent._compact_context_if_needed() is True
    assert agent.working_memory.startswith(agent.COMPACTION_MARKER)
    assert len(agent.working_memory) <= 21000
    assert [
        message["role"] for message in agent._build_request_messages()
    ].count("system") == 1


def test_repeated_compaction_refreshes_one_working_memory_without_extra_system_roles():
    agent = DecisionAgent(api_key="test")
    agent.messages = [
        {"role": "system", "content": "control prompt"},
        *[
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"first-{index}:" + "a" * 7000}
            for index in range(8)
        ],
    ]

    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"summary-{len(calls)}"))]
        )

    agent.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    assert agent._compact_context_if_needed() is True
    first_memory = agent.working_memory
    agent.messages.extend(
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"second-{index}:" + "b" * 7000}
        for index in range(8)
    )
    assert agent._compact_context_if_needed() is True

    assert agent.compaction_count == 2
    assert agent.working_memory != first_memory
    assert "summary-2" in agent.working_memory
    assert "Existing durable working memory" in calls[1]["messages"][1]["content"]
    request_messages = agent._build_request_messages()
    assert request_messages[0]["role"] == "system"
    assert [message["role"] for message in request_messages].count("system") == 1
