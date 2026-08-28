"""Deterministic final claim verification for FinOASIS protocol v3.

The verifier consumes only durable Runtime state plus one parsed submission.  It
does not inspect Gold, subset labels, scorer output, external files, or networks.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from findver_agent.financial_dsl.executor import (
    FinDSLExecutionError,
    execute_financial_program,
    financial_program_sha256,
    numeric_certificate_sha256,
)
from findver_agent.financial_rules.applicability import (
    RuleApplicabilityError,
    check_rule_applicability,
    rule_applicability_certificate_sha256,
)
from findver_agent.financial_rules.corpus import (
    FrozenRuleCorpus,
    RuleCorpusError,
    rule_record_sha256,
)
from findver_agent.financial_rules.models import RuleApplicabilityResult
from findver_agent.schemas import Confidence, Label

from .contracts import (
    CertificateKind,
    Diagnostic,
    ObligationStatus,
    ObligationType,
    ReferenceId,
    SHA256_PATTERN,
)


MAX_FINAL_DOCUMENT_REFS = 24


class ClaimCertificateVerifier:
    """Bound Runtime facade over the pure final-verification function."""

    __slots__ = ("_rule_corpus",)

    def __init__(self, rule_corpus: FrozenRuleCorpus | None = None) -> None:
        self._rule_corpus = rule_corpus

    def verify(self, **arguments: object) -> "ClaimVerificationCertificate":
        if "rule_corpus" in arguments:
            raise TypeError("rule_corpus is bound by ClaimCertificateVerifier")
        return verify_claim_submission(
            **arguments,
            rule_corpus=self._rule_corpus,
        )


class ClaimVerificationResult(str, Enum):
    VERIFIED = "verified"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ClaimVerificationFailure(str, Enum):
    INVALID_FINAL_TARGET = "invalid_final_target"
    MISSING_EXPLANATION = "missing_explanation"
    UNKNOWN_EVIDENCE = "unknown_evidence"
    TOO_MANY_EVIDENCE_REFS = "too_many_evidence_refs"
    MISSING_DOCUMENT_EVIDENCE = "missing_document_evidence"
    EVIDENCE_NOT_ATTACHED = "evidence_not_attached"
    EVIDENCE_HASH_MISMATCH = "evidence_hash_mismatch"
    UNRESOLVED_MANDATORY = "unresolved_mandatory"
    EVIDENCE_CONFLICT = "evidence_conflict"
    MISSING_NUMERIC_CERTIFICATE = "missing_numeric_certificate"
    INVALID_NUMERIC_CERTIFICATE = "invalid_numeric_certificate"
    NUMERIC_LABEL_MISMATCH = "numeric_label_mismatch"
    MISSING_RULE_CERTIFICATE = "missing_rule_certificate"
    INVALID_RULE_CERTIFICATE = "invalid_rule_certificate"
    RULE_LABEL_MISMATCH = "rule_label_mismatch"
    FALLBACK_CONTROL_REQUIRED = "fallback_control_required"


class ClaimVerificationCertificate(BaseModel):
    """Complete bounded final-verifier payload persisted beside its envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: ReferenceId
    target_obligation_id: ReferenceId
    claim_sha256: str = Field(pattern=SHA256_PATTERN)
    submission_sha256: str = Field(pattern=SHA256_PATTERN)
    explanation_sha256: str = Field(pattern=SHA256_PATTERN)
    label: Label
    submitted_evidence_ids: list[int] = Field(default_factory=list, max_length=30)
    document_evidence_refs: list[ReferenceId] = Field(
        default_factory=list, max_length=MAX_FINAL_DOCUMENT_REFS
    )
    numeric_certificate_refs: list[ReferenceId] = Field(
        default_factory=list, max_length=16
    )
    rule_certificate_refs: list[ReferenceId] = Field(
        default_factory=list, max_length=16
    )
    checked_obligation_ids: list[ReferenceId] = Field(
        default_factory=list, max_length=256
    )
    unresolved_obligation_ids: list[ReferenceId] = Field(
        default_factory=list, max_length=256
    )
    conflicting_obligation_ids: list[ReferenceId] = Field(
        default_factory=list, max_length=256
    )
    document_check_passed: bool
    numeric_check_passed: bool | None
    rule_check_passed: bool | None
    label_supported: bool | None
    fallback_controls_passed: bool | None
    result: ClaimVerificationResult
    failure_codes: list[ClaimVerificationFailure] = Field(
        default_factory=list, max_length=16
    )
    diagnostics: list[Diagnostic] = Field(default_factory=list, max_length=8)

    @field_validator(
        "submitted_evidence_ids",
        "document_evidence_refs",
        "numeric_certificate_refs",
        "rule_certificate_refs",
        "checked_obligation_ids",
        "unresolved_obligation_ids",
        "conflicting_obligation_ids",
        "failure_codes",
        "diagnostics",
    )
    @classmethod
    def collections_are_unique(cls, value: list[object]) -> list[object]:
        if len(value) != len(set(value)):
            raise ValueError("final certificate collections must be unique")
        return value

    @model_validator(mode="after")
    def result_matches_checks(self) -> "ClaimVerificationCertificate":
        if any(item < 0 for item in self.submitted_evidence_ids):
            raise ValueError("submitted evidence IDs must be non-negative")
        if set(self.unresolved_obligation_ids) - set(self.checked_obligation_ids):
            raise ValueError("unresolved obligations must be checked obligations")
        if set(self.conflicting_obligation_ids) - set(self.checked_obligation_ids):
            raise ValueError("conflicting obligations must be checked obligations")
        if self.target_obligation_id not in self.checked_obligation_ids:
            raise ValueError("final target must be a checked obligation")
        expected_submission = claim_submission_sha256_from_parts(
            self.label,
            self.submitted_evidence_ids,
            self.explanation_sha256,
        )
        if self.submission_sha256 != expected_submission:
            raise ValueError("final certificate submission hash is inconsistent")
        if self.result is ClaimVerificationResult.VERIFIED:
            if (
                self.failure_codes
                or self.unresolved_obligation_ids
                or self.conflicting_obligation_ids
                or not self.document_check_passed
                or self.numeric_check_passed is False
                or self.rule_check_passed is False
                or self.label_supported is False
                or self.fallback_controls_passed is not None
            ):
                raise ValueError("verified final certificate has a failed check")
            if not self.document_evidence_refs:
                raise ValueError("verified final certificate requires document evidence")
            if bool(self.numeric_certificate_refs) != (
                self.numeric_check_passed is True
            ):
                raise ValueError("verified numeric proof summary is inconsistent")
            if bool(self.rule_certificate_refs) != (
                self.rule_check_passed is True
            ):
                raise ValueError("verified rule proof summary is inconsistent")
            if self.numeric_certificate_refs or self.rule_certificate_refs:
                if self.label_supported is not True:
                    raise ValueError("verified specialist proof must support the label")
            elif self.label_supported is not None:
                raise ValueError("document-only proof has no mechanical label outcome")
        elif self.result is ClaimVerificationResult.INCOMPLETE:
            if (
                not self.unresolved_obligation_ids
                and not self.conflicting_obligation_ids
            ):
                raise ValueError("incomplete final certificate needs unresolved proof")
            if self.fallback_controls_passed is not True:
                raise ValueError("incomplete final certificate requires fallback controls")
            if set(self.failure_codes) - {
                ClaimVerificationFailure.UNRESOLVED_MANDATORY,
                ClaimVerificationFailure.EVIDENCE_CONFLICT,
            }:
                raise ValueError("incomplete final certificate contains a fatal failure")
            if (
                not self.document_check_passed
                or self.numeric_check_passed is False
                or self.rule_check_passed is False
                or self.label_supported is False
            ):
                raise ValueError("incomplete final certificate contains a failed check")
        elif not self.failure_codes:
            raise ValueError("failed final certificate requires a failure code")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def claim_submission_sha256_from_parts(
    label: Label | str,
    evidence_ids: Sequence[int],
    explanation_sha256: str,
) -> str:
    payload = {
        "label": Label(label).value,
        "evidence_ids": list(evidence_ids),
        "explanation_sha256": explanation_sha256,
    }
    return _sha256_text(_canonical_json(payload))


def claim_submission_sha256(
    label: Label | str, evidence_ids: Sequence[int], explanation: str
) -> str:
    return claim_submission_sha256_from_parts(
        label, evidence_ids, _sha256_text(explanation)
    )


def claim_verification_certificate_sha256(
    certificate: ClaimVerificationCertificate,
) -> str:
    return _sha256_text(_canonical_json(certificate.model_dump(mode="json")))


def _risk_values(risk_flags: Sequence[object]) -> set[str]:
    return {
        str(getattr(item, "value", item)).strip().casefold() for item in risk_flags
    }


def verify_claim_submission(
    *,
    state: object,
    label: Label | str,
    evidence_ids: Sequence[int],
    explanation: str,
    confidence: Confidence | str,
    risk_flags: Sequence[object],
    allow_fallback: bool,
    certificate_id: str,
    target_obligation_id: str,
    rule_corpus: FrozenRuleCorpus | None = None,
) -> ClaimVerificationCertificate:
    """Replay all proof links and classify one final submission deterministically."""

    selected_label = Label(label)
    failure_codes: list[ClaimVerificationFailure] = []
    diagnostics: list[str] = []

    def fail(code: ClaimVerificationFailure, message: str) -> None:
        if code not in failure_codes:
            failure_codes.append(code)
        bounded = " ".join(message.split())[:500]
        if bounded and bounded not in diagnostics and len(diagnostics) < 8:
            diagnostics.append(bounded)

    if not explanation.strip():
        fail(
            ClaimVerificationFailure.MISSING_EXPLANATION,
            "submission explanation must contain non-whitespace text",
        )

    obligations = list(getattr(state, "obligations"))
    obligation_by_id = {item.obligation_id: item for item in obligations}
    target_obligation = obligation_by_id.get(target_obligation_id)
    if (
        target_obligation is None
        or target_obligation.type is not ObligationType.FINAL_VERIFICATION
        or target_obligation.status is ObligationStatus.SATISFIED
    ):
        fail(
            ClaimVerificationFailure.INVALID_FINAL_TARGET,
            "submission target is not one active final-verification obligation",
        )
    checked_ids = [item.obligation_id for item in obligations]
    unresolved = [
        item.obligation_id
        for item in obligations
        if item.mandatory
        and item.type is not ObligationType.FINAL_VERIFICATION
        and item.status is not ObligationStatus.SATISFIED
    ]
    conflicting = [
        item.obligation_id
        for item in obligations
        if item.status is ObligationStatus.CONFLICTING
        or (
            item.type is ObligationType.EVIDENCE_CONFLICT
            and item.status is not ObligationStatus.SATISFIED
        )
    ]
    if unresolved:
        fail(
            ClaimVerificationFailure.UNRESOLVED_MANDATORY,
            f"{len(unresolved)} mandatory proof obligations remain unresolved",
        )
    if conflicting:
        fail(
            ClaimVerificationFailure.EVIDENCE_CONFLICT,
            f"{len(conflicting)} evidence conflicts remain unresolved",
        )

    submitted_ids = list(evidence_ids)
    if len(submitted_ids) > MAX_FINAL_DOCUMENT_REFS:
        fail(
            ClaimVerificationFailure.TOO_MANY_EVIDENCE_REFS,
            "submission exceeds the bounded final evidence-reference limit",
        )
    document_refs: list[str] = []
    evidence_ledger = getattr(state, "evidence_ledger")
    for paragraph_id in submitted_ids[:MAX_FINAL_DOCUMENT_REFS]:
        reference = f"report-paragraph:{paragraph_id}"
        evidence = evidence_ledger.get(reference)
        if evidence is None or evidence.source != "report_paragraph":
            fail(
                ClaimVerificationFailure.UNKNOWN_EVIDENCE,
                f"submitted paragraph {paragraph_id} was not read into the ledger",
            )
            continue
        if _sha256_text(evidence.exact_text) != evidence.exact_text_sha256:
            fail(
                ClaimVerificationFailure.EVIDENCE_HASH_MISMATCH,
                f"submitted paragraph {paragraph_id} failed its text hash",
            )
            continue
        document_refs.append(reference)

    attached_document_refs = {
        reference
        for obligation in obligations
        if obligation.type is ObligationType.DOCUMENT_FACT
        for reference in obligation.evidence_refs
        if reference in evidence_ledger
        and evidence_ledger[reference].source == "report_paragraph"
    }
    if document_refs and not set(document_refs) <= attached_document_refs:
        fail(
            ClaimVerificationFailure.EVIDENCE_NOT_ATTACHED,
            "submitted evidence is not attached to a document-fact obligation",
        )

    numeric_obligations = [
        item for item in obligations if item.type is ObligationType.NUMERIC_OPERATION
    ]
    numeric_refs: list[str] = []
    numeric_support: list[bool] = []
    for obligation in numeric_obligations:
        if obligation.status is not ObligationStatus.SATISFIED:
            continue
        references = [
            reference
            for reference in obligation.certificate_refs
            if reference in getattr(state, "numeric_certificate_ledger")
        ]
        if not references:
            fail(
                ClaimVerificationFailure.MISSING_NUMERIC_CERTIFICATE,
                f"numeric obligation {obligation.obligation_id} has no certificate",
            )
            continue
        for reference in references:
            certificate = state.numeric_certificate_ledger[reference]
            envelope = state.certificate_ledger.get(reference)
            program = state.financial_program_ledger.get(certificate.program_id)
            try:
                replayed = execute_financial_program(
                    program.program,
                    program.claim_relation,
                    values=state.numeric_value_ledger,
                    claims=state.claim_value_ledger,
                    program_id=program.program_id,
                    certificate_id=reference,
                ).certificate
            except (AttributeError, FinDSLExecutionError, KeyError, ValueError):
                replayed = None
            valid = (
                envelope is not None
                and envelope.kind is CertificateKind.NUMERIC
                and envelope.verified
                and envelope.claim_sha256 == state.resume_identity.statement_sha256
                and envelope.payload_sha256
                == numeric_certificate_sha256(certificate)
                and program is not None
                and program.program_sha256
                == financial_program_sha256(program.program, program.claim_relation)
                and program.program_sha256 == certificate.program_sha256
                and program.result_value == certificate.result
                and replayed == certificate
            )
            if not valid:
                fail(
                    ClaimVerificationFailure.INVALID_NUMERIC_CERTIFICATE,
                    f"numeric certificate {reference} failed replay validation",
                )
                continue
            numeric_refs.append(reference)
            numeric_support.append(certificate.relation_satisfied)

    rule_obligations = [
        item for item in obligations if item.type is ObligationType.RULE_APPLICABILITY
    ]
    rule_refs: list[str] = []
    rule_support: list[bool] = []
    for obligation in rule_obligations:
        if obligation.status is not ObligationStatus.SATISFIED:
            continue
        references = [
            reference
            for reference in obligation.certificate_refs
            if reference in getattr(state, "rule_applicability_certificate_ledger")
            and state.rule_applicability_certificate_ledger[reference].result
            in {
                RuleApplicabilityResult.APPLICABLE,
                RuleApplicabilityResult.NOT_APPLICABLE,
            }
        ]
        if not references:
            fail(
                ClaimVerificationFailure.MISSING_RULE_CERTIFICATE,
                f"rule obligation {obligation.obligation_id} has no conclusive certificate",
            )
            continue
        for reference in references:
            certificate = state.rule_applicability_certificate_ledger[reference]
            envelope = state.certificate_ledger.get(reference)
            dependencies = [
                obligation_by_id[item]
                for item in obligation.dependency_ids
                if item in obligation_by_id
            ]
            domain_dependencies = [
                item for item in dependencies if item.type is ObligationType.DOMAIN_RULE
            ]
            document_dependencies = [
                item
                for item in dependencies
                if item.type is ObligationType.DOCUMENT_FACT
            ]
            dependency_rule_refs = {
                item
                for dependency in domain_dependencies
                for item in dependency.evidence_refs
            }
            dependency_document_refs = {
                item
                for dependency in document_dependencies
                for item in dependency.evidence_refs
            }
            metadata = obligation.metadata
            scope_valid = (
                metadata.jurisdiction == certificate.jurisdiction
                and metadata.effective_date == certificate.effective_date
                and metadata.entity_scope == certificate.entity_scope
            )
            records_valid = all(
                evidence.rule_sha256 == rule_record_sha256(evidence.record)
                and evidence.record.source_sha256
                == _sha256_text(evidence.record.text)
                for evidence_ref in certificate.rule_evidence_refs
                if (evidence := state.rule_evidence_ledger.get(evidence_ref))
                is not None
            ) and all(
                evidence_ref in state.rule_evidence_ledger
                for evidence_ref in certificate.rule_evidence_refs
            )
            try:
                replayed = (
                    check_rule_applicability(
                        corpus=rule_corpus,
                        rule_evidence=[
                            state.rule_evidence_ledger[item]
                            for item in certificate.rule_evidence_refs
                        ],
                        document_evidence=[
                            state.evidence_ledger[item]
                            for item in certificate.document_evidence_refs
                        ],
                        effective_date=certificate.effective_date,
                        jurisdiction=certificate.jurisdiction,
                        entity_scope=certificate.entity_scope,
                        predicate_ids=[
                            item.predicate_id for item in certificate.predicates
                        ],
                        certificate_id=reference,
                    )
                    if rule_corpus is not None
                    else None
                )
            except (
                KeyError,
                RuleApplicabilityError,
                RuleCorpusError,
                ValueError,
            ):
                replayed = None
            valid = (
                envelope is not None
                and envelope.kind is CertificateKind.RULE_APPLICABILITY
                and envelope.verified
                and envelope.claim_sha256 == state.resume_identity.statement_sha256
                and envelope.payload_sha256
                == rule_applicability_certificate_sha256(certificate)
                and certificate.corpus_id == state.resume_identity.rule_corpus_id
                and certificate.manifest_sha256
                == state.resume_identity.rule_manifest_sha256
                and certificate.records_sha256
                == state.resume_identity.rule_records_sha256
                and records_valid
                and bool(domain_dependencies)
                and all(
                    item.status is ObligationStatus.SATISFIED
                    for item in domain_dependencies
                )
                and set(certificate.rule_evidence_refs) <= dependency_rule_refs
                and set(certificate.document_evidence_refs)
                <= dependency_document_refs
                and scope_valid
                and replayed == certificate
            )
            if not valid:
                fail(
                    ClaimVerificationFailure.INVALID_RULE_CERTIFICATE,
                    f"rule certificate {reference} failed replay validation",
                )
                continue
            rule_refs.append(reference)
            expected_applies = metadata.expected_relation == "applies"
            certificate_applies = (
                certificate.result is RuleApplicabilityResult.APPLICABLE
            )
            rule_support.append(certificate_applies is expected_applies)

    expected_support = selected_label is Label.ENTAILED
    if numeric_support and any(value is not expected_support for value in numeric_support):
        fail(
            ClaimVerificationFailure.NUMERIC_LABEL_MISMATCH,
            "numeric certificate relation does not support the submitted label",
        )
    if rule_support and any(value is not expected_support for value in rule_support):
        fail(
            ClaimVerificationFailure.RULE_LABEL_MISMATCH,
            "rule applicability result does not support the submitted label",
        )

    specialist_failure_codes = {
        ClaimVerificationFailure.MISSING_NUMERIC_CERTIFICATE,
        ClaimVerificationFailure.INVALID_NUMERIC_CERTIFICATE,
        ClaimVerificationFailure.NUMERIC_LABEL_MISMATCH,
        ClaimVerificationFailure.MISSING_RULE_CERTIFICATE,
        ClaimVerificationFailure.INVALID_RULE_CERTIFICATE,
        ClaimVerificationFailure.RULE_LABEL_MISMATCH,
    }
    document_fatal_codes = {
        ClaimVerificationFailure.MISSING_EXPLANATION,
        ClaimVerificationFailure.UNKNOWN_EVIDENCE,
        ClaimVerificationFailure.TOO_MANY_EVIDENCE_REFS,
        ClaimVerificationFailure.EVIDENCE_NOT_ATTACHED,
        ClaimVerificationFailure.EVIDENCE_HASH_MISMATCH,
    }
    fallback_needed = bool(unresolved or conflicting)
    if not document_refs and not fallback_needed:
        fail(
            ClaimVerificationFailure.MISSING_DOCUMENT_EVIDENCE,
            "normal submission requires at least one read report paragraph",
        )

    fallback_controls: bool | None = None
    if fallback_needed:
        fallback_controls = (
            allow_fallback
            and Confidence(confidence) is Confidence.LOW
            and "unresolved_obligation" in _risk_values(risk_flags)
        )
        if not fallback_controls:
            fail(
                ClaimVerificationFailure.FALLBACK_CONTROL_REQUIRED,
                "incomplete submission requires low confidence and unresolved risk",
            )

    fatal = set(failure_codes) & (
        specialist_failure_codes
        | document_fatal_codes
        | {
            ClaimVerificationFailure.INVALID_FINAL_TARGET,
            ClaimVerificationFailure.MISSING_DOCUMENT_EVIDENCE,
            ClaimVerificationFailure.FALLBACK_CONTROL_REQUIRED,
        }
    )
    if fallback_needed and fallback_controls and not fatal:
        result = ClaimVerificationResult.INCOMPLETE
    elif failure_codes:
        result = ClaimVerificationResult.FAILED
    else:
        result = ClaimVerificationResult.VERIFIED
        diagnostics.append("all deterministic final claim checks passed")

    numeric_check = None if not numeric_obligations else not bool(
        set(failure_codes)
        & {
            ClaimVerificationFailure.MISSING_NUMERIC_CERTIFICATE,
            ClaimVerificationFailure.INVALID_NUMERIC_CERTIFICATE,
            ClaimVerificationFailure.NUMERIC_LABEL_MISMATCH,
        }
    )
    rule_check = None if not rule_obligations else not bool(
        set(failure_codes)
        & {
            ClaimVerificationFailure.MISSING_RULE_CERTIFICATE,
            ClaimVerificationFailure.INVALID_RULE_CERTIFICATE,
            ClaimVerificationFailure.RULE_LABEL_MISMATCH,
        }
    )
    label_supported = None if not (numeric_support or rule_support) else not bool(
        set(failure_codes)
        & {
            ClaimVerificationFailure.NUMERIC_LABEL_MISMATCH,
            ClaimVerificationFailure.RULE_LABEL_MISMATCH,
        }
    )
    explanation_hash = _sha256_text(explanation)
    return ClaimVerificationCertificate(
        certificate_id=certificate_id,
        target_obligation_id=target_obligation_id,
        claim_sha256=state.resume_identity.statement_sha256,
        submission_sha256=claim_submission_sha256_from_parts(
            selected_label, submitted_ids, explanation_hash
        ),
        explanation_sha256=explanation_hash,
        label=selected_label,
        submitted_evidence_ids=submitted_ids,
        document_evidence_refs=document_refs,
        numeric_certificate_refs=list(dict.fromkeys(numeric_refs)),
        rule_certificate_refs=list(dict.fromkeys(rule_refs)),
        checked_obligation_ids=checked_ids,
        unresolved_obligation_ids=unresolved,
        conflicting_obligation_ids=conflicting,
        document_check_passed=not bool(
            set(failure_codes)
            & (
                document_fatal_codes
                | {ClaimVerificationFailure.MISSING_DOCUMENT_EVIDENCE}
            )
        ),
        numeric_check_passed=numeric_check,
        rule_check_passed=rule_check,
        label_supported=label_supported,
        fallback_controls_passed=fallback_controls,
        result=result,
        failure_codes=failure_codes,
        diagnostics=diagnostics or ["submission verification failed"],
    )


__all__ = [
    "ClaimCertificateVerifier",
    "ClaimVerificationCertificate",
    "ClaimVerificationFailure",
    "ClaimVerificationResult",
    "claim_submission_sha256",
    "claim_submission_sha256_from_parts",
    "claim_verification_certificate_sha256",
    "verify_claim_submission",
]
