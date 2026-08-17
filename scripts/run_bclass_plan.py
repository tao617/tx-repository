#!/usr/bin/env python3
"""Execute exactly one hash-bound run from a frozen B-class plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from findver_agent.config import AppConfig, load_config
from findver_agent.run_identity import RunIdentity
from findver_agent.runner import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _load_plan(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("B-class plan is missing or invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("B-class plan must be a JSON object")
    if value.get("schema_version") != 2:
        raise ValueError("B-class execution requires plan schema_version 2")
    if value.get("status") != "prepared_not_executed":
        raise ValueError("B-class plan is not in prepared_not_executed state")
    return value


def _repository_path(value: object, *, parent: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("planned repository path must be a non-empty string")
    path = (REPO_ROOT / value).resolve()
    if path.parent != parent.resolve():
        raise ValueError(f"planned path is outside {parent.relative_to(REPO_ROOT)}")
    return path


def _configuration_path(value: object, *, backend_kind: object) -> Path:
    if backend_kind not in {"api", "local"}:
        raise ValueError("planned backend kind must be api or local")
    if not isinstance(value, str) or not value:
        raise ValueError("planned config path must be a non-empty string")
    path = (REPO_ROOT / value).resolve()
    allowed_parents = {
        (REPO_ROOT / "configs" / "bclass" / str(backend_kind)).resolve(),
    }
    if backend_kind == "api":
        allowed_parents.add(
            (REPO_ROOT / "configs" / "bclass" / "ablations").resolve()
        )
    if path.parent not in allowed_parents:
        raise ValueError(
            "planned config path is outside the selected B-class config directories"
        )
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


def _git_is_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return not result.stdout.strip()


def _model_from_env(path: Path) -> str:
    if path.stat().st_mode & 0o777 != 0o600:
        raise ValueError("credential file must have mode 0600")
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line.startswith("MODEL_NAME="):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values.append(value)
    if len(values) != 1 or not values[0]:
        raise ValueError("credential file must define MODEL_NAME exactly once")
    return values[0]


def _configured_retrieval_file(config: AppConfig) -> Path | None:
    configured: Path | None = None
    if config.baseline is not None:
        configured = config.baseline.retrieval_file
    elif config.agent is not None and config.agent.initial_retrieval.enabled:
        configured = config.agent.initial_retrieval.retrieval_file
    elif config.iterative_rag is not None:
        configured = config.iterative_rag.retrieval_file
    if configured is None:
        return None
    container_path = Path(configured)
    if container_path.parent != Path("/retrieval") or container_path.name in {"", ".", ".."}:
        raise ValueError("planned retrieval must be a direct file under /retrieval")
    host_path = REPO_ROOT / "runtime_data" / "retrieval" / container_path.name
    return host_path.resolve(strict=True)


def _configured_concurrency(config: AppConfig) -> int:
    section = config.baseline or config.agent or config.iterative_rag
    if section is None:
        raise ValueError("planned configuration mode section is missing")
    return section.concurrency


def _select_run(plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    if not PLAIN_NAME.fullmatch(run_id):
        raise ValueError("plan run ID must be a plain name")
    runs = plan.get("runs")
    if not isinstance(runs, list):
        raise ValueError("B-class plan runs must be a list")
    matches = [
        item for item in runs if isinstance(item, dict) and item.get("run_id") == run_id
    ]
    if len(matches) != 1:
        raise ValueError("plan run ID must select exactly one run")
    return matches[0]


def prepare_execution(
    plan_path: Path,
    *,
    plan_run_id: str,
    env_path: Path,
    resume: bool,
) -> tuple[RunIdentity, list[str], dict[str, str]]:
    plan_path = plan_path.resolve(strict=True)
    env_path = env_path.resolve(strict=True)
    plan = _load_plan(plan_path)
    run = _select_run(plan, plan_run_id)
    matrix_id = plan.get("matrix_id")
    condition_id = run.get("condition_id")
    if not isinstance(matrix_id, str) or not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("plan matrix_id must be a plain name")
    if not isinstance(condition_id, str) or not PLAIN_NAME.fullmatch(condition_id):
        raise ValueError("plan condition_id must be a plain name")

    task = plan.get("task")
    retrieval = plan.get("retrieval")
    config_spec = run.get("config")
    if not all(isinstance(item, dict) for item in (task, retrieval, config_spec)):
        raise ValueError("plan task, retrieval, and run config are required")
    backend_kind = run.get("backend_kind")
    tasks_path = _repository_path(
        task["path"],
        parent=REPO_ROOT / "runtime_data" / "public",
    )
    planned_retrieval_path = _repository_path(
        retrieval["path"],
        parent=REPO_ROOT / "runtime_data" / "retrieval",
    )
    config_path = _configuration_path(
        config_spec["path"],
        backend_kind=backend_kind,
    )
    task_sha256 = sha256_file(tasks_path)
    retrieval_sha256 = sha256_file(planned_retrieval_path)
    config_sha256 = sha256_file(config_path)
    if task_sha256 != task.get("sha256"):
        raise ValueError("planned public task SHA256 does not match")
    if retrieval_sha256 != retrieval.get("sha256"):
        raise ValueError("planned retrieval SHA256 does not match")
    if config_sha256 != config_spec.get("sha256"):
        raise ValueError("planned config SHA256 does not match")

    config = load_config(config_path)
    if config.run.backend_kind != backend_kind:
        raise ValueError("planned backend kind does not match config")
    expected_command = {
        "agent": "run",
        "baseline": "baseline",
        "iterative_rag": "iterative-rag",
    }[config.run.mode]
    if run.get("command") != expected_command:
        raise ValueError("planned command does not match config")
    planned_window = run.get("model_context_window_tokens")
    if (
        planned_window != config.backend.model_context_window_tokens
        or config_spec.get("model_context_window_tokens") != planned_window
    ):
        raise ValueError(
            "planned model context window does not match the effective config"
        )
    configured_thinking = (
        config.backend.thinking.model_dump(mode="json")
        if config.backend.thinking is not None
        else None
    )
    planned_profile = run.get("request_profile")
    planned_thinking = run.get("thinking")
    planned_concurrency = run.get("configured_concurrency")
    plan_profiles = plan.get("request_profiles")
    if not isinstance(plan_profiles, dict):
        raise ValueError("plan request_profiles provenance is required")
    selected_profile = plan_profiles.get(backend_kind)
    if not isinstance(selected_profile, dict):
        raise ValueError("selected plan request profile is invalid")
    if (
        planned_profile != config.backend.request_profile
        or config_spec.get("request_profile") != planned_profile
        or selected_profile.get("name") != planned_profile
        or planned_thinking != configured_thinking
        or config_spec.get("thinking") != planned_thinking
        or selected_profile.get("thinking") != planned_thinking
    ):
        raise ValueError(
            "planned request profile or thinking mode does not match the effective config"
        )
    configured_concurrency = _configured_concurrency(config)
    if (
        planned_concurrency != configured_concurrency
        or config_spec.get("configured_concurrency") != planned_concurrency
    ):
        raise ValueError(
            "planned concurrency does not match the effective config"
        )


    effective_model_id = _model_from_env(env_path)
    if effective_model_id != run.get("model_id"):
        raise ValueError("MODEL_NAME does not match the planned effective model ID")
    if "deepseek-v4" in effective_model_id.casefold() and (
        backend_kind != "api"
        or planned_profile != "deepseek_v4_openai"
        or planned_thinking != {"type": "disabled"}
    ):
        raise ValueError(
            "DeepSeek V4 formal execution requires explicit disabled thinking"
        )
    commit = _git_commit()
    if commit != plan.get("code_commit"):
        raise ValueError("HEAD does not match the planned code commit")
    if not _git_is_clean():
        raise ValueError("formal B-class execution requires a clean tracked worktree")

    effective_retrieval_path = _configured_retrieval_file(config)
    effective_retrieval_sha256 = (
        sha256_file(effective_retrieval_path)
        if effective_retrieval_path is not None
        else None
    )
    if (
        effective_retrieval_sha256 is not None
        and effective_retrieval_sha256 != retrieval_sha256
    ):
        raise ValueError("effective retrieval does not match the planned retrieval")

    identity = RunIdentity(
        plan_sha256=sha256_file(plan_path),
        matrix_id=matrix_id,
        condition_id=condition_id,
        plan_run_id=plan_run_id,
        effective_model_id=effective_model_id,
        model_alias=config.backend.model,
        backend_kind=backend_kind,
        git_commit_at_start=commit,
        git_worktree_clean=True,
        config_sha256=config_sha256,
        public_tasks_sha256=task_sha256,
        planned_retrieval_sha256=retrieval_sha256,
        effective_retrieval_sha256=effective_retrieval_sha256,
        model_context_window_tokens=run["model_context_window_tokens"],
        request_profile=planned_profile,
        thinking_mode=(
            planned_thinking["type"]
            if isinstance(planned_thinking, dict)
            else "unsupported"
        ),
        configured_concurrency=configured_concurrency,
    )
    config_name = str(config_path.relative_to(REPO_ROOT / "configs"))
    arguments = [
        str(REPO_ROOT / "scripts" / "run_agent_with_env.sh"),
        str(env_path),
        backend_kind,
        tasks_path.name,
        plan_run_id,
        expected_command,
        config_name,
    ]
    if resume:
        arguments.append("--resume")
    environment = os.environ.copy()
    environment["FINDVER_EXPECTED_MODEL_ID"] = effective_model_id
    environment["FINDVER_RUN_IDENTITY_JSON"] = identity.model_dump_json()
    return identity, arguments, environment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    identity, command, environment = prepare_execution(
        args.plan,
        plan_run_id=args.plan_run_id,
        env_path=args.env,
        resume=args.resume,
    )
    subprocess.run(command, cwd=REPO_ROOT, env=environment, check=True)
    print(
        f"completed planned run={identity.plan_run_id} "
        f"plan_sha256={identity.plan_sha256}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
