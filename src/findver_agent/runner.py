"""Resumable batch execution for Agent and Baseline modes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from findver_agent.run_identity import RunIdentity
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
        loaded_ids: list[str] = []
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
                    loaded_ids.append(prediction.example_id)
        if self.final.exists() and set(self.predictions) != self.expected_set:
            raise ValueError("final predictions file is incomplete")
        if self.final.exists() and loaded_ids != self.expected_ids:
            raise ValueError("final predictions are not in public task order")

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
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.predictions[prediction.example_id] = prediction

    def complete(self) -> Path:
        if set(self.predictions) != self.expected_set:
            missing = self.expected_set - set(self.predictions)
            raise ValueError(f"cannot complete run with {len(missing)} missing predictions")
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
                for example_id in self.expected_ids:
                    handle.write(self.predictions[example_id].model_dump_json())
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
        directory = os.open(self.final.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        try:
            self.partial.unlink()
        except FileNotFoundError:
            pass
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
    concurrency: int = 1,
    answer: Callable[[PublicTask], Awaitable[Prediction]],
    run_identity: RunIdentity | None = None,
) -> Path:
    if not 1 <= concurrency <= 32:
        raise ValueError("concurrency must be between 1 and 32")
    tasks = load_public_tasks(tasks_path)
    if not tasks:
        raise ValueError("public task file is empty")
    task_ids = [task.example_id for task in tasks]
    journal = PredictionJournal(run_dir, task_ids)
    metadata_path = run_dir / "run_metadata.json"
    config_hash = sha256_file(config_path)
    public_tasks_hash = sha256_file(tasks_path)
    identity_data = (
        run_identity.model_dump(mode="json") if run_identity is not None else None
    )
    if run_identity is not None:
        if run_dir.name != run_identity.plan_run_id:
            raise ValueError("run directory name does not match planned run identity")
        if model != run_identity.model_alias:
            raise ValueError("runtime model alias does not match planned run identity")
        if backend_kind != run_identity.backend_kind:
            raise ValueError("runtime backend does not match planned run identity")
        if config_hash != run_identity.config_sha256:
            raise ValueError("runtime config does not match planned run identity")
        if public_tasks_hash != run_identity.public_tasks_sha256:
            raise ValueError("runtime tasks do not match planned run identity")
        if concurrency != run_identity.configured_concurrency:
            raise ValueError(
                "runtime concurrency does not match planned run identity"
            )
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("public_tasks_sha256") != public_tasks_hash:
            raise ValueError("public task file changed since the run started")
        if metadata.get("config_sha256") != config_hash:
            raise ValueError("configuration changed since the run started")
        if metadata.get("task_ids") != task_ids:
            raise ValueError("public task IDs changed since the run started")
        if metadata.get("mode") != mode:
            raise ValueError("run mode changed since the run started")
        if metadata.get("model") != model:
            raise ValueError("model alias changed since the run started")
        if metadata.get("backend") != backend_kind:
            raise ValueError("backend changed since the run started")
        if metadata.get("run_identity") != identity_data:
            raise ValueError("run identity changed since the run started")
        if metadata.get("configured_concurrency", 1) != concurrency:
            raise ValueError("configured concurrency changed since the run started")
        started_at = metadata["started_at"]
        prior_duration = float(metadata.get("wall_clock_duration_seconds", 0.0))
        prior_peak = int(metadata.get("peak_concurrency", 0))
    else:
        started_at = datetime.now(timezone.utc).isoformat()
        prior_duration = 0.0
        prior_peak = 0
    invocation_started = time.perf_counter()
    remaining = [
        task for task in tasks if task.example_id not in journal.predictions
    ]
    effective_concurrency = min(concurrency, len(remaining))
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
        "run_identity": identity_data,
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
                if prediction.example_id != task.example_id:
                    raise ValueError(
                        "answer returned a prediction for the wrong example"
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
