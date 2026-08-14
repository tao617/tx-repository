#!/usr/bin/env python3
"""Reject public task files that expose gold-derived data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ALLOWED_FIELDS = {"example_id", "statement", "report"}
FORBIDDEN_FIELDS = {
    "entailment_label",
    "gold_label",
    "explanation",
    "relevant_context",
    "result",
    "correct",
    "extracted_label",
    "gold_explanation",
    "subset",
}


def load_records(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise ValueError("public data JSON must be an array")
        return value
    records: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON on line {line_number}: {error}") from error
    return records


def verify_records(records: list[Any]) -> None:
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {index} is not an object")
        keys = set(record)
        forbidden = sorted(keys & FORBIDDEN_FIELDS)
        if forbidden:
            raise ValueError(f"record {index} exposes forbidden fields: {forbidden}")
        if keys != ALLOWED_FIELDS:
            raise ValueError(f"record {index} fields must be exactly {sorted(ALLOWED_FIELDS)}")
        example_id = record["example_id"]
        if not isinstance(example_id, str) or not example_id:
            raise ValueError(f"record {index} has an invalid example_id")
        if example_id in seen:
            raise ValueError(f"duplicate example_id: {example_id}")
        seen.add(example_id)
        if not isinstance(record["statement"], str) or not record["statement"].strip():
            raise ValueError(f"record {example_id} has an invalid statement")
        report = record["report"]
        if not isinstance(report, str) or Path(report).name != report or not report.lower().endswith(".json"):
            raise ValueError(f"record {example_id} has an unsafe report filename")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True, type=Path)
    args = parser.parse_args()
    records = load_records(args.tasks)
    verify_records(records)
    print(f"verified public tasks: {len(records)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

