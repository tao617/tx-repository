"""Load a frozen, gold-free fixed-retrieval index."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from findver_agent.report_store import ReportError, ReportSession
from findver_agent.schemas import PublicTask


SUPPORTED_RETRIEVERS = frozenset(
    {"bm25", "text-embedding-3-large", "contriever-msmarco"}
)
SUPPORTED_TOP_K = frozenset({3, 5, 10})
FORBIDDEN_FIELDS = frozenset(
    {
        "entailment_label",
        "label",
        "subset",
        "explanation",
        "relevant_context",
        "gold",
        "correct",
        "feedback",
        "scorer_output",
    }
)
LIST_RECORD_FIELDS = frozenset({"example_id", "report", "retrieved_context"})
WRAPPED_RECORD_FIELDS = frozenset({"report", "retrieved_context"})


class FixedRetrievalError(ValueError):
    """The frozen retrieval file or a task lookup is invalid."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise FixedRetrievalError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _reject_forbidden_fields(value: Any, *, location: str) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_FIELDS & {key.casefold() for key in value}
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise FixedRetrievalError(f"forbidden fields at {location}: {names}")
        for key, child in value.items():
            _reject_forbidden_fields(child, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, location=f"{location}[{index}]")


def _safe_report_name(value: Any, *, example_id: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or not value.lower().endswith(".json")
    ):
        raise FixedRetrievalError(f"invalid report name for {example_id}")
    return value


def _paragraph_ids(value: Any, *, example_id: str, top_k: int) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or len(value) > top_k
        or any(type(item) is not int or item < 0 for item in value)
        or len(value) != len(set(value))
    ):
        raise FixedRetrievalError(f"invalid paragraph ids for {example_id}")
    return tuple(value)


class FixedRetrievalIndex:
    """In-memory example index bound to one immutable retrieval artifact."""

    def __init__(
        self,
        path: Path,
        *,
        retriever: str | None = None,
        top_k: int | None = None,
    ) -> None:
        self.path = Path(path)
        try:
            raw = self.path.read_bytes()
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_object_without_duplicate_keys,
            )
        except FixedRetrievalError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FixedRetrievalError(
                f"cannot load fixed retrieval file: {self.path}"
            ) from error
        self.file_sha256 = hashlib.sha256(raw).hexdigest()
        _reject_forbidden_fields(value, location="root")

        if isinstance(value, list):
            if retriever is None or top_k is None:
                raise FixedRetrievalError(
                    "list-format retrieval requires configured retriever and top_k"
                )
            resolved_retriever, resolved_top_k = retriever, top_k
            records = self._records_from_list(value)
            metadata: dict[str, Any] = {
                "retriever": resolved_retriever,
                "top_k": resolved_top_k,
                "format": "findver-list",
            }
        elif isinstance(value, dict) and set(value) == {"metadata", "items"}:
            metadata = value["metadata"]
            items = value["items"]
            if not isinstance(metadata, dict) or not isinstance(items, dict):
                raise FixedRetrievalError(
                    "fixed retrieval metadata and items must be objects"
                )
            file_retriever = metadata.get("retriever")
            file_top_k = metadata.get("top_k")
            if retriever is not None and retriever != file_retriever:
                raise FixedRetrievalError("configured retriever does not match file metadata")
            if top_k is not None and top_k != file_top_k:
                raise FixedRetrievalError("configured top_k does not match file metadata")
            resolved_retriever = file_retriever if retriever is None else retriever
            resolved_top_k = file_top_k if top_k is None else top_k
            records = self._records_from_items(items)
        else:
            raise FixedRetrievalError(
                "fixed retrieval root must be a FinDVer list or contain metadata and items"
            )

        if resolved_retriever not in SUPPORTED_RETRIEVERS:
            raise FixedRetrievalError(f"unsupported retriever: {resolved_retriever}")
        if resolved_top_k not in SUPPORTED_TOP_K:
            raise FixedRetrievalError(f"unsupported top_k: {resolved_top_k}")

        normalized: dict[str, tuple[str, tuple[int, ...]]] = {}
        for example_id, record in records:
            if not isinstance(example_id, str) or not example_id:
                raise FixedRetrievalError(
                    "fixed retrieval example_id must be a non-empty string"
                )
            if example_id in normalized:
                raise FixedRetrievalError(f"duplicate example_id: {example_id}")
            report = _safe_report_name(record.get("report"), example_id=example_id)
            paragraph_ids = _paragraph_ids(
                record.get("retrieved_context"),
                example_id=example_id,
                top_k=resolved_top_k,
            )
            normalized[example_id] = (report, paragraph_ids)

        self.retriever = resolved_retriever
        self.top_k = resolved_top_k
        self.metadata = dict(metadata)
        self._items = normalized

    @staticmethod
    def _records_from_list(
        value: list[Any],
    ) -> list[tuple[Any, dict[str, Any]]]:
        records: list[tuple[Any, dict[str, Any]]] = []
        for index, record in enumerate(value):
            if not isinstance(record, dict) or set(record) != LIST_RECORD_FIELDS:
                raise FixedRetrievalError(f"invalid fixed retrieval record at index {index}")
            records.append((record["example_id"], record))
        return records

    @staticmethod
    def _records_from_items(
        items: dict[str, Any],
    ) -> list[tuple[Any, dict[str, Any]]]:
        records: list[tuple[Any, dict[str, Any]]] = []
        for example_id, record in items.items():
            if not isinstance(record, dict) or set(record) != WRAPPED_RECORD_FIELDS:
                raise FixedRetrievalError(f"invalid fixed retrieval record: {example_id}")
            records.append((example_id, record))
        return records

    def paragraph_ids(self, task: PublicTask, session: ReportSession) -> list[int]:
        try:
            report, paragraph_ids = self._items[task.example_id]
        except KeyError as error:
            raise FixedRetrievalError(
                f"fixed retrieval missing example_id: {task.example_id}"
            ) from error
        if report != task.report or report != session.report_name:
            raise FixedRetrievalError(
                f"fixed retrieval report mismatch: {task.example_id}"
            )
        for paragraph_id in paragraph_ids:
            try:
                session.read(paragraph_id)
            except (ReportError, TypeError) as error:
                raise FixedRetrievalError(
                    "fixed retrieval paragraph id out of range "
                    f"for {task.example_id}: {paragraph_id}"
                ) from error
        return list(paragraph_ids)


class FixedEmbeddingIndex(FixedRetrievalIndex):
    """Compatibility loader for the historical embedding top-10 artifact."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            path,
            retriever="text-embedding-3-large",
            top_k=10,
        )
