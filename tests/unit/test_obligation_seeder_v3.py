import pytest

from findver_agent.findoasis.contracts import ObligationType
from findver_agent.findoasis.seeder import (
    ConservativeObligationSeeder,
    seed_obligations,
)
from findver_agent.findoasis.state import FinOASISQuestionState, ResumeIdentity
from findver_agent.schemas import PublicTask


def obligation_types(claim: str) -> list[ObligationType]:
    return [proposal.type for proposal in seed_obligations(claim)]


def test_ie_claim_seeds_only_document_fact_and_final_verification():
    proposals = seed_obligations(
        "The company opened a new distribution center in Shanghai."
    )

    assert [proposal.type for proposal in proposals] == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.FINAL_VERIFICATION,
    ]
    assert proposals[0].dependency_ids == []
    assert proposals[1].dependency_ids == ["obl-0001"]
    assert all(proposal.mandatory for proposal in proposals)


@pytest.mark.parametrize(
    "claim",
    [
        "Revenue increased to $120 million in 2024.",
        "The income tax expense was $12 million in 2024.",
        "The standard product warranty expense was $12 million in 2024.",
        "The company was required to repay $10 million by 2025.",
        "The rate was disclosed in the 10-K filed in 2024.",
        "Revenue increased on December 31, 2024.",
        "收入在2024年12月31日有所增长。",
        "Assets were 100 and liabilities were 80.",
        "The reports cover 2023 and 2024.",
    ],
)
def test_ambiguous_ie_wording_does_not_false_trigger_specialist_obligations(claim):
    assert obligation_types(claim) == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.FINAL_VERIFICATION,
    ]


def test_explicit_numeric_comparison_seeds_numeric_dependency_chain():
    proposals = seed_obligations(
        "Revenue increased from $100 million in 2022 to $120 million in 2023."
    )

    assert [proposal.type for proposal in proposals] == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.NUMERIC_OPERAND,
        ObligationType.UNIT_PERIOD,
        ObligationType.NUMERIC_OPERATION,
        ObligationType.FINAL_VERIFICATION,
    ]
    assert [proposal.dependency_ids for proposal in proposals] == [
        [],
        ["obl-0001"],
        ["obl-0002"],
        ["obl-0002", "obl-0003"],
        ["obl-0001", "obl-0004"],
    ]


def test_two_explicit_periods_can_seed_temporal_numeric_comparison():
    proposals = seed_obligations("Revenue was lower in 2023 than in 2024.")
    assert [proposal.type for proposal in proposals] == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.NUMERIC_OPERAND,
        ObligationType.UNIT_PERIOD,
        ObligationType.NUMERIC_OPERATION,
        ObligationType.FINAL_VERIFICATION,
    ]
    assert [
        (slot.metric, slot.period) for slot in proposals[1].metadata.operand_slots
    ] == [("revenue", "2023"), ("revenue", "2024")]


def test_single_report_value_plus_claim_threshold_seeds_one_typed_slot():
    proposals = seed_obligations("FY2024 operating margin was above 10%.")

    assert [proposal.type for proposal in proposals] == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.NUMERIC_OPERAND,
        ObligationType.UNIT_PERIOD,
        ObligationType.NUMERIC_OPERATION,
        ObligationType.FINAL_VERIFICATION,
    ]
    assert len(proposals[1].metadata.operand_slots) == 1
    slot = proposals[1].metadata.operand_slots[0]
    assert slot.slot_id == "operand-slot-0001"
    assert slot.metric == "operating margin"
    assert slot.period == "fy2024"

    assert ObligationType.NUMERIC_OPERAND in obligation_types(
        "Revenue was above 10 million."
    )


def test_rule_effective_date_does_not_create_an_extra_numeric_operand():
    proposals = seed_obligations(
        "Under GAAP on 2024-12-31, revenue was lower in 2023 than in 2024."
    )
    numeric = next(
        proposal
        for proposal in proposals
        if proposal.type is ObligationType.NUMERIC_OPERAND
    )

    assert [slot.period for slot in numeric.metadata.operand_slots] == ["2024", "2023"]


def test_chinese_numeric_comparison_is_not_missed():
    assert obligation_types("收入从2022年的100增长到2023年的120。") == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.NUMERIC_OPERAND,
        ObligationType.UNIT_PERIOD,
        ObligationType.NUMERIC_OPERATION,
        ObligationType.FINAL_VERIFICATION,
    ]


def test_single_quoted_result_is_intentionally_under_seeded_for_later_expansion():
    assert obligation_types("The operating margin was approximately 12%.") == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.FINAL_VERIFICATION,
    ]


def test_knowledge_claim_seeds_rule_and_applicability_without_numeric_path():
    proposals = seed_obligations(
        "Under GAAP, a qualifying lease is classified as a finance lease."
    )

    assert [proposal.type for proposal in proposals] == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
        ObligationType.FINAL_VERIFICATION,
    ]
    assert [proposal.dependency_ids for proposal in proposals] == [
        [],
        [],
        ["obl-0001", "obl-0002"],
        ["obl-0001", "obl-0003"],
    ]


def test_rule_scope_metadata_is_deterministic_and_unknowns_remain_explicit():
    scoped = seed_obligations(
        "Under US GAAP, a public issuer applied the rule on 2024-12-31."
    )
    domain_rule, applicability = scoped[1:3]
    assert domain_rule.metadata.expected_relation is None
    assert applicability.metadata.expected_relation == "applies"
    assert domain_rule.metadata.jurisdiction == "US"
    assert domain_rule.metadata.effective_date == "2024-12-31"
    assert domain_rule.metadata.entity_scope == "public issuer"

    unknowns = seed_obligations(
        "Under GAAP, a qualifying lease is classified as a finance lease."
    )[1].metadata
    assert unknowns.jurisdiction == "US"
    assert unknowns.effective_date == "unknown"
    assert unknowns.entity_scope == "unknown"


def test_negative_rule_claim_seeds_explicit_non_applicability_relation():
    proposals = seed_obligations(
        "Under US GAAP, the stated rule does not apply to the public issuer."
    )
    applicability = next(
        proposal
        for proposal in proposals
        if proposal.type is ObligationType.RULE_APPLICABILITY
    )

    assert applicability.metadata.expected_relation == "does_not_apply"


def test_chinese_rule_signal_seeds_knowledge_obligations():
    assert obligation_types(
        "根据《企业会计准则》，满足定义条件的租赁应当确认为使用权资产。"
    ) == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
        ObligationType.FINAL_VERIFICATION,
    ]


def test_named_regulation_is_a_strong_knowledge_signal():
    assert obligation_types("Regulation S-K requires the stated disclosure.") == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
        ObligationType.FINAL_VERIFICATION,
    ]


def test_financial_definition_is_a_strong_knowledge_signal():
    assert obligation_types(
        "A current asset is defined as an asset expected to be realized soon."
    ) == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
        ObligationType.FINAL_VERIFICATION,
    ]


def test_mixed_claim_has_both_certificate_families_and_joined_final_dependency():
    proposals = seed_obligations(
        "Under GAAP, the margin increase from 20% in 2022 to 25% in 2023 "
        "qualifies for the stated accounting treatment."
    )

    assert [proposal.type for proposal in proposals] == [
        ObligationType.DOCUMENT_FACT,
        ObligationType.NUMERIC_OPERAND,
        ObligationType.UNIT_PERIOD,
        ObligationType.NUMERIC_OPERATION,
        ObligationType.DOMAIN_RULE,
        ObligationType.RULE_APPLICABILITY,
        ObligationType.FINAL_VERIFICATION,
    ]
    assert proposals[-1].dependency_ids == ["obl-0001", "obl-0004", "obl-0006"]


def test_negation_does_not_make_the_seeder_predict_a_label():
    positive = obligation_types("Revenue increased from 100 in 2023 to 125 in 2024.")
    negated = obligation_types(
        "Revenue did not increase from 100 in 2023 to 125 in 2024."
    )

    assert positive == negated


def test_seed_sequence_is_deterministic_and_contains_no_runtime_owned_id():
    claim = "Revenue increased from 100 in 2023 to 125 in 2024 under IFRS."
    seeder = ConservativeObligationSeeder()

    first = seeder.seed(claim)
    second = seeder.seed(claim)

    assert first == second
    assert isinstance(first, tuple)
    assert all("obligation_id" not in proposal.model_dump() for proposal in first)
    for sequence, proposal in enumerate(first, start=1):
        assert all(
            int(dependency.removeprefix("obl-")) < sequence
            for dependency in proposal.dependency_ids
        )


def test_seed_dependencies_are_valid_when_runtime_opens_into_a_fresh_graph():
    # Integration must assert this exact precondition before allocating IDs.
    task = PublicTask(
        example_id="public-example",
        statement="Revenue increased from 100 in 2023 to 125 in 2024 under IFRS.",
        report="report.json",
    )
    identity = ResumeIdentity.create(
        task,
        report_sha256="1" * 64,
        config_sha256="2" * 64,
        registry_sha256="3" * 64,
        obligation_policy_sha256="4" * 64,
    )
    state = FinOASISQuestionState.create(task, identity, max_steps=8)
    assert state.obligations == []
    assert state.next_obligation_sequence == 1

    proposals = seed_obligations(
        task.statement
    )
    allocated = [state.open_obligation(proposal) for proposal in proposals]

    assert [obligation.obligation_id for obligation in allocated] == [
        f"obl-{sequence:04d}" for sequence in range(1, len(proposals) + 1)
    ]
    assert state.next_obligation_sequence == len(proposals) + 1


@pytest.mark.parametrize("claim", ["", "   ", "\n\t"])
def test_empty_claim_is_rejected(claim):
    with pytest.raises(ValueError, match="must not be empty"):
        seed_obligations(claim)


def test_non_string_claim_is_rejected_without_inspecting_other_task_fields():
    with pytest.raises(TypeError, match="must be a string"):
        seed_obligations({"statement": "Revenue increased.", "subset": "numeric"})
