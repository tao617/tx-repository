"""Hash-bound planner for composable B-class conditions and deployments."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

import yaml

from findver_agent.experiment_config import (
    ExperimentCondition,
    ModelDeployment,
    compose_effective_config,
    effective_config_sha256,
    effective_config_value,
    load_experiment_condition,
    load_model_deployment,
)
from findver_agent.model_backends.transport_adapters import get_transport_adapter
from findver_agent.runner import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_CONDITION_ORDER = (
    "BLC_FINDVER_COT",
    "BRAG10_FINDVER_COT",
    "BITER_RAG10",
    "A_SCRATCH",
    "M0_RAG10_SEEDED",
    "M1_BUDGET_AWARE",
    "M2_SELECTIVE_REVIEW",
)
EXTENSION_CONDITION_ORDER = (
    "RAG3_SEEDED",
    "RAG5_SEEDED",
    "BITER2_RAG10",
    "M2_BUDGET4",
)
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _load_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return value


def _repository_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("manifest paths must be non-empty strings")
    path = (REPO_ROOT / value).resolve()
    if path != REPO_ROOT and REPO_ROOT not in path.parents:
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


def _condition_path(value: object, family: str) -> Path:
    path = _repository_path(value)
    expected_parent = (
        REPO_ROOT / "configs" / "conditions" / "bclass" / family
    ).resolve()
    if path.parent != expected_parent:
        raise ValueError(f"{family} condition must be in the canonical condition directory")
    return path


def _deployment_path(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path = path.resolve(strict=True)
    if path.parent != (REPO_ROOT / "configs" / "deployments").resolve():
        raise ValueError("deployment must be directly under configs/deployments")
    return path


def _validate_condition_shape(condition: ExperimentCondition) -> None:
    condition_id = condition.condition_id
    if condition.configured_concurrency != 32:
        raise ValueError(f"{condition_id} concurrency must be frozen at 32")
    if condition_id == "BLC_FINDVER_COT":
        valid = (
            condition.baseline is not None
            and condition.baseline.prompt_type == "findver_cot_json"
            and condition.baseline.retrieval == "none"
        )
    elif condition_id == "BRAG10_FINDVER_COT":
        valid = (
            condition.baseline is not None
            and condition.baseline.retrieval == "fixed_retrieval"
            and condition.baseline.retriever == "text-embedding-3-large"
            and condition.baseline.top_k == 10
        )
    elif condition_id == "BITER_RAG10":
        valid = (
            condition.iterative_rag is not None
            and condition.iterative_rag.retrieval_rounds == 3
            and condition.iterative_rag.top_k == 10
        )
    elif condition_id == "A_SCRATCH":
        valid = (
            condition.agent is not None
            and not condition.agent.initial_retrieval.enabled
            and condition.agent.review_policy == "selective"
        )
    elif condition_id == "M0_RAG10_SEEDED":
        valid = (
            condition.agent is not None
            and condition.agent.protocol_version == "v1"
            and condition.agent.initial_retrieval.enabled
            and condition.agent.initial_retrieval.top_k == 10
        )
    elif condition_id == "M1_BUDGET_AWARE":
        valid = (
            condition.agent is not None
            and condition.agent.protocol_version == "v2"
            and condition.agent.initial_retrieval.enabled
            and condition.agent.review_policy == "none"
            and condition.agent.review_steps == 0
        )
    elif condition_id == "M2_SELECTIVE_REVIEW":
        valid = (
            condition.agent is not None
            and condition.agent.protocol_version == "v2"
            and condition.agent.initial_retrieval.enabled
            and condition.agent.review_policy == "selective"
            and condition.agent.review_steps == 1
        )
    elif condition_id == "RAG3_SEEDED":
        valid = condition.agent is not None and condition.agent.initial_retrieval.top_k == 3
    elif condition_id == "RAG5_SEEDED":
        valid = condition.agent is not None and condition.agent.initial_retrieval.top_k == 5
    elif condition_id == "BITER2_RAG10":
        valid = (
            condition.iterative_rag is not None
            and condition.iterative_rag.retrieval_rounds == 2
            and condition.iterative_rag.top_k == 10
        )
    elif condition_id == "M2_BUDGET4":
        valid = (
            condition.agent is not None
            and condition.agent.exploration_steps == 4
            and condition.agent.initial_retrieval.top_k == 10
        )
    else:
        valid = False
    if not valid:
        raise ValueError(f"{condition_id} configuration does not match its method")


def _freeze_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_object(path)
    if manifest.get("schema_version") != 2:
        raise ValueError("composable B-class manifest requires schema_version 2")
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
    retrieval_artifacts = manifest.get("retrieval_artifacts")
    if not isinstance(task, dict) or not isinstance(retrieval_artifacts, dict):
        raise ValueError("task and retrieval_artifacts are required")
    task_path = _repository_path(task.get("path"))
    task_hash = sha256_file(task_path)
    if task_hash != task.get("sha256"):
        raise ValueError("public task SHA256 does not match the manifest")

    frozen_retrieval: dict[str, dict[str, Any]] = {}
    for key, top_k in (("top3", 3), ("top5", 5), ("top10", 10)):
        item = retrieval_artifacts.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"retrieval artifact {key} is required")
        artifact_path = _repository_path(item.get("path"))
        if artifact_path.parent != (REPO_ROOT / "runtime_data" / "retrieval"):
            raise ValueError("retrieval artifact must be under runtime_data/retrieval")
        artifact_hash = sha256_file(artifact_path)
        if artifact_hash != item.get("sha256"):
            raise ValueError(f"retrieval artifact {key} SHA256 does not match")
        if item.get("retriever") != "text-embedding-3-large" or item.get("top_k") != top_k:
            raise ValueError(f"retrieval artifact {key} identity is invalid")
        frozen_retrieval[key] = {
            "path": str(artifact_path.relative_to(REPO_ROOT)),
            "sha256": artifact_hash,
            "retriever": item["retriever"],
            "top_k": top_k,
        }

    frozen_families: dict[str, list[dict[str, Any]]] = {}
    for manifest_key, family, expected_order in (
        ("conditions", "main", MAIN_CONDITION_ORDER),
        ("extensions", "extensions", EXTENSION_CONDITION_ORDER),
    ):
        values = manifest.get(manifest_key)
        if not isinstance(values, list):
            raise ValueError(f"{manifest_key} must be a list")
        frozen: list[dict[str, Any]] = []
        for value in values:
            condition_path = _condition_path(value, family)
            condition = load_experiment_condition(condition_path)
            expected_family = "main" if family == "main" else "extension"
            if condition.family != expected_family:
                raise ValueError("condition family does not match its directory")
            _validate_condition_shape(condition)
            frozen.append(
                {
                    "path": str(condition_path.relative_to(REPO_ROOT)),
                    "sha256": sha256_file(condition_path),
                    "condition": condition,
                }
            )
        if tuple(item["condition"].condition_id for item in frozen) != expected_order:
            raise ValueError(f"{manifest_key} must use the fixed B-class order")
        frozen_families[manifest_key] = frozen

    commit = _git_commit()
    if manifest.get("code_commit", "auto") not in {"auto", commit}:
        raise ValueError("manifest code_commit does not match HEAD")
    return {
        "matrix_id": matrix_id,
        "purpose": manifest.get("purpose"),
        "evaluation_split": manifest["evaluation_split"],
        "manifest_sha256": sha256_file(path),
        "code_commit": commit,
        "task": {"path": str(task_path.relative_to(REPO_ROOT)), "sha256": task_hash},
        "retrieval_artifacts": frozen_retrieval,
        **frozen_families,
    }


def _deployment_spec(path: Path) -> tuple[ModelDeployment, dict[str, Any]]:
    deployment = load_model_deployment(path)
    adapter = get_transport_adapter(deployment.transport_profile)
    rate_limit = (
        deployment.rate_limit.model_dump(mode="json")
        if deployment.rate_limit is not None
        else None
    )
    return deployment, {
        "path": str(path.relative_to(REPO_ROOT)),
        "sha256": sha256_file(path),
        "deployment_id": deployment.deployment_id,
        "model_id": deployment.model_id,
        "backend_kind": deployment.backend_kind,
        "model_alias": deployment.model_alias,
        "model_context_window_tokens": deployment.model_context_window_tokens,
        "transport_profile": deployment.transport_profile,
        "thinking_mode": deployment.thinking_mode,
        "rate_limit": rate_limit,
        "allowed_request_fields": sorted(adapter.allowed_request_fields),
    }


def _command(condition: ExperimentCondition) -> str:
    return {
        "agent": "run",
        "baseline": "baseline",
        "iterative_rag": "iterative-rag",
    }[condition.run_mode]


def _condition_retrieval_key(condition: ExperimentCondition) -> str | None:
    if condition.baseline is not None:
        return None if condition.baseline.retrieval == "none" else f"top{condition.baseline.top_k}"
    if condition.agent is not None:
        retrieval = condition.agent.initial_retrieval
        return f"top{retrieval.top_k}" if retrieval.enabled else None
    if condition.iterative_rag is not None:
        return f"top{condition.iterative_rag.top_k}"
    return None  # pragma: no cover


def _run(
    *,
    matrix_id: str,
    slot: str,
    condition_spec: dict[str, Any],
    deployment_spec: dict[str, Any],
    deployment: ModelDeployment,
) -> dict[str, Any]:
    condition: ExperimentCondition = condition_spec["condition"]
    effective = compose_effective_config(condition, deployment)
    return {
        "slot": slot,
        "deployment_id": deployment.deployment_id,
        "model_id": deployment.model_id,
        "backend_kind": deployment.backend_kind,
        "model_context_window_tokens": deployment.model_context_window_tokens,
        "transport_profile": deployment.transport_profile,
        "thinking_mode": deployment.thinking_mode,
        "rate_limit": deployment_spec["rate_limit"],
        "configured_concurrency": condition.configured_concurrency,
        "condition_id": condition.condition_id,
        "run_id": f"{matrix_id}-{slot}-{condition.condition_id}",
        "command": _command(condition),
        "condition": {
            "path": condition_spec["path"],
            "sha256": condition_spec["sha256"],
            "family": condition.family,
        },
        "deployment": {
            "path": deployment_spec["path"],
            "sha256": deployment_spec["sha256"],
        },
        "effective_config": {
            "sha256": effective_config_sha256(effective),
            "value": effective_config_value(effective),
        },
        "prompt_profile": condition.prompt_profile,
        "maximum_model_calls": condition.maximum_model_calls,
        "effective_retrieval_required": _condition_retrieval_key(condition) is not None,
    }


def _deployments(paths: Iterable[Path | str]) -> list[tuple[str, ModelDeployment, dict[str, Any]]]:
    result: list[tuple[str, ModelDeployment, dict[str, Any]]] = []
    for index, value in enumerate(paths):
        path = _deployment_path(value)
        deployment, spec = _deployment_spec(path)
        result.append((f"model_{chr(ord('a') + index)}", deployment, spec))
    if not result or len(result) > 2:
        raise ValueError("a B-class matrix requires one or two deployments")
    if len({item[1].deployment_id for item in result}) != len(result):
        raise ValueError("matrix deployments must have distinct deployment IDs")
    if len({item[1].model_id for item in result}) != len(result):
        raise ValueError("matrix deployments must have distinct model IDs")
    return result


def prepare_matrix_plan(
    manifest_path: Path,
    *,
    deployment_a: Path | str,
    deployment_b: Path | str | None = None,
) -> dict[str, Any]:
    frozen = _freeze_manifest(manifest_path)
    deployment_values = [deployment_a]
    if deployment_b is not None:
        deployment_values.append(deployment_b)
    deployments = _deployments(deployment_values)
    matrix_id = frozen["matrix_id"]
    if len(deployments) == 1:
        matrix_id = f"{matrix_id}-single-model-a"
    if len(matrix_id) > 256 or not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("effective matrix ID is invalid")
    if any(
        _condition_retrieval_key(item["condition"]) not in {None, "top10"}
        for item in frozen["conditions"]
    ):
        raise ValueError("main conditions must use only the frozen top-10 retrieval")
    runs = [
        _run(
            matrix_id=matrix_id,
            slot=slot,
            condition_spec=condition_spec,
            deployment_spec=deployment_spec,
            deployment=deployment,
        )
        for slot, deployment, deployment_spec in deployments
        for condition_spec in frozen["conditions"]
    ]
    return {
        "schema_version": 3,
        "status": "prepared_not_executed",
        "matrix_id": matrix_id,
        "purpose": frozen["purpose"],
        "evaluation_split": frozen["evaluation_split"],
        "manifest_sha256": frozen["manifest_sha256"],
        "code_commit": frozen["code_commit"],
        "task": frozen["task"],
        "retrieval": frozen["retrieval_artifacts"]["top10"],
        "deployments": [
            {"slot": slot, **spec} for slot, _, spec in deployments
        ],
        "conditions": [
            {
                "condition_id": item["condition"].condition_id,
                "family": item["condition"].family,
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in frozen["conditions"]
        ],
        "runs": runs,
    }


def prepare_extension_plan(
    manifest_path: Path,
    *,
    condition_id: str,
    matrix_id: str,
    deployment: Path | str,
    slot: str = "model_a",
) -> dict[str, Any]:
    if condition_id not in EXTENSION_CONDITION_ORDER:
        raise ValueError("unsupported B-class extension condition")
    if not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("matrix_id must be a plain name")
    if slot not in {"model_a", "model_b"}:
        raise ValueError("extension slot must be model_a or model_b")
    frozen = _freeze_manifest(manifest_path)
    condition_spec = next(
        item
        for item in frozen["extensions"]
        if item["condition"].condition_id == condition_id
    )
    deployment_path = _deployment_path(deployment)
    deployment_value, deployment_spec = _deployment_spec(deployment_path)
    condition: ExperimentCondition = condition_spec["condition"]
    retrieval_key = _condition_retrieval_key(condition)
    if retrieval_key is None:
        raise ValueError("extension must bind an effective retrieval artifact")
    run = _run(
        matrix_id=matrix_id,
        slot=slot,
        condition_spec=condition_spec,
        deployment_spec=deployment_spec,
        deployment=deployment_value,
    )
    return {
        "schema_version": 3,
        "status": "prepared_not_executed",
        "matrix_id": matrix_id,
        "purpose": f"bclass-{slot.replace('_', '-')}-development-extension",
        "evaluation_split": frozen["evaluation_split"],
        "manifest_sha256": frozen["manifest_sha256"],
        "code_commit": frozen["code_commit"],
        "task": frozen["task"],
        "retrieval": frozen["retrieval_artifacts"][retrieval_key],
        "deployments": [{"slot": slot, **deployment_spec}],
        "conditions": [
            {
                "condition_id": condition.condition_id,
                "family": condition.family,
                "path": condition_spec["path"],
                "sha256": condition_spec["sha256"],
            }
        ],
        "runs": [run],
    }
