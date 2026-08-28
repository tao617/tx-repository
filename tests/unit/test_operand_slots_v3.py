from types import SimpleNamespace

import pytest

from findver_agent.financial_dsl.executor import execute_financial_program
from findver_agent.financial_dsl.models import (
    ClaimRelation,
    ClaimValueRef,
    FinancialProgram,
)
from findver_agent.findoasis.agent import FinOASISAgent
from findver_agent.findoasis.contracts import (
    OperandSlot,
    ObligationMetadata,
    ObligationProposal,
)
from findver_agent.findoasis.operand_slots import match_operand_slots
from findver_agent.findoasis.state import (
    FinOASISQuestionState,
    NumericValueLedgerEntry,
    ResumeIdentity,
)
from findver_agent.schemas import PublicTask
from findver_agent.skills.base import SkillError


def value(reference: str, number: str, *, metric: str, period: str):
    return SimpleNamespace(
        value_id=reference,
        evidence_ref=f"evidence:{reference}",
        normalized_value=number,
        numeric_type="money",
        currency="USD",
        unit="USD",
        scale="one",
        period=period,
        entity="issuer",
        metric=metric,
        ambiguity_flags=[],
    )


def ledger_value(reference: str, number: str, *, metric: str, period: str):
    return NumericValueLedgerEntry(
        value_id=reference,
        evidence_ref=f"evidence:{reference}",
        raw_value=number,
        normalized_value=number,
        numeric_type="money",
        currency="USD",
        unit="USD",
        scale="one",
        period=period,
        entity="issuer",
        metric=metric,
        paragraph_id=0,
        text_span_start=0,
        text_span_end=len(number),
    )


def test_slots_require_one_distinct_matching_value_per_declared_operand():
    slots = [
        OperandSlot(slot_id=f"slot-{index}", metric="revenue", period="FY2024")
        for index in range(1, 4)
    ]
    values = {
        f"value-{index:04d}": value(
            f"value-{index:04d}", str(index * 10), metric="Revenue", period="2024"
        )
        for index in range(1, 4)
    }

    assert match_operand_slots(slots, dict(list(values.items())[:2])) is None
    assert match_operand_slots(slots, values) == {
        "slot-1": "value-0001",
        "slot-2": "value-0002",
        "slot-3": "value-0003",
    }


def test_explicit_metric_and_period_constraints_reject_unrelated_values():
    slots = [
        OperandSlot(slot_id="revenue-2024", metric="revenue", period="FY2024"),
        OperandSlot(slot_id="income-2023", metric="net income", period="FY2023"),
    ]
    wrong = {
        "value-0001": value("value-0001", "120", metric="Revenue", period="2024"),
        "value-0002": value("value-0002", "90", metric="Revenue", period="2023"),
    }
    correct = {
        **wrong,
        "value-0003": value(
            "value-0003", "25", metric="Net Income", period="2023"
        ),
    }

    assert match_operand_slots(slots, wrong) is None
    assert match_operand_slots(slots, correct) == {
        "revenue-2024": "value-0001",
        "income-2023": "value-0003",
    }


def test_program_must_use_required_slots_and_cannot_use_global_unattached_value():
    task = PublicTask(
        example_id="operand-program-scope",
        statement="Three report values are summed.",
        report="report.json",
    )
    identity = ResumeIdentity.create(
        task,
        report_sha256="1" * 64,
        config_sha256="2" * 64,
        registry_sha256="3" * 64,
        obligation_policy_sha256="4" * 64,
    )
    state = FinOASISQuestionState.create(task, identity, max_steps=4)
    slots = [OperandSlot(slot_id=f"slot-{index}") for index in range(1, 4)]
    operand = state.open_obligation(
        ObligationProposal(
            type="numeric_operand",
            description="Bind all three required report values.",
            metadata=ObligationMetadata(operand_slots=slots),
        )
    )
    operation = state.open_obligation(
        ObligationProposal(
            type="numeric_operation",
            description="Execute the three-value program.",
            dependency_ids=[operand.obligation_id],
        )
    )
    for index in range(1, 5):
        reference = f"value-{index:04d}"
        state.numeric_value_ledger[reference] = ledger_value(
            reference,
            str(index * 10),
            metric=f"metric {index}",
            period="FY2024",
        )
    state.obligation(operand.obligation_id).evidence_refs = [
        "value-0001",
        "value-0002",
        "value-0003",
    ]

    FinOASISAgent._validate_program_operand_refs(
        state, operation, ["value-0001", "value-0002", "value-0003"]
    )
    with pytest.raises(SkillError, match="does not consume every required"):
        FinOASISAgent._validate_program_operand_refs(
            state, operation, ["value-0001", "value-0002"]
        )
    with pytest.raises(SkillError, match="outside its operand dependencies"):
        FinOASISAgent._validate_program_operand_refs(
            state,
            operation,
            ["value-0001", "value-0002", "value-0003", "value-0004"],
        )


@pytest.mark.parametrize(
    ("operator", "numbers", "expected"),
    [
        ("sum", ("10", "20", "30"), "60"),
        ("average", ("10", "20", "30"), "20"),
        ("within_range", ("20", "10", "30"), "true"),
    ],
)
def test_three_operand_programs_require_and_consume_three_slots(
    operator, numbers, expected
):
    slots = [OperandSlot(slot_id=f"slot-{index}") for index in range(1, 4)]
    values = {
        f"value-{index:04d}": value(
            f"value-{index:04d}", number, metric=f"metric {index}", period="FY2024"
        )
        for index, number in enumerate(numbers, start=1)
    }
    matched = match_operand_slots(slots, values)
    assert matched is not None
    program = FinancialProgram.model_validate(
        {
            "op": operator,
            "args": [
                {"kind": "value_ref", "ref": matched[slot.slot_id]}
                for slot in slots
            ],
        }
    )

    claims = {}
    relation = None
    if operator != "within_range":
        claims["claim-value-0001"] = ClaimValueRef(
            claim_value_id="claim-value-0001",
            raw_value=expected,
            normalized_value=expected,
            numeric_type="money",
            currency="USD",
            unit="USD",
            scale="one",
            relation="equals",
            source_span_start=0,
            source_span_end=len(expected),
        )
        relation = ClaimRelation(op="equals", claim_ref="claim-value-0001")
    execution = execute_financial_program(
        program,
        relation,
        values=values,
        claims=claims,
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )

    assert execution.certificate.result == expected
    assert [item.ref for item in execution.certificate.normalized_operands[:3]] == [
        "value-0001",
        "value-0002",
        "value-0003",
    ]
