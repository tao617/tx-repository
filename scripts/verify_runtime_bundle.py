#!/usr/bin/env python3
"""Validate a sealed submission and optionally the runtime build allowlist."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from findver_agent.submission import verify_submission_archive


ALLOWED_CONTEXT_ROOTS = {"README.md", "pyproject.toml", "src", "configs", "contracts", "deploy"}
BANNED_NAME_TERMS = {"gold", "feedback", "diagnostic", "scorer"}
ANSWER_MAPPING = re.compile(r"example_id\s*(?:==|in|:)\s*[^\n]{0,120}(?:entailed|refuted)", re.IGNORECASE)


def verify_context(root: Path) -> int:
    dockerignore = root / ".dockerignore"
    lines = [line.strip() for line in dockerignore.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    if not lines or lines[0] != "**":
        raise ValueError(".dockerignore must start with a deny-all rule")
    checked = 0
    for top in sorted(ALLOWED_CONTEXT_ROOTS):
        path = root / top
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else path.rglob("*")
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError(f"runtime allowlist contains a symlink: {candidate}")
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root)
            lower_parts = [part.lower() for part in relative.parts]
            if any(term in part for term in BANNED_NAME_TERMS for part in lower_parts):
                raise ValueError(f"runtime filename contains a banned term: {relative}")
            if candidate.suffix.lower() in {".py", ".md", ".yaml", ".yml", ".json"}:
                text = candidate.read_text(encoding="utf-8", errors="strict")
                if ANSWER_MAPPING.search(text):
                    raise ValueError(f"possible example-specific answer mapping: {relative}")
            checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--context", type=Path)
    args = parser.parse_args()
    manifest, predictions = verify_submission_archive(args.submission)
    context_files = verify_context(args.context) if args.context else None
    suffix = f" context_files={context_files}" if context_files is not None else ""
    print(f"verified submission run_id={manifest.run_id} predictions={len(predictions)}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

