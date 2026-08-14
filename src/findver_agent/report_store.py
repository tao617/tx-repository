"""Safe access to the report bound to one question."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ReportError(ValueError):
    """A report is missing, malformed, or outside the report root."""


@dataclass(frozen=True, slots=True)
class Paragraph:
    paragraph_id: int
    text: str


@dataclass(frozen=True, slots=True)
class ReportSession:
    report_name: str
    paragraphs: tuple[Paragraph, ...]

    def read(self, paragraph_id: int) -> Paragraph:
        if isinstance(paragraph_id, bool) or paragraph_id < 0 or paragraph_id >= len(self.paragraphs):
            raise ReportError(f"paragraph id out of range: {paragraph_id}")
        return self.paragraphs[paragraph_id]


class ReportStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ReportError("report root must be a directory")

    def open_session(self, report_name: str) -> ReportSession:
        if not isinstance(report_name, str) or Path(report_name).name != report_name:
            raise ReportError("report must be a bare filename")
        if not report_name.lower().endswith(".json"):
            raise ReportError("report must use the .json extension")
        candidate = (self.root / report_name).resolve(strict=True)
        if candidate.parent != self.root or not candidate.is_file():
            raise ReportError("report is outside the configured report root")
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
            context = value["context"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise ReportError(f"invalid report: {report_name}") from error
        if not isinstance(context, list):
            raise ReportError("report context must be a list")
        paragraphs: list[Paragraph] = []
        for index, item in enumerate(context):
            if not isinstance(item, dict) or not isinstance(item.get("context"), str):
                raise ReportError(f"invalid paragraph at index {index}")
            paragraphs.append(Paragraph(paragraph_id=index, text=item["context"]))
        return ReportSession(report_name=report_name, paragraphs=tuple(paragraphs))

