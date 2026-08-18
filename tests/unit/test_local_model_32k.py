import importlib.util
import json
from pathlib import Path

import pytest

from findver_agent.config import load_config


ROOT = Path(__file__).parents[2]
CONFIG = (
    ROOT
    / "configs"
    / "local_models"
    / "deepseek_r1_distill_llama_8b_32k"
    / "M2_SELECTIVE_REVIEW_32K.yaml"
)
FROZEN_M2 = ROOT / "configs" / "bclass" / "local" / "M2_SELECTIVE_REVIEW.yaml"
QWEN_CONFIGS = {
    "QWEN2_5_7B_M2_32K": (
        ROOT
        / "configs"
        / "local_models"
        / "qwen2_5_7b_32k"
        / "QWEN2_5_7B_M2_32K.yaml"
    ),
    "QWEN2_5_14B_M2_32K": (
        ROOT
        / "configs"
        / "local_models"
        / "qwen2_5_14b_32k"
        / "QWEN2_5_14B_M2_32K.yaml"
    ),
}
SCRIPT = ROOT / "scripts" / "prepare_local_model_run.py"
SPEC = importlib.util.spec_from_file_location("prepare_local_model_run", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_32k_config_retains_m2_method_without_claiming_100k_capacity():
    config = load_config(CONFIG)
    frozen = load_config(FROZEN_M2)

    assert config.run.mode == "agent"
    assert config.run.backend_kind == "local"
    assert config.backend.model_context_window_tokens == 32768
    assert config.backend.request_profile == "generic_openai"
    assert config.backend.thinking is None
    assert config.generation.model_dump() == {
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 7,
        "max_output_tokens": 1024,
        "prompt_budget_tokens": 28672,
    }
    assert config.agent is not None and frozen.agent is not None
    local_method = config.agent.model_dump()
    frozen_method = frozen.agent.model_dump()
    assert local_method.pop("concurrency") == 2
    assert frozen_method.pop("concurrency") == 32
    assert local_method == frozen_method


def test_qwen_configs_are_method_and_generation_identical_to_local_32k_m2():
    reference = load_config(CONFIG)
    for condition_id, path in QWEN_CONFIGS.items():
        qwen = load_config(path)
        assert path.stem == condition_id
        assert qwen.model_dump() == reference.model_dump()


def _local_repo_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    task = repo / "runtime_data" / "public" / "tasks.jsonl"
    retrieval = (
        repo
        / "runtime_data"
        / "retrieval"
        / "findver_embedding3large_top10.json"
    )
    config = repo / MODULE.CONFIG_RELATIVE
    task.parent.mkdir(parents=True)
    retrieval.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    task.write_text(
        '{"example_id":"one","statement":"Claim","report":"one.json"}\n',
        encoding="utf-8",
    )
    retrieval.write_text(
        '[{"example_id":"one","report":"one.json","paragraph_ids":[0,1,2,3,4,5,6,7,8,9],"retriever":"text-embedding-3-large","top_k":10}]\n',
        encoding="utf-8",
    )
    config.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(MODULE, "REPO_ROOT", repo)
    monkeypatch.setattr(MODULE, "_git_commit", lambda: "1" * 40)
    return repo, task


def test_local_model_plan_binds_32k_generic_profile_and_public_task(
    tmp_path, monkeypatch
):
    _, task = _local_repo_fixture(tmp_path, monkeypatch)

    plan = MODULE.prepare_plan(
        task_name=task.name,
        matrix_id="deepseek-r1-8b-smoke",
        model_id="deepseek-r1-distill-8b",
        context_window=32768,
    )

    assert plan["schema_version"] == 2
    assert plan["status"] == "prepared_not_executed"
    assert plan["purpose"] == "independent-local-model-public-development"
    assert plan["scorer_handoff_authorized"] is False
    assert plan["holdout_or_hidden_authorized"] is False
    assert plan["task"]["sha256"] == MODULE.sha256_file(task)
    run = plan["runs"][0]
    assert run["condition_id"] == "M2_SELECTIVE_REVIEW_32K"
    assert run["backend_kind"] == "local"
    assert run["model_context_window_tokens"] == 32768
    assert run["request_profile"] == "generic_openai"
    assert run["thinking"] is None
    assert run["configured_concurrency"] == 2
    assert run["maximum_model_calls"] == 9


def test_local_model_plan_rejects_capacity_misrepresentation(tmp_path, monkeypatch):
    _, task = _local_repo_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="32768-token window"):
        MODULE.prepare_plan(
            task_name=task.name,
            matrix_id="deepseek-r1-8b-smoke",
            model_id="deepseek-r1-distill-8b",
            context_window=100000,
        )


def test_local_model_plan_accepts_a_dedicated_qwen_config(tmp_path, monkeypatch):
    repo, task = _local_repo_fixture(tmp_path, monkeypatch)
    qwen_relative = Path(
        "configs/local_models/qwen2_5_7b_32k/QWEN2_5_7B_M2_32K.yaml"
    )
    qwen_path = repo / qwen_relative
    qwen_path.parent.mkdir(parents=True)
    qwen_path.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    plan = MODULE.prepare_plan(
        task_name=task.name,
        matrix_id="findver-qwen2-5-7b-32k-smoke-v1",
        model_id="qwen2.5-7b-instruct",
        context_window=32768,
        config_relative=qwen_relative,
        condition_id="QWEN2_5_7B_M2_32K",
    )

    run = plan["runs"][0]
    assert run["condition_id"] == "QWEN2_5_7B_M2_32K"
    assert run["run_id"].endswith("-QWEN2_5_7B_M2_32K")
    assert run["config"]["path"] == qwen_relative.as_posix()


def test_local_model_plan_writer_is_private_and_never_overwrites(tmp_path):
    output = tmp_path / "plan.json"
    MODULE._atomic_json(output, {"status": "prepared_not_executed"})
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "prepared_not_executed"
    with pytest.raises(ValueError, match="already exists"):
        MODULE._atomic_json(output, {"status": "replacement"})
