import json
from pathlib import Path

import pytest

from findver_agent.experiment_config import (
    compose_effective_config,
    load_experiment_condition,
    load_model_deployment,
)
from findver_agent.fixed_retrieval import FixedRetrievalIndex
from findver_agent.retrieval_control_planner import prepare_control_plan
from scripts.prepare_retrieval_control_artifact import RRF_K, _fuse, build


ROOT = Path(__file__).parents[2]
CONDITION_ROOT = ROOT / "configs" / "conditions" / "bclass"
DEPLOYMENT_ROOT = ROOT / "configs" / "deployments"
MANIFEST = ROOT / "experiments" / "retrieval_controls_dev_template.yaml"


def _write_report(root: Path, count: int = 20) -> Path:
    root.mkdir()
    (root / "report.json").write_text(
        json.dumps({"context": [{"context": f"paragraph {i}"} for i in range(count)]}),
        encoding="utf-8",
    )
    return root


def _write_tasks(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "example_id": "example",
                "statement": "claim",
                "report": "report.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_ranked(path: Path, paragraph_ids: list[int]) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "example_id": "example",
                    "report": "reports/processed_reports/report.json",
                    "retrieved_paragraphs": [
                        [paragraph_id, float(len(paragraph_ids) - rank)]
                        for rank, paragraph_id in enumerate(paragraph_ids)
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_rrf_is_fixed_deduplicated_top10_and_document_ordered():
    assert RRF_K == 60
    fused = _fuse(list(range(10)), list(range(100, 110)))

    assert fused == [0, 1, 2, 3, 4, 100, 101, 102, 103, 104]
    assert fused == sorted(set(fused))
    assert len(fused) == 10


def test_control_artifact_builder_uses_rank_top10_then_document_order(tmp_path):
    reports = _write_report(tmp_path / "reports")
    tasks = _write_tasks(tmp_path / "tasks.jsonl")
    bm25 = _write_ranked(tmp_path / "bm25.json", list(range(19, -1, -1)))
    embedding = _write_ranked(tmp_path / "embedding.json", list(range(20)))

    bm25_value = build(
        mode="bm25",
        tasks_path=tasks,
        reports_path=reports,
        bm25_paths=[bm25],
        embedding_paths=None,
        source_commit="frozen",
    )
    hybrid_value = build(
        mode="hybrid_rrf",
        tasks_path=tasks,
        reports_path=reports,
        bm25_paths=[bm25],
        embedding_paths=[embedding],
        source_commit="frozen",
    )

    assert bm25_value["items"]["example"]["retrieved_context"] == list(range(10, 20))
    hybrid_ids = hybrid_value["items"]["example"]["retrieved_context"]
    assert hybrid_ids == sorted(set(hybrid_ids))
    assert len(hybrid_ids) == 10
    expected_metadata = {
        "retriever": "hybrid-rrf",
        "input_top_k": 10,
        "top_k": 10,
        "output_order": "document",
        "rrf_k": 60,
        "deduplicated": True,
    }
    assert all(
        hybrid_value["metadata"].get(key) == value
        for key, value in expected_metadata.items()
    )


def test_ranked_control_source_rejects_gold_bearing_record(tmp_path):
    reports = _write_report(tmp_path / "reports")
    tasks = _write_tasks(tmp_path / "tasks.jsonl")
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            [
                {
                    "example_id": "example",
                    "report": "report.json",
                    "retrieved_paragraphs": [[0, 1.0]],
                    "label": "entailed",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="gold-bearing"):
        build(
            mode="bm25",
            tasks_path=tasks,
            reports_path=reports,
            bm25_paths=[source],
            embedding_paths=None,
            source_commit="frozen",
        )


@pytest.mark.parametrize(
    ("condition_id", "retriever", "artifact_name"),
    [
        ("BBM25_10", "bm25", "findver_bm25_top10_dev.json"),
        ("BHYBRID_RRF10", "hybrid-rrf", "findver_hybrid_rrf60_top10_dev.json"),
    ],
)
def test_controls_match_brag_prompt_generation_and_load_artifacts(
    condition_id, retriever, artifact_name
):
    brag = load_experiment_condition(CONDITION_ROOT / "main" / "BRAG10_FINDVER_COT.yaml")
    control = load_experiment_condition(
        CONDITION_ROOT / "controls" / f"{condition_id}.yaml"
    )
    assert control.family == "control"
    assert control.prompt_profile == brag.prompt_profile
    assert control.generation == brag.generation
    assert control.baseline is not None and brag.baseline is not None
    assert control.baseline.prompt_type == brag.baseline.prompt_type
    assert control.baseline.top_k == brag.baseline.top_k == 10
    assert control.baseline.concurrency == brag.baseline.concurrency == 32
    assert control.baseline.retriever == retriever

    path = ROOT / "runtime_data" / "retrieval" / artifact_name
    index = FixedRetrievalIndex(path, retriever=retriever, top_k=10)
    assert index.metadata["examples"] == 700
    assert index.metadata["output_order"] == "document"


@pytest.mark.parametrize(
    ("condition_id", "artifact_name"),
    [
        ("BBM25_10", "findver_bm25_top10_dev.json"),
        ("BHYBRID_RRF10", "findver_hybrid_rrf60_top10_dev.json"),
    ],
)
def test_control_plans_bind_one_model_a_row(condition_id, artifact_name):
    plan = prepare_control_plan(
        MANIFEST,
        condition_id=condition_id,
        deployment_path=DEPLOYMENT_ROOT / "deepseek_v4_flash_api.yaml",
        slot="model_a",
    )

    assert plan["schema_version"] == 3
    assert plan["status"] == "prepared_not_executed"
    assert plan["evaluation_split"] == "dev_feedback"
    assert plan["retrieval"]["path"].endswith(artifact_name)
    assert len(plan["runs"]) == 1
    run = plan["runs"][0]
    assert run["condition_id"] == condition_id
    assert run["condition"]["family"] == "control"
    assert run["maximum_model_calls"] == 1
    assert run["effective_retrieval_required"] is True
    assert run["model_id"] == "deepseek-v4-flash"


def test_control_conditions_compose_identically_across_models():
    deepseek = load_model_deployment(DEPLOYMENT_ROOT / "deepseek_v4_flash_api.yaml")
    qwen = load_model_deployment(DEPLOYMENT_ROOT / "qwen3_5_27b_dashscope.yaml")
    for condition_id in ("BBM25_10", "BHYBRID_RRF10"):
        condition = load_experiment_condition(
            CONDITION_ROOT / "controls" / f"{condition_id}.yaml"
        )
        model_a = compose_effective_config(condition, deepseek)
        model_b = compose_effective_config(condition, qwen)
        assert model_a.generation == model_b.generation
        assert model_a.baseline == model_b.baseline
