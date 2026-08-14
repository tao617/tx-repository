import json

import pytest

from scripts.verify_public_data import verify_records
from scripts.verify_runtime_bundle import verify_context


@pytest.mark.parametrize("field", ["entailment_label", "relevant_context"])
def test_public_gold_fields_fail_validation(field):
    record = {"example_id": "one", "statement": "Claim", "report": "report.json", field: "leak"}
    with pytest.raises(ValueError, match="forbidden"):
        verify_records([record])


def test_runtime_context_allowlist_passes_repository():
    checked = verify_context(__import__("pathlib").Path.cwd())
    assert checked > 0

