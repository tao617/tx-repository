from findver_agent.actions import SubmitAction, parse_action
from tests.fixtures.mock_openai_server import ACTION


def test_builder_mock_submit_is_valid_for_v1_and_v2():
    assert isinstance(parse_action(ACTION, protocol_version="v1"), SubmitAction)
    action = parse_action(ACTION, protocol_version="v2")
    assert isinstance(action, SubmitAction)
    assert action.control is not None
    assert action.control.evidence_status == "sufficient"
    assert action.control.confidence == "high"
