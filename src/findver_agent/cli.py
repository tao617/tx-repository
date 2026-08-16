"""Command-line entry point for isolated Runtime execution."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from findver_agent.baseline import BaselineRunner
from findver_agent.config import load_config
from findver_agent.iterative_rag import IterativeRAGRunner
from findver_agent.model_backends.openai_compatible import OpenAICompatibleBackend
from findver_agent.orchestrator import AgentOrchestrator
from findver_agent.report_store import ReportStore
from findver_agent.runner import run_batch


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="findver-agent")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("run", "baseline", "iterative-rag"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--tasks", required=True, type=Path)
        command.add_argument("--reports", required=True, type=Path)
        command.add_argument("--run-dir", required=True, type=Path)
    return root


async def execute(args: argparse.Namespace) -> Path:
    config = load_config(args.config)
    expected_mode = {
        "run": "agent",
        "baseline": "baseline",
        "iterative-rag": "iterative_rag",
    }[args.command]
    if config.run.mode != expected_mode:
        raise ValueError(f"configuration mode must be {expected_mode}")
    backend = OpenAICompatibleBackend(
        base_url=config.backend.base_url,
        model=config.backend.model,
        timeout_seconds=config.backend.timeout_seconds,
        max_retries=config.backend.max_retries,
    )
    try:
        reports = ReportStore(args.reports)
        if expected_mode == "agent":
            if config.agent is None:  # validation already enforces this
                raise ValueError("agent configuration is missing")
            engine = AgentOrchestrator(
                backend=backend,
                generation=config.generation,
                agent_config=config.agent,
                report_store=reports,
                run_dir=args.run_dir,
            )
        elif expected_mode == "baseline":
            if config.baseline is None:
                raise ValueError("baseline configuration is missing")
            engine = BaselineRunner(
                backend=backend,
                generation=config.generation,
                baseline_config=config.baseline,
                report_store=reports,
                run_dir=args.run_dir,
            )
        else:
            if config.iterative_rag is None:
                raise ValueError("iterative_rag configuration is missing")
            engine = IterativeRAGRunner(
                backend=backend,
                generation=config.generation,
                iterative_config=config.iterative_rag,
                report_store=reports,
                run_dir=args.run_dir,
            )
        return await run_batch(
            tasks_path=args.tasks,
            config_path=args.config,
            run_dir=args.run_dir,
            mode=expected_mode,
            model=config.backend.model,
            backend_kind=config.run.backend_kind,
            answer=engine.run_question,
        )
    finally:
        await backend.aclose()


def main() -> int:
    args = parser().parse_args()
    predictions = asyncio.run(execute(args))
    print(predictions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
