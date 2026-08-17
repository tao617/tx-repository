import json

import pytest

from findver_agent.run_identity import RunIdentity
from findver_agent.runner import run_batch, sha256_file
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


@pytest.mark.asyncio
async def test_planned_batch_resume_requires_exact_run_identity(tmp_path):
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
    run_dir = tmp_path / "matrix-model_a-condition"
    identity = RunIdentity(
        plan_sha256="a" * 64,
        matrix_id="matrix",
        condition_id="condition",
        plan_run_id=run_dir.name,
        effective_model_id="provider/model-a",
        model_alias="external-model-name",
        backend_kind="api",
        git_commit_at_start="b" * 40,
        config_sha256=sha256_file(config),
        public_tasks_sha256=sha256_file(tasks),
        planned_retrieval_sha256="c" * 64,
        model_context_window_tokens=100_000,
    )

    async def interrupted(task):
        if task.example_id == "two":
            raise StopBatch()
        return completed(task.example_id)

    with pytest.raises(StopBatch):
        await run_batch(
            tasks_path=tasks,
            config_path=config,
            run_dir=run_dir,
            mode="agent",
            model="external-model-name",
            backend_kind="api",
            answer=interrupted,
            run_identity=identity,
        )

    metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["run_identity"] == identity.model_dump(mode="json")

    changed_identity = RunIdentity.model_validate(
        {**identity.model_dump(mode="json"), "plan_sha256": "d" * 64}
    )

    async def resumed(task):
        return completed(task.example_id)

    with pytest.raises(ValueError, match="run identity changed"):
        await run_batch(
            tasks_path=tasks,
            config_path=config,
            run_dir=run_dir,
            mode="agent",
            model="external-model-name",
            backend_kind="api",
            answer=resumed,
            run_identity=changed_identity,
        )

    final = await run_batch(
        tasks_path=tasks,
        config_path=config,
        run_dir=run_dir,
        mode="agent",
        model="external-model-name",
        backend_kind="api",
        answer=resumed,
        run_identity=identity,
    )

    assert final.name == "predictions.jsonl"

