import json

import pytest
from pydantic import ValidationError

from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PredictionStatus, PublicTask
from findver_agent.state import StateStore


class AbortRun(BaseException):
    pass


class CapturingBackend:
    model_name = "mock-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    async def generate(self, messages, config):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, Exception):
            raise response
        return ModelResponse(
            content=response,
            input_tokens=11,
            output_tokens=3,
            latency_ms=1,
        )

    async def aclose(self):
        return None


@pytest.fixture
def case(tmp_path):
    reports_path = tmp_path / "reports"
    reports_path.mkdir()
    (reports_path / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "Revenue was 12 in 2023."},
                    {"context": "Revenue was 10 in 2022."},
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="phase-example",
        statement="Revenue increased in 2023.",
        report="report.json",
    )
    return task, ReportStore(reports_path)


def action(name, arguments):
    submitting = name == "submit_answer"
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": {
                "evidence_status": "sufficient" if submitting else "partial",
                "missing_information": [] if submitting else ["direct support"],
                "confidence": "high" if submitting else "medium",
                "risk_flags": [],
            },
        }
    )


def submit(label="entailed", evidence_ids=None, explanation="Revenue increased."):
    if evidence_ids is None:
        evidence_ids = []
    return action(
        "submit_answer",
        {
            "label": label,
            "evidence_ids": evidence_ids,
            "explanation": explanation,
        },
    )


def v2_config(**overrides):
    values = {
        "protocol_version": "v2",
        "exploration_steps": 1,
        "finalization_steps": 2,
        "review_steps": 1,
        "review_policy": "none",
    }
    values.update(overrides)
    return AgentConfig(**values)


def engine(tmp_path, case, responses, **config_overrides):
    task, reports = case
    backend = CapturingBackend(responses)
    run_dir = tmp_path / "run"
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=v2_config(**config_overrides),
        report_store=reports,
        run_dir=run_dir,
    )
    return task, backend, run_dir, orchestrator


@pytest.mark.asyncio
async def test_exploration_exhaustion_enters_reserved_finalization(tmp_path, case):
    task, backend, run_dir, orchestrator = engine(
        tmp_path,
        case,
        [
            action("search_report", {"query": "revenue", "top_k": 3}),
            submit(),
        ],
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=1,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.exploration_step == 1
    assert state.finalization_step == 1
    assert state.review_step == 0
    assert state.forced_finalization is True
    assert state.termination_reason == "submitted_during_finalization"
    assert state.usage.model_calls == 2
    assert backend.responses == []


@pytest.mark.asyncio
async def test_exploration_errors_cannot_consume_finalization_attempts(tmp_path, case):
    task, _, run_dir, orchestrator = engine(
        tmp_path,
        case,
        ["not json", "still not json", submit()],
        exploration_steps=2,
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=2,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.exploration_step == 2
    assert state.finalization_step == 1
    assert state.phase_errors.exploration.parse == 2
    assert state.phase_errors.finalization.parse == 0


@pytest.mark.asyncio
async def test_finalization_hides_and_rejects_non_submit_actions_then_retries(tmp_path, case):
    task, backend, run_dir, orchestrator = engine(
        tmp_path,
        case,
        [
            action("search_report", {"query": "revenue", "top_k": 3}),
            submit(),
        ],
        exploration_steps=0,
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=0,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.finalization_step == 2
    assert state.tool_counts.search_report == 0
    assert state.phase_errors.finalization.protocol == 1
    for messages in backend.messages:
        system = messages[0]["content"]
        assert '"action":"search_report"' not in system
        assert '"action":"read_paragraphs"' not in system
        assert '"action":"calculator"' not in system
        assert '"action":"submit_answer"' in system


@pytest.mark.asyncio
async def test_first_finalization_format_error_allows_second_submit(tmp_path, case):
    task, _, run_dir, orchestrator = engine(
        tmp_path,
        case,
        ["malformed", submit()],
        exploration_steps=0,
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=0,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.finalization_step == 2
    assert state.phase_errors.finalization.parse == 1


@pytest.mark.asyncio
async def test_invalid_only_after_all_finalization_attempts_fail(tmp_path, case):
    task, _, run_dir, orchestrator = engine(
        tmp_path,
        case,
        ["malformed", action("calculator", {"expression": "1+1"})],
        exploration_steps=0,
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=0,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.INVALID
    assert state.finalization_step == 2
    assert state.termination_reason == "finalization_budget_exhausted"
    assert state.phase_errors.finalization.parse == 1
    assert state.phase_errors.finalization.protocol == 1


@pytest.mark.asyncio
async def test_model_errors_are_counted_only_in_current_phase(tmp_path, case):
    task, _, run_dir, orchestrator = engine(
        tmp_path,
        case,
        [RuntimeError("temporary"), submit()],
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=1,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.phase_errors.exploration.model == 1
    assert state.phase_errors.finalization.model == 0


@pytest.mark.asyncio
async def test_resume_preserves_consumed_phase_attempt_and_rejects_budget_change(tmp_path, case):
    task, reports = case
    run_dir = tmp_path / "run"
    first = AgentOrchestrator(
        backend=CapturingBackend([AbortRun()]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=v2_config(),
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(AbortRun):
        await first.run_question(task)

    changed = AgentOrchestrator(
        backend=CapturingBackend([]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=v2_config(exploration_steps=2),
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(ValueError, match="phase budgets do not match"):
        await changed.run_question(task)

    resumed = AgentOrchestrator(
        backend=CapturingBackend([submit()]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=v2_config(),
        report_store=reports,
        run_dir=run_dir,
    )
    prediction = await resumed.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=1,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.exploration_step == 1
    assert state.finalization_step == 1
    assert state.usage.model_calls == 2


@pytest.mark.asyncio
async def test_mandatory_review_has_independent_budget_and_falls_back_to_draft(tmp_path, case):
    task, _, run_dir, orchestrator = engine(
        tmp_path,
        case,
        [submit(label="refuted", explanation="Verified draft."), "bad review"],
        review_policy="mandatory",
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=1,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.status == PredictionStatus.COMPLETED
    assert prediction.label.value == "refuted"
    assert state.exploration_step == 1
    assert state.finalization_step == 0
    assert state.review_step == 1
    assert state.phase_errors.review.parse == 1
    assert state.review_fallback_used is True
    assert state.termination_reason == "review_fallback"


def test_protocol_configuration_rejects_mixed_review_controls():
    with pytest.raises(ValidationError, match="review_policy"):
        AgentConfig(protocol_version="v1", review_policy="mandatory")
    with pytest.raises(ValidationError, match="pre_submit_review"):
        AgentConfig(protocol_version="v2", pre_submit_review=True)
    with pytest.raises(ValidationError, match="at least one review step"):
        AgentConfig(
            protocol_version="v2",
            review_policy="mandatory",
            review_steps=0,
        )
