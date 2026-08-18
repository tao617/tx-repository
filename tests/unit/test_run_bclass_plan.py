import importlib.util
import json
import sys
from pathlib import Path

import pytest

from findver_agent.run_identity import RunIdentity
from findver_agent.experiment_config import (
    compose_effective_config,
    effective_config_sha256,
    effective_config_value,
    load_experiment_condition,
    load_model_deployment,
)


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "run_bclass_plan.py"
CONFIG_FIXTURE = ROOT / "configs" / "bclass" / "api" / "BLC_FINDVER_COT.yaml"
QWEN_CONDITION_FIXTURE = (
    ROOT / "configs" / "conditions" / "bclass" / "main" / "BLC_FINDVER_COT.yaml"
)
QWEN_DEPLOYMENT_FIXTURE = (
    ROOT / "configs" / "deployments" / "qwen3_5_27b_dashscope.yaml"
)
LOCAL_32K_CONFIG_FIXTURE = (
    ROOT
    / "configs"
    / "local_models"
    / "deepseek_r1_distill_llama_8b_32k"
    / "M2_SELECTIVE_REVIEW_32K.yaml"
)
LC_CONFIG_FIXTURE = (
    ROOT / "configs" / "bclass" / "ablations" / "LC_AGENT_FIRSTPASS.yaml"
)
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


def _prepared_qwen_fixture(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    task_path = repo / "runtime_data" / "public" / "tasks.jsonl"
    retrieval_path = repo / "runtime_data" / "retrieval" / "retrieval.jsonl"
    condition_path = (
        repo
        / "configs"
        / "conditions"
        / "bclass"
        / "main"
        / "BLC_FINDVER_COT.yaml"
    )
    deployment_path = repo / "configs" / "deployments" / "qwen.yaml"
    task_path.parent.mkdir(parents=True)
    retrieval_path.parent.mkdir(parents=True)
    condition_path.parent.mkdir(parents=True)
    deployment_path.parent.mkdir(parents=True)
    task_path.write_text(
        '{"example_id":"one","statement":"Claim","report":"one.json"}\n',
        encoding="utf-8",
    )
    retrieval_path.write_text(
        '{"example_id":"one","paragraph_ids":[1]}\n', encoding="utf-8"
    )
    condition_path.write_text(
        QWEN_CONDITION_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    deployment_path.write_text(
        QWEN_DEPLOYMENT_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    condition = load_experiment_condition(condition_path)
    deployment = load_model_deployment(deployment_path)
    effective = compose_effective_config(condition, deployment)
    rate_limit = {
        "requests_per_minute": 540,
        "tokens_per_minute": 850_000,
    }
    commit = "1" * 40
    run_id = "matrix-model_b-BLC_FINDVER_COT"
    condition_spec = {
        "condition_id": "BLC_FINDVER_COT",
        "family": "main",
        "path": "configs/conditions/bclass/main/BLC_FINDVER_COT.yaml",
        "sha256": MODULE.sha256_file(condition_path),
    }
    deployment_spec = {
        "slot": "model_b",
        "deployment_id": "qwen3_5_27b_dashscope",
        "path": "configs/deployments/qwen.yaml",
        "sha256": MODULE.sha256_file(deployment_path),
    }
    plan = {
        "schema_version": 3,
        "status": "prepared_not_executed",
        "matrix_id": "matrix",
        "code_commit": commit,
        "task": {
            "path": "runtime_data/public/tasks.jsonl",
            "sha256": MODULE.sha256_file(task_path),
        },
        "retrieval": {
            "path": "runtime_data/retrieval/retrieval.jsonl",
            "sha256": MODULE.sha256_file(retrieval_path),
        },
        "conditions": [condition_spec],
        "deployments": [deployment_spec],
        "runs": [
            {
                "slot": "model_b",
                "deployment_id": "qwen3_5_27b_dashscope",
                "condition_id": "BLC_FINDVER_COT",
                "run_id": run_id,
                "command": "baseline",
            "model_id": "qwen3.5-27b",
                "backend_kind": "api",
                "model_context_window_tokens": 100_000,
                "transport_profile": "dashscope_openai_chat",
                "thinking_mode": "disabled",
            "rate_limit": rate_limit,
                "configured_concurrency": 32,
                "effective_retrieval_required": False,
                "condition": {
                    key: condition_spec[key] for key in ("family", "path", "sha256")
                },
                "deployment": {
                    key: deployment_spec[key] for key in ("path", "sha256")
                },
                "effective_config": {
                    "sha256": effective_config_sha256(effective),
                    "value": effective_config_value(effective),
                },
            }
        ],
    }
    plan_path = tmp_path / "qwen-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    env_path = tmp_path / "qwen.env"
    env_path.write_text(
        "MODEL_BASE_URL=https://example.invalid/v1\n"
        "MODEL_API_KEY=secret\n"
        "MODEL_NAME=qwen3.5-27b\n",
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


def test_executor_composes_qwen_deployment_and_binds_rate_limits(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_qwen_fixture(tmp_path, monkeypatch)

    identity, command, _ = MODULE.prepare_execution(
        plan_path,
        plan_run_id=run_id,
        env_path=env_path,
        resume=False,
    )

    assert identity.effective_model_id == "qwen3.5-27b"
    assert identity.request_profile == "dashscope_openai_chat"
    assert identity.thinking_mode == "disabled"
    assert identity.rate_limit_requests_per_minute == 540
    assert identity.rate_limit_tokens_per_minute == 850_000
    assert command[-1].startswith("@effective/")
    assert command[-1].endswith(".json")


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


def test_executor_enforces_planned_long_context_without_effective_retrieval(
    tmp_path, monkeypatch
):
    plan_path, env_path, run_id, _ = _prepared_fixture(tmp_path, monkeypatch)
    target = (
        MODULE.REPO_ROOT
        / "configs"
        / "bclass"
        / "ablations"
        / "LC_AGENT_FIRSTPASS.yaml"
    )
    target.parent.mkdir(parents=True)
    target.write_text(LC_CONFIG_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    run = plan["runs"][0]
    run.update(
        {
            "condition_id": "LC_AGENT_FIRSTPASS",
            "command": "run",
            "effective_retrieval_required": False,
            "long_context_scope": "first_exploration_attempt",
            "config": {
                "path": "configs/bclass/ablations/LC_AGENT_FIRSTPASS.yaml",
                "sha256": MODULE.sha256_file(target),
                "model_context_window_tokens": 100_000,
                "request_profile": "deepseek_v4_openai",
                "thinking": {"type": "disabled"},
                "configured_concurrency": 32,
            },
        }
    )
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    identity, command, _ = MODULE.prepare_execution(
        plan_path,
        plan_run_id=run_id,
        env_path=env_path,
        resume=False,
    )

    assert identity.condition_id == "LC_AGENT_FIRSTPASS"
    assert identity.effective_retrieval_sha256 is None
    assert command[-2:] == ["run", "bclass/ablations/LC_AGENT_FIRSTPASS.yaml"]


def test_executor_rejects_ablation_directory_for_local_backend(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)
    with pytest.raises(ValueError, match="outside the selected formal"):
        MODULE._configuration_path(
            "configs/bclass/ablations/RAG3_SEEDED.yaml",
            backend_kind="local",
        )


def test_executor_allows_dedicated_32k_directories_for_local_model_plan(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    target = (
        repo
        / "configs"
        / "local_models"
        / "deepseek_r1_distill_llama_8b_32k"
        / "M2_SELECTIVE_REVIEW_32K.yaml"
    )
    target.parent.mkdir(parents=True)
    target.write_text(
        LOCAL_32K_CONFIG_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)

    assert MODULE._configuration_path(
        "configs/local_models/deepseek_r1_distill_llama_8b_32k/"
        "M2_SELECTIVE_REVIEW_32K.yaml",
        backend_kind="local",
        plan_purpose="independent-local-model-public-development",
    ) == target
    qwen_target = (
        repo
        / "configs"
        / "local_models"
        / "qwen2_5_7b_32k"
        / "QWEN2_5_7B_M2_32K.yaml"
    )
    qwen_target.parent.mkdir(parents=True)
    qwen_target.write_text(
        LOCAL_32K_CONFIG_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert MODULE._configuration_path(
        "configs/local_models/qwen2_5_7b_32k/QWEN2_5_7B_M2_32K.yaml",
        backend_kind="local",
        plan_purpose="independent-local-model-public-development",
    ) == qwen_target
    with pytest.raises(ValueError, match="outside the selected formal"):
        MODULE._configuration_path(
            "configs/local_models/deepseek_r1_distill_llama_8b_32k/"
            "M2_SELECTIVE_REVIEW_32K.yaml",
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


def test_executor_rejects_composable_rate_limit_drift(tmp_path, monkeypatch):
    plan_path, env_path, run_id, _ = _prepared_qwen_fixture(tmp_path, monkeypatch)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["runs"][0]["rate_limit"]["tokens_per_minute"] = 999_999
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="rate limit"):
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
    postprocessed = []
    monkeypatch.setattr(MODULE, "postprocess_completed_run", postprocessed.append)
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
    assert postprocessed == [identity.plan_run_id]


def test_postprocess_completed_run_summarizes_seals_and_verifies(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    run_id = "matrix-model_a-RAG3_SEEDED"
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)
    launched = []

    def fake_run(arguments, **kwargs):
        launched.append((arguments, kwargs))
        if "summarize_run.py" in arguments[1]:
            (run_dir / "efficiency-summary.json").write_text("{}\n", encoding="utf-8")
        if "seal_submission.py" in arguments[1]:
            (run_dir / "submission.tar.gz").write_bytes(b"sealed")
            (run_dir / MODULE.SIDECAR_NAME).write_text("", encoding="utf-8")

    verified = []

    class Manifest:
        def __init__(self, value):
            self.run_id = value

    def fake_verify(archive, *, evidence_ledger_sidecar):
        verified.append((archive, evidence_ledger_sidecar))
        return Manifest(run_id), []

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "verify_submission_archive", fake_verify)

    MODULE.postprocess_completed_run(run_id)

    assert [Path(call[0][1]).name for call in launched] == [
        "summarize_run.py",
        "seal_submission.py",
    ]
    assert all(call[1] == {"cwd": repo, "check": True} for call in launched)
    assert verified == [
        (run_dir / "submission.tar.gz", run_dir / MODULE.SIDECAR_NAME)
    ]


def test_postprocess_completed_run_rejects_incomplete_metadata(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    run_id = "matrix-model_a-RAG3_SEEDED"
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_metadata.json").write_text(
        json.dumps({"status": "running"}), encoding="utf-8"
    )
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)

    with pytest.raises(ValueError, match="did not complete"):
        MODULE.postprocess_completed_run(run_id)
