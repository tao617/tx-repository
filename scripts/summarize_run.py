#!/usr/bin/env python3
"""Summarize non-sensitive efficiency metrics from one completed run."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _load_predictions(path: Path) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"prediction line {line_number} must be an object")
            predictions.append(value)
    return predictions


def summarize(
    run_dir: Path,
    *,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> dict[str, Any]:
    metadata = _load_object(run_dir / "run_metadata.json")
    predictions = _load_predictions(run_dir / "predictions.jsonl")
    expected = int(metadata["expected_examples"])
    if expected <= 0:
        raise ValueError("expected_examples must be positive")
    if len(predictions) > expected:
        raise ValueError("prediction count exceeds expected_examples")

    action_attempts: Counter[str] = Counter()
    steps = model_calls = input_tokens = output_tokens = 0
    latency_ms = 0.0
    trace_files = sorted((run_dir / "traces").glob("*.jsonl"))
    for trace_path in trace_files:
        with trace_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError(f"{trace_path.name}:{line_number} must be an object")
                event_name = event.get("event")
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    raise ValueError(f"{trace_path.name}:{line_number} payload must be an object")
                if event_name == "model_request":
                    steps += 1
                elif event_name == "model_response":
                    model_calls += 1
                    input_tokens += int(payload.get("input_tokens", 0))
                    output_tokens += int(payload.get("output_tokens", 0))
                    latency_ms += float(payload.get("latency_ms", 0))
                elif event_name == "action":
                    action_name = payload.get("action")
                    if isinstance(action_name, str):
                        action_attempts[action_name] += 1

    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("latency total must be finite and non-negative")
    invalid = sum(1 for prediction in predictions if prediction.get("status") != "completed")
    totals = {
        "steps": steps,
        "model_calls": model_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": round(latency_ms, 3),
        "action_attempts": dict(sorted(action_attempts.items())),
    }
    means = {
        "steps": round(steps / expected, 6),
        "model_calls": round(model_calls / expected, 6),
        "input_tokens": round(input_tokens / expected, 6),
        "output_tokens": round(output_tokens / expected, 6),
        "latency_ms": round(latency_ms / expected, 6),
        "action_attempts": {
            name: round(count / expected, 6) for name, count in sorted(action_attempts.items())
        },
    }
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run": {
            key: metadata.get(key)
            for key in (
                "status",
                "mode",
                "model",
                "backend",
                "config_sha256",
                "public_tasks_sha256",
                "expected_examples",
                "completed_examples",
            )
        },
        "rates": {
            "prediction_coverage": round(len(predictions) / expected, 6),
            "invalid": round(invalid / expected, 6),
        },
        "totals": totals,
        "means_per_expected_example": means,
    }
    if input_cost_per_million is not None or output_cost_per_million is not None:
        if input_cost_per_million is None or output_cost_per_million is None:
            raise ValueError("both input and output prices are required")
        if input_cost_per_million < 0 or output_cost_per_million < 0:
            raise ValueError("prices must be non-negative")
        input_cost = input_tokens * input_cost_per_million / 1_000_000
        output_cost = output_tokens * output_cost_per_million / 1_000_000
        summary["estimated_cost_usd"] = {
            "input": round(input_cost, 8),
            "output": round(output_cost, 8),
            "total": round(input_cost + output_cost, 8),
            "input_per_million_tokens": input_cost_per_million,
            "output_per_million_tokens": output_cost_per_million,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    args = parser.parse_args()
    result = summarize(
        args.run_dir,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
