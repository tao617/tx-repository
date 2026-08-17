import json
import tarfile
from pathlib import Path

import httpx
import pytest

from findver_agent.config import AgentConfig
from findver_agent.model_backends.base import GenerationConfig
from findver_agent.model_backends.openai_compatible import OpenAICompatibleBackend
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.runner import run_batch
from findver_agent.submission import seal_submission


@pytest.mark.asyncio
async def test_reasoning_drift_fails_closed_without_persisting_hidden_content(tmp_path):
    secret_reasoning = "never persist this hidden reasoning"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "id": "drift",
                "choices": [
                    {
                        "message": {
                            "content": "{}",
                            "reasoning_content": secret_reasoning,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps({"context": [{"context": "Public evidence."}]}),
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        json.dumps(
            {
                "example_id": "one",
                "statement": "Claim",
                "report": "report.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("concurrency: 1\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=100_000,
        request_profile="deepseek_v4_openai",
        thinking_type="disabled",
        transport=httpx.MockTransport(handler),
    )
    engine = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(),
        agent_config=AgentConfig(max_steps=1, concurrency=1),
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )
    try:
        await run_batch(
            tasks_path=tasks,
            config_path=config,
            run_dir=run_dir,
            mode="agent",
            model="fixed-model",
            backend_kind="api",
            concurrency=1,
            answer=engine.run_question,
        )
    finally:
        await backend.aclose()

    prediction = json.loads(
        (run_dir / "predictions.jsonl").read_text(encoding="utf-8")
    )
    assert prediction["status"] == "invalid"
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    assert secret_reasoning not in persisted
    assert "reasoning_content" not in persisted
    assert '"error_type":"protocol_drift"' in persisted

    archive = tmp_path / "submission.tar.gz"
    seal_submission(run_dir, archive, repository_root=Path.cwd())
    with tarfile.open(archive, "r:gz") as sealed:
        sealed_text = "\n".join(
            sealed.extractfile(name).read().decode("utf-8")
            for name in sealed.getnames()
        )
    assert secret_reasoning not in sealed_text
    assert "reasoning_content" not in sealed_text
