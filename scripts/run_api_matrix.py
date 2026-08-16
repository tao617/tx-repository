#!/usr/bin/env python3
"""Run, resume, score, archive, and aggregate the frozen seven-condition API matrix."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from findver_agent.config import AppConfig, load_config
from findver_agent.runner import sha256_file
from findver_agent.submission import verify_submission_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ["GIT_CONFIG_COUNT"] = "1"
os.environ["GIT_CONFIG_KEY_0"] = "safe.directory"
os.environ["GIT_CONFIG_VALUE_0"] = str(REPO_ROOT)
CONDITION_ORDER = (
    "B0_API",
    "B1_API",
    "B2_API",
    "B3_API",
    "A0_API",
    "A1_API",
    "A2_API",
)
STAGES = {
    "pending": 0,
    "runtime_running": 1,
    "runtime_completed": 2,
    "sealed": 3,
    "handed_off": 4,
    "scored": 5,
    "archived": 6,
}
PLAIN_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
EXPECTED_CONDITIONS = {
    "B0_API": ("baseline", "direct", "none", None),
    "B1_API": ("baseline", "cot", "none", None),
    "B2_API": ("baseline", "cot", "fixed_bm25", None),
    "B3_API": ("baseline", "cot", "fixed_embedding", None),
    "A0_API": ("agent", None, None, False),
    "A1_API": ("agent", None, None, True),
    "A2_API": ("agent", None, None, True),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(arguments: list[str], *, cwd: Path) -> None:
    print("+", " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, check=True)


def git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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


def atomic_copy(source: Path, target: Path, *, mode: int = 0o600) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def repository_path(value: str) -> Path:
    path = (REPO_ROOT / value).resolve()
    if path != REPO_ROOT and REPO_ROOT not in path.parents:
        raise ValueError(f"path is outside repository: {value}")
    return path


def model_from_env(path: Path) -> str:
    if path.stat().st_mode & 0o777 != 0o600:
        raise ValueError("credential file must have mode 0600")
    model = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line.startswith("MODEL_NAME="):
            continue
        model = line.split("=", 1)[1].strip()
        if len(model) >= 2 and model[0] == model[-1] and model[0] in {"'", '"'}:
            model = model[1:-1]
    if not model:
        raise ValueError("credential file does not define MODEL_NAME")
    return model


def _validate_condition(condition_id: str, config: AppConfig) -> None:
    mode, prompt_type, retrieval, calculator = EXPECTED_CONDITIONS[condition_id]
    if config.run.mode != mode or config.run.backend_kind != "api":
        raise ValueError(f"{condition_id} has an invalid run mode")
    generation = config.generation
    if (
        generation.temperature != 1
        or generation.top_p != 1
        or generation.max_output_tokens != 1024
    ):
        raise ValueError(f"{condition_id} generation parameters are not frozen")
    if mode == "baseline":
        if config.baseline is None:
            raise ValueError(f"{condition_id} baseline configuration is missing")
        if (
            config.baseline.prompt_type != prompt_type
            or config.baseline.retrieval != retrieval
            or config.baseline.top_k != 10
        ):
            raise ValueError(f"{condition_id} baseline settings are invalid")
    else:
        if config.agent is None or config.agent.calculator_enabled is not calculator:
            raise ValueError(f"{condition_id} calculator setting is invalid")
        expected_steps = 10 if condition_id == "A2_API" else 8
        expected_review = condition_id == "A2_API"
        if (
            config.agent.max_steps != expected_steps
            or config.agent.pre_submit_review is not expected_review
        ):
            raise ValueError(f"{condition_id} Agent settings are invalid")


def freeze_inputs(manifest_path: Path, env_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("matrix manifest must be a YAML object")
    matrix_id = manifest.get("matrix_id")
    if not isinstance(matrix_id, str) or not PLAIN_NAME.fullmatch(matrix_id):
        raise ValueError("matrix_id must be a plain name")

    task = manifest.get("task")
    retrieval = manifest.get("retrieval")
    conditions = manifest.get("conditions")
    if not isinstance(task, dict) or not isinstance(retrieval, dict):
        raise ValueError("matrix task and retrieval sections are required")
    if not isinstance(conditions, list):
        raise ValueError("matrix conditions must be a list")
    ids = [item.get("condition_id") for item in conditions if isinstance(item, dict)]
    if ids != list(CONDITION_ORDER):
        raise ValueError("matrix conditions must use the frozen seven-condition order")

    tasks_path = repository_path(str(task["path"]))
    retrieval_path = repository_path(str(retrieval["path"]))
    if tasks_path.parent != REPO_ROOT / "runtime_data" / "public":
        raise ValueError("matrix task file must be below runtime_data/public")
    task_hash = sha256_file(tasks_path)
    retrieval_hash = sha256_file(retrieval_path)
    if task_hash != task.get("sha256") or retrieval_hash != retrieval.get("sha256"):
        raise ValueError("matrix task or retrieval SHA256 does not match the manifest")

    condition_specs: dict[str, dict[str, Any]] = {}
    config_hashes: dict[str, str] = {}
    for item in conditions:
        condition_id = item["condition_id"]
        config_path = repository_path(str(item["config"]))
        config = load_config(config_path)
        _validate_condition(condition_id, config)
        command = item.get("command")
        expected_command = "baseline" if config.run.mode == "baseline" else "run"
        if command != expected_command:
            raise ValueError(f"{condition_id} command is invalid")
        condition_specs[condition_id] = {
            **item,
            "config_path": config_path,
        }
        config_hashes[condition_id] = sha256_file(config_path)

    code_commit = git_output("rev-parse", "HEAD")
    requested_commit = manifest.get("code_commit", "auto")
    if requested_commit not in {"auto", code_commit}:
        raise ValueError("matrix code_commit does not match HEAD")
    model = model_from_env(env_path)
    frozen = {
        "manifest_sha256": sha256_file(manifest_path),
        "code_commit": code_commit,
        "task_sha256": task_hash,
        "retrieval_sha256": retrieval_hash,
        "model": model,
        "config_hashes": config_hashes,
    }
    resolved = {
        "manifest": manifest,
        "matrix_id": matrix_id,
        "tasks_path": tasks_path,
        "retrieval_path": retrieval_path,
        "conditions": condition_specs,
    }
    return resolved, frozen


def initial_state(resolved: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    condition_state = {}
    for condition_id in CONDITION_ORDER:
        condition_state[condition_id] = {
            "status": "pending",
            "stage": "pending",
            "completed_examples": 0,
            "config_hash": frozen["config_hashes"][condition_id],
            "task_hash": frozen["task_sha256"],
            "retrieval_hash": (
                frozen["retrieval_sha256"] if condition_id == "B3_API" else None
            ),
            "model": frozen["model"],
            "run_id": f"{resolved['matrix_id']}-{condition_id}",
            "started_at": None,
            "completed_at": None,
            "error": None,
        }
    return {
        "schema_version": 1,
        "matrix_id": resolved["matrix_id"],
        "status": "pending",
        **frozen,
        "started_at": None,
        "completed_at": None,
        "conditions": condition_state,
    }


def validate_resume(state: dict[str, Any], frozen: dict[str, Any]) -> None:
    for field in (
        "manifest_sha256",
        "code_commit",
        "task_sha256",
        "retrieval_sha256",
        "model",
        "config_hashes",
    ):
        if state.get(field) != frozen[field]:
            raise ValueError(f"matrix resume refused because {field} changed")


def update_completed_examples(record: dict[str, Any], run_dir: Path) -> None:
    metadata_path = run_dir / "run_metadata.json"
    if metadata_path.exists():
        metadata = load_object(metadata_path)
        record["completed_examples"] = int(metadata.get("completed_examples", 0))


def verify_scoring_summary(path: Path, run_id: str) -> dict[str, Any]:
    summary = load_object(path)
    if summary.get("run_id") != run_id or summary.get("mode") != "final-aggregate":
        raise ValueError("private scorer summary does not match the condition")
    return summary


def archive_condition(
    *,
    matrix_root: Path,
    scorer_root: Path,
    matrix_id: str,
    condition_id: str,
    run_id: str,
    score_summary: Path,
    sealed_archive: Path,
) -> None:
    inbox_archive = scorer_root / "inbox" / "submission.tar.gz"
    private_root = scorer_root / "archive" / matrix_id
    private_target = private_root / condition_id
    private_root.mkdir(parents=True, exist_ok=True)
    if private_target.exists():
        archived_submission = private_target / "submission.tar.gz"
        archived_summary = private_target / "summary.json"
        if (
            not archived_submission.is_file()
            or not archived_summary.is_file()
            or sha256_file(archived_submission) != sha256_file(sealed_archive)
        ):
            raise ValueError("existing private archive does not match the condition")
        verify_scoring_summary(archived_summary, run_id)
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{condition_id}.", dir=private_root))
        try:
            shutil.copyfile(sealed_archive, temporary / "submission.tar.gz")
            shutil.copyfile(score_summary, temporary / "summary.json")
            os.chmod(temporary / "submission.tar.gz", 0o444)
            os.chmod(temporary / "summary.json", 0o444)
            os.replace(temporary, private_target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    atomic_copy(score_summary, matrix_root / "summaries" / f"{condition_id}.json")
    if inbox_archive.exists():
        if sha256_file(inbox_archive) != sha256_file(sealed_archive):
            raise ValueError("scorer inbox contains a different submission")
        inbox_archive.unlink()
        print(f"archived {run_id}; cleared the scorer inbox copy", flush=True)


def stage_at_least(record: dict[str, Any], stage: str) -> bool:
    return STAGES.get(str(record.get("stage")), -1) >= STAGES[stage]


def run_condition(
    *,
    resolved: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    matrix_root: Path,
    env_path: Path,
    scorer_root: Path,
    condition_id: str,
) -> None:
    spec = resolved["conditions"][condition_id]
    record = state["conditions"][condition_id]
    run_id = record["run_id"]
    run_dir = REPO_ROOT / "runs" / run_id
    record["status"] = "running"
    record["started_at"] = record["started_at"] or now()
    record["error"] = None
    state["status"] = "running"
    state["started_at"] = state["started_at"] or now()
    atomic_json(state_path, state)

    try:
        if not stage_at_least(record, "runtime_completed"):
            record["stage"] = "runtime_running"
            atomic_json(state_path, state)
            arguments = [
                str(REPO_ROOT / "scripts" / "run_agent_with_env.sh"),
                str(env_path),
                "api",
                resolved["tasks_path"].name,
                run_id,
                spec["command"],
                spec["config_path"].name,
            ]
            if run_dir.exists():
                arguments.append("--resume")
            run_command(arguments, cwd=REPO_ROOT)
            metadata = load_object(run_dir / "run_metadata.json")
            if metadata.get("status") != "completed":
                raise ValueError("Runtime returned without completing the condition")
            update_completed_examples(record, run_dir)
            run_command(
                [
                    str(REPO_ROOT / ".venv" / "bin" / "python"),
                    str(REPO_ROOT / "scripts" / "summarize_run.py"),
                    "--run-dir",
                    str(run_dir),
                    "--output",
                    str(run_dir / "efficiency-summary.json"),
                ],
                cwd=REPO_ROOT,
            )
            record["stage"] = "runtime_completed"
            atomic_json(state_path, state)

        sealed = run_dir / "submission.tar.gz"
        if not stage_at_least(record, "sealed"):
            if not sealed.exists():
                run_command(
                    [
                        str(REPO_ROOT / ".venv" / "bin" / "python"),
                        str(REPO_ROOT / "scripts" / "seal_submission.py"),
                        "--run-dir",
                        str(run_dir),
                        "--output",
                        str(sealed),
                    ],
                    cwd=REPO_ROOT,
                )
            manifest, _ = verify_submission_archive(sealed)
            if manifest.run_id != run_id:
                raise ValueError("sealed submission run_id mismatch")
            record["stage"] = "sealed"
            atomic_json(state_path, state)

        inbox = scorer_root / "inbox" / "submission.tar.gz"
        if not stage_at_least(record, "handed_off"):
            if inbox.exists():
                inbox_manifest, _ = verify_submission_archive(inbox)
                if inbox_manifest.run_id != run_id:
                    raise ValueError("scorer inbox is occupied by another run")
            else:
                run_command(
                    [
                        str(REPO_ROOT / "scripts" / "handoff_submission.sh"),
                        str(sealed),
                        str(scorer_root / "inbox"),
                    ],
                    cwd=REPO_ROOT,
                )
            record["stage"] = "handed_off"
            atomic_json(state_path, state)

        scorer_output_name = f"{resolved['matrix_id']}-{condition_id}-final"
        score_summary = scorer_root / "outputs" / scorer_output_name / "summary.json"
        if not stage_at_least(record, "scored"):
            if score_summary.exists():
                verify_scoring_summary(score_summary, run_id)
            else:
                run_command(
                    [
                        str(scorer_root / "scripts" / "run_scorer.sh"),
                        "final-aggregate",
                        f"outputs/{scorer_output_name}",
                    ],
                    cwd=scorer_root,
                )
                verify_scoring_summary(score_summary, run_id)
            record["stage"] = "scored"
            atomic_json(state_path, state)

        if not stage_at_least(record, "archived"):
            archive_condition(
                matrix_root=matrix_root,
                scorer_root=scorer_root,
                matrix_id=resolved["matrix_id"],
                condition_id=condition_id,
                run_id=run_id,
                score_summary=score_summary,
                sealed_archive=sealed,
            )
            record["stage"] = "archived"
            atomic_json(state_path, state)

        update_completed_examples(record, run_dir)
        record["status"] = "completed"
        record["completed_at"] = now()
        atomic_json(state_path, state)
    except BaseException as error:
        update_completed_examples(record, run_dir)
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"[:1000]
        state["status"] = "failed"
        atomic_json(state_path, state)
        raise


def comparison_interpretation(
    overall_delta: float, subset_deltas: dict[str, float]
) -> str:
    if overall_delta <= 0:
        return "无提升"
    if overall_delta < 1:
        return "差异不足 1 个百分点，不称为提升"
    if overall_delta < 2:
        return "正向趋势"
    aligned = sum(delta > 0 for delta in subset_deltas.values())
    if aligned >= 2:
        return "有实质改善"
    return "总体差异达到 2 个百分点，但子集方向不足两项一致"


def aggregate_results(
    *, matrix_root: Path, state: dict[str, Any], resolved: dict[str, Any]
) -> None:
    rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    for condition_id in CONDITION_ORDER:
        record = state["conditions"][condition_id]
        run_dir = REPO_ROOT / "runs" / record["run_id"]
        scorer = load_object(matrix_root / "summaries" / f"{condition_id}.json")
        efficiency = load_object(run_dir / "efficiency-summary.json")
        subsets = scorer.get("subsets", {})
        row = {
            "condition_id": condition_id,
            "run_id": record["run_id"],
            "overall_accuracy": scorer["accuracy"],
            "ie_accuracy": subsets["ie"]["accuracy"],
            "math_accuracy": subsets["numeric"]["accuracy"],
            "know_accuracy": subsets["knowledge"]["accuracy"],
            "completed": record["completed_examples"],
            "coverage": scorer["coverage"],
            "invalid": scorer["invalid_predictions"],
            "model_calls": efficiency["totals"]["model_calls"],
            "mean_steps": efficiency["means_per_expected_example"]["steps"],
            "max_steps_termination_rate": efficiency["means_per_expected_example"][
                "max_steps_terminated"
            ],
            "calculator_calls": efficiency["totals"]["calculator_calls"],
            "review_completion_rate": efficiency["means_per_expected_example"][
                "review_completed"
            ],
            "input_tokens": efficiency["totals"]["input_tokens"],
            "output_tokens": efficiency["totals"]["output_tokens"],
            "mean_latency_ms": efficiency["means_per_expected_example"]["latency_ms"],
        }
        rows.append(row)
        summaries[condition_id] = row

    comparison_specs = (
        ("B0_API", "B1_API", "完整报告下 CoT 效果"),
        ("B1_API", "B2_API", "完整报告与 BM25 top-10"),
        ("B2_API", "B3_API", "BM25 与 Embedding top-10"),
        ("B2_API", "A0_API", "固定 RAG 与完整 Agent 系统"),
        ("A0_API", "A1_API", "Calculator 增益"),
        ("A1_API", "A2_API", "Mandatory Review 增益"),
    )
    comparisons = []
    for left, right, description in comparison_specs:
        left_row, right_row = summaries[left], summaries[right]
        subset_deltas = {
            "ie": (right_row["ie_accuracy"] - left_row["ie_accuracy"]) * 100,
            "math": (right_row["math_accuracy"] - left_row["math_accuracy"]) * 100,
            "know": (right_row["know_accuracy"] - left_row["know_accuracy"]) * 100,
        }
        overall_delta = (
            right_row["overall_accuracy"] - left_row["overall_accuracy"]
        ) * 100
        comparisons.append(
            {
                "comparison": f"{left} vs {right}",
                "description": description,
                "overall_delta_percentage_points": round(overall_delta, 6),
                "subset_deltas_percentage_points": {
                    key: round(value, 6) for key, value in subset_deltas.items()
                },
                "interpretation": comparison_interpretation(
                    overall_delta, subset_deltas
                ),
            }
        )

    result = {
        "schema_version": 1,
        "matrix_id": resolved["matrix_id"],
        "model": state["model"],
        "code_commit": state["code_commit"],
        "task_sha256": state["task_sha256"],
        "retrieval_sha256": state["retrieval_sha256"],
        "conditions": rows,
        "comparisons": comparisons,
    }
    atomic_json(matrix_root / "aggregate.json", result)

    lines = [
        f"# {resolved['matrix_id']} 七条件结果",
        "",
        "| 条件 | Overall | IE | MATH | KNOW | Completed | Coverage | Invalid |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {condition_id} | {overall_accuracy:.2%} | {ie_accuracy:.2%} | "
            "{math_accuracy:.2%} | {know_accuracy:.2%} | {completed} | "
            "{coverage:.2%} | {invalid} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## 核心对照",
            "",
            "| 对照 | 口径 | Overall 差值（百分点） | 结论 |",
            "|---|---|---:|---|",
        ]
    )
    for item in comparisons:
        lines.append(
            f"| {item['comparison']} | {item['description']} | "
            f"{item['overall_delta_percentage_points']:.3f} | "
            f"{item['interpretation']} |"
        )
    lines.extend(
        [
            "",
            "## 运行行为",
            "",
            "| 条件 | Model calls | 平均步数 | Max-step 终止率 | Calculator calls | "
            "Review 完成率 | Input tokens | Output tokens | 平均耗时 ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {condition_id} | {model_calls} | {mean_steps:.3f} | "
            "{max_steps_termination_rate:.2%} | {calculator_calls} | "
            "{review_completion_rate:.2%} | {input_tokens} | {output_tokens} | "
            "{mean_latency_ms:.1f} |".format(**row)
        )
    (matrix_root / "aggregate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def selected_conditions(
    state: dict[str, Any], only: str | None = None
) -> tuple[str, ...]:
    requested = (only,) if only else CONDITION_ORDER
    return tuple(
        condition_id
        for condition_id in requested
        if state["conditions"][condition_id]["status"] != "completed"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only", choices=CONDITION_ORDER)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve(strict=True)
    env_path = args.env_file.resolve(strict=True)
    resolved, frozen = freeze_inputs(manifest_path, env_path)
    if git_output("status", "--porcelain"):
        raise ValueError("matrix execution requires a clean git worktree")
    if args.preflight_only:
        print(
            f"preflight ok matrix={resolved['matrix_id']} model={frozen['model']} "
            f"task_sha256={frozen['task_sha256']} retrieval_sha256={frozen['retrieval_sha256']}"
        )
        return 0

    scorer_root = Path(
        resolved["manifest"].get(
            "private_scorer_root",
            "/home/taoxi/secure/FinDVer-Scorer-Private",
        )
    ).resolve(strict=True)
    matrix_root = REPO_ROOT / "runs" / "matrices" / resolved["matrix_id"]
    matrix_root.mkdir(parents=True, exist_ok=True)
    lock_path = matrix_root / "matrix.lock"
    state_path = matrix_root / "state.json"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another runner owns this matrix state") from error

        if state_path.exists():
            if not args.resume:
                raise ValueError("matrix state exists; pass --resume")
            state = load_object(state_path)
            validate_resume(state, frozen)
        else:
            state = initial_state(resolved, frozen)
            atomic_json(state_path, state)

        for condition_id in selected_conditions(state, args.only):
            run_condition(
                resolved=resolved,
                state=state,
                state_path=state_path,
                matrix_root=matrix_root,
                env_path=env_path,
                scorer_root=scorer_root,
                condition_id=condition_id,
            )

        if all(
            state["conditions"][condition_id]["status"] == "completed"
            for condition_id in CONDITION_ORDER
        ):
            aggregate_results(matrix_root=matrix_root, state=state, resolved=resolved)
            state["status"] = "completed"
            state["completed_at"] = now()
        else:
            state["status"] = "pending"
        atomic_json(state_path, state)
        print(f"matrix state: {state_path} status={state['status']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
