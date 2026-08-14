from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_credentials_and_proxies_are_gateway_only() -> None:
    compose = yaml.safe_load(
        (ROOT / "deploy/wsl/docker-compose.agent.yaml").read_text(encoding="utf-8")
    )
    agent_env = compose["services"]["agent-runtime"].get("environment", {})
    gateway_env = compose["services"]["model-gateway"]["environment"]
    assert all("KEY" not in name and "PROXY" not in name for name in agent_env)
    assert "FINDVER_GATEWAY_UPSTREAM_API_KEY" in gateway_env
    assert {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}.issubset(gateway_env)


def test_runtime_env_loader_does_not_copy_or_print_secrets() -> None:
    text = (ROOT / "scripts/run_agent_with_env.sh").read_text(encoding="utf-8")
    assert "source \"$env_file\"" in text
    assert "cp " not in text
    assert "MODEL_API_KEY" in text
    assert "echo \"$MODEL_API_KEY\"" not in text
    assert "agent_api.yaml" not in text
    assert "flock -n 9" in text
    assert "--project-name findver-agent" in text
    assert "COMPOSE_PROJECT_NAME" in text
    assert "FINDVER_RUN_OUTPUT_DIR" in text
