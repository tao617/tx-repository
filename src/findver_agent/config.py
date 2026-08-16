"""Validated runtime configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from findver_agent.model_backends.base import GenerationConfig


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["agent", "baseline"]
    backend_kind: Literal["api", "local", "mock"]


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["openai_compatible"]
    base_url: str
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)

    @model_validator(mode="after")
    def fixed_gateway_only(self) -> "BackendConfig":
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname != "model-gateway":
            raise ValueError("runtime backend base_url must target http://model-gateway")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("runtime backend base_url cannot contain credentials or query data")
        return self


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(default=8, ge=1, le=32)
    max_search_calls: int = Field(default=4, ge=0, le=16)
    max_read_calls: int = Field(default=4, ge=0, le=16)
    max_calculator_calls: int = Field(default=4, ge=0, le=16)
    max_paragraphs_per_read: int = Field(default=12, ge=1, le=12)
    max_total_unique_paragraphs: int = Field(default=30, ge=1, le=100)
    calculator_enabled: bool = True
    pre_submit_review: bool = False
    cross_question_memory: Literal[False] = False
    scorer_feedback: Literal[False] = False
    concurrency: int = Field(default=1, ge=1, le=32)


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_type: Literal["direct", "cot"] = "direct"
    retrieval: Literal["none", "fixed_bm25", "fixed_embedding"] = "none"
    retrieval_file: Path | None = None
    top_k: int = Field(default=10, ge=1, le=10)
    concurrency: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def fixed_embedding_requires_file(self) -> "BaselineConfig":
        if self.retrieval == "fixed_embedding" and self.retrieval_file is None:
            raise ValueError("retrieval_file is required for fixed_embedding")
        if self.retrieval != "fixed_embedding" and self.retrieval_file is not None:
            raise ValueError("retrieval_file is only valid for fixed_embedding")
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunConfig
    backend: BackendConfig
    generation: GenerationConfig
    agent: AgentConfig | None = None
    baseline: BaselineConfig | None = None

    @model_validator(mode="after")
    def mode_section_matches(self) -> "AppConfig":
        if self.run.mode == "agent" and self.agent is None:
            raise ValueError("agent configuration is required in agent mode")
        if self.run.mode == "baseline" and self.baseline is None:
            raise ValueError("baseline configuration is required in baseline mode")
        return self


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML object")
    return AppConfig.model_validate(data)

