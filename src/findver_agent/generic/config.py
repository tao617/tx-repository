"""Configuration for the additive generic evaluation-agent runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from findver_agent.config import BackendConfig
from findver_agent.model_backends.base import GenerationConfig
from findver_agent.model_backends.transport_adapters import canonical_transport_profile


GenericReviewPolicy = Literal["none", "mandatory", "selective"]


class GenericAgentConfig(BaseModel):
    """Bounded phase and skill budgets for one generic Agent condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exploration_steps: int = Field(default=6, ge=0, le=32)
    finalization_steps: int = Field(default=2, ge=1, le=8)
    review_steps: int = Field(default=1, ge=0, le=8)
    review_policy: GenericReviewPolicy = "selective"
    default_skill_call_limit: int = Field(default=4, ge=0, le=32)
    skill_call_limits: dict[str, int] = Field(default_factory=dict)
    max_total_evidence_units: int = Field(default=30, ge=0, le=1_000)
    max_history_records: int = Field(default=12, ge=1, le=64)
    max_observation_characters: int = Field(default=4_000, ge=256, le=100_000)
    concurrency: int = Field(default=1, ge=1, le=32)

    @field_validator("skill_call_limits")
    @classmethod
    def skill_call_limits_are_safe(cls, value: dict[str, int]) -> dict[str, int]:
        for name, limit in value.items():
            if name == "submit_answer":
                raise ValueError("submit_answer does not use a skill call limit")
            if (
                not name
                or not all(character.isalnum() or character in "._-" for character in name)
            ):
                raise ValueError("skill_call_limits contains an invalid skill name")
            if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 32:
                raise ValueError("skill call limits must be integers between 0 and 32")
        return value

    @model_validator(mode="after")
    def review_budget_matches_policy(self) -> "GenericAgentConfig":
        if self.review_policy != "none" and self.review_steps < 1:
            raise ValueError("enabled review_policy requires at least one review step")
        return self

    def skill_limit(self, name: str) -> int:
        return self.skill_call_limits.get(name, self.default_skill_call_limit)


class GenericAppConfig(BaseModel):
    """Credential-free effective configuration for the generic Runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend_kind: Literal["api", "local", "mock"]
    backend: BackendConfig
    generation: GenerationConfig
    agent: GenericAgentConfig = Field(default_factory=GenericAgentConfig)

    @model_validator(mode="after")
    def backend_kind_matches_transport(self) -> "GenericAppConfig":
        if (
            self.backend_kind in {"local", "mock"}
            and canonical_transport_profile(self.backend.transport_profile)
            != "openai_standard"
        ):
            raise ValueError("local and mock generic backends require openai_standard")
        return self


def _load_yaml_object(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return value


def load_generic_config(path: Path) -> GenericAppConfig:
    return GenericAppConfig.model_validate(_load_yaml_object(path))
