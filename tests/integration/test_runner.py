import json

import pytest

from findver_agent.runner import run_batch
from findver_agent.schemas import Prediction


class StopBatch(BaseException):
    pass


def completed(example_id):
    return Prediction(
        example_id=example_id,
        label="entailed",
        status="completed",
        evidence_ids=[],
        explanation="mock",
    )


@pytest.mark.asyncio
async def test_batch_resumes_partial_predictions_and_atomically_completes(tmp_path):
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        "\n".join(
            json.dumps({"example_id": item, "statement": "Claim", "report": "report.json"})
            for item in ("one", "two")
        )
        + "\n",
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("version: 1\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    calls = []

    async def interrupted(task):
        calls.append(task.example_id)
        if task.example_id == "two":
            raise StopBatch()
        return completed(task.example_id)

    with pytest.raises(StopBatch):
        await run_batch(
            tasks_path=tasks,
            config_path=config,
            run_dir=run_dir,
            mode="agent",
            model="mock",
            backend_kind="mock",
            answer=interrupted,
        )
    assert (run_dir / "predictions.partial.jsonl").exists()
    assert calls == ["one", "two"]

    resumed_calls = []

    async def resumed(task):
        resumed_calls.append(task.example_id)
        return completed(task.example_id)

    final = await run_batch(
        tasks_path=tasks,
        config_path=config,
        run_dir=run_dir,
        mode="agent",
        model="mock",
        backend_kind="mock",
        answer=resumed,
    )

    assert resumed_calls == ["two"]
    assert final.name == "predictions.jsonl"
    assert not (run_dir / "predictions.partial.jsonl").exists()
    assert len(final.read_text(encoding="utf-8").splitlines()) == 2

