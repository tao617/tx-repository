#!/usr/bin/env python3
"""Build every first-pass LC Agent prompt without making a model request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from findver_agent.config import load_config
from findver_agent.model_backends.base import context_window_metadata
from findver_agent.prompt_builder import PromptBuilder
from findver_agent.report_format import format_full_report
from findver_agent.report_store import ReportStore
from findver_agent.runner import load_public_tasks, sha256_file
from findver_agent.state import QuestionState


def _corpus_sha256(reports: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for report_name in sorted(reports):
        digest.update(report_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(reports[report_name].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def preflight(
    *,
    config_path: Path,
    tasks_path: Path,
    reports_path: Path,
    expected_examples: int,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config.agent is None or not config.agent.long_context.enabled:
        raise ValueError("preflight requires an enabled Agent long_context config")
    if config.agent.initial_retrieval.enabled:
        raise ValueError("LC Agent preflight forbids effective initial retrieval")
    tasks = load_public_tasks(tasks_path)
    if len(tasks) != expected_examples:
        raise ValueError(
            f"preflight expected {expected_examples} tasks, found {len(tasks)}"
        )
    reports = ReportStore(reports_path)
    builder = PromptBuilder(config.generation, config.agent)
    overflow_count = 0
    estimated_input_total = 0
    maximum_input = 0
    maximum_total = 0
    report_serializations: dict[str, str] = {}

    for task in tasks:
        session = reports.open_session(task.report)
        serialized = format_full_report(session)
        prior = report_serializations.setdefault(task.report, serialized)
        if prior != serialized:  # pragma: no cover - one path cannot vary in one process
            raise ValueError("report serialization changed during preflight")
        state = QuestionState.create(
            task,
            config.agent.max_steps,
            protocol_version="v2",
            exploration_steps=config.agent.exploration_steps,
            finalization_steps=config.agent.finalization_steps,
            review_steps=config.agent.review_steps,
        )
        state.phase = "exploration"
        state.exploration_step = 1
        state.step = 1
        state.usage.model_calls = 1
        state.remaining_steps = (
            config.agent.exploration_steps
            - 1
            + config.agent.finalization_steps
            + config.agent.review_steps
        )
        messages = builder.build(state, full_report_preview=serialized)
        context = context_window_metadata(
            messages,
            max_output_tokens=config.generation.max_output_tokens,
            model_context_window_tokens=config.backend.model_context_window_tokens,
        )
        estimated_input = int(context["estimated_input_tokens"])
        estimated_total = int(context["estimated_total_tokens"])
        estimated_input_total += estimated_input
        maximum_input = max(maximum_input, estimated_input)
        maximum_total = max(maximum_total, estimated_total)
        overflow_count += int(context["overflow_status"] == "estimated_overflow")

    return {
        "schema_version": 1,
        "condition_id": "LC_AGENT_FIRSTPASS",
        "status": "offline_preflight",
        "model_requests_made": 0,
        "examples": len(tasks),
        "full_report_injection_requests": len(tasks),
        "estimated_overflow_count": overflow_count,
        "estimated_input_tokens_total": estimated_input_total,
        "maximum_estimated_input_tokens": maximum_input,
        "maximum_estimated_total_tokens": maximum_total,
        "max_output_tokens": config.generation.max_output_tokens,
        "model_context_window_tokens": config.backend.model_context_window_tokens,
        "config_sha256": sha256_file(config_path),
        "public_tasks_sha256": sha256_file(tasks_path),
        "report_corpus_sha256": _corpus_sha256(report_serializations),
        "unique_reports": len(report_serializations),
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError("preflight output already exists")
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
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    parser.add_argument("--expected-examples", type=int, default=700)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = preflight(
        config_path=args.config.resolve(strict=True),
        tasks_path=args.tasks.resolve(strict=True),
        reports_path=args.reports.resolve(strict=True),
        expected_examples=args.expected_examples,
    )
    _atomic_json(args.output.resolve(), result)
    print(
        f"preflighted examples={result['examples']} "
        f"overflows={result['estimated_overflow_count']}",
        flush=True,
    )
    return 0 if result["estimated_overflow_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
