import json

import pytest

from findver_agent.baseline import BaselineRunner
from findver_agent.config import BaselineConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PublicTask


class Backend:
    model_name = "mock-model"
    model_context_window_tokens = 100_000

    def __init__(self, response):
        self.response = response

    async def generate(self, messages, config):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def aclose(self):
        return None


def setup_runner(tmp_path, response):
    reports = tmp_path / "reports"
    reports.mkdir()
    paragraphs = ["First report paragraph.", "Second report paragraph."]
    (reports / "report.json").write_text(
        json.dumps({"context": [{"context": text} for text in paragraphs]}),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="long-context-example",
        statement="The first paragraph exists.",
        report="report.json",
    )
    run_dir = tmp_path / "run"
    runner = BaselineRunner(
        backend=Backend(response),
        generation=GenerationConfig(prompt_budget_tokens=8192),
        baseline_config=BaselineConfig(
            prompt_type="findver_direct_json",
            retrieval="none",
        ),
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )
    return task, runner, run_dir, paragraphs


@pytest.mark.asyncio
async def test_baseline_records_full_context_shape_and_actual_usage(tmp_path):
    response = ModelResponse(
        content=json.dumps(
            {
                "action": "submit_answer",
                "arguments": {
                    "label": "entailed",
                    "evidence_ids": [0],
                    "explanation": "The first paragraph is present.",
                },
            }
        ),
        input_tokens=123,
        output_tokens=17,
        latency_ms=9.5,
    )
    task, runner, run_dir, paragraphs = setup_runner(tmp_path, response)

    prediction = await runner.run_question(task)

    assert prediction.status == "completed"
    events = [
        json.loads(line)
        for line in next((run_dir / "traces").glob("*.jsonl")).read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    context = next(event["payload"] for event in events if event["event"] == "input_context")
    usage = next(event["payload"] for event in events if event["event"] == "model_response")
    assert {
        key: context[key]
        for key in (
            "report_paragraph_count",
            "report_character_count",
            "assembled_paragraph_count",
            "full_report_assembled",
            "local_truncation",
        )
    } == {
        "report_paragraph_count": 2,
        "report_character_count": sum(len(text) for text in paragraphs),
        "assembled_paragraph_count": 2,
        "full_report_assembled": True,
        "local_truncation": False,
    }
    assert context["prompt_budget_tokens"] == 8192
    assert context["estimated_input_tokens"] > 0
    assert context["estimated_total_tokens"] == (
        context["estimated_input_tokens"] + context["max_output_tokens"]
    )
    assert context["model_context_window_tokens"] == 100_000
    assert context["overflow_status"] == "within_window"
    assert (usage["input_tokens"], usage["output_tokens"], usage["latency_ms"]) == (
        123,
        17,
        9.5,
    )
    assert usage["actual_provider_input_tokens"] == 123


@pytest.mark.asyncio
async def test_baseline_classifies_provider_context_error(tmp_path):
    task, runner, run_dir, _ = setup_runner(
        tmp_path,
        RuntimeError("provider maximum context length exceeded"),
    )

    prediction = await runner.run_question(task)

    assert prediction.status == "invalid"
    events = [
        json.loads(line)
        for line in next((run_dir / "traces").glob("*.jsonl")).read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    error = next(event["payload"] for event in events if event["event"] == "baseline_error")
    assert error["provider_context_error"] is True
