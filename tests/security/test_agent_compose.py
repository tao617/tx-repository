from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "wsl" / "docker-compose.agent.yaml"


def load_compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_has_explicit_isolated_project_name():
    compose = load_compose()
    assert compose["name"] == "findver-agent"


def test_agent_runtime_has_only_internal_network_and_allowed_mounts():
    compose = load_compose()
    agent = compose["services"]["agent-runtime"]
    assert agent["networks"] == ["agent-internal"]
    assert compose["networks"]["agent-internal"]["internal"] is True
    assert agent["read_only"] is True
    assert agent["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in agent["security_opt"]
    targets = {volume["target"] for volume in agent["volumes"]}
    assert targets == {"/public", "/reports", "/output/${FINDVER_RUN_NAME:-run}"}
    assert all("docker.sock" not in str(volume) for volume in agent["volumes"])
    assert all("scorer" not in str(volume).lower() for volume in agent["volumes"])
    output = next(volume for volume in agent["volumes"] if volume["target"].startswith("/output/"))
    assert output["source"] == "${FINDVER_RUN_OUTPUT_DIR:-../../runs/run}"
    assert output.get("read_only") is not True
    assert all(volume.get("read_only") is True for volume in agent["volumes"] if volume is not output)


def test_gateway_is_only_dual_network_service_and_no_ports_exist():
    compose = load_compose()
    agent = compose["services"]["agent-runtime"]
    gateway = compose["services"]["model-gateway"]
    assert set(gateway["networks"]) == {"agent-internal", "gateway-egress"}
    assert "ports" not in agent
    assert "ports" not in gateway
    assert gateway["read_only"] is True
    assert gateway["cap_drop"] == ["ALL"]
    assert "FINDVER_GATEWAY_UPSTREAM_API_KEY" in gateway["environment"]
    assert all("KEY" not in name for name in agent.get("environment", {}))


def test_runtime_dockerfile_uses_whitelisted_copy_sources():
    dockerfile = (ROOT / "deploy" / "wsl" / "Dockerfile.agent").read_text(encoding="utf-8")
    assert "COPY ." not in dockerfile
    assert "data/" not in dockerfile
    assert "financial_reports" not in dockerfile
    assert "scorer" not in dockerfile.lower()

