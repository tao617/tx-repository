#!/usr/bin/env python3
"""Summarize aggregate-only reliability and efficiency metrics for one run."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


PHASES = (
    "exploration",
    "finalization",
    "review",
    "iterative_retrieval",
    "legacy",
    "baseline",
)
ERROR_KINDS = ("parse", "model", "skill", "protocol")
TOOL_NAMES = ("search_report", "read_paragraphs", "calculator")
VISIBILITY_KEYS = (
    "ledger_evidence_ids",
    "prompt_visible_evidence_ids",
    "prompt_omitted_evidence_ids",
    "dynamic_ledger_evidence_ids",
    "prompt_visible_dynamic_evidence_ids",
)
SAFE_TERMINATION_REASONS = {
    "step budget exhausted",
    "submitted_during_exploration",
    "submitted_during_finalization",
    "review_completed",
    "review_fallback",
    "review_budget_exhausted",
    "finalization_budget_exhausted",
    "iterative_rag_finalized",
}


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


def _strict_valid(prediction: dict[str, Any]) -> bool:
    evidence_ids = prediction.get("evidence_ids")
    return (
        prediction.get("status") == "completed"
        and prediction.get("label") in {"entailed", "refuted"}
        and isinstance(evidence_ids, list)
        and all(type(item) is int and item >= 0 for item in evidence_ids)
        and len(evidence_ids) == len(set(evidence_ids))
        and isinstance(prediction.get("explanation"), str)
        and bool(prediction["explanation"].strip())
    )


def _error_kind(payload: dict[str, Any], *, baseline: bool = False) -> str:
    configured = payload.get("error_type")
    if configured in ERROR_KINDS:
        return str(configured)
    message = str(payload.get("error", "")).casefold()
    if "model error" in message or (baseline and "context" in message):
        return "model"
    if "skill error" in message or message.startswith("skillerror"):
        return "skill"
    return "parse"


def _mean(value: int | float, denominator: int) -> float:
    return round(value / denominator, 6)


def _valid_id_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(type(item) is int and item >= 0 for item in value)
        and len(value) == len(set(value))
    )


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
    phase_attempts: Counter[str] = Counter()
    trace_tool_calls: Counter[str] = Counter()
    termination_reasons: Counter[str] = Counter()
    phase_errors = {phase: Counter() for phase in PHASES}
    model_calls = model_responses = input_tokens = output_tokens = 0
    seed_paragraphs_from_trace = dynamic_paragraphs_from_trace = 0
    review_triggers_from_trace = 0
    max_steps_terminated = 0
    latency_ms = 0.0
    context_records = context_report_paragraphs = context_report_characters = 0
    context_assembled_paragraphs = context_full_report = context_local_truncations = 0
    provider_context_errors = 0
    context_request_records = estimated_input_tokens = 0
    actual_provider_input_records = actual_provider_input_tokens = 0
    context_windows: Counter[str] = Counter()
    prompt_budgets: Counter[str] = Counter()
    overflow_statuses: Counter[str] = Counter()
    legacy_context_limits: Counter[str] = Counter()
    visibility_counts: Counter[str] = Counter()

    trace_files = sorted((run_dir / "traces").glob("*.jsonl"))
    for trace_path in trace_files:
        trace_seed_count: int | None = None
        trace_nonfull_context_count: int | None = None
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
                    raise ValueError(
                        f"{trace_path.name}:{line_number} payload must be an object"
                    )
                if event_name == "model_request":
                    model_calls += 1
                    phase = payload.get("phase")
                    phase_attempts[str(phase) if phase in PHASES else "legacy"] += 1
                    estimated = payload.get("estimated_input_tokens")
                    if type(estimated) is int and estimated >= 0:
                        context_request_records += 1
                        estimated_input_tokens += estimated
                        window = payload.get("model_context_window_tokens")
                        if type(window) is int and window > 0:
                            context_windows[str(window)] += 1
                        prompt_budget = payload.get("prompt_budget_tokens")
                        if type(prompt_budget) is int and prompt_budget > 0:
                            prompt_budgets[str(prompt_budget)] += 1
                        overflow_status = payload.get("overflow_status")
                        if overflow_status in {
                            "within_window", "estimated_overflow", "not_enforced"
                        }:
                            overflow_statuses[str(overflow_status)] += 1
                    present_visibility = [
                        key for key in VISIBILITY_KEYS if key in payload
                    ]
                    if present_visibility:
                        if len(present_visibility) != len(VISIBILITY_KEYS) or any(
                            not _valid_id_list(payload.get(key))
                            for key in VISIBILITY_KEYS
                        ):
                            raise ValueError(
                                f"{trace_path.name}:{line_number} has invalid evidence visibility IDs"
                            )
                        ids = {key: list(payload[key]) for key in VISIBILITY_KEYS}
                        ledger = set(ids["ledger_evidence_ids"])
                        visible = set(ids["prompt_visible_evidence_ids"])
                        omitted = set(ids["prompt_omitted_evidence_ids"])
                        dynamic = set(ids["dynamic_ledger_evidence_ids"])
                        visible_dynamic = set(
                            ids["prompt_visible_dynamic_evidence_ids"]
                        )
                        if (
                            visible & omitted
                            or visible | omitted != ledger
                            or not dynamic <= ledger
                            or not visible_dynamic <= dynamic & visible
                        ):
                            raise ValueError(
                                f"{trace_path.name}:{line_number} has inconsistent evidence visibility IDs"
                            )
                        visibility_counts["instrumented_requests"] += 1
                        visibility_counts["ledger"] += len(ledger)
                        visibility_counts["visible"] += len(visible)
                        visibility_counts["omitted"] += len(omitted)
                        visibility_counts["dynamic_ledger"] += len(dynamic)
                        visibility_counts["dynamic_visible"] += len(visible_dynamic)
                elif event_name == "model_response":
                    model_responses += 1
                    input_tokens += int(payload.get("input_tokens", 0))
                    output_tokens += int(payload.get("output_tokens", 0))
                    latency_ms += float(payload.get("latency_ms", 0))
                    actual_input = payload.get("actual_provider_input_tokens")
                    if type(actual_input) is int and actual_input >= 0:
                        actual_provider_input_records += 1
                        actual_provider_input_tokens += actual_input
                elif event_name == "action":
                    action_name = payload.get("action")
                    if isinstance(action_name, str):
                        action_attempts[action_name] += 1
                elif event_name == "tool_result":
                    skill = payload.get("skill")
                    if skill in TOOL_NAMES:
                        trace_tool_calls[str(skill)] += 1
                    elif {"expression", "result"}.issubset(payload):
                        trace_tool_calls["calculator"] += 1
                elif event_name == "retrieval_seed_loaded":
                    paragraph_ids = payload.get("paragraph_ids", [])
                    if isinstance(paragraph_ids, list):
                        trace_seed_count = len(paragraph_ids)
                elif event_name == "dynamic_evidence_loaded":
                    paragraph_ids = payload.get("paragraph_ids", [])
                    if isinstance(paragraph_ids, list):
                        dynamic_paragraphs_from_trace += len(paragraph_ids)
                elif event_name == "review_triggered":
                    review_triggers_from_trace += 1
                elif event_name == "recoverable_error":
                    phase = payload.get("phase")
                    phase_name = str(phase) if phase in PHASES else "legacy"
                    phase_errors[phase_name][_error_kind(payload)] += 1
                    error_text = payload.get("error")
                    if (
                        payload.get("error_type") == "model"
                        and isinstance(error_text, str)
                        and (
                            "context window" in error_text.casefold()
                            or "context length" in error_text.casefold()
                        )
                    ):
                        provider_context_errors += 1
                elif event_name == "baseline_error":
                    phase_errors["baseline"][_error_kind(payload, baseline=True)] += 1
                    provider_context_errors += int(
                        payload.get("provider_context_error") is True
                    )
                elif event_name == "input_context":
                    context_records += 1
                    context_report_paragraphs += int(
                        payload.get("report_paragraph_count", 0)
                    )
                    context_report_characters += int(
                        payload.get("report_character_count", 0)
                    )
                    assembled = int(payload.get("assembled_paragraph_count", 0))
                    context_assembled_paragraphs += assembled
                    is_full = payload.get("full_report_assembled") is True
                    context_full_report += int(is_full)
                    context_local_truncations += int(
                        payload.get("local_truncation") is True
                    )
                    if not is_full:
                        trace_nonfull_context_count = assembled
                    limit = payload.get("model_context_limit")
                    if type(limit) is int and limit > 0:
                        legacy_context_limits[str(limit)] += 1
                elif event_name == "question_closed":
                    reason = payload.get("reason")
                    status = payload.get("status", "unknown")
                    if not isinstance(reason, str) or not reason:
                        reason = f"{status}_unspecified"
                    elif reason not in SAFE_TERMINATION_REASONS:
                        # Error strings may contain provider or task material.
                        reason = f"{status}_other"
                    termination_reasons[reason] += 1
                    if reason == "step budget exhausted":
                        max_steps_terminated += 1
        if trace_seed_count is not None:
            seed_paragraphs_from_trace += trace_seed_count
        elif trace_nonfull_context_count is not None:
            seed_paragraphs_from_trace += trace_nonfull_context_count

    state_files = sorted((run_dir / "state").glob("*.json"))
    state_tool_calls: Counter[str] = Counter()
    seed_paragraphs_from_state = dynamic_paragraphs_from_state = 0
    review_completed = review_triggered = review_fallbacks = review_label_changes = 0
    has_state_tool_metrics = False
    has_state_seed_metrics = False
    has_state_evidence_metrics = False
    has_state_review_metrics = False
    for state_path in state_files:
        state = _load_object(state_path)
        tool_counts = state.get("tool_counts")
        if isinstance(tool_counts, dict):
            has_state_tool_metrics = True
            for tool in TOOL_NAMES:
                state_tool_calls[tool] += int(tool_counts.get(tool, 0))
        initial = state.get("initial_retrieval_state")
        if isinstance(initial, dict):
            has_state_seed_metrics = True
            paragraph_ids = initial.get("paragraph_ids", [])
            if isinstance(paragraph_ids, list):
                seed_paragraphs_from_state += len(paragraph_ids)
        evidence = state.get("evidence_ledger")
        if isinstance(evidence, list):
            has_state_evidence_metrics = True
            dynamic_paragraphs_from_state += sum(
                1
                for record in evidence
                if isinstance(record, dict)
                and not str(record.get("source", "report")).startswith("fixed_rag:")
            )
        if any(key.startswith("review_") for key in state):
            has_state_review_metrics = True
        review_completed += int(state.get("review_completed") is True)
        review_triggered += int(state.get("review_triggered") is True)
        review_fallbacks += int(state.get("review_fallback_used") is True)
        review_label_changes += int(state.get("review_changed_label") is True)

    tool_calls = state_tool_calls if has_state_tool_metrics else trace_tool_calls
    seed_paragraphs = (
        seed_paragraphs_from_state
        if has_state_seed_metrics
        else seed_paragraphs_from_trace
    )
    dynamic_paragraphs = (
        dynamic_paragraphs_from_state
        if has_state_evidence_metrics
        else dynamic_paragraphs_from_trace
    )
    if not has_state_review_metrics:
        review_triggered = review_triggers_from_trace

    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise ValueError("latency total must be finite and non-negative")
    invalid = sum(
        1 for prediction in predictions if prediction.get("status") != "completed"
    )
    strict_valid = sum(1 for prediction in predictions if _strict_valid(prediction))
    exploration_attempts = phase_attempts["exploration"]
    if metadata.get("mode") == "agent":
        exploration_attempts += phase_attempts["legacy"]
    phase_error_output = {
        phase: {kind: int(phase_errors[phase].get(kind, 0)) for kind in ERROR_KINDS}
        for phase in PHASES
    }
    totals = {
        "steps": model_calls,
        "model_calls": model_calls,
        "model_responses": model_responses,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": round(latency_ms, 3),
        "exploration_steps": exploration_attempts,
        "finalization_attempts": phase_attempts["finalization"],
        "review_attempts": phase_attempts["review"],
        "iterative_retrieval_attempts": phase_attempts["iterative_retrieval"],
        "search_calls": tool_calls["search_report"],
        "read_calls": tool_calls["read_paragraphs"],
        "calculator_calls": tool_calls["calculator"],
        "seed_paragraphs": seed_paragraphs,
        "dynamic_paragraphs": dynamic_paragraphs,
        "review_triggered": review_triggered,
        "review_completed": review_completed,
        "review_fallbacks": review_fallbacks,
        "review_label_changes": review_label_changes,
        "max_steps_terminated": max_steps_terminated,
        "action_attempts": dict(sorted(action_attempts.items())),
        "termination_reasons": dict(sorted(termination_reasons.items())),
        "phase_errors": phase_error_output,
    }
    means = {
        "steps": _mean(model_calls, expected),
        "model_calls": _mean(model_calls, expected),
        "input_tokens": _mean(input_tokens, expected),
        "output_tokens": _mean(output_tokens, expected),
        "latency_ms": _mean(latency_ms, expected),
        "exploration_steps": _mean(exploration_attempts, expected),
        "finalization_attempts": _mean(phase_attempts["finalization"], expected),
        "review_attempts": _mean(phase_attempts["review"], expected),
        "iterative_retrieval_attempts": _mean(
            phase_attempts["iterative_retrieval"], expected
        ),
        "search_calls": _mean(tool_calls["search_report"], expected),
        "read_calls": _mean(tool_calls["read_paragraphs"], expected),
        "calculator_calls": _mean(tool_calls["calculator"], expected),
        "seed_paragraphs": _mean(seed_paragraphs, expected),
        "dynamic_paragraphs": _mean(dynamic_paragraphs, expected),
        "action_attempts": {
            name: _mean(count, expected)
            for name, count in sorted(action_attempts.items())
        },
        "review_completed": _mean(review_completed, expected),
        "max_steps_terminated": _mean(max_steps_terminated, expected),
    }
    summary: dict[str, Any] = {
        "schema_version": 2,
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
            "file_completion_rate": _mean(len(predictions), expected),
            "valid_output_rate": _mean(strict_valid, expected),
            "invalid_rate": _mean(invalid, expected),
            "review_trigger_rate": _mean(review_triggered, expected),
            "prediction_coverage": _mean(len(predictions), expected),
            "invalid": _mean(invalid, expected),
            "strict_valid": _mean(strict_valid, expected),
            "review_trigger": _mean(review_triggered, expected),
        },
        "totals": totals,
        "means_per_expected_example": means,
        "evidence_visibility": {
            "instrumented_model_requests": visibility_counts[
                "instrumented_requests"
            ],
            "ledger_request_occurrences": visibility_counts["ledger"],
            "visible_request_occurrences": visibility_counts["visible"],
            "omitted_request_occurrences": visibility_counts["omitted"],
            "dynamic_ledger_request_occurrences": visibility_counts[
                "dynamic_ledger"
            ],
            "dynamic_visible_request_occurrences": visibility_counts[
                "dynamic_visible"
            ],
            "overall_visibility_rate": (
                _mean(visibility_counts["visible"], visibility_counts["ledger"])
                if visibility_counts["ledger"]
                else 0.0
            ),
            "dynamic_visibility_rate": (
                _mean(
                    visibility_counts["dynamic_visible"],
                    visibility_counts["dynamic_ledger"],
                )
                if visibility_counts["dynamic_ledger"]
                else 0.0
            ),
        },
        "long_context": {
            "instrumented_examples": context_records,
            "instrumented_model_requests": context_request_records,
            "mean_estimated_input_tokens": (
                _mean(estimated_input_tokens, context_request_records)
                if context_request_records
                else 0.0
            ),
            "instrumented_provider_responses": actual_provider_input_records,
            "mean_actual_provider_input_tokens": (
                _mean(actual_provider_input_tokens, actual_provider_input_records)
                if actual_provider_input_records
                else 0.0
            ),
            "configured_model_context_windows": dict(
                sorted(context_windows.items())
            ),
            "configured_prompt_budgets": dict(sorted(prompt_budgets.items())),
            "overflow_status_counts": dict(sorted(overflow_statuses.items())),
            "mean_report_paragraphs": (
                _mean(context_report_paragraphs, context_records)
                if context_records
                else 0.0
            ),
            "mean_report_characters": (
                _mean(context_report_characters, context_records)
                if context_records
                else 0.0
            ),
            "mean_assembled_paragraphs": (
                _mean(context_assembled_paragraphs, context_records)
                if context_records
                else 0.0
            ),
            "full_report_assembly_rate": (
                _mean(context_full_report, context_records)
                if context_records
                else 0.0
            ),
            "local_truncation_count": context_local_truncations,
            "provider_context_error_count": provider_context_errors,
            "legacy_configured_context_limits": dict(
                sorted(legacy_context_limits.items())
            ),
        },
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
