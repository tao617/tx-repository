"""Resumable bounded batch execution for generic tasks."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from findver_agent.generic.models import (
    GenericPrediction,
    GenericTask,
    GenericTaskProfile,
)
from findver_agent.runner import sha256_file


def load_generic_tasks(path: Path) -> list[GenericTask]:
    tasks: list[GenericTask] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                task = GenericTask.model_validate_json(line)
            except ValueError as error:
                raise ValueError(
                    f"invalid generic task on line {line_number}: {error}"
                ) from error
            if task.task_id in seen:
                raise ValueError(f"duplicate generic task id: {task.task_id}")
            seen.add(task.task_id)
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


class GenericPredictionJournal:
    def __init__(self, run_dir: Path, expected_ids: list[str]) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        self.partial = run_dir / "predictions.partial.jsonl"
        self.final = run_dir / "predictions.jsonl"
        self.expected_ids = expected_ids
        self.expected_set = set(expected_ids)
        self.predictions: dict[str, GenericPrediction] = {}
        loaded_ids: list[str] = []
        source = self.final if self.final.exists() else self.partial
        if source.exists():
            with source.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        prediction = GenericPrediction.model_validate_json(line)
                    except ValueError as error:
                        raise ValueError(
                            f"invalid generic prediction on line {line_number}: {error}"
                        ) from error
                    if prediction.task_id not in self.expected_set:
                        raise ValueError(f"unknown generic prediction id: {prediction.task_id}")
                    if prediction.task_id in self.predictions:
                        raise ValueError(
                            f"duplicate generic prediction id: {prediction.task_id}"
                        )
                    self.predictions[prediction.task_id] = prediction
                    loaded_ids.append(prediction.task_id)
        if self.final.exists() and set(self.predictions) != self.expected_set:
            raise ValueError("final generic predictions file is incomplete")
        if self.final.exists() and loaded_ids != self.expected_ids:
            raise ValueError("final generic predictions are not in task order")

    def append(self, prediction: GenericPrediction) -> None:
        if self.final.exists():
            raise ValueError("completed generic predictions cannot be appended")
        if prediction.task_id not in self.expected_set:
            raise ValueError(f"unknown generic prediction id: {prediction.task_id}")
        if prediction.task_id in self.predictions:
            raise ValueError(f"duplicate generic prediction id: {prediction.task_id}")
        data = (prediction.model_dump_json() + "\n").encode("utf-8")
        descriptor = os.open(self.partial, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.predictions[prediction.task_id] = prediction

    def complete(self) -> Path:
        if set(self.predictions) != self.expected_set:
            missing = self.expected_set - set(self.predictions)
            raise ValueError(
                f"cannot complete generic run with {len(missing)} missing predictions"
            )
        if self.final.exists():
            try:
                self.partial.unlink()
            except FileNotFoundError:
                pass
            return self.final
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.final.name}.", dir=self.final.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                for task_id in self.expected_ids:
                    handle.write(self.predictions[task_id].model_dump_json())
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.final)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        try:
            self.partial.unlink()
        except FileNotFoundError:
            pass
        return self.final


async def run_generic_batch(
    *,
    tasks_path: Path,
    config_path: Path,
    profile_path: Path,
    profile: GenericTaskProfile,
    run_dir: Path,
    model: str,
    backend_kind: str,
    concurrency: int,
    answer: Callable[[GenericTask], Awaitable[GenericPrediction]],
) -> Path:
    if not 1 <= concurrency <= 32:
        raise ValueError("concurrency must be between 1 and 32")
    tasks = load_generic_tasks(tasks_path)
    if not tasks:
        raise ValueError("generic task file is empty")
    task_ids = [task.task_id for task in tasks]
    journal = GenericPredictionJournal(run_dir, task_ids)
    metadata_path = run_dir / "run_metadata.json"
    config_hash = sha256_file(config_path)
    profile_hash = sha256_file(profile_path)
    tasks_hash = sha256_file(tasks_path)
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected = {
            "config_sha256": config_hash,
            "profile_sha256": profile_hash,
            "public_tasks_sha256": tasks_hash,
            "profile_id": profile.profile_id,
            "task_ids": task_ids,
            "model": model,
            "backend": backend_kind,
            "configured_concurrency": concurrency,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(f"generic run {key} changed since the run started")
        started_at = metadata["started_at"]
        prior_duration = float(metadata.get("wall_clock_duration_seconds", 0.0))
        prior_peak = int(metadata.get("peak_concurrency", 0))
    else:
        started_at = datetime.now(timezone.utc).isoformat()
        prior_duration = 0.0
        prior_peak = 0
    invocation_started = time.perf_counter()
    remaining = [task for task in tasks if task.task_id not in journal.predictions]
    effective_concurrency = min(concurrency, len(remaining))
    metadata = {
        "status": "running",
        "mode": "generic_agent",
        "model": model,
        "backend": backend_kind,
        "profile_id": profile.profile_id,
        "config_sha256": config_hash,
        "profile_sha256": profile_hash,
        "public_tasks_sha256": tasks_hash,
        "expected_examples": len(tasks),
        "task_ids": task_ids,
        "configured_concurrency": concurrency,
        "effective_concurrency": effective_concurrency,
        "peak_concurrency": prior_peak,
        "wall_clock_duration_seconds": prior_duration,
        "completed_examples": len(journal.predictions),
        "started_at": started_at,
        "completed_at": None,
        "interrupted_at": None,
        "fatal_error_type": None,
    }
    _atomic_json(metadata_path, metadata)
    next_index = 0
    active = 0
    peak = prior_peak
    stop_assigning = asyncio.Event()
    assignment_lock = asyncio.Lock()
    first_error: list[BaseException] = []

    def update_elapsed() -> None:
        metadata["wall_clock_duration_seconds"] = round(
            prior_duration + time.perf_counter() - invocation_started,
            6,
        )

    async def worker() -> None:
        nonlocal next_index, active, peak
        while True:
            async with assignment_lock:
                if stop_assigning.is_set() or next_index >= len(remaining):
                    return
                task = remaining[next_index]
                next_index += 1
                active += 1
                peak = max(peak, active)
                metadata["peak_concurrency"] = peak
            try:
                prediction = await answer(task)
                if prediction.task_id != task.task_id:
                    raise ValueError(
                        "generic answer returned a prediction for the wrong task"
                    )
                journal.append(prediction)
                metadata["completed_examples"] = len(journal.predictions)
                update_elapsed()
                _atomic_json(metadata_path, metadata)
            except BaseException as error:
                if not first_error:
                    first_error.append(error)
                    stop_assigning.set()
                return
            finally:
                active -= 1

    workers = [
        asyncio.create_task(worker()) for _ in range(effective_concurrency)
    ]
    if workers:
        await asyncio.gather(*workers)
    if first_error:
        metadata["status"] = "interrupted"
        metadata["interrupted_at"] = datetime.now(timezone.utc).isoformat()
        metadata["fatal_error_type"] = type(first_error[0]).__name__
        update_elapsed()
        _atomic_json(metadata_path, metadata)
        raise first_error[0]
    predictions_path = journal.complete()
    metadata["status"] = "completed"
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    update_elapsed()
    _atomic_json(metadata_path, metadata)
    return predictions_path
