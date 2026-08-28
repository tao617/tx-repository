"""Deterministic dynamic Skill availability for FinOASIS protocol v3."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from findver_agent.config import FinOasisConfig

from .contracts import (
    Obligation,
    ObligationId,
    ObligationStatus,
    ObligationType,
    QuestionPhase,
    ReferenceId,
    ShortText,
    SkillName,
)
from .operand_slots import match_operand_slots
from .registry import REGISTRY, SkillRegistry
from .state import FinOASISQuestionState


_ACTIVE_STATUSES = {
    ObligationStatus.PENDING,
    ObligationStatus.PARTIAL,
    ObligationStatus.CONFLICTING,
}
_UNKNOWN_METADATA = {"", "unknown", "unspecified", "n/a"}


class RuleApplicabilityMetadata(BaseModel):
    """Runtime-verified scope inputs, never model-derived arbitrary metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    jurisdiction: ShortText
    effective_date: str = Field(min_length=4, max_length=32)
    entity_scope: ShortText
    document_evidence_refs: tuple[ReferenceId, ...] = Field(
        default=(), max_length=20
    )

    @field_validator("document_evidence_refs")
    @classmethod
    def document_refs_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("document_evidence_refs must be unique")
        return value


class RuntimeFacts(BaseModel):
    """Small trusted snapshot of candidate and verifier state outside QuestionState."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    search_candidate_paragraph_ids: tuple[int, ...] = Field(
        default=(),
        max_length=100,
        validation_alias=AliasChoices(
            "search_candidate_paragraph_ids", "search_candidates"
        ),
    )
    read_paragraph_ids: tuple[int, ...] = Field(default=(), max_length=100)
    table_candidate_ids: tuple[ReferenceId, ...] = Field(
        default=(),
        max_length=64,
        validation_alias=AliasChoices("table_candidate_ids", "table_candidates"),
    )
    read_table_evidence_refs: tuple[ReferenceId, ...] = Field(
        default=(),
        max_length=128,
        validation_alias=AliasChoices(
            "read_table_evidence_refs", "read_table_refs"
        ),
    )
    bound_value_refs: tuple[ReferenceId, ...] = Field(
        default=(),
        max_length=64,
        validation_alias=AliasChoices("bound_value_refs", "bound_values"),
    )
    rule_corpus_valid: bool = False
    rule_candidate_ids: tuple[ReferenceId, ...] = Field(
        default=(),
        max_length=64,
        validation_alias=AliasChoices("rule_candidate_ids", "rule_candidates"),
    )
    read_rule_evidence_refs: tuple[ReferenceId, ...] = Field(
        default=(),
        max_length=64,
        validation_alias=AliasChoices("read_rule_evidence_refs", "read_rules"),
    )
    applicability_metadata: RuleApplicabilityMetadata | None = None
    budget_exhausted: bool = False
    repair_skill: SkillName | None = None

    @field_validator("search_candidate_paragraph_ids", "read_paragraph_ids")
    @classmethod
    def paragraph_ids_are_unique_nonnegative(
        cls, value: tuple[int, ...]
    ) -> tuple[int, ...]:
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("paragraph IDs must be non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("paragraph IDs must be unique")
        return value

    @field_validator(
        "table_candidate_ids",
        "read_table_evidence_refs",
        "bound_value_refs",
        "rule_candidate_ids",
        "read_rule_evidence_refs",
    )
    @classmethod
    def reference_tuples_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("RuntimeFacts references must be unique")
        return value

    @property
    def search_candidates(self) -> tuple[int, ...]:
        return self.search_candidate_paragraph_ids

    @property
    def table_candidates(self) -> tuple[str, ...]:
        return self.table_candidate_ids

    @property
    def bound_values(self) -> tuple[str, ...]:
        return self.bound_value_refs

    @property
    def rule_candidates(self) -> tuple[str, ...]:
        return self.rule_candidate_ids

    @property
    def read_rules(self) -> tuple[str, ...]:
        return self.read_rule_evidence_refs


class SkillAvailabilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    skill: SkillName
    available: bool
    reason: ShortText
    target_obligation_ids: tuple[ObligationId, ...] = Field(default=(), max_length=256)

    @field_validator("target_obligation_ids")
    @classmethod
    def target_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("target_obligation_ids must be unique")
        return value

    @model_validator(mode="after")
    def unavailable_decision_has_no_targets(self) -> "SkillAvailabilityDecision":
        if not self.available and self.target_obligation_ids:
            raise ValueError("an unavailable Skill cannot advertise target obligations")
        return self


class AvailabilityResolution(BaseModel):
    """Ordered available subset plus one bounded reason for every Registry entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decisions: tuple[SkillAvailabilityDecision, ...] = Field(
        min_length=9, max_length=9
    )

    @model_validator(mode="after")
    def decisions_cover_registry_once(self) -> "AvailabilityResolution":
        names = [decision.skill for decision in self.decisions]
        if len(names) != len(set(names)) or set(names) != set(REGISTRY):
            raise ValueError(
                "availability decisions must cover the static Registry once"
            )
        return self

    @property
    def available_skills(self) -> tuple[SkillName, ...]:
        return tuple(
            decision.skill for decision in self.decisions if decision.available
        )

    @property
    def unavailable_skills(self) -> tuple[SkillName, ...]:
        return tuple(
            decision.skill for decision in self.decisions if not decision.available
        )

    def decision_for(self, skill: SkillName | str) -> SkillAvailabilityDecision:
        name = SkillName(skill)
        return next(decision for decision in self.decisions if decision.skill is name)

    def reason_for(self, skill: SkillName | str) -> str:
        return self.decision_for(skill).reason

    def __contains__(self, skill: object) -> bool:
        try:
            name = SkillName(skill)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        return name in self.available_skills


class SkillAvailabilityResolver:
    """Resolve availability from the fixed Registry and trusted Runtime state."""

    __slots__ = ()

    @property
    def registry(self) -> SkillRegistry:
        return REGISTRY

    def resolve(
        self,
        state: FinOASISQuestionState,
        config: FinOasisConfig,
        facts: RuntimeFacts | None = None,
    ) -> AvailabilityResolution:
        facts = facts or RuntimeFacts()
        decisions = tuple(
            self._resolve_one(skill, state, config, facts) for skill in REGISTRY
        )
        return AvailabilityResolution(decisions=decisions)

    def _resolve_one(
        self,
        skill: SkillName,
        state: FinOASISQuestionState,
        config: FinOasisConfig,
        facts: RuntimeFacts,
    ) -> SkillAvailabilityDecision:
        contract = REGISTRY[skill]
        if state.phase is QuestionPhase.CLOSED:
            return self._unavailable(skill, "Question state is closed.")
        if skill.value not in config.enabled_skills:
            return self._unavailable(
                skill, "Skill is disabled by the configured allowlist."
            )

        configured_budget = getattr(config.skill_budgets, skill.value)
        used_calls = state.skill_call_counts.get(skill, 0)
        call_limit = min(configured_budget, contract.maximum_calls)
        if used_calls >= call_limit:
            return self._unavailable(
                skill, "The configured per-Skill budget is exhausted."
            )

        if facts.repair_skill is not None and skill is not facts.repair_skill:
            return self._unavailable(
                skill, "A bounded repair attempt exposes another Skill."
            )

        budget_exhausted = facts.budget_exhausted or state.remaining_steps == 0
        if (
            budget_exhausted
            and facts.repair_skill is None
            and skill is not SkillName.SUBMIT_ANSWER
        ):
            return self._unavailable(
                skill,
                "Only best-effort submission remains after budget exhaustion.",
            )

        matching = self._matching_active_obligations(
            state, contract.target_obligation_types
        )
        ready = tuple(
            obligation
            for obligation in matching
            if self._dependencies_satisfied(obligation, state)
        )
        eligible_targets = ready
        if skill is SkillName.SUBMIT_ANSWER and budget_exhausted and matching:
            # Best-effort finalization deliberately records unresolved dependencies;
            # it does not pretend that they became satisfied.
            eligible_targets = matching
        dynamic = config.obligation_policy.skill_exposure == "dynamic"
        if dynamic and not eligible_targets:
            if matching:
                return self._unavailable(
                    skill,
                    "Compatible obligations have unsatisfied dependencies.",
                )
            return self._unavailable(skill, contract.unavailable_reason)

        specific_reason = self._specific_precondition_failure(
            skill=skill,
            state=state,
            config=config,
            facts=facts,
            ready_targets=eligible_targets,
            budget_exhausted=budget_exhausted,
        )
        if specific_reason is not None:
            return self._unavailable(skill, specific_reason)

        if dynamic:
            reason = contract.availability_reason
        elif eligible_targets:
            reason = (
                f"{skill.value} is exposed by the always-exposed ablation; "
                "safety checks passed."
            )
        else:
            reason = (
                f"{skill.value} is exposed by ablation; hard safety checks passed."
            )
        return SkillAvailabilityDecision(
            skill=skill,
            available=True,
            reason=reason,
            target_obligation_ids=tuple(
                item.obligation_id for item in eligible_targets
            ),
        )

    def _specific_precondition_failure(
        self,
        *,
        skill: SkillName,
        state: FinOASISQuestionState,
        config: FinOasisConfig,
        facts: RuntimeFacts,
        ready_targets: tuple[Obligation, ...],
        budget_exhausted: bool,
    ) -> str | None:
        if skill is SkillName.READ_PARAGRAPHS:
            read_ids = set(facts.read_paragraph_ids)
            read_ids.update(
                entry.paragraph_id
                for entry in state.evidence_ledger.values()
                if entry.source == "report_paragraph"
            )
            if not set(facts.search_candidate_paragraph_ids) - read_ids:
                return "No unread paragraph candidate is available."

        elif skill is SkillName.READ_TABLE_REGION:
            if not facts.table_candidate_ids:
                return "No structurally valid table candidate is available."

        elif skill is SkillName.BIND_FINANCIAL_VALUE:
            if not self._read_report_evidence_refs(state, facts):
                return "No exact read report evidence is available for value binding."

        elif skill is SkillName.EXECUTE_FINANCIAL_PROGRAM:
            if not ready_targets:
                return "No ready numeric-operation obligation exists."
            if not self._bound_values_are_program_ready(state, facts, ready_targets):
                return "Evidence-bound operands lack complete unit or period metadata."

        elif skill in {
            SkillName.SEARCH_FINANCIAL_RULES,
            SkillName.READ_FINANCIAL_RULES,
            SkillName.CHECK_RULE_APPLICABILITY,
        }:
            if not config.rule_corpus.enabled or not facts.rule_corpus_valid:
                return "The configured frozen rule corpus has not passed validation."
            if skill is SkillName.READ_FINANCIAL_RULES and not facts.rule_candidate_ids:
                return "No verified rule candidate is available to read."
            if skill is SkillName.CHECK_RULE_APPLICABILITY:
                if not ready_targets:
                    return "No ready rule-applicability obligation exists."
                if not self._applicability_inputs_are_ready(state, facts):
                    return (
                        "Read rule, document, or scope applicability inputs "
                        "are incomplete."
                    )

        elif skill is SkillName.SUBMIT_ANSWER:
            if not ready_targets:
                return "No ready final-verification obligation exists."
            unresolved = [
                obligation
                for obligation in state.obligations
                if obligation.mandatory
                and obligation.type is not ObligationType.FINAL_VERIFICATION
                and obligation.status is not ObligationStatus.SATISFIED
            ]
            if unresolved and not budget_exhausted:
                return "Mandatory proof obligations remain unresolved."

        return None

    @staticmethod
    def _matching_active_obligations(
        state: FinOASISQuestionState,
        target_types: Iterable[ObligationType],
    ) -> tuple[Obligation, ...]:
        allowed = set(target_types)
        return tuple(
            obligation
            for obligation in state.obligations
            if obligation.type in allowed and obligation.status in _ACTIVE_STATUSES
        )

    @staticmethod
    def _dependencies_satisfied(
        obligation: Obligation, state: FinOASISQuestionState
    ) -> bool:
        return all(
            state.obligation(dependency_id).status is ObligationStatus.SATISFIED
            for dependency_id in obligation.dependency_ids
        )

    @staticmethod
    def _read_report_evidence_refs(
        state: FinOASISQuestionState, facts: RuntimeFacts
    ) -> set[str]:
        if set(facts.read_table_evidence_refs) - set(state.evidence_ledger):
            return set()
        return set(state.evidence_ledger)

    @staticmethod
    def _bound_values_are_program_ready(
        state: FinOASISQuestionState,
        facts: RuntimeFacts,
        ready_targets: tuple[Obligation, ...],
    ) -> bool:
        refs = set(facts.bound_value_refs or tuple(state.numeric_value_ledger))
        if not refs or refs - set(state.numeric_value_ledger):
            return False
        by_id = {
            obligation.obligation_id: obligation for obligation in state.obligations
        }
        for operation in ready_targets:
            operand_dependencies = [
                by_id[dependency_id]
                for dependency_id in operation.dependency_ids
                if by_id[dependency_id].type is ObligationType.NUMERIC_OPERAND
            ]
            for item in operand_dependencies:
                attached = set(item.evidence_refs) & refs
                values = {
                    reference: state.numeric_value_ledger[reference]
                    for reference in attached
                }
                matched = match_operand_slots(item.metadata.operand_slots, values)
                if matched is None:
                    return False
                for reference in matched.values():
                    value = state.numeric_value_ledger[reference]
                    if value.ambiguity_flags:
                        return False
                    if value.period.casefold() in _UNKNOWN_METADATA:
                        return False
                    if value.unit.casefold() in _UNKNOWN_METADATA:
                        return False
        return True

    @staticmethod
    def _applicability_inputs_are_ready(
        state: FinOASISQuestionState, facts: RuntimeFacts
    ) -> bool:
        metadata = facts.applicability_metadata
        if metadata is None:
            return False
        fields = (metadata.jurisdiction, metadata.effective_date, metadata.entity_scope)
        if any(value.casefold() in _UNKNOWN_METADATA for value in fields):
            return False

        rule_refs = set(
            facts.read_rule_evidence_refs or tuple(state.rule_evidence_ledger)
        )
        if not rule_refs or rule_refs - set(state.rule_evidence_ledger):
            return False
        document_refs = set(metadata.document_evidence_refs)
        if not document_refs:
            document_refs = set(state.evidence_ledger)
        if not document_refs or document_refs - set(state.evidence_ledger):
            return False
        return any(
            obligation.type is ObligationType.DOCUMENT_FACT
            and obligation.status is ObligationStatus.SATISFIED
            and bool(set(obligation.evidence_refs) & document_refs)
            for obligation in state.obligations
        )

    @staticmethod
    def _unavailable(skill: SkillName, reason: str) -> SkillAvailabilityDecision:
        return SkillAvailabilityDecision(skill=skill, available=False, reason=reason)


RESOLVER = SkillAvailabilityResolver()


def resolve_available_skills(
    state: FinOASISQuestionState,
    config: FinOasisConfig,
    facts: RuntimeFacts | None = None,
) -> AvailabilityResolution:
    """Resolve the currently exposed subset without mutating state or configuration."""

    return RESOLVER.resolve(state, config, facts)


resolve_skill_availability = resolve_available_skills
AvailabilityResolver = SkillAvailabilityResolver


__all__ = [
    "AvailabilityResolution",
    "AvailabilityResolver",
    "RESOLVER",
    "RuleApplicabilityMetadata",
    "RuntimeFacts",
    "SkillAvailabilityDecision",
    "SkillAvailabilityResolver",
    "resolve_available_skills",
    "resolve_skill_availability",
]
