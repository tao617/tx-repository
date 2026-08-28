"""Strict protocol-v3 proof-obligation and Skill contracts.

The models in this module are deliberately independent of the legacy v1/v2
protocol.  In particular, model-authored obligation proposals never contain an
obligation ID or a way to mark an obligation satisfied.  Those operations belong
to :mod:`findver_agent.findoasis.state` and are performed by the Runtime.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
OBLIGATION_ID_PATTERN = r"^obl-[0-9]{4,}$"
MAX_SKILL_RESULT_BYTES = 32 * 1024

ShortText = Annotated[str, Field(min_length=1, max_length=160)]
Description = Annotated[str, Field(min_length=1, max_length=600)]
Diagnostic = Annotated[str, Field(min_length=1, max_length=500)]
ReferenceId = Annotated[str, Field(pattern=REFERENCE_PATTERN)]
ObligationId = Annotated[str, Field(pattern=OBLIGATION_ID_PATTERN)]


class ObligationType(str, Enum):
    DOCUMENT_FACT = "document_fact"
    TABLE_CELL = "table_cell"
    NUMERIC_OPERAND = "numeric_operand"
    NUMERIC_OPERATION = "numeric_operation"
    UNIT_PERIOD = "unit_period"
    DOMAIN_RULE = "domain_rule"
    RULE_APPLICABILITY = "rule_applicability"
    EVIDENCE_CONFLICT = "evidence_conflict"
    FINAL_VERIFICATION = "final_verification"


class ObligationStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    SATISFIED = "satisfied"
    CONFLICTING = "conflicting"
    BLOCKED = "blocked"


class QuestionPhase(str, Enum):
    INITIALIZATION = "initialization"
    EXPLORATION = "exploration"
    FINALIZATION = "finalization"
    REVIEW = "review"
    CLOSED = "closed"


class SkillName(str, Enum):
    SEARCH_REPORT = "search_report"
    READ_PARAGRAPHS = "read_paragraphs"
    READ_TABLE_REGION = "read_table_region"
    BIND_FINANCIAL_VALUE = "bind_financial_value"
    EXECUTE_FINANCIAL_PROGRAM = "execute_financial_program"
    SEARCH_FINANCIAL_RULES = "search_financial_rules"
    READ_FINANCIAL_RULES = "read_financial_rules"
    CHECK_RULE_APPLICABILITY = "check_rule_applicability"
    SUBMIT_ANSWER = "submit_answer"


class SkillResultStatus(str, Enum):
    SATISFIED = "satisfied"
    PARTIAL = "partial"
    CONFLICT = "conflict"
    INVALID = "invalid"


class CertificateKind(str, Enum):
    DOCUMENT = "document"
    NUMERIC = "numeric"
    RULE_APPLICABILITY = "rule_applicability"
    FINAL_VERIFICATION = "final_verification"


class FinalCertificateStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class OperandSlot(BaseModel):
    """One required report-value slot for a numeric proof obligation.

    ``"unknown"`` is an explicit wildcard for metadata the conservative seeder
    cannot infer.  Runtime matching remains one-to-one: one ValueRef cannot fill
    two required slots, even when both slots contain wildcards.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: ReferenceId
    metric: ShortText = "unknown"
    entity: ShortText = "unknown"
    period: ShortText = "unknown"
    numeric_type: Literal[
        "unknown",
        "money",
        "percentage",
        "basis_points",
        "count",
        "ratio",
        "scalar",
        "duration",
        "date",
        "boolean",
    ] = "unknown"
    currency: ShortText = "unknown"
    unit: ShortText = "unknown"
    scale: ShortText = "unknown"


class ObligationMetadata(BaseModel):
    """Bounded, typed metadata shared by initial obligation families.

    Unknown values are represented explicitly by the string ``"unknown"`` in
    the relevant field; arbitrary dictionaries and nested model-provided data are
    intentionally not accepted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: ShortText | None = None
    entity: ShortText | None = None
    period: ShortText | None = None
    currency: ShortText | None = None
    unit: ShortText | None = None
    scale: ShortText | None = None
    jurisdiction: ShortText | None = None
    effective_date: ShortText | None = None
    entity_scope: ShortText | None = None
    relation: ShortText | None = None
    expected_relation: Literal["applies", "does_not_apply"] | None = None
    source_hint: ShortText | None = None
    operand_slots: list[OperandSlot] = Field(default_factory=list, max_length=16)
    ambiguity_flags: list[ShortText] = Field(default_factory=list, max_length=8)

    @field_validator("ambiguity_flags")
    @classmethod
    def ambiguity_flags_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("ambiguity_flags must be unique")
        return value

    @field_validator("operand_slots")
    @classmethod
    def operand_slot_ids_are_unique(cls, value: list[OperandSlot]) -> list[OperandSlot]:
        slot_ids = [slot.slot_id for slot in value]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("operand slot IDs must be unique")
        return value


class ObligationProposal(BaseModel):
    """A model or Skill proposal from which Runtime creates an obligation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ObligationType
    description: Description
    mandatory: bool = True
    dependency_ids: list[ObligationId] = Field(default_factory=list, max_length=12)
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)
    metadata: ObligationMetadata = Field(default_factory=ObligationMetadata)

    @field_validator("dependency_ids", "diagnostics")
    @classmethod
    def proposal_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("proposal lists must contain unique values")
        return value

    @model_validator(mode="after")
    def numeric_operands_have_typed_slots(self) -> "ObligationProposal":
        if (
            self.type is ObligationType.NUMERIC_OPERAND
            and not self.metadata.operand_slots
        ):
            raise ValueError("numeric operand obligations require operand slots")
        if (
            self.type is ObligationType.RULE_APPLICABILITY
            and self.metadata.expected_relation is None
        ):
            raise ValueError(
                "rule applicability obligations require an expected relation"
            )
        return self


class Obligation(BaseModel):
    """One Runtime-owned node in the persistent proof-obligation graph."""

    model_config = ConfigDict(extra="forbid")

    obligation_id: ObligationId
    type: ObligationType
    description: Description
    status: ObligationStatus = ObligationStatus.PENDING
    mandatory: bool = True
    dependency_ids: list[ObligationId] = Field(default_factory=list, max_length=12)
    evidence_refs: list[ReferenceId] = Field(default_factory=list, max_length=32)
    certificate_refs: list[ReferenceId] = Field(default_factory=list, max_length=16)
    created_phase: QuestionPhase
    created_step: int = Field(ge=0)
    updated_phase: QuestionPhase
    updated_step: int = Field(ge=0)
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)
    metadata: ObligationMetadata = Field(default_factory=ObligationMetadata)

    @field_validator(
        "dependency_ids", "evidence_refs", "certificate_refs", "diagnostics"
    )
    @classmethod
    def lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("obligation lists must contain unique values")
        return value

    @model_validator(mode="after")
    def local_invariants_hold(self) -> "Obligation":
        if self.obligation_id in self.dependency_ids:
            raise ValueError("an obligation cannot depend on itself")
        if self.updated_step < self.created_step:
            raise ValueError("obligation update cannot predate creation")
        if self.status is ObligationStatus.SATISFIED and not (
            self.evidence_refs or self.certificate_refs
        ):
            raise ValueError(
                "a satisfied obligation requires evidence or a certificate"
            )
        if (
            self.type is ObligationType.NUMERIC_OPERAND
            and not self.metadata.operand_slots
        ):
            raise ValueError("numeric operand obligations require operand slots")
        if (
            self.type is ObligationType.RULE_APPLICABILITY
            and self.metadata.expected_relation is None
        ):
            raise ValueError(
                "rule applicability obligations require an expected relation"
            )
        return self


class OpenObligationDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["open"] = "open"
    obligation: ObligationProposal


class AddDependencyDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["add_dependency"] = "add_dependency"
    obligation_id: ObligationId
    dependency_id: ObligationId

    @model_validator(mode="after")
    def dependency_is_not_self(self) -> "AddDependencyDelta":
        if self.obligation_id == self.dependency_id:
            raise ValueError("an obligation cannot depend on itself")
        return self


class AttachEvidenceDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["attach_evidence"] = "attach_evidence"
    obligation_id: ObligationId
    evidence_refs: list[ReferenceId] = Field(min_length=1, max_length=12)

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must be unique")
        return value


class MarkPartialDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["mark_partial"] = "mark_partial"
    obligation_id: ObligationId
    diagnostic: Diagnostic


class MarkConflictingDelta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Literal["mark_conflicting"] = "mark_conflicting"
    obligation_id: ObligationId
    diagnostic: Diagnostic


# This union deliberately has no mark_satisfied or waive variant.
ObligationDelta = Annotated[
    Union[
        OpenObligationDelta,
        AddDependencyDelta,
        AttachEvidenceDelta,
        MarkPartialDelta,
        MarkConflictingDelta,
    ],
    Field(discriminator="operation"),
]
OBLIGATION_DELTA_ADAPTER = TypeAdapter(ObligationDelta)


class CertificateEnvelope(BaseModel):
    """Small hash-bound certificate reference accepted in a SkillResult."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: ReferenceId
    kind: CertificateKind
    payload_sha256: str = Field(pattern=SHA256_PATTERN)
    claim_sha256: str = Field(pattern=SHA256_PATTERN)
    evidence_refs: list[ReferenceId] = Field(default_factory=list, max_length=24)
    verified: bool
    diagnostic: Diagnostic | None = None

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("certificate evidence_refs must be unique")
        return value


class SkillResult(BaseModel):
    """The only bounded transaction result accepted from a protocol-v3 Skill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SkillResultStatus
    target_obligation_id: ObligationId
    satisfied_obligation_ids: list[ObligationId] = Field(
        default_factory=list, max_length=16
    )
    partial_obligation_ids: list[ObligationId] = Field(
        default_factory=list, max_length=16
    )
    conflicting_obligation_ids: list[ObligationId] = Field(
        default_factory=list, max_length=16
    )
    spawned_obligations: list[ObligationProposal] = Field(
        default_factory=list, max_length=8
    )
    evidence_refs: list[ReferenceId] = Field(default_factory=list, max_length=32)
    certificate: CertificateEnvelope | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)

    @field_validator(
        "satisfied_obligation_ids",
        "partial_obligation_ids",
        "conflicting_obligation_ids",
        "evidence_refs",
        "diagnostics",
    )
    @classmethod
    def result_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("SkillResult lists must contain unique values")
        return value

    @model_validator(mode="after")
    def result_is_consistent_and_bounded(self) -> "SkillResult":
        groups = (
            set(self.satisfied_obligation_ids),
            set(self.partial_obligation_ids),
            set(self.conflicting_obligation_ids),
        )
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("SkillResult obligation outcome lists must be disjoint")
        if self.status is SkillResultStatus.SATISFIED and not self.satisfied_obligation_ids:
            raise ValueError("satisfied SkillResult requires a satisfied obligation")
        if self.status is SkillResultStatus.PARTIAL and not self.partial_obligation_ids:
            raise ValueError("partial SkillResult requires a partial obligation")
        if self.status is SkillResultStatus.CONFLICT and not self.conflicting_obligation_ids:
            raise ValueError("conflict SkillResult requires a conflicting obligation")
        if self.status is SkillResultStatus.INVALID and any(groups):
            raise ValueError("invalid SkillResult cannot change obligation status")
        if self.status is SkillResultStatus.INVALID and (
            self.spawned_obligations or self.certificate is not None
        ):
            raise ValueError("invalid SkillResult cannot mutate ledgers or obligations")
        affected = groups[0] | groups[1] | groups[2]
        if self.status is not SkillResultStatus.INVALID and (
            self.target_obligation_id not in affected
        ):
            raise ValueError("SkillResult must affect its target obligation")
        if self.satisfied_obligation_ids and not (
            self.evidence_refs or (self.certificate is not None and self.certificate.verified)
        ):
            raise ValueError(
                "satisfied SkillResult requires evidence or a verified certificate"
            )
        if len(self.model_dump_json().encode("utf-8")) > MAX_SKILL_RESULT_BYTES:
            raise ValueError("SkillResult exceeds the serialized size limit")
        return self


class SkillContract(BaseModel):
    """Immutable entry for the future code-owned static Skill Registry."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, arbitrary_types_allowed=True
    )

    name: SkillName
    argument_model: type[BaseModel]
    target_obligation_types: tuple[ObligationType, ...] = Field(
        min_length=1, max_length=9
    )
    preconditions: tuple[ShortText, ...] = Field(default=(), max_length=12)
    maximum_calls: int = Field(ge=1, le=100)
    deterministic: bool
    produces_certificate: bool
    availability_reason: ShortText
    unavailable_reason: ShortText

    @field_validator("target_obligation_types", "preconditions")
    @classmethod
    def contract_tuples_are_unique(cls, value: tuple[object, ...]) -> tuple[object, ...]:
        if len(value) != len(set(value)):
            raise ValueError("SkillContract collections must be unique")
        return value
