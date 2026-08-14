#!/usr/bin/env python3
"""Seal a completed Runtime run into the submission protocol."""

from __future__ import annotations

import argparse
from pathlib import Path

from findver_agent.submission import seal_submission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    digest = seal_submission(args.run_dir, args.output)
    print(f"sealed {args.output} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

