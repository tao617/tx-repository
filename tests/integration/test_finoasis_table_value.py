import json

import pytest
from pydantic import ValidationError

from findver_agent.config import AgentConfig
from findver_agent.findoasis.contracts import ObligationStatus, SkillName
from findver_agent.findoasis.state import FinOASISQuestionState, FinOASISStateStore
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask


class AbortRun(BaseException):
    pass


class SequenceBackend:
    model_name = "mock-v3-numeric"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def generate(self, messages, config):
        self.requests.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ModelResponse(content=response, input_tokens=13, output_tokens=8)

    async def aclose(self):
        return None


def action(name, arguments, target):
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": {
                "target_obligation_id": target,
                "open_obligations": [],
                "obligation_deltas": [],
                "confidence": "low",
                "risk_flags": ["calculation"],
                "expected_skill_effect": "advance the evidence-bound numeric proof",
            },
        }
    )


def numeric_config():
    enabled = (
        "search_report",
        "read_paragraphs",
        "read_table_region",
        "bind_financial_value",
        "execute_financial_program",
        "submit_answer",
    )
    return AgentConfig.model_validate(
        {
            "max_steps": 7,
            "protocol_version": "v3",
            "exploration_steps": 6,
            "finalization_steps": 1,
            "review_steps": 0,
            "review_policy": "none",
            "calculator_enabled": False,
            "findoasis": {
                "experimental": True,
                "official_test_authorized": False,
                "real_model_execution_authorized": False,
                "scorer_handoff_authorized": False,
                "enabled_skills": enabled,
                "skill_budgets": {
                    skill.value: (8 if skill.value in enabled else 0)
                    for skill in SkillName
                },
                "obligation_policy": {
                    "seeding": "conservative",
                    "skill_exposure": "dynamic",
                    "model_may_open_obligations": True,
                    "model_may_satisfy_obligations": False,
                    "model_may_waive_mandatory": False,
                    "normal_submit_requires_all_mandatory": True,
                    "budget_exhausted_submit": "low_confidence_best_effort",
                },
                "rule_corpus": {
                    "enabled": False,
                    "read_only": True,
                    "network_fallback": False,
                },
            },
        }
    )


@pytest.mark.asyncio
async def test_table_values_bind_before_numeric_program_is_exposed(tmp_path):
    report = {
        "context": [
            {
                "id": 0,
                "type": "table",
                "context": (
                    "CONSOLIDATED RESULTS\n(in millions)\n"
                    "| Metric | 2024 | 2023 |\n"
                    "| Revenue | $ 1,200 | $ 1,000 |"
                ),
            }
        ],
        "html_tables": [
            "<table><tr><th>Metric</th><th>2024</th><th>2023</th></tr>"
            "<tr><td>Revenue</td><td>$ 1,200</td><td>$ 1,000</td></tr></table>"
        ],
    }
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(json.dumps(report), encoding="utf-8")
    task = PublicTask(
        example_id="finoasis-numeric",
        statement="Revenue increased from $1,000 in 2023 to $1,200 in 2024.",
        report="report.json",
    )
    backend = SequenceBackend(
        [
            action(
                "search_report",
                {"query": "revenue 2024 2023", "top_k": 2},
                "obl-0001",
            ),
            action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
            action(
                "read_table_region",
                {
                    "table_id": "table:0000",
                    "row_indices": [1],
                    "column_indices": [1, 2],
                },
                "obl-0002",
            ),
            action(
                "bind_financial_value",
                {
                    "evidence_ref": "table-cell:table:0000:1:1",
                    "raw_value": "$ 1,200",
                    "metric": "Revenue",
                    "entity": "issuer",
                    "period": "2024",
                    "numeric_type": "money",
                    "currency": "unknown",
                    "unit": "unknown",
                    "scale": "unknown",
                },
                "obl-0002",
            ),
            action(
                "bind_financial_value",
                {
                    "evidence_ref": "table-cell:table:0000:1:2",
                    "raw_value": "$ 1,000",
                    "metric": "Revenue",
                    "entity": "issuer",
                    "period": "2023",
                    "numeric_type": "money",
                    "currency": "unknown",
                    "unit": "unknown",
                    "scale": "unknown",
                },
                "obl-0002",
            ),
            action(
                "execute_financial_program",
                {
                    "program": {
                        "op": "greater_than",
                        "args": [
                            {"kind": "value_ref", "ref": "value-0001"},
                            {"kind": "value_ref", "ref": "value-0002"},
                        ],
                    }
                },
                "obl-0004",
            ),
            AbortRun(),
        ]
    )
    run_dir = tmp_path / "run"
    config = numeric_config()
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(prompt_budget_tokens=8192),
        agent_config=config,
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )

    with pytest.raises(AbortRun):
        await orchestrator.run_question(task)

    state = FinOASISStateStore(run_dir / "state").load_or_create(
        task,
        orchestrator._finoasis_agent._resume_identity(task),
        7,
        exploration_steps=6,
        finalization_steps=1,
    )
    assert [candidate.table_id for candidate in state.table_candidates] == [
        "table:0000"
    ]
    assert list(state.numeric_value_ledger) == ["value-0001", "value-0002"]
    assert [
        value.normalized_value for value in state.numeric_value_ledger.values()
    ] == ["1200", "1000"]
    assert [value.currency for value in state.numeric_value_ledger.values()] == [
        "USD",
        "USD",
    ]
    assert [value.scale for value in state.numeric_value_ledger.values()] == [
        "million",
        "million",
    ]
    assert state.obligation("obl-0002").status is ObligationStatus.SATISFIED
    assert state.obligation("obl-0003").status is ObligationStatus.SATISFIED
    assert state.obligation("obl-0004").status is ObligationStatus.SATISFIED
    assert state.skill_call_counts[SkillName.READ_TABLE_REGION] == 1
    assert state.skill_call_counts[SkillName.BIND_FINANCIAL_VALUE] == 2
    assert state.skill_call_counts[SkillName.EXECUTE_FINANCIAL_PROGRAM] == 1
    assert list(state.financial_program_ledger) == ["program-0001"]
    assert list(state.numeric_certificate_ledger) == [
        "numeric-certificate-0001"
    ]
    certificate = state.numeric_certificate_ledger["numeric-certificate-0001"]
    assert certificate.result == "true"
    assert certificate.relation_satisfied is True
    assert certificate.source_evidence_refs == [
        "table-cell:table:0000:1:1",
        "table-cell:table:0000:1:2",
    ]

    before_values = backend.requests[3][0]["content"]
    assert '"action":"execute_financial_program"' not in before_values
    after_values = backend.requests[5][0]["content"]
    assert '"action":"execute_financial_program"' in after_values
    after_values_user = backend.requests[5][1]["content"]
    assert '"value_ref":"value-0001"' in after_values_user
    assert '"claim_value_ref":"claim-value-0001"' in after_values_user
    assert "<table" not in "\n".join(
        message["content"] for request in backend.requests for message in request
    )

    tampered = state.model_dump(mode="json")
    tampered["numeric_certificate_ledger"]["numeric-certificate-0001"][
        "diagnostics"
    ] = ["tampered certificate"]
    with pytest.raises(ValidationError, match="payload hash"):
        FinOASISQuestionState.model_validate(tampered)
