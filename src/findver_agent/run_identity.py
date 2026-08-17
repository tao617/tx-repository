"""Immutable identity bound to one planned experiment run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def run_name_is_matrix_scoped(self) -> "RunIdentity":
        if not self.plan_run_id.startswith(f"{self.matrix_id}-"):
            raise ValueError("plan_run_id must be scoped by matrix_id")
        return self
