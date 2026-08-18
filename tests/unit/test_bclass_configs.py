from pathlib import Path

import pytest

from findver_agent.config import load_config
from findver_agent.experiment_config import (
    compose_effective_config,
    load_experiment_condition,
    load_model_deployment,
)


ROOT = Path(__file__).parents[2]
BCLASS = ROOT / "configs" / "bclass"
CONDITION_ROOT = ROOT / "configs" / "conditions" / "bclass"
DEPLOYMENT_ROOT = ROOT / "configs" / "deployments"
CONDITIONS = {
    "BLC_FINDVER_COT": "baseline",
    "BRAG10_FINDVER_COT": "baseline",
    "BITER_RAG10": "iterative_rag",
    "A_SCRATCH": "agent",
    "M0_RAG10_SEEDED": "agent",
    "M1_BUDGET_AWARE": "agent",
    "M2_SELECTIVE_REVIEW": "agent",
}


def method_section(config):
    return config.baseline or config.agent or config.iterative_rag


def test_canonical_conditions_compose_with_deployments_without_method_copies():
    deepseek = load_model_deployment(DEPLOYMENT_ROOT / "deepseek_v4_flash_api.yaml")
    qwen = load_model_deployment(DEPLOYMENT_ROOT / "qwen3_5_27b_dashscope.yaml")
    for condition_id, mode in CONDITIONS.items():
        condition = load_experiment_condition(
            CONDITION_ROOT / "main" / f"{condition_id}.yaml"
        )
        deepseek_config = compose_effective_config(condition, deepseek)
        qwen_config = compose_effective_config(condition, qwen)

        assert deepseek_config.run.mode == qwen_config.run.mode == mode
        assert deepseek_config.run.backend_kind == qwen_config.run.backend_kind == "api"
        assert deepseek_config.backend.transport_profile == "deepseek_openai_chat"
        assert qwen_config.backend.transport_profile == "dashscope_openai_chat"
        assert deepseek_config.backend.thinking is not None
        assert qwen_config.backend.thinking is not None
        assert deepseek_config.backend.rate_limit is None
        assert qwen_config.backend.rate_limit is not None
        assert qwen_config.backend.rate_limit.model_dump() == {
            "requests_per_minute": 540,
            "tokens_per_minute": 850_000,
        }
        assert deepseek_config.backend.model_context_window_tokens == 100_000
        assert qwen_config.backend.model_context_window_tokens == 100_000
        assert deepseek_config.generation == qwen_config.generation
        assert deepseek_config.generation.model_dump() == {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 7,
            "max_output_tokens": 1024,
            "prompt_budget_tokens": 32768,
        }
        assert method_section(deepseek_config) == method_section(qwen_config)
        assert method_section(deepseek_config).concurrency == 32


def test_historical_deepseek_and_local_config_paths_remain_loadable():
    for condition_id, mode in CONDITIONS.items():
        api = load_config(BCLASS / "api" / f"{condition_id}.yaml")
        local = load_config(BCLASS / "local" / f"{condition_id}.yaml")
        assert api.run.mode == local.run.mode == mode
        assert api.backend.request_profile == "deepseek_v4_openai"
        assert local.backend.request_profile == "generic_openai"


def test_main_bclass_method_settings_match_the_frozen_design():
    load = lambda name: load_config(BCLASS / "api" / f"{name}.yaml")

    blc = load("BLC_FINDVER_COT").baseline
    brag = load("BRAG10_FINDVER_COT").baseline
    iterative = load("BITER_RAG10").iterative_rag
    scratch = load("A_SCRATCH").agent
    m0 = load("M0_RAG10_SEEDED").agent
    m1 = load("M1_BUDGET_AWARE").agent
    m2 = load("M2_SELECTIVE_REVIEW").agent

    assert blc is not None and (blc.prompt_type, blc.retrieval) == (
        "findver_cot_json",
        "none",
    )
    assert brag is not None and (
        brag.prompt_type,
        brag.retrieval,
        brag.retriever,
        brag.top_k,
    ) == ("findver_cot_json", "fixed_retrieval", "text-embedding-3-large", 10)
    assert iterative is not None and (
        iterative.retrieval_rounds,
        iterative.finalization_steps,
        iterative.top_k,
    ) == (3, 2, 10)
    assert scratch is not None and not scratch.initial_retrieval.enabled
    assert scratch.review_policy == "selective"
    assert m0 is not None and m0.protocol_version == "v1"
    assert m0.initial_retrieval.enabled and not m0.pre_submit_review
    assert m1 is not None and (
        m1.protocol_version,
        m1.exploration_steps,
        m1.finalization_steps,
        m1.review_steps,
        m1.review_policy,
    ) == ("v2", 6, 2, 0, "none")
    assert m2 is not None and (
        m2.protocol_version,
        m2.exploration_steps,
        m2.finalization_steps,
        m2.review_steps,
        m2.review_policy,
    ) == ("v2", 6, 2, 1, "selective")


def test_top_k_ablations_use_independent_named_artifacts():
    paths = []
    for top_k in (3, 5, 10):
        config = load_config(BCLASS / "ablations" / f"RAG{top_k}_SEEDED.yaml")
        assert config.agent is not None
        assert config.backend.model_context_window_tokens == 100_000
        assert config.generation.prompt_budget_tokens == 32_768
        initial = config.agent.initial_retrieval
        assert initial.enabled
        assert initial.top_k == top_k
        assert initial.retriever == "text-embedding-3-large"
        paths.append(initial.retrieval_file)

    assert len(set(paths)) == 3
    assert [path.name for path in paths if path is not None] == [
        "findver_embedding3large_top3.json",
        "findver_embedding3large_top5.json",
        "findver_embedding3large_top10.json",
    ]


def test_two_round_biter_calibration_changes_only_fixed_round_budget():
    main = load_config(BCLASS / "api" / "BITER_RAG10.yaml")
    calibrated = load_config(BCLASS / "ablations" / "BITER2_RAG10.yaml")

    assert main.iterative_rag is not None
    assert calibrated.iterative_rag is not None
    assert main.generation == calibrated.generation
    assert main.backend == calibrated.backend
    assert main.iterative_rag.retrieval_rounds == 3
    assert calibrated.iterative_rag.retrieval_rounds == 2
    main_method = main.iterative_rag.model_dump()
    calibrated_method = calibrated.iterative_rag.model_dump()
    main_method.pop("retrieval_rounds")
    calibrated_method.pop("retrieval_rounds")
    assert main_method == calibrated_method


def test_budget4_sensitivity_changes_only_exploration_steps():
    main = load_config(BCLASS / "api" / "M2_SELECTIVE_REVIEW.yaml")
    budget4 = load_config(BCLASS / "ablations" / "M2_BUDGET4.yaml")

    assert main.agent is not None
    assert budget4.agent is not None
    assert main.generation == budget4.generation
    assert main.backend == budget4.backend
    assert main.agent.exploration_steps == 6
    assert budget4.agent.exploration_steps == 4
    main_method = main.agent.model_dump()
    budget4_method = budget4.agent.model_dump()
    main_method.pop("exploration_steps")
    budget4_method.pop("exploration_steps")
    assert main_method == budget4_method


@pytest.mark.parametrize(
    ("condition", "reference"),
    [
        ("RAG3_SEEDED", "RAG3_SEEDED"),
        ("RAG5_SEEDED", "RAG5_SEEDED"),
        ("BITER2_RAG10", "BITER2_RAG10"),
        ("M2_BUDGET4", "M2_BUDGET4"),
    ],
)
def test_canonical_extensions_compose_with_both_api_dialects(condition, reference):
    del reference
    condition_config = load_experiment_condition(
        CONDITION_ROOT / "extensions" / f"{condition}.yaml"
    )
    deepseek = compose_effective_config(
        condition_config,
        load_model_deployment(DEPLOYMENT_ROOT / "deepseek_v4_flash_api.yaml"),
    )
    qwen = compose_effective_config(
        condition_config,
        load_model_deployment(DEPLOYMENT_ROOT / "qwen3_5_27b_dashscope.yaml"),
    )
    assert deepseek.generation == qwen.generation
    assert method_section(deepseek) == method_section(qwen)
    assert qwen.backend.transport_profile == "dashscope_openai_chat"
    assert qwen.backend.rate_limit is not None


def test_lc_agent_firstpass_changes_only_the_scratch_initial_context():
    scratch = load_config(BCLASS / "api" / "A_SCRATCH.yaml")
    firstpass = load_config(BCLASS / "ablations" / "LC_AGENT_FIRSTPASS.yaml")

    assert scratch.agent is not None
    assert firstpass.agent is not None
    assert scratch.generation == firstpass.generation
    assert scratch.backend == firstpass.backend
    assert not firstpass.agent.initial_retrieval.enabled
    assert firstpass.agent.long_context.enabled
    assert firstpass.agent.long_context.scope == "first_exploration_attempt"
    assert not firstpass.agent.long_context.preload_as_evidence
    scratch_method = scratch.agent.model_dump()
    firstpass_method = firstpass.agent.model_dump()
    scratch_method.pop("long_context")
    firstpass_method.pop("long_context")
    assert scratch_method == firstpass_method
