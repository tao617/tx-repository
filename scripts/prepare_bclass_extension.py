#!/usr/bin/env python3
"""Compose one deployment with one canonical B-class extension condition."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from findver_agent.experiment_planner import (
    EXTENSION_CONDITION_ORDER,
    prepare_extension_plan as _prepare_extension_plan,
)
from findver_agent.runner import sha256_file


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
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


def prepare_extension_plan(
    manifest_path: Path,
    *,
    condition_id: str,
    matrix_id: str,
    deployment: Path | str,
    slot: str = "model_a",
) -> dict[str, Any]:
    return _prepare_extension_plan(
        manifest_path,
        condition_id=condition_id,
        matrix_id=matrix_id,
        deployment=deployment,
        slot=slot,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--condition", choices=EXTENSION_CONDITION_ORDER, required=True)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--slot", choices=("model_a", "model_b"), default="model_a")
    parser.add_argument("--deployment", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_extension_plan(
        args.manifest.resolve(strict=True),
        condition_id=args.condition,
        matrix_id=args.matrix_id,
        deployment=args.deployment,
        slot=args.slot,
    )
    _atomic_json(args.output.resolve(), plan)
    print(
        f"prepared extension run={plan['runs'][0]['run_id']} at {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
