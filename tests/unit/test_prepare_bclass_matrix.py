import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "prepare_bclass_matrix.py"
MANIFEST = ROOT / "experiments" / "bclass_dev_feedback_template.yaml"
TASK_FIXTURE = ROOT / "tests" / "fixtures" / "bclass_public_tasks.jsonl"
SPEC = importlib.util.spec_from_file_location("prepare_bclass_matrix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest_with_public_task_fixture(tmp_path, *, temperature=0):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    manifest["task"] = {
        "path": str(TASK_FIXTURE.relative_to(ROOT)),
        "sha256": MODULE.sha256_file(TASK_FIXTURE),
    }
    manifest["generation"]["temperature"] = temperature
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


def test_tracked_manifest_keeps_frozen_artifact_hashes():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["task"]["sha256"] == (
        "f51d29db5200c7166f74c9f7920ad8557d5db46a3b700f49513ef2932d1da0f5"
    )
    assert manifest["retrieval"]["sha256"] == (
        "2c29496e6762b3df2d51b01c246800b0512d396090785199d414703dbbf752e5"
    )


def test_two_explicit_distinct_models_produce_paired_independent_runs(tmp_path):
    manifest = _manifest_with_public_task_fixture(tmp_path)
    plan = MODULE.prepare_plan(
        manifest,
        model_a="provider/model-a",
        model_b="provider/model-b",
        backend_a="api",
        backend_b="local",
    )

    assert plan["status"] == "prepared_not_executed"
    assert plan["evaluation_split"] == "dev_feedback"
    assert plan["models"] == [
        {"slot": "model_a", "model_id": "provider/model-a", "backend_kind": "api"},
        {"slot": "model_b", "model_id": "provider/model-b", "backend_kind": "local"},
    ]
    assert len(plan["runs"]) == 14
    assert len({run["run_id"] for run in plan["runs"]}) == 14
    by_condition = {}
    for run in plan["runs"]:
        by_condition.setdefault(run["condition_id"], []).append(run)
    for paired_runs in by_condition.values():
        assert len(paired_runs) == 2
        assert paired_runs[0]["prompt_profile"] == paired_runs[1]["prompt_profile"]
        assert paired_runs[0]["maximum_model_calls"] == paired_runs[1]["maximum_model_calls"]
    assert plan["task"]["sha256"] == MODULE.sha256_file(TASK_FIXTURE)
    assert plan["retrieval"]["sha256"] == "2c29496e6762b3df2d51b01c246800b0512d396090785199d414703dbbf752e5"
    assert plan["generation"] == {
        "temperature": 0,
        "top_p": 1,
        "seed": 7,
        "max_output_tokens": 1024,
        "max_context_tokens": 32768,
    }


def test_matrix_rejects_same_model_id():
    with pytest.raises(ValueError, match="must be different"):
        MODULE.prepare_plan(
            MANIFEST,
            model_a="same-model",
            model_b="same-model",
            backend_a="api",
            backend_b="api",
        )


def test_matrix_rejects_generation_drift(tmp_path):
    changed = _manifest_with_public_task_fixture(tmp_path, temperature=1)

    with pytest.raises(ValueError, match="generation differs"):
        MODULE.prepare_plan(
            changed,
            model_a="model-a",
            model_b="model-b",
            backend_a="api",
            backend_b="local",
        )


def test_matrix_plan_writer_never_overwrites(tmp_path):
    path = tmp_path / "plan.json"
    MODULE._atomic_json(path, {"status": "prepared_not_executed"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "prepared_not_executed"
    with pytest.raises(ValueError, match="already exists"):
        MODULE._atomic_json(path, {"status": "replacement"})
