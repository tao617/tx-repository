import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "prepare_bclass_matrix.py"
MANIFEST = ROOT / "experiments" / "bclass_composable_template.yaml"
TASK_FIXTURE = ROOT / "tests" / "fixtures" / "bclass_public_tasks.jsonl"
DEEPSEEK = ROOT / "configs" / "deployments" / "deepseek_v4_flash_api.yaml"
QWEN = ROOT / "configs" / "deployments" / "qwen3_5_27b_dashscope.yaml"
SPEC = importlib.util.spec_from_file_location("prepare_bclass_matrix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest_with_public_task_fixture(tmp_path):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    manifest["task"] = {
        "path": str(TASK_FIXTURE.relative_to(ROOT)),
        "sha256": MODULE.sha256_file(TASK_FIXTURE),
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


def test_tracked_manifest_keeps_frozen_artifact_hashes_and_single_condition_paths():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["task"]["sha256"] == (
        "f51d29db5200c7166f74c9f7920ad8557d5db46a3b700f49513ef2932d1da0f5"
    )
    assert manifest["retrieval_artifacts"]["top10"]["sha256"] == (
        "2c29496e6762b3df2d51b01c246800b0512d396090785199d414703dbbf752e5"
    )
    assert len(manifest["conditions"]) == 7
    assert len(manifest["extensions"]) == 4
    assert all("configs/conditions/" in path for path in manifest["conditions"])


def test_two_deployments_compose_fourteen_hash_bound_runs(tmp_path):
    plan = MODULE.prepare_plan(
        _manifest_with_public_task_fixture(tmp_path),
        deployment_a=DEEPSEEK,
        deployment_b=QWEN,
    )

    assert plan["schema_version"] == 3
    assert plan["status"] == "prepared_not_executed"
    assert len(plan["runs"]) == 14
    assert len({run["run_id"] for run in plan["runs"]}) == 14
    assert {item["transport_profile"] for item in plan["deployments"]} == {
        "deepseek_openai_chat",
        "dashscope_openai_chat",
    }
    assert all("qwen_api" not in str(run) for run in plan["runs"])
    by_condition = {}
    for run in plan["runs"]:
        by_condition.setdefault(run["condition_id"], []).append(run)
        assert len(run["condition"]["sha256"]) == 64
        assert len(run["deployment"]["sha256"]) == 64
        assert len(run["effective_config"]["sha256"]) == 64
    for paired_runs in by_condition.values():
        assert len(paired_runs) == 2
        assert paired_runs[0]["condition"] == paired_runs[1]["condition"]
        assert paired_runs[0]["prompt_profile"] == paired_runs[1]["prompt_profile"]
        assert paired_runs[0]["maximum_model_calls"] == paired_runs[1]["maximum_model_calls"]


def test_qwen_is_only_a_deployment_over_the_same_seven_conditions(tmp_path):
    plan = MODULE.prepare_plan(
        _manifest_with_public_task_fixture(tmp_path),
        deployment_a=QWEN,
    )

    assert len(plan["runs"]) == 7
    assert {run["deployment_id"] for run in plan["runs"]} == {
        "qwen3_5_27b_dashscope"
    }
    assert {run["transport_profile"] for run in plan["runs"]} == {
        "dashscope_openai_chat"
    }
    assert {run["thinking_mode"] for run in plan["runs"]} == {"disabled"}
    assert {run["rate_limit"]["requests_per_minute"] for run in plan["runs"]} == {540}
    assert all(
        run["condition"]["path"].startswith("configs/conditions/bclass/main/")
        for run in plan["runs"]
    )


def test_single_deployment_gets_distinct_matrix_scope(tmp_path):
    single = MODULE.prepare_plan(
        _manifest_with_public_task_fixture(tmp_path), deployment_a=DEEPSEEK
    )
    paired = MODULE.prepare_plan(
        _manifest_with_public_task_fixture(tmp_path),
        deployment_a=DEEPSEEK,
        deployment_b=QWEN,
    )
    assert single["matrix_id"].endswith("-single-model-a")
    assert single["matrix_id"] != paired["matrix_id"]
    assert len(single["runs"]) == 7


def test_duplicate_deployment_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="distinct deployment IDs"):
        MODULE.prepare_plan(
            _manifest_with_public_task_fixture(tmp_path),
            deployment_a=DEEPSEEK,
            deployment_b=DEEPSEEK,
        )


def test_manifest_condition_order_drift_fails_closed(tmp_path):
    path = _manifest_with_public_task_fixture(tmp_path)
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["conditions"] = list(reversed(manifest["conditions"]))
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="fixed B-class order"):
        MODULE.prepare_plan(path, deployment_a=DEEPSEEK)


def test_manifest_artifact_hash_drift_fails_closed(tmp_path):
    path = _manifest_with_public_task_fixture(tmp_path)
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["retrieval_artifacts"]["top10"]["sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="top10 SHA256"):
        MODULE.prepare_plan(path, deployment_a=DEEPSEEK)
