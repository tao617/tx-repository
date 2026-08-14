import pytest

from findver_agent.skills.base import SkillError
from findver_agent.skills.calculator import CalculatorSkill


def test_calculator_handles_financial_percentage_math():
    result = CalculatorSkill().execute(expression="round((128.4 - 114.7) / 114.7 * 100, 4)")
    assert result["result"] == 11.9442


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "(1).__class__",
        "open('/private/gold.jsonl')",
        "2 ** 1000",
        "1 % 2",
    ],
)
def test_calculator_rejects_execution_and_unbounded_operations(expression):
    with pytest.raises(SkillError):
        CalculatorSkill().execute(expression=expression)

