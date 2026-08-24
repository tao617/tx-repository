"""Command-line entry point for the additive generic evaluation agent."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import yaml

from findver_agent.generic.config import load_generic_config
from findver_agent.generic.engine import GenericAgent
from findver_agent.generic.models import GenericTaskProfile
from findver_agent.generic.runner import run_generic_batch
from findver_agent.model_backends.openai_compatible import OpenAICompatibleBackend


def load_task_profile(path: Path) -> GenericTaskProfile:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("task profile must contain a YAML object")
    return GenericTaskProfile.model_validate(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="generic-eval-agent")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--profile", required=True, type=Path)
    run.add_argument("--tasks", required=True, type=Path)
    run.add_argument("--run-dir", required=True, type=Path)
    return root


async def execute(args: argparse.Namespace) -> Path:
    if args.command != "run":
        raise ValueError(f"unsupported generic command: {args.command}")
    config = load_generic_config(args.config)
    profile = load_task_profile(args.profile)
    backend = OpenAICompatibleBackend(
        base_url=config.backend.base_url,
        model=config.backend.model,
        timeout_seconds=config.backend.timeout_seconds,
        max_retries=config.backend.max_retries,
        model_context_window_tokens=config.backend.model_context_window_tokens,
        transport_profile=config.backend.transport_profile,
        thinking_type=(
            config.backend.thinking.type
            if config.backend.thinking is not None
            else None
        ),
        response_format=config.backend.response_format,
        rate_limit_requests_per_minute=(
            config.backend.rate_limit.requests_per_minute
            if config.backend.rate_limit is not None
            else None
        ),
        rate_limit_tokens_per_minute=(
            config.backend.rate_limit.tokens_per_minute
            if config.backend.rate_limit is not None
            else None
        ),
    )
    try:
        engine = GenericAgent(
            backend=backend,
            generation=config.generation,
            agent_config=config.agent,
            profile=profile,
            run_dir=args.run_dir,
        )
        return await run_generic_batch(
            tasks_path=args.tasks,
            config_path=args.config,
            profile_path=args.profile,
            profile=profile,
            run_dir=args.run_dir,
            model=config.backend.model,
            backend_kind=config.backend_kind,
            concurrency=config.agent.concurrency,
            answer=engine.run_task,
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
