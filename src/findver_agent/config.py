"""Validated runtime configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from findver_agent.model_backends.base import GenerationConfig


RetrieverName = Literal["bm25", "text-embedding-3-large", "contriever-msmarco"]
RetrievalTopK = Literal[3, 5, 10]
ProtocolVersion = Literal["v1", "v2"]
ReviewPolicy = Literal["none", "mandatory", "selective"]


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["agent", "baseline", "iterative_rag"]
    backend_kind: Literal["api", "local", "mock"]


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["openai_compatible"]
    base_url: str
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    model_context_window_tokens: int = Field(default=32768, ge=8192, le=1_000_000)

    @model_validator(mode="after")
    def fixed_gateway_only(self) -> "BackendConfig":
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname != "model-gateway":
            raise ValueError("runtime backend base_url must target http://model-gateway")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("runtime backend base_url cannot contain credentials or query data")
        return self


class InitialRetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    retrieval_file: Path | None = None
    retriever: RetrieverName | None = None
    top_k: RetrievalTopK = 10
    preload_as_evidence: bool = True

    @model_validator(mode="after")
    def enabled_retrieval_is_complete(self) -> "InitialRetrievalConfig":
        if self.enabled and (self.retrieval_file is None or self.retriever is None):
            raise ValueError(
                "enabled initial_retrieval requires retrieval_file and retriever"
            )
        if not self.enabled and (
            self.retrieval_file is not None or self.retriever is not None
        ):
            raise ValueError(
                "disabled initial_retrieval cannot configure a file or retriever"
            )
        return self


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(default=8, ge=1, le=32)
    protocol_version: ProtocolVersion = "v1"
    exploration_steps: int = Field(default=6, ge=0, le=32)
    finalization_steps: int = Field(default=2, ge=1, le=8)
    review_steps: int = Field(default=1, ge=0, le=8)
    review_policy: ReviewPolicy = "none"
    max_search_calls: int = Field(default=4, ge=0, le=16)
    max_read_calls: int = Field(default=4, ge=0, le=16)
    max_calculator_calls: int = Field(default=4, ge=0, le=16)
    max_paragraphs_per_read: int = Field(default=12, ge=1, le=12)
    max_total_unique_paragraphs: int = Field(default=30, ge=1, le=100)
    calculator_enabled: bool = True
    pre_submit_review: bool = False
    initial_retrieval: InitialRetrievalConfig = Field(
        default_factory=InitialRetrievalConfig
    )
    cross_question_memory: Literal[False] = False
    scorer_feedback: Literal[False] = False
    concurrency: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def protocol_settings_are_compatible(self) -> "AgentConfig":
        if self.protocol_version == "v1" and self.review_policy != "none":
            raise ValueError("protocol v1 uses pre_submit_review, not review_policy")
        if self.protocol_version == "v2" and self.pre_submit_review:
            raise ValueError("protocol v2 uses review_policy, not pre_submit_review")
        if self.review_policy != "none" and self.review_steps < 1:
            raise ValueError("enabled review_policy requires at least one review step")
        return self


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_type: Literal["direct", "cot", "findver_direct_json", "findver_cot_json"] = "direct"
    retrieval: Literal[
        "none", "fixed_bm25", "fixed_embedding", "fixed_retrieval"
    ] = "none"
    retrieval_file: Path | None = None
    retriever: RetrieverName | None = None
    top_k: RetrievalTopK = 10
    concurrency: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def fixed_retrieval_configuration(self) -> "BaselineConfig":
        file_mode = self.retrieval in {"fixed_embedding", "fixed_retrieval"}
        if file_mode and self.retrieval_file is None:
            raise ValueError("retrieval_file is required for file-based retrieval")
        if not file_mode and self.retrieval_file is not None:
            raise ValueError(
                "retrieval_file is only valid for file-based retrieval"
            )
        if self.retrieval == "fixed_retrieval" and self.retriever is None:
            raise ValueError("retriever is required for fixed_retrieval")
        if self.retrieval != "fixed_retrieval" and self.retriever is not None:
            raise ValueError("retriever is only valid for fixed_retrieval")
        return self


class IterativeRAGConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retrieval_file: Path
    retriever: RetrieverName
    top_k: RetrievalTopK = 10
    retrieval_rounds: int = Field(default=3, ge=1, le=8)
    results_per_round: int = Field(default=5, ge=1, le=10)
    auto_read_per_round: int = Field(default=5, ge=1, le=10)
    max_total_unique_paragraphs: int = Field(default=40, ge=1, le=100)
    finalization_steps: int = Field(default=2, ge=1, le=8)
    prompt_type: Literal["findver_direct_json", "findver_cot_json"] = "findver_cot_json"
    concurrency: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def fixed_loop_limits_are_consistent(self) -> "IterativeRAGConfig":
        if self.auto_read_per_round > self.results_per_round:
            raise ValueError("auto_read_per_round cannot exceed results_per_round")
        if self.max_total_unique_paragraphs < self.top_k:
            raise ValueError("max_total_unique_paragraphs cannot be smaller than top_k")
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run: RunConfig
    backend: BackendConfig
    generation: GenerationConfig
    agent: AgentConfig | None = None
    baseline: BaselineConfig | None = None
    iterative_rag: IterativeRAGConfig | None = None

    @model_validator(mode="after")
    def mode_section_matches(self) -> "AppConfig":
        required = {
            "agent": self.agent,
            "baseline": self.baseline,
            "iterative_rag": self.iterative_rag,
        }
        if required[self.run.mode] is None:
            raise ValueError(f"{self.run.mode} configuration is required in {self.run.mode} mode")
        for name, section in required.items():
            if name != self.run.mode and section is not None:
                raise ValueError(f"{name} configuration is not valid in {self.run.mode} mode")
        return self


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML object")
    return AppConfig.model_validate(data)
