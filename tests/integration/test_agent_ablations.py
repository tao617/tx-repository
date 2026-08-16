import json

import pytest

from findver_agent.config import AgentConfig
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
        return ModelResponse(
            content=self.responses.pop(0),
            input_tokens=10,
            output_tokens=4,
            latency_ms=1,
        )

    async def aclose(self):
        return None


@pytest.fixture
def task_and_reports(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps({"context": [{"context": "Operating income was 128.4 in 2022."}]}),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="ablation-example",
        statement="Operating income was 128.4 in 2022.",
        report="report.json",
    )
    return task, ReportStore(reports)


def action(name, arguments):
    return json.dumps({"action": name, "arguments": arguments})


@pytest.mark.asyncio
async def test_calculator_disabled_is_recoverable(tmp_path, task_and_reports):
    task, reports = task_and_reports
    backend = SequenceBackend(
        [
            action("calculator", {"expression": "1+1"}),
            action(
                "submit_answer",
                {"label": "entailed", "evidence_ids": [], "explanation": "No calculator used."},
            ),
        ]
    )
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=2, calculator_enabled=False, max_calculator_calls=0),
        report_store=reports,
        run_dir=tmp_path / "run-no-calculator",
    )

    prediction = await engine.run_question(task)
    state = StateStore(tmp_path / "run-no-calculator" / "state").load_or_create(task, 2)

    assert prediction.status == PredictionStatus.COMPLETED
    assert state.tool_counts.calculator == 0
    assert state.calculations == []
    assert state.errors == ["skill error: calculator is disabled for this run"]


@pytest.mark.asyncio
async def test_pre_submit_review_requires_second_submission(tmp_path, task_and_reports):
    task, reports = task_and_reports
    backend = SequenceBackend(
        [
            action(
                "submit_answer",
                {"label": "refuted", "evidence_ids": [], "explanation": "Draft."},
            ),
            action(
                "submit_answer",
                {"label": "entailed", "evidence_ids": [], "explanation": "Reviewed final."},
            ),
        ]
    )
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(max_steps=4, pre_submit_review=True),
        report_store=reports,
        run_dir=tmp_path / "run-review",
    )

    prediction = await engine.run_question(task)
    state = StateStore(tmp_path / "run-review" / "state").load_or_create(task, 4)

    assert prediction.label.value == "entailed"
    assert state.step == 2
    assert state.review_requested is True
    assert state.review_completed is True
    assert state.draft_submission["label"] == "refuted"
    assert state.last_observation["review_completed"] is True
    assert state.last_observation["accepted"] is True
    assert state.usage.model_calls == 2


def test_disabled_calculator_is_not_advertised(tmp_path, task_and_reports):
    task, reports = task_and_reports
    engine = AgentOrchestrator(
        backend=SequenceBackend([]),
        generation=GenerationConfig(max_context_tokens=4096),
        agent_config=AgentConfig(calculator_enabled=False, max_calculator_calls=0),
        report_store=reports,
        run_dir=tmp_path / "prompt",
    )
    state = engine.state_store.load_or_create(task, 8)

    system_prompt = engine.prompt_builder.build(state)[0]["content"]

    assert '"action":"calculator"' not in system_prompt
