"""Validated runtime configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from findver_agent.model_backends.base import GenerationConfig
from findver_agent.model_backends.transport_adapters import (
    ResponseFormat,
    TransportProfile,
    canonical_transport_profile,
    validate_transport_thinking,
)


RetrieverName = Literal[
    "bm25",
    "text-embedding-3-large",
    "contriever-msmarco",
    "hybrid-rrf",
]
RetrievalTopK = Literal[3, 5, 10]
ProtocolVersion = Literal["v1", "v2", "v3"]
ReviewPolicy = Literal["none", "mandatory", "selective"]
FinOasisSkillName = Literal[
    "search_report",
    "read_paragraphs",
    "read_table_region",
    "bind_financial_value",
    "execute_financial_program",
    "search_financial_rules",
    "read_financial_rules",
    "check_rule_applicability",
    "submit_answer",
]


class ThinkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["disabled"]


class RateLimitConfig(BaseModel):
    """Plan-bound provider admission limits applied before transport."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requests_per_minute: int = Field(ge=1, le=1_000_000)
    tokens_per_minute: int = Field(ge=1, le=100_000_000)


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["agent", "baseline", "iterative_rag"]
    backend_kind: Literal["api", "local", "mock"]


class BackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    type: Literal["openai_compatible"]
    base_url: str
    model: str = Field(min_length=1)
    timeout_seconds: float = Field(default=120, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    model_context_window_tokens: int = Field(default=32768, ge=8192, le=1_000_000)
    transport_profile: TransportProfile = Field(
        default="openai_standard",
        validation_alias=AliasChoices("transport_profile", "request_profile"),
    )
    thinking: ThinkingConfig | None = None
    response_format: ResponseFormat = "text"
    rate_limit: RateLimitConfig | None = None

    @model_validator(mode="after")
    def fixed_gateway_only(self) -> "BackendConfig":
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname != "model-gateway":
            raise ValueError("runtime backend base_url must target http://model-gateway")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("runtime backend base_url cannot contain credentials or query data")
        thinking_mode = self.thinking.type if self.thinking is not None else "unsupported"
        validate_transport_thinking(self.transport_profile, thinking_mode)
        if (
            self.response_format == "json_object"
            and canonical_transport_profile(self.transport_profile)
            != "dashscope_openai_chat"
        ):
            raise ValueError(
                "response_format=json_object is supported only by dashscope_openai_chat"
            )
        return self

    @property
    def request_profile(self) -> TransportProfile:
        """Compatibility accessor for historical runtime and trace schemas."""

        return self.transport_profile


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


class LongContextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    source: Literal["full_report"] = "full_report"
    scope: Literal["first_exploration_attempt"] = "first_exploration_attempt"
    preload_as_evidence: Literal[False] = False


class FinOasisSkillBudgetsConfig(BaseModel):
    """Per-Skill limits for the reviewed protocol-v3 registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    search_report: int = Field(ge=0, le=32)
    read_paragraphs: int = Field(ge=0, le=32)
    read_table_region: int = Field(ge=0, le=32)
    bind_financial_value: int = Field(ge=0, le=32)
    execute_financial_program: int = Field(ge=0, le=32)
    search_financial_rules: int = Field(ge=0, le=32)
    read_financial_rules: int = Field(ge=0, le=32)
    check_rule_applicability: int = Field(ge=0, le=32)
    submit_answer: int = Field(ge=0, le=8)


class FinOasisObligationPolicyConfig(BaseModel):
    """Closed policy choices; none of these are model-controlled switches."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seeding: Literal["conservative"]
    skill_exposure: Literal["dynamic", "always_exposed_ablation"]
    model_may_open_obligations: Literal[True]
    model_may_satisfy_obligations: Literal[False]
    model_may_waive_mandatory: Literal[False]
    normal_submit_requires_all_mandatory: Literal[True]
    budget_exhausted_submit: Literal["low_confidence_best_effort"]


class FinOasisRuleCorpusConfig(BaseModel):
    """Configuration identity for a local, frozen rule corpus.

    Runtime containment and hash verification are deliberately implemented by the
    corpus loader.  This schema nevertheless rules out URLs and ambiguous absolute
    corpus-member paths before execution is possible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    rule_root: Path | None = None
    manifest_path: Path | None = None
    records_path: Path | None = None
    corpus_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )
    manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    records_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    read_only: Literal[True]
    network_fallback: Literal[False]

    @model_validator(mode="after")
    def corpus_identity_is_complete_or_absent(self) -> "FinOasisRuleCorpusConfig":
        identity = (
            self.rule_root,
            self.manifest_path,
            self.records_path,
            self.corpus_id,
            self.manifest_sha256,
            self.records_sha256,
        )
        if self.enabled and any(value is None for value in identity):
            raise ValueError("enabled rule_corpus requires complete path, ID, and hashes")
        if not self.enabled and any(value is not None for value in identity):
            raise ValueError("disabled rule_corpus cannot configure path, ID, or hashes")
        if not self.enabled:
            return self

        assert self.rule_root is not None
        assert self.manifest_path is not None
        assert self.records_path is not None
        if not self.rule_root.is_absolute() or self.rule_root == Path("/"):
            raise ValueError("rule_root must be a confined absolute directory")
        if ".." in self.rule_root.parts:
            raise ValueError("rule_root cannot contain parent traversal")
        for name, path in (
            ("manifest_path", self.manifest_path),
            ("records_path", self.records_path),
        ):
            if path == Path(".") or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"{name} must be a traversal-free path relative to rule_root")
            if urlparse(str(path)).scheme:
                raise ValueError(f"{name} must be a local path")
        if self.manifest_path == self.records_path:
            raise ValueError("manifest_path and records_path must be distinct")
        return self


class FinOasisConfig(BaseModel):
    """Explicit opt-in boundary for experimental protocol v3."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experimental: Literal[True]
    official_test_authorized: Literal[False]
    real_model_execution_authorized: Literal[False]
    scorer_handoff_authorized: Literal[False]
    enabled_skills: tuple[FinOasisSkillName, ...] = Field(min_length=1, max_length=9)
    skill_budgets: FinOasisSkillBudgetsConfig
    obligation_policy: FinOasisObligationPolicyConfig
    rule_corpus: FinOasisRuleCorpusConfig

    @model_validator(mode="after")
    def allowlist_budgets_and_dependencies_are_consistent(self) -> "FinOasisConfig":
        enabled = set(self.enabled_skills)
        if len(enabled) != len(self.enabled_skills):
            raise ValueError("enabled_skills cannot contain duplicates")
        if "submit_answer" not in enabled:
            raise ValueError("enabled_skills must include submit_answer")

        for skill_name, budget in self.skill_budgets.model_dump().items():
            if skill_name in enabled and budget < 1:
                raise ValueError(f"enabled Skill {skill_name} requires a positive budget")
            if skill_name not in enabled and budget != 0:
                raise ValueError(f"disabled Skill {skill_name} must have a zero budget")

        prerequisites = {
            "read_financial_rules": {"search_financial_rules"},
            "check_rule_applicability": {"read_financial_rules"},
            "execute_financial_program": {"bind_financial_value"},
        }
        for skill_name, required in prerequisites.items():
            missing = required - enabled if skill_name in enabled else set()
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(f"enabled Skill {skill_name} requires {names}")
        if "bind_financial_value" in enabled and not enabled.intersection(
            {"read_paragraphs", "read_table_region"}
        ):
            raise ValueError(
                "enabled Skill bind_financial_value requires a report-reading Skill"
            )

        rule_skills = {
            "search_financial_rules",
            "read_financial_rules",
            "check_rule_applicability",
        }
        if bool(enabled.intersection(rule_skills)) != self.rule_corpus.enabled:
            raise ValueError(
                "rule_corpus must be enabled exactly when rule Skills are enabled"
            )
        return self


# Compatibility spelling for callers that mirror the lowercase ``findoasis`` package.
FindOasisConfig = FinOasisConfig


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
    long_context: LongContextConfig = Field(default_factory=LongContextConfig)
    findoasis: FinOasisConfig | None = None
    cross_question_memory: Literal[False] = False
    scorer_feedback: Literal[False] = False
    concurrency: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def protocol_settings_are_compatible(self) -> "AgentConfig":
        if self.protocol_version in {"v1", "v2"} and self.findoasis is not None:
            raise ValueError("findoasis configuration is valid only for protocol v3")
        if self.protocol_version == "v3":
            if self.findoasis is None:
                raise ValueError("protocol v3 requires explicit findoasis configuration")
            if self.calculator_enabled:
                raise ValueError("protocol v3 disables the legacy calculator")
            if self.initial_retrieval.enabled:
                raise ValueError("protocol v3 disables legacy initial_retrieval")
            if self.long_context.enabled:
                raise ValueError("protocol v3 disables legacy long_context")
            if self.pre_submit_review:
                raise ValueError("protocol v3 does not use legacy pre_submit_review")
            if self.review_policy == "mandatory":
                raise ValueError("protocol v3 does not support mandatory legacy review")
            if self.review_policy == "none" and self.review_steps != 0:
                raise ValueError("protocol v3 without review requires review_steps=0")
        if self.protocol_version == "v1" and self.review_policy != "none":
            raise ValueError("protocol v1 uses pre_submit_review, not review_policy")
        if self.protocol_version == "v2" and self.pre_submit_review:
            raise ValueError("protocol v2 uses review_policy, not pre_submit_review")
        if self.review_policy != "none" and self.review_steps < 1:
            raise ValueError("enabled review_policy requires at least one review step")
        if self.long_context.enabled:
            if self.protocol_version != "v2":
                raise ValueError("long_context requires protocol v2")
            if self.exploration_steps < 1:
                raise ValueError(
                    "long_context requires at least one Exploration attempt"
                )
            if self.initial_retrieval.enabled:
                raise ValueError(
                    "long_context cannot be combined with initial_retrieval"
                )
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
        if (
            self.run.backend_kind in {"local", "mock"}
            and canonical_transport_profile(self.backend.transport_profile)
            != "openai_standard"
        ):
            raise ValueError(
                "local and mock backends must use the openai_standard transport profile"
            )
        return self


def load_config(path: Path) -> AppConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration must be a YAML object")
    return AppConfig.model_validate(data)
