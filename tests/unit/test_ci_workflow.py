from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_public_ci_covers_supported_python_and_stateful_docker_without_secrets():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    pytest_job = workflow["jobs"]["pytest"]
    assert pytest_job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    assert any("pytest -q" in step.get("run", "") for step in pytest_job["steps"])

    docker_job = workflow["jobs"]["stateful-docker-smoke"]
    assert docker_job["needs"] == "pytest"
    assert any(
        "scripts/run_stateful_mock_smoke.sh" in step.get("run", "")
        for step in docker_job["steps"]
    )
    assert "secrets." not in text
    assert "pull_request:" in text
    assert "push:" in text
