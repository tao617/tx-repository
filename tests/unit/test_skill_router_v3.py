import hashlib
from pathlib import Path

from findver_agent.config import FinOasisConfig
from findver_agent.financial_rules.corpus import rule_record_sha256
from findver_agent.financial_rules.models import RuleRecord
from findver_agent.findoasis.contracts import (
    OperandSlot,
    ObligationMetadata,
    ObligationProposal,
    QuestionPhase,
    SkillName,
    SkillResult,
)
from findver_agent.findoasis.router import (
    RuleApplicabilityMetadata,
    RuntimeFacts,
    resolve_available_skills,
)
from findver_agent.findoasis.state import (
    EvidenceLedgerEntry,
    FinOASISQuestionState,
    NumericValueLedgerEntry,
    ResumeIdentity,
    RuleEvidenceLedgerEntry,
)
from findver_agent.schemas import PublicTask


EVIDENCE_TEXT = "Revenue was 128.4 in FY2024. Operating margin was 12.5%."
HASH = hashlib.sha256(EVIDENCE_TEXT.encode()).hexdigest()
ALL_SKILLS = tuple(skill.value for skill in SkillName)


def _config(
    enabled=ALL_SKILLS,
    *,
    exposure="dynamic",
    budgets=None,
):
    enabled = tuple(enabled)
    values = {
        "experimental": True,
        "official_test_authorized": False,
        "real_model_execution_authorized": False,
        "scorer_handoff_authorized": False,
        "enabled_skills": enabled,
        "skill_budgets": {
            skill.value: (4 if skill.value in enabled else 0) for skill in SkillName
        },
        "obligation_policy": {
            "seeding": "conservative",
            "skill_exposure": exposure,
            "model_may_open_obligations": True,
            "model_may_satisfy_obligations": False,
            "model_may_waive_mandatory": False,
            "normal_submit_requires_all_mandatory": True,
            "budget_exhausted_submit": "low_confidence_best_effort",
        },
        "rule_corpus": {
            "enabled": bool(
                {
                    "search_financial_rules",
                    "read_financial_rules",
                    "check_rule_applicability",
                }
                & set(enabled)
            ),
            "read_only": True,
            "network_fallback": False,
        },
    }
    if values["rule_corpus"]["enabled"]:
        values["rule_corpus"].update(
            {
                "rule_root": Path("/rules/frozen"),
                "manifest_path": Path("manifest.json"),
                "records_path": Path("records.jsonl"),
                "corpus_id": "synthetic-v1",
                "manifest_sha256": "b" * 64,
                "records_sha256": "c" * 64,
            }
        )
    if budgets:
        values["skill_budgets"].update(budgets)
    return FinOasisConfig.model_validate(values)


def _state(statement="Revenue increased."):
    task = PublicTask(example_id="example-1", statement=statement, report="report.json")
    identity = ResumeIdentity.create(
        task,
        report_sha256="1" * 64,
        config_sha256="2" * 64,
        registry_sha256="3" * 64,
        obligation_policy_sha256="4" * 64,
    )
    state = FinOASISQuestionState.create(task, identity, max_steps=8)
    state.phase = QuestionPhase.EXPLORATION
    return state


def _open(state, obligation_type, *, dependencies=(), mandatory=True, metadata=None):
    if obligation_type == "numeric_operand" and metadata is None:
        metadata = ObligationMetadata(
            operand_slots=[
                OperandSlot(
                    slot_id="operating-margin-2024",
                    metric="operating margin",
                    period="FY2024",
                )
            ]
        )
    return state.open_obligation(
        ObligationProposal(
            type=obligation_type,
            description=f"Resolve the {obligation_type} proof requirement.",
            dependency_ids=list(dependencies),
            mandatory=mandatory,
            metadata=metadata or ObligationMetadata(),
        )
    )


def _add_paragraph_evidence(state, evidence_id="ev-1", paragraph_id=3):
    state.evidence_ledger[evidence_id] = EvidenceLedgerEntry(
        evidence_id=evidence_id,
        source="report_paragraph",
        paragraph_id=paragraph_id,
        exact_text=EVIDENCE_TEXT,
        exact_text_sha256=HASH,
    )


def test_ie_routes_only_report_skills_and_requires_candidates_before_read():
    state = _state()
    fact = _open(state, "document_fact")
    _open(state, "final_verification", dependencies=(fact.obligation_id,))

    initial = resolve_available_skills(
        state, _config(), RuntimeFacts(rule_corpus_valid=True)
    )
    assert initial.available_skills == (SkillName.SEARCH_REPORT,)
    assert "numeric" not in " ".join(skill.value for skill in initial.available_skills)

    after_search = resolve_available_skills(
        state,
        _config(),
        RuntimeFacts(
            search_candidate_paragraph_ids=(2, 3),
            rule_corpus_valid=True,
        ),
    )
    assert after_search.available_skills == (
        SkillName.SEARCH_REPORT,
        SkillName.READ_PARAGRAPHS,
    )
    assert not {
        SkillName.BIND_FINANCIAL_VALUE,
        SkillName.EXECUTE_FINANCIAL_PROGRAM,
        SkillName.SEARCH_FINANCIAL_RULES,
    } & set(after_search.available_skills)


def test_numeric_program_stays_hidden_until_operands_are_evidence_bound():
    state = _state("Operating margin increased by two percentage points.")
    operand = _open(state, "numeric_operand")
    operation = _open(
        state, "numeric_operation", dependencies=(operand.obligation_id,)
    )
    _add_paragraph_evidence(state)

    before_binding = resolve_available_skills(state, _config(), RuntimeFacts())
    assert SkillName.BIND_FINANCIAL_VALUE in before_binding
    assert SkillName.EXECUTE_FINANCIAL_PROGRAM not in before_binding

    state.numeric_value_ledger["value-0001"] = NumericValueLedgerEntry(
        value_id="value-0001",
        evidence_ref="ev-1",
        raw_value="12.5%",
        normalized_value="12.5",
        numeric_type="percentage",
        currency="unknown",
        unit="percentage_points",
        scale="1",
        period="FY2024",
        entity="issuer",
        metric="operating margin",
        paragraph_id=3,
        text_span_start=EVIDENCE_TEXT.index("12.5%"),
        text_span_end=EVIDENCE_TEXT.index("12.5%") + len("12.5%"),
    )
    state.next_value_sequence = 2
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=operand.obligation_id,
            satisfied_obligation_ids=[operand.obligation_id],
            evidence_refs=["value-0001"],
        )
    )
    after_binding = resolve_available_skills(
        state,
        _config(),
        RuntimeFacts(bound_value_refs=("value-0001",)),
    )
    decision = after_binding.decision_for("execute_financial_program")
    assert decision.available is True
    assert decision.target_obligation_ids == (operation.obligation_id,)

    state.numeric_value_ledger["value-0001"] = state.numeric_value_ledger[
        "value-0001"
    ].model_copy(update={"ambiguity_flags": ["period_conflict"]})
    ambiguous = resolve_available_skills(
        state,
        _config(),
        RuntimeFacts(bound_value_refs=("value-0001",)),
    )
    assert SkillName.EXECUTE_FINANCIAL_PROGRAM not in ambiguous


def test_knowledge_skills_fail_closed_without_valid_corpus_then_open_in_order():
    state = _state("The issuer was required to apply the stated recognition rule.")
    document = _open(state, "document_fact")
    domain = _open(state, "domain_rule")
    applicability = _open(
        state,
        "rule_applicability",
        dependencies=(document.obligation_id, domain.obligation_id),
    )

    no_rule_config = _config(
        enabled=("search_report", "read_paragraphs", "submit_answer")
    )
    assert SkillName.SEARCH_FINANCIAL_RULES not in resolve_available_skills(
        state, no_rule_config, RuntimeFacts(rule_corpus_valid=True)
    )

    invalid_corpus = resolve_available_skills(state, _config(), RuntimeFacts())
    assert SkillName.SEARCH_FINANCIAL_RULES not in invalid_corpus
    assert "not passed validation" in invalid_corpus.reason_for(
        SkillName.SEARCH_FINANCIAL_RULES
    )

    valid_corpus = resolve_available_skills(
        state, _config(), RuntimeFacts(rule_corpus_valid=True)
    )
    assert SkillName.SEARCH_FINANCIAL_RULES in valid_corpus
    assert SkillName.READ_FINANCIAL_RULES not in valid_corpus

    candidates = resolve_available_skills(
        state,
        _config(),
        RuntimeFacts(rule_corpus_valid=True, rule_candidate_ids=("rule-1",)),
    )
    assert SkillName.READ_FINANCIAL_RULES in candidates
    assert SkillName.CHECK_RULE_APPLICABILITY not in candidates

    _add_paragraph_evidence(state)
    state.resume_identity = state.resume_identity.model_copy(
        update={
            "rule_corpus_id": "synthetic-v1",
            "rule_manifest_sha256": "b" * 64,
            "rule_records_sha256": "c" * 64,
        }
    )
    rule_text = "Synthetic rule text."
    rule = RuleRecord(
        rule_id="rule-1",
        title="Synthetic rule",
        text=rule_text,
        jurisdiction="US",
        entity_scope="public issuer",
        topic="recognition",
        effective_from="2020-01-01",
        source_reference="synthetic://rule-1",
        source_sha256=hashlib.sha256(rule_text.encode()).hexdigest(),
    )
    state.rule_evidence_ledger["rule-evidence-0001"] = RuleEvidenceLedgerEntry(
        rule_evidence_id="rule-evidence-0001",
        rule_id="rule-1",
        rule_sha256=rule_record_sha256(rule),
        corpus_id="synthetic-v1",
        manifest_sha256="b" * 64,
        records_sha256="c" * 64,
        record=rule,
    )
    state.next_rule_evidence_sequence = 2
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=document.obligation_id,
            satisfied_obligation_ids=[document.obligation_id],
            evidence_refs=["ev-1"],
        )
    )
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=domain.obligation_id,
            satisfied_obligation_ids=[domain.obligation_id],
            evidence_refs=["rule-evidence-0001"],
        )
    )
    checkable = resolve_available_skills(
        state,
        _config(),
        RuntimeFacts(
            rule_corpus_valid=True,
            read_rule_evidence_refs=("rule-evidence-0001",),
            applicability_metadata=RuleApplicabilityMetadata(
                jurisdiction="US",
                effective_date="2024-12-31",
                entity_scope="public issuer",
                document_evidence_refs=("ev-1",),
            ),
        ),
    )
    assert checkable.decision_for(
        SkillName.CHECK_RULE_APPLICABILITY
    ).target_obligation_ids == (applicability.obligation_id,)


def test_dependencies_per_skill_budgets_and_submit_rules_are_enforced():
    state = _state()
    fact = _open(state, "document_fact")
    final = _open(state, "final_verification", dependencies=(fact.obligation_id,))
    config = _config(budgets={"search_report": 1})
    state.skill_call_counts[SkillName.SEARCH_REPORT] = 1

    unresolved = resolve_available_skills(state, config, RuntimeFacts())
    assert SkillName.SEARCH_REPORT not in unresolved
    assert "per-Skill budget" in unresolved.reason_for("search_report")
    assert SkillName.SUBMIT_ANSWER not in unresolved

    exhausted = resolve_available_skills(
        state, config, RuntimeFacts(budget_exhausted=True)
    )
    assert exhausted.available_skills == (SkillName.SUBMIT_ANSWER,)
    assert exhausted.decision_for("submit_answer").target_obligation_ids == (
        final.obligation_id,
    )

    _add_paragraph_evidence(state)
    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=fact.obligation_id,
            satisfied_obligation_ids=[fact.obligation_id],
            evidence_refs=["ev-1"],
        )
    )
    normal = resolve_available_skills(state, config, RuntimeFacts())
    assert normal.available_skills == (SkillName.SUBMIT_ANSWER,)


def test_repair_and_always_exposed_ablation_never_bypass_hard_safety_checks():
    state = _state()
    _open(state, "document_fact")
    _add_paragraph_evidence(state)
    ablation = _config(exposure="always_exposed_ablation")
    facts = RuntimeFacts(
        search_candidate_paragraph_ids=(4,),
        table_candidate_ids=("table-1",),
        rule_corpus_valid=True,
    )

    available = resolve_available_skills(state, ablation, facts)
    assert SkillName.SEARCH_FINANCIAL_RULES in available
    assert SkillName.BIND_FINANCIAL_VALUE in available
    assert SkillName.EXECUTE_FINANCIAL_PROGRAM not in available
    assert SkillName.CHECK_RULE_APPLICABILITY not in available
    assert SkillName.SUBMIT_ANSWER not in available
    available_reasons = [
        decision.reason for decision in available.decisions if decision.available
    ]
    assert len(available_reasons) == len(set(available_reasons))

    repair = resolve_available_skills(
        state,
        ablation,
        facts.model_copy(update={"repair_skill": SkillName.READ_PARAGRAPHS}),
    )
    assert repair.available_skills == (SkillName.READ_PARAGRAPHS,)


def test_resolution_is_pure_and_runtime_facts_are_immutable():
    state = _state()
    _open(state, "document_fact")
    config = _config()
    facts = RuntimeFacts(search_candidates=(1, 2), rule_corpus_valid=True)
    state_before = state.model_dump(mode="json")
    config_before = config.model_dump(mode="json")

    first = resolve_available_skills(state, config, facts)
    second = resolve_available_skills(state, config, facts)

    assert first == second
    assert state.model_dump(mode="json") == state_before
    assert config.model_dump(mode="json") == config_before
    assert facts.search_candidates == (1, 2)
