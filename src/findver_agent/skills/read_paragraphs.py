"""Exact paragraph reads with no path parameter."""

from __future__ import annotations

from findver_agent.report_store import ReportError, ReportSession
from findver_agent.skills.base import SkillError


class ReadParagraphsSkill:
    name = "read_paragraphs"

    def __init__(self, session: ReportSession, *, max_paragraphs: int = 12) -> None:
        self._session = session
        self._max_paragraphs = min(max_paragraphs, 12)

    def execute(self, *, paragraph_ids: list[int]) -> dict[str, object]:
        if not isinstance(paragraph_ids, list) or not paragraph_ids:
            raise SkillError("paragraph_ids must be a non-empty list")
        if len(paragraph_ids) > self._max_paragraphs:
            raise SkillError(f"at most {self._max_paragraphs} paragraphs may be read")
        if len(paragraph_ids) != len(set(paragraph_ids)):
            raise SkillError("paragraph_ids must be unique")
        try:
            paragraphs = [self._session.read(item) for item in paragraph_ids]
        except (ReportError, TypeError) as error:
            raise SkillError(str(error)) from error
        return {
            "paragraphs": [
                {"paragraph_id": paragraph.paragraph_id, "text": paragraph.text}
                for paragraph in paragraphs
            ]
        }

