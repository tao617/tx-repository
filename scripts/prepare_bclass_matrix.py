#!/usr/bin/env python3
"""Compose one or two deployments with the seven canonical B-class conditions."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from findver_agent.experiment_planner import prepare_matrix_plan
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


def prepare_plan(
    manifest_path: Path,
    *,
    deployment_a: Path | str,
    deployment_b: Path | str | None = None,
) -> dict[str, Any]:
    return prepare_matrix_plan(
        manifest_path,
        deployment_a=deployment_a,
        deployment_b=deployment_b,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--deployment-a", required=True, type=Path)
    parser.add_argument("--deployment-b", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_plan(
        args.manifest.resolve(strict=True),
        deployment_a=args.deployment_a,
        deployment_b=args.deployment_b,
    )
    _atomic_json(args.output.resolve(), plan)
    print(
        f"prepared {len(plan['runs'])} non-executing B-class runs at {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
