from types import MappingProxyType

import pytest
from pydantic import ValidationError

from findver_agent.findoasis.actions import (
    BindFinancialValueArguments,
    CheckRuleApplicabilityArguments,
    ExecuteFinancialProgramArguments,
    ReadFinancialRulesArguments,
    ReadParagraphsArguments,
    ReadTableRegionArguments,
    SearchFinancialRulesArguments,
    SearchReportArguments,
    SubmitAnswerArguments,
)
from findver_agent.findoasis.contracts import SkillName
from findver_agent.findoasis.registry import (
    REGISTRY,
    REGISTRY_SHA256,
    SKILL_CONTRACTS,
    SKILL_REGISTRY,
    SkillRegistry,
    get_skill_contract,
    get_skill_registry,
)


EXPECTED_ARGUMENT_MODELS = {
    SkillName.SEARCH_REPORT: SearchReportArguments,
    SkillName.READ_PARAGRAPHS: ReadParagraphsArguments,
    SkillName.READ_TABLE_REGION: ReadTableRegionArguments,
    SkillName.BIND_FINANCIAL_VALUE: BindFinancialValueArguments,
    SkillName.EXECUTE_FINANCIAL_PROGRAM: ExecuteFinancialProgramArguments,
    SkillName.SEARCH_FINANCIAL_RULES: SearchFinancialRulesArguments,
    SkillName.READ_FINANCIAL_RULES: ReadFinancialRulesArguments,
    SkillName.CHECK_RULE_APPLICABILITY: CheckRuleApplicabilityArguments,
    SkillName.SUBMIT_ANSWER: SubmitAnswerArguments,
}


def test_registry_is_closed_complete_and_argument_models_are_existing_v3_models():
    assert isinstance(SKILL_REGISTRY, MappingProxyType)
    assert isinstance(REGISTRY, SkillRegistry)
    assert get_skill_registry() is REGISTRY
    assert len(REGISTRY) == len(SkillName) == 9
    assert set(REGISTRY) == set(SkillName)
    assert len(SKILL_CONTRACTS) == 9

    for name, argument_model in EXPECTED_ARGUMENT_MODELS.items():
        contract = get_skill_contract(name)
        assert contract.argument_model is argument_model
        assert contract.name is name


def test_registry_and_contracts_cannot_be_mutated_or_dynamically_registered():
    with pytest.raises(TypeError):
        SKILL_REGISTRY[SkillName.SEARCH_REPORT] = SKILL_REGISTRY[  # type: ignore[index]
            SkillName.READ_PARAGRAPHS
        ]
    with pytest.raises(ValidationError):
        REGISTRY[SkillName.SEARCH_REPORT].maximum_calls = 99
    assert not hasattr(REGISTRY, "register")


def test_registry_hash_is_stable_complete_sha256_and_unknown_names_fail_closed():
    assert len(REGISTRY_SHA256) == 64
    assert set(REGISTRY_SHA256) <= set("0123456789abcdef")
    assert REGISTRY.sha256 == REGISTRY_SHA256
    assert get_skill_contract("search_report").name is SkillName.SEARCH_REPORT
    with pytest.raises(ValueError):
        get_skill_contract("calculator")


def test_certificate_and_call_limit_metadata_is_explicit():
    certificate_skills = {
        contract.name for contract in SKILL_CONTRACTS if contract.produces_certificate
    }
    assert certificate_skills == {
        SkillName.EXECUTE_FINANCIAL_PROGRAM,
        SkillName.CHECK_RULE_APPLICABILITY,
        SkillName.SUBMIT_ANSWER,
    }
    assert all(contract.maximum_calls > 0 for contract in SKILL_CONTRACTS)
    assert all(contract.deterministic for contract in SKILL_CONTRACTS)
