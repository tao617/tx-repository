"""Strict text-JSON action protocol shared by all model types."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from findver_agent.schemas import Confidence, EvidenceStatus, Label, RiskFlag


class ActionParseError(ValueError):
    """The model response is not one valid action."""


MissingInformation = Annotated[str, Field(min_length=1, max_length=300)]


class ActionControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_status: EvidenceStatus
    missing_information: list[MissingInformation] = Field(
        default_factory=list,
        max_length=5,
    )
    confidence: Confidence
    risk_flags: list[RiskFlag] = Field(default_factory=list, max_length=5)

    @field_validator("missing_information")
    @classmethod
    def missing_information_is_clean_and_unique(cls, value: list[str]) -> list[str]:
        if any(item != item.strip() for item in value):
            raise ValueError("missing_information items cannot have outer whitespace")
        if len(value) != len(set(value)):
            raise ValueError("missing_information items must be unique")
        return value

    @field_validator("risk_flags")
    @classmethod
    def risk_flags_are_unique(cls, value: list[RiskFlag]) -> list[RiskFlag]:
        if len(value) != len(set(value)):
            raise ValueError("risk_flags must be unique")
        return value


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class ReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    paragraph_ids: list[int] = Field(min_length=1, max_length=12)


class CalculatorArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expression: str = Field(min_length=1, max_length=256)


class SubmitArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: Label
    evidence_ids: list[int] = Field(default_factory=list, max_length=30)
    explanation: str = Field(default="", max_length=4000)


class SearchAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["search_report"]
    arguments: SearchArguments
    control: ActionControl | None = None


class ReadAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["read_paragraphs"]
    arguments: ReadArguments
    control: ActionControl | None = None


class CalculatorAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["calculator"]
    arguments: CalculatorArguments
    control: ActionControl | None = None


class SubmitAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["submit_answer"]
    arguments: SubmitArguments
    control: ActionControl | None = None


Action = Annotated[
    Union[SearchAction, ReadAction, CalculatorAction, SubmitAction],
    Field(discriminator="action"),
]
ACTION_ADAPTER = TypeAdapter(Action)


def parse_action(content: str, *, protocol_version: Literal["v1", "v2"] = "v1") -> Action:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
            text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ActionParseError(f"response must be one JSON object: {error.msg}") from error
    if not isinstance(value, dict):
        raise ActionParseError("response must be one JSON object")
    try:
        action = ACTION_ADAPTER.validate_python(value)
    except ValueError as error:
        raise ActionParseError(f"invalid action: {error}") from error
    if protocol_version == "v2" and action.control is None:
        raise ActionParseError("invalid action: protocol v2 requires control metadata")
    return action
