import pytest
from pydantic import ValidationError

from findver_agent.schemas import Prediction, PublicTask


def test_public_task_rejects_extra_and_traversing_report():
    with pytest.raises(ValidationError):
        PublicTask(
            example_id="example-1",
            statement="Claim",
            report="../gold.json",
            subset="numeric",
        )


def test_prediction_rejects_duplicate_evidence_ids():
    with pytest.raises(ValidationError, match="unique"):
        Prediction(
            example_id="example-1",
            label="entailed",
            status="completed",
            evidence_ids=[1, 1],
            explanation="Evidence.",
        )

