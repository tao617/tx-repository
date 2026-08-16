#!/usr/bin/env python3
"""Select one public IE, MATH, and KNOW task for the real-API pilot."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from findver_agent.runner import load_public_tasks


PREFIXES = ("ie-", "numeric-", "knowledge-")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    tasks = load_public_tasks(args.tasks)
    selected = []
    for prefix in PREFIXES:
        try:
            selected.append(next(task for task in tasks if task.example_id.startswith(prefix)))
        except StopIteration as error:
            raise ValueError(f"task file has no example with prefix {prefix}") from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{args.output.name}.", dir=args.output.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for task in selected:
                handle.write(task.model_dump_json())
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    print("pilot examples:", ", ".join(task.example_id for task in selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
