import json

import pytest

from findver_agent.findoasis.actions import (
    ActionParseError,
    ReadParagraphsAction,
    SearchReportAction,
    parse_action,
)


def control(**updates):
    value = {
        "target_obligation_id": "obl-0001",
        "open_obligations": [],
        "obligation_deltas": [],
        "confidence": "medium",
        "risk_flags": ["retrieval_gap"],
        "expected_skill_effect": "Locate candidate report evidence.",
    }
    value.update(updates)
    return value


def action(name, arguments, **updates):
    value = {"action": name, "arguments": arguments, "control": control()}
    value.update(updates)
    return json.dumps(value)


def test_parser_accepts_only_one_strict_v3_action_and_json_fences():
    parsed = parse_action(action("search_report", {"query": "net revenue"}))
    assert isinstance(parsed, SearchReportAction)
    assert parsed.arguments.top_k == 5

    fenced = parse_action(
        "```json\n"
        + action("read_paragraphs", {"paragraph_ids": [3, 8]})
        + "\n```"
    )
    assert isinstance(fenced, ReadParagraphsAction)

    with pytest.raises(ActionParseError, match="one JSON object"):
        parse_action("[]")
    with pytest.raises(ActionParseError, match="one JSON object"):
        parse_action("not-json")


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        (
            "read_table_region",
            {"table_id": "table-1", "row_indices": [1], "column_indices": [2]},
        ),
        (
            "bind_financial_value",
            {
                "evidence_ref": "cell-1",
                "raw_value": "$1.2 million",
                "metric": "revenue",
                "entity": "issuer",
                "period": "FY2024",
                "numeric_type": "money",
            },
        ),
        (
            "execute_financial_program",
            {
                "program": {
                    "op": "subtract",
                    "args": [
                        {"kind": "value_ref", "ref": "value-1"},
                        {"kind": "value_ref", "ref": "value-2"},
                    ],
                },
                "claim_relation": {
                    "op": "equals",
                    "claim_ref": "claim-value-1",
                },
            },
        ),
        (
            "search_financial_rules",
            {
                "query": "recognition threshold",
                "jurisdiction": "US",
                "as_of_date": "2024-12-31",
            },
        ),
        ("read_financial_rules", {"rule_ids": ["rule-1"]}),
        (
            "check_rule_applicability",
            {
                "rule_evidence_refs": ["rule-evidence-1"],
                "document_evidence_refs": ["ev-1"],
                "jurisdiction": "US",
                "effective_date": "2024-12-31",
                "entity_scope": "public issuer",
            },
        ),
        (
            "submit_answer",
            {"label": "entailed", "evidence_ids": [1], "explanation": "Supported."},
        ),
    ],
)
def test_parser_has_a_reviewed_action_variant_for_each_v3_skill(name, arguments):
    assert parse_action(action(name, arguments)).action == name


def test_v3_rejects_legacy_calculator_unknown_skills_and_missing_control():
    with pytest.raises(ActionParseError):
        parse_action(action("calculator", {"expression": "1 + 1"}))
    with pytest.raises(ActionParseError):
        parse_action(action("browse_web", {"url": "https://example.com"}))
    with pytest.raises(ActionParseError):
        parse_action(json.dumps({"action": "search_report", "arguments": {"query": "x"}}))


def test_model_cannot_mark_satisfied_supply_certificate_or_smuggle_code_or_paths():
    mark_satisfied = control(
        obligation_deltas=[
            {"operation": "mark_satisfied", "obligation_id": "obl-0001"}
        ]
    )
    with pytest.raises(ActionParseError):
        parse_action(
            json.dumps(
                {
                    "action": "search_report",
                    "arguments": {"query": "revenue"},
                    "control": mark_satisfied,
                }
            )
        )

    for forbidden in (
        {"certificate": {"verified": True}},
        {"file_path": "/etc/passwd"},
        {"code": "import os"},
    ):
        with pytest.raises(ActionParseError):
            parse_action(action("search_report", {"query": "revenue", **forbidden}))


def test_control_open_obligations_are_proposals_without_runtime_ids_or_status():
    valid_control = control(
        open_obligations=[
            {
                "type": "evidence_conflict",
                "description": "Resolve inconsistent values in two report sections.",
                "mandatory": True,
            }
        ]
    )
    parsed = parse_action(
        json.dumps(
            {
                "action": "search_report",
                "arguments": {"query": "inconsistent value"},
                "control": valid_control,
            }
        )
    )
    assert parsed.control.open_obligations[0].type.value == "evidence_conflict"

    for forbidden in ({"obligation_id": "obl-9999"}, {"status": "satisfied"}):
        proposal = {
            "type": "document_fact",
            "description": "Find a supporting fact.",
            **forbidden,
        }
        with pytest.raises(ActionParseError):
            parse_action(
                json.dumps(
                    {
                        "action": "search_report",
                        "arguments": {"query": "fact"},
                        "control": control(open_obligations=[proposal]),
                    }
                )
            )
