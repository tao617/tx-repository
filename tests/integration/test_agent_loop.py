import json

import pytest

from findver_agent.baseline import BaselineRunner
from findver_agent.config import AgentConfig, BaselineConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PredictionStatus, PublicTask
from findver_agent.state import StateStore


class SequenceBackend:
    model_name = "mock-model"

    def __init__(self, responses):
        self.responses = list(responses)

    async def generate(self, messages, config):
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ModelResponse(content=response, input_tokens=10, output_tokens=4, latency_ms=1)

    async def aclose(self):
        return None


class AbortRun(BaseException):
    pass


@pytest.fixture
def task_and_reports(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {"context": "Overview."},
                    {"context": "Operating income was 128.4 in 2022."},
                    {"context": "Operating income was 114.7 in 2021."},
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(example_id="example-1", statement="Operating income rose about 11.9%.", report="report.json")
    return task, ReportStore(reports)


def action(name, arguments):
    return json.dumps({"action": name, "arguments": arguments})


@pytest.mark.asyncio
async def test_multistep_search_read_calculate_submit(tmp_path, task_and_reports):
    task, reports = task_and_reports
    backend = SequenceBackend(
        [
            action("search_report", {"query": "operating income 2022 2021", "top_k": 3}),
            action("read_paragraphs", {"paragraph_ids": [1, 2]}),
            action("calculator", {"expression": "round((128.4-114.7)/114.7*100, 4)"}),
            action(
                "submit_answer",
                {"label": "entailed", "evidence_ids": [1, 2], "explanation": "Increase is 11.9442%."},
            ),
        ]
    )
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=8),
        report_store=reports,
        run_dir=tmp_path / "run",
    )

    prediction = await engine.run_question(task)
    state = StateStore(tmp_path / "run" / "state").load_or_create(task, 8)

    assert prediction.label.value == "entailed"
    assert state.closed is True
    assert [item.paragraph_id for item in state.evidence_ledger] == [1, 2]
    assert state.calculations[0].result == 11.9442
    assert state.tool_counts.model_dump() == {
        "search_report": 1,
        "read_paragraphs": 1,
        "calculator": 1,
    }


@pytest.mark.asyncio
async def test_invalid_json_is_recoverable(tmp_path, task_and_reports):
    task, reports = task_and_reports
    backend = SequenceBackend(
        [
            "I cannot return JSON",
            action("submit_answer", {"label": "refuted", "evidence_ids": [], "explanation": "No support."}),
        ]
    )
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=2),
        report_store=reports,
        run_dir=tmp_path / "run",
    )

    prediction = await engine.run_question(task)
    state = StateStore(tmp_path / "run" / "state").load_or_create(task, 2)

    assert prediction.status == PredictionStatus.COMPLETED
    assert len(state.errors) == 1
    assert state.usage.model_calls == 2


@pytest.mark.asyncio
async def test_max_steps_produces_stable_invalid(tmp_path, task_and_reports):
    task, reports = task_and_reports
    engine = AgentOrchestrator(
        backend=SequenceBackend([action("search_report", {"query": "income", "top_k": 1})]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=1),
        report_store=reports,
        run_dir=tmp_path / "run",
    )

    first = await engine.run_question(task)
    second = await engine.run_question(task)

    assert first == second
    assert first.status == PredictionStatus.INVALID
    assert first.label is None


@pytest.mark.asyncio
async def test_interrupted_question_resumes_from_durable_state(tmp_path, task_and_reports):
    task, reports = task_and_reports
    run_dir = tmp_path / "run"
    first = AgentOrchestrator(
        backend=SequenceBackend(
            [action("search_report", {"query": "operating income", "top_k": 2}), AbortRun()]
        ),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=4),
        report_store=reports,
        run_dir=run_dir,
    )
    with pytest.raises(AbortRun):
        await first.run_question(task)

    resumed = AgentOrchestrator(
        backend=SequenceBackend(
            [action("submit_answer", {"label": "entailed", "evidence_ids": [], "explanation": "Recovered."})]
        ),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=4),
        report_store=reports,
        run_dir=run_dir,
    )
    prediction = await resumed.run_question(task)
    state = StateStore(run_dir / "state").load_or_create(task, 4)

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.step == 2
    assert state.search_queries[0].query == "operating income"


@pytest.mark.asyncio
async def test_baseline_uses_one_submit_call(tmp_path, task_and_reports):
    task, reports = task_and_reports
    backend = SequenceBackend(
        [action("submit_answer", {"label": "entailed", "evidence_ids": [1, 2], "explanation": "Values support it."})]
    )
    baseline = BaselineRunner(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        baseline_config=BaselineConfig(prompt_type="direct", retrieval="none"),
        report_store=reports,
        run_dir=tmp_path / "baseline",
    )

    prediction = await baseline.run_question(task)

    assert prediction.status == PredictionStatus.COMPLETED
    assert backend.responses == []

