import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.evidence_sidecar import build_evidence_ledger_sidecar
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_format import format_full_report
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask
from findver_agent.state import StateStore


class AbortRun(BaseException):
    pass


class CapturingBackend:
    model_name = "mock-model"
    model_context_window_tokens = 100_000
    request_profile = "generic_openai"
    thinking_mode = "unsupported"

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    async def generate(self, messages, config):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ModelResponse(
            content=response,
            input_tokens=100,
            output_tokens=10,
            latency_ms=1,
        )


@pytest.fixture
def case(tmp_path):
    reports_path = tmp_path / "reports"
    reports_path.mkdir()
    (reports_path / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "Revenue was 10 in 2022."},
                    {"context": "Revenue was 12 in 2023."},
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="lc-firstpass",
        statement="Revenue increased in 2023.",
        report="report.json",
    )
    return task, ReportStore(reports_path)


def action(name, arguments, *, status="partial", confidence="medium", risks=None):
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": {
                "evidence_status": status,
                "missing_information": [] if status == "sufficient" else ["support"],
                "confidence": confidence,
                "risk_flags": risks or [],
            },
        }
    )


def read(paragraph_ids, *, risks=None):
    return action(
        "read_paragraphs",
        {"paragraph_ids": paragraph_ids},
        risks=risks,
    )


def submit(evidence_ids, *, risks=None):
    return action(
        "submit_answer",
        {
            "label": "entailed",
            "evidence_ids": evidence_ids,
            "explanation": "Revenue rose from 10 to 12.",
        },
        status="sufficient",
        confidence="high",
        risks=risks,
    )


def config(*, exploration_steps=3):
    return AgentConfig(
        protocol_version="v2",
        exploration_steps=exploration_steps,
        finalization_steps=2,
        review_steps=1,
        review_policy="selective",
        long_context={"enabled": True},
    )


def engine(tmp_path, case, responses, *, exploration_steps=3, run_name="run"):
    task, reports = case
    backend = CapturingBackend(responses)
    run_dir = tmp_path / run_name
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(prompt_budget_tokens=32_768),
        agent_config=config(exploration_steps=exploration_steps),
        report_store=reports,
        run_dir=run_dir,
    )
    return task, reports, backend, run_dir, orchestrator


def rendered(messages):
    return "\n".join(message["content"] for message in messages)


def trace_events(run_dir):
    path = next((run_dir / "traces").glob("*.jsonl"))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_first_exploration_gets_exact_report_without_preloading_ledger(
    tmp_path, case
):
    task, reports, backend, run_dir, orchestrator = engine(
        tmp_path,
        case,
        [read([1]), submit([1])],
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=3,
        finalization_steps=2,
        review_steps=1,
    )
    full_report = format_full_report(reports.open_session(task.report))

    assert prediction.evidence_ids == [1]
    assert full_report in rendered(backend.messages[0])
    assert "<full_report_preview>" in rendered(backend.messages[0])
    assert "<full_report_preview>" not in rendered(backend.messages[1])
    assert [item.paragraph_id for item in state.evidence_ledger] == [1]
    assert state.long_context_state is not None
    assert state.long_context_state.injected is True
    assert state.long_context_state.injection_attempt == 1
    request_flags = [
        event["payload"]["long_context_injected"]
        for event in trace_events(run_dir)
        if event["event"] == "model_request"
    ]
    assert request_flags == [True, False]

    sidecar = build_evidence_ledger_sidecar(run_dir, [task.example_id])
    record = json.loads(sidecar)
    assert record == {
        "example_id": task.example_id,
        "initial_rag_evidence_ids": [],
        "final_agent_evidence_ids": [1],
    }


@pytest.mark.asyncio
async def test_parse_and_preview_only_submission_failures_do_not_reinject(
    tmp_path, case
):
    task, _, backend, run_dir, orchestrator = engine(
        tmp_path,
        case,
        ["not json", submit([1]), read([1]), submit([1])],
        exploration_steps=4,
    )

    prediction = await orchestrator.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(
        task,
        8,
        protocol_version="v2",
        exploration_steps=4,
        finalization_steps=2,
        review_steps=1,
    )

    assert prediction.evidence_ids == [1]
    assert state.phase_errors.exploration.parse == 1
    assert state.phase_errors.exploration.skill == 1
    assert ["<full_report_preview>" in rendered(item) for item in backend.messages] == [
        True,
        False,
        False,
        False,
    ]


@pytest.mark.asyncio
async def test_finalization_and_review_never_receive_full_report(tmp_path, case):
    task, _, backend, run_dir, orchestrator = engine(
        tmp_path,
        case,
        [
            read([1], risks=["table_alignment"]),
            submit([1], risks=["table_alignment"]),
            submit([1]),
        ],
        exploration_steps=1,
    )

    prediction = await orchestrator.run_question(task)
    events = trace_events(run_dir)
    requests = [event["payload"] for event in events if event["event"] == "model_request"]

    assert prediction.evidence_ids == [1]
    assert [item["phase"] for item in requests] == [
        "exploration",
        "finalization",
        "review",
    ]
    assert [item["long_context_injected"] for item in requests] == [True, False, False]
    assert ["<full_report_preview>" in rendered(item) for item in backend.messages] == [
        True,
        False,
        False,
    ]


@pytest.mark.asyncio
async def test_resume_after_claim_does_not_repeat_full_report(tmp_path, case):
    task, reports = case
    run_dir = tmp_path / "resume"
    first_backend = CapturingBackend([AbortRun()])
    first = AgentOrchestrator(
        backend=first_backend,
        generation=GenerationConfig(prompt_budget_tokens=32_768),
        agent_config=config(exploration_steps=1),
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(AbortRun):
        await first.run_question(task)

    resumed_backend = CapturingBackend([submit([])])
    resumed = AgentOrchestrator(
        backend=resumed_backend,
        generation=GenerationConfig(prompt_budget_tokens=32_768),
        agent_config=config(exploration_steps=1),
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

    assert prediction.status == "completed"
    assert "<full_report_preview>" in rendered(first_backend.messages[0])
    assert all(
        "<full_report_preview>" not in rendered(messages)
        for messages in resumed_backend.messages
    )
    assert state.long_context_state is not None
    assert state.long_context_state.injection_attempt == 1
    assert state.usage.model_calls == 3
