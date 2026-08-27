"""Strict schemas for a synthetic, hash-frozen financial rule corpus."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REFERENCE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
ReferenceId = Annotated[str, Field(pattern=REFERENCE_PATTERN)]
ShortText = Annotated[str, Field(min_length=1, max_length=160)]
Diagnostic = Annotated[str, Field(min_length=1, max_length=500)]


class RulePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    predicate_id: ReferenceId
    kind: Literal["document_contains", "document_not_contains"]
    term: ShortText
    required: bool = True


class RuleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: ReferenceId
    title: ShortText
    text: str = Field(min_length=1, max_length=20_000)
    aliases: list[ShortText] = Field(default_factory=list, max_length=16)
    jurisdiction: ShortText
    entity_scope: ShortText
    topic: ShortText
    effective_from: date
    effective_to: date | None = None
    source_reference: str = Field(min_length=1, max_length=500)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    predicates: list[RulePredicate] = Field(default_factory=list, max_length=16)
    conflicts_with: list[ReferenceId] = Field(default_factory=list, max_length=16)

    @field_validator("aliases", "conflicts_with")
    @classmethod
    def lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("rule collections must be unique")
        return value

    @field_validator("predicates")
    @classmethod
    def predicates_are_unique(
        cls, value: list[RulePredicate]
    ) -> list[RulePredicate]:
        identifiers = [item.predicate_id for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("rule predicate IDs must be unique")
        return value

    @model_validator(mode="after")
    def effective_interval_and_conflicts_are_valid(self) -> "RuleRecord":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("rule effective_to cannot predate effective_from")
        if self.rule_id in self.conflicts_with:
            raise ValueError("a rule cannot conflict with itself")
        return self


class RuleCorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    schema_version: Literal[1]
    source_name: ShortText
    source_version: ShortText
    created_at: datetime
    records_sha256: str = Field(pattern=SHA256_PATTERN)
    license_note: str = Field(min_length=1, max_length=1_000)
    provenance_note: str = Field(min_length=1, max_length=1_000)

    @field_validator("created_at")
    @classmethod
    def creation_time_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class RuleRecordsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    records: list[RuleRecord] = Field(min_length=1, max_length=10_000)


class RuleSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: ReferenceId
    score: int = Field(gt=0, le=1_000_000)
    snippet: str = Field(min_length=1, max_length=240)


class RuleApplicabilityResult(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNDETERMINED = "undetermined"


class RulePredicateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: ReferenceId
    predicate_id: ReferenceId
    satisfied: bool
    evidence_refs: list[ReferenceId] = Field(default_factory=list, max_length=20)

    @field_validator("evidence_refs")
    @classmethod
    def evidence_is_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("predicate evidence refs must be unique")
        return value


class RuleApplicabilityCertificate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: ReferenceId
    corpus_id: ShortText
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    records_sha256: str = Field(pattern=SHA256_PATTERN)
    rule_evidence_refs: list[ReferenceId] = Field(min_length=1, max_length=10)
    rule_ids: list[ReferenceId] = Field(min_length=1, max_length=10)
    document_evidence_refs: list[ReferenceId] = Field(min_length=1, max_length=20)
    effective_date: ShortText
    jurisdiction: ShortText
    entity_scope: ShortText
    effective_date_check: bool | None
    jurisdiction_check: bool | None
    entity_scope_check: bool | None
    predicates: list[RulePredicateResult] = Field(default_factory=list, max_length=64)
    conflict_rule_ids: list[ReferenceId] = Field(default_factory=list, max_length=20)
    result: RuleApplicabilityResult
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)

    @field_validator(
        "rule_evidence_refs",
        "rule_ids",
        "document_evidence_refs",
        "conflict_rule_ids",
        "diagnostics",
    )
    @classmethod
    def certificate_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("applicability certificate collections must be unique")
        return value

    @model_validator(mode="after")
    def result_matches_mechanical_checks(self) -> "RuleApplicabilityCertificate":
        if len(self.rule_evidence_refs) != len(self.rule_ids):
            raise ValueError("rule evidence refs and rule IDs must align one-to-one")
        predicate_keys = [
            (predicate.rule_id, predicate.predicate_id)
            for predicate in self.predicates
        ]
        if len(predicate_keys) != len(set(predicate_keys)):
            raise ValueError("applicability predicate results must be unique")
        if any(predicate.rule_id not in self.rule_ids for predicate in self.predicates):
            raise ValueError("applicability predicate references an unselected rule")
        document_refs = set(self.document_evidence_refs)
        if any(
            set(predicate.evidence_refs) - document_refs
            for predicate in self.predicates
        ):
            raise ValueError("predicate evidence must be certificate document evidence")
        if set(self.conflict_rule_ids) - set(self.rule_ids):
            raise ValueError("conflicts must identify selected rule evidence")
        checks = (
            self.effective_date_check,
            self.jurisdiction_check,
            self.entity_scope_check,
        )
        predicate_failure = any(not item.satisfied for item in self.predicates)
        if self.result is RuleApplicabilityResult.APPLICABLE and (
            not all(check is True for check in checks)
            or predicate_failure
            or self.conflict_rule_ids
        ):
            raise ValueError("applicable result requires every check and no conflict")
        if self.result is RuleApplicabilityResult.NOT_APPLICABLE:
            if (
                any(check is None for check in checks)
                or self.conflict_rule_ids
                or not (any(check is False for check in checks) or predicate_failure)
            ):
                raise ValueError(
                    "not_applicable requires conclusive mechanical counterevidence"
                )
        if self.result is RuleApplicabilityResult.UNDETERMINED and not (
            any(check is None for check in checks) or self.conflict_rule_ids
        ):
            raise ValueError("undetermined requires missing metadata or a conflict")
        return self


__all__ = [
    "RuleApplicabilityCertificate",
    "RuleApplicabilityResult",
    "RuleCorpusManifest",
    "RulePredicate",
    "RulePredicateResult",
    "RuleRecord",
    "RuleRecordsFile",
    "RuleSearchHit",
]
