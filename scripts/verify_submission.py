#!/usr/bin/env python3
"""Validate a sealed archive without exposing prediction content."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from findver_agent.submission import verify_submission_archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    manifest, predictions = verify_submission_archive(args.archive)
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    print(
        f"valid run_id={manifest.run_id} predictions={len(predictions)} "
        f"sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
