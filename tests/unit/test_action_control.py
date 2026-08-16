import json

import pytest

from findver_agent.actions import ActionParseError, SearchAction, SubmitAction, parse_action


def action(control=None):
    value = {
        "action": "search_report",
        "arguments": {"query": "adjusted EBITDA", "top_k": 5},
    }
    if control is not None:
        value["control"] = control
    return json.dumps(value)


def valid_control(**overrides):
    value = {
        "evidence_status": "partial",
        "missing_information": ["2023 adjusted EBITDA value"],
        "confidence": "medium",
        "risk_flags": ["retrieval_gap"],
    }
    value.update(overrides)
    return value


def test_v1_action_remains_compatible_without_control():
    parsed = parse_action(action())

    assert isinstance(parsed, SearchAction)
    assert parsed.control is None


def test_v2_requires_bounded_structured_control():
    with pytest.raises(ActionParseError, match="requires control"):
        parse_action(action(), protocol_version="v2")

    parsed = parse_action(action(valid_control()), protocol_version="v2")

    assert parsed.control.evidence_status.value == "partial"
    assert parsed.control.missing_information == ["2023 adjusted EBITDA value"]
    assert parsed.control.confidence.value == "medium"
    assert [flag.value for flag in parsed.control.risk_flags] == ["retrieval_gap"]


@pytest.mark.parametrize(
    "control",
    [
        valid_control(missing_information=[str(index) for index in range(6)]),
        valid_control(missing_information=["x" * 301]),
        valid_control(risk_flags=["arbitrary_unbounded_risk"]),
        valid_control(risk_flags=["weak_support", "weak_support"]),
        {**valid_control(), "hidden_reasoning": "private chain of thought"},
    ],
)
def test_v2_rejects_unbounded_or_unknown_control_fields(control):
    with pytest.raises(ActionParseError):
        parse_action(action(control), protocol_version="v2")


def test_v2_submit_control_uses_enumerated_values():
    parsed = parse_action(
        json.dumps(
            {
                "action": "submit_answer",
                "arguments": {
                    "label": "entailed",
                    "evidence_ids": [],
                    "explanation": "Direct support.",
                },
                "control": valid_control(
                    evidence_status="sufficient",
                    missing_information=[],
                    confidence="high",
                    risk_flags=["table_alignment"],
                ),
            }
        ),
        protocol_version="v2",
    )

    assert isinstance(parsed, SubmitAction)
    assert parsed.control.confidence.value == "high"
