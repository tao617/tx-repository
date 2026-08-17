#!/usr/bin/env python3
"""Validate and freeze a non-executing one- or two-model B-class run plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml

from findver_agent.config import AppConfig, load_config
from findver_agent.runner import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]
CONDITION_ORDER = (
    "BLC_FINDVER_COT",
    "BRAG10_FINDVER_COT",
    "BITER_RAG10",
    "A_SCRATCH",
    "M0_RAG10_SEEDED",
    "M1_BUDGET_AWARE",
    "M2_SELECTIVE_REVIEW",
)
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
EXPECTED_REQUEST_PROFILES = {
    "api": {
        "name": "deepseek_v4_openai",
        "thinking": {"type": "disabled"},
    },
    "local": {"name": "generic_openai", "thinking": None},
}
PLACEHOLDER_MODEL_IDS = frozenset(
    {"tbd", "todo", "placeholder", "pending", "unknown", "n/a", "na"}
)


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


def _method_section(config: AppConfig) -> dict[str, Any]:
    if config.run.mode == "baseline" and config.baseline is not None:
        return config.baseline.model_dump(mode="json")
    if config.run.mode == "agent" and config.agent is not None:
        return config.agent.model_dump(mode="json")
    if config.run.mode == "iterative_rag" and config.iterative_rag is not None:
        return config.iterative_rag.model_dump(mode="json")
    raise ValueError("configuration mode section is missing")


def _command(config: AppConfig) -> str:
    return {
        "baseline": "baseline",
        "agent": "run",
        "iterative_rag": "iterative-rag",
    }[config.run.mode]


def _maximum_model_calls(config: AppConfig) -> int:
    if config.baseline is not None:
        return 1
    if config.iterative_rag is not None:
        return (
            config.iterative_rag.retrieval_rounds
            + config.iterative_rag.finalization_steps
        )
    if config.agent is None:
        raise ValueError("Agent configuration is missing")
    if config.agent.protocol_version == "v1":
        return config.agent.max_steps
    return (
        config.agent.exploration_steps
        + config.agent.finalization_steps
        + config.agent.review_steps
    )


def _configured_concurrency(config: AppConfig) -> int:
    section = config.baseline or config.agent or config.iterative_rag
    if section is None:
        raise ValueError("configuration mode section is missing")
    return section.concurrency


def _profile_spec(config: AppConfig) -> dict[str, Any]:
    return {
        "name": config.backend.request_profile,
        "thinking": (
            config.backend.thinking.model_dump(mode="json")
            if config.backend.thinking is not None
            else None
        ),
    }


def _model_id(value: object, *, slot: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{slot} model ID must be an explicit string")
    model_id = value.strip()
    if not model_id or len(model_id) > 256:
        raise ValueError(f"{slot} model ID must be 1-256 characters")
    if slot == "model B" and model_id.casefold() in PLACEHOLDER_MODEL_IDS:
        raise ValueError("model B cannot be a placeholder or pending value")
    return model_id


def _validate_condition_shape(condition_id: str, config: AppConfig) -> None:
    if condition_id == "BLC_FINDVER_COT":
        valid = (
            config.baseline is not None
            and config.baseline.prompt_type == "findver_cot_json"
            and config.baseline.retrieval == "none"
        )
    elif condition_id == "BRAG10_FINDVER_COT":
        valid = (
            config.baseline is not None
            and config.baseline.prompt_type == "findver_cot_json"
            and config.baseline.retrieval == "fixed_retrieval"
            and config.baseline.retriever == "text-embedding-3-large"
            and config.baseline.top_k == 10
        )
    elif condition_id == "BITER_RAG10":
        valid = (
            config.iterative_rag is not None
            and config.iterative_rag.retriever == "text-embedding-3-large"
            and config.iterative_rag.top_k == 10
            and config.iterative_rag.retrieval_rounds == 3
        )
    elif condition_id == "A_SCRATCH":
        valid = (
            config.agent is not None
            and config.agent.protocol_version == "v2"
            and not config.agent.initial_retrieval.enabled
            and config.agent.review_policy == "selective"
        )
    elif condition_id == "M0_RAG10_SEEDED":
        valid = (
            config.agent is not None
            and config.agent.protocol_version == "v1"
            and config.agent.initial_retrieval.enabled
            and config.agent.initial_retrieval.top_k == 10
        )
    elif condition_id == "M1_BUDGET_AWARE":
        valid = (
            config.agent is not None
            and config.agent.protocol_version == "v2"
            and config.agent.initial_retrieval.enabled
            and config.agent.review_policy == "none"
            and config.agent.review_steps == 0
        )
    elif condition_id == "M2_SELECTIVE_REVIEW":
        valid = (
            config.agent is not None
            and config.agent.protocol_version == "v2"
            and config.agent.initial_retrieval.enabled
            and config.agent.review_policy == "selective"
            and config.agent.review_steps == 1
        )
    else:  # pragma: no cover - order validation rejects this first
        valid = False
    if not valid:
        raise ValueError(f"{condition_id} configuration does not match its method")


def freeze_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_object(path)
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported B-class manifest schema_version")
    matrix_id = manifest.get("matrix_id")
    if not isinstance(matrix_id, str) or not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("matrix_id must be a plain name")
    if manifest.get("evaluation_split") not in {
        "dev_feedback",
        "dev_holdout",
        "final_hidden",
    }:
        raise ValueError("evaluation_split must follow the frozen lifecycle")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("tracked B-class templates must not authorize execution")

    task = manifest.get("task")
    retrieval = manifest.get("retrieval")
    generation = manifest.get("generation")
    request_profiles = manifest.get("request_profiles")
    conditions = manifest.get("conditions")
    if not all(isinstance(item, dict) for item in (task, retrieval, generation)):
        raise ValueError("task, retrieval, and generation sections are required")
    if not isinstance(conditions, list):
        raise ValueError("conditions must be a list")
    if request_profiles != EXPECTED_REQUEST_PROFILES:
        raise ValueError(
            "B-class request_profiles must explicitly freeze DeepSeek thinking disabled and generic local transport"
        )
    condition_ids = [
        item.get("condition_id") for item in conditions if isinstance(item, dict)
    ]
    if condition_ids != list(CONDITION_ORDER):
        raise ValueError("conditions must use the fixed B-class order")

    task_path = _repository_path(task["path"])
    retrieval_path = _repository_path(retrieval["path"])
    task_hash = sha256_file(task_path)
    retrieval_hash = sha256_file(retrieval_path)
    if task_hash != task.get("sha256"):
        raise ValueError("public task SHA256 does not match the manifest")
    if retrieval_hash != retrieval.get("sha256"):
        raise ValueError("retrieval SHA256 does not match the manifest")
    if retrieval.get("retriever") != "text-embedding-3-large" or retrieval.get(
        "top_k"
    ) != 10:
        raise ValueError("main B-class matrix requires embedding top-10 retrieval")

    frozen_conditions: list[dict[str, Any]] = []
    for item in conditions:
        condition_id = str(item["condition_id"])
        configs: dict[str, AppConfig] = {}
        paths: dict[str, Path] = {}
        for backend_kind in ("api", "local"):
            config_path = _repository_path(item[f"{backend_kind}_config"])
            config = load_config(config_path)
            if config.run.backend_kind != backend_kind:
                raise ValueError(
                    f"{condition_id} {backend_kind} config has the wrong backend kind"
                )
            if config.generation.model_dump(mode="json") != generation:
                raise ValueError(
                    f"{condition_id} {backend_kind} generation differs from the manifest"
                )
            if _profile_spec(config) != request_profiles[backend_kind]:
                raise ValueError(
                    f"{condition_id} {backend_kind} request profile differs from the manifest"
                )
            if _configured_concurrency(config) != 32:
                raise ValueError(
                    f"{condition_id} {backend_kind} concurrency must be frozen at 32"
                )
            _validate_condition_shape(condition_id, config)
            configs[backend_kind] = config
            paths[backend_kind] = config_path
        if configs["api"].run.mode != configs["local"].run.mode:
            raise ValueError(f"{condition_id} API/local modes differ")
        if _method_section(configs["api"]) != _method_section(configs["local"]):
            raise ValueError(f"{condition_id} API/local method settings differ")
        frozen_conditions.append(
            {
                "condition_id": condition_id,
                "prompt_profile": item["prompt_profile"],
                "command": _command(configs["api"]),
                "maximum_model_calls": _maximum_model_calls(configs["api"]),
                "configs": {
                    backend_kind: {
                        "path": str(paths[backend_kind].relative_to(REPO_ROOT)),
                        "sha256": sha256_file(paths[backend_kind]),
                        "model_context_window_tokens": (
                            configs[
                                backend_kind
                            ].backend.model_context_window_tokens
                        ),
                        "request_profile": configs[
                            backend_kind
                        ].backend.request_profile,
                        "thinking": _profile_spec(configs[backend_kind])[
                            "thinking"
                        ],
                        "configured_concurrency": _configured_concurrency(
                            configs[backend_kind]
                        ),
                    }
                    for backend_kind in ("api", "local")
                },
            }
        )

    commit = _git_commit()
    requested_commit = manifest.get("code_commit", "auto")
    if requested_commit not in {"auto", commit}:
        raise ValueError("manifest code_commit does not match HEAD")
    return {
        "matrix_id": matrix_id,
        "purpose": manifest.get("purpose"),
        "evaluation_split": manifest["evaluation_split"],
        "manifest_sha256": sha256_file(path),
        "code_commit": commit,
        "task": {"path": str(task_path.relative_to(REPO_ROOT)), "sha256": task_hash},
        "retrieval": {
            "path": str(retrieval_path.relative_to(REPO_ROOT)),
            "sha256": retrieval_hash,
            "retriever": retrieval["retriever"],
            "top_k": retrieval["top_k"],
        },
        "generation": generation,
        "request_profiles": request_profiles,
        "conditions": frozen_conditions,
    }


def prepare_plan(
    manifest_path: Path,
    *,
    model_a: str,
    backend_a: Literal["api", "local"],
    context_window_a: int,
    model_b: str | None = None,
    backend_b: Literal["api", "local"] | None = None,
    context_window_b: int | None = None,
) -> dict[str, Any]:
    model_a = _model_id(model_a, slot="model A")
    model_b_group = (model_b, backend_b, context_window_b)
    provided_b = [value is not None for value in model_b_group]
    if any(provided_b) and not all(provided_b):
        raise ValueError(
            "model B ID, backend, and context window must be provided together or all omitted"
        )
    validated_model_b = (
        _model_id(model_b, slot="model B") if all(provided_b) else None
    )
    if validated_model_b is not None and model_a == validated_model_b:
        raise ValueError("model A and model B IDs must be different")
    if not 8192 <= context_window_a <= 1_000_000:
        raise ValueError("model A context window must be 8192-1000000 tokens")
    if context_window_b is not None and not 8192 <= context_window_b <= 1_000_000:
        raise ValueError("model B context window must be 8192-1000000 tokens")
    frozen = freeze_manifest(manifest_path)
    matrix_id = frozen["matrix_id"]
    models: list[tuple[str, str, Literal["api", "local"], int]] = [
        ("model_a", model_a, backend_a, context_window_a)
    ]
    if validated_model_b is not None:
        if backend_b is None or context_window_b is None:  # closed by group check
            raise ValueError("model B group is incomplete")
        models.append(
            ("model_b", validated_model_b, backend_b, context_window_b)
        )
    else:
        matrix_id = f"{matrix_id}-single-model-a"
        if len(matrix_id) > 256 or not PLAIN_NAME.fullmatch(matrix_id):
            raise ValueError("single-model matrix ID is invalid")
    runs = []
    for slot, model_id, backend_kind, context_window in models:
        configured_windows = {
            condition["configs"][backend_kind][
                "model_context_window_tokens"
            ]
            for condition in frozen["conditions"]
        }
        if configured_windows != {context_window}:
            raise ValueError(
                f"{slot} context window does not match selected B-class configs"
            )
        configured_profiles = {
            (
                condition["configs"][backend_kind]["request_profile"],
                json.dumps(
                    condition["configs"][backend_kind]["thinking"],
                    sort_keys=True,
                ),
            )
            for condition in frozen["conditions"]
        }
        if len(configured_profiles) != 1:
            raise ValueError(f"{slot} request profile differs across conditions")
        request_profile, serialized_thinking = next(iter(configured_profiles))
        thinking = json.loads(serialized_thinking)
        if "deepseek-v4" in model_id.casefold() and (
            backend_kind != "api"
            or request_profile != "deepseek_v4_openai"
            or thinking != {"type": "disabled"}
        ):
            raise ValueError(
                f"{slot} DeepSeek V4 requires the explicit disabled API request profile"
            )
        for condition in frozen["conditions"]:
            runs.append(
                {
                    "slot": slot,
                    "model_id": model_id,
                    "backend_kind": backend_kind,
                    "model_context_window_tokens": context_window,
                    "request_profile": request_profile,
                    "thinking": thinking,
                    "configured_concurrency": condition["configs"][
                        backend_kind
                    ]["configured_concurrency"],
                    "condition_id": condition["condition_id"],
                    "run_id": (
                        f"{matrix_id}-{slot}-{condition['condition_id']}"
                    ),
                    "command": condition["command"],
                    "config": condition["configs"][backend_kind],
                    "prompt_profile": condition["prompt_profile"],
                    "maximum_model_calls": condition["maximum_model_calls"],
                }
            )
    return {
        "schema_version": 2,
        "status": "prepared_not_executed",
        **frozen,
        "matrix_id": matrix_id,
        "models": [
            {
                "slot": slot,
                "model_id": model_id,
                "backend_kind": backend_kind,
                "model_context_window_tokens": context_window,
                "request_profile": frozen["request_profiles"][backend_kind][
                    "name"
                ],
                "thinking": frozen["request_profiles"][backend_kind][
                    "thinking"
                ],
            }
            for slot, model_id, backend_kind, context_window in models
        ],
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--model-a", required=True)
    parser.add_argument("--model-b")
    parser.add_argument("--backend-a", choices=("api", "local"), required=True)
    parser.add_argument("--backend-b", choices=("api", "local"))
    parser.add_argument("--model-a-context-window", required=True, type=int)
    parser.add_argument("--model-b-context-window", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare_plan(
        args.manifest.resolve(strict=True),
        model_a=args.model_a,
        model_b=args.model_b,
        backend_a=args.backend_a,
        backend_b=args.backend_b,
        context_window_a=args.model_a_context_window,
        context_window_b=args.model_b_context_window,
    )
    _atomic_json(args.output.resolve(), plan)
    print(
        f"prepared {len(plan['runs'])} non-executed runs at {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
