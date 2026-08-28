import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from findver_agent.config import AgentConfig
from findver_agent.findoasis.contracts import ObligationStatus, SkillName
from findver_agent.findoasis.state import (
    FinOASISQuestionState,
    FinOASISStateStore,
)
from findver_agent.financial_rules.corpus import rule_record_sha256
from findver_agent.financial_rules.models import RuleApplicabilityResult
from findver_agent.model_backends.base import GenerationConfig, ModelResponse
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.schemas import PredictionStatus, PublicTask


MANIFEST_SHA256 = "549461e4b4a2fb1b8357b30f03589f62562db7a4b26ac8d38074b34080a4dc33"
RECORDS_SHA256 = "4a3085d2b0d32a320fbc8e5b99527221e1abd161a3a277239732804873fe3436"


class SequenceBackend:
    model_name = "mock-v3-rules"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def generate(self, messages, config):
        self.requests.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return ModelResponse(content=response, input_tokens=13, output_tokens=8)

    async def aclose(self):
        return None


def action(name, arguments, target):
    return json.dumps(
        {
            "action": name,
            "arguments": arguments,
            "control": {
                "target_obligation_id": target,
                "open_obligations": [],
                "obligation_deltas": [],
                "confidence": "low",
                "risk_flags": ["rule_applicability"],
                "expected_skill_effect": "advance frozen rule verification",
            },
        }
    )


def rule_config(rule_root):
    enabled = (
        "search_report",
        "read_paragraphs",
        "search_financial_rules",
        "read_financial_rules",
        "check_rule_applicability",
        "submit_answer",
    )
    return AgentConfig.model_validate(
        {
            "max_steps": 6,
            "protocol_version": "v3",
            "exploration_steps": 5,
            "finalization_steps": 1,
            "review_steps": 0,
            "review_policy": "none",
            "calculator_enabled": False,
            "findoasis": {
                "experimental": True,
                "official_test_authorized": False,
                "real_model_execution_authorized": False,
                "scorer_handoff_authorized": False,
                "enabled_skills": enabled,
                "skill_budgets": {
                    skill.value: (8 if skill.value in enabled else 0)
                    for skill in SkillName
                },
                "obligation_policy": {
                    "seeding": "conservative",
                    "skill_exposure": "dynamic",
                    "model_may_open_obligations": True,
                    "model_may_satisfy_obligations": False,
                    "model_may_waive_mandatory": False,
                    "normal_submit_requires_all_mandatory": True,
                    "budget_exhausted_submit": "low_confidence_best_effort",
                },
                "rule_corpus": {
                    "enabled": True,
                    "rule_root": str(rule_root),
                    "manifest_path": "manifest.json",
                    "records_path": "records.json",
                    "corpus_id": "finoasis-synthetic-rules-v1",
                    "manifest_sha256": MANIFEST_SHA256,
                    "records_sha256": RECORDS_SHA256,
                    "read_only": True,
                    "network_fallback": False,
                },
            },
        }
    )


@pytest.mark.asyncio
async def test_rule_search_read_and_applicability_certificate_are_gated(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {
                        "id": 0,
                        "type": "text",
                        "context": (
                            "The identified performance obligation was satisfied "
                            "before revenue recognition."
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id="finoasis-rules",
        statement=(
            "Under US GAAP, the recognition rule required a public issuer on "
            "2024-12-31 to recognize revenue when the performance obligation "
            "was satisfied."
        ),
        report="report.json",
    )
    backend = SequenceBackend(
        [
            action(
                "search_report",
                {"query": "performance obligation satisfied", "top_k": 2},
                "obl-0001",
            ),
            action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
            action(
                "search_financial_rules",
                {
                    "query": "performance obligation revenue recognition",
                    "jurisdiction": "US",
                    "as_of_date": "2024-12-31",
                    "top_k": 3,
                },
                "obl-0002",
            ),
            action(
                "read_financial_rules",
                {"rule_ids": ["synthetic-us-revenue-current"]},
                "obl-0002",
            ),
            action(
                "check_rule_applicability",
                {
                    "rule_evidence_refs": ["rule-evidence-0001"],
                    "document_evidence_refs": ["report-paragraph:0"],
                    "jurisdiction": "US",
                    "effective_date": "2024-12-31",
                    "entity_scope": "public issuer",
                    "applicability_predicate_ids": [
                        "predicate:performance-obligation"
                    ],
                },
                "obl-0003",
            ),
            action(
                "submit_answer",
                {
                    "label": "entailed",
                    "evidence_ids": [0],
                    "explanation": "The report fact and applicable frozen rule support the claim.",
                },
                "obl-0004",
            ),
        ]
    )
    run_dir = tmp_path / "run"
    rule_root = Path("tests/fixtures/finoasis_rule_corpus").resolve()
    config = rule_config(rule_root)
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(prompt_budget_tokens=8192),
        agent_config=config,
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )

    prediction = await orchestrator.run_question(task)

    state = FinOASISStateStore(run_dir / "state").load_or_create(
        task,
        orchestrator._finoasis_agent._resume_identity(task),
        6,
        exploration_steps=5,
        finalization_steps=1,
    )
    assert state.obligation("obl-0001").status is ObligationStatus.SATISFIED
    assert state.obligation("obl-0002").status is ObligationStatus.SATISFIED
    assert state.obligation("obl-0003").status is ObligationStatus.SATISFIED
    assert state.obligation("obl-0004").status is ObligationStatus.SATISFIED
    assert prediction.status is PredictionStatus.COMPLETED
    assert state.final_certificate_status.value == "verified"
    final = state.final_verification_certificate_ledger["final-certificate-0001"]
    assert final.rule_certificate_refs == ["rule-certificate-0001"]
    assert final.label_supported is True
    assert len(state.rule_search_history) == 1
    assert list(state.rule_evidence_ledger) == ["rule-evidence-0001"]
    assert list(state.rule_applicability_certificate_ledger) == [
        "rule-certificate-0001"
    ]
    certificate = state.rule_applicability_certificate_ledger[
        "rule-certificate-0001"
    ]
    assert certificate.result is RuleApplicabilityResult.APPLICABLE
    assert certificate.rule_ids == ["synthetic-us-revenue-current"]
    assert certificate.document_evidence_refs == ["report-paragraph:0"]
    assert state.skill_call_counts[SkillName.SEARCH_FINANCIAL_RULES] == 1
    assert state.skill_call_counts[SkillName.READ_FINANCIAL_RULES] == 1
    assert state.skill_call_counts[SkillName.CHECK_RULE_APPLICABILITY] == 1

    before_search = backend.requests[2][0]["content"]
    assert '"action":"read_financial_rules"' not in before_search
    after_search = backend.requests[3]
    assert '"action":"read_financial_rules"' in after_search[0]["content"]
    assert '"rule_id":"synthetic-us-revenue-current"' in after_search[1]["content"]
    after_read = backend.requests[4]
    assert '"action":"check_rule_applicability"' in after_read[0]["content"]
    assert '"rule_evidence_ref":"rule-evidence-0001"' in after_read[1]["content"]
    assert "Synthetic current rule:" not in after_read[1]["content"]

    tampered = state.model_dump(mode="json")
    tampered["rule_applicability_certificate_ledger"][
        "rule-certificate-0001"
    ]["diagnostics"][0] = "tampered applicability diagnostic"
    with pytest.raises(ValidationError, match="payload hash does not match"):
        FinOASISQuestionState.model_validate(tampered)

    candidate = state.model_copy(deep=True)
    evidence = candidate.rule_evidence_ledger["rule-evidence-0001"]
    changed_text = evidence.record.text + " Tampered."
    changed_record = evidence.record.model_copy(
        update={
            "text": changed_text,
            "source_sha256": hashlib.sha256(changed_text.encode()).hexdigest(),
        }
    )
    candidate.rule_evidence_ledger["rule-evidence-0001"] = evidence.model_copy(
        update={
            "record": changed_record,
            "rule_sha256": rule_record_sha256(changed_record),
        }
    )
    with pytest.raises(ValueError, match="differs from the frozen corpus"):
        orchestrator._finoasis_agent._validate_rule_state_against_corpus(candidate)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "rule_id",
        "rule_query",
        "document_fact",
        "predicate_id",
        "failed_check",
    ),
    [
        (
            "synthetic-us-revenue-expired",
            "expired legacy delivery rule",
            "delivery occurred",
            "predicate:legacy-delivery",
            "effective_date_check",
        ),
        (
            "synthetic-eu-revenue-current",
            "EU control transfer rule",
            "control transfers",
            "predicate:control-transfer",
            "jurisdiction_check",
        ),
    ],
)
async def test_scope_mismatched_rules_remain_retrievable_for_negative_certificate(
    tmp_path,
    rule_id,
    rule_query,
    document_fact,
    predicate_id,
    failed_check,
):
    reports = tmp_path / f"reports-{rule_id}"
    reports.mkdir()
    (reports / "report.json").write_text(
        json.dumps(
            {
                "context": [
                    {
                        "id": 0,
                        "type": "text",
                        "context": f"The report states that {document_fact}.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    task = PublicTask(
        example_id=f"finoasis-negative-{rule_id}",
        statement=(
            f"Under US GAAP, the {rule_query} applied to a public issuer on "
            f"2024-12-31 because {document_fact}."
        ),
        report="report.json",
    )
    backend = SequenceBackend(
        [
            action(
                "search_report",
                {"query": document_fact, "top_k": 1},
                "obl-0001",
            ),
            action("read_paragraphs", {"paragraph_ids": [0]}, "obl-0001"),
            action(
                "search_financial_rules",
                {
                    "query": rule_query,
                    "jurisdiction": "US",
                    "as_of_date": "2024-12-31",
                    "top_k": 4,
                },
                "obl-0002",
            ),
            action(
                "read_financial_rules",
                {"rule_ids": [rule_id]},
                "obl-0002",
            ),
            action(
                "check_rule_applicability",
                {
                    "rule_evidence_refs": ["rule-evidence-0001"],
                    "document_evidence_refs": ["report-paragraph:0"],
                    "jurisdiction": "US",
                    "effective_date": "2024-12-31",
                    "entity_scope": "public issuer",
                    "applicability_predicate_ids": [predicate_id],
                },
                "obl-0003",
            ),
            action(
                "submit_answer",
                {
                    "label": "refuted",
                    "evidence_ids": [0],
                    "explanation": (
                        "The retrieved rule is mechanically outside the claim scope."
                    ),
                },
                "obl-0004",
            ),
        ]
    )
    run_dir = tmp_path / f"run-{rule_id}"
    rule_root = Path("tests/fixtures/finoasis_rule_corpus").resolve()
    orchestrator = AgentOrchestrator(
        backend=backend,
        generation=GenerationConfig(prompt_budget_tokens=8192),
        agent_config=rule_config(rule_root),
        report_store=ReportStore(reports),
        run_dir=run_dir,
    )

    prediction = await orchestrator.run_question(task)
    state = FinOASISStateStore(run_dir / "state").load_or_create(
        task,
        orchestrator._finoasis_agent._resume_identity(task),
        6,
        exploration_steps=5,
        finalization_steps=1,
    )

    assert prediction.status is PredictionStatus.COMPLETED
    assert prediction.label.value == "refuted"
    hits = {hit.rule_id: hit for hit in state.rule_search_history[0].hits}
    assert rule_id in hits
    assert hits[rule_id].jurisdiction in {"US", "EU"}
    certificate = state.rule_applicability_certificate_ledger[
        "rule-certificate-0001"
    ]
    assert certificate.result is RuleApplicabilityResult.NOT_APPLICABLE
    assert getattr(certificate, failed_check) is False
    final = state.final_verification_certificate_ledger["final-certificate-0001"]
    assert final.label_supported is True
    assert not backend.responses
