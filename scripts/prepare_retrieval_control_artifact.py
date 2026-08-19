#!/usr/bin/env python3
"""Build Gold-free BM25 or fixed-k hybrid-RRF retrieval controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from findver_agent.report_store import ReportStore
from findver_agent.runner import load_public_tasks


RRF_K = 60
INPUT_TOP_K = 10
OUTPUT_TOP_K = 10
RANKED_RECORD_FIELDS = frozenset({"example_id", "report", "retrieved_paragraphs"})
Mode = Literal["bm25", "hybrid_rrf"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_ranked(paths: list[Path]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"{path} must contain a JSON array")
        for record in value:
            if not isinstance(record, dict) or set(record) != RANKED_RECORD_FIELDS:
                raise ValueError(f"{path} contains an invalid or gold-bearing record")
            example_id = record["example_id"]
            if not isinstance(example_id, str) or not example_id:
                raise ValueError(f"{path} contains an invalid example_id")
            if example_id in records:
                raise ValueError(f"duplicate ranked example_id: {example_id}")
            ranked = record["retrieved_paragraphs"]
            if not isinstance(ranked, list):
                raise ValueError(f"invalid ranked paragraphs: {example_id}")
            seen: set[int] = set()
            previous_score = math.inf
            for pair in ranked:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or type(pair[0]) is not int
                    or pair[0] < 0
                    or isinstance(pair[1], bool)
                    or not isinstance(pair[1], (int, float))
                    or not math.isfinite(float(pair[1]))
                    or pair[0] in seen
                    or float(pair[1]) > previous_score
                ):
                    raise ValueError(f"invalid ranked paragraphs: {example_id}")
                seen.add(pair[0])
                previous_score = float(pair[1])
            records[example_id] = record
    return records


def _ranked_ids(record: dict[str, Any]) -> list[int]:
    return [int(pair[0]) for pair in record["retrieved_paragraphs"][:INPUT_TOP_K]]


def _fuse(embedding_ids: list[int], bm25_ids: list[int]) -> list[int]:
    ranks = {
        "text-embedding-3-large": {
            paragraph_id: rank for rank, paragraph_id in enumerate(embedding_ids, 1)
        },
        "bm25": {
            paragraph_id: rank for rank, paragraph_id in enumerate(bm25_ids, 1)
        },
    }
    candidates = set(embedding_ids) | set(bm25_ids)

    def fusion_key(paragraph_id: int) -> tuple[float, int, int, int]:
        source_ranks = [
            source.get(paragraph_id, INPUT_TOP_K + 1) for source in ranks.values()
        ]
        score = sum(
            1.0 / (RRF_K + source[paragraph_id])
            for source in ranks.values()
            if paragraph_id in source
        )
        return (-score, min(source_ranks), max(source_ranks), paragraph_id)

    selected = sorted(candidates, key=fusion_key)[:OUTPUT_TOP_K]
    return sorted(selected)


def build(
    *,
    mode: Mode,
    tasks_path: Path,
    reports_path: Path,
    bm25_paths: list[Path],
    embedding_paths: list[Path] | None,
    source_commit: str,
) -> dict[str, Any]:
    if mode not in {"bm25", "hybrid_rrf"}:
        raise ValueError(f"unsupported retrieval-control mode: {mode}")
    if mode == "hybrid_rrf" and not embedding_paths:
        raise ValueError("hybrid_rrf requires embedding ranked sources")
    if mode == "bm25" and embedding_paths:
        raise ValueError("bm25 control does not accept embedding ranked sources")

    tasks = load_public_tasks(tasks_path)
    reports = ReportStore(reports_path)
    bm25 = _load_ranked(bm25_paths)
    embedding = _load_ranked(embedding_paths or [])
    items: dict[str, dict[str, Any]] = {}
    for task in tasks:
        try:
            bm25_record = bm25[task.example_id]
        except KeyError as error:
            raise ValueError(f"BM25 retrieval missing example_id: {task.example_id}") from error
        bm25_report = Path(bm25_record["report"]).name
        if bm25_report != task.report:
            raise ValueError(f"BM25 retrieval report mismatch: {task.example_id}")
        bm25_ids = _ranked_ids(bm25_record)
        if mode == "hybrid_rrf":
            try:
                embedding_record = embedding[task.example_id]
            except KeyError as error:
                raise ValueError(
                    f"embedding retrieval missing example_id: {task.example_id}"
                ) from error
            if Path(embedding_record["report"]).name != task.report:
                raise ValueError(
                    f"embedding retrieval report mismatch: {task.example_id}"
                )
            paragraph_ids = _fuse(_ranked_ids(embedding_record), bm25_ids)
        else:
            paragraph_ids = sorted(bm25_ids[:OUTPUT_TOP_K])

        session = reports.open_session(task.report)
        for paragraph_id in paragraph_ids:
            session.read(paragraph_id)
        items[task.example_id] = {
            "report": task.report,
            "retrieved_context": paragraph_ids,
        }

    source_paths = [*bm25_paths, *(embedding_paths or [])]
    metadata: dict[str, Any] = {
        "source_repo": "yilunzhao/FinDVer",
        "source_commit": source_commit,
        "source_files": [str(path) for path in source_paths],
        "source_sha256": {str(path): _sha256(path) for path in source_paths},
        "retriever": "bm25" if mode == "bm25" else "hybrid-rrf",
        "input_top_k": INPUT_TOP_K,
        "top_k": OUTPUT_TOP_K,
        "output_order": "document",
        "examples": len(items),
    }
    if mode == "hybrid_rrf":
        metadata.update(
            {
                "fusion": "reciprocal-rank-fusion",
                "rrf_k": RRF_K,
                "sources": ["text-embedding-3-large", "bm25"],
                "deduplicated": True,
            }
        )
    return {"metadata": metadata, "items": items}


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
    parser.add_argument("--mode", choices=("bm25", "hybrid_rrf"), required=True)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    parser.add_argument("--bm25", action="append", required=True, type=Path)
    parser.add_argument("--embedding", action="append", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = build(
        mode=args.mode,
        tasks_path=args.tasks,
        reports_path=args.reports,
        bm25_paths=args.bm25,
        embedding_paths=args.embedding,
        source_commit=args.source_commit,
    )
    atomic_write(args.output, value)
    print(f"wrote {len(value['items'])} Gold-free {args.mode} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
