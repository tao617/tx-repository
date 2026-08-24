"""Strict public contracts for the generic evaluation agent."""

from __future__ import annotations

import json
import math
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class ContextUnit(BaseModel):
    """One addressable piece of public task context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=512)


class GenericTask(BaseModel):
    """Dataset-independent public task consumed by the generic runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=256)
    instruction: str = Field(min_length=1, max_length=20_000)
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    context: list[ContextUnit] = Field(default_factory=list, max_length=10_000)
    data: JsonValue | None = None

    @field_validator("context")
    @classmethod
    def context_ids_are_unique(cls, value: list[ContextUnit]) -> list[ContextUnit]:
        ids = [unit.unit_id for unit in value]
        if len(ids) != len(set(ids)):
            raise ValueError("context unit_id values must be unique")
        return value


class GenericEvidenceStatus(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    SUFFICIENT = "sufficient"
    CONFLICTING = "conflicting"


class GenericConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GenericRiskFlag(str, Enum):
    CALCULATION = "calculation"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    WEAK_SUPPORT = "weak_support"
    RETRIEVAL_GAP = "retrieval_gap"
    FORMAT_UNCERTAINTY = "format_uncertainty"
    EXTERNAL_KNOWLEDGE = "external_knowledge"
    TASK_AMBIGUITY = "task_ambiguity"


class AnswerContract(BaseModel):
    """Small deterministic answer validator selected by a task profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["enum", "text", "number", "boolean", "json"] = "text"
    choices: list[str] = Field(default_factory=list, max_length=256)
    max_length: int = Field(default=4_000, ge=1, le=100_000)
    minimum: float | None = None
    maximum: float | None = None
    required_keys: list[str] = Field(default_factory=list, max_length=128)
    explanation_required: bool = False

    @field_validator("choices", "required_keys")
    @classmethod
    def strings_are_clean_and_unique(cls, value: list[str]) -> list[str]:
        if any(not item or item != item.strip() for item in value):
            raise ValueError("configured strings must be non-empty without outer whitespace")
        if len(value) != len(set(value)):
            raise ValueError("configured strings must be unique")
        return value

    @model_validator(mode="after")
    def fields_match_kind(self) -> "AnswerContract":
        if self.kind == "enum" and not self.choices:
            raise ValueError("enum answers require at least one choice")
        if self.kind != "enum" and self.choices:
            raise ValueError("choices are valid only for enum answers")
        if self.kind != "json" and self.required_keys:
            raise ValueError("required_keys are valid only for json answers")
        if self.kind != "number" and (self.minimum is not None or self.maximum is not None):
            raise ValueError("minimum and maximum are valid only for number answers")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum cannot exceed maximum")
        return self

    def validate_answer(self, value: JsonValue) -> JsonValue:
        """Validate and return one JSON-safe answer without coercing its type."""

        if self.kind == "enum":
            if not isinstance(value, str) or value not in self.choices:
                raise ValueError(f"answer must be one of {self.choices}")
            return value
        if self.kind == "text":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("answer must be a non-empty string")
            if len(value) > self.max_length:
                raise ValueError("answer exceeds max_length")
            return value
        if self.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("answer must be a number")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("answer must be finite")
            if self.minimum is not None and value < self.minimum:
                raise ValueError("answer is smaller than minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("answer is larger than maximum")
            return value
        if self.kind == "boolean":
            if not isinstance(value, bool):
                raise ValueError("answer must be a boolean")
            return value

        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > self.max_length:
            raise ValueError("JSON answer exceeds max_length")
        if self.required_keys:
            if not isinstance(value, dict):
                raise ValueError("JSON answer must be an object")
            missing = [key for key in self.required_keys if key not in value]
            if missing:
                raise ValueError(f"JSON answer is missing required keys: {missing}")
        return value


EvidencePolicy = Literal["none", "optional", "read_only", "required_read"]


class GenericTaskProfile(BaseModel):
    """Builder-selected task semantics and Runtime skill allowlist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    profile_id: str = Field(
        pattern=r"^[A-Za-z0-9._-]+$", min_length=1, max_length=256
    )
    description: str = Field(default="", max_length=4_000)
    system_prompt: str = Field(default="", max_length=20_000)
    allowed_skills: list[str] = Field(default_factory=list, max_length=64)
    answer: AnswerContract = Field(default_factory=AnswerContract)
    evidence_policy: EvidencePolicy = "optional"

    @field_validator("allowed_skills")
    @classmethod
    def skill_names_are_clean_and_unique(cls, value: list[str]) -> list[str]:
        if "submit_answer" in value:
            raise ValueError("submit_answer is implicit and cannot be listed as a skill")
        if any(
            not name
            or name != name.strip()
            or not all(character.isalnum() or character in "._-" for character in name)
            for name in value
        ):
            raise ValueError("skill names must use only letters, numbers, dot, dash, or underscore")
        if len(value) != len(set(value)):
            raise ValueError("allowed_skills must be unique")
        return value


class GenericPredictionStatus(str, Enum):
    COMPLETED = "completed"
    INVALID = "invalid"
    ERROR = "error"


class GenericPrediction(BaseModel):
    """Dataset-independent Runtime result."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=256)
    status: GenericPredictionStatus
    answer: JsonValue | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    explanation: str = Field(default="", max_length=100_000)

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("evidence_ids must be non-empty strings")
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value

    @model_validator(mode="after")
    def status_matches_answer(self) -> "GenericPrediction":
        if self.status == GenericPredictionStatus.COMPLETED and self.answer is None:
            raise ValueError("completed prediction must contain an answer")
        if self.status != GenericPredictionStatus.COMPLETED and self.answer is not None:
            raise ValueError("non-completed prediction cannot contain an answer")
        return self


class GenericActionControl(BaseModel):
    """Bounded control metadata matching the existing protocol-v2 shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_status: GenericEvidenceStatus
    missing_information: list[str] = Field(default_factory=list, max_length=5)
    confidence: GenericConfidence
    risk_flags: list[GenericRiskFlag] = Field(default_factory=list, max_length=8)

    @field_validator("missing_information")
    @classmethod
    def missing_information_is_bounded_and_unique(cls, value: list[str]) -> list[str]:
        if any(not item or item != item.strip() or len(item) > 300 for item in value):
            raise ValueError("missing_information items must contain 1 to 300 clean characters")
        if len(value) != len(set(value)):
            raise ValueError("missing_information items must be unique")
        return value

    @field_validator("risk_flags")
    @classmethod
    def risk_flags_are_unique(
        cls, value: list[GenericRiskFlag]
    ) -> list[GenericRiskFlag]:
        if len(value) != len(set(value)):
            raise ValueError("risk_flags must be unique")
        return value


class GenericActionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str = Field(min_length=1, max_length=128)
    arguments: dict[str, JsonValue]
    control: GenericActionControl


class GenericSubmitArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: JsonValue
    evidence_ids: list[str] = Field(default_factory=list, max_length=256)
    explanation: str = Field(default="", max_length=100_000)

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("evidence_ids must be non-empty strings")
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value
