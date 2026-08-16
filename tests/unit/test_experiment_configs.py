from pathlib import Path

import pytest

from findver_agent.config import load_config


CONFIG_ROOT = Path(__file__).parents[2] / "configs"


@pytest.mark.parametrize("backend_kind", ["api", "local"])
def test_minimum_experiment_matrix_is_loadable(backend_kind):
    expected = {
        f"baseline_{backend_kind}.yaml": ("baseline", "direct", "none"),
        f"baseline_cot_{backend_kind}.yaml": ("baseline", "cot", "none"),
        f"baseline_bm25_{backend_kind}.yaml": ("baseline", "direct", "fixed_bm25"),
        f"agent_{backend_kind}.yaml": ("agent", True, False),
        f"agent_no_calculator_{backend_kind}.yaml": ("agent", False, False),
        f"agent_review_{backend_kind}.yaml": ("agent", True, True),
    }

    for filename, settings in expected.items():
        config = load_config(CONFIG_ROOT / filename)
        assert config.run.mode == settings[0]
        assert config.run.backend_kind == backend_kind
        if config.run.mode == "baseline":
            assert config.baseline is not None
            assert (config.baseline.prompt_type, config.baseline.retrieval) == settings[1:]
        else:
            assert config.agent is not None
            assert (config.agent.calculator_enabled, config.agent.pre_submit_review) == settings[1:]


def test_formal_seven_condition_api_matrix_is_loadable():
    expected = {
        "B0_API.yaml": ("baseline", "direct", "none"),
        "B1_API.yaml": ("baseline", "cot", "none"),
        "B2_API.yaml": ("baseline", "cot", "fixed_bm25"),
        "B3_API.yaml": ("baseline", "cot", "fixed_embedding"),
        "A0_API.yaml": ("agent", False, False),
        "A1_API.yaml": ("agent", True, False),
        "A2_API.yaml": ("agent", True, True),
    }
    loaded = {}
    for filename, settings in expected.items():
        config = load_config(CONFIG_ROOT / filename)
        loaded[filename] = config
        assert config.run.mode == settings[0]
        assert config.run.backend_kind == "api"
        assert config.generation.temperature == 1
        assert config.generation.top_p == 1
        assert config.generation.seed == 7
        assert config.generation.max_output_tokens == 1024
        if config.run.mode == "baseline":
            assert config.baseline is not None
            assert (config.baseline.prompt_type, config.baseline.retrieval) == settings[1:]
        else:
            assert config.agent is not None
            assert (config.agent.calculator_enabled, config.agent.pre_submit_review) == settings[1:]

    a0 = loaded["A0_API.yaml"].agent.model_dump()
    a1 = loaded["A1_API.yaml"].agent.model_dump()
    for key in ("calculator_enabled", "max_calculator_calls"):
        a0.pop(key)
        a1.pop(key)
