import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from findver_agent.financial_dsl.claim_parser import parse_claim_values
from findver_agent.financial_dsl.executor import (
    FinDSLExecutionError,
    execute_financial_program,
    numeric_certificate_sha256,
)
from findver_agent.financial_dsl.models import (
    ClaimRelation,
    ClaimValueRef,
    FinancialProgram,
)
from findver_agent.findoasis.actions import ExecuteFinancialProgramArguments


def value(
    reference,
    number,
    *,
    numeric_type="money",
    currency="USD",
    unit="USD",
    scale="one",
    period="FY2024",
    ambiguity_flags=(),
):
    return SimpleNamespace(
        value_id=reference,
        evidence_ref=f"evidence:{reference}",
        normalized_value=number,
        numeric_type=numeric_type,
        currency=currency,
        unit=unit,
        scale=scale,
        period=period,
        ambiguity_flags=list(ambiguity_flags),
    )


def claim(
    number,
    *,
    reference="claim-value-0001",
    numeric_type="money",
    currency="USD",
    unit="USD",
    scale="one",
):
    return ClaimValueRef(
        claim_value_id=reference,
        raw_value=number,
        normalized_value=number,
        numeric_type=numeric_type,
        currency=currency,
        unit=unit,
        scale=scale,
        relation="equals",
        source_span_start=0,
        source_span_end=len(number),
    )


def leaf(reference):
    return {"kind": "value_ref", "ref": reference}


def program(op, *references, rounding=None, tolerance=None):
    payload = {"op": op, "args": [leaf(reference) for reference in references]}
    if rounding is not None:
        payload["rounding"] = rounding
    if tolerance is not None:
        payload["tolerance"] = tolerance
    return FinancialProgram.model_validate(payload)


def execute(
    root,
    values,
    *,
    expected="0",
    claim_type="money",
    claim_currency="USD",
    claim_unit="USD",
    claim_scale="one",
    relation="equals",
    tolerance=None,
):
    expected_claim = claim(
        expected,
        numeric_type=claim_type,
        currency=claim_currency,
        unit=claim_unit,
        scale=claim_scale,
    )
    relation_payload = {"op": relation, "claim_ref": expected_claim.claim_value_id}
    if tolerance is not None:
        relation_payload["tolerance"] = tolerance
    return execute_financial_program(
        root,
        ClaimRelation.model_validate(relation_payload),
        values=values,
        claims={expected_claim.claim_value_id: expected_claim},
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )


@pytest.mark.parametrize(
    ("op", "numbers", "expected"),
    [
        ("add", ("10", "5"), "15"),
        ("subtract", ("10", "5"), "5"),
        ("multiply", ("10", "5"), "50"),
        ("divide", ("10", "5"), "2"),
    ],
)
def test_basic_decimal_arithmetic(op, numbers, expected):
    values = {
        "value-0001": value(
            "value-0001",
            numbers[0],
            numeric_type="scalar" if op in {"multiply", "divide"} else "money",
            currency="unknown" if op in {"multiply", "divide"} else "USD",
            unit="one" if op in {"multiply", "divide"} else "USD",
        ),
        "value-0002": value(
            "value-0002",
            numbers[1],
            numeric_type="scalar" if op in {"multiply", "divide"} else "money",
            currency="unknown" if op in {"multiply", "divide"} else "USD",
            unit="one" if op in {"multiply", "divide"} else "USD",
        ),
    }
    result_type = "scalar" if op in {"multiply", "divide"} else "money"
    execution = execute(
        program(op, *values),
        values,
        expected=expected,
        claim_type=result_type,
        claim_currency="unknown" if result_type == "scalar" else "USD",
        claim_unit="one" if result_type == "scalar" else "USD",
    )

    assert execution.certificate.result == expected
    assert execution.certificate.relation_satisfied is True
    assert execution.certificate.type_checks_passed is True


@pytest.mark.parametrize(
    ("op", "first", "second", "expected", "result_type", "unit"),
    [
        ("pct_change", "120", "100", "20", "percentage", "percentage"),
        ("margin", "20", "100", "20", "percentage", "percentage"),
        (
            "basis_point_change",
            "12.5",
            "10",
            "250",
            "basis_points",
            "basis_points",
        ),
    ],
)
def test_financial_percentage_operators(op, first, second, expected, result_type, unit):
    source_type = "percentage" if op == "basis_point_change" else "money"
    source_unit = "percentage" if source_type == "percentage" else "USD"
    source_currency = "unknown" if source_type == "percentage" else "USD"
    values = {
        "value-0001": value(
            "value-0001",
            first,
            numeric_type=source_type,
            unit=source_unit,
            currency=source_currency,
            period="FY2024",
        ),
        "value-0002": value(
            "value-0002",
            second,
            numeric_type=source_type,
            unit=source_unit,
            currency=source_currency,
            period="FY2023" if op != "margin" else "FY2024",
        ),
    }

    execution = execute(
        program(op, *values),
        values,
        expected=expected,
        claim_type=result_type,
        claim_currency="unknown",
        claim_unit=unit,
    )

    assert execution.certificate.result == expected
    assert execution.certificate.result_type == result_type


def test_cagr_and_rounding_are_explicit_and_deterministic():
    values = {
        "value-0001": value("value-0001", "121", period="FY2024"),
        "value-0002": value("value-0002", "100", period="FY2022"),
        "value-0003": value(
            "value-0003",
            "2",
            numeric_type="duration",
            currency="unknown",
            unit="year",
            period="unknown",
        ),
    }
    root = program(
        "cagr",
        *values,
        rounding={"digits": 2, "mode": "half_up"},
    )

    first = execute(
        root,
        values,
        expected="10",
        claim_type="percentage",
        claim_currency="unknown",
        claim_unit="percentage",
    )
    second = execute(
        root,
        values,
        expected="10",
        claim_type="percentage",
        claim_currency="unknown",
        claim_unit="percentage",
    )

    assert first.certificate.result == "10"
    assert first.program_sha256 == second.program_sha256
    assert numeric_certificate_sha256(first.certificate) == numeric_certificate_sha256(
        second.certificate
    )


def test_cagr_converts_twenty_four_months_to_two_years():
    common = {
        "value-0001": value("value-0001", "121", period="FY2024"),
        "value-0002": value("value-0002", "100", period="FY2022"),
    }
    years = {
        **common,
        "value-0003": value(
            "value-0003",
            "2",
            numeric_type="duration",
            currency="unknown",
            unit="year",
            period="unknown",
        ),
    }
    months = {
        **common,
        "value-0003": value(
            "value-0003",
            "24",
            numeric_type="duration",
            currency="unknown",
            unit="months",
            period="unknown",
        ),
    }
    root = program(
        "cagr",
        *years,
        rounding={"digits": 8, "mode": "half_even"},
    )

    by_year = execute(
        root,
        years,
        expected="10",
        claim_type="percentage",
        claim_currency="unknown",
        claim_unit="percentage",
    )
    by_month = execute(
        root,
        months,
        expected="10",
        claim_type="percentage",
        claim_currency="unknown",
        claim_unit="percentage",
    )

    assert by_year.certificate.result == "10"
    assert by_month.certificate.result == by_year.certificate.result


def test_scaled_scalar_operand_is_rejected_before_operator_execution():
    values = {
        "value-0001": value(
            "value-0001",
            "10",
            numeric_type="scalar",
            currency="unknown",
            unit="one",
            scale="million",
        ),
        "value-0002": value(
            "value-0002",
            "2",
            numeric_type="scalar",
            currency="unknown",
            unit="one",
        ),
    }

    with pytest.raises(FinDSLExecutionError, match="scalar operands require scale one"):
        execute(
            program("multiply", *values),
            values,
            expected="20",
            claim_type="scalar",
            claim_currency="unknown",
            claim_unit="one",
        )


@pytest.mark.parametrize(
    ("op", "numbers", "expected"),
    [
        ("sum", ("10", "20", "30"), "60"),
        ("average", ("10", "20", "30"), "20"),
        ("min", ("10", "20", "30"), "10"),
        ("max", ("10", "20", "30"), "30"),
        ("absolute_difference", ("10", "25"), "15"),
    ],
)
def test_aggregate_and_difference_operators(op, numbers, expected):
    values = {
        f"value-{index:04d}": value(
            f"value-{index:04d}",
            number,
            period="FY2024" if op != "absolute_difference" or index == 1 else "FY2023",
        )
        for index, number in enumerate(numbers, start=1)
    }
    execution = execute(program(op, *values), values, expected=expected)
    assert execution.certificate.result == expected


def test_ratio_per_share_and_share_of_total_have_explicit_result_units():
    money = {
        "value-0001": value("value-0001", "25"),
        "value-0002": value("value-0002", "100"),
    }
    ratio_result = execute(
        program("ratio", *money),
        money,
        expected="0.25",
        claim_type="ratio",
        claim_currency="unknown",
        claim_unit="ratio",
    )
    share_result = execute(
        program("share_of_total", *money),
        money,
        expected="25",
        claim_type="percentage",
        claim_currency="unknown",
        claim_unit="percentage",
    )
    per_share_values = {
        "value-0001": value("value-0001", "100"),
        "value-0002": value(
            "value-0002",
            "10",
            numeric_type="count",
            currency="unknown",
            unit="shares",
        ),
    }
    per_share_result = execute(
        program("per_share", *per_share_values),
        per_share_values,
        expected="10",
        claim_type="money",
        claim_currency="USD",
        claim_unit="USD/share",
    )

    assert ratio_result.certificate.result_unit == "ratio"
    assert share_result.certificate.result_unit == "percentage"
    assert per_share_result.certificate.result_unit == "USD/share"


def test_addition_converts_compatible_scales_without_using_float():
    values = {
        "value-0001": value("value-0001", "1", scale="million"),
        "value-0002": value("value-0002", "500", scale="thousand"),
    }
    execution = execute(
        program("add", *values),
        values,
        expected="1.5",
        claim_scale="million",
    )
    assert execution.certificate.result == "1.5"
    assert execution.certificate.result_scale == "million"


@pytest.mark.parametrize(
    ("op", "lhs", "rhs", "outcome"),
    [
        ("equals", "10", "10", True),
        ("greater_than", "11", "10", True),
        ("greater_than_or_equal", "10", "10", True),
        ("less_than", "9", "10", True),
        ("less_than_or_equal", "10", "10", True),
        ("greater_than", "9", "10", False),
    ],
)
def test_boolean_comparison_operators(op, lhs, rhs, outcome):
    values = {
        "value-0001": value("value-0001", lhs, period="FY2024"),
        "value-0002": value("value-0002", rhs, period="FY2023"),
    }
    execution = execute_financial_program(
        program(op, *values),
        None,
        values=values,
        claims={},
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )
    assert execution.certificate.result == str(outcome).lower()
    assert execution.certificate.relation_satisfied is outcome


def test_approximately_equals_and_within_range_use_explicit_semantics():
    approximate_values = {
        "value-0001": value("value-0001", "10.04"),
        "value-0002": value("value-0002", "10"),
    }
    approximate = execute_financial_program(
        program(
            "approximately_equals",
            *approximate_values,
            tolerance={"kind": "absolute", "value": "0.05"},
        ),
        None,
        values=approximate_values,
        claims={},
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )
    range_values = {
        "value-0001": value("value-0001", "10"),
        "value-0002": value("value-0002", "9"),
        "value-0003": value("value-0003", "11"),
    }
    within = execute_financial_program(
        program("within_range", *range_values),
        None,
        values=range_values,
        claims={},
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )
    assert approximate.certificate.relation_satisfied is True
    assert within.certificate.relation_satisfied is True


def test_date_and_boolean_types_support_only_type_safe_comparisons():
    date_values = {
        "value-0001": value(
            "value-0001",
            "2024-12-31",
            numeric_type="date",
            currency="unknown",
            unit="date",
            period="unknown",
        ),
        "value-0002": value(
            "value-0002",
            "2023-12-31",
            numeric_type="date",
            currency="unknown",
            unit="date",
            period="unknown",
        ),
    }
    dates = execute_financial_program(
        program("greater_than", *date_values),
        None,
        values=date_values,
        claims={},
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )
    boolean_values = {
        "value-0001": value(
            "value-0001",
            "true",
            numeric_type="boolean",
            currency="unknown",
            unit="boolean",
            period="unknown",
        ),
        "value-0002": value(
            "value-0002",
            "true",
            numeric_type="boolean",
            currency="unknown",
            unit="boolean",
            period="unknown",
        ),
    }
    booleans = execute_financial_program(
        program("equals", *boolean_values),
        None,
        values=boolean_values,
        claims={},
        program_id="program-0001",
        certificate_id="numeric-certificate-0001",
    )

    assert dates.certificate.relation_satisfied is True
    assert booleans.certificate.relation_satisfied is True
    with pytest.raises(FinDSLExecutionError, match="only equals"):
        execute_financial_program(
            program("greater_than", *boolean_values),
            None,
            values=boolean_values,
            claims={},
            program_id="program-0001",
            certificate_id="numeric-certificate-0001",
        )
    with pytest.raises(FinDSLExecutionError, match="arithmetic operands"):
        execute(
            program("add", *date_values),
            date_values,
            expected="1",
        )


def test_nested_ast_can_use_only_allowlisted_constant_references():
    values = {
        "value-0001": value("value-0001", "10"),
        "value-0002": value("value-0002", "5"),
    }
    root = FinancialProgram.model_validate(
        {
            "op": "multiply",
            "args": [
                {
                    "op": "add",
                    "args": [leaf("value-0001"), leaf("value-0002")],
                },
                {"kind": "constant_ref", "ref": "constant:hundred"},
            ],
        }
    )
    execution = execute(root, values, expected="1500")
    assert execution.certificate.result == "1500"
    assert execution.certificate.operand_refs == [
        "value-0001",
        "value-0002",
        "constant:hundred",
    ]


def test_negative_pct_change_uses_documented_absolute_baseline_convention():
    values = {
        "value-0001": value("value-0001", "-80", period="FY2024"),
        "value-0002": value("value-0002", "-100", period="FY2023"),
    }
    execution = execute(
        program("pct_change", *values),
        values,
        expected="20",
        claim_type="percentage",
        claim_currency="unknown",
        claim_unit="percentage",
    )
    assert "absolute negative baseline" in execution.certificate.diagnostics[0]


def test_negative_denominator_policies_are_operator_specific():
    values = {
        "value-0001": value("value-0001", "20"),
        "value-0002": value("value-0002", "-100"),
    }
    ratio_result = execute(
        program("ratio", *values),
        values,
        expected="-0.2",
        claim_type="ratio",
        claim_currency="unknown",
        claim_unit="ratio",
    )
    assert "signed division" in ratio_result.certificate.diagnostics[0]
    with pytest.raises(FinDSLExecutionError, match="positive denominator"):
        execute(
            program("margin", *values),
            values,
            expected="-20",
            claim_type="percentage",
            claim_currency="unknown",
            claim_unit="percentage",
        )


@pytest.mark.parametrize("op", ["divide", "pct_change", "margin", "ratio"])
def test_zero_denominators_fail_closed(op):
    values = {
        "value-0001": value("value-0001", "10"),
        "value-0002": value("value-0002", "0"),
    }
    with pytest.raises(FinDSLExecutionError, match="zero"):
        execute(program(op, *values), values, expected="0")


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"numeric_type": "percentage", "currency": "unknown", "unit": "percentage"}, "types"),
        ({"currency": "EUR", "unit": "EUR"}, "currencies"),
        ({"unit": "shares"}, "units"),
        ({"period": "Q4 2024"}, "cross-period"),
    ],
)
def test_addition_rejects_type_currency_unit_and_period_mismatch(updates, message):
    second_metadata = {"period": "FY2024", **updates}
    values = {
        "value-0001": value("value-0001", "10", period="FY2024"),
        "value-0002": value("value-0002", "5", **second_metadata),
    }
    with pytest.raises(FinDSLExecutionError, match=message):
        execute(program("add", *values), values, expected="15")


def test_cross_period_operator_rejects_year_to_quarter_comparison():
    values = {
        "value-0001": value("value-0001", "120", period="FY2024"),
        "value-0002": value("value-0002", "100", period="Q4 2023"),
    }
    with pytest.raises(FinDSLExecutionError, match="granularities"):
        execute(program("pct_change", *values), values, expected="20")


def test_action_schema_rejects_raw_literal_unknown_operator_and_too_many_operands():
    with pytest.raises(ValidationError):
        ExecuteFinancialProgramArguments.model_validate(
            {"program": {"op": "add", "args": [{"kind": "literal", "value": "1"}]}}
        )
    with pytest.raises(ValidationError):
        ExecuteFinancialProgramArguments.model_validate(
            {"program": {"op": "system", "args": [leaf("value-0001")]}}
        )
    with pytest.raises(ValidationError):
        ExecuteFinancialProgramArguments.model_validate(
            {
                "program": {
                    "op": "sum",
                    "args": [leaf(f"value-{index:04d}") for index in range(33)],
                }
            }
        )


def test_claim_and_constant_only_program_is_rejected_as_source_less():
    claim_value = claim(
        "10",
        numeric_type="scalar",
        currency="unknown",
        unit="one",
    )
    root = FinancialProgram.model_validate(
        {
            "op": "add",
            "args": [
                {"kind": "claim_value_ref", "ref": claim_value.claim_value_id},
                {"kind": "constant_ref", "ref": "constant:one"},
            ],
        }
    )
    with pytest.raises(FinDSLExecutionError, match="source-bound"):
        execute_financial_program(
            root,
            ClaimRelation(op="equals", claim_ref=claim_value.claim_value_id),
            values={},
            claims={claim_value.claim_value_id: claim_value},
            program_id="program-0001",
            certificate_id="numeric-certificate-0001",
        )


def test_executor_rejects_excessive_ast_depth_and_result_size():
    nested = FinancialProgram.model_validate(
        {
            "op": "multiply",
            "args": [
                leaf("value-0001"),
                {
                    "op": "multiply",
                    "args": [
                        leaf("value-0002"),
                        {
                            "op": "multiply",
                            "args": [
                                leaf("value-0003"),
                                {
                                    "op": "multiply",
                                    "args": [
                                        leaf("value-0004"),
                                        {
                                            "op": "multiply",
                                            "args": [
                                                leaf("value-0005"),
                                                leaf("value-0006"),
                                            ],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
    )
    scalar_values = {
        f"value-{index:04d}": value(
            f"value-{index:04d}",
            "2",
            numeric_type="scalar",
            currency="unknown",
            unit="one",
        )
        for index in range(1, 7)
    }
    with pytest.raises(FinDSLExecutionError, match="maximum depth"):
        execute(nested, scalar_values, expected="64", claim_type="scalar", claim_currency="unknown", claim_unit="one")

    huge_values = {
        "value-0001": value(
            "value-0001",
            "9" * 120,
            numeric_type="scalar",
            currency="unknown",
            unit="one",
        ),
        "value-0002": value(
            "value-0002",
            "9" * 120,
            numeric_type="scalar",
            currency="unknown",
            unit="one",
        ),
    }
    with pytest.raises(FinDSLExecutionError, match="exceeds Decimal bounds"):
        execute(
            program("multiply", *huge_values),
            huge_values,
            expected="1",
            claim_type="scalar",
            claim_currency="unknown",
            claim_unit="one",
        )


def test_claim_parser_preserves_exact_spans_types_scales_and_relations():
    statement = (
        "Revenue grew by approximately 12.5% from $1.2 million in 2023, "
        "and leverage moved 125 bps."
    )
    values = parse_claim_values(statement)

    assert [item.raw_value for item in values] == ["12.5%", "$1.2 million", "125 bps"]
    assert [item.numeric_type for item in values] == [
        "percentage",
        "money",
        "basis_points",
    ]
    assert values[0].relation == "approximately_equals"
    assert values[1].scale == "million"
    assert all(
        statement[item.source_span_start : item.source_span_end] == item.raw_value
        for item in values
    )

    signed = parse_claim_values("Loss was (1,200) and the change was -12.5%.")
    assert [item.normalized_value for item in signed] == ["-1200", "-12.5"]


def test_financial_dsl_has_no_dynamic_execution_network_or_float_capability():
    paths = [
        Path("src/findver_agent/financial_dsl/models.py"),
        Path("src/findver_agent/financial_dsl/claim_parser.py"),
        Path("src/findver_agent/financial_dsl/executor.py"),
    ]
    called_names = set()
    imported_roots = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called_names.update(
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
        imported_roots.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        )

    assert not {"eval", "exec", "float", "compile", "__import__"} & called_names
    assert not {"socket", "requests", "urllib", "subprocess", "pathlib", "os"} & imported_roots
