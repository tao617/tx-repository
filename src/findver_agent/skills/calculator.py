"""AST-allowlisted arithmetic calculator."""

from __future__ import annotations

import ast
import math
from collections.abc import Callable

from findver_agent.skills.base import SkillError


Number = int | float
MAX_ABS_VALUE = 1e100


class CalculatorSkill:
    name = "calculator"

    _binary: dict[type[ast.operator], Callable[[Number, Number], Number]] = {
        ast.Add: lambda left, right: left + right,
        ast.Sub: lambda left, right: left - right,
        ast.Mult: lambda left, right: left * right,
        ast.Div: lambda left, right: left / right,
        ast.Pow: lambda left, right: left**right,
    }
    _unary: dict[type[ast.unaryop], Callable[[Number], Number]] = {
        ast.UAdd: lambda value: value,
        ast.USub: lambda value: -value,
    }

    def execute(self, *, expression: str) -> dict[str, object]:
        if not isinstance(expression, str) or not expression.strip() or len(expression) > 256:
            raise SkillError("expression must contain 1 to 256 characters")
        try:
            tree = ast.parse(expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 64:
                raise SkillError("expression is too complex")
            result = self._evaluate(tree.body)
            self._check_number(result)
        except SkillError:
            raise
        except (SyntaxError, ArithmeticError, OverflowError, ValueError, TypeError) as error:
            raise SkillError(f"invalid calculation: {error}") from error
        return {"expression": expression, "result": result}

    def _evaluate(self, node: ast.AST) -> Number:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise SkillError("only numeric constants are allowed")
            self._check_number(node.value)
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary:
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise SkillError("power exponent exceeds the safety bound")
            result = self._binary[type(node.op)](left, right)
            self._check_number(result)
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._unary:
            result = self._unary[type(node.op)](self._evaluate(node.operand))
            self._check_number(result)
            return result
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            arguments = [self._evaluate(argument) for argument in node.args]
            result = self._call(node.func.id, arguments)
            self._check_number(result)
            return result
        raise SkillError(f"operation is not allowed: {type(node).__name__}")

    @staticmethod
    def _call(name: str, arguments: list[Number]) -> Number:
        if name == "abs" and len(arguments) == 1:
            return abs(arguments[0])
        if name == "sqrt" and len(arguments) == 1:
            return math.sqrt(arguments[0])
        if name in {"min", "max"} and arguments:
            return min(arguments) if name == "min" else max(arguments)
        if name == "round" and 1 <= len(arguments) <= 2:
            if len(arguments) == 2 and (not isinstance(arguments[1], int) or abs(arguments[1]) > 12):
                raise SkillError("round precision must be an integer between -12 and 12")
            return round(*arguments)
        raise SkillError(f"function is not allowed: {name}")

    @staticmethod
    def _check_number(value: Number) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SkillError("calculation did not produce a number")
        if isinstance(value, float) and not math.isfinite(value):
            raise SkillError("calculation result must be finite")
        if abs(value) > MAX_ABS_VALUE:
            raise SkillError("calculation result exceeds the safety bound")

