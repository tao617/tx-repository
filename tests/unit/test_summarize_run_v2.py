import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "summarize_run.py"
SPEC = importlib.util.spec_from_file_location("summarize_run_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_jsonl(path, values):
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def test_v2_summary_reports_phase_failure_review_evidence_and_context_aggregates(tmp_path):
    run = tmp_path / "run"
    (run / "traces").mkdir(parents=True)
    (run / "state").mkdir()
    (run / "run_metadata.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "agent",
                "model": "model-a",
                "backend": "mock",
                "expected_examples": 1,
                "completed_examples": 1,
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(
        run / "predictions.jsonl",
        [
            {
                "example_id": "sensitive-example-id",
                "status": "completed",
                "label": "entailed",
                "evidence_ids": [0, 3],
                "explanation": "Sensitive answer text.",
            }
        ],
    )
    write_jsonl(
        run / "traces" / "trace.jsonl",
        [
            {"event": "model_request", "payload": {"phase": "exploration", "messages": ["private"]}},
            {"event": "model_response", "payload": {"input_tokens": 10, "output_tokens": 2, "latency_ms": 3}},
            {"event": "model_request", "payload": {"phase": "finalization"}},
            {"event": "model_request", "payload": {"phase": "review"}},
            {"event": "model_response", "payload": {"input_tokens": 12, "output_tokens": 4, "latency_ms": 5}},
            {"event": "recoverable_error", "payload": {"phase": "exploration", "error_type": "parse", "error": "private parse"}},
            {"event": "recoverable_error", "payload": {"phase": "finalization", "error_type": "model", "error": "private model"}},
            {"event": "recoverable_error", "payload": {"phase": "review", "error_type": "skill", "error": "private skill"}},
            {"event": "review_triggered", "payload": {"reasons": ["private reason"]}},
            {"event": "input_context", "payload": {"report_paragraph_count": 9, "report_character_count": 900, "assembled_paragraph_count": 9, "full_report_assembled": True, "local_truncation": False, "model_context_limit": 8192}},
            {"event": "baseline_error", "payload": {"error": "private context", "provider_context_error": True}},
            {"event": "question_closed", "payload": {"status": "completed", "reason": "review_fallback"}},
        ],
    )
    (run / "state" / "state.json").write_text(
        json.dumps(
            {
                "tool_counts": {"search_report": 2, "read_paragraphs": 1, "calculator": 1},
                "initial_retrieval_state": {"paragraph_ids": [0, 1, 2]},
                "evidence_ledger": [
                    {"source": "fixed_rag:bm25:top3"},
                    {"source": "fixed_rag:bm25:top3"},
                    {"source": "fixed_rag:bm25:top3"},
                    {"source": "report", "exact_text": "private evidence"},
                    {"source": "report", "exact_text": "private evidence"},
                ],
                "review_triggered": True,
                "review_completed": False,
                "review_fallback_used": True,
                "review_changed_label": True,
            }
        ),
        encoding="utf-8",
    )

    summary = MODULE.summarize(run)
    rendered = json.dumps(summary)

    assert summary["rates"] == {
        "prediction_coverage": 1.0,
        "invalid": 0.0,
        "strict_valid": 1.0,
        "review_trigger": 1.0,
    }
    assert summary["totals"]["model_calls"] == 3
    assert summary["totals"]["model_responses"] == 2
    assert summary["totals"]["exploration_steps"] == 1
    assert summary["totals"]["finalization_attempts"] == 1
    assert summary["totals"]["review_attempts"] == 1
    assert summary["totals"]["search_calls"] == 2
    assert summary["totals"]["read_calls"] == 1
    assert summary["totals"]["calculator_calls"] == 1
    assert summary["totals"]["seed_paragraphs"] == 3
    assert summary["totals"]["dynamic_paragraphs"] == 2
    assert summary["totals"]["review_fallbacks"] == 1
    assert summary["totals"]["review_label_changes"] == 1
    assert summary["totals"]["termination_reasons"] == {"review_fallback": 1}
    assert summary["totals"]["phase_errors"]["exploration"]["parse"] == 1
    assert summary["totals"]["phase_errors"]["finalization"]["model"] == 1
    assert summary["totals"]["phase_errors"]["review"]["skill"] == 1
    assert summary["long_context"]["provider_context_error_count"] == 1
    assert summary["long_context"]["configured_context_limits"] == {"8192": 1}
    for secret in ("sensitive-example-id", "Sensitive answer", "private evidence", "private parse"):
        assert secret not in rendered
