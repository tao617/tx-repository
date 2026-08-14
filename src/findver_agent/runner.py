"""Resumable batch execution for Agent and Baseline modes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from findver_agent.schemas import Prediction, PublicTask


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_public_tasks(path: Path) -> list[PublicTask]:
    tasks: list[PublicTask] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                task = PublicTask.model_validate_json(line)
            except ValueError as error:
                raise ValueError(f"invalid public task on line {line_number}: {error}") from error
            if task.example_id in seen:
                raise ValueError(f"duplicate public task id: {task.example_id}")
            seen.add(task.example_id)
            tasks.append(task)
    return tasks


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class PredictionJournal:
    def __init__(self, run_dir: Path, expected_ids: list[str]) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        self.partial = run_dir / "predictions.partial.jsonl"
        self.final = run_dir / "predictions.jsonl"
        self.expected_ids = expected_ids
        self.expected_set = set(expected_ids)
        self.predictions: dict[str, Prediction] = {}
        source = self.final if self.final.exists() else self.partial
        if source.exists():
            with source.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        prediction = Prediction.model_validate_json(line)
                    except ValueError as error:
                        raise ValueError(f"invalid prediction on line {line_number}: {error}") from error
                    if prediction.example_id not in self.expected_set:
                        raise ValueError(f"unknown prediction id: {prediction.example_id}")
                    if prediction.example_id in self.predictions:
                        raise ValueError(f"duplicate prediction id: {prediction.example_id}")
                    self.predictions[prediction.example_id] = prediction
        if self.final.exists() and set(self.predictions) != self.expected_set:
            raise ValueError("final predictions file is incomplete")

    def append(self, prediction: Prediction) -> None:
        if self.final.exists():
            raise ValueError("sealed run predictions cannot be appended")
        if prediction.example_id not in self.expected_set:
            raise ValueError(f"unknown prediction id: {prediction.example_id}")
        if prediction.example_id in self.predictions:
            raise ValueError(f"duplicate prediction id: {prediction.example_id}")
        data = (prediction.model_dump_json() + "\n").encode("utf-8")
        descriptor = os.open(self.partial, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.predictions[prediction.example_id] = prediction

    def complete(self) -> Path:
        if set(self.predictions) != self.expected_set:
            missing = self.expected_set - set(self.predictions)
            raise ValueError(f"cannot complete run with {len(missing)} missing predictions")
        if self.final.exists():
            return self.final
        os.replace(self.partial, self.final)
        directory = os.open(self.final.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return self.final


async def run_batch(
    *,
    tasks_path: Path,
    config_path: Path,
    run_dir: Path,
    mode: str,
    model: str,
    backend_kind: str,
    answer: Callable[[PublicTask], Awaitable[Prediction]],
) -> Path:
    tasks = load_public_tasks(tasks_path)
    if not tasks:
        raise ValueError("public task file is empty")
    task_ids = [task.example_id for task in tasks]
    journal = PredictionJournal(run_dir, task_ids)
    metadata_path = run_dir / "run_metadata.json"
    config_hash = sha256_file(config_path)
    public_tasks_hash = sha256_file(tasks_path)
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("public_tasks_sha256") != public_tasks_hash:
            raise ValueError("public task file changed since the run started")
        if metadata.get("config_sha256") != config_hash:
            raise ValueError("configuration changed since the run started")
        if metadata.get("task_ids") != task_ids:
            raise ValueError("public task IDs changed since the run started")
        started_at = metadata["started_at"]
    else:
        started_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "status": "running",
        "mode": mode,
        "model": model,
        "backend": backend_kind,
        "agent_enabled": mode == "agent",
        "config_sha256": config_hash,
        "public_tasks_sha256": public_tasks_hash,
        "expected_examples": len(tasks),
        "task_ids": task_ids,
        "completed_examples": len(journal.predictions),
        "started_at": started_at,
        "completed_at": None,
    }
    _atomic_json(metadata_path, metadata)
    for task in tasks:
        if task.example_id in journal.predictions:
            continue
        prediction = await answer(task)
        journal.append(prediction)
        metadata["completed_examples"] = len(journal.predictions)
        _atomic_json(metadata_path, metadata)
    predictions_path = journal.complete()
    metadata["status"] = "completed"
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(metadata_path, metadata)
    return predictions_path

