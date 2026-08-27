"""Independent durable state and transactional obligation graph for protocol v3."""

from __future__ import annotations

import hashlib
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from findver_agent.schemas import Confidence, Prediction, PublicTask

from .contracts import (
    AddDependencyDelta,
    AttachEvidenceDelta,
    CertificateEnvelope,
    Diagnostic,
    FinalCertificateStatus,
    MarkConflictingDelta,
    MarkPartialDelta,
    Obligation,
    ObligationDelta,
    ObligationId,
    ObligationProposal,
    ObligationStatus,
    ObligationType,
    OpenObligationDelta,
    QuestionPhase,
    ReferenceId,
    SHA256_PATTERN,
    ShortText,
    SkillName,
    SkillResult,
    SkillResultStatus,
)


MAX_STATE_BYTES = 4 * 1024 * 1024
DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ResumeIdentity(BaseModel):
    """All immutable inputs whose drift makes a v3 resume unsafe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["v3"] = "v3"
    example_id: str = Field(min_length=1, max_length=256)
    statement_sha256: str = Field(pattern=SHA256_PATTERN)
    report_name: str = Field(min_length=1, max_length=512)
    report_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    registry_sha256: str = Field(pattern=SHA256_PATTERN)
    obligation_policy_sha256: str = Field(pattern=SHA256_PATTERN)
    rule_corpus_id: ShortText | None = None
    rule_manifest_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    rule_records_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("report_name")
    @classmethod
    def report_name_is_bare_json_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("report_name must be a bare filename")
        if not value.lower().endswith(".json"):
            raise ValueError("report_name must use the .json extension")
        return value

    @model_validator(mode="after")
    def corpus_identity_is_all_or_nothing(self) -> "ResumeIdentity":
        corpus_values = (
            self.rule_corpus_id,
            self.rule_manifest_sha256,
            self.rule_records_sha256,
        )
        if any(value is not None for value in corpus_values) and not all(
            value is not None for value in corpus_values
        ):
            raise ValueError("rule corpus identity fields must be supplied together")
        return self

    @classmethod
    def create(
        cls,
        task: PublicTask,
        *,
        report_sha256: str,
        config_sha256: str,
        registry_sha256: str,
        obligation_policy_sha256: str,
        rule_corpus_id: str | None = None,
        rule_manifest_sha256: str | None = None,
        rule_records_sha256: str | None = None,
    ) -> "ResumeIdentity":
        return cls(
            example_id=task.example_id,
            statement_sha256=_sha256_text(task.statement),
            report_name=task.report,
            report_sha256=report_sha256,
            config_sha256=config_sha256,
            registry_sha256=registry_sha256,
            obligation_policy_sha256=obligation_policy_sha256,
            rule_corpus_id=rule_corpus_id,
            rule_manifest_sha256=rule_manifest_sha256,
            rule_records_sha256=rule_records_sha256,
        )

    def assert_matches_task(self, task: PublicTask) -> None:
        if (
            self.example_id != task.example_id
            or self.statement_sha256 != _sha256_text(task.statement)
            or self.report_name != task.report
        ):
            raise ValueError("protocol-v3 resume identity does not match the public task")


class EvidenceLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: ReferenceId
    source: Literal["report_paragraph", "table_cell"]
    paragraph_id: int = Field(ge=0)
    exact_text: str = Field(min_length=1, max_length=100_000)
    exact_text_sha256: str = Field(pattern=SHA256_PATTERN)
    table_id: ReferenceId | None = None
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)
    header_path: list[ShortText] = Field(default_factory=list, max_length=8)
    inferred_unit: ShortText = "unknown"
    inferred_scale: ShortText = "unknown"
    raw_source_start: int | None = Field(default=None, ge=0)
    raw_source_end: int | None = Field(default=None, ge=0)
    ambiguity_flags: list[ShortText] = Field(default_factory=list, max_length=8)

    @field_validator("header_path", "ambiguity_flags")
    @classmethod
    def evidence_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence metadata lists must be unique")
        return value

    @model_validator(mode="after")
    def table_coordinates_are_consistent(self) -> "EvidenceLedgerEntry":
        if _sha256_text(self.exact_text) != self.exact_text_sha256:
            raise ValueError("evidence exact_text does not match exact_text_sha256")
        coordinates = (self.table_id, self.row_index, self.column_index)
        if self.source == "table_cell":
            if not all(item is not None for item in coordinates):
                raise ValueError("table_cell evidence requires table coordinates")
        elif any(item is not None for item in coordinates):
            raise ValueError("paragraph evidence cannot contain table coordinates")
        elif self.header_path:
            raise ValueError("paragraph evidence cannot contain a table header path")
        if (self.raw_source_start is None) != (self.raw_source_end is None):
            raise ValueError("raw source offsets must be supplied together")
        if (
            self.raw_source_start is not None
            and self.raw_source_end is not None
            and self.raw_source_end <= self.raw_source_start
        ):
            raise ValueError("raw source end must follow its start")
        return self


class NumericValueLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value_id: ReferenceId
    evidence_ref: ReferenceId
    raw_value: str = Field(min_length=1, max_length=128)
    normalized_value: str = Field(pattern=DECIMAL_PATTERN, max_length=128)
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
    period: ShortText
    entity: ShortText
    metric: ShortText
    paragraph_id: int = Field(ge=0)
    table_id: ReferenceId | None = None
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)
    text_span_start: int = Field(ge=0)
    text_span_end: int = Field(ge=1)
    ambiguity_flags: list[ShortText] = Field(default_factory=list, max_length=8)

    @field_validator("ambiguity_flags")
    @classmethod
    def ambiguity_flags_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("ambiguity_flags must be unique")
        return value

    @model_validator(mode="after")
    def source_coordinates_are_complete(self) -> "NumericValueLedgerEntry":
        if self.text_span_end <= self.text_span_start:
            raise ValueError("numeric value text span must be non-empty")
        coordinates = (self.row_index, self.column_index)
        if self.table_id is None and any(item is not None for item in coordinates):
            raise ValueError("paragraph value cannot contain table coordinates")
        if self.table_id is not None and not all(item is not None for item in coordinates):
            raise ValueError("table value requires row and column coordinates")
        return self


class FinancialProgramLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    program_id: ReferenceId
    program_sha256: str = Field(pattern=SHA256_PATTERN)
    operand_value_refs: list[ReferenceId] = Field(min_length=1, max_length=32)
    result_value: str = Field(pattern=DECIMAL_PATTERN, max_length=128)
    certificate_ref: ReferenceId | None = None

    @field_validator("operand_value_refs")
    @classmethod
    def operand_refs_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("operand_value_refs must be unique")
        return value


class RuleEvidenceLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_evidence_id: ReferenceId
    rule_id: ReferenceId
    rule_sha256: str = Field(pattern=SHA256_PATTERN)
    corpus_id: ShortText
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    records_sha256: str = Field(pattern=SHA256_PATTERN)


class SkillAvailabilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: QuestionPhase
    step: int = Field(ge=0)
    available_skills: list[SkillName] = Field(default_factory=list, max_length=9)
    selected_skill: SkillName | None = None
    rejected_skill: SkillName | None = None
    target_obligation_id: ObligationId | None = None
    availability_reasons: list[ShortText] = Field(default_factory=list, max_length=9)

    @field_validator("available_skills", "availability_reasons")
    @classmethod
    def availability_lists_are_unique(cls, value: list[object]) -> list[object]:
        if len(value) != len(set(value)):
            raise ValueError("availability record lists must be unique")
        return value

    @model_validator(mode="after")
    def selected_skill_was_available(self) -> "SkillAvailabilityRecord":
        if self.selected_skill is not None and self.selected_skill not in self.available_skills:
            raise ValueError("selected_skill must be present in available_skills")
        if self.selected_skill is not None and self.rejected_skill is not None:
            raise ValueError("an availability record cannot select and reject a Skill")
        return self


class BoundedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill: SkillName | None = None
    status: Literal["satisfied", "partial", "conflict", "invalid", "rejected"]
    target_obligation_id: ObligationId | None = None
    references: list[ReferenceId] = Field(default_factory=list, max_length=20)
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)

    @field_validator("references", "diagnostics")
    @classmethod
    def observation_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("observation lists must be unique")
        return value


class PhaseAttemptBudget(BaseModel):
    """Durable phase limits and charged attempts for exact resume."""

    model_config = ConfigDict(extra="forbid")

    exploration_limit: int = Field(ge=0, le=32)
    finalization_limit: int = Field(ge=0, le=8)
    review_limit: int = Field(ge=0, le=8)
    exploration_used: int = Field(default=0, ge=0, le=32)
    finalization_used: int = Field(default=0, ge=0, le=8)
    review_used: int = Field(default=0, ge=0, le=8)

    @model_validator(mode="after")
    def usage_does_not_exceed_limits(self) -> "PhaseAttemptBudget":
        for phase in ("exploration", "finalization", "review"):
            if getattr(self, f"{phase}_used") > getattr(self, f"{phase}_limit"):
                raise ValueError(f"{phase} attempts exceed the configured limit")
        return self

    @property
    def total_limit(self) -> int:
        return self.exploration_limit + self.finalization_limit + self.review_limit

    @property
    def total_used(self) -> int:
        return self.exploration_used + self.finalization_used + self.review_used

    def limit_for(self, phase: QuestionPhase) -> int:
        if phase is QuestionPhase.EXPLORATION:
            return self.exploration_limit
        if phase is QuestionPhase.FINALIZATION:
            return self.finalization_limit
        if phase is QuestionPhase.REVIEW:
            return self.review_limit
        raise ValueError(f"phase {phase.value} does not consume model attempts")

    def used_for(self, phase: QuestionPhase) -> int:
        if phase is QuestionPhase.EXPLORATION:
            return self.exploration_used
        if phase is QuestionPhase.FINALIZATION:
            return self.finalization_used
        if phase is QuestionPhase.REVIEW:
            return self.review_used
        raise ValueError(f"phase {phase.value} does not consume model attempts")

    def charge(self, phase: QuestionPhase) -> None:
        field = {
            QuestionPhase.EXPLORATION: "exploration_used",
            QuestionPhase.FINALIZATION: "finalization_used",
            QuestionPhase.REVIEW: "review_used",
        }.get(phase)
        if field is None:
            raise ValueError(f"phase {phase.value} does not consume model attempts")
        limit = self.limit_for(phase)
        used = self.used_for(phase)
        if used >= limit:
            raise ValueError(f"{phase.value} attempt budget is exhausted")
        setattr(self, field, used + 1)


class RuntimeUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    local_skill_calls: int = Field(default=0, ge=0)


class RuntimeErrorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: QuestionPhase
    step: int = Field(ge=0)
    kind: Literal["parse", "model", "skill", "protocol", "protocol_drift"]
    message: str = Field(min_length=1, max_length=500)


class ReportSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    paragraph_id: int = Field(ge=0)
    score: float = Field(ge=0)
    snippet: str = Field(min_length=1, max_length=500)


class ReportSearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=500)
    target_obligation_id: ObligationId
    step: int = Field(ge=0)
    hits: list[ReportSearchHit] = Field(default_factory=list, max_length=10)

    @field_validator("hits")
    @classmethod
    def hit_ids_are_unique(cls, value: list[ReportSearchHit]) -> list[ReportSearchHit]:
        ids = [hit.paragraph_id for hit in value]
        if len(ids) != len(set(ids)):
            raise ValueError("search hit paragraph IDs must be unique")
        return value


class TableCandidateRecord(BaseModel):
    """Bounded report-table catalog entry persisted for prompt and resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table_id: ReferenceId
    paragraph_id: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=500)
    row_count: int = Field(ge=0, le=10_000)
    column_count: int = Field(ge=0, le=1_000)
    ambiguity_flags: list[ShortText] = Field(default_factory=list, max_length=8)

    @field_validator("ambiguity_flags")
    @classmethod
    def candidate_flags_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("table candidate ambiguity flags must be unique")
        return value


class FinOASISQuestionState(BaseModel):
    """Strict protocol-v3 state with graph and ledger integrity validation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = 3
    protocol_version: Literal["v3"] = "v3"
    resume_identity: ResumeIdentity
    example_id: str = Field(min_length=1, max_length=256)
    statement: str = Field(min_length=1)
    report: str = Field(min_length=1, max_length=512)
    phase: QuestionPhase = QuestionPhase.INITIALIZATION
    step: int = Field(default=0, ge=0)
    remaining_steps: int = Field(ge=0)
    phase_attempts: PhaseAttemptBudget
    confidence: Confidence = Confidence.LOW
    obligations: list[Obligation] = Field(default_factory=list, max_length=256)
    next_obligation_sequence: int = Field(default=1, ge=1, le=1_000_000)
    next_value_sequence: int = Field(default=1, ge=1, le=1_000_000)
    evidence_ledger: dict[ReferenceId, EvidenceLedgerEntry] = Field(
        default_factory=dict, max_length=512
    )
    numeric_value_ledger: dict[ReferenceId, NumericValueLedgerEntry] = Field(
        default_factory=dict, max_length=256
    )
    financial_program_ledger: dict[ReferenceId, FinancialProgramLedgerEntry] = Field(
        default_factory=dict, max_length=128
    )
    rule_evidence_ledger: dict[ReferenceId, RuleEvidenceLedgerEntry] = Field(
        default_factory=dict, max_length=128
    )
    certificate_ledger: dict[ReferenceId, CertificateEnvelope] = Field(
        default_factory=dict, max_length=128
    )
    skill_call_counts: dict[SkillName, int] = Field(default_factory=dict, max_length=9)
    skill_rejection_counts: dict[SkillName, int] = Field(
        default_factory=dict, max_length=9
    )
    skill_availability_history: list[SkillAvailabilityRecord] = Field(
        default_factory=list, max_length=512
    )
    report_search_history: list[ReportSearchRecord] = Field(
        default_factory=list, max_length=64
    )
    table_candidates: list[TableCandidateRecord] = Field(
        default_factory=list, max_length=512
    )
    last_observation: BoundedObservation | None = None
    usage: RuntimeUsage = Field(default_factory=RuntimeUsage)
    errors: list[RuntimeErrorRecord] = Field(default_factory=list, max_length=128)
    prediction: Prediction | None = None
    draft_prediction: Prediction | None = None
    closed: bool = False
    forced_finalization: bool = False
    termination_reason: ShortText | None = None
    final_certificate_status: FinalCertificateStatus = FinalCertificateStatus.PENDING
    unresolved_obligation_ids: list[ObligationId] = Field(
        default_factory=list, max_length=256
    )

    @field_validator("report")
    @classmethod
    def report_is_bare_json_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("report must be a bare filename")
        if not value.lower().endswith(".json"):
            raise ValueError("report must use the .json extension")
        return value

    @field_validator("skill_call_counts", "skill_rejection_counts")
    @classmethod
    def counts_are_nonnegative(cls, value: dict[SkillName, int]) -> dict[SkillName, int]:
        if any(type(count) is not int or count < 0 for count in value.values()):
            raise ValueError("Skill counts must be non-negative integers")
        return value

    @field_validator("unresolved_obligation_ids")
    @classmethod
    def unresolved_ids_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("unresolved_obligation_ids must be unique")
        return value

    @model_validator(mode="after")
    def state_integrity_holds(self) -> "FinOASISQuestionState":
        if (
            self.resume_identity.example_id != self.example_id
            or self.resume_identity.statement_sha256 != _sha256_text(self.statement)
            or self.resume_identity.report_name != self.report
        ):
            raise ValueError("state fields do not match the immutable resume identity")

        obligation_by_id: dict[str, Obligation] = {}
        for sequence, obligation in enumerate(self.obligations, start=1):
            expected_id = f"obl-{sequence:04d}"
            if obligation.obligation_id != expected_id:
                raise ValueError("obligation IDs must be deterministic and contiguous")
            if obligation.obligation_id in obligation_by_id:
                raise ValueError("duplicate obligation ID")
            obligation_by_id[obligation.obligation_id] = obligation
        if self.next_obligation_sequence != len(self.obligations) + 1:
            raise ValueError("next_obligation_sequence does not follow the obligation ledger")

        for sequence, value in enumerate(
            self.numeric_value_ledger.values(), start=1
        ):
            if value.value_id != f"value-{sequence:04d}":
                raise ValueError("ValueRef IDs must be deterministic and contiguous")
        if self.next_value_sequence != len(self.numeric_value_ledger) + 1:
            raise ValueError("next_value_sequence does not follow the value ledger")

        known_ids = set(obligation_by_id)
        for obligation in self.obligations:
            unknown = set(obligation.dependency_ids) - known_ids
            if unknown:
                raise ValueError("obligation references an unknown dependency")
        self._reject_dependency_cycles(obligation_by_id)

        for obligation in self.obligations:
            if obligation.status is ObligationStatus.SATISFIED and any(
                obligation_by_id[dependency].status is not ObligationStatus.SATISFIED
                for dependency in obligation.dependency_ids
            ):
                raise ValueError("satisfied obligation has an unsatisfied dependency")

        self._validate_ledger_keys()
        evidence_refs = (
            set(self.evidence_ledger)
            | set(self.numeric_value_ledger)
            | set(self.rule_evidence_ledger)
            | set(self.financial_program_ledger)
        )
        certificate_refs = set(self.certificate_ledger)
        for obligation in self.obligations:
            if set(obligation.evidence_refs) - evidence_refs:
                raise ValueError("obligation contains a dangling evidence reference")
            if set(obligation.certificate_refs) - certificate_refs:
                raise ValueError("obligation contains a dangling certificate reference")

        for value in self.numeric_value_ledger.values():
            if value.evidence_ref not in self.evidence_ledger:
                raise ValueError("numeric value contains a dangling evidence reference")
            source = self.evidence_ledger[value.evidence_ref]
            if value.paragraph_id != source.paragraph_id:
                raise ValueError("numeric value paragraph does not match its evidence")
            if (value.table_id, value.row_index, value.column_index) != (
                source.table_id,
                source.row_index,
                source.column_index,
            ):
                raise ValueError("numeric value table coordinates do not match evidence")
            if value.text_span_end > len(source.exact_text):
                raise ValueError("numeric value text span exceeds its evidence")
            if (
                source.exact_text[value.text_span_start : value.text_span_end]
                != value.raw_value
            ):
                raise ValueError("numeric value raw text does not match its source span")
        for program in self.financial_program_ledger.values():
            if set(program.operand_value_refs) - set(self.numeric_value_ledger):
                raise ValueError("financial program contains a dangling value reference")
            if (
                program.certificate_ref is not None
                and program.certificate_ref not in self.certificate_ledger
            ):
                raise ValueError("financial program contains a dangling certificate reference")
        for certificate in self.certificate_ledger.values():
            if set(certificate.evidence_refs) - evidence_refs:
                raise ValueError("certificate contains a dangling evidence reference")
            if certificate.claim_sha256 != self.resume_identity.statement_sha256:
                raise ValueError("certificate is not bound to the current claim")

        for record in self.skill_availability_history:
            if (
                record.target_obligation_id is not None
                and record.target_obligation_id not in known_ids
            ):
                raise ValueError("availability history targets an unknown obligation")
        for record in self.report_search_history:
            if record.target_obligation_id not in known_ids:
                raise ValueError("report search history targets an unknown obligation")
        table_ids = [candidate.table_id for candidate in self.table_candidates]
        if len(table_ids) != len(set(table_ids)):
            raise ValueError("table candidate IDs must be unique")

        if self.step != self.phase_attempts.total_used:
            raise ValueError("step does not match charged phase attempts")
        if self.remaining_steps != self.phase_attempts.total_limit - self.step:
            raise ValueError("remaining_steps does not match phase attempt budgets")
        if self.closed:
            if self.phase is not QuestionPhase.CLOSED:
                raise ValueError("closed state must use the closed phase")
            if self.prediction is None:
                raise ValueError("closed state requires a prediction")
        elif self.phase is QuestionPhase.CLOSED:
            raise ValueError("closed phase requires closed=true")
        for prediction in (self.prediction, self.draft_prediction):
            if prediction is not None and prediction.example_id != self.example_id:
                raise ValueError("prediction is not bound to the current example")

        active_ids = {
            obligation.obligation_id
            for obligation in self.obligations
            if obligation.status is not ObligationStatus.SATISFIED
        }
        if set(self.unresolved_obligation_ids) - active_ids:
            raise ValueError("unresolved_obligation_ids contains a resolved or unknown ID")
        if self.final_certificate_status is FinalCertificateStatus.VERIFIED:
            if self.unresolved_obligation_ids:
                raise ValueError("verified state cannot list unresolved obligations")
            if any(
                obligation.mandatory
                and obligation.status is not ObligationStatus.SATISFIED
                for obligation in self.obligations
            ):
                raise ValueError("verified state contains an unresolved mandatory obligation")
            if any(
                obligation.status is ObligationStatus.CONFLICTING
                for obligation in self.obligations
            ):
                raise ValueError("verified state contains an unresolved conflict")
            if not any(
                obligation.mandatory
                and obligation.type is ObligationType.FINAL_VERIFICATION
                and obligation.status is ObligationStatus.SATISFIED
                for obligation in self.obligations
            ):
                raise ValueError(
                    "verified state requires a satisfied final-verification obligation"
                )
        return self

    @staticmethod
    def _reject_dependency_cycles(obligations: dict[str, Obligation]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(obligation_id: str) -> None:
            if obligation_id in visiting:
                raise ValueError("obligation dependency graph contains a cycle")
            if obligation_id in visited:
                return
            visiting.add(obligation_id)
            for dependency_id in obligations[obligation_id].dependency_ids:
                visit(dependency_id)
            visiting.remove(obligation_id)
            visited.add(obligation_id)

        for obligation_id in obligations:
            visit(obligation_id)

    def _validate_ledger_keys(self) -> None:
        ledgers = (
            (self.evidence_ledger, "evidence_id"),
            (self.numeric_value_ledger, "value_id"),
            (self.financial_program_ledger, "program_id"),
            (self.rule_evidence_ledger, "rule_evidence_id"),
            (self.certificate_ledger, "certificate_id"),
        )
        all_keys: list[str] = []
        for ledger, identifier_field in ledgers:
            for key, entry in ledger.items():
                if getattr(entry, identifier_field) != key:
                    raise ValueError("ledger key does not match entry identifier")
                all_keys.append(str(key))
        if len(all_keys) != len(set(all_keys)):
            raise ValueError("ledger identifiers must be globally unique")

    @classmethod
    def create(
        cls,
        task: PublicTask,
        resume_identity: ResumeIdentity,
        max_steps: int,
        *,
        exploration_steps: int | None = None,
        finalization_steps: int = 0,
        review_steps: int = 0,
    ) -> "FinOASISQuestionState":
        resume_identity.assert_matches_task(task)
        exploration_limit = max_steps if exploration_steps is None else exploration_steps
        total_steps = exploration_limit + finalization_steps + review_steps
        if total_steps != max_steps:
            raise ValueError("phase attempt limits must sum to max_steps")
        return cls(
            resume_identity=resume_identity,
            example_id=task.example_id,
            statement=task.statement,
            report=task.report,
            remaining_steps=total_steps,
            phase_attempts=PhaseAttemptBudget(
                exploration_limit=exploration_limit,
                finalization_limit=finalization_steps,
                review_limit=review_steps,
            ),
        )

    def charge_attempt(self) -> None:
        """Persistently charge the current phase before invoking a model."""

        candidate = self.model_copy(deep=True)
        candidate.phase_attempts.charge(candidate.phase)
        candidate.step += 1
        candidate.remaining_steps -= 1
        validated = type(self).model_validate(candidate.model_dump(mode="python"))
        self._adopt(validated)

    def record_error(self, kind: str, message: str) -> None:
        bounded = " ".join(str(message).split())[:500]
        if not bounded:
            bounded = "unspecified Runtime error"
        if len(self.errors) >= 128:
            self.errors.pop(0)
        self.errors.append(
            RuntimeErrorRecord(
                phase=self.phase,
                step=self.step,
                kind=kind,
                message=bounded,
            )
        )

    def obligation(self, obligation_id: str) -> Obligation:
        for obligation in self.obligations:
            if obligation.obligation_id == obligation_id:
                return obligation
        raise ValueError(f"unknown obligation ID: {obligation_id}")

    def open_obligation(
        self,
        proposal: ObligationProposal,
        *,
        phase: QuestionPhase | None = None,
        step: int | None = None,
    ) -> Obligation:
        """Runtime-allocate one deterministic ID and transactionally add a node."""

        candidate = self.model_copy(deep=True)
        opened = candidate._open_obligation_unchecked(
            proposal, phase=phase or self.phase, step=self.step if step is None else step
        )
        validated = type(self).model_validate(candidate.model_dump(mode="python"))
        self._adopt(validated)
        return self.obligation(opened.obligation_id)

    def _open_obligation_unchecked(
        self, proposal: ObligationProposal, *, phase: QuestionPhase, step: int
    ) -> Obligation:
        known_ids = {item.obligation_id for item in self.obligations}
        if set(proposal.dependency_ids) - known_ids:
            raise ValueError("new obligation references an unknown dependency")
        obligation_id = f"obl-{self.next_obligation_sequence:04d}"
        obligation = Obligation(
            obligation_id=obligation_id,
            type=proposal.type,
            description=proposal.description,
            mandatory=proposal.mandatory,
            dependency_ids=list(proposal.dependency_ids),
            created_phase=phase,
            created_step=step,
            updated_phase=phase,
            updated_step=step,
            diagnostics=list(proposal.diagnostics),
            metadata=proposal.metadata,
        )
        self.obligations.append(obligation)
        self.next_obligation_sequence += 1
        return obligation

    def apply_model_deltas(self, deltas: list[ObligationDelta]) -> list[str]:
        """Apply model-safe deltas atomically; satisfaction is intentionally absent."""

        if len(deltas) > 16:
            raise ValueError("too many obligation deltas")
        candidate = self.model_copy(deep=True)
        opened_ids: list[str] = []
        for delta in deltas:
            if isinstance(delta, OpenObligationDelta):
                opened = candidate._open_obligation_unchecked(
                    delta.obligation, phase=candidate.phase, step=candidate.step
                )
                opened_ids.append(opened.obligation_id)
                continue
            obligation = candidate.obligation(delta.obligation_id)
            if isinstance(delta, AddDependencyDelta):
                candidate.obligation(delta.dependency_id)
                if obligation.status is ObligationStatus.SATISFIED:
                    raise ValueError("cannot change dependencies of a satisfied obligation")
                if delta.dependency_id not in obligation.dependency_ids:
                    obligation.dependency_ids.append(delta.dependency_id)
            elif isinstance(delta, AttachEvidenceDelta):
                known_evidence = (
                    set(candidate.evidence_ledger)
                    | set(candidate.numeric_value_ledger)
                    | set(candidate.rule_evidence_ledger)
                    | set(candidate.financial_program_ledger)
                )
                if set(delta.evidence_refs) - known_evidence:
                    raise ValueError("model delta references unknown evidence")
                for reference in delta.evidence_refs:
                    if reference not in obligation.evidence_refs:
                        obligation.evidence_refs.append(reference)
            elif isinstance(delta, MarkPartialDelta):
                if obligation.status not in {
                    ObligationStatus.PENDING,
                    ObligationStatus.PARTIAL,
                }:
                    raise ValueError("model cannot make this transition to partial")
                obligation.status = ObligationStatus.PARTIAL
                candidate._append_diagnostic(obligation, delta.diagnostic)
            elif isinstance(delta, MarkConflictingDelta):
                if obligation.status not in {
                    ObligationStatus.PENDING,
                    ObligationStatus.PARTIAL,
                    ObligationStatus.CONFLICTING,
                }:
                    raise ValueError("model cannot make this transition to conflicting")
                obligation.status = ObligationStatus.CONFLICTING
                candidate._append_diagnostic(obligation, delta.diagnostic)
            else:  # pragma: no cover - closed union, defensive at runtime boundary
                raise TypeError("unsupported obligation delta")
            obligation.updated_phase = candidate.phase
            obligation.updated_step = candidate.step

        validated = type(self).model_validate(candidate.model_dump(mode="python"))
        self._adopt(validated)
        return opened_ids

    apply_obligation_deltas = apply_model_deltas

    def apply_skill_result(self, result: SkillResult) -> None:
        """Transactionally apply the sole Runtime path that may satisfy nodes."""

        candidate = self.model_copy(deep=True)
        candidate.obligation(result.target_obligation_id)
        if result.status is SkillResultStatus.INVALID:
            return
        outcome_ids = (
            result.satisfied_obligation_ids
            + result.partial_obligation_ids
            + result.conflicting_obligation_ids
        )
        for obligation_id in outcome_ids:
            candidate.obligation(obligation_id)

        known_evidence = (
            set(candidate.evidence_ledger)
            | set(candidate.numeric_value_ledger)
            | set(candidate.rule_evidence_ledger)
            | set(candidate.financial_program_ledger)
        )
        if set(result.evidence_refs) - known_evidence:
            raise ValueError("SkillResult references unknown evidence")

        certificate_ref: str | None = None
        if result.certificate is not None:
            certificate_ref = result.certificate.certificate_id
            if certificate_ref in candidate.certificate_ledger:
                if candidate.certificate_ledger[certificate_ref] != result.certificate:
                    raise ValueError("certificate ID collision")
            else:
                if set(result.certificate.evidence_refs) - known_evidence:
                    raise ValueError("certificate references unknown evidence")
                if (
                    result.certificate.claim_sha256
                    != candidate.resume_identity.statement_sha256
                ):
                    raise ValueError("certificate is not bound to the current claim")
                candidate.certificate_ledger[certificate_ref] = result.certificate

        for obligation_id in result.satisfied_obligation_ids:
            obligation = candidate.obligation(obligation_id)
            if obligation.status is ObligationStatus.SATISFIED:
                raise ValueError("satisfied obligation cannot be satisfied again")
            if any(
                candidate.obligation(dependency).status is not ObligationStatus.SATISFIED
                for dependency in obligation.dependency_ids
            ):
                raise ValueError("SkillResult cannot satisfy before dependencies")
            candidate._attach_result_references(
                obligation, result.evidence_refs, certificate_ref
            )
            if not (obligation.evidence_refs or obligation.certificate_refs):
                raise ValueError("satisfaction requires evidence or a certificate")
            obligation.status = ObligationStatus.SATISFIED
            obligation.updated_phase = candidate.phase
            obligation.updated_step = candidate.step

        for obligation_id in result.partial_obligation_ids:
            obligation = candidate.obligation(obligation_id)
            if obligation.status not in {
                ObligationStatus.PENDING,
                ObligationStatus.PARTIAL,
                ObligationStatus.CONFLICTING,
            }:
                raise ValueError("SkillResult cannot make this transition to partial")
            candidate._attach_result_references(
                obligation, result.evidence_refs, certificate_ref
            )
            obligation.status = ObligationStatus.PARTIAL
            obligation.updated_phase = candidate.phase
            obligation.updated_step = candidate.step

        for obligation_id in result.conflicting_obligation_ids:
            obligation = candidate.obligation(obligation_id)
            if obligation.status is ObligationStatus.SATISFIED:
                raise ValueError("SkillResult cannot reopen a satisfied obligation")
            candidate._attach_result_references(
                obligation, result.evidence_refs, certificate_ref
            )
            obligation.status = ObligationStatus.CONFLICTING
            obligation.updated_phase = candidate.phase
            obligation.updated_step = candidate.step

        for proposal in result.spawned_obligations:
            candidate._open_obligation_unchecked(
                proposal, phase=candidate.phase, step=candidate.step
            )
        for diagnostic in result.diagnostics:
            candidate._append_diagnostic(
                candidate.obligation(result.target_obligation_id), diagnostic
            )

        validated = type(self).model_validate(candidate.model_dump(mode="python"))
        self._adopt(validated)

    @staticmethod
    def _append_diagnostic(obligation: Obligation, diagnostic: str) -> None:
        if diagnostic not in obligation.diagnostics:
            if len(obligation.diagnostics) >= 8:
                obligation.diagnostics.pop(0)
            obligation.diagnostics.append(diagnostic)

    @staticmethod
    def _attach_result_references(
        obligation: Obligation, evidence_refs: list[str], certificate_ref: str | None
    ) -> None:
        for reference in evidence_refs:
            if reference not in obligation.evidence_refs:
                obligation.evidence_refs.append(reference)
        if (
            certificate_ref is not None
            and certificate_ref not in obligation.certificate_refs
        ):
            obligation.certificate_refs.append(certificate_ref)

    def _adopt(self, validated: "FinOASISQuestionState") -> None:
        # Replace the complete model dictionary only after validation succeeds.
        self.__dict__.clear()
        self.__dict__.update(deepcopy(validated.__dict__))


QuestionStateV3 = FinOASISQuestionState
QuestionState = FinOASISQuestionState
V3ResumeIdentity = ResumeIdentity


def safe_example_filename(example_id: str, suffix: str = ".v3.json") -> str:
    digest = hashlib.sha256(example_id.encode("utf-8")).hexdigest()
    return f"{digest}{suffix}"


class FinOASISStateStore:
    """Atomic, fsync-backed protocol-v3 state store with strict identity resume."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, example_id: str) -> Path:
        return self.root / safe_example_filename(example_id)

    def load_or_create(
        self,
        task: PublicTask,
        resume_identity: ResumeIdentity,
        max_steps: int,
        *,
        exploration_steps: int | None = None,
        finalization_steps: int = 0,
        review_steps: int = 0,
    ) -> FinOASISQuestionState:
        resume_identity.assert_matches_task(task)
        path = self.path_for(task.example_id)
        if not path.exists():
            return FinOASISQuestionState.create(
                task,
                resume_identity,
                max_steps,
                exploration_steps=exploration_steps,
                finalization_steps=finalization_steps,
                review_steps=review_steps,
            )
        if path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError("saved protocol-v3 state exceeds the size limit")
        state = FinOASISQuestionState.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if state.resume_identity != resume_identity:
            raise ValueError("saved protocol-v3 resume identity does not match Runtime")
        if (state.example_id, state.statement, state.report) != (
            task.example_id,
            task.statement,
            task.report,
        ):
            raise ValueError("saved protocol-v3 state does not match the public task")
        return state

    def save(self, state: FinOASISQuestionState) -> None:
        validated = FinOASISQuestionState.model_validate(state.model_dump(mode="python"))
        payload = validated.model_dump_json(indent=2) + "\n"
        if len(payload.encode("utf-8")) > MAX_STATE_BYTES:
            raise ValueError("protocol-v3 state exceeds the size limit")
        path = self.path_for(validated.example_id)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory()
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _fsync_directory(self) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        directory_fd = os.open(self.root, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


V3StateStore = FinOASISStateStore
StateStore = FinOASISStateStore


__all__ = [
    "BoundedObservation",
    "EvidenceLedgerEntry",
    "FinancialProgramLedgerEntry",
    "FinOASISQuestionState",
    "FinOASISStateStore",
    "NumericValueLedgerEntry",
    "PhaseAttemptBudget",
    "QuestionState",
    "QuestionStateV3",
    "ReportSearchHit",
    "ReportSearchRecord",
    "ResumeIdentity",
    "RuleEvidenceLedgerEntry",
    "RuntimeErrorRecord",
    "RuntimeUsage",
    "SkillAvailabilityRecord",
    "StateStore",
    "TableCandidateRecord",
    "V3ResumeIdentity",
    "V3StateStore",
    "safe_example_filename",
]
