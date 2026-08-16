import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[2]
PRIVATE_METRICS = ROOT / "docs" / "private_metrics"


def test_private_metric_schemas_are_valid_and_output_is_aggregate_only():
    input_schema = json.loads(
        (PRIVATE_METRICS / "evidence_analysis_input.schema.json").read_text(
            encoding="utf-8"
        )
    )
    output_schema = json.loads(
        (PRIVATE_METRICS / "evidence_analysis_output.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(output_schema)
    output_text = json.dumps(output_schema)
    for per_example_field in (
        "example_id",
        "gold_label",
        "gold_evidence_ids",
        "candidate_evidence_ids",
        "final_agent_evidence_ids",
    ):
        assert per_example_field not in output_text


def test_private_metric_contract_names_every_required_analysis():
    text = (ROOT / "docs" / "PRIVATE_EVIDENCE_METRICS.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "Evidence Precision",
        "Evidence Recall",
        "Evidence F1",
        "All-Gold Evidence Recall",
        "Initial RAG Recall",
        "Final Agent Evidence Recall",
        "Evidence Recovery Rate",
        "paired bootstrap",
        "McNemar",
        "short",
        "medium",
        "long",
        "front",
        "middle",
        "back",
    ):
        assert required.casefold() in text.casefold()
