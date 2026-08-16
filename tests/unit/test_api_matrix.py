import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "run_api_matrix.py"
SPEC = importlib.util.spec_from_file_location("run_api_matrix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def matrix_state():
    return {
        "conditions": {
            condition_id: {"status": "pending"}
            for condition_id in MODULE.CONDITION_ORDER
        }
    }


def test_matrix_resume_skips_completed_conditions():
    state = matrix_state()
    state["conditions"]["B0_API"]["status"] = "completed"
    state["conditions"]["B2_API"]["status"] = "completed"

    assert MODULE.selected_conditions(state) == (
        "B1_API",
        "B3_API",
        "A0_API",
        "A1_API",
        "A2_API",
    )
    assert MODULE.selected_conditions(state, "B0_API") == ()


def test_matrix_resume_rejects_changed_frozen_input():
    frozen = {
        "manifest_sha256": "a",
        "code_commit": "b",
        "task_sha256": "c",
        "retrieval_sha256": "d",
        "model": "e",
        "config_hashes": {"B0_API": "f"},
    }
    state = dict(frozen)
    MODULE.validate_resume(state, frozen)

    changed = dict(frozen)
    changed["task_sha256"] = "different"
    with pytest.raises(ValueError, match="task_sha256 changed"):
        MODULE.validate_resume(state, changed)


@pytest.mark.parametrize(
    ("delta", "subsets", "expected"),
    [
        (0.5, {"ie": 1, "math": 1, "know": 1}, "不足 1"),
        (1.5, {"ie": 1, "math": 1, "know": 1}, "趋势"),
        (2.0, {"ie": 1, "math": 1, "know": -1}, "实质改善"),
    ],
)
def test_comparison_wording_thresholds(delta, subsets, expected):
    assert expected in MODULE.comparison_interpretation(delta, subsets)
