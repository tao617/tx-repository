import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SMOKE_TASK = ROOT / "tests" / "fixtures" / "stateful_smoke_tasks.jsonl"
CONCURRENT_SMOKE_TASKS = ROOT / "tests" / "fixtures" / "concurrent_smoke_tasks.jsonl"
FINOASIS_SMOKE_TASKS = ROOT / "tests" / "fixtures" / "finoasis_smoke_tasks.jsonl"
FINOASIS_SMOKE_REPORTS = ROOT / "tests" / "fixtures" / "finoasis_smoke_reports"
RETRIEVAL = ROOT / "runtime_data" / "retrieval" / "findver_embedding3large_top10.json"


def test_stateful_ci_fixture_matches_public_release_artifacts():
    task = json.loads(SMOKE_TASK.read_text(encoding="utf-8"))
    assert set(task) == {"example_id", "statement", "report"}
    assert (ROOT / "financial_reports" / task["report"]).is_file()
    retrieval = json.loads(RETRIEVAL.read_text(encoding="utf-8"))
    assert retrieval["items"][task["example_id"]]["report"] == task["report"]


def test_concurrent_ci_fixture_contains_only_public_fields_and_reports():
    tasks = [
        json.loads(line)
        for line in CONCURRENT_SMOKE_TASKS.read_text(encoding="utf-8").splitlines()
    ]
    assert len(tasks) == 40
    assert len({task["example_id"] for task in tasks}) == 40
    assert all(set(task) == {"example_id", "statement", "report"} for task in tasks)
    assert all((ROOT / "financial_reports" / task["report"]).is_file() for task in tasks)


def test_finoasis_ci_fixture_is_synthetic_and_contains_only_public_fields():
    tasks = [
        json.loads(line)
        for line in FINOASIS_SMOKE_TASKS.read_text(encoding="utf-8").splitlines()
    ]
    assert len(tasks) == 4
    assert len({task["example_id"] for task in tasks}) == 4
    assert all(set(task) == {"example_id", "statement", "report"} for task in tasks)
    assert all((FINOASIS_SMOKE_REPORTS / task["report"]).is_file() for task in tasks)
    assert all(task["example_id"].startswith("finoasis-smoke-") for task in tasks)
    assert all(task["report"].startswith("finoasis-") for task in tasks)


def test_public_ci_covers_supported_python_and_stateful_docker_without_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    pytest_job = workflow["jobs"]["pytest"]
    assert pytest_job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    assert any("pytest -q" in step.get("run", "") for step in pytest_job["steps"])

    docker_job = workflow["jobs"]["stateful-docker-smoke"]
    assert docker_job["needs"] == "pytest"
    assert any(
        "tests/fixtures/stateful_smoke_tasks.jsonl" in step.get("run", "")
        and "runtime_data/public/smoke-tasks.jsonl" in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert any(
        "scripts/run_stateful_mock_smoke.sh" in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert any(
        "tests/fixtures/concurrent_smoke_tasks.jsonl" in step.get("run", "")
        and "runtime_data/public/concurrent-smoke-tasks.jsonl"
        in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert any(
        "scripts/run_concurrent_mock_smoke.sh" in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert any(
        "tests/fixtures/finoasis_smoke_tasks.jsonl" in step.get("run", "")
        and "runtime_data/public/finoasis-smoke-tasks.jsonl"
        in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert any(
        "scripts/run_finoasis_mock_smoke.sh" in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert "secrets." not in text
    assert "pull_request:" in text
    assert "push:" in text
