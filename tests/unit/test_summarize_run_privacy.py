import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "summarize_run.py"
SPEC = importlib.util.spec_from_file_location("summarize_run_privacy", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_summary_buckets_arbitrary_failure_text_without_leaking_it(tmp_path):
    run = tmp_path / "run"
    (run / "traces").mkdir(parents=True)
    (run / "run_metadata.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "baseline",
                "expected_examples": 1,
                "completed_examples": 1,
            }
        ),
        encoding="utf-8",
    )
    (run / "predictions.jsonl").write_text(
        json.dumps(
            {
                "example_id": "secret-id",
                "status": "invalid",
                "label": None,
                "evidence_ids": [],
                "explanation": "secret explanation",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    secret = "provider context failure containing secret task material"
    events = [
        {"event": "model_request", "payload": {"messages": [secret]}},
        {
            "event": "input_context",
            "payload": {
                "report_paragraph_count": 10,
                "report_character_count": 1000,
                "assembled_paragraph_count": 3,
                "full_report_assembled": False,
                "local_truncation": False,
                "model_context_limit": 4096,
            },
        },
        {
            "event": "baseline_error",
            "payload": {"error": secret, "provider_context_error": True},
        },
        {"event": "question_closed", "payload": {"status": "invalid", "reason": secret}},
    ]
    (run / "traces" / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    summary = MODULE.summarize(run)
    rendered = json.dumps(summary)

    assert summary["totals"]["termination_reasons"] == {"invalid_other": 1}
    assert summary["totals"]["phase_errors"]["baseline"]["model"] == 1
    assert summary["totals"]["seed_paragraphs"] == 3
    assert summary["long_context"]["provider_context_error_count"] == 1
    assert secret not in rendered
    assert "secret-id" not in rendered
