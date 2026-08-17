import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "preflight_lc_agent.py"
CONFIG = ROOT / "configs" / "bclass" / "ablations" / "LC_AGENT_FIRSTPASS.yaml"
SPEC = importlib.util.spec_from_file_location("preflight_lc_agent", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(tmp_path, paragraph):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps({"context": [{"context": paragraph}]}),
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        json.dumps(
            {
                "example_id": "preflight",
                "statement": "The report contains a fact.",
                "report": "report.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return tasks, reports


def test_preflight_builds_exact_prompts_without_model_requests(tmp_path):
    tasks, reports = fixture(tmp_path, "A short financial fact.")

    result = MODULE.preflight(
        config_path=CONFIG,
        tasks_path=tasks,
        reports_path=reports,
        expected_examples=1,
    )

    assert result["condition_id"] == "LC_AGENT_FIRSTPASS"
    assert result["model_requests_made"] == 0
    assert result["examples"] == 1
    assert result["full_report_injection_requests"] == 1
    assert result["estimated_overflow_count"] == 0
    assert result["maximum_estimated_input_tokens"] > 0
    assert result["model_context_window_tokens"] == 100_000
    assert result["unique_reports"] == 1
    assert len(result["report_corpus_sha256"]) == 64


def test_preflight_reports_estimated_overflow(tmp_path):
    tasks, reports = fixture(tmp_path, "x" * 40_000)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["backend"]["model_context_window_tokens"] = 8192
    config_path = tmp_path / "overflow.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    result = MODULE.preflight(
        config_path=config_path,
        tasks_path=tasks,
        reports_path=reports,
        expected_examples=1,
    )

    assert result["estimated_overflow_count"] == 1
    assert result["maximum_estimated_total_tokens"] > 8192
