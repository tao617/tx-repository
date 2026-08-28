"""Code-owned immutable Skill Registry for FinOASIS protocol v3.

The Registry is deliberately assembled from explicit imports.  Configuration may
select a subset of these entries, but it cannot add implementations or replace an
argument schema at runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from types import MappingProxyType

from .actions import (
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
from .contracts import ObligationType, SkillContract, SkillName


_CONTRACTS = (
    SkillContract(
        name=SkillName.SEARCH_REPORT,
        argument_model=SearchReportArguments,
        target_obligation_types=(
            ObligationType.DOCUMENT_FACT,
            ObligationType.TABLE_CELL,
            ObligationType.NUMERIC_OPERAND,
            ObligationType.UNIT_PERIOD,
            ObligationType.DOMAIN_RULE,
            ObligationType.EVIDENCE_CONFLICT,
        ),
        preconditions=("An unresolved report-evidence obligation exists.",),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=False,
        availability_reason="An active obligation can be advanced by report search.",
        unavailable_reason="No active obligation needs report search.",
    ),
    SkillContract(
        name=SkillName.READ_PARAGRAPHS,
        argument_model=ReadParagraphsArguments,
        target_obligation_types=(
            ObligationType.DOCUMENT_FACT,
            ObligationType.NUMERIC_OPERAND,
            ObligationType.UNIT_PERIOD,
            ObligationType.DOMAIN_RULE,
            ObligationType.EVIDENCE_CONFLICT,
        ),
        preconditions=(
            "An unresolved report-evidence obligation exists.",
            "Report search returned paragraph candidates.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=False,
        availability_reason="Unread search candidates can enter the evidence ledger.",
        unavailable_reason="No unread paragraph candidate is available.",
    ),
    SkillContract(
        name=SkillName.READ_TABLE_REGION,
        argument_model=ReadTableRegionArguments,
        target_obligation_types=(
            ObligationType.TABLE_CELL,
            ObligationType.NUMERIC_OPERAND,
            ObligationType.UNIT_PERIOD,
            ObligationType.EVIDENCE_CONFLICT,
        ),
        preconditions=(
            "An unresolved table-backed obligation exists.",
            "The report exposes a structurally valid table candidate.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=False,
        availability_reason="A table candidate can be read for the active obligation.",
        unavailable_reason="No structurally valid table candidate is available.",
    ),
    SkillContract(
        name=SkillName.BIND_FINANCIAL_VALUE,
        argument_model=BindFinancialValueArguments,
        target_obligation_types=(
            ObligationType.NUMERIC_OPERAND,
            ObligationType.UNIT_PERIOD,
        ),
        preconditions=(
            "A numeric operand or unit-period obligation is active.",
            "Exact report paragraph or table-cell evidence has been read.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=False,
        availability_reason="Read report evidence can be bound as a financial value.",
        unavailable_reason="No read report evidence is available for value binding.",
    ),
    SkillContract(
        name=SkillName.EXECUTE_FINANCIAL_PROGRAM,
        argument_model=ExecuteFinancialProgramArguments,
        target_obligation_types=(ObligationType.NUMERIC_OPERATION,),
        preconditions=(
            "A numeric-operation obligation is active.",
            "Every prospective operand is evidence-bound with valid metadata.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=True,
        availability_reason="Evidence-bound operands are ready for FinDSL execution.",
        unavailable_reason="No complete evidence-bound operand set is ready.",
    ),
    SkillContract(
        name=SkillName.SEARCH_FINANCIAL_RULES,
        argument_model=SearchFinancialRulesArguments,
        target_obligation_types=(ObligationType.DOMAIN_RULE,),
        preconditions=(
            "A domain-rule obligation is active.",
            "The configured frozen rule corpus passed identity validation.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=False,
        availability_reason="The verified frozen corpus can answer a rule search.",
        unavailable_reason=(
            "No valid frozen rule corpus or domain-rule gap is available."
        ),
    ),
    SkillContract(
        name=SkillName.READ_FINANCIAL_RULES,
        argument_model=ReadFinancialRulesArguments,
        target_obligation_types=(ObligationType.DOMAIN_RULE,),
        preconditions=(
            "A domain-rule obligation is active.",
            "Verified rule search returned candidate IDs.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=False,
        availability_reason="Rule candidates can be read into the rule ledger.",
        unavailable_reason="No verified rule candidate is available to read.",
    ),
    SkillContract(
        name=SkillName.CHECK_RULE_APPLICABILITY,
        argument_model=CheckRuleApplicabilityArguments,
        target_obligation_types=(ObligationType.RULE_APPLICABILITY,),
        preconditions=(
            "A rule-applicability obligation is active.",
            "Read rule and document evidence plus scope metadata are available.",
        ),
        maximum_calls=32,
        deterministic=True,
        produces_certificate=True,
        availability_reason="Rule, document, and scope inputs are ready for checking.",
        unavailable_reason="Applicability evidence or scope metadata is incomplete.",
    ),
    SkillContract(
        name=SkillName.SUBMIT_ANSWER,
        argument_model=SubmitAnswerArguments,
        target_obligation_types=(ObligationType.FINAL_VERIFICATION,),
        preconditions=(
            "A final-verification obligation is active.",
            "All mandatory obligations are satisfied, or budget fallback is active.",
        ),
        maximum_calls=8,
        deterministic=True,
        produces_certificate=True,
        availability_reason="The claim is ready for deterministic submission checks.",
        unavailable_reason="Mandatory proof obligations remain unresolved.",
    ),
)

if {contract.name for contract in _CONTRACTS} != set(SkillName):
    raise RuntimeError(
        "the protocol-v3 Skill Registry must define every Skill exactly once"
    )


SKILL_REGISTRY: Mapping[SkillName, SkillContract] = MappingProxyType(
    {contract.name: contract for contract in _CONTRACTS}
)
SKILL_CONTRACTS: tuple[SkillContract, ...] = _CONTRACTS


def _registry_payload() -> list[dict[str, object]]:
    return [
        {
            "name": contract.name.value,
            "argument_model": contract.argument_model.__name__,
            "argument_schema": contract.argument_model.model_json_schema(),
            "target_obligation_types": [
                obligation_type.value
                for obligation_type in contract.target_obligation_types
            ],
            "preconditions": list(contract.preconditions),
            "maximum_calls": contract.maximum_calls,
            "deterministic": contract.deterministic,
            "produces_certificate": contract.produces_certificate,
            "availability_reason": contract.availability_reason,
            "unavailable_reason": contract.unavailable_reason,
        }
        for contract in _CONTRACTS
    ]


REGISTRY_SHA256 = hashlib.sha256(
    json.dumps(
        _registry_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


class SkillRegistry(Mapping[SkillName, SkillContract]):
    """Read-only mapping facade over the sole code-owned Registry."""

    __slots__ = ()

    def __getitem__(self, name: SkillName | str) -> SkillContract:
        return SKILL_REGISTRY[SkillName(name)]

    def __iter__(self) -> Iterator[SkillName]:
        return iter(SKILL_REGISTRY)

    def __len__(self) -> int:
        return len(SKILL_REGISTRY)

    @property
    def sha256(self) -> str:
        return REGISTRY_SHA256


REGISTRY = SkillRegistry()


def get_skill_contract(name: SkillName | str) -> SkillContract:
    """Return one immutable contract, rejecting names outside the closed enum."""

    return REGISTRY[name]


def get_skill_registry() -> SkillRegistry:
    """Return the immutable singleton Registry."""

    return REGISTRY


__all__ = [
    "REGISTRY",
    "REGISTRY_SHA256",
    "SKILL_CONTRACTS",
    "SKILL_REGISTRY",
    "SkillRegistry",
    "get_skill_contract",
    "get_skill_registry",
]
