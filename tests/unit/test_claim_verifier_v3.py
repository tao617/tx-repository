import hashlib
from pathlib import Path

import pytest

from findver_agent.config import FinOasisRuleCorpusConfig
from findver_agent.financial_dsl.executor import (
    execute_financial_program,
    numeric_certificate_sha256,
)
from findver_agent.financial_dsl.models import FinancialProgram
from findver_agent.financial_rules.applicability import (
    check_rule_applicability,
    rule_applicability_certificate_sha256,
)
from findver_agent.financial_rules.corpus import FrozenRuleCorpus, rule_record_sha256
from findver_agent.financial_rules.models import RuleApplicabilityResult
from findver_agent.findoasis.claim_verifier import (
    ClaimVerificationFailure,
    ClaimVerificationResult,
    claim_verification_certificate_sha256,
    verify_claim_submission,
)
from findver_agent.findoasis.contracts import (
    CertificateEnvelope,
    CertificateKind,
    ObligationMetadata,
    OperandSlot,
    ObligationProposal,
    QuestionPhase,
    SkillResult,
)
from findver_agent.findoasis.state import (
    EvidenceLedgerEntry,
    FinancialProgramLedgerEntry,
    FinOASISQuestionState,
    NumericValueLedgerEntry,
    ResumeIdentity,
    RuleEvidenceLedgerEntry,
)
from findver_agent.schemas import PublicTask


FIXTURE_ROOT = Path("tests/fixtures/finoasis_rule_corpus").resolve()
MANIFEST_SHA256 = "549461e4b4a2fb1b8357b30f03589f62562db7a4b26ac8d38074b34080a4dc33"
RECORDS_SHA256 = "4a3085d2b0d32a320fbc8e5b99527221e1abd161a3a277239732804873fe3436"
EVIDENCE_TEXT = (
    "The performance obligation was satisfied. Revenue was 1200 in 2024 "
    "and 1000 in 2023."
)


def corpus():
    return FrozenRuleCorpus.load(
        FinOasisRuleCorpusConfig(
            enabled=True,
            rule_root=FIXTURE_ROOT,
            manifest_path=Path("manifest.json"),
            records_path=Path("records.json"),
            corpus_id="finoasis-synthetic-rules-v1",
            manifest_sha256=MANIFEST_SHA256,
            records_sha256=RECORDS_SHA256,
            read_only=True,
            network_fallback=False,
        )
    )


def mixed_state(
    *, numeric_true=True, rule_applicable=True, expected_relation="applies"
):
    task = PublicTask(
        example_id="mixed-verifier",
        statement=(
            "Under US GAAP, a public issuer on 2024-12-31 recognized revenue "
            "after it increased from 1000 in 2023 to 1200 in 2024."
        ),
        report="report.json",
    )
    identity = ResumeIdentity.create(
        task,
        report_sha256="1" * 64,
        config_sha256="2" * 64,
        registry_sha256="3" * 64,
        obligation_policy_sha256="4" * 64,
        rule_corpus_id="finoasis-synthetic-rules-v1",
        rule_manifest_sha256=MANIFEST_SHA256,
        rule_records_sha256=RECORDS_SHA256,
    )
    state = FinOASISQuestionState.create(task, identity, max_steps=8)
    state.phase = QuestionPhase.EXPLORATION
    fact = state.open_obligation(
        ObligationProposal(type="document_fact", description="Read the report fact.")
    )
    operands = state.open_obligation(
        ObligationProposal(
            type="numeric_operand",
            description="Bind both values.",
            dependency_ids=[fact.obligation_id],
            metadata=ObligationMetadata(
                operand_slots=[
                    OperandSlot(
                        slot_id="revenue-2024",
                        metric="revenue",
                        period="2024",
                    ),
                    OperandSlot(
                        slot_id="revenue-2023",
                        metric="revenue",
                        period="2023",
                    ),
                ]
            ),
        )
    )
    units = state.open_obligation(
        ObligationProposal(
            type="unit_period",
            description="Check units and periods.",
            dependency_ids=[operands.obligation_id],
        )
    )
    numeric = state.open_obligation(
        ObligationProposal(
            type="numeric_operation",
            description="Execute the numeric comparison.",
            dependency_ids=[operands.obligation_id, units.obligation_id],
        )
    )
    scope = ObligationMetadata(
        jurisdiction="US",
        effective_date="2024-12-31",
        entity_scope="public issuer",
        expected_relation=expected_relation,
    )
    domain = state.open_obligation(
        ObligationProposal(
            type="domain_rule", description="Read the rule.", metadata=scope
        )
    )
    applicability = state.open_obligation(
        ObligationProposal(
            type="rule_applicability",
            description="Check the rule scope.",
            dependency_ids=[fact.obligation_id, domain.obligation_id],
            metadata=scope,
        )
    )
    state.open_obligation(
        ObligationProposal(
            type="final_verification",
            description="Verify the complete claim.",
            dependency_ids=[
                fact.obligation_id,
                numeric.obligation_id,
                applicability.obligation_id,
            ],
        )
    )

    evidence_ref = "report-paragraph:0"
    state.evidence_ledger[evidence_ref] = EvidenceLedgerEntry(
        evidence_id=evidence_ref,
        source="report_paragraph",
        paragraph_id=0,
        exact_text=EVIDENCE_TEXT,
        exact_text_sha256=hashlib.sha256(EVIDENCE_TEXT.encode()).hexdigest(),
    )
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=fact.obligation_id,
            satisfied_obligation_ids=[fact.obligation_id],
            evidence_refs=[evidence_ref],
        )
    )

    value_ids = ("value-0001", "value-0002")
    for value_id, raw, period in zip(value_ids, ("1200", "1000"), ("2024", "2023")):
        start = EVIDENCE_TEXT.index(raw)
        state.numeric_value_ledger[value_id] = NumericValueLedgerEntry(
            value_id=value_id,
            evidence_ref=evidence_ref,
            raw_value=raw,
            normalized_value=raw,
            numeric_type="money",
            currency="USD",
            unit="USD",
            scale="one",
            period=period,
            entity="issuer",
            metric="revenue",
            paragraph_id=0,
            text_span_start=start,
            text_span_end=start + len(raw),
        )
    state.next_value_sequence = 3
    for obligation in (operands, units):
        state.apply_skill_result(
            SkillResult(
                status="satisfied",
                target_obligation_id=obligation.obligation_id,
                satisfied_obligation_ids=[obligation.obligation_id],
                evidence_refs=list(value_ids),
            )
        )

    program = FinancialProgram(
        op="greater_than" if numeric_true else "less_than",
        args=[
            {"kind": "value_ref", "ref": value_ids[0]},
            {"kind": "value_ref", "ref": value_ids[1]},
        ],
    )
    executed = execute_financial_program(
        program,
        None,
        values=state.numeric_value_ledger,
        claims=state.claim_value_ledger,
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )
    numeric_certificate = executed.certificate
    state.financial_program_ledger["program-0001"] = FinancialProgramLedgerEntry(
        program_id="program-0001",
        program_sha256=executed.program_sha256,
        operator=program.op.value,
        program=program,
        operand_value_refs=list(value_ids),
        result_value=numeric_certificate.result,
        result_type=numeric_certificate.result_type,
        certificate_ref=numeric_certificate.certificate_id,
    )
    state.numeric_certificate_ledger[numeric_certificate.certificate_id] = (
        numeric_certificate
    )
    state.next_program_sequence = 2
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=numeric.obligation_id,
            satisfied_obligation_ids=[numeric.obligation_id],
            evidence_refs=["program-0001"],
            certificate=CertificateEnvelope(
                certificate_id=numeric_certificate.certificate_id,
                kind=CertificateKind.NUMERIC,
                payload_sha256=numeric_certificate_sha256(numeric_certificate),
                claim_sha256=identity.statement_sha256,
                evidence_refs=[evidence_ref],
                verified=True,
            ),
        )
    )

    frozen = corpus()
    record = frozen.record("synthetic-us-revenue-current")
    state.rule_evidence_ledger["rule-evidence-0001"] = RuleEvidenceLedgerEntry(
        rule_evidence_id="rule-evidence-0001",
        rule_id=record.rule_id,
        rule_sha256=rule_record_sha256(record),
        corpus_id=frozen.corpus_id,
        manifest_sha256=frozen.manifest_sha256,
        records_sha256=frozen.records_sha256,
        record=record,
    )
    state.next_rule_evidence_sequence = 2
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=domain.obligation_id,
            satisfied_obligation_ids=[domain.obligation_id],
            evidence_refs=["rule-evidence-0001"],
        )
    )
    rule_certificate = check_rule_applicability(
        corpus=frozen,
        rule_evidence=[state.rule_evidence_ledger["rule-evidence-0001"]],
        document_evidence=[state.evidence_ledger[evidence_ref]],
        effective_date="2024-12-31",
        jurisdiction="US" if rule_applicable else "EU",
        entity_scope="public issuer",
        predicate_ids=["predicate:performance-obligation"],
        certificate_id="rule-certificate-0001",
    )
    if not rule_applicable:
        state.obligation(applicability.obligation_id).metadata = ObligationMetadata(
            jurisdiction="EU",
            effective_date="2024-12-31",
            entity_scope="public issuer",
            expected_relation=expected_relation,
        )
    state.rule_applicability_certificate_ledger[rule_certificate.certificate_id] = (
        rule_certificate
    )
    state.next_rule_certificate_sequence = 2
    rule_refs = ["rule-evidence-0001", evidence_ref]
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=applicability.obligation_id,
            satisfied_obligation_ids=[applicability.obligation_id],
            evidence_refs=rule_refs,
            certificate=CertificateEnvelope(
                certificate_id=rule_certificate.certificate_id,
                kind=CertificateKind.RULE_APPLICABILITY,
                payload_sha256=rule_applicability_certificate_sha256(rule_certificate),
                claim_sha256=identity.statement_sha256,
                evidence_refs=rule_refs,
                verified=True,
            ),
        )
    )
    FinOASISQuestionState.model_validate(state.model_dump(mode="python"))
    return state, frozen


def verify(state, frozen, *, label="entailed", evidence_ids=(0,), **updates):
    values = {
        "state": state,
        "label": label,
        "evidence_ids": evidence_ids,
        "explanation": "The cited proof supports the submitted label.",
        "confidence": "high",
        "risk_flags": (),
        "allow_fallback": False,
        "certificate_id": "final-certificate-0001",
        "target_obligation_id": "obl-0007",
        "rule_corpus": frozen,
    }
    values.update(updates)
    return verify_claim_submission(**values)


@pytest.mark.parametrize(
    ("expected_relation", "rule_applicable", "label"),
    [
        ("applies", True, "entailed"),
        ("does_not_apply", True, "refuted"),
        ("applies", False, "refuted"),
        ("does_not_apply", False, "entailed"),
    ],
)
def test_rule_result_and_claim_polarity_jointly_support_all_label_combinations(
    expected_relation, rule_applicable, label
):
    state, frozen = mixed_state(
        numeric_true=label == "entailed",
        rule_applicable=rule_applicable,
        expected_relation=expected_relation,
    )
    certificate = verify(state, frozen, label=label)

    assert certificate.result is ClaimVerificationResult.VERIFIED
    assert certificate.numeric_check_passed is True
    assert certificate.rule_check_passed is True
    assert certificate.label_supported is True
    assert certificate.numeric_certificate_refs == ["numeric-certificate-0001"]
    assert certificate.rule_certificate_refs == ["rule-certificate-0001"]
    assert len(claim_verification_certificate_sha256(certificate)) == 64


def test_specialist_certificate_contradiction_fails_final_label():
    state, frozen = mixed_state()
    certificate = verify(state, frozen, label="refuted")
    assert certificate.result is ClaimVerificationResult.FAILED
    assert set(certificate.failure_codes) == {
        ClaimVerificationFailure.NUMERIC_LABEL_MISMATCH,
        ClaimVerificationFailure.RULE_LABEL_MISMATCH,
    }


def test_replay_rejects_coherently_rehashed_numeric_and_rule_tampering():
    state, frozen = mixed_state()
    numeric = state.numeric_certificate_ledger["numeric-certificate-0001"]
    changed_numeric = numeric.model_copy(
        update={"result": "false", "relation_satisfied": False}
    )
    state.numeric_certificate_ledger[numeric.certificate_id] = changed_numeric
    program = state.financial_program_ledger["program-0001"]
    state.financial_program_ledger["program-0001"] = program.model_copy(
        update={"result_value": "false"}
    )
    state.certificate_ledger[numeric.certificate_id] = state.certificate_ledger[
        numeric.certificate_id
    ].model_copy(update={"payload_sha256": numeric_certificate_sha256(changed_numeric)})

    numeric_tamper = verify(state, frozen, label="refuted")
    assert ClaimVerificationFailure.INVALID_NUMERIC_CERTIFICATE in (
        numeric_tamper.failure_codes
    )

    state, frozen = mixed_state()
    rule = state.rule_applicability_certificate_ledger["rule-certificate-0001"]
    changed_rule = rule.model_copy(
        update={
            "jurisdiction": "EU",
            "jurisdiction_check": False,
            "result": RuleApplicabilityResult.NOT_APPLICABLE,
        }
    )
    state.rule_applicability_certificate_ledger[rule.certificate_id] = changed_rule
    state.certificate_ledger[rule.certificate_id] = state.certificate_ledger[
        rule.certificate_id
    ].model_copy(
        update={
            "payload_sha256": rule_applicability_certificate_sha256(changed_rule)
        }
    )
    rule_tamper = verify(state, frozen, label="refuted")
    assert ClaimVerificationFailure.INVALID_RULE_CERTIFICATE in rule_tamper.failure_codes


def test_unknown_evidence_blank_explanation_and_missing_family_fail_closed():
    state, frozen = mixed_state()
    unknown = verify(state, frozen, evidence_ids=(99,))
    assert unknown.result is ClaimVerificationResult.FAILED
    assert ClaimVerificationFailure.UNKNOWN_EVIDENCE in unknown.failure_codes

    blank = verify(state, frozen, explanation="   ")
    assert blank.result is ClaimVerificationResult.FAILED
    assert ClaimVerificationFailure.MISSING_EXPLANATION in blank.failure_codes

    numeric_obligation = next(
        item for item in state.obligations if item.type.value == "numeric_operation"
    )
    numeric_obligation.certificate_refs.clear()
    missing = verify(state, frozen)
    assert ClaimVerificationFailure.MISSING_NUMERIC_CERTIFICATE in missing.failure_codes


def test_unresolved_fallback_requires_forced_low_confidence_control():
    state, frozen = mixed_state()
    rule_obligation = next(
        item for item in state.obligations if item.type.value == "rule_applicability"
    )
    rule_obligation.status = "partial"
    state.forced_finalization = True
    state.phase = QuestionPhase.FINALIZATION

    incomplete = verify(
        state,
        frozen,
        evidence_ids=(),
        confidence="low",
        risk_flags=("unresolved_obligation",),
        allow_fallback=True,
    )
    assert incomplete.result is ClaimVerificationResult.INCOMPLETE
    assert incomplete.fallback_controls_passed is True
    assert incomplete.unresolved_obligation_ids == [rule_obligation.obligation_id]

    high_confidence = verify(
        state,
        frozen,
        evidence_ids=(),
        confidence="high",
        risk_flags=("unresolved_obligation",),
        allow_fallback=True,
    )
    assert high_confidence.result is ClaimVerificationResult.FAILED
    assert ClaimVerificationFailure.FALLBACK_CONTROL_REQUIRED in (
        high_confidence.failure_codes
    )
