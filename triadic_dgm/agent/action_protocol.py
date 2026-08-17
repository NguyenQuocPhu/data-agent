"""Structured action contract for the notebook observation loop.

The model is intentionally given one broad execution tool (EXECUTE_PYTHON).  This
module only validates the control-plane envelope around that tool; it does not try
to constrain which Python libraries or already-defined notebook functions the
agent may use.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


VALID_ACTIONS = {
    "ASK_USER",
    "PROPOSE_PLAN",
    "EXECUTE_PYTHON",
    "FINAL_ANSWER",
}


class ActionProtocolError(ValueError):
    """Raised when an LLM response does not satisfy the action contract."""


@dataclass(frozen=True)
class AgentAction:
    action: str
    description: str = ""
    code: str = ""
    question: str = ""
    options: tuple[str, ...] = ()
    plan: tuple[str, ...] = ()
    answer: str = ""


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise ActionProtocolError("response does not contain a JSON object")
        candidate = candidate[start:end + 1]

    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ActionProtocolError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ActionProtocolError("top-level JSON value must be an object")
    return value


def parse_agent_action(text: str) -> AgentAction:
    """Parse and validate one model decision.

    Extra keys are ignored so the protocol remains tolerant of small prompt/model
    variations, while the fields required by the selected action remain strict.
    """

    payload = _extract_json_object(text)
    action = str(payload.get("action", "")).strip().upper()
    if action not in VALID_ACTIONS:
        allowed = ", ".join(sorted(VALID_ACTIONS))
        raise ActionProtocolError(f"unknown action {action!r}; expected one of: {allowed}")

    description = str(payload.get("description", "")).strip()
    code = str(payload.get("code", "")).strip()
    question = str(payload.get("question", "")).strip()
    answer = str(payload.get("answer", "")).strip()

    raw_options = payload.get("options", [])
    if not isinstance(raw_options, list):
        raise ActionProtocolError("options must be an array of strings")
    options_list: list[str] = []
    seen_options: set[str] = set()
    for item in raw_options:
        if not isinstance(item, str):
            raise ActionProtocolError("options must be an array of strings")
        option = item.strip()
        normalized = option.casefold()
        if not option or normalized in {"other", "khác", "khac"} or normalized in seen_options:
            continue
        seen_options.add(normalized)
        options_list.append(option)
    options = tuple(options_list)

    raw_plan = payload.get("plan", [])
    if isinstance(raw_plan, str):
        raw_plan = [raw_plan]
    if not isinstance(raw_plan, list):
        raise ActionProtocolError("plan must be an array of strings")
    plan = tuple(str(step).strip() for step in raw_plan if str(step).strip())

    required_value = {
        "ASK_USER": question,
        "PROPOSE_PLAN": plan,
        "EXECUTE_PYTHON": code,
        "FINAL_ANSWER": answer,
    }[action]
    if not required_value:
        field = {
            "ASK_USER": "question",
            "PROPOSE_PLAN": "plan",
            "EXECUTE_PYTHON": "code",
            "FINAL_ANSWER": "answer",
        }[action]
        raise ActionProtocolError(f"{action} requires a non-empty {field} field")

    if action == "ASK_USER" and not 2 <= len(options) <= 4:
        raise ActionProtocolError(
            "ASK_USER requires 2 to 4 distinct options; do not include Other because the UI adds it"
        )

    return AgentAction(
        action=action,
        description=description,
        code=code,
        question=question,
        options=options,
        plan=plan,
        answer=answer,
    )
