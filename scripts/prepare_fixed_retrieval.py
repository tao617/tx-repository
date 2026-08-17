#!/usr/bin/env python3
"""Build a Runtime-only fixed-retrieval artifact from cutoff-specific outputs."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from findver_agent.fixed_retrieval import SUPPORTED_RETRIEVERS, SUPPORTED_TOP_K
from findver_agent.report_store import ReportStore
from findver_agent.runner import load_public_tasks


ALLOWED_FIELDS = frozenset({"example_id", "report", "retrieved_context"})


def load_official(paths: list[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"{path} must contain a JSON array")
        for record in value:
            if not isinstance(record, dict) or set(record) != ALLOWED_FIELDS:
                raise ValueError(f"{path} contains an invalid or gold-bearing record")
            example_id = record["example_id"]
            if not isinstance(example_id, str) or not example_id:
                raise ValueError(f"{path} contains an invalid example_id")
            if example_id in records:
                raise ValueError(f"duplicate official example_id: {example_id}")
            records[example_id] = record
    return records


def build(
    *,
    tasks_path: Path,
    reports_path: Path,
    official_paths: list[Path],
    source_commit: str,
    retriever: str = "text-embedding-3-large",
    top_k: int = 10,
) -> dict[str, Any]:
    if retriever not in SUPPORTED_RETRIEVERS:
        raise ValueError(f"unsupported retriever: {retriever}")
    if top_k not in SUPPORTED_TOP_K:
        raise ValueError(f"unsupported top_k: {top_k}")
    tasks = load_public_tasks(tasks_path)
    official = load_official(official_paths)
    reports = ReportStore(reports_path)
    items: dict[str, dict[str, Any]] = {}
    for task in tasks:
        try:
            record = official[task.example_id]
        except KeyError as error:
            raise ValueError(f"official retrieval missing example_id: {task.example_id}") from error
        report = Path(record["report"]).name
        if report != task.report:
            raise ValueError(f"official retrieval report mismatch: {task.example_id}")
        paragraph_ids = record["retrieved_context"]
        if (
            not isinstance(paragraph_ids, list)
            or len(paragraph_ids) > top_k
            or any(type(item) is not int or item < 0 for item in paragraph_ids)
            or len(paragraph_ids) != len(set(paragraph_ids))
        ):
            raise ValueError(f"invalid official paragraph ids: {task.example_id}")
        session = reports.open_session(task.report)
        for paragraph_id in paragraph_ids:
            session.read(paragraph_id)
        items[task.example_id] = {
            "report": report,
            "retrieved_context": paragraph_ids,
        }
    canonical_sources = [
        f"outputs/test_outputs/retriever_output/top_{top_k}/{retriever}.json",
        f"outputs/testmini_outputs/retriever_output/top_{top_k}/{retriever}.json",
    ]
    return {
        "metadata": {
            "source_repo": "yilunzhao/FinDVer",
            "source_commit": source_commit,
            "source_files": canonical_sources,
            "retriever": retriever,
            "top_k": top_k,
            "examples": len(items),
        },
        "items": items,
    }


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    parser.add_argument("--official-test", required=True, type=Path)
    parser.add_argument("--official-testmini", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--retriever",
        choices=sorted(SUPPORTED_RETRIEVERS),
        default="text-embedding-3-large",
    )
    parser.add_argument(
        "--top-k",
        choices=sorted(SUPPORTED_TOP_K),
        default=10,
        type=int,
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = build(
        tasks_path=args.tasks,
        reports_path=args.reports,
        official_paths=[args.official_test, args.official_testmini],
        source_commit=args.source_commit,
        retriever=args.retriever,
        top_k=args.top_k,
    )
    atomic_write(args.output, value)
    print(f"wrote {len(value['items'])} gold-free retrieval records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
