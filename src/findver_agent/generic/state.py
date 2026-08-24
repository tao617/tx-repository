"""Durable per-task state for the generic evaluation agent."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from findver_agent.generic.config import GenericAgentConfig
from findver_agent.generic.models import (
    GenericConfidence,
    GenericEvidenceStatus,
    GenericPrediction,
    GenericRiskFlag,
    GenericTask,
    GenericTaskProfile,
)
from findver_agent.state import safe_example_filename


GenericPhase = Literal["initialization", "exploration", "finalization", "review", "closed"]


def canonical_sha256(value: BaseModel) -> str:
    data = (
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class GenericPhaseBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    exploration: int = Field(ge=0)
    finalization: int = Field(ge=1)
    review: int = Field(ge=0)


class GenericUsageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0


class GenericEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    exact_text: str
    read_order: int = Field(ge=0)
    source_skill: str = "read_context"


class GenericSkillRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    arguments: dict[str, JsonValue]
    observation: dict[str, JsonValue]
    phase: Literal["exploration", "finalization", "review"]
    step: int = Field(ge=1)


class GenericQuestionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    profile_id: str
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    task_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase: GenericPhase = "initialization"
    phase_budgets: GenericPhaseBudgets
    step: int = 0
    remaining_steps: int = Field(ge=0)
    exploration_step: int = 0
    finalization_step: int = 0
    review_step: int = 0
    evidence_status: GenericEvidenceStatus = GenericEvidenceStatus.NONE
    confidence: GenericConfidence = GenericConfidence.LOW
    risk_flags: list[GenericRiskFlag] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    skill_counts: dict[str, int] = Field(default_factory=dict)
    skill_history: list[GenericSkillRecord] = Field(default_factory=list)
    evidence_ledger: list[GenericEvidenceRecord] = Field(default_factory=list)
    last_observation: dict[str, JsonValue] | None = None
    usage: GenericUsageTotals = Field(default_factory=GenericUsageTotals)
    errors: list[str] = Field(default_factory=list)
    forced_finalization: bool = False
    draft_prediction: GenericPrediction | None = None
    prediction: GenericPrediction | None = None
    review_triggered: bool = False
    review_trigger_reasons: list[str] = Field(default_factory=list)
    review_completed: bool = False
    review_fallback_used: bool = False
    review_failure_reason: str | None = None
    review_changed_answer: bool = False
    review_changed_evidence: bool = False
    review_changed_explanation: bool = False
    termination_reason: str | None = None
    closed: bool = False

    @field_validator("risk_flags")
    @classmethod
    def risk_flags_are_unique(
        cls, value: list[GenericRiskFlag]
    ) -> list[GenericRiskFlag]:
        if len(value) != len(set(value)):
            raise ValueError("risk_flags must be unique")
        return value

    @classmethod
    def create(
        cls,
        task: GenericTask,
        profile: GenericTaskProfile,
        config: GenericAgentConfig,
    ) -> "GenericQuestionState":
        budgets = GenericPhaseBudgets(
            exploration=config.exploration_steps,
            finalization=config.finalization_steps,
            review=config.review_steps,
        )
        total = budgets.exploration + budgets.finalization + budgets.review
        return cls(
            profile_id=profile.profile_id,
            profile_sha256=canonical_sha256(profile),
            config_sha256=canonical_sha256(config),
            task_id=task.task_id,
            task_sha256=canonical_sha256(task),
            phase_budgets=budgets,
            remaining_steps=total,
            skill_counts={name: 0 for name in profile.allowed_skills},
        )


class GenericStateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, task_id: str) -> Path:
        return self.root / safe_example_filename(task_id, ".json")

    def load_or_create(
        self,
        task: GenericTask,
        profile: GenericTaskProfile,
        config: GenericAgentConfig,
    ) -> GenericQuestionState:
        path = self.path_for(task.task_id)
        expected_budgets = GenericPhaseBudgets(
            exploration=config.exploration_steps,
            finalization=config.finalization_steps,
            review=config.review_steps,
        )
        if not path.exists():
            return GenericQuestionState.create(task, profile, config)
        state = GenericQuestionState.model_validate_json(path.read_text(encoding="utf-8"))
        if state.task_id != task.task_id or state.task_sha256 != canonical_sha256(task):
            raise ValueError("saved generic state does not match the public task")
        if (
            state.profile_id != profile.profile_id
            or state.profile_sha256 != canonical_sha256(profile)
        ):
            raise ValueError("saved generic state does not match the task profile")
        if state.config_sha256 != canonical_sha256(config):
            raise ValueError("saved generic state does not match the Agent config")
        if state.phase_budgets != expected_budgets:
            raise ValueError("saved generic state phase budgets do not match config")
        if set(state.skill_counts) != set(profile.allowed_skills):
            raise ValueError("saved generic state skill allowlist does not match profile")
        return state

    def save(self, state: GenericQuestionState) -> None:
        path = self.path_for(state.task_id)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
