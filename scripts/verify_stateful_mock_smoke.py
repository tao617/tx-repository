#!/usr/bin/env python3
"""Verify the deterministic stateful M2 Docker smoke without scorer data."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


EXPECTED_ACTIONS = [
    "search_report",
    "read_paragraphs",
    "calculator",
    "search_report",
    "read_paragraphs",
    "calculator",
    "search_report",
    "submit_answer",
]


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain one JSON object")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    values = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(value, dict) for value in values):
        raise AssertionError(f"{path} must contain JSON objects")
    return values


def _only_path(root: Path, pattern: str) -> Path:
    paths = sorted(root.glob(pattern))
    if len(paths) != 1:
        raise AssertionError(f"expected exactly one {pattern} under {root}")
    return paths[0]


def verify(
    run_dir: Path,
    *,
    expect_long_context: bool = False,
) -> dict[str, int | str]:
    metadata = _load_object(run_dir / "run_metadata.json")
    if metadata.get("status") != "completed":
        raise AssertionError("stateful smoke run did not complete")

    predictions = _load_jsonl(run_dir / "predictions.jsonl")
    if len(predictions) != 1:
        raise AssertionError("stateful smoke must produce exactly one prediction")
    prediction = predictions[0]
    if (
        prediction.get("status") != "completed"
        or prediction.get("label") != "entailed"
        or prediction.get("evidence_ids") != [0]
    ):
        raise AssertionError("stateful smoke prediction is not the verified draft")

    state = _load_object(_only_path(run_dir / "state", "*.json"))
    if state.get("termination_reason") != "review_fallback":
        raise AssertionError("review failure did not fall back to the verified draft")
    if state.get("review_fallback_used") is not True:
        raise AssertionError("review fallback flag is missing")
    if state.get("review_triggered") is not True:
        raise AssertionError("selective review was not triggered")
    if state.get("tool_counts") != {
        "search_report": 2,
        "read_paragraphs": 2,
        "calculator": 2,
    }:
        raise AssertionError("stateful tool sequence did not execute as planned")
    if state.get("usage", {}).get("model_calls") != 9:
        raise AssertionError("stateful smoke must make exactly nine model calls")
    if state.get("phase_errors", {}).get("finalization", {}).get("protocol") != 1:
        raise AssertionError("finalization protocol retry was not recorded")
    if state.get("phase_errors", {}).get("review", {}).get("parse") != 1:
        raise AssertionError("review parse failure was not recorded")
    if "weak_support" in state.get("risk_flags", []):
        raise AssertionError("rejected finalization action polluted persistent risk")
    if "weak_support" in state.get("draft_risk_flags", []):
        raise AssertionError("rejected finalization action polluted draft risk")
    if "calculation" not in state.get("draft_risk_flags", []):
        raise AssertionError("accepted calculator risk is missing from the draft")
    if expect_long_context:
        long_context = state.get("long_context_state")
        if not isinstance(long_context, dict):
            raise AssertionError("LC smoke is missing durable long-context state")
        if (
            long_context.get("injected") is not True
            or long_context.get("injection_attempt") != 1
        ):
            raise AssertionError("LC smoke did not claim exactly the first attempt")
        if state.get("initial_retrieval_state") is not None:
            raise AssertionError("LC smoke unexpectedly loaded initial retrieval")

    events = _load_jsonl(_only_path(run_dir / "traces", "*.jsonl"))
    model_requests = [event for event in events if event.get("event") == "model_request"]
    model_responses = [event for event in events if event.get("event") == "model_response"]
    if len(model_requests) != 9 or len(model_responses) != 9:
        raise AssertionError("stateful trace must contain nine requests and responses")
    if any(
        event.get("payload", {}).get("request_profile")
        != "deepseek_openai_chat"
        or event.get("payload", {}).get("thinking_mode") != "disabled"
        for event in model_requests
    ):
        raise AssertionError("DeepSeek disabled-thinking provenance is incomplete")
    if any(
        event.get("payload", {}).get("finish_reason") != "stop"
        for event in model_responses
    ):
        raise AssertionError("stateful finish reasons were not retained")
    phases = Counter(
        str(event.get("payload", {}).get("phase")) for event in model_requests
    )
    if phases != {"exploration": 6, "finalization": 2, "review": 1}:
        raise AssertionError("stateful trace has unexpected phase attempts")
    if expect_long_context:
        injection_flags = [
            event.get("payload", {}).get("long_context_injected")
            for event in model_requests
        ]
        if injection_flags != [True, *([False] * 8)]:
            raise AssertionError("LC smoke did not inject exactly one first-pass report")
        contexts = [
            event.get("payload", {})
            for event in events
            if event.get("event") == "input_context"
            and event.get("payload", {}).get("long_context_injected") is True
        ]
        if len(contexts) != 1 or (
            contexts[0].get("phase"), contexts[0].get("phase_attempt")
        ) != ("exploration", 1):
            raise AssertionError("LC smoke has invalid context injection telemetry")
    actions = [
        event.get("payload", {}).get("action")
        for event in events
        if event.get("event") == "action"
    ]
    if actions != EXPECTED_ACTIONS:
        raise AssertionError("stateful trace has an unexpected action sequence")

    errors = [
        event.get("payload", {})
        for event in events
        if event.get("event") == "recoverable_error"
    ]
    error_pairs = {
        (error.get("phase"), error.get("error_type")) for error in errors
    }
    if ("finalization", "protocol") not in error_pairs:
        raise AssertionError("missing finalization protocol error trace")
    if ("review", "parse") not in error_pairs:
        raise AssertionError("missing review parse error trace")

    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    if "reasoning_content" in persisted:
        raise AssertionError("hidden reasoning field leaked into Runtime artifacts")

    return {
        "model_calls": len(model_requests),
        "actions": len(actions),
        "termination_reason": "review_fallback",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--expect-long-context", action="store_true")
    args = parser.parse_args()
    result = verify(
        args.run_dir.resolve(strict=True),
        expect_long_context=args.expect_long_context,
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
