import importlib.util
import json
import sys
from pathlib import Path

import pytest

from findver_agent.run_identity import RunIdentity


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "run_bclass_plan.py"
CONFIG_FIXTURE = ROOT / "configs" / "bclass" / "api" / "BLC_FINDVER_COT.yaml"
SPEC = importlib.util.spec_from_file_location("run_bclass_plan", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _prepared_fixture(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    task_path = repo / "runtime_data" / "public" / "tasks.jsonl"
    retrieval_path = repo / "runtime_data" / "retrieval" / "retrieval.jsonl"
    config_path = repo / "configs" / "bclass" / "api" / "BLC_FINDVER_COT.yaml"
    task_path.parent.mkdir(parents=True)
    retrieval_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    task_path.write_text(
        '{"example_id":"one","statement":"Claim","report":"one.json"}\n',
        encoding="utf-8",
    )
    retrieval_path.write_text('{"example_id":"one","paragraph_ids":[1]}\n', encoding="utf-8")
    config_path.write_text(CONFIG_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    commit = "1" * 40
    run_id = "matrix-model_a-BLC_FINDVER_COT"
    plan = {
        "schema_version": 2,
        "status": "prepared_not_executed",
        "matrix_id": "matrix",
        "code_commit": commit,
        "request_profiles": {
            "api": {
                "name": "deepseek_v4_openai",
                "thinking": {"type": "disabled"},
            },
            "local": {"name": "generic_openai", "thinking": None},
        },
        "task": {
            "path": "runtime_data/public/tasks.jsonl",
            "sha256": MODULE.sha256_file(task_path),
        },
        "retrieval": {
            "path": "runtime_data/retrieval/retrieval.jsonl",
            "sha256": MODULE.sha256_file(retrieval_path),
        },
        "runs": [
            {
                "run_id": run_id,
                "condition_id": "BLC_FINDVER_COT",
                "model_id": "provider/model-a",
                "backend_kind": "api",
                "model_context_window_tokens": 100_000,
                "request_profile": "deepseek_v4_openai",
                "thinking": {"type": "disabled"},
                "configured_concurrency": 32,
                "command": "baseline",
                "config": {
                    "path": "configs/bclass/api/BLC_FINDVER_COT.yaml",
                    "sha256": MODULE.sha256_file(config_path),
                    "model_context_window_tokens": 100_000,
                    "request_profile": "deepseek_v4_openai",
                    "thinking": {"type": "disabled"},
                    "configured_concurrency": 32,
                },
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    env_path = tmp_path / "model.env"
    env_path.write_text(
        "MODEL_BASE_URL=https://example.invalid/v1\n"
        "MODEL_API_KEY=secret\n"
        "MODEL_NAME=provider/model-a\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)
    monkeypatch.setattr(MODULE, "_git_commit", lambda: commit)
    monkeypatch.setattr(MODULE, "_git_is_clean", lambda: True)
    return plan_path, env_path, run_id, task_path


def test_executor_binds_plan_model_artifacts_commit_and_context(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)

    identity, command, environment = MODULE.prepare_execution(
        plan_path,
        plan_run_id=run_id,
        env_path=env_path,
        resume=False,
    )

    assert identity.plan_sha256 == MODULE.sha256_file(plan_path)
    assert identity.effective_model_id == "provider/model-a"
    assert identity.model_alias == "external-model-name"
    assert identity.git_commit_at_start == "1" * 40
    assert identity.model_context_window_tokens == 100_000
    assert identity.request_profile == "deepseek_v4_openai"
    assert identity.thinking_mode == "disabled"
    assert identity.configured_concurrency == 32
    assert identity.effective_retrieval_sha256 is None
    assert command[-5:] == ["api", "tasks.jsonl", run_id, "baseline", "bclass/api/BLC_FINDVER_COT.yaml"]
    assert json.loads(environment["FINDVER_RUN_IDENTITY_JSON"])["plan_run_id"] == run_id
    assert environment["FINDVER_EXPECTED_MODEL_ID"] == "provider/model-a"


def test_executor_accepts_frozen_api_ablation_config_directory(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    source = (
        MODULE.REPO_ROOT
        / "configs"
        / "bclass"
        / "api"
        / "BLC_FINDVER_COT.yaml"
    )
    target = (
        MODULE.REPO_ROOT
        / "configs"
        / "bclass"
        / "ablations"
        / "RAG3_SEEDED.yaml"
    )
    target.parent.mkdir(parents=True)
    source.rename(target)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["runs"][0]["config"] = {
        "path": "configs/bclass/ablations/RAG3_SEEDED.yaml",
        "sha256": MODULE.sha256_file(target),
        "model_context_window_tokens": 100_000,
        "request_profile": "deepseek_v4_openai",
        "thinking": {"type": "disabled"},
        "configured_concurrency": 32,
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    identity, command, _ = MODULE.prepare_execution(
        plan_path,
        plan_run_id=run_id,
        env_path=env_path,
        resume=False,
    )

    assert identity.backend_kind == "api"
    assert command[-1] == "bclass/ablations/RAG3_SEEDED.yaml"


def test_executor_rejects_ablation_directory_for_local_backend(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)
    with pytest.raises(ValueError, match="outside the selected B-class"):
        MODULE._configuration_path(
            "configs/bclass/ablations/RAG3_SEEDED.yaml",
            backend_kind="local",
        )


def test_executor_rejects_model_substitution(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    env_path.write_text("MODEL_NAME=provider/other-model\n", encoding="utf-8")

    with pytest.raises(ValueError, match="planned effective model ID"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_rejects_artifact_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, task_path = _prepared_fixture(tmp_path, monkeypatch)
    task_path.write_text(
        '{"example_id":"changed","statement":"Claim","report":"one.json"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="public task SHA256"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_requires_clean_planned_commit(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(MODULE, "_git_is_clean", lambda: False)

    with pytest.raises(ValueError, match="clean tracked worktree"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_preserves_identity_on_explicit_resume(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)

    identity, command, _ = MODULE.prepare_execution(
        plan_path,
        plan_run_id=run_id,
        env_path=env_path,
        resume=True,
    )

    assert identity.plan_run_id == run_id
    assert command[-1] == "--resume"


def test_executor_rejects_context_window_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["runs"][0]["model_context_window_tokens"] = 128_000
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="context window"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_rejects_thinking_profile_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["runs"][0]["thinking"] = None
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="request profile or thinking"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_rejects_config_hash_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["runs"][0]["config"]["sha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="config SHA256"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_rejects_retrieval_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["retrieval"]["sha256"] = "0" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="retrieval SHA256"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_rejects_commit_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["code_commit"] = "2" * 40
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="HEAD"):
        MODULE.prepare_execution(
            plan_path,
            plan_run_id=run_id,
            env_path=env_path,
            resume=False,
        )


def test_executor_main_launches_exactly_one_single_model_plan_row(tmp_path, monkeypatch):
    identity = RunIdentity(
        plan_sha256="a" * 64,
        matrix_id="matrix-single-model-a",
        condition_id="BLC_FINDVER_COT",
        plan_run_id="matrix-single-model-a-model_a-BLC_FINDVER_COT",
        effective_model_id="deepseek-v4-flash",
        model_alias="external-model-name",
        backend_kind="api",
        git_commit_at_start="b" * 40,
        config_sha256="c" * 64,
        public_tasks_sha256="d" * 64,
        planned_retrieval_sha256="e" * 64,
        model_context_window_tokens=100_000,
        request_profile="deepseek_v4_openai",
        thinking_mode="disabled",
        configured_concurrency=32,
    )
    plan_path = tmp_path / "plan.json"
    env_path = tmp_path / "model.env"
    plan_path.write_text("{}", encoding="utf-8")
    env_path.write_text("MODEL_NAME=deepseek-v4-flash\n", encoding="utf-8")
    command = ["launcher", "one-row"]
    environment = {"BOUND": "1"}
    monkeypatch.setattr(
        MODULE,
        "prepare_execution",
        lambda *args, **kwargs: (identity, command, environment),
    )
    launched = []

    def fake_run(arguments, **kwargs):
        launched.append((arguments, kwargs))

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_bclass_plan.py",
            "--plan",
            str(plan_path),
            "--plan-run-id",
            identity.plan_run_id,
            "--env",
            str(env_path),
        ],
    )

    assert MODULE.main() == 0
    assert launched == [
        (
            command,
            {"cwd": MODULE.REPO_ROOT, "env": environment, "check": True},
        )
    ]
