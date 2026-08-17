import pytest

from findver_agent.actions import ActionParseError, SubmitAction, parse_action
from tests.fixtures.mock_openai_server import (
    ACTION,
    STATEFUL_M2_RESPONSES,
)


def test_builder_mock_submit_is_valid_for_v1_and_v2():
    assert isinstance(parse_action(ACTION, protocol_version="v1"), SubmitAction)
    action = parse_action(ACTION, protocol_version="v2")
    assert isinstance(action, SubmitAction)
    assert action.control is not None
    assert action.control.evidence_status == "sufficient"
    assert action.control.confidence == "high"


def test_stateful_m2_mock_has_eight_valid_actions_then_review_parse_failure():
    actions = [
        parse_action(content, protocol_version="v2")
        for content in STATEFUL_M2_RESPONSES[:-1]
    ]
    assert [action.action for action in actions] == [
        "search_report",
        "read_paragraphs",
        "calculator",
        "search_report",
        "read_paragraphs",
        "calculator",
        "search_report",
        "submit_answer",
    ]
    with pytest.raises(ActionParseError):
        parse_action(STATEFUL_M2_RESPONSES[-1], protocol_version="v2")
