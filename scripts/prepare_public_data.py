#!/usr/bin/env python3
"""Split a gold-bearing FinDVer JSON array into public tasks and private gold."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]


def normalise_label(value: Any) -> str:
    if value is True or value == "entailed":
        return "entailed"
    if value is False or value == "refuted":
        return "refuted"
    raise ValueError(f"unsupported entailment label: {value!r}")


def validate_report_name(value: Any) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ValueError(f"invalid report filename: {value!r}")
    if not value.lower().endswith(".json"):
        raise ValueError(f"report must be JSON: {value!r}")
    return value


def split_records(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {index} is not an object")
        example_id = record.get("example_id")
        if not isinstance(example_id, str) or not example_id:
            raise ValueError(f"record {index} has an invalid example_id")
        if example_id in seen:
            raise ValueError(f"duplicate example_id: {example_id}")
        seen.add(example_id)
        statement = record.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"record {example_id} has an invalid statement")
        subset = record.get("subset")
        if subset not in {"ie", "numeric", "knowledge"}:
            raise ValueError(f"record {example_id} has an invalid subset")
        public.append(
            {
                "example_id": example_id,
                "statement": statement,
                "report": validate_report_name(record.get("report")),
            }
        )
        gold.append(
            {
                "example_id": example_id,
                "label": normalise_label(record.get("entailment_label")),
                "subset": subset,
            }
        )
    return public, gold


def atomic_jsonl(path: Path, records: list[dict[str, Any]], mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def ensure_private_path_is_outside_repository(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("private gold output must be outside the Agent repository")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--public-tasks", required=True, type=Path)
    parser.add_argument("--private-gold", required=True, type=Path)
    args = parser.parse_args()

    ensure_private_path_is_outside_repository(args.private_gold)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    if not isinstance(source, list):
        raise ValueError("source dataset must be a JSON array")
    public, gold = split_records(source)
    atomic_jsonl(args.public_tasks, public, 0o644)
    atomic_jsonl(args.private_gold, gold, 0o600)
    print(f"prepared public={len(public)} private={len(gold)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

