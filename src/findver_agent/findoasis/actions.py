"""Strict JSON action protocol for FinOASIS protocol v3.

The legacy parser intentionally remains in :mod:`findver_agent.actions`.  This
module recognizes only the reviewed v3 Skill names and bounded argument models.
Runtime availability is a separate check performed after parsing.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from findver_agent.financial_dsl.models import (
    ClaimRelation,
    FinancialOperator,
    FinancialProgram,
)
from findver_agent.schemas import Confidence, Label

from .contracts import (
    AddDependencyDelta,
    AttachEvidenceDelta,
    MarkConflictingDelta,
    MarkPartialDelta,
    ObligationDelta,
    ObligationId,
    ObligationProposal,
    OpenObligationDelta,
    ReferenceId,
    ShortText,
)


class ActionParseError(ValueError):
    """The model response is not exactly one valid protocol-v3 action."""


class V3RiskFlag(str, Enum):
    CALCULATION = "calculation"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    WEAK_SUPPORT = "weak_support"
    RETRIEVAL_GAP = "retrieval_gap"
    TABLE_ALIGNMENT = "table_alignment"
    UNIT_PERIOD_AMBIGUITY = "unit_period_ambiguity"
    RULE_APPLICABILITY = "rule_applicability"
    UNRESOLVED_OBLIGATION = "unresolved_obligation"
    CERTIFICATE_FAILURE = "certificate_failure"


class V3ActionControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_obligation_id: ObligationId
    open_obligations: list[ObligationProposal] = Field(
        default_factory=list, max_length=5
    )
    obligation_deltas: list[ObligationDelta] = Field(default_factory=list, max_length=8)
    confidence: Confidence
    risk_flags: list[V3RiskFlag] = Field(default_factory=list, max_length=8)
    expected_skill_effect: ShortText

    @field_validator("risk_flags")
    @classmethod
    def risk_flags_are_unique(cls, value: list[V3RiskFlag]) -> list[V3RiskFlag]:
        if len(value) != len(set(value)):
            raise ValueError("risk_flags must be unique")
        return value


# Public alias follows the naming used by the v1/v2 module while remaining isolated.
ActionControl = V3ActionControl


class SearchReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class ReadParagraphsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paragraph_ids: list[int] = Field(min_length=1, max_length=12)

    @field_validator("paragraph_ids")
    @classmethod
    def paragraph_ids_are_unique_nonnegative(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("paragraph_ids must be non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("paragraph_ids must be unique")
        return value


class ReadTableRegionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    table_id: ReferenceId
    row_indices: list[int] = Field(min_length=1, max_length=20)
    column_indices: list[int] = Field(min_length=1, max_length=12)

    @field_validator("row_indices", "column_indices")
    @classmethod
    def indices_are_unique_nonnegative(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("table indices must be non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("table indices must be unique")
        return value


class BindFinancialValueArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_ref: ReferenceId
    raw_value: str = Field(min_length=1, max_length=128)
    metric: ShortText
    entity: ShortText
    period: ShortText
    numeric_type: Literal[
        "money",
        "percentage",
        "basis_points",
        "count",
        "ratio",
        "scalar",
        "duration",
        "date",
        "boolean",
    ]
    currency: ShortText = "unknown"
    unit: ShortText = "unknown"
    scale: ShortText = "unknown"


class ExecuteFinancialProgramArguments(BaseModel):
    """A bounded reference-only AST and optional root-to-claim relation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    program: FinancialProgram
    claim_relation: ClaimRelation | None = None


class SearchFinancialRulesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=500)
    jurisdiction: ShortText
    as_of_date: str = Field(min_length=4, max_length=32)
    top_k: int = Field(default=5, ge=1, le=10)


class ReadFinancialRulesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_ids: list[ReferenceId] = Field(min_length=1, max_length=10)

    @field_validator("rule_ids")
    @classmethod
    def rule_ids_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("rule_ids must be unique")
        return value


class CheckRuleApplicabilityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_evidence_refs: list[ReferenceId] = Field(min_length=1, max_length=10)
    document_evidence_refs: list[ReferenceId] = Field(min_length=1, max_length=20)
    jurisdiction: ShortText
    effective_date: str = Field(min_length=4, max_length=32)
    entity_scope: ShortText

    @field_validator("rule_evidence_refs", "document_evidence_refs")
    @classmethod
    def applicability_refs_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("applicability references must be unique")
        return value


class SubmitAnswerArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: Label
    evidence_ids: list[int] = Field(default_factory=list, max_length=30)
    explanation: str = Field(min_length=1, max_length=4000)

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique_nonnegative(cls, value: list[int]) -> list[int]:
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("evidence_ids must be non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value


class SearchReportAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["search_report"]
    arguments: SearchReportArguments
    control: V3ActionControl


class ReadParagraphsAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["read_paragraphs"]
    arguments: ReadParagraphsArguments
    control: V3ActionControl


class ReadTableRegionAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["read_table_region"]
    arguments: ReadTableRegionArguments
    control: V3ActionControl


class BindFinancialValueAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["bind_financial_value"]
    arguments: BindFinancialValueArguments
    control: V3ActionControl


class ExecuteFinancialProgramAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["execute_financial_program"]
    arguments: ExecuteFinancialProgramArguments
    control: V3ActionControl


class SearchFinancialRulesAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["search_financial_rules"]
    arguments: SearchFinancialRulesArguments
    control: V3ActionControl


class ReadFinancialRulesAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["read_financial_rules"]
    arguments: ReadFinancialRulesArguments
    control: V3ActionControl


class CheckRuleApplicabilityAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["check_rule_applicability"]
    arguments: CheckRuleApplicabilityArguments
    control: V3ActionControl


class SubmitAnswerAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["submit_answer"]
    arguments: SubmitAnswerArguments
    control: V3ActionControl


Action = Annotated[
    Union[
        SearchReportAction,
        ReadParagraphsAction,
        ReadTableRegionAction,
        BindFinancialValueAction,
        ExecuteFinancialProgramAction,
        SearchFinancialRulesAction,
        ReadFinancialRulesAction,
        CheckRuleApplicabilityAction,
        SubmitAnswerAction,
    ],
    Field(discriminator="action"),
]
ACTION_ADAPTER = TypeAdapter(Action)


def parse_action(content: str) -> Action:
    """Parse exactly one strict protocol-v3 JSON action."""

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
        return ACTION_ADAPTER.validate_python(value)
    except ValueError as error:
        raise ActionParseError(f"invalid protocol-v3 action: {error}") from error


parse_action_v3 = parse_action


__all__ = [
    "ACTION_ADAPTER",
    "Action",
    "ActionControl",
    "ActionParseError",
    "AddDependencyDelta",
    "AttachEvidenceDelta",
    "BindFinancialValueAction",
    "CheckRuleApplicabilityAction",
    "ExecuteFinancialProgramAction",
    "MarkConflictingDelta",
    "MarkPartialDelta",
    "OpenObligationDelta",
    "ReadFinancialRulesAction",
    "ReadParagraphsAction",
    "ReadTableRegionAction",
    "SearchFinancialRulesAction",
    "SearchReportAction",
    "SubmitAnswerAction",
    "V3ActionControl",
    "parse_action",
    "parse_action_v3",
]
