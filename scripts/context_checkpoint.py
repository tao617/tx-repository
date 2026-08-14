#!/usr/bin/env python3
"""Persist repository state after a bounded implementation phase."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "docs" / "STATE.yaml"
HANDOFF_PATH = ROOT / "docs" / "SESSION_HANDOFF.md"


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.rstrip()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def changed_files() -> list[str]:
    paths: list[str] = []
    for line in git("status", "--porcelain=v1").splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return sorted(set(paths))


def append_unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def load_state() -> dict[str, Any]:
    with STATE_PATH.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{STATE_PATH} must contain a YAML object")
    return loaded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--next", dest="next_action", required=True)
    parser.add_argument("--test-passed", action="append", default=[])
    parser.add_argument("--test-failed", action="append", default=[])
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--issue", action="append", default=[])
    args = parser.parse_args()

    state = load_state()
    commit = git("rev-parse", "HEAD")
    files = changed_files()
    unstaged = git("diff", "--stat")
    staged = git("diff", "--cached", "--stat")
    diff_summary = "\n".join(part for part in (staged, unstaged) if part).strip()
    if not diff_summary:
        diff_summary = "No tracked-file diff; see files_changed for untracked files."

    state.update(
        {
            "current_phase": args.phase,
            "last_completed_phase": args.phase,
            "last_git_commit": commit,
            "files_changed": files,
            "next_actions": [args.next_action],
            "last_updated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        }
    )
    state["tests_passed"] = append_unique(state.get("tests_passed", []), args.test_passed)
    state["tests_failed"] = append_unique(state.get("tests_failed", []), args.test_failed)
    state["decisions"] = append_unique(state.get("decisions", []), args.decision)
    state["known_issues"] = append_unique(state.get("known_issues", []), args.issue)

    yaml_text = yaml.safe_dump(state, sort_keys=False, allow_unicode=True)
    atomic_write(STATE_PATH, yaml_text)

    passed = "\n".join(f"- {item}" for item in args.test_passed) or "- None recorded in this phase"
    failed = "\n".join(f"- {item}" for item in args.test_failed) or "- None"
    handoff = f"""# Session Handoff

## Current state

Phase `{args.phase}` completed: {args.summary}

- Git commit at checkpoint start: `{commit}`
- Changed files: {len(files)}

## Diff summary

```text
{diff_summary}
```

## Tests passed

{passed}

## Tests failed or unavailable

{failed}

## Recovery protocol

```bash
pwd
git status --short
git log --oneline -10
cat AGENTS.md
cat docs/PROJECT_CONTRACT.md
cat docs/STATE.yaml
cat docs/SESSION_HANDOFF.md
find docs/adr -maxdepth 1 -type f -print | sort
pytest -q
```

## Next action

{args.next_action}
"""
    atomic_write(HANDOFF_PATH, handoff)
    print(f"checkpointed phase={args.phase} commit={commit} files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

