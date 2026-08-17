import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "prepare_bclass_extension.py"
MANIFEST = ROOT / "experiments" / "bclass_dev_feedback_template.yaml"
TASK_FIXTURE = ROOT / "tests" / "fixtures" / "bclass_public_tasks.jsonl"
SPEC = importlib.util.spec_from_file_location("prepare_bclass_extension", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    manifest["task"] = {
        "path": str(TASK_FIXTURE.relative_to(ROOT)),
        "sha256": MODULE.sha256_file(TASK_FIXTURE),
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("condition", "top_k", "config_name", "maximum_calls", "command"),
    [
        ("RAG3_SEEDED", 3, "RAG3_SEEDED.yaml", 9, "run"),
        ("RAG5_SEEDED", 5, "RAG5_SEEDED.yaml", 9, "run"),
        ("BITER2_RAG10", 10, "BITER2_RAG10.yaml", 4, "iterative-rag"),
    ],
)
def test_extension_plan_binds_condition_retrieval_and_transport(
    tmp_path, condition, top_k, config_name, maximum_calls, command
):
    plan = MODULE.prepare_extension_plan(
        _manifest(tmp_path),
        condition_id=condition,
        matrix_id=f"extension-{condition.lower()}",
        model_id="deepseek-v4-flash",
        context_window=100_000,
    )

    assert plan["schema_version"] == 2
    assert plan["status"] == "prepared_not_executed"
    assert plan["retrieval"]["top_k"] == top_k
    assert plan["retrieval"]["retriever"] == "text-embedding-3-large"
    assert plan["models"][0]["thinking"] == {"type": "disabled"}
    run = plan["runs"][0]
    assert run["condition_id"] == condition
    assert run["command"] == command
    assert run["maximum_model_calls"] == maximum_calls
    assert run["configured_concurrency"] == 32
    assert run["config"]["path"].endswith(config_name)


def test_extension_is_dev_feedback_only(tmp_path):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    manifest["evaluation_split"] = "dev_holdout"
    path = tmp_path / "holdout.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="dev_feedback only"):
        MODULE.prepare_extension_plan(
            path,
            condition_id="RAG3_SEEDED",
            matrix_id="extension-top3",
            model_id="deepseek-v4-flash",
            context_window=100_000,
        )


def test_extension_writer_never_overwrites(tmp_path):
    output = tmp_path / "plan.json"
    MODULE._atomic_json(output, {"status": "prepared_not_executed"})
    with pytest.raises(ValueError, match="already exists"):
        MODULE._atomic_json(output, {"status": "replacement"})
