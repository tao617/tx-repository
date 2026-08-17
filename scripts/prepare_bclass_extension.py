#!/usr/bin/env python3
"""Freeze one hash-bound, Model-A-only B-class development extension plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

from findver_agent.config import AppConfig, load_config
from findver_agent.runner import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
EXTENSIONS = {
    "RAG3_SEEDED": {
        "config": "configs/bclass/ablations/RAG3_SEEDED.yaml",
        "prompt_profile": "action_compatible_findver_v2",
        "top_k": 3,
        "mode": "agent",
    },
    "RAG5_SEEDED": {
        "config": "configs/bclass/ablations/RAG5_SEEDED.yaml",
        "prompt_profile": "action_compatible_findver_v2",
        "top_k": 5,
        "mode": "agent",
    },
    "BITER2_RAG10": {
        "config": "configs/bclass/ablations/BITER2_RAG10.yaml",
        "prompt_profile": "findver_cot_json_fixed_loop",
        "top_k": 10,
        "mode": "iterative_rag",
        "retrieval_rounds": 2,
    },
    "M2_BUDGET4": {
        "config": "configs/bclass/ablations/M2_BUDGET4.yaml",
        "prompt_profile": "action_compatible_findver_v2",
        "top_k": 10,
        "mode": "agent",
        "exploration_steps": 4,
    },
}
EXPECTED_API_PROFILE = {
    "name": "deepseek_v4_openai",
    "thinking": {"type": "disabled"},
}


def _load_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return value


def _repository_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("manifest paths must be non-empty strings")
    path = (REPO_ROOT / value).resolve()
    if REPO_ROOT not in path.parents:
        raise ValueError(f"path is outside repository: {value}")
    return path


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


def _configured_concurrency(config: AppConfig) -> int:
    section = config.agent or config.iterative_rag
    if section is None:
        raise ValueError("extension configuration method section is missing")
    return section.concurrency


def _retrieval_spec(config: AppConfig) -> tuple[Path, str, int]:
    if config.agent is not None:
        retrieval = config.agent.initial_retrieval
        if not retrieval.enabled or retrieval.retrieval_file is None:
            raise ValueError("Agent extension requires enabled initial retrieval")
        container_path = retrieval.retrieval_file
        retriever = retrieval.retriever
        top_k = retrieval.top_k
    elif config.iterative_rag is not None:
        container_path = config.iterative_rag.retrieval_file
        retriever = config.iterative_rag.retriever
        top_k = config.iterative_rag.top_k
    else:
        raise ValueError("extension configuration does not use retrieval")
    if container_path.parent != Path("/retrieval"):
        raise ValueError("extension retrieval must be a direct file under /retrieval")
    host_path = (
        REPO_ROOT / "runtime_data" / "retrieval" / container_path.name
    ).resolve(strict=True)
    return host_path, retriever, top_k


def _maximum_model_calls(config: AppConfig) -> int:
    if config.agent is not None:
        return (
            config.agent.exploration_steps
            + config.agent.finalization_steps
            + config.agent.review_steps
        )
    if config.iterative_rag is not None:
        return (
            config.iterative_rag.retrieval_rounds
            + config.iterative_rag.finalization_steps
        )
    raise ValueError("extension configuration method section is missing")


def prepare_extension_plan(
    manifest_path: Path,
    *,
    condition_id: str,
    matrix_id: str,
    model_id: str,
    context_window: int,
) -> dict[str, Any]:
    if condition_id not in EXTENSIONS:
        raise ValueError("unsupported B-class extension condition")
    if not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("matrix_id must be a plain name")
    model_id = model_id.strip()
    if not model_id or len(model_id) > 256:
        raise ValueError("model ID must be 1-256 characters")
    if not 8192 <= context_window <= 1_000_000:
        raise ValueError("model context window must be 8192-1000000 tokens")

    manifest = _load_object(manifest_path)
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported B-class manifest schema_version")
    if manifest.get("evaluation_split") != "dev_feedback":
        raise ValueError("B-class extensions are dev_feedback only")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("tracked B-class templates must not authorize execution")
    if manifest.get("request_profiles", {}).get("api") != EXPECTED_API_PROFILE:
        raise ValueError("extension requires the frozen disabled-thinking API profile")
    task = manifest.get("task")
    generation = manifest.get("generation")
    if not isinstance(task, dict) or not isinstance(generation, dict):
        raise ValueError("manifest task and generation sections are required")
    task_path = _repository_path(task.get("path"))
    task_hash = sha256_file(task_path)
    if task_hash != task.get("sha256"):
        raise ValueError("public task SHA256 does not match the manifest")

    extension = EXTENSIONS[condition_id]
    config_path = _repository_path(extension["config"])
    if config_path.parent != (REPO_ROOT / "configs" / "bclass" / "ablations"):
        raise ValueError("extension config must be under configs/bclass/ablations")
    config = load_config(config_path)
    if config.run.backend_kind != "api" or config.run.mode != extension["mode"]:
        raise ValueError("extension config backend or mode does not match")
    if config.generation.model_dump(mode="json") != generation:
        raise ValueError("extension generation differs from the manifest")
    thinking = (
        config.backend.thinking.model_dump(mode="json")
        if config.backend.thinking is not None
        else None
    )
    if (
        config.backend.request_profile != EXPECTED_API_PROFILE["name"]
        or thinking != EXPECTED_API_PROFILE["thinking"]
    ):
        raise ValueError("extension config request profile differs from the manifest")
    if config.backend.model_context_window_tokens != context_window:
        raise ValueError("model context window does not match extension config")
    concurrency = _configured_concurrency(config)
    if concurrency != 32:
        raise ValueError("extension concurrency must be frozen at 32")
    retrieval_path, retriever, top_k = _retrieval_spec(config)
    if retriever != "text-embedding-3-large" or top_k != extension["top_k"]:
        raise ValueError("extension retrieval identity does not match its condition")
    expected_rounds = extension.get("retrieval_rounds")
    if expected_rounds is not None and (
        config.iterative_rag is None
        or config.iterative_rag.retrieval_rounds != expected_rounds
    ):
        raise ValueError("BITER extension retrieval rounds do not match")
    expected_exploration_steps = extension.get("exploration_steps")
    if expected_exploration_steps is not None and (
        config.agent is None
        or config.agent.exploration_steps != expected_exploration_steps
    ):
        raise ValueError("Agent extension exploration budget does not match")
    if "deepseek-v4" in model_id.casefold() and thinking != {"type": "disabled"}:
        raise ValueError("DeepSeek V4 requires disabled thinking")

    commit = _git_commit()
    run_id = f"{matrix_id}-model_a-{condition_id}"
    config_spec = {
        "path": str(config_path.relative_to(REPO_ROOT)),
        "sha256": sha256_file(config_path),
        "model_context_window_tokens": context_window,
        "request_profile": config.backend.request_profile,
        "thinking": thinking,
        "configured_concurrency": concurrency,
    }
    command = "run" if config.agent is not None else "iterative-rag"
    return {
        "schema_version": 2,
        "status": "prepared_not_executed",
        "matrix_id": matrix_id,
        "purpose": "bclass-model-a-development-extension",
        "evaluation_split": "dev_feedback",
        "manifest_sha256": sha256_file(manifest_path),
        "code_commit": commit,
        "task": {
            "path": str(task_path.relative_to(REPO_ROOT)),
            "sha256": task_hash,
        },
        "retrieval": {
            "path": str(retrieval_path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(retrieval_path),
            "retriever": retriever,
            "top_k": top_k,
        },
        "generation": generation,
        "request_profiles": manifest["request_profiles"],
        "models": [
            {
                "slot": "model_a",
                "model_id": model_id,
                "backend_kind": "api",
                "model_context_window_tokens": context_window,
                "request_profile": config.backend.request_profile,
                "thinking": thinking,
            }
        ],
        "runs": [
            {
                "slot": "model_a",
                "model_id": model_id,
                "backend_kind": "api",
                "model_context_window_tokens": context_window,
                "request_profile": config.backend.request_profile,
                "thinking": thinking,
                "configured_concurrency": concurrency,
                "condition_id": condition_id,
                "run_id": run_id,
                "command": command,
                "config": config_spec,
                "prompt_profile": extension["prompt_profile"],
                "maximum_model_calls": _maximum_model_calls(config),
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--condition", choices=tuple(EXTENSIONS), required=True)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--model-a", required=True)
    parser.add_argument("--model-a-context-window", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_extension_plan(
        args.manifest.resolve(strict=True),
        condition_id=args.condition,
        matrix_id=args.matrix_id,
        model_id=args.model_a,
        context_window=args.model_a_context_window,
    )
    _atomic_json(args.output.resolve(), plan)
    print(
        f"prepared extension run={plan['runs'][0]['run_id']} at {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
