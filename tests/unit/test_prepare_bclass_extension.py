import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "prepare_bclass_extension.py"
MANIFEST = ROOT / "experiments" / "bclass_composable_template.yaml"
TASK_FIXTURE = ROOT / "tests" / "fixtures" / "bclass_public_tasks.jsonl"
DEEPSEEK = ROOT / "configs" / "deployments" / "deepseek_v4_flash_api.yaml"
QWEN = ROOT / "configs" / "deployments" / "qwen3_5_27b_dashscope.yaml"
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
    ("condition", "top_k", "maximum_calls", "command"),
    [
        ("RAG3_SEEDED", 3, 9, "run"),
        ("RAG5_SEEDED", 5, 9, "run"),
        ("BITER2_RAG10", 10, 4, "iterative-rag"),
        ("M2_BUDGET4", 10, 7, "run"),
    ],
)
def test_extension_plan_binds_condition_deployment_and_effective_config(
    tmp_path, condition, top_k, maximum_calls, command
):
    plan = MODULE.prepare_extension_plan(
        _manifest(tmp_path),
        condition_id=condition,
        matrix_id=f"extension-{condition.lower()}",
        deployment=DEEPSEEK,
    )

    run = plan["runs"][0]
    assert plan["schema_version"] == 3
    assert plan["retrieval"]["top_k"] == top_k
    assert run["condition"]["path"].endswith(f"/{condition}.yaml")
    assert run["deployment"]["path"].endswith("/deepseek_v4_flash_api.yaml")
    assert run["transport_profile"] == "deepseek_openai_chat"
    assert run["maximum_model_calls"] == maximum_calls
    assert run["command"] == command
    assert run["effective_retrieval_required"] is True
    assert len(run["effective_config"]["sha256"]) == 64


@pytest.mark.parametrize("condition", MODULE.EXTENSION_CONDITION_ORDER)
def test_qwen_model_b_extension_reuses_the_same_condition_file(tmp_path, condition):
    plan = MODULE.prepare_extension_plan(
        _manifest(tmp_path),
        condition_id=condition,
        matrix_id=f"qwen-{condition.lower()}",
        deployment=QWEN,
        slot="model_b",
    )
    run = plan["runs"][0]
    assert run["slot"] == "model_b"
    assert run["transport_profile"] == "dashscope_openai_chat"
    assert run["thinking_mode"] == "disabled"
    assert run["rate_limit"] == {
        "requests_per_minute": 540,
        "tokens_per_minute": 850_000,
    }
    assert "configs/conditions/bclass/extensions/" in run["condition"]["path"]
    assert "qwen_ablations" not in str(plan)


def test_only_the_four_canonical_extensions_are_supported(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        MODULE.prepare_extension_plan(
            _manifest(tmp_path),
            condition_id="LC_AGENT_FIRSTPASS",
            matrix_id="legacy-only",
            deployment=QWEN,
        )


def test_extension_is_dev_feedback_only(tmp_path):
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    manifest["evaluation_split"] = "unknown"
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="lifecycle"):
        MODULE.prepare_extension_plan(
            path,
            condition_id="RAG3_SEEDED",
            matrix_id="extension",
            deployment=DEEPSEEK,
        )
