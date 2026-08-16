import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PredictionStatus, PublicTask
from findver_agent.state import StateStore


class SequenceBackend:
    model_name = "mock"

    def __init__(self, responses):
        self.responses = list(responses)

    async def generate(self, messages, config):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ModelResponse(
            content=response,
            input_tokens=13,
            output_tokens=4,
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
        example_id="selective-review",
        statement="Revenue increased in 2023.",
        report="report.json",
    )
    return task, ReportStore(reports_path)


def control(
    *,
    status="partial",
    confidence="medium",
    missing=None,
    risk_flags=None,
):
    return {
        "evidence_status": status,
        "missing_information": ["direct support"] if missing is None else missing,
        "confidence": confidence,
        "risk_flags": [] if risk_flags is None else risk_flags,
    }


def action(name, arguments, **control_values):
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": control(**control_values),
        }
    )


def submit(
    *,
    label="entailed",
    evidence_ids=None,
    explanation="Revenue increased.",
    status="sufficient",
    confidence="high",
    risk_flags=None,
):
    return action(
        "submit_answer",
        {
            "label": label,
            "evidence_ids": [] if evidence_ids is None else evidence_ids,
            "explanation": explanation,
        },
        status=status,
        confidence=confidence,
        missing=[] if status == "sufficient" else ["direct support"],
        risk_flags=[] if risk_flags is None else risk_flags,
    )


def make_engine(tmp_path, case, responses, **config_values):
    task, reports = case
    run_dir = tmp_path / "run"
    values = {
        "protocol_version": "v2",
        "exploration_steps": 3,
        "finalization_steps": 2,
        "review_steps": 1,
        "review_policy": "selective",
    }
    values.update(config_values)
    engine = AgentOrchestrator(
        backend=SequenceBackend(responses),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(**values),
        report_store=reports,
        run_dir=run_dir,
    )
    return task, run_dir, engine, values


def load_state(task, run_dir, values):
    return StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=values["exploration_steps"],
        finalization_steps=values["finalization_steps"],
        review_steps=values["review_steps"],
    )


@pytest.mark.asyncio
async def test_calculator_use_triggers_selective_review(tmp_path, case):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [
            action(
                "calculator",
                {"expression": "(12-10)/10*100"},
                risk_flags=["calculation"],
            ),
            submit(),
            submit(),
        ],
    )

    await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert state.review_triggered is True
    assert "calculator_used" in state.review_trigger_reasons
    assert state.review_step == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("submit_kwargs", "reason"),
    [
        ({"status": "conflicting"}, "conflicting_evidence"),
        ({"confidence": "low"}, "low_confidence"),
        ({"risk_flags": ["weak_support"]}, "weak_support"),
        ({"risk_flags": ["table_alignment"]}, "table_alignment"),
    ],
)
async def test_selective_review_risk_triggers(tmp_path, case, submit_kwargs, reason):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [submit(**submit_kwargs), submit()],
    )

    await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert reason in state.review_trigger_reasons
    assert state.review_completed is True


@pytest.mark.asyncio
async def test_high_confidence_risk_free_draft_skips_review(tmp_path, case):
    task, run_dir, engine, values = make_engine(tmp_path, case, [submit()])

    prediction = await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.review_triggered is False
    assert state.review_step == 0
    assert state.termination_reason == "submitted_during_exploration"


@pytest.mark.asyncio
async def test_forced_finalization_with_insufficient_evidence_triggers_review(tmp_path, case):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [
            action("search_report", {"query": "revenue", "top_k": 3}),
            submit(
                status="partial",
                confidence="medium",
                risk_flags=["retrieval_gap"],
            ),
            submit(),
        ],
        exploration_steps=1,
    )

    await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert state.forced_finalization is True
    assert state.forced_finalization_evidence_status.value == "partial"
    assert "forced_finalization_insufficient_evidence" in state.review_trigger_reasons


@pytest.mark.asyncio
async def test_sufficient_non_submit_action_is_recoverable_protocol_error(tmp_path, case):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [
            action(
                "search_report",
                {"query": "irrelevant broad search", "top_k": 3},
                status="sufficient",
                confidence="high",
                missing=[],
            ),
            submit(),
        ],
    )

    await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert state.tool_counts.search_report == 0
    assert state.phase_errors.exploration.protocol == 1


@pytest.mark.asyncio
async def test_unread_evidence_cannot_be_saved_as_draft(tmp_path, case):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [
            submit(evidence_ids=[1], explanation="Unread paragraph."),
            submit(evidence_ids=[], explanation="Valid retry."),
        ],
    )

    prediction = await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert prediction.explanation == "Valid retry."
    assert state.phase_errors.exploration.skill == 1
    assert state.draft_prediction.explanation == "Valid retry."
    assert state.draft_submission["evidence_ids"] == []


@pytest.mark.asyncio
async def test_review_success_can_change_verified_draft_and_records_changes(tmp_path, case):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [
            action("read_paragraphs", {"paragraph_ids": [0]}),
            submit(
                label="refuted",
                evidence_ids=[],
                explanation="Low-confidence draft.",
                confidence="low",
            ),
            submit(
                label="entailed",
                evidence_ids=[0],
                explanation="Revenue rose to 12.",
            ),
        ],
    )

    prediction = await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert prediction.label.value == "entailed"
    assert state.review_changed_label is True
    assert state.review_changed_evidence is True
    assert state.review_changed_explanation is True
    assert state.review_fallback_used is False


@pytest.mark.asyncio
async def test_review_parse_failure_falls_back_to_verified_draft(tmp_path, case):
    task, run_dir, engine, values = make_engine(
        tmp_path,
        case,
        [
            submit(
                label="refuted",
                explanation="Verified low-confidence draft.",
                confidence="low",
            ),
            "not json",
        ],
    )

    prediction = await engine.run_question(task)
    state = load_state(task, run_dir, values)

    assert prediction.status == PredictionStatus.COMPLETED
    assert prediction.label.value == "refuted"
    assert state.review_fallback_used is True
    assert state.termination_reason == "review_fallback"
    assert state.review_failure_reason.startswith("parse:")


@pytest.mark.asyncio
async def test_v1_mandatory_review_failure_also_falls_back_to_validated_draft(tmp_path, case):
    task, reports = case
    run_dir = tmp_path / "v1"
    legacy_submit = json.dumps(
        {
            "action": "submit_answer",
            "arguments": {
                "label": "entailed",
                "evidence_ids": [],
                "explanation": "Validated legacy draft.",
            },
        }
    )
    engine = AgentOrchestrator(
        backend=SequenceBackend([legacy_submit, "not json"]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=2, pre_submit_review=True),
        report_store=reports,
        run_dir=run_dir,
    )

    prediction = await engine.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(task, 2)

    assert prediction.status == PredictionStatus.COMPLETED
    assert prediction.explanation == "Validated legacy draft."
    assert state.review_fallback_used is True
    assert state.termination_reason == "review_fallback"
