import json

import pytest

from findver_agent.schemas import PublicTask
from findver_agent.state import QuestionState, StateStore


def task():
    return PublicTask(
        example_id="state-v2",
        statement="Claim",
        report="report.json",
    )


def test_v2_state_starts_in_initialization_with_persisted_budgets():
    state = QuestionState.create(
        task(),
        8,
        protocol_version="v2",
        exploration_steps=6,
        finalization_steps=2,
        review_steps=1,
    )

    assert state.schema_version == 2
    assert state.protocol_version == "v2"
    assert state.phase == "initialization"
    assert state.phase_budgets.model_dump() == {
        "exploration": 6,
        "finalization": 2,
        "review": 1,
    }
    assert state.remaining_steps == 9


def test_legacy_v1_state_without_new_fields_remains_loadable(tmp_path):
    store = StateStore(tmp_path / "state")
    legacy = {
        "example_id": "state-v2",
        "statement": "Claim",
        "report": "report.json",
        "step": 1,
        "remaining_steps": 7,
        "search_queries": [],
        "evidence_ledger": [],
        "calculations": [],
        "open_questions": [],
        "tool_counts": {
            "search_report": 0,
            "read_paragraphs": 0,
            "calculator": 0,
        },
        "usage": {
            "model_calls": 1,
            "input_tokens": 10,
            "output_tokens": 2,
            "latency_ms": 1,
        },
        "errors": [],
        "last_observation": None,
        "prediction": None,
        "review_requested": False,
        "review_completed": False,
        "draft_submission": None,
        "closed": False,
    }
    store.path_for("state-v2").write_text(json.dumps(legacy), encoding="utf-8")

    restored = store.load_or_create(task(), 8)

    assert restored.schema_version == 1
    assert restored.protocol_version == "v1"
    assert restored.phase == "exploration"
    assert restored.phase_budgets is None
    assert restored.step == 1
    assert restored.draft_risk_flags == []


def test_protocol_version_change_is_rejected_on_resume(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(QuestionState.create(task(), 8))

    with pytest.raises(ValueError, match="protocol_version"):
        store.load_or_create(
            task(),
            8,
            protocol_version="v2",
            exploration_steps=6,
            finalization_steps=2,
            review_steps=1,
        )
