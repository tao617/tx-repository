import hashlib
import json
import stat

import pytest
from pydantic import ValidationError

from findver_agent.findoasis.contracts import (
    AddDependencyDelta,
    AttachEvidenceDelta,
    MarkPartialDelta,
    ObligationProposal,
    ObligationStatus,
    QuestionPhase,
    SkillResult,
)
from findver_agent.findoasis.state import (
    EvidenceLedgerEntry,
    FinOASISQuestionState,
    FinOASISStateStore,
    ResumeIdentity,
)
from findver_agent.schemas import PublicTask


EVIDENCE_TEXT = "Operating income was 128.4 in 2022."
HASH = hashlib.sha256(EVIDENCE_TEXT.encode()).hexdigest()


def task(statement="Revenue increased."):
    return PublicTask(example_id="example-1", statement=statement, report="report.json")


def identity(public_task=None, **updates):
    public_task = public_task or task()
    values = {
        "report_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "registry_sha256": "3" * 64,
        "obligation_policy_sha256": "4" * 64,
    }
    values.update(updates)
    return ResumeIdentity.create(public_task, **values)


def state_with_fact():
    state = FinOASISQuestionState.create(task(), identity(), max_steps=8)
    fact = state.open_obligation(
        ObligationProposal(
            type="document_fact", description="Find the exact report fact."
        )
    )
    return state, fact.obligation_id


def add_evidence(state, evidence_id="ev-1"):
    state.evidence_ledger[evidence_id] = EvidenceLedgerEntry(
        evidence_id=evidence_id,
        source="report_paragraph",
        paragraph_id=3,
        exact_text=EVIDENCE_TEXT,
        exact_text_sha256=HASH,
    )


def test_runtime_allocates_deterministic_contiguous_ids_and_known_dependencies():
    state = FinOASISQuestionState.create(task(), identity(), max_steps=8)
    first = state.open_obligation(
        ObligationProposal(type="document_fact", description="Read the source fact.")
    )
    second = state.open_obligation(
        ObligationProposal(
            type="final_verification",
            description="Verify all evidence before submission.",
            dependency_ids=[first.obligation_id],
        )
    )
    assert [item.obligation_id for item in state.obligations] == [
        "obl-0001",
        "obl-0002",
    ]
    assert second.dependency_ids == ["obl-0001"]
    assert state.next_obligation_sequence == 3

    before = state.model_dump()
    with pytest.raises(ValueError, match="unknown dependency"):
        state.open_obligation(
            ObligationProposal(
                type="domain_rule",
                description="Find the relevant rule.",
                dependency_ids=["obl-9999"],
            )
        )
    assert state.model_dump() == before


def test_graph_rejects_cycles_transactionally():
    state = FinOASISQuestionState.create(task(), identity(), max_steps=8)
    first = state.open_obligation(
        ObligationProposal(type="document_fact", description="Read the report fact.")
    )
    second = state.open_obligation(
        ObligationProposal(
            type="final_verification",
            description="Verify the report fact.",
            dependency_ids=[first.obligation_id],
        )
    )
    before = state.model_dump()
    with pytest.raises(ValidationError, match="cycle"):
        state.apply_model_deltas(
            [
                AddDependencyDelta(
                    obligation_id=first.obligation_id,
                    dependency_id=second.obligation_id,
                )
            ]
        )
    assert state.model_dump() == before


def test_model_deltas_can_attach_and_mark_partial_but_not_satisfy():
    state, obligation_id = state_with_fact()
    add_evidence(state)
    state.apply_model_deltas(
        [
            AttachEvidenceDelta(
                obligation_id=obligation_id, evidence_refs=["ev-1"]
            ),
            MarkPartialDelta(
                obligation_id=obligation_id,
                diagnostic="The period still needs confirmation.",
            ),
        ]
    )
    obligation = state.obligation(obligation_id)
    assert obligation.status is ObligationStatus.PARTIAL
    assert obligation.evidence_refs == ["ev-1"]
    with pytest.raises(ValidationError):
        MarkPartialDelta.model_validate(
            {"operation": "mark_satisfied", "obligation_id": obligation_id}
        )


def test_only_validated_skill_result_can_satisfy_and_dependencies_are_enforced():
    state = FinOASISQuestionState.create(task(), identity(), max_steps=8)
    first = state.open_obligation(
        ObligationProposal(type="document_fact", description="Read the report fact.")
    )
    second = state.open_obligation(
        ObligationProposal(
            type="final_verification",
            description="Verify the report fact.",
            dependency_ids=[first.obligation_id],
        )
    )
    add_evidence(state)
    second_result = SkillResult(
        status="satisfied",
        target_obligation_id=second.obligation_id,
        satisfied_obligation_ids=[second.obligation_id],
        evidence_refs=["ev-1"],
    )
    before = state.model_dump()
    with pytest.raises(ValueError, match="before dependencies"):
        state.apply_skill_result(second_result)
    assert state.model_dump() == before

    state.apply_skill_result(
        SkillResult(
            status="satisfied",
            target_obligation_id=first.obligation_id,
            satisfied_obligation_ids=[first.obligation_id],
            evidence_refs=["ev-1"],
        )
    )
    state.apply_skill_result(second_result)
    assert all(
        obligation.status is ObligationStatus.SATISFIED
        for obligation in state.obligations
    )


def test_state_validation_rejects_dangling_ledgers_and_false_verified_status():
    state, obligation_id = state_with_fact()
    payload = state.model_dump(mode="json")
    payload["obligations"][0]["evidence_refs"] = ["missing-evidence"]
    with pytest.raises(ValidationError, match="dangling evidence"):
        FinOASISQuestionState.model_validate(payload)

    payload = state.model_dump(mode="json")
    payload["final_certificate_status"] = "verified"
    with pytest.raises(ValidationError, match="unresolved mandatory"):
        FinOASISQuestionState.model_validate(payload)

    payload = state.model_dump(mode="json")
    payload["next_obligation_sequence"] = 99
    with pytest.raises(ValidationError, match="next_obligation_sequence"):
        FinOASISQuestionState.model_validate(payload)


def test_evidence_text_hash_and_phase_attempt_counters_are_integrity_bound():
    state, _ = state_with_fact()
    add_evidence(state)
    payload = state.model_dump(mode="json")
    payload["evidence_ledger"]["ev-1"]["exact_text"] = "tampered evidence"
    with pytest.raises(ValidationError, match="exact_text_sha256"):
        FinOASISQuestionState.model_validate(payload)

    state.phase = QuestionPhase.EXPLORATION
    state.charge_attempt()
    assert state.step == 1
    assert state.phase_attempts.exploration_used == 1
    assert state.remaining_steps == 7
    payload = state.model_dump(mode="json")
    payload["step"] = 2
    with pytest.raises(ValidationError, match="charged phase attempts"):
        FinOASISQuestionState.model_validate(payload)


def test_state_store_round_trip_is_private_atomic_and_identity_bound(tmp_path):
    public_task = task()
    resume_identity = identity(public_task)
    store = FinOASISStateStore(tmp_path / "state")
    state = store.load_or_create(public_task, resume_identity, max_steps=8)
    state.open_obligation(
        ObligationProposal(type="document_fact", description="Read the report fact.")
    )
    store.save(state)

    path = store.path_for(public_task.example_id)
    assert path.name.endswith(".v3.json")
    assert "example-1" not in path.name
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.load_or_create(public_task, resume_identity, max_steps=8) == state
    assert not list(path.parent.glob(f".{path.name}.*"))

    changed_identity = identity(public_task, config_sha256="9" * 64)
    with pytest.raises(ValueError, match="resume identity"):
        store.load_or_create(public_task, changed_identity, max_steps=8)


def test_resume_rejects_public_task_and_serialized_identity_drift(tmp_path):
    public_task = task()
    store = FinOASISStateStore(tmp_path / "state")
    resume_identity = identity(public_task)
    store.save(FinOASISQuestionState.create(public_task, resume_identity, max_steps=8))

    with pytest.raises(ValueError, match="public task"):
        store.load_or_create(task("Different claim."), resume_identity, max_steps=8)

    path = store.path_for(public_task.example_id)
    payload = json.loads(path.read_text())
    payload["statement"] = "Tampered claim."
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="immutable resume identity"):
        store.load_or_create(public_task, resume_identity, max_steps=8)


def test_resume_identity_requires_complete_rule_corpus_binding():
    with pytest.raises(ValidationError, match="supplied together"):
        ResumeIdentity.create(
            task(),
            report_sha256="1" * 64,
            config_sha256="2" * 64,
            registry_sha256="3" * 64,
            obligation_policy_sha256="4" * 64,
            rule_corpus_id="synthetic-v1",
        )
