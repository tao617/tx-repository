from pathlib import Path

import pytest

from scripts.prepare_public_data import (
    ensure_private_path_is_outside_repository,
    split_records,
)
from scripts.verify_public_data import verify_records


def source_record(**overrides):
    record = {
        "example_id": "example-1",
        "statement": "Revenue increased.",
        "report": "report.json",
        "subset": "ie",
        "entailment_label": True,
        "explanation": ["builder-only"],
        "relevant_context": [2],
    }
    record.update(overrides)
    return record


def test_split_exposes_only_public_contract_fields():
    public, gold = split_records([source_record()])

    assert public == [
        {
            "example_id": "example-1",
            "statement": "Revenue increased.",
            "report": "report.json",
        }
    ]
    assert gold == [{"example_id": "example-1", "label": "entailed", "subset": "ie"}]
    verify_records(public)


@pytest.mark.parametrize("field", ["entailment_label", "relevant_context", "subset", "correct"])
def test_public_verifier_rejects_gold_derived_fields(field):
    public = {"example_id": "example-1", "statement": "Claim", "report": "report.json"}
    public[field] = "forbidden"

    with pytest.raises(ValueError, match="forbidden fields"):
        verify_records([public])


def test_duplicate_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate example_id"):
        split_records([source_record(), source_record()])


def test_private_output_cannot_be_inside_agent_repository():
    with pytest.raises(ValueError, match="outside the Agent repository"):
        ensure_private_path_is_outside_repository(Path("private/gold.jsonl"))

