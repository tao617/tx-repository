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


def test_long_context_requires_v2_exploration_without_initial_retrieval():
    raw = agent_config()
    raw["agent"].update(
        {
            "protocol_version": "v2",
            "long_context": {"enabled": True},
        }
    )
    config = AppConfig.model_validate(raw)
    assert config.agent is not None
    assert config.agent.long_context.enabled is True
    assert config.agent.long_context.scope == "first_exploration_attempt"
    assert config.agent.long_context.preload_as_evidence is False

    raw["agent"]["protocol_version"] = "v1"
    with pytest.raises(ValidationError, match="protocol v2"):
        AppConfig.model_validate(raw)

    raw["agent"]["protocol_version"] = "v2"
    raw["agent"]["exploration_steps"] = 0
    with pytest.raises(ValidationError, match="Exploration"):
        AppConfig.model_validate(raw)

    raw["agent"]["exploration_steps"] = 1
    raw["agent"]["initial_retrieval"] = {
        "enabled": True,
        "retrieval_file": "/retrieval/top10.json",
        "retriever": "text-embedding-3-large",
    }
    with pytest.raises(ValidationError, match="initial_retrieval"):
        AppConfig.model_validate(raw)


def test_long_context_rejects_preloading_or_unknown_scope():
    raw = agent_config()
    raw["agent"].update(
        {
            "protocol_version": "v2",
            "long_context": {
                "enabled": True,
                "preload_as_evidence": True,
            },
        }
    )
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)

    raw["agent"]["long_context"] = {
        "enabled": True,
        "scope": "until_first_valid_action",
    }
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)


def test_deepseek_profile_requires_explicit_disabled_thinking():
    raw = agent_config()
    raw["backend"]["transport_profile"] = "deepseek_openai_chat"
    with pytest.raises(ValidationError, match="thinking_mode=disabled"):
        AppConfig.model_validate(raw)

    raw["backend"]["thinking"] = {"type": "disabled"}
    config = AppConfig.model_validate(raw)
    assert config.backend.thinking is not None
    assert config.backend.thinking.type == "disabled"


def test_dashscope_profile_requires_disabled_thinking_and_accepts_deployment_rate_limit():
    raw = agent_config()
    raw["backend"]["transport_profile"] = "dashscope_openai_chat"
    with pytest.raises(ValidationError, match="thinking_mode=disabled"):
        AppConfig.model_validate(raw)

    raw["backend"]["thinking"] = {"type": "disabled"}
    raw["backend"]["rate_limit"] = {
        "requests_per_minute": 540,
        "tokens_per_minute": 850_000,
    }
    config = AppConfig.model_validate(raw)
    assert config.backend.transport_profile == "dashscope_openai_chat"
    assert config.backend.thinking is not None
    assert config.backend.rate_limit is not None
    assert config.backend.rate_limit.tokens_per_minute == 850_000


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
    with pytest.raises(ValidationError, match="openai_standard"):
        AppConfig.model_validate(raw)

    raw = agent_config()
    raw["backend"]["extra_body"] = {"thinking": {"type": "disabled"}}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw)

    raw = agent_config()
    raw["backend"]["rate_limit"] = {
        "requests_per_minute": 1,
        "tokens_per_minute": 1,
    }
    config = AppConfig.model_validate(raw)
    assert config.backend.rate_limit is not None
    assert config.backend.rate_limit.requests_per_minute == 1
