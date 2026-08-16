"""Per-question durable state; no state is shared across examples."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from findver_agent.schemas import Prediction, PublicTask


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


class QuestionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str
    statement: str
    report: str
    step: int = 0
    remaining_steps: int
    search_queries: list[SearchRecord] = Field(default_factory=list)
    evidence_ledger: list[EvidenceRecord] = Field(default_factory=list)
    calculations: list[CalculationRecord] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tool_counts: ToolCounts = Field(default_factory=ToolCounts)
    usage: UsageTotals = Field(default_factory=UsageTotals)
    errors: list[str] = Field(default_factory=list)
    last_observation: dict[str, Any] | None = None
    prediction: Prediction | None = None
    review_requested: bool = False
    review_completed: bool = False
    draft_submission: dict[str, Any] | None = None
    closed: bool = False

    @classmethod
    def create(cls, task: PublicTask, max_steps: int) -> "QuestionState":
        return cls(
            example_id=task.example_id,
            statement=task.statement,
            report=task.report,
            remaining_steps=max_steps,
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

    def load_or_create(self, task: PublicTask, max_steps: int) -> QuestionState:
        path = self.path_for(task.example_id)
        if not path.exists():
            return QuestionState.create(task, max_steps)
        state = QuestionState.model_validate_json(path.read_text(encoding="utf-8"))
        if (state.example_id, state.statement, state.report) != (
            task.example_id,
            task.statement,
            task.report,
        ):
            raise ValueError("saved question state does not match the public task")
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

