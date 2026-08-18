"""Immutable identity bound to one planned experiment run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from findver_agent.model_backends.transport_adapters import (
    TransportProfile,
    validate_transport_thinking,
)


SHA256_PATTERN = r"^[a-f0-9]{64}$"
COMMIT_PATTERN = r"^[a-f0-9]{40,64}$"
PLAIN_NAME_PATTERN = r"^[A-Za-z0-9._-]+$"


class RunIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    matrix_id: str = Field(pattern=PLAIN_NAME_PATTERN, min_length=1, max_length=256)
    condition_id: str = Field(pattern=PLAIN_NAME_PATTERN, min_length=1, max_length=256)
    plan_run_id: str = Field(pattern=PLAIN_NAME_PATTERN, min_length=1, max_length=256)
    effective_model_id: str = Field(min_length=1, max_length=256)
    model_alias: str = Field(min_length=1, max_length=256)
    backend_kind: Literal["api", "local"]
    git_commit_at_start: str = Field(pattern=COMMIT_PATTERN)
    git_worktree_clean: Literal[True] = True
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    public_tasks_sha256: str = Field(pattern=SHA256_PATTERN)
    planned_retrieval_sha256: str = Field(pattern=SHA256_PATTERN)
    effective_retrieval_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    model_context_window_tokens: int = Field(ge=8192, le=1_000_000)
    request_profile: TransportProfile = "openai_standard"
    thinking_mode: Literal["disabled", "unsupported"] = "unsupported"
    rate_limit_requests_per_minute: int | None = Field(
        default=None, ge=1, le=1_000_000
    )
    rate_limit_tokens_per_minute: int | None = Field(
        default=None, ge=1, le=100_000_000
    )
    configured_concurrency: int = Field(default=1, ge=1, le=32)

    @model_validator(mode="after")
    def run_name_is_matrix_scoped(self) -> "RunIdentity":
        if not self.plan_run_id.startswith(f"{self.matrix_id}-"):
            raise ValueError("plan_run_id must be scoped by matrix_id")
        validate_transport_thinking(self.request_profile, self.thinking_mode)
        rate_limit_group = (
            self.rate_limit_requests_per_minute,
            self.rate_limit_tokens_per_minute,
        )
        if any(value is not None for value in rate_limit_group) and not all(
            value is not None for value in rate_limit_group
        ):
            raise ValueError("run identity RPM and TPM limits must be paired")
        return self
