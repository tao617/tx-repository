"""Load a frozen, gold-free fixed-retrieval index for baseline runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from findver_agent.report_store import ReportSession
from findver_agent.schemas import PublicTask


FORBIDDEN_FIELDS = frozenset(
    {
        "entailment_label",
        "explanation",
        "relevant_context",
        "gold",
        "correct",
        "feedback",
        "scorer_output",
    }
)


class FixedRetrievalError(ValueError):
    """The frozen retrieval file or a task lookup is invalid."""


def _reject_forbidden_fields(value: Any, *, location: str) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_FIELDS & set(value)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise FixedRetrievalError(f"forbidden fields at {location}: {names}")
        for key, child in value.items():
            _reject_forbidden_fields(child, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, location=f"{location}[{index}]")


class FixedEmbeddingIndex:
    """In-memory example-id index loaded once at Runtime startup."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FixedRetrievalError(f"cannot load fixed retrieval file: {path}") from error
        if not isinstance(value, dict) or set(value) != {"metadata", "items"}:
            raise FixedRetrievalError("fixed retrieval root must contain metadata and items")
        _reject_forbidden_fields(value, location="root")
        metadata, items = value["metadata"], value["items"]
        if not isinstance(metadata, dict) or not isinstance(items, dict):
            raise FixedRetrievalError("fixed retrieval metadata and items must be objects")
        if metadata.get("retriever") != "text-embedding-3-large" or metadata.get("top_k") != 10:
            raise FixedRetrievalError(
                "fixed retrieval metadata must identify embedding-3-large top-10"
            )

        normalized: dict[str, tuple[str, tuple[int, ...]]] = {}
        for example_id, record in items.items():
            if not isinstance(example_id, str) or not example_id:
                raise FixedRetrievalError(
                    "fixed retrieval example_id must be a non-empty string"
                )
            if not isinstance(record, dict) or set(record) != {
                "report",
                "retrieved_context",
            }:
                raise FixedRetrievalError(f"invalid fixed retrieval record: {example_id}")
            report, paragraph_ids = record["report"], record["retrieved_context"]
            if not isinstance(report, str) or Path(report).name != report:
                raise FixedRetrievalError(f"invalid report name for {example_id}")
            if (
                not isinstance(paragraph_ids, list)
                or len(paragraph_ids) > 10
                or any(type(item) is not int or item < 0 for item in paragraph_ids)
                or len(paragraph_ids) != len(set(paragraph_ids))
            ):
                raise FixedRetrievalError(f"invalid paragraph ids for {example_id}")
            normalized[example_id] = (report, tuple(paragraph_ids))
        self.metadata = metadata
        self._items = normalized

    def paragraph_ids(self, task: PublicTask, session: ReportSession) -> list[int]:
        try:
            report, paragraph_ids = self._items[task.example_id]
        except KeyError as error:
            raise FixedRetrievalError(
                f"fixed retrieval missing example_id: {task.example_id}"
            ) from error
        if report != task.report or report != session.report_name:
            raise FixedRetrievalError(f"fixed retrieval report mismatch: {task.example_id}")
        for paragraph_id in paragraph_ids:
            try:
                session.read(paragraph_id)
            except ValueError as error:
                raise FixedRetrievalError(
                    "fixed retrieval paragraph id out of range "
                    f"for {task.example_id}: {paragraph_id}"
                ) from error
        return list(paragraph_ids)
