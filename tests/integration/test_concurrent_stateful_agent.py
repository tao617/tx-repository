import asyncio
import json

import pytest

from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.runner import run_batch


class ConcurrentSubmitBackend:
    model_name = "stateful-mock"
    model_context_window_tokens = 100_000
    request_profile = "generic_openai"
    thinking_mode = "unsupported"

    def __init__(self):
        self.active = 0
        self.peak = 0
        self.calls = 0

    async def generate(self, messages, config):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls += 1
        try:
            await asyncio.sleep(0.01)
            return ModelResponse(
                content=json.dumps(
                    {
                        "action": "submit_answer",
                        "arguments": {
                            "label": "entailed",
                            "evidence_ids": [],
                            "explanation": "Independent stateful mock result.",
                        },
                        "control": {
                            "evidence_status": "sufficient",
                            "missing_information": [],
                            "confidence": "high",
                            "risk_flags": [],
                        },
                    }
                ),
                finish_reason="stop",
            )
        finally:
            self.active -= 1

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_multi_question_stateful_agent_is_concurrent_and_isolated(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps({"context": [{"context": "Synthetic public paragraph."}]}),
        encoding="utf-8",
    )
    task_values = [
        {
            "example_id": f"example-{index}",
            "statement": f"Independent claim {index}",
            "report": "report.json",
        }
        for index in range(8)
    ]
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        "".join(json.dumps(value) + "\n" for value in task_values),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("concurrency: 4\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    backend = ConcurrentSubmitBackend()
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(),
        agent_config=AgentConfig(
            protocol_version="v2",
            exploration_steps=1,
            finalization_steps=1,
            review_steps=0,
            review_policy="none",
            concurrency=4,
        ),
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )

    final = await run_batch(
        tasks_path=tasks,
        config_path=config,
        run_dir=run_dir,
        mode="agent",
        model=backend.model_name,
        backend_kind="mock",
        concurrency=4,
        answer=engine.run_question,
    )

    assert backend.calls == len(task_values)
    assert 1 < backend.peak <= 4
    assert [
        json.loads(line)["example_id"]
        for line in final.read_text(encoding="utf-8").splitlines()
    ] == [value["example_id"] for value in task_values]
    states = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (run_dir / "state").glob("*.json")
    ]
    assert len(states) == len(task_values)
    expected_statements = {
        value["example_id"]: value["statement"] for value in task_values
    }
    assert {
        state["example_id"]: state["statement"] for state in states
    } == expected_statements
    assert all(state["usage"]["model_calls"] == 1 for state in states)
    for trace_path in (run_dir / "traces").glob("*.jsonl"):
        events = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
        ]
        assert len({event["example_id"] for event in events}) == 1
