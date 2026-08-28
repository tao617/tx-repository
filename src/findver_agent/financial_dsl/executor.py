"""Deterministic Decimal executor for the reference-only FinDSL AST."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
    localcontext,
)
from typing import Mapping

from .models import (
    ClaimRelation,
    ClaimValueOperand,
    ClaimValueRef,
    ConstantOperand,
    FinancialOperator,
    FinancialProgram,
    NumericCertificate,
    OperandSnapshot,
    RoundingSpec,
    ToleranceSpec,
    ValueOperand,
)


MAX_AST_DEPTH = 4
MAX_AST_NODES = 32
MAX_TOTAL_OPERANDS = 32

_UNKNOWN = {"", "?", "n/a", "na", "none", "unknown", "unspecified"}
_SCALE_FACTORS = {
    "1": Decimal(1),
    "one": Decimal(1),
    "ones": Decimal(1),
    "thousand": Decimal(1000),
    "thousands": Decimal(1000),
    "million": Decimal(1000000),
    "millions": Decimal(1000000),
    "billion": Decimal(1000000000),
    "billions": Decimal(1000000000),
    "trillion": Decimal(1000000000000),
    "trillions": Decimal(1000000000000),
}
_CONSTANTS = {
    "constant:zero": Decimal(0),
    "constant:one": Decimal(1),
    "constant:hundred": Decimal(100),
}
_ROUNDING = {
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
    "half_down": ROUND_HALF_DOWN,
    "down": ROUND_DOWN,
    "up": ROUND_UP,
}
_COMPARISONS = {
    FinancialOperator.EQUALS,
    FinancialOperator.APPROXIMATELY_EQUALS,
    FinancialOperator.GREATER_THAN,
    FinancialOperator.GREATER_THAN_OR_EQUAL,
    FinancialOperator.LESS_THAN,
    FinancialOperator.LESS_THAN_OR_EQUAL,
    FinancialOperator.WITHIN_RANGE,
}
_CROSS_PERIOD = {
    FinancialOperator.SUBTRACT,
    FinancialOperator.ABSOLUTE_DIFFERENCE,
    FinancialOperator.PCT_CHANGE,
    FinancialOperator.BASIS_POINT_CHANGE,
    FinancialOperator.CAGR,
    FinancialOperator.EQUALS,
    FinancialOperator.APPROXIMATELY_EQUALS,
    FinancialOperator.GREATER_THAN,
    FinancialOperator.GREATER_THAN_OR_EQUAL,
    FinancialOperator.LESS_THAN,
    FinancialOperator.LESS_THAN_OR_EQUAL,
}


class FinDSLExecutionError(ValueError):
    """The program is unsafe, incompatible, or arithmetically undefined."""


@dataclass(frozen=True, slots=True)
class ProgramExecution:
    program_sha256: str
    certificate: NumericCertificate


@dataclass(slots=True)
class _Evaluation:
    value: Decimal | bool | str
    numeric_type: str
    currency: str
    unit: str
    scale: str
    period: str
    snapshots: list[OperandSnapshot]
    evidence_refs: list[str]
    diagnostics: list[str]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def financial_program_sha256(
    program: FinancialProgram, claim_relation: ClaimRelation | None
) -> str:
    canonical_program = {
        "schema": "findsl-v1",
        "program": program.model_dump(mode="json"),
        "claim_relation": (
            claim_relation.model_dump(mode="json")
            if claim_relation is not None
            else None
        ),
    }
    return hashlib.sha256(
        _canonical_json(canonical_program).encode("utf-8")
    ).hexdigest()


def financial_program_leaf_references(
    program: FinancialProgram,
) -> tuple[tuple[str, str], ...]:
    """Return ordered typed leaves while independently enforcing AST bounds."""

    leaves: list[tuple[str, str]] = []
    node_count = 0

    def visit(expression, depth: int) -> None:
        nonlocal node_count
        if depth > MAX_AST_DEPTH:
            raise FinDSLExecutionError("FinDSL AST exceeds the maximum depth")
        if isinstance(expression, FinancialProgram):
            node_count += 1
            if node_count > MAX_AST_NODES:
                raise FinDSLExecutionError("FinDSL exceeds the AST node bound")
            for child in expression.args:
                visit(child, depth + 1)
            return
        leaves.append((expression.kind, expression.ref))
        if len(leaves) > MAX_TOTAL_OPERANDS:
            raise FinDSLExecutionError("FinDSL exceeds the total operand bound")

    visit(program, 1)
    references = [reference for _, reference in leaves]
    if len(references) != len(set(references)):
        raise FinDSLExecutionError("a FinDSL operand reference is reused")
    return tuple(leaves)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise FinDSLExecutionError("financial program produced a non-finite result")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-0", "+0"}:
        rendered = "0"
    if len(rendered) > 128:
        raise FinDSLExecutionError("financial program result exceeds Decimal bounds")
    return rendered


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise FinDSLExecutionError("operand is not a valid Decimal string") from error
    if not parsed.is_finite():
        raise FinDSLExecutionError("operand Decimal must be finite")
    return parsed


def _scale_factor(scale: str) -> Decimal:
    factor = _SCALE_FACTORS.get(scale.strip().casefold())
    if factor is None:
        raise FinDSLExecutionError(f"unsupported or unknown scale: {scale}")
    return factor


def _base_value(item: _Evaluation) -> Decimal:
    if isinstance(item.value, (bool, str)):
        raise FinDSLExecutionError(
            "date or boolean values cannot be used as arithmetic operands"
        )
    return item.value * _scale_factor(item.scale)


def _from_base(value: Decimal, scale: str) -> Decimal:
    return value / _scale_factor(scale)


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _period_kind(period: str) -> str | None:
    lowered = period.strip().casefold()
    if lowered in _UNKNOWN:
        return None
    if re.search(r"\bq[1-4]\b|quarter", lowered):
        return "quarter"
    if re.search(r"\b(?:fy\s*)?(?:19|20|21)\d{2}\b|fiscal year|year ended", lowered):
        return "year"
    if re.search(r"\b(?:h1|h2|half[- ]year)\b", lowered):
        return "half_year"
    return "other"


def _require_periods(items: list[_Evaluation], *, allow_cross: bool) -> str:
    periods = [
        item.period
        for item in items
        if item.numeric_type not in {"scalar", "duration", "date", "boolean"}
        and item.evidence_refs
        and item.period.casefold() not in _UNKNOWN
    ]
    period_bearing = [
        item
        for item in items
        if item.numeric_type not in {"scalar", "duration", "date", "boolean"}
        and item.evidence_refs
    ]
    if not periods:
        return "unknown"
    if len(periods) != len(
        period_bearing
    ):
        raise FinDSLExecutionError("period metadata is incomplete")
    unique = list(dict.fromkeys(periods))
    if len(unique) == 1:
        return unique[0]
    if not allow_cross:
        raise FinDSLExecutionError("operator does not allow cross-period operands")
    kinds = {_period_kind(period) for period in unique}
    if None in kinds or len(kinds) != 1:
        raise FinDSLExecutionError("cross-period operand granularities are incompatible")
    return " -> ".join(unique)


def _require_same_dimension(items: list[_Evaluation]) -> None:
    types = {item.numeric_type for item in items}
    if len(types) != 1:
        raise FinDSLExecutionError("operand numeric types are incompatible")
    first = items[0]
    if first.numeric_type == "money":
        currencies = {item.currency.casefold() for item in items}
        if len(currencies) != 1 or currencies & _UNKNOWN:
            raise FinDSLExecutionError("money operands have incompatible currencies")
    units = {_normalized_name(item.unit) for item in items}
    if len(units) != 1 or not next(iter(units)):
        raise FinDSLExecutionError("operand units are incompatible")
    for item in items:
        _scale_factor(item.scale)


def _merge(items: list[_Evaluation]) -> tuple[list[OperandSnapshot], list[str], list[str]]:
    snapshots: list[OperandSnapshot] = []
    evidence: list[str] = []
    diagnostics: list[str] = []
    seen_refs: set[str] = set()
    for item in items:
        for snapshot in item.snapshots:
            if snapshot.ref in seen_refs:
                raise FinDSLExecutionError("a FinDSL operand reference is reused")
            seen_refs.add(snapshot.ref)
            snapshots.append(snapshot)
        evidence.extend(item.evidence_refs)
        diagnostics.extend(item.diagnostics)
    return snapshots, list(dict.fromkeys(evidence)), list(dict.fromkeys(diagnostics))


def _leaf(
    expression: ValueOperand | ClaimValueOperand | ConstantOperand,
    values: Mapping[str, object],
    claims: Mapping[str, ClaimValueRef],
) -> _Evaluation:
    if isinstance(expression, ValueOperand):
        item = values.get(expression.ref)
        if item is None:
            raise FinDSLExecutionError("program references an unknown ValueRef")
        if getattr(item, "ambiguity_flags"):
            raise FinDSLExecutionError("program operand retains unresolved ambiguity")
        numeric_type = str(getattr(item, "numeric_type"))
        normalized = str(getattr(item, "normalized_value"))
        leaf_value: Decimal | bool | str
        if numeric_type == "date":
            leaf_value = normalized
        elif numeric_type == "boolean":
            if normalized not in {"true", "false"}:
                raise FinDSLExecutionError("boolean ValueRef is not canonical")
            leaf_value = normalized == "true"
        else:
            leaf_value = _decimal(normalized)
        result = _Evaluation(
            value=leaf_value,
            numeric_type=numeric_type,
            currency=str(getattr(item, "currency")),
            unit=str(getattr(item, "unit")),
            scale=str(getattr(item, "scale")),
            period=str(getattr(item, "period")),
            snapshots=[],
            evidence_refs=[str(getattr(item, "evidence_ref"))],
            diagnostics=[],
        )
        kind = "value_ref"
    elif isinstance(expression, ClaimValueOperand):
        item = claims.get(expression.ref)
        if item is None:
            raise FinDSLExecutionError("program references an unknown ClaimValueRef")
        if item.ambiguity_flags:
            raise FinDSLExecutionError("claim operand retains unresolved ambiguity")
        if item.numeric_type == "date":
            claim_value: Decimal | bool | str = item.normalized_value
        elif item.numeric_type == "boolean":
            claim_value = item.normalized_value == "true"
        else:
            claim_value = _decimal(item.normalized_value)
        result = _Evaluation(
            value=claim_value,
            numeric_type=item.numeric_type,
            currency=item.currency,
            unit=item.unit,
            scale=item.scale,
            period="unknown",
            snapshots=[],
            evidence_refs=[],
            diagnostics=[],
        )
        kind = "claim_value_ref"
    else:
        constant = _CONSTANTS.get(expression.ref)
        if constant is None:  # pragma: no cover - Literal schema is primary guard
            raise FinDSLExecutionError("constant is not in the Runtime allowlist")
        result = _Evaluation(
            value=constant,
            numeric_type="scalar",
            currency="unknown",
            unit="one",
            scale="one",
            period="unknown",
            snapshots=[],
            evidence_refs=[],
            diagnostics=[],
        )
        kind = "constant_ref"
    result.snapshots.append(
        OperandSnapshot(
            ref=expression.ref,
            kind=kind,
            normalized_value=(
                str(result.value).lower()
                if isinstance(result.value, bool)
                else (
                    result.value
                    if isinstance(result.value, str)
                    else _canonical_decimal(result.value)
                )
            ),
            numeric_type=result.numeric_type,
            currency=result.currency,
            unit=result.unit,
            scale=result.scale,
            period=result.period,
        )
    )
    return result


def _arity(op: FinancialOperator, count: int) -> None:
    exact = {
        FinancialOperator.SUBTRACT: 2,
        FinancialOperator.MULTIPLY: 2,
        FinancialOperator.DIVIDE: 2,
        FinancialOperator.ABSOLUTE_DIFFERENCE: 2,
        FinancialOperator.PCT_CHANGE: 2,
        FinancialOperator.RATIO: 2,
        FinancialOperator.MARGIN: 2,
        FinancialOperator.BASIS_POINT_CHANGE: 2,
        FinancialOperator.CAGR: 3,
        FinancialOperator.PER_SHARE: 2,
        FinancialOperator.SHARE_OF_TOTAL: 2,
        FinancialOperator.EQUALS: 2,
        FinancialOperator.APPROXIMATELY_EQUALS: 2,
        FinancialOperator.GREATER_THAN: 2,
        FinancialOperator.GREATER_THAN_OR_EQUAL: 2,
        FinancialOperator.LESS_THAN: 2,
        FinancialOperator.LESS_THAN_OR_EQUAL: 2,
        FinancialOperator.WITHIN_RANGE: 3,
    }
    minimum = {
        FinancialOperator.ADD: 2,
        FinancialOperator.SUM: 2,
        FinancialOperator.AVERAGE: 1,
        FinancialOperator.MIN: 1,
        FinancialOperator.MAX: 1,
    }
    if op in exact and count != exact[op]:
        raise FinDSLExecutionError(f"operator {op.value} requires {exact[op]} operands")
    if op in minimum and count < minimum[op]:
        raise FinDSLExecutionError(
            f"operator {op.value} requires at least {minimum[op]} operands"
        )


def _apply_rounding(value: Decimal, rounding: RoundingSpec | None) -> Decimal:
    if rounding is None:
        return value
    quantum = Decimal(1).scaleb(-rounding.digits)
    try:
        rounded = value.quantize(quantum, rounding=_ROUNDING[rounding.mode])
    except InvalidOperation as error:
        raise FinDSLExecutionError("result cannot be rounded within Decimal bounds") from error
    if not rounded.is_finite():
        raise FinDSLExecutionError("rounding produced a non-finite result")
    return rounded


def _tolerance_amount(
    tolerance: ToleranceSpec,
    *,
    rhs: Decimal,
    numeric_type: str,
    scale: str,
) -> Decimal:
    value = _decimal(tolerance.value)
    if tolerance.kind == "absolute":
        return value * _scale_factor(scale)
    if tolerance.kind == "relative":
        return abs(rhs) * value
    if tolerance.kind == "percentage_points":
        if numeric_type != "percentage":
            raise FinDSLExecutionError(
                "percentage-point tolerance requires percentage operands"
            )
        return value * _scale_factor(scale)
    if numeric_type != "percentage":
        raise FinDSLExecutionError(
            "basis-point tolerance requires percentage operands"
        )
    return value / Decimal(100) * _scale_factor(scale)


def _comparison(
    op: FinancialOperator | str,
    items: list[_Evaluation],
    tolerance: ToleranceSpec | None,
) -> bool:
    _require_same_dimension(items)
    if items[0].numeric_type in {"date", "boolean"}:
        name = op.value if isinstance(op, FinancialOperator) else op
        if tolerance is not None:
            raise FinDSLExecutionError(
                "date and boolean comparisons do not accept tolerance"
            )
        if items[0].numeric_type == "boolean" and name != "equals":
            raise FinDSLExecutionError("boolean values support only equals")
        lhs_non_numeric = items[0].value
        rhs_non_numeric = items[1].value
        if name == "equals":
            return lhs_non_numeric == rhs_non_numeric
        if name == "greater_than":
            return lhs_non_numeric > rhs_non_numeric  # type: ignore[operator]
        if name == "greater_than_or_equal":
            return lhs_non_numeric >= rhs_non_numeric  # type: ignore[operator]
        if name == "less_than":
            return lhs_non_numeric < rhs_non_numeric  # type: ignore[operator]
        if name == "less_than_or_equal":
            return lhs_non_numeric <= rhs_non_numeric  # type: ignore[operator]
        if name == "within_range" and items[0].numeric_type == "date":
            return rhs_non_numeric <= lhs_non_numeric <= items[2].value  # type: ignore[operator]
        raise FinDSLExecutionError("operator is invalid for date or boolean values")
    lhs = _base_value(items[0])
    rhs = _base_value(items[1])
    name = op.value if isinstance(op, FinancialOperator) else op
    if name == "equals":
        if tolerance is not None:
            raise FinDSLExecutionError("equals does not accept a tolerance")
        return lhs == rhs
    if name == "approximately_equals":
        if tolerance is None:
            raise FinDSLExecutionError(
                "approximately_equals requires an explicit tolerance"
            )
        return abs(lhs - rhs) <= _tolerance_amount(
            tolerance,
            rhs=rhs,
            numeric_type=items[0].numeric_type,
            scale=items[0].scale,
        )
    if tolerance is not None:
        raise FinDSLExecutionError("tolerance is not valid for this comparison")
    if name == "greater_than":
        return lhs > rhs
    if name == "greater_than_or_equal":
        return lhs >= rhs
    if name == "less_than":
        return lhs < rhs
    if name == "less_than_or_equal":
        return lhs <= rhs
    if name == "within_range":
        upper = _base_value(items[2])
        if rhs > upper:
            raise FinDSLExecutionError("within_range lower bound exceeds upper bound")
        return rhs <= lhs <= upper
    raise FinDSLExecutionError("unknown comparison operator")


class _Executor:
    def __init__(
        self,
        values: Mapping[str, object],
        claims: Mapping[str, ClaimValueRef],
    ) -> None:
        self.values = values
        self.claims = claims
        self.nodes = 0
        self.operands = 0

    def evaluate(
        self,
        expression: FinancialProgram | ValueOperand | ClaimValueOperand | ConstantOperand,
        *,
        depth: int = 1,
    ) -> _Evaluation:
        if depth > MAX_AST_DEPTH:
            raise FinDSLExecutionError("FinDSL AST exceeds the maximum depth")
        if not isinstance(expression, FinancialProgram):
            self.operands += 1
            if self.operands > MAX_TOTAL_OPERANDS:
                raise FinDSLExecutionError("FinDSL exceeds the total operand bound")
            return _leaf(expression, self.values, self.claims)

        self.nodes += 1
        if self.nodes > MAX_AST_NODES:
            raise FinDSLExecutionError("FinDSL exceeds the AST node bound")
        items = [self.evaluate(item, depth=depth + 1) for item in expression.args]
        _arity(expression.op, len(items))
        snapshots, evidence, diagnostics = _merge(items)
        op = expression.op
        period = _require_periods(items, allow_cross=op in _CROSS_PERIOD)

        if op in _COMPARISONS:
            if expression.rounding is not None:
                raise FinDSLExecutionError("boolean operators cannot specify rounding")
            result = _comparison(op, items, expression.tolerance)
            return _Evaluation(
                value=result,
                numeric_type="boolean",
                currency="unknown",
                unit="boolean",
                scale="one",
                period=period,
                snapshots=snapshots,
                evidence_refs=evidence,
                diagnostics=diagnostics,
            )
        if expression.tolerance is not None:
            raise FinDSLExecutionError("tolerance is allowed only on comparison nodes")

        if op in {
            FinancialOperator.ADD,
            FinancialOperator.SUM,
            FinancialOperator.SUBTRACT,
            FinancialOperator.AVERAGE,
            FinancialOperator.MIN,
            FinancialOperator.MAX,
            FinancialOperator.ABSOLUTE_DIFFERENCE,
        }:
            _require_same_dimension(items)
            base = [_base_value(item) for item in items]
            if op in {FinancialOperator.ADD, FinancialOperator.SUM}:
                answer = sum(base, Decimal(0))
            elif op is FinancialOperator.SUBTRACT:
                answer = base[0] - base[1]
            elif op is FinancialOperator.AVERAGE:
                answer = sum(base, Decimal(0)) / Decimal(len(base))
            elif op is FinancialOperator.MIN:
                answer = min(base)
            elif op is FinancialOperator.MAX:
                answer = max(base)
            else:
                answer = abs(base[0] - base[1])
            scale = items[0].scale
            value = _from_base(answer, scale)
            result_type, currency, unit = (
                items[0].numeric_type,
                items[0].currency,
                items[0].unit,
            )
        elif op is FinancialOperator.MULTIPLY:
            scalar_indices = [
                index for index, item in enumerate(items) if item.numeric_type == "scalar"
            ]
            if len(scalar_indices) not in {1, 2}:
                raise FinDSLExecutionError(
                    "multiply requires at least one dimensionless scalar"
                )
            if len(scalar_indices) == 2:
                value = items[0].value * items[1].value  # type: ignore[operator]
                result_type, currency, unit, scale = (
                    "scalar",
                    "unknown",
                    "one",
                    "one",
                )
            else:
                scalar_index = scalar_indices[0]
                dimensioned = items[1 - scalar_index]
                scalar = items[scalar_index]
                value = dimensioned.value * scalar.value  # type: ignore[operator]
                result_type, currency, unit, scale = (
                    dimensioned.numeric_type,
                    dimensioned.currency,
                    dimensioned.unit,
                    dimensioned.scale,
                )
        elif op is FinancialOperator.DIVIDE:
            denominator = _base_value(items[1])
            if denominator == 0:
                raise FinDSLExecutionError("division by zero is undefined")
            if items[1].numeric_type == "scalar":
                value = items[0].value / items[1].value  # type: ignore[operator]
                result_type, currency, unit, scale = (
                    items[0].numeric_type,
                    items[0].currency,
                    items[0].unit,
                    items[0].scale,
                )
            else:
                _require_same_dimension(items)
                value = _base_value(items[0]) / denominator
                result_type, currency, unit, scale = (
                    "ratio",
                    "unknown",
                    "ratio",
                    "one",
                )
            if denominator < 0:
                diagnostics.append("negative denominator uses standard signed division")
        elif op in {
            FinancialOperator.PCT_CHANGE,
            FinancialOperator.RATIO,
            FinancialOperator.MARGIN,
            FinancialOperator.BASIS_POINT_CHANGE,
            FinancialOperator.SHARE_OF_TOTAL,
        }:
            _require_same_dimension(items)
            first, second = _base_value(items[0]), _base_value(items[1])
            if second == 0:
                raise FinDSLExecutionError(f"{op.value} denominator cannot be zero")
            if op is FinancialOperator.PCT_CHANGE:
                value = (first - second) / abs(second) * Decimal(100)
                if second < 0:
                    diagnostics.append(
                        "pct_change uses the absolute negative baseline denominator"
                    )
                result_type, unit = "percentage", "percentage"
            elif op is FinancialOperator.RATIO:
                value = first / second
                result_type, unit = "ratio", "ratio"
                if second < 0:
                    diagnostics.append("ratio uses standard signed division")
            elif op is FinancialOperator.BASIS_POINT_CHANGE:
                if items[0].numeric_type not in {"percentage", "basis_points"}:
                    raise FinDSLExecutionError(
                        "basis_point_change requires percentage or basis-point operands"
                    )
                value = (
                    (first - second) * Decimal(100)
                    if items[0].numeric_type == "percentage"
                    else first - second
                )
                result_type, unit = "basis_points", "basis_points"
            else:
                if second < 0:
                    raise FinDSLExecutionError(
                        f"{op.value} requires a positive denominator"
                    )
                value = first / second * Decimal(100)
                result_type, unit = "percentage", "percentage"
            currency, scale = "unknown", "one"
        elif op is FinancialOperator.CAGR:
            _require_same_dimension(items[:2])
            ending, beginning = _base_value(items[0]), _base_value(items[1])
            years = _base_value(items[2])
            if beginning <= 0 or ending <= 0:
                raise FinDSLExecutionError("cagr requires positive beginning and ending values")
            if years <= 0 or items[2].numeric_type not in {"scalar", "duration"}:
                raise FinDSLExecutionError("cagr requires a positive duration operand")
            with localcontext() as context:
                context.prec = 50
                value = ((ending / beginning) ** (Decimal(1) / years) - 1) * 100
            result_type, currency, unit, scale = (
                "percentage",
                "unknown",
                "percentage",
                "one",
            )
        elif op is FinancialOperator.PER_SHARE:
            if items[0].numeric_type != "money" or items[1].numeric_type != "count":
                raise FinDSLExecutionError("per_share requires money then count")
            denominator = _base_value(items[1])
            if denominator <= 0:
                raise FinDSLExecutionError("per_share requires a positive share count")
            value = _base_value(items[0]) / denominator
            result_type, currency, unit, scale = (
                "money",
                items[0].currency,
                f"{items[0].currency}/share",
                "one",
            )
        else:  # pragma: no cover - enum exhaustiveness guard
            raise FinDSLExecutionError(f"unsupported financial operator: {op.value}")

        if isinstance(value, bool):  # pragma: no cover - noncomparison branch guard
            raise FinDSLExecutionError("numeric operator produced a boolean")
        value = _apply_rounding(value, expression.rounding)
        _canonical_decimal(value)
        return _Evaluation(
            value=value,
            numeric_type=result_type,
            currency=currency,
            unit=unit,
            scale=scale,
            period=period,
            snapshots=snapshots,
            evidence_refs=evidence,
            diagnostics=list(dict.fromkeys(diagnostics))[:8],
        )


def execute_financial_program(
    program: FinancialProgram,
    claim_relation: ClaimRelation | None,
    *,
    values: Mapping[str, object],
    claims: Mapping[str, ClaimValueRef],
    program_id: str,
    certificate_id: str,
) -> ProgramExecution:
    """Validate and execute one AST, returning a deterministic full certificate."""

    executor = _Executor(values, claims)
    with localcontext() as context:
        context.prec = 50
        result = executor.evaluate(program)
    if not result.evidence_refs:
        raise FinDSLExecutionError(
            "program requires at least one source-bound ValueRef operand"
        )

    tolerance: ToleranceSpec | None
    if isinstance(result.value, bool):
        if claim_relation is not None:
            raise FinDSLExecutionError(
                "a boolean root program cannot also declare a claim relation"
            )
        relation_name = "program_boolean"
        relation_satisfied = result.value
        tolerance = program.tolerance
        result_text = "true" if result.value else "false"
    else:
        if claim_relation is None:
            raise FinDSLExecutionError(
                "a numeric root program requires an explicit claim relation"
            )
        claim = claims.get(claim_relation.claim_ref)
        if claim is None:
            raise FinDSLExecutionError("claim relation references an unknown ClaimValueRef")
        if claim.ambiguity_flags:
            raise FinDSLExecutionError("claim relation value retains ambiguity")
        claim_item = _Evaluation(
            value=_decimal(claim.normalized_value),
            numeric_type=claim.numeric_type,
            currency=claim.currency,
            unit=claim.unit,
            scale=claim.scale,
            period="unknown",
            snapshots=[],
            evidence_refs=[],
            diagnostics=[],
        )
        relation_satisfied = _comparison(
            claim_relation.op,
            [result, claim_item],
            claim_relation.tolerance,
        )
        relation_name = f"{claim_relation.op}:{claim_relation.claim_ref}"
        tolerance = claim_relation.tolerance
        result_text = _canonical_decimal(result.value)

    program_sha256 = financial_program_sha256(program, claim_relation)
    certificate = NumericCertificate(
        certificate_id=certificate_id,
        program_id=program_id,
        program_sha256=program_sha256,
        operator=program.op,
        operand_refs=[snapshot.ref for snapshot in result.snapshots],
        source_evidence_refs=result.evidence_refs,
        type_checks_passed=True,
        unit_checks_passed=True,
        period_checks_passed=True,
        normalized_operands=result.snapshots,
        result=result_text,
        result_type=result.numeric_type,
        result_currency=result.currency,
        result_unit=result.unit,
        result_scale=result.scale,
        result_period=result.period,
        claim_relation=relation_name,
        relation_satisfied=relation_satisfied,
        rounding=program.rounding,
        tolerance=tolerance,
        diagnostics=result.diagnostics,
    )
    return ProgramExecution(program_sha256=program_sha256, certificate=certificate)


def numeric_certificate_sha256(certificate: NumericCertificate) -> str:
    return hashlib.sha256(
        _canonical_json(certificate.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "FinDSLExecutionError",
    "MAX_AST_DEPTH",
    "MAX_AST_NODES",
    "MAX_TOTAL_OPERANDS",
    "ProgramExecution",
    "execute_financial_program",
    "financial_program_leaf_references",
    "financial_program_sha256",
    "numeric_certificate_sha256",
]
