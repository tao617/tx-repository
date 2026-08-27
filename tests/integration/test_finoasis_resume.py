import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.findoasis.contracts import SkillName
from findver_agent.findoasis.contracts import ObligationStatus
from findver_agent.findoasis.state import FinOASISStateStore
from findver_agent.model_backends.base import (
    GenerationConfig,
    ModelResponse,
)
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask


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
        return ModelResponse(content=response, input_tokens=11, output_tokens=7)

    async def aclose(self):
        return None


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


def _findoasis_config():
    enabled = ("search_report", "read_paragraphs", "submit_answer")
    return AgentConfig.model_validate(
        {
            "max_steps": 4,
            "protocol_version": "v3",
            "exploration_steps": 3,
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
    return (
        PublicTask(
            example_id="finoasis-resume",
            statement="Revenue was 128.4 million in fiscal 2024.",
            report="report.json",
        ),
        ReportStore(reports),
    )


class AbortRun(BaseException):
    pass


@pytest.mark.asyncio
async def test_v3_resume_keeps_charged_attempt_and_does_not_repeat_search(tmp_path):
    task, reports = _fixture(tmp_path)
    run_dir = tmp_path / "run"
    config = _findoasis_config()
    interrupted = AgentOrchestrator(
        backend=SequenceBackend(
            [
                _action(
                    "search_report",
                    {"query": "revenue 128.4 2024", "top_k": 2},
                ),
                AbortRun(),
            ]
        ),
        generation=GenerationConfig(prompt_budget_tokens=4096),
        agent_config=config,
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(AbortRun):
        await interrupted.run_question(task)

    resumed_backend = SequenceBackend(
        [
            _action("read_paragraphs", {"paragraph_ids": [1]}),
            _action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [1],
                    "explanation": "Recovered from durable v3 state.",
                },
                target="obl-0002",
            ),
        ]
    )
    resumed = AgentOrchestrator(
        backend=resumed_backend,
        generation=GenerationConfig(prompt_budget_tokens=4096),
        agent_config=config,
        report_store=reports,
        run_dir=run_dir,
    )
    await resumed.run_question(task)
    state = FinOASISStateStore(run_dir / "state").load_or_create(
        task,
        resumed._finoasis_agent._resume_identity(task),
        4,
        exploration_steps=3,
        finalization_steps=1,
    )

    assert state.step == 4
    assert state.phase_attempts.exploration_used == 3
    assert state.phase_attempts.finalization_used == 1
    assert state.usage.model_calls == 4
    assert len(state.report_search_history) == 1
    assert state.obligation("obl-0001").status is ObligationStatus.SATISFIED
    assert list(state.evidence_ledger) == ["report-paragraph:1"]
    assert '"action":"read_paragraphs"' in resumed_backend.requests[0][0][
        "content"
    ]
