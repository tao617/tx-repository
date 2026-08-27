import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.findoasis.contracts import (
    FinalCertificateStatus,
    ObligationStatus,
    SkillName,
)
from findver_agent.findoasis.state import FinOASISStateStore
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PredictionStatus, PublicTask


class SequenceBackend:
    model_name = "mock-v3-submission"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def generate(self, messages, config):
        self.requests.append(messages)
        return ModelResponse(
            content=self.responses.pop(0),
            input_tokens=10,
            output_tokens=6,
            latency_ms=1,
        )

    async def aclose(self):
        return None


def action(
    name,
    arguments,
    target,
    *,
    confidence="high",
    risk_flags=(),
):
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": {
                "target_obligation_id": target,
                "open_obligations": [],
                "obligation_deltas": [],
                "confidence": confidence,
                "risk_flags": list(risk_flags),
                "expected_skill_effect": "advance deterministic final verification",
            },
        }
    )


def config(*, exploration=3, finalization=1, review=0, review_policy="none"):
    enabled = ("search_report", "read_paragraphs", "submit_answer")
    return AgentConfig.model_validate(
        {
            "max_steps": exploration + finalization + review,
            "protocol_version": "v3",
            "exploration_steps": exploration,
            "finalization_steps": finalization,
            "review_steps": review,
            "review_policy": review_policy,
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


def fixture(tmp_path, *, responses, agent_config):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "The issuer opened a facility in Shanghai."},
                    {"context": "Unrelated background paragraph."},
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="v3-submit",
        statement="The issuer opened a facility in Shanghai.",
        report="report.json",
    )
    backend = SequenceBackend(responses)
    run_dir = tmp_path / "run"
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(prompt_budget_tokens=8192),
        agent_config=agent_config,
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )
    return task, backend, run_dir, orchestrator


def load_state(task, run_dir, orchestrator, agent_config):
    return FinOASISStateStore(run_dir / "state").load_or_create(
        task,
        orchestrator._finoasis_agent._resume_identity(task),
        agent_config.max_steps,
        exploration_steps=agent_config.exploration_steps,
        finalization_steps=agent_config.finalization_steps,
        review_steps=agent_config.review_steps,
    )


@pytest.mark.asyncio
async def test_forced_finalization_closes_with_bounded_incomplete_prediction(tmp_path):
    agent_config = config(exploration=1, finalization=1)
    task, _, run_dir, orchestrator = fixture(
        tmp_path,
        agent_config=agent_config,
        responses=[
            action(
                "search_report",
                {"query": "facility Shanghai", "top_k": 2},
                "obl-0001",
            ),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [],
                    "explanation": "Best effort after the proof budget expired.",
                },
                "obl-0002",
                confidence="low",
                risk_flags=("unresolved_obligation", "retrieval_gap"),
            ),
        ],
    )

    prediction = await orchestrator.run_question(task)
    state = load_state(task, run_dir, orchestrator, agent_config)

    assert prediction.status is PredictionStatus.COMPLETED
    assert state.final_certificate_status is FinalCertificateStatus.INCOMPLETE
    assert state.unresolved_obligation_ids == ["obl-0001", "obl-0002"]
    assert state.obligation("obl-0002").status is ObligationStatus.PARTIAL
    certificate = state.final_verification_certificate_ledger[
        state.prediction_certificate_ref
    ]
    assert certificate.result.value == "incomplete"
    assert state.certificate_ledger[certificate.certificate_id].verified is False
    assert state.termination_reason == "budget_exhausted_fallback"


@pytest.mark.asyncio
async def test_unknown_final_evidence_fails_and_cannot_become_fallback(tmp_path):
    agent_config = config(exploration=2, finalization=1)
    task, _, run_dir, orchestrator = fixture(
        tmp_path,
        agent_config=agent_config,
        responses=[
            action(
                "search_report",
                {"query": "facility Shanghai", "top_k": 2},
                "obl-0001",
            ),
            action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [99],
                    "explanation": "This cites an unread paragraph.",
                },
                "obl-0002",
                confidence="low",
                risk_flags=("unresolved_obligation",),
            ),
        ],
    )

    prediction = await orchestrator.run_question(task)
    state = load_state(task, run_dir, orchestrator, agent_config)

    assert prediction.status is PredictionStatus.INVALID
    assert state.final_certificate_status is FinalCertificateStatus.FAILED
    certificate = state.final_verification_certificate_ledger[
        "final-certificate-0001"
    ]
    assert certificate.result.value == "failed"
    assert "unknown_evidence" in {item.value for item in certificate.failure_codes}
    assert state.obligation("obl-0002").status is ObligationStatus.PENDING


@pytest.mark.asyncio
@pytest.mark.parametrize("review_response", ["not-json", None])
async def test_review_uses_only_a_certificate_verified_draft(
    tmp_path, review_response
):
    agent_config = config(
        exploration=3,
        finalization=1,
        review=1,
        review_policy="selective",
    )
    responses = [
        action(
            "search_report",
            {"query": "facility Shanghai", "top_k": 2},
            "obl-0001",
        ),
        action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
        action(
            "submit_answer",
            {
                "label": "entailed",
                "evidence_ids": [0],
                "explanation": "The exact report paragraph supports the claim.",
            },
            "obl-0002",
            confidence="low",
            risk_flags=("weak_support",),
        ),
    ]
    if review_response is None:
        responses.append(
            action(
                "submit_answer",
                {
                    "label": "refuted",
                    "evidence_ids": [0],
                    "explanation": "The Review proposed a changed label.",
                },
                "obl-0002",
            )
        )
    else:
        responses.append(review_response)
    task, backend, run_dir, orchestrator = fixture(
        tmp_path,
        responses=responses,
        agent_config=agent_config,
    )

    prediction = await orchestrator.run_question(task)
    state = load_state(task, run_dir, orchestrator, agent_config)

    assert "Verified draft (present only when Runtime certificate-bound)" in (
        backend.requests[3][1]["content"]
    )
    assert '"certificate_ref":"final-certificate-0001"' in (
        backend.requests[3][1]["content"]
    )
    assert state.obligation("obl-0002").status is ObligationStatus.SATISFIED
    assert state.final_certificate_status is FinalCertificateStatus.VERIFIED
    if review_response is not None:
        assert prediction.label.value == "entailed"
        assert state.review_fallback_used is True
        assert state.prediction_certificate_ref == state.draft_certificate_ref
        assert state.termination_reason == "review_fallback"
    else:
        assert prediction.label.value == "refuted"
        assert state.review_fallback_used is False
        assert state.review_changed_label is True
        assert state.review_changed_explanation is True
        assert state.prediction_certificate_ref == "final-certificate-0002"
        assert state.termination_reason == "review_verified"
