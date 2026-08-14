import pytest

from findver_agent.actions import ActionParseError, SubmitAction, parse_action


def test_action_parser_accepts_one_json_fence():
    action = parse_action(
        """```json
{"action":"submit_answer","arguments":{"label":"entailed","evidence_ids":[2],"explanation":"Supported."}}
```"""
    )
    assert isinstance(action, SubmitAction)
    assert action.arguments.evidence_ids == [2]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"action":"shell","arguments":{"command":"id"}}',
        '{"action":"search_report","arguments":{"query":"revenue","top_k":50}}',
        '{"action":"calculator","arguments":{"expression":"1+1"}} trailing',
    ],
)
def test_action_parser_rejects_invalid_or_unknown_actions(content):
    with pytest.raises(ActionParseError):
        parse_action(content)

