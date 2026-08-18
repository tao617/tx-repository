import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "summarize_run.py"
SPEC = importlib.util.spec_from_file_location("summarize_run", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_jsonl(path, values):
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def test_summary_contains_only_aggregate_efficiency_metrics(tmp_path):
    run = tmp_path / "run"
    traces = run / "traces"
    traces.mkdir(parents=True)
    (run / "state").mkdir()
    (run / "run_metadata.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "agent",
                "model": "alias",
                "backend": "api",
                "config_sha256": "c" * 64,
                "public_tasks_sha256": "d" * 64,
                "expected_examples": 2,
                "completed_examples": 2,
                "task_ids": ["private-id-1", "private-id-2"],
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(
        run / "predictions.jsonl",
        [
            {"example_id": "private-id-1", "status": "completed"},
            {"example_id": "private-id-2", "status": "invalid"},
        ],
    )
    write_jsonl(
        traces / "trace.jsonl",
        [
            {
                "event": "model_request",
                "payload": {
                    "messages": ["secret statement"],
                    "ledger_evidence_ids": [1, 2, 3],
                    "prompt_visible_evidence_ids": [2, 3],
                    "prompt_omitted_evidence_ids": [1],
                    "dynamic_ledger_evidence_ids": [3],
                    "prompt_visible_dynamic_evidence_ids": [3],
                },
            },
            {
                "event": "model_response",
                "payload": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "latency_ms": 50.5,
                    "rate_limit_wait_ms": 125.0,
                    "transport_retries": 1,
                },
            },
            {"event": "action", "payload": {"action": "search_report"}},
            {"event": "model_request", "payload": {}},
            {
                "event": "model_response",
                "payload": {"input_tokens": 80, "output_tokens": 10, "latency_ms": 49.5},
            },
            {"event": "action", "payload": {"action": "submit_answer"}},
            {"event": "tool_result", "payload": {"expression": "1+1", "result": 2}},
            {
                "event": "question_closed",
                "payload": {"status": "invalid", "reason": "step budget exhausted"},
            },
        ],
    )
    (run / "state" / "one.json").write_text(
        json.dumps({"review_completed": True}), encoding="utf-8"
    )

    summary = MODULE.summarize(
        run,
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
    )
    rendered = json.dumps(summary)

    assert summary["rates"] == {
        "file_completion_rate": 1.0,
        "valid_output_rate": 0.0,
        "invalid_rate": 0.5,
        "review_trigger_rate": 0.0,
        "prediction_coverage": 1.0,
        "invalid": 0.5,
        "strict_valid": 0.0,
        "review_trigger": 0.0,
    }
    assert summary["totals"]["steps"] == 2
    assert summary["totals"]["model_calls"] == 2
    assert summary["totals"]["input_tokens"] == 180
    assert summary["totals"]["rate_limit_wait_ms"] == 125.0
    assert summary["totals"]["transport_retries"] == 1
    assert summary["totals"]["action_attempts"] == {
        "search_report": 1,
        "submit_answer": 1,
    }
    assert summary["totals"]["calculator_calls"] == 1
    assert summary["totals"]["review_completed"] == 1
    assert summary["totals"]["max_steps_terminated"] == 1
    assert summary["evidence_visibility"] == {
        "instrumented_model_requests": 1,
        "ledger_request_occurrences": 3,
        "visible_request_occurrences": 2,
        "omitted_request_occurrences": 1,
        "dynamic_ledger_request_occurrences": 1,
        "dynamic_visible_request_occurrences": 1,
        "overall_visibility_rate": 0.666667,
        "dynamic_visibility_rate": 1.0,
    }
    assert summary["estimated_cost_usd"]["total"] == 0.00024
    assert "private-id" not in rendered
    assert "secret statement" not in rendered


def test_cost_requires_both_prices(tmp_path):
    run = tmp_path / "run"
    (run / "traces").mkdir(parents=True)
    (run / "run_metadata.json").write_text(
        json.dumps({"expected_examples": 1}), encoding="utf-8"
    )
    (run / "predictions.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="both input and output prices"):
        MODULE.summarize(run, input_cost_per_million=1.0)


def test_summary_rejects_unknown_finish_reason(tmp_path):
    run = tmp_path / "run"
    (run / "traces").mkdir(parents=True)
    (run / "run_metadata.json").write_text(
        json.dumps({"expected_examples": 1}), encoding="utf-8"
    )
    (run / "predictions.jsonl").write_text("", encoding="utf-8")
    write_jsonl(
        run / "traces" / "trace.jsonl",
        [{"event": "model_response", "payload": {"finish_reason": "mystery"}}],
    )

    with pytest.raises(ValueError, match="unknown finish_reason"):
        MODULE.summarize(run)
