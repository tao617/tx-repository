"""Per-question durable state; no state is shared across examples."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from findver_agent.schemas import (
    Confidence,
    EvidenceStatus,
    Prediction,
    PublicTask,
    RiskFlag,
)


ProtocolVersion = Literal["v1", "v2"]
QuestionPhase = Literal["initialization", "exploration", "finalization", "review", "closed"]


class SearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    result_ids: list[int]


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paragraph_id: int
    exact_text: str
    source: str = "report"
    reason_selected: str
    read_order: int
    pinned: bool = False


class CalculationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str
    result: int | float


class ToolCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_report: int = 0
    read_paragraphs: int = 0
    calculator: int = 0


class UsageTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0


class InitialRetrievalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retriever: Literal["bm25", "text-embedding-3-large", "contriever-msmarco"]
    top_k: Literal[3, 5, 10]
    report: str
    paragraph_ids: list[int]
    preload_as_evidence: bool

    @field_validator("paragraph_ids")
    @classmethod
    def paragraph_ids_are_unique_nonnegative(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("initial retrieval paragraph ids must be non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("initial retrieval paragraph ids must be unique")
        return value


class PhaseBudgets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exploration: int = Field(ge=0)
    finalization: int = Field(ge=1)
    review: int = Field(ge=0)


class ErrorCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parse: int = 0
    model: int = 0
    skill: int = 0
    protocol: int = 0
    protocol_drift: int = 0


class PhaseErrors(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exploration: ErrorCounts = Field(default_factory=ErrorCounts)
    finalization: ErrorCounts = Field(default_factory=ErrorCounts)
    review: ErrorCounts = Field(default_factory=ErrorCounts)


class QuestionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    protocol_version: ProtocolVersion = "v1"
    phase: QuestionPhase = "exploration"
    phase_budgets: PhaseBudgets | None = None
    example_id: str
    statement: str
    report: str
    step: int = 0
    remaining_steps: int
    exploration_step: int = 0
    finalization_step: int = 0
    review_step: int = 0
    initial_retrieval_state: InitialRetrievalState | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.NONE
    evidence_confidence: Confidence = Confidence.LOW
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    search_queries: list[SearchRecord] = Field(default_factory=list)
    evidence_ledger: list[EvidenceRecord] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tool_counts: ToolCounts = Field(default_factory=ToolCounts)
    usage: UsageTotals = Field(default_factory=UsageTotals)
    errors: list[str] = Field(default_factory=list)
    phase_errors: PhaseErrors = Field(default_factory=PhaseErrors)
    last_observation: dict[str, Any] | None = None
    prediction: Prediction | None = None
    draft_prediction: Prediction | None = None
    draft_confidence: Confidence | None = None
    draft_evidence_status: EvidenceStatus | None = None
    draft_risk_flags: list[RiskFlag] = Field(default_factory=list)
    review_requested: bool = False
    review_completed: bool = False
    draft_submission: dict[str, Any] | None = None
    review_triggered: bool = False
    review_trigger_reasons: list[str] = Field(default_factory=list)
    review_fallback_used: bool = False
    review_failure_reason: str | None = None
    review_changed_label: bool = False
    review_changed_evidence: bool = False
    review_changed_explanation: bool = False
    forced_finalization: bool = False
    forced_finalization_evidence_status: EvidenceStatus | None = None
    termination_reason: str | None = None
    closed: bool = False

    @field_validator("risk_flags", "draft_risk_flags")
    @classmethod
    def risk_flags_are_unique(cls, value: list[RiskFlag]) -> list[RiskFlag]:
        if len(value) != len(set(value)):
            raise ValueError("state risk flags must be unique")
        return value

    @classmethod
    def create(
        cls,
        task: PublicTask,
        max_steps: int,
        *,
        protocol_version: ProtocolVersion = "v1",
        exploration_steps: int = 6,
        finalization_steps: int = 2,
        review_steps: int = 1,
    ) -> "QuestionState":
        phase_budgets = None
        phase: QuestionPhase = "exploration"
        remaining_steps = max_steps
        if protocol_version == "v2":
            phase_budgets = PhaseBudgets(
                exploration=exploration_steps,
                finalization=finalization_steps,
                review=review_steps,
            )
            phase = "initialization"
            remaining_steps = exploration_steps + finalization_steps + review_steps
        return cls(
            schema_version=2,
            protocol_version=protocol_version,
            phase=phase,
            phase_budgets=phase_budgets,
            example_id=task.example_id,
            statement=task.statement,
            report=task.report,
            remaining_steps=remaining_steps,
        )


def safe_example_filename(example_id: str, suffix: str) -> str:
    digest = hashlib.sha256(example_id.encode("utf-8")).hexdigest()
    return f"{digest}{suffix}"


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, example_id: str) -> Path:
        return self.root / safe_example_filename(example_id, ".json")

    def load_or_create(
        self,
        task: PublicTask,
        max_steps: int,
        *,
        protocol_version: ProtocolVersion = "v1",
        exploration_steps: int = 6,
        finalization_steps: int = 2,
        review_steps: int = 1,
    ) -> QuestionState:
        path = self.path_for(task.example_id)
        expected_budgets = None
        if protocol_version == "v2":
            expected_budgets = PhaseBudgets(
                exploration=exploration_steps,
                finalization=finalization_steps,
                review=review_steps,
            )
        if not path.exists():
            return QuestionState.create(
                task,
                max_steps,
                protocol_version=protocol_version,
                exploration_steps=exploration_steps,
                finalization_steps=finalization_steps,
                review_steps=review_steps,
            )
        state = QuestionState.model_validate_json(path.read_text(encoding="utf-8"))
        if (state.example_id, state.statement, state.report) != (
            task.example_id,
            task.statement,
            task.report,
        ):
            raise ValueError("saved question state does not match the public task")
        if state.protocol_version != protocol_version:
            raise ValueError("saved question state protocol_version does not match config")
        if protocol_version == "v2" and state.phase_budgets != expected_budgets:
            raise ValueError("saved question state phase budgets do not match config")
        return state

    def save(self, state: QuestionState) -> None:
        path = self.path_for(state.example_id)
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
