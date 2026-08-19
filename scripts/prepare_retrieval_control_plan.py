#!/usr/bin/env python3
"""Prepare one non-executing schema-v3 retrieval-control plan."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from findver_agent.retrieval_control_planner import (
    CONTROL_ORDER,
    prepare_control_plan,
)


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    if path.exists():
        raise ValueError("output already exists; choose a new plan path")
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
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--condition", required=True, choices=CONTROL_ORDER)
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--slot", required=True, choices=("model_a", "model_b"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_control_plan(
        args.manifest.resolve(strict=True),
        condition_id=args.condition,
        deployment_path=args.deployment,
        slot=args.slot,
    )
    _atomic_json(args.output.resolve(), plan)
    print(f"prepared non-executing retrieval-control plan at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
