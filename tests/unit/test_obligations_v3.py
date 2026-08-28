import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from findver_agent.findoasis.contracts import (
    MAX_SKILL_RESULT_BYTES,
    OBLIGATION_DELTA_ADAPTER,
    OperandSlot,
    Obligation,
    ObligationMetadata,
    ObligationProposal,
    ObligationStatus,
    ObligationType,
    QuestionPhase,
    SkillContract,
    SkillName,
    SkillResult,
    SkillResultStatus,
)


def test_obligation_types_and_statuses_are_closed_typed_sets():
    assert {item.value for item in ObligationType} == {
        "document_fact",
        "table_cell",
        "numeric_operand",
        "numeric_operation",
        "unit_period",
        "domain_rule",
        "rule_applicability",
        "evidence_conflict",
        "final_verification",
    }
    assert {item.value for item in ObligationStatus} == {
        "pending",
        "partial",
        "satisfied",
        "conflicting",
        "blocked",
    }


def test_obligation_is_strict_bounded_and_satisfaction_needs_a_reference():
    common = {
        "obligation_id": "obl-0001",
        "type": "document_fact",
        "description": "Read the filing fact that supports the claim.",
        "created_phase": "initialization",
        "created_step": 0,
        "updated_phase": "initialization",
        "updated_step": 0,
    }
    with pytest.raises(ValidationError, match="requires evidence or a certificate"):
        Obligation(**common, status="satisfied")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Obligation(**common, model_note="trust me")
    with pytest.raises(ValidationError):
        Obligation(**{**common, "description": "x" * 601})

    obligation = Obligation(**common, status="satisfied", evidence_refs=["ev-1"])
    assert obligation.status is ObligationStatus.SATISFIED


def test_model_obligation_proposal_has_no_runtime_fields_or_satisfaction_escape():
    proposal = ObligationProposal(
        type="numeric_operand",
        description="Bind both report values used in the comparison.",
        metadata=ObligationMetadata(
            operand_slots=[OperandSlot(slot_id="revenue-2024", period="FY2024")]
        ),
    )
    assert "obligation_id" not in proposal.model_dump()
    assert "status" not in proposal.model_dump()

    with pytest.raises(ValidationError, match="require operand slots"):
        ObligationProposal(
            type="numeric_operand",
            description="Bind an unspecified collection of values.",
        )

    with pytest.raises(ValidationError):
        ObligationProposal.model_validate(
            {
                "type": "numeric_operand",
                "description": "Bind the values.",
                "status": "satisfied",
            }
        )
    with pytest.raises(ValidationError):
        OBLIGATION_DELTA_ADAPTER.validate_python(
            {"operation": "mark_satisfied", "obligation_id": "obl-0001"}
        )


def test_skill_result_is_strict_disjoint_and_requires_target_effect():
    valid = SkillResult(
        status="partial",
        target_obligation_id="obl-0001",
        partial_obligation_ids=["obl-0001"],
        evidence_refs=["ev-1"],
        diagnostics=["A second period still needs to be bound."],
    )
    assert valid.status is SkillResultStatus.PARTIAL
    assert len(valid.model_dump_json().encode()) < MAX_SKILL_RESULT_BYTES

    with pytest.raises(ValidationError, match="must affect its target"):
        SkillResult(
            status="partial",
            target_obligation_id="obl-0001",
            partial_obligation_ids=["obl-0002"],
        )
    with pytest.raises(ValidationError, match="must be disjoint"):
        SkillResult(
            status="satisfied",
            target_obligation_id="obl-0001",
            satisfied_obligation_ids=["obl-0001"],
            partial_obligation_ids=["obl-0001"],
            evidence_refs=["ev-1"],
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SkillResult(
            status="invalid",
            target_obligation_id="obl-0001",
            report_body="copied filing",
        )
    with pytest.raises(ValidationError, match="cannot mutate"):
        SkillResult(
            status="invalid",
            target_obligation_id="obl-0001",
            spawned_obligations=[
                {
                    "type": "document_fact",
                    "description": "This cannot be opened from an invalid result.",
                }
            ],
        )
    with pytest.raises(ValidationError):
        SkillResult(
            status="invalid",
            target_obligation_id="obl-0001",
            diagnostics=["x" * 501],
        )


def test_oversized_skill_result_fails_the_complete_serialized_bound():
    proposals = []
    for proposal_index in range(8):
        diagnostics = [
            f"{proposal_index}-{diagnostic_index}-".ljust(500, "x")
            for diagnostic_index in range(8)
        ]
        proposals.append(
            {
                "type": "document_fact",
                "description": f"bounded proposal {proposal_index}".ljust(600, "x"),
                "diagnostics": diagnostics,
            }
        )

    with pytest.raises(ValidationError, match="serialized size limit"):
        SkillResult(
            status="partial",
            target_obligation_id="obl-0001",
            partial_obligation_ids=["obl-0001"],
            spawned_obligations=proposals,
        )


def test_skill_contract_binds_a_strict_argument_model_and_is_immutable():
    class Arguments(BaseModel):
        model_config = ConfigDict(extra="forbid")
        query: str

    contract = SkillContract(
        name=SkillName.SEARCH_REPORT,
        argument_model=Arguments,
        target_obligation_types=(ObligationType.DOCUMENT_FACT,),
        preconditions=("An active report-fact gap exists.",),
        maximum_calls=4,
        deterministic=True,
        produces_certificate=False,
        availability_reason="A document fact is pending.",
        unavailable_reason="No document fact is active.",
    )
    with pytest.raises(ValidationError):
        contract.maximum_calls = 10
    with pytest.raises(ValidationError):
        SkillContract.model_validate({**contract.model_dump(), "unexpected": True})


def test_obligation_rejects_self_dependency_and_duplicate_references():
    common = {
        "obligation_id": "obl-0001",
        "type": "document_fact",
        "description": "Find the exact report fact.",
        "created_phase": QuestionPhase.EXPLORATION,
        "created_step": 1,
        "updated_phase": QuestionPhase.EXPLORATION,
        "updated_step": 1,
    }
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        Obligation(**common, dependency_ids=["obl-0001"])
    with pytest.raises(ValidationError, match="unique"):
        Obligation(**common, evidence_refs=["ev-1", "ev-1"])
