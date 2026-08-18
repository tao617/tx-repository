#!/usr/bin/env python3
"""Verify the no-credential multi-question concurrency Docker smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from findver_agent.evidence_sidecar import SIDECAR_NAME
from findver_agent.submission import verify_submission_archive


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def verify(run_dir: Path, tasks_path: Path, submission: Path) -> dict[str, int | float]:
    tasks = _jsonl(tasks_path)
    expected_ids = [str(task["example_id"]) for task in tasks]
    expected_statements = {
        str(task["example_id"]): str(task["statement"]) for task in tasks
    }
    metadata = json.loads(
        (run_dir / "run_metadata.json").read_text(encoding="utf-8")
    )
    if metadata.get("status") != "completed":
        raise AssertionError("concurrent smoke did not complete")
    if metadata.get("configured_concurrency") != 32:
        raise AssertionError("configured concurrency is not frozen at 32")
    if metadata.get("effective_concurrency") != 32:
        raise AssertionError("40-task smoke did not start a 32-worker pool")
    peak = metadata.get("peak_concurrency")
    if type(peak) is not int or not 1 < peak <= 32:
        raise AssertionError("concurrent smoke peak is outside 2..32")

    predictions = _jsonl(run_dir / "predictions.jsonl")
    if [prediction.get("example_id") for prediction in predictions] != expected_ids:
        raise AssertionError("final predictions are not in public task order")
    if (run_dir / "predictions.partial.jsonl").exists():
        raise AssertionError("completed concurrent smoke retained partial predictions")

    states = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_dir / "state").glob("*.json"))
    ]
    if len(states) != len(expected_ids):
        raise AssertionError("concurrent smoke state population is incomplete")
    actual_statements = {
        state.get("example_id"): state.get("statement") for state in states
    }
    if actual_statements != expected_statements:
        raise AssertionError("question state crossed example boundaries")
    if any(state.get("usage", {}).get("model_calls") != 1 for state in states):
        raise AssertionError("each concurrent smoke question must make one model call")

    trace_files = sorted((run_dir / "traces").glob("*.jsonl"))
    if len(trace_files) != len(expected_ids):
        raise AssertionError("concurrent smoke trace population is incomplete")
    for trace_path in trace_files:
        events = _jsonl(trace_path)
        if len({event.get("example_id") for event in events}) != 1:
            raise AssertionError("a trace contains cross-question events")
        requests = [event for event in events if event.get("event") == "model_request"]
        responses = [event for event in events if event.get("event") == "model_response"]
        if len(requests) != 1 or len(responses) != 1:
            raise AssertionError("each concurrent question must have one request and response")
        request_payload = requests[0].get("payload", {})
        response_payload = responses[0].get("payload", {})
        if request_payload.get("request_profile") != "deepseek_openai_chat":
            raise AssertionError("DeepSeek request profile is missing from trace")
        if request_payload.get("thinking_mode") != "disabled":
            raise AssertionError("disabled thinking provenance is missing from trace")
        if response_payload.get("finish_reason") != "stop":
            raise AssertionError("mock response finish reason was not retained")

    manifest, sealed_predictions = verify_submission_archive(
        submission,
        evidence_ledger_sidecar=run_dir / SIDECAR_NAME,
    )
    if [prediction.example_id for prediction in sealed_predictions] != expected_ids:
        raise AssertionError("sealed prediction order differs from public tasks")
    if manifest.submitted_examples != len(expected_ids):
        raise AssertionError("sealed concurrent smoke population is incomplete")

    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    if "reasoning_content" in persisted:
        raise AssertionError("hidden reasoning field leaked into Runtime artifacts")
    return {
        "examples": len(expected_ids),
        "configured_concurrency": 32,
        "peak_concurrency": peak,
        "wall_clock_duration_seconds": float(
            metadata.get("wall_clock_duration_seconds", 0.0)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--submission", required=True, type=Path)
    args = parser.parse_args()
    result = verify(
        args.run_dir.resolve(strict=True),
        args.tasks.resolve(strict=True),
        args.submission.resolve(strict=True),
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
