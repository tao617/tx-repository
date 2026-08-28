"""Strict data models for the bounded FinDSL language and its certificates."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
ReferenceId = Annotated[str, Field(pattern=REFERENCE_PATTERN)]
DecimalString = Annotated[str, Field(pattern=DECIMAL_PATTERN, max_length=128)]
ShortText = Annotated[str, Field(min_length=1, max_length=160)]
Diagnostic = Annotated[str, Field(min_length=1, max_length=500)]


class FinancialOperator(str, Enum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    SUM = "sum"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    ABSOLUTE_DIFFERENCE = "absolute_difference"
    PCT_CHANGE = "pct_change"
    RATIO = "ratio"
    MARGIN = "margin"
    BASIS_POINT_CHANGE = "basis_point_change"
    CAGR = "cagr"
    PER_SHARE = "per_share"
    SHARE_OF_TOTAL = "share_of_total"
    EQUALS = "equals"
    APPROXIMATELY_EQUALS = "approximately_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    WITHIN_RANGE = "within_range"


class RoundingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    digits: int = Field(ge=0, le=12)
    mode: Literal["half_even", "half_up", "half_down", "down", "up"] = (
        "half_even"
    )


class ToleranceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["absolute", "relative", "percentage_points", "basis_points"]
    value: DecimalString

    @field_validator("value")
    @classmethod
    def tolerance_is_finite_nonnegative(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:  # pragma: no cover - regex is primary guard
            raise ValueError("tolerance must be a Decimal string") from error
        if not parsed.is_finite() or parsed < 0:
            raise ValueError("tolerance must be finite and non-negative")
        return value


class ValueOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["value_ref"] = "value_ref"
    ref: ReferenceId


class ClaimValueOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["claim_value_ref"] = "claim_value_ref"
    ref: ReferenceId


class ConstantOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["constant_ref"] = "constant_ref"
    ref: Literal["constant:zero", "constant:one", "constant:hundred"]


class FinancialProgram(BaseModel):
    """One bounded AST node; nested nodes are checked again by the executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["program"] = "program"
    op: FinancialOperator
    args: list[
        Union[
            ValueOperand,
            ClaimValueOperand,
            ConstantOperand,
            "FinancialProgram",
        ]
    ] = Field(min_length=1, max_length=32)
    rounding: RoundingSpec | None = None
    tolerance: ToleranceSpec | None = None


class ClaimRelation(BaseModel):
    """Compare the root program result with one parsed claim value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    op: Literal[
        "equals",
        "approximately_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    ]
    claim_ref: ReferenceId
    tolerance: ToleranceSpec | None = None

    @model_validator(mode="after")
    def tolerance_matches_relation(self) -> "ClaimRelation":
        if self.op == "approximately_equals" and self.tolerance is None:
            raise ValueError("approximately_equals requires an explicit tolerance")
        if self.op != "approximately_equals" and self.tolerance is not None:
            raise ValueError("tolerance is allowed only for approximately_equals")
        return self


class ClaimValueRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_value_id: ReferenceId
    raw_value: str = Field(min_length=1, max_length=128)
    normalized_value: str = Field(min_length=1, max_length=128)
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
    currency: ShortText
    unit: ShortText
    scale: ShortText
    relation: ShortText
    tolerance: ToleranceSpec | None = None
    source_span_start: int = Field(ge=0)
    source_span_end: int = Field(gt=0)
    ambiguity_flags: list[ShortText] = Field(default_factory=list, max_length=8)

    @field_validator("ambiguity_flags")
    @classmethod
    def ambiguity_flags_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("claim ambiguity flags must be unique")
        return value

    @model_validator(mode="after")
    def span_matches_raw_value(self) -> "ClaimValueRef":
        if self.source_span_end - self.source_span_start != len(self.raw_value):
            raise ValueError("claim source span must cover raw_value exactly")
        if self.numeric_type == "date":
            try:
                date.fromisoformat(self.normalized_value)
            except ValueError as error:
                raise ValueError("date claim values must use ISO YYYY-MM-DD") from error
        elif self.numeric_type == "boolean":
            if self.normalized_value not in {"true", "false"}:
                raise ValueError("boolean claim values must be true or false")
        elif not re.fullmatch(DECIMAL_PATTERN, self.normalized_value):
            raise ValueError("numeric claim values require canonical Decimal strings")
        return self


class OperandSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: ReferenceId
    kind: Literal["value_ref", "claim_value_ref", "constant_ref", "program_result"]
    normalized_value: str = Field(min_length=1, max_length=128)
    numeric_type: ShortText
    currency: ShortText
    unit: ShortText
    scale: ShortText
    period: ShortText


class NumericCertificate(BaseModel):
    """Full deterministic proof payload persisted beside its envelope hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: ReferenceId
    program_id: ReferenceId
    program_sha256: str = Field(pattern=SHA256_PATTERN)
    operator: FinancialOperator
    operand_refs: list[ReferenceId] = Field(min_length=1, max_length=32)
    source_evidence_refs: list[ReferenceId] = Field(default_factory=list, max_length=32)
    type_checks_passed: Literal[True]
    unit_checks_passed: Literal[True]
    period_checks_passed: Literal[True]
    normalized_operands: list[OperandSnapshot] = Field(min_length=1, max_length=32)
    result: str = Field(min_length=1, max_length=128)
    result_type: ShortText
    result_currency: ShortText
    result_unit: ShortText
    result_scale: ShortText
    result_period: ShortText
    claim_relation: ShortText
    relation_satisfied: bool
    rounding: RoundingSpec | None = None
    tolerance: ToleranceSpec | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)

    @field_validator(
        "operand_refs", "source_evidence_refs", "diagnostics"
    )
    @classmethod
    def certificate_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("certificate collections must be unique")
        return value


FinancialProgram.model_rebuild()


__all__ = [
    "ClaimRelation",
    "ClaimValueOperand",
    "ClaimValueRef",
    "ConstantOperand",
    "FinancialOperator",
    "FinancialProgram",
    "NumericCertificate",
    "OperandSnapshot",
    "RoundingSpec",
    "ToleranceSpec",
    "ValueOperand",
]
