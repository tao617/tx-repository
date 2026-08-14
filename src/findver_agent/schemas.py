"""Shared runtime data models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Label(str, Enum):
    ENTAILED = "entailed"
    REFUTED = "refuted"


class PublicTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    example_id: str = Field(min_length=1, max_length=256)
    statement: str = Field(min_length=1)
    report: str = Field(min_length=1, max_length=512)

    @field_validator("report")
    @classmethod
    def report_is_bare_json_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("report must be a bare filename")
        if not value.lower().endswith(".json"):
            raise ValueError("report must use the .json extension")
        return value


class PredictionStatus(str, Enum):
    COMPLETED = "completed"
    INVALID = "invalid"
    ERROR = "error"


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str = Field(min_length=1, max_length=256)
    label: Label | None
    status: PredictionStatus
    evidence_ids: list[int] = Field(default_factory=list)
    explanation: str = ""

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique_nonnegative(cls, value: list[int]) -> list[int]:
        if any(item < 0 for item in value):
            raise ValueError("evidence_ids must be non-negative")
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value

