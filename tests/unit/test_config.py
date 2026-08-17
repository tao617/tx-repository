import pytest
from pydantic import ValidationError

from findver_agent.config import AppConfig


def agent_config(base_url="http://model-gateway:8080/v1"):
    return {
        "run": {"mode": "agent", "backend_kind": "api"},
        "backend": {
            "type": "openai_compatible",
            "base_url": base_url,
            "model": "model",
            "timeout_seconds": 30,
            "max_retries": 1,
        },
        "generation": {"temperature": 0, "top_p": 1, "max_output_tokens": 64, "max_context_tokens": 4096},
        "agent": {"cross_question_memory": False, "scorer_feedback": False},
    }


def test_runtime_config_accepts_fixed_gateway():
    config = AppConfig.model_validate(agent_config())
    assert config.backend.base_url == "http://model-gateway:8080/v1"
    assert config.backend.model_context_window_tokens == 32768
    assert config.generation.prompt_budget_tokens == 4096
    assert config.generation.max_context_tokens == 4096
    assert config.generation.model_dump()["prompt_budget_tokens"] == 4096
    assert "max_context_tokens" not in config.generation.model_dump()


def test_runtime_config_separates_prompt_budget_from_model_capacity():
    raw = agent_config()
    raw["backend"]["model_context_window_tokens"] = 100_000
    raw["generation"] = {"prompt_budget_tokens": 32_768}
    config = AppConfig.model_validate(raw)
    assert (config.generation.prompt_budget_tokens, config.backend.model_context_window_tokens) == (32_768, 100_000)


@pytest.mark.parametrize(
    "url",
    ["https://api.example.com/v1", "http://127.0.0.1:8080/v1", "http://user:secret@model-gateway/v1"],
)
def test_runtime_config_rejects_non_gateway_or_embedded_credentials(url):
    with pytest.raises(ValidationError, match="model-gateway|credentials"):
        AppConfig.model_validate(agent_config(url))


def test_runtime_config_cannot_enable_memory_or_scorer_feedback():
    raw = agent_config()
    raw["agent"]["cross_question_memory"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_deepseek_profile_requires_explicit_disabled_thinking():
    raw = agent_config()
    raw["backend"]["request_profile"] = "deepseek_v4_openai"
    with pytest.raises(ValidationError, match="thinking.type=disabled"):
        AppConfig.model_validate(raw)

    raw["backend"]["thinking"] = {"type": "disabled"}
    config = AppConfig.model_validate(raw)
    assert config.backend.thinking is not None
    assert config.backend.thinking.type == "disabled"


@pytest.mark.parametrize(
    "thinking",
    [
        {"type": "enabled"},
        {"type": "disabled", "effort": "high"},
        {"mode": "disabled"},
    ],
)
def test_deepseek_profile_rejects_enabled_unknown_or_extended_thinking(thinking):
    raw = agent_config()
    raw["backend"].update(
        {"request_profile": "deepseek_v4_openai", "thinking": thinking}
    )
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_generic_profile_rejects_deepseek_fields_and_arbitrary_extensions():
    raw = agent_config()
    raw["backend"]["thinking"] = {"type": "disabled"}
    with pytest.raises(ValidationError, match="generic_openai"):
        AppConfig.model_validate(raw)

    raw = agent_config()
    raw["backend"]["extra_body"] = {"thinking": {"type": "disabled"}}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)
