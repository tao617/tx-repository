"""Composable experiment-condition and model-deployment configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from findver_agent.config import (
    AgentConfig,
    AppConfig,
    BackendConfig,
    BaselineConfig,
    IterativeRAGConfig,
    RateLimitConfig,
    RunConfig,
    ThinkingConfig,
)
from findver_agent.model_backends.base import GenerationConfig
from findver_agent.model_backends.transport_adapters import (
    CanonicalTransportProfile,
    ThinkingMode,
    validate_transport_thinking,
)


PLAIN_NAME_PATTERN = r"^[A-Za-z0-9._-]+$"


class ExperimentCondition(BaseModel):
    """Model-independent method settings for one experiment condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    condition_id: str = Field(pattern=PLAIN_NAME_PATTERN, min_length=1, max_length=256)
    family: Literal["main", "extension"]
    prompt_profile: str = Field(min_length=1, max_length=256)
    run_mode: Literal["agent", "baseline", "iterative_rag"]
    generation: GenerationConfig
    agent: AgentConfig | None = None
    baseline: BaselineConfig | None = None
    iterative_rag: IterativeRAGConfig | None = None

    @model_validator(mode="after")
    def mode_section_matches(self) -> "ExperimentCondition":
        sections = {
            "agent": self.agent,
            "baseline": self.baseline,
            "iterative_rag": self.iterative_rag,
        }
        if sections[self.run_mode] is None:
            raise ValueError(f"{self.run_mode} method section is required")
        if any(
            section is not None
            for name, section in sections.items()
            if name != self.run_mode
        ):
            raise ValueError("condition contains a method section for another run mode")
        return self

    @property
    def configured_concurrency(self) -> int:
        section = self.agent or self.baseline or self.iterative_rag
        if section is None:  # pragma: no cover - validator closes this
            raise ValueError("condition method section is missing")
        return section.concurrency

    @property
    def maximum_model_calls(self) -> int:
        if self.baseline is not None:
            return 1
        if self.iterative_rag is not None:
            return (
                self.iterative_rag.retrieval_rounds
                + self.iterative_rag.finalization_steps
            )
        if self.agent is None:  # pragma: no cover - validator closes this
            raise ValueError("condition method section is missing")
        if self.agent.protocol_version == "v1":
            return self.agent.max_steps
        return (
            self.agent.exploration_steps
            + self.agent.finalization_steps
            + self.agent.review_steps
        )


class ModelDeployment(BaseModel):
    """Model and provider admission settings independent of experiment methods."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    deployment_id: str = Field(pattern=PLAIN_NAME_PATTERN, min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)
    backend_kind: Literal["api", "local"]
    model_alias: str = Field(min_length=1, max_length=256)
    base_url: str = "http://model-gateway:8080/v1"
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    model_context_window_tokens: int = Field(ge=8192, le=1_000_000)
    transport_profile: CanonicalTransportProfile
    thinking_mode: ThinkingMode
    rate_limit: RateLimitConfig | None = None

    @model_validator(mode="after")
    def deployment_is_supported(self) -> "ModelDeployment":
        validate_transport_thinking(self.transport_profile, self.thinking_mode)
        if self.backend_kind == "local" and self.transport_profile != "openai_standard":
            raise ValueError("local deployments require openai_standard")
        # Reuse the runtime gateway boundary validation here.
        BackendConfig(
            type="openai_compatible",
            base_url=self.base_url,
            model=self.model_alias,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            model_context_window_tokens=self.model_context_window_tokens,
            transport_profile=self.transport_profile,
            thinking=(
                ThinkingConfig(type="disabled")
                if self.thinking_mode == "disabled"
                else None
            ),
            rate_limit=self.rate_limit,
        )
        return self


def _load_yaml_object(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return value


def load_experiment_condition(path: Path) -> ExperimentCondition:
    return ExperimentCondition.model_validate(_load_yaml_object(path))


def load_model_deployment(path: Path) -> ModelDeployment:
    return ModelDeployment.model_validate(_load_yaml_object(path))


def compose_effective_config(
    condition: ExperimentCondition,
    deployment: ModelDeployment,
) -> AppConfig:
    """Compose and fully validate the exact Runtime configuration."""

    backend = BackendConfig(
        type="openai_compatible",
        base_url=deployment.base_url,
        model=deployment.model_alias,
        timeout_seconds=deployment.timeout_seconds,
        max_retries=deployment.max_retries,
        model_context_window_tokens=deployment.model_context_window_tokens,
        transport_profile=deployment.transport_profile,
        thinking=(
            ThinkingConfig(type="disabled")
            if deployment.thinking_mode == "disabled"
            else None
        ),
        rate_limit=deployment.rate_limit,
    )
    return AppConfig(
        run=RunConfig(mode=condition.run_mode, backend_kind=deployment.backend_kind),
        backend=backend,
        generation=condition.generation,
        agent=condition.agent,
        baseline=condition.baseline,
        iterative_rag=condition.iterative_rag,
    )


def effective_config_value(config: AppConfig) -> dict[str, object]:
    return config.model_dump(mode="json", exclude_none=True)


def effective_config_bytes(config: AppConfig) -> bytes:
    return (
        json.dumps(
            effective_config_value(config),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def effective_config_sha256(config: AppConfig) -> str:
    return hashlib.sha256(effective_config_bytes(config)).hexdigest()
