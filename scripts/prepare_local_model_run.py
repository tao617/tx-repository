#!/usr/bin/env python3
"""Freeze one hash-bound public-development run for the 32K local model."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from findver_agent.config import AppConfig, load_config
from findver_agent.runner import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
CONFIG_RELATIVE = Path(
    "configs/local_models/deepseek_r1_distill_llama_8b_32k/"
    "M2_SELECTIVE_REVIEW_32K.yaml"
)
CONDITION_ID = "M2_SELECTIVE_REVIEW_32K"
PLAN_PURPOSE = "independent-local-model-public-development"


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError("output already exists; choose a new plan path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
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


def _task_path(task_name: str) -> Path:
    if not PLAIN_NAME.fullmatch(task_name) or not task_name.endswith(".jsonl"):
        raise ValueError("task must be a plain JSONL filename")
    path = (REPO_ROOT / "runtime_data" / "public" / task_name).resolve(strict=True)
    if path.parent != (REPO_ROOT / "runtime_data" / "public").resolve():
        raise ValueError("task must be directly under runtime_data/public")
    return path


def _retrieval_spec(config: AppConfig) -> tuple[Path, str, int]:
    if config.agent is None:
        raise ValueError("local 32K plan requires an Agent configuration")
    retrieval = config.agent.initial_retrieval
    if not retrieval.enabled or retrieval.retrieval_file is None:
        raise ValueError("local 32K plan requires enabled initial retrieval")
    container_path = retrieval.retrieval_file
    if container_path.parent != Path("/retrieval"):
        raise ValueError("local 32K retrieval must be a direct file under /retrieval")
    host_path = (
        REPO_ROOT / "runtime_data" / "retrieval" / container_path.name
    ).resolve(strict=True)
    if retrieval.retriever is None:
        raise ValueError("local 32K retrieval identity is incomplete")
    return host_path, retrieval.retriever, retrieval.top_k


def _validate_config(config: AppConfig, *, context_window: int) -> None:
    if config.run.backend_kind != "local" or config.run.mode != "agent":
        raise ValueError("local 32K configuration must use the local Agent backend")
    if (
        config.backend.model != "local-small-model"
        or config.backend.request_profile != "generic_openai"
        or config.backend.thinking is not None
    ):
        raise ValueError("local 32K configuration must use generic_openai without thinking")
    if config.backend.model_context_window_tokens != context_window:
        raise ValueError("model context window does not match the local 32K config")
    if config.generation.max_output_tokens != 1024:
        raise ValueError("local 32K output budget must remain 1024 tokens")
    if (
        config.generation.prompt_budget_tokens
        + config.generation.max_output_tokens
        > context_window
    ):
        raise ValueError("local 32K prompt and output budgets exceed the context window")
    agent = config.agent
    if agent is None or (
        agent.protocol_version,
        agent.exploration_steps,
        agent.finalization_steps,
        agent.review_steps,
        agent.review_policy,
        agent.concurrency,
    ) != ("v2", 6, 2, 1, "selective", 2):
        raise ValueError("local 32K config must retain the M2 6/2/1 controller at concurrency 2")
    retrieval = agent.initial_retrieval
    if (
        not retrieval.enabled
        or retrieval.retriever != "text-embedding-3-large"
        or retrieval.top_k != 10
        or not retrieval.preload_as_evidence
    ):
        raise ValueError("local 32K config must retain the frozen M2 Top-10 seed")


def prepare_plan(
    *,
    task_name: str,
    matrix_id: str,
    model_id: str,
    context_window: int,
    config_relative: Path | str = CONFIG_RELATIVE,
    condition_id: str = CONDITION_ID,
) -> dict[str, Any]:
    if not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("matrix_id must be a plain name")
    if not PLAIN_NAME.fullmatch(condition_id):
        raise ValueError("condition_id must be a plain name")
    model_id = model_id.strip()
    if not model_id or len(model_id) > 256:
        raise ValueError("model ID must be 1-256 characters")
    if context_window != 32768:
        raise ValueError("this independent local-model plan requires a 32768-token window")

    task_path = _task_path(task_name)
    config_relative = Path(config_relative)
    if config_relative.is_absolute() or config_relative.suffix != ".yaml":
        raise ValueError("local 32K config must be a relative YAML path")
    config_path = (REPO_ROOT / config_relative).resolve(strict=True)
    expected_root = (REPO_ROOT / "configs" / "local_models").resolve()
    if not config_path.is_relative_to(expected_root):
        raise ValueError("local 32K config is outside configs/local_models")
    config = load_config(config_path)
    _validate_config(config, context_window=context_window)
    retrieval_path, retriever, top_k = _retrieval_spec(config)
    if config.agent is None:
        raise AssertionError("validated Agent configuration is missing")

    commit = _git_commit()
    run_id = f"{matrix_id}-model_local-{condition_id}"
    thinking = None
    concurrency = config.agent.concurrency
    config_spec = {
        "path": str(config_path.relative_to(REPO_ROOT)),
        "sha256": sha256_file(config_path),
        "model_context_window_tokens": context_window,
        "request_profile": config.backend.request_profile,
        "thinking": thinking,
        "configured_concurrency": concurrency,
    }
    return {
        "schema_version": 2,
        "status": "prepared_not_executed",
        "matrix_id": matrix_id,
        "purpose": PLAN_PURPOSE,
        "evaluation_split": "dev_feedback",
        "authorization_scope": "public-development-runtime-only",
        "scorer_handoff_authorized": False,
        "holdout_or_hidden_authorized": False,
        "code_commit": commit,
        "task": {
            "path": str(task_path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(task_path),
        },
        "retrieval": {
            "path": str(retrieval_path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(retrieval_path),
            "retriever": retriever,
            "top_k": top_k,
        },
        "generation": config.generation.model_dump(mode="json"),
        "request_profiles": {
            "local": {"name": "generic_openai", "thinking": None}
        },
        "models": [
            {
                "slot": "model_local",
                "model_id": model_id,
                "backend_kind": "local",
                "model_context_window_tokens": context_window,
                "request_profile": "generic_openai",
                "thinking": None,
            }
        ],
        "runs": [
            {
                "slot": "model_local",
                "model_id": model_id,
                "backend_kind": "local",
                "model_context_window_tokens": context_window,
                "request_profile": "generic_openai",
                "thinking": None,
                "configured_concurrency": concurrency,
                "condition_id": condition_id,
                "run_id": run_id,
                "command": "run",
                "config": config_spec,
                "prompt_profile": "action_compatible_findver_v2",
                "maximum_model_calls": 9,
                "effective_retrieval_required": True,
                "long_context_scope": None,
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-context-window", required=True, type=int)
    parser.add_argument("--config", default=str(CONFIG_RELATIVE), type=Path)
    parser.add_argument("--condition-id", default=CONDITION_ID)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_plan(
        task_name=args.task,
        matrix_id=args.matrix_id,
        model_id=args.model,
        context_window=args.model_context_window,
        config_relative=args.config,
        condition_id=args.condition_id,
    )
    _atomic_json(args.output.resolve(), plan)
    print(f"prepared local-model run={plan['runs'][0]['run_id']} at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
