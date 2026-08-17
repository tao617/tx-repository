from pathlib import Path

from findver_agent.config import load_config


ROOT = Path(__file__).parents[2]
BCLASS = ROOT / "configs" / "bclass"
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


def test_api_and_local_bclass_configs_are_paired_and_loadable():
    for condition_id, mode in CONDITIONS.items():
        api = load_config(BCLASS / "api" / f"{condition_id}.yaml")
        local = load_config(BCLASS / "local" / f"{condition_id}.yaml")

        assert api.run.mode == local.run.mode == mode
        assert api.run.backend_kind == "api"
        assert local.run.backend_kind == "local"
        assert api.backend.model == "external-model-name"
        assert local.backend.model == "local-small-model"
        assert api.backend.request_profile == "deepseek_v4_openai"
        assert api.backend.thinking is not None
        assert api.backend.thinking.type == "disabled"
        assert local.backend.request_profile == "generic_openai"
        assert local.backend.thinking is None
        assert api.backend.model_context_window_tokens == local.backend.model_context_window_tokens == 100_000
        assert api.generation == local.generation
        assert api.generation.model_dump() == {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 7,
            "max_output_tokens": 1024,
            "prompt_budget_tokens": 32768,
        }
        assert method_section(api) == method_section(local)
        assert method_section(api).concurrency == 32


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
