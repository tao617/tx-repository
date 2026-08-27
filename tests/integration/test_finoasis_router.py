import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.findoasis.contracts import ObligationStatus, SkillName
from findver_agent.findoasis.state import FinOASISStateStore
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PredictionStatus, PublicTask


class SequenceBackend:
    model_name = "mock-v3"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def generate(self, messages, config):
        self.requests.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ModelResponse(
            content=response,
            input_tokens=11,
            output_tokens=7,
            latency_ms=2,
        )

    async def aclose(self):
        return None


def _findoasis_config(*, exploration_steps=3, finalization_steps=1):
    enabled = ("search_report", "read_paragraphs", "submit_answer")
    return AgentConfig.model_validate(
        {
            "max_steps": exploration_steps + finalization_steps,
            "protocol_version": "v3",
            "exploration_steps": exploration_steps,
            "finalization_steps": finalization_steps,
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
                    skill.value: (4 if skill.value in enabled else 0)
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


def _fixture(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "Overview of the issuer."},
                    {"context": "Revenue was 128.4 million in fiscal 2024."},
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="finoasis-ie",
        statement="Revenue was 128.4 million in fiscal 2024.",
        report="report.json",
    )
    return task, ReportStore(reports)


def _action(name, arguments, *, target="obl-0001"):
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": {
                "target_obligation_id": target,
                "open_obligations": [],
                "obligation_deltas": [],
                "confidence": "low",
                "risk_flags": [],
                "expected_skill_effect": "advance the selected obligation",
            },
        }
    )


@pytest.mark.asyncio
async def test_dynamic_router_rejects_hidden_skill_without_ledger_mutation(tmp_path):
    task, reports = _fixture(tmp_path)
    backend = SequenceBackend(
        [
            _action(
                "execute_financial_program",
                {
                    "program": {
                        "op": "equals",
                        "args": [
                            {"kind": "value_ref", "ref": "value-1"},
                            {"kind": "constant_ref", "ref": "constant:one"},
                        ],
                    }
                },
            ),
            _action("search_report", {"query": "revenue 128.4 2024", "top_k": 2}),
            _action("read_paragraphs", {"paragraph_ids": [1]}),
            _action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [1],
                    "explanation": "The exact report paragraph supports the claim.",
                },
                target="obl-0002",
            ),
        ]
    )
    run_dir = tmp_path / "run"
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(prompt_budget_tokens=4096),
        agent_config=_findoasis_config(),
        report_store=reports,
        run_dir=run_dir,
    )

    prediction = await orchestrator.run_question(task)
    state = FinOASISStateStore(run_dir / "state").load_or_create(
        task,
        orchestrator._finoasis_agent._resume_identity(task),
        4,
        exploration_steps=3,
        finalization_steps=1,
    )

    assert prediction.status is PredictionStatus.INVALID
    assert state.skill_rejection_counts == {SkillName.EXECUTE_FINANCIAL_PROGRAM: 1}
    assert state.financial_program_ledger == {}
    assert state.numeric_value_ledger == {}
    assert state.obligation("obl-0001").status is ObligationStatus.SATISFIED
    assert list(state.evidence_ledger) == ["report-paragraph:1"]
    assert state.evidence_ledger["report-paragraph:1"].exact_text.startswith("Revenue")
    assert state.report_search_history[0].hits[0].paragraph_id == 1

    initial_allowed = backend.requests[0][0]["content"].split(
        "Allowed actions (complete current set", 1
    )[1]
    assert '"action":"search_report"' in initial_allowed
    assert "execute_financial_program" not in initial_allowed
    read_prompt = backend.requests[2][1]["content"]
    assert "Revenue was 128.4 million" in read_prompt
