"""Hash-bound plans for the two prespecified one-call retrieval controls."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml

from findver_agent.experiment_config import (
    ExperimentCondition,
    compose_effective_config,
    effective_config_sha256,
    effective_config_value,
    load_experiment_condition,
    load_model_deployment,
)
from findver_agent.fixed_retrieval import FixedRetrievalIndex
from findver_agent.runner import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTROL_ORDER = ("BBM25_10", "BHYBRID_RRF10")
CONTROL_RETRIEVERS = {
    "BBM25_10": "bm25",
    "BHYBRID_RRF10": "hybrid-rrf",
}
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _load_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return value


def _repository_path(value: object, *, parent: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("manifest paths must be non-empty strings")
    path = (REPO_ROOT / value).resolve(strict=True)
    if path.parent != parent.resolve():
        raise ValueError(f"path is outside {parent.relative_to(REPO_ROOT)}")
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


def _validate_against_brag(condition: ExperimentCondition) -> None:
    reference = load_experiment_condition(
        REPO_ROOT
        / "configs"
        / "conditions"
        / "bclass"
        / "main"
        / "BRAG10_FINDVER_COT.yaml"
    )
    baseline = condition.baseline
    reference_baseline = reference.baseline
    expected_retriever = CONTROL_RETRIEVERS.get(condition.condition_id)
    if (
        condition.family != "control"
        or condition.run_mode != "baseline"
        or condition.prompt_profile != reference.prompt_profile
        or condition.generation != reference.generation
        or baseline is None
        or reference_baseline is None
        or baseline.prompt_type != reference_baseline.prompt_type
        or baseline.retrieval != "fixed_retrieval"
        or baseline.retriever != expected_retriever
        or baseline.top_k != reference_baseline.top_k
        or baseline.concurrency != reference_baseline.concurrency
    ):
        raise ValueError(
            f"{condition.condition_id} must differ from BRAG10 only by retrieval artifact"
        )


def _freeze_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_object(path)
    if manifest.get("schema_version") != 1:
        raise ValueError("retrieval-control manifest requires schema_version 1")
    matrix_id = manifest.get("matrix_id")
    if not isinstance(matrix_id, str) or not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("matrix_id must be a plain name")
    if manifest.get("evaluation_split") != "dev_feedback":
        raise ValueError("retrieval controls are frozen to dev_feedback")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("tracked retrieval-control manifest must not authorize execution")

    task = manifest.get("task")
    if not isinstance(task, dict):
        raise ValueError("retrieval-control task is required")
    task_path = _repository_path(
        task.get("path"), parent=REPO_ROOT / "runtime_data" / "public"
    )
    task_hash = sha256_file(task_path)
    if task_hash != task.get("sha256"):
        raise ValueError("public task SHA256 does not match the manifest")

    controls = manifest.get("controls")
    if not isinstance(controls, list) or len(controls) != len(CONTROL_ORDER):
        raise ValueError("manifest must contain exactly the two retrieval controls")
    frozen_controls: dict[str, dict[str, Any]] = {}
    for value, expected_id in zip(controls, CONTROL_ORDER, strict=True):
        condition_path = _repository_path(
            value,
            parent=REPO_ROOT / "configs" / "conditions" / "bclass" / "controls",
        )
        condition = load_experiment_condition(condition_path)
        if condition.condition_id != expected_id:
            raise ValueError("retrieval controls must use the frozen order")
        _validate_against_brag(condition)
        frozen_controls[expected_id] = {
            "path": str(condition_path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(condition_path),
            "condition": condition,
        }

    artifacts = manifest.get("retrieval_artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(CONTROL_ORDER):
        raise ValueError("manifest retrieval artifacts must match the two controls")
    frozen_artifacts: dict[str, dict[str, Any]] = {}
    for condition_id in CONTROL_ORDER:
        item = artifacts[condition_id]
        if not isinstance(item, dict):
            raise ValueError(f"retrieval artifact {condition_id} is invalid")
        artifact_path = _repository_path(
            item.get("path"), parent=REPO_ROOT / "runtime_data" / "retrieval"
        )
        artifact_hash = sha256_file(artifact_path)
        retriever = CONTROL_RETRIEVERS[condition_id]
        if artifact_hash != item.get("sha256"):
            raise ValueError(f"retrieval artifact {condition_id} SHA256 does not match")
        if item.get("retriever") != retriever or item.get("top_k") != 10:
            raise ValueError(f"retrieval artifact {condition_id} identity is invalid")
        index = FixedRetrievalIndex(artifact_path, retriever=retriever, top_k=10)
        if index.metadata.get("output_order") != "document":
            raise ValueError(f"retrieval artifact {condition_id} is not document ordered")
        if condition_id == "BHYBRID_RRF10" and (
            item.get("rrf_k") != 60
            or index.metadata.get("rrf_k") != 60
            or index.metadata.get("input_top_k") != 10
            or index.metadata.get("deduplicated") is not True
        ):
            raise ValueError("hybrid retrieval must use deduplicated RRF k=60 over Top-10")
        condition_file = frozen_controls[condition_id]["condition"].baseline
        if condition_file is None or condition_file.retrieval_file is None:
            raise ValueError("retrieval control baseline is incomplete")
        if condition_file.retrieval_file.name != artifact_path.name:
            raise ValueError("control condition does not reference its frozen artifact")
        frozen_artifacts[condition_id] = {
            "path": str(artifact_path.relative_to(REPO_ROOT)),
            "sha256": artifact_hash,
            "retriever": retriever,
            "top_k": 10,
            **({"rrf_k": 60} if condition_id == "BHYBRID_RRF10" else {}),
        }

    commit = _git_commit()
    if manifest.get("code_commit", "auto") not in {"auto", commit}:
        raise ValueError("manifest code_commit does not match HEAD")
    return {
        "matrix_id": matrix_id,
        "purpose": manifest.get("purpose"),
        "evaluation_split": manifest["evaluation_split"],
        "manifest_sha256": sha256_file(path),
        "code_commit": commit,
        "task": {
            "path": str(task_path.relative_to(REPO_ROOT)),
            "sha256": task_hash,
        },
        "controls": frozen_controls,
        "artifacts": frozen_artifacts,
    }


def prepare_control_plan(
    manifest_path: Path,
    *,
    condition_id: str,
    deployment_path: Path,
    slot: Literal["model_a", "model_b"],
) -> dict[str, Any]:
    if condition_id not in CONTROL_ORDER:
        raise ValueError("unsupported retrieval-control condition")
    if slot not in {"model_a", "model_b"}:
        raise ValueError("retrieval-control slot must be model_a or model_b")
    frozen = _freeze_manifest(manifest_path)
    deployment_path = deployment_path.resolve(strict=True)
    if deployment_path.parent != (REPO_ROOT / "configs" / "deployments").resolve():
        raise ValueError("deployment must be directly under configs/deployments")
    deployment = load_model_deployment(deployment_path)
    condition_spec = frozen["controls"][condition_id]
    condition: ExperimentCondition = condition_spec["condition"]
    effective = compose_effective_config(condition, deployment)
    matrix_id = f"{frozen['matrix_id']}-{condition_id.lower()}"
    run_id = f"{matrix_id}-{slot}-{condition_id}"
    deployment_spec = {
        "slot": slot,
        "path": str(deployment_path.relative_to(REPO_ROOT)),
        "sha256": sha256_file(deployment_path),
        "deployment_id": deployment.deployment_id,
        "model_id": deployment.model_id,
        "backend_kind": deployment.backend_kind,
        "model_alias": deployment.model_alias,
        "model_context_window_tokens": deployment.model_context_window_tokens,
        "transport_profile": deployment.transport_profile,
        "thinking_mode": deployment.thinking_mode,
        "rate_limit": (
            deployment.rate_limit.model_dump(mode="json")
            if deployment.rate_limit is not None
            else None
        ),
    }
    condition_plan_spec = {
        "condition_id": condition_id,
        "family": condition.family,
        "path": condition_spec["path"],
        "sha256": condition_spec["sha256"],
    }
    run = {
        "slot": slot,
        "deployment_id": deployment.deployment_id,
        "model_id": deployment.model_id,
        "backend_kind": deployment.backend_kind,
        "model_context_window_tokens": deployment.model_context_window_tokens,
        "transport_profile": deployment.transport_profile,
        "thinking_mode": deployment.thinking_mode,
        "rate_limit": deployment_spec["rate_limit"],
        "configured_concurrency": condition.configured_concurrency,
        "condition_id": condition_id,
        "run_id": run_id,
        "command": "baseline",
        "condition": {
            key: condition_plan_spec[key] for key in ("family", "path", "sha256")
        },
        "deployment": {
            key: deployment_spec[key] for key in ("path", "sha256")
        },
        "effective_config": {
            "sha256": effective_config_sha256(effective),
            "value": effective_config_value(effective),
        },
        "prompt_profile": condition.prompt_profile,
        "maximum_model_calls": 1,
        "effective_retrieval_required": True,
    }
    return {
        "schema_version": 3,
        "status": "prepared_not_executed",
        "matrix_id": matrix_id,
        "purpose": frozen["purpose"],
        "evaluation_split": frozen["evaluation_split"],
        "manifest_sha256": frozen["manifest_sha256"],
        "code_commit": frozen["code_commit"],
        "task": frozen["task"],
        "retrieval": frozen["artifacts"][condition_id],
        "deployments": [deployment_spec],
        "conditions": [condition_plan_spec],
        "runs": [run],
    }
