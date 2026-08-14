"""Final immutable answer validation."""

from __future__ import annotations

from findver_agent.report_store import ReportError, ReportSession
from findver_agent.schemas import Label, Prediction, PredictionStatus
from findver_agent.skills.base import SkillError


class SubmitAnswerSkill:
    name = "submit_answer"

    def __init__(self, session: ReportSession, example_id: str) -> None:
        self._session = session
        self._example_id = example_id

    def execute(
        self,
        *,
        label: Label,
        evidence_ids: list[int],
        explanation: str,
    ) -> Prediction:
        if len(evidence_ids) != len(set(evidence_ids)):
            raise SkillError("evidence_ids must be unique")
        try:
            for paragraph_id in evidence_ids:
                self._session.read(paragraph_id)
        except (ReportError, TypeError) as error:
            raise SkillError(str(error)) from error
        return Prediction(
            example_id=self._example_id,
            label=label,
            status=PredictionStatus.COMPLETED,
            evidence_ids=evidence_ids,
            explanation=explanation,
        )

