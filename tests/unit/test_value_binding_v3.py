import ast
import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from findver_agent.findoasis.actions import BindFinancialValueArguments
from findver_agent.findoasis.agent import FinOASISAgent
from findver_agent.findoasis.state import EvidenceLedgerEntry
from findver_agent.findoasis.value_binding import (
    ValueAmbiguityFlag,
    ValueBindingError,
    ValueRef,
    bind_financial_value,
)


def _evidence(
    text,
    *,
    evidence_id="ev-1",
    source="report_paragraph",
    paragraph_id=3,
    table_id=None,
    row_index=None,
    column_index=None,
    **metadata,
):
    return EvidenceLedgerEntry(
        evidence_id=evidence_id,
        source=source,
        paragraph_id=paragraph_id,
        exact_text=text,
        exact_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        table_id=table_id,
        row_index=row_index,
        column_index=column_index,
        **metadata,
    )


def _arguments(raw_value, **updates):
    values = {
        "evidence_ref": "ev-1",
        "raw_value": raw_value,
        "metric": "revenue",
        "entity": "issuer",
        "period": "FY2024",
        "numeric_type": "money",
        "currency": "USD",
        "unit": "USD",
        "scale": "one",
    }
    values.update(updates)
    return BindFinancialValueArguments.model_validate(values)


def test_binds_one_exact_paragraph_occurrence_and_canonicalizes_decimal():
    text = "Revenue was $1,234.500 million in FY2024."
    arguments = _arguments("$1,234.500 million", scale="million")
    before = arguments.model_dump()
    evidence = _evidence(text)

    value = bind_financial_value(
        arguments, evidence, value_id="value-0001"
    )

    assert isinstance(value, ValueRef)
    assert value.normalized_value == "1234.5"
    assert value.source == "report_paragraph"
    assert value.paragraph_id == 3
    assert value.source_span == (
        text.index(arguments.raw_value),
        text.index(arguments.raw_value) + len(arguments.raw_value),
    )
    assert text[slice(*value.source_span)] == value.raw_value
    assert value.table_id is None
    assert value.ambiguity_flags == ()
    assert arguments.model_dump() == before

    with pytest.raises(ValidationError):
        value.normalized_value = "999"


def test_table_binding_preserves_exact_cell_coordinates_without_copying_cell_body():
    evidence = _evidence(
        "12.50%",
        source="table_cell",
        paragraph_id=7,
        table_id="table-2",
        row_index=4,
        column_index=3,
    )
    arguments = _arguments(
        "12.50%",
        numeric_type="percentage",
        currency="unknown",
        unit="percentage",
        scale="one",
        metric="operating margin",
    )

    value = bind_financial_value(
        arguments, evidence, value_id="value-table-1"
    )

    assert value.normalized_value == "12.5"
    assert value.source == "table_cell"
    assert (value.table_id, value.row_index, value.column_index) == (
        "table-2",
        4,
        3,
    )
    assert ValueAmbiguityFlag.CURRENCY_AMBIGUOUS not in value.ambiguity_flags
    assert "exact_text" not in value.model_dump()


def test_agent_fills_unknown_metadata_from_deterministic_table_inference():
    arguments = _arguments(
        "$1,200", currency="unknown", unit="unknown", scale="unknown"
    )
    evidence = _evidence(
        "$1,200",
        source="table_cell",
        table_id="table-2",
        row_index=4,
        column_index=3,
        inferred_unit="USD",
        inferred_scale="millions",
    )

    reconciled = FinOASISAgent._trusted_binding_arguments(arguments, evidence)

    assert reconciled.currency == "USD"
    assert reconciled.unit == "USD"
    assert reconciled.scale == "million"
    assert arguments.currency == "unknown"
    value = bind_financial_value(
        reconciled, evidence, value_id="value-inferred", mandatory=True
    )
    assert value.ambiguity_flags == ()


def test_agent_rejects_model_metadata_that_conflicts_with_table_inference():
    evidence = _evidence(
        "$1,200",
        source="table_cell",
        table_id="table-2",
        row_index=4,
        column_index=3,
        inferred_unit="USD",
        inferred_scale="million",
    )

    with pytest.raises(ValueError, match="currency metadata conflicts"):
        FinOASISAgent._trusted_binding_arguments(
            _arguments("$1,200", currency="EUR", unit="USD", scale="million"),
            evidence,
        )
    with pytest.raises(ValueError, match="scale metadata conflicts"):
        FinOASISAgent._trusted_binding_arguments(
            _arguments("$1,200", scale="thousand"), evidence
        )


@pytest.mark.parametrize(
    ("text", "raw_value", "message"),
    [
        ("Revenue was 100.", "999", "not an exact standalone"),
        ("The values were 10 and 10.", "10", "more than once"),
        ("The value was 312.", "12", "not an exact standalone"),
    ],
)
def test_rejects_invented_repeated_and_non_token_substring_values(
    text, raw_value, message
):
    with pytest.raises(ValueBindingError, match=message):
        bind_financial_value(
            _arguments(raw_value),
            _evidence(text),
            value_id="value-invalid",
        )


def test_rejects_wrong_evidence_reference_and_hash_even_for_matching_text():
    evidence = _evidence("Revenue was 10.")
    with pytest.raises(ValueBindingError, match="evidence_ref"):
        bind_financial_value(
            _arguments("10", evidence_ref="ev-other"),
            evidence,
            value_id="value-invalid",
        )

    bypassed = EvidenceLedgerEntry.model_construct(
        **{
            **evidence.model_dump(),
            "exact_text_sha256": "0" * 64,
        }
    )
    with pytest.raises(ValueBindingError, match="exact-text hash"):
        bind_financial_value(
            _arguments("10"), bypassed, value_id="value-invalid"
        )


@pytest.mark.parametrize("raw_value", ["1 + 2", "1e3", "NaN", "Infinity"])
def test_parser_rejects_expressions_exponents_and_non_finite_tokens(raw_value):
    with pytest.raises(ValueBindingError, match="Decimal literal"):
        bind_financial_value(
            _arguments(raw_value),
            _evidence(f"The reported value was {raw_value}."),
            value_id="value-invalid",
        )


@pytest.mark.parametrize("raw_value", ["-", "—", "N/A", "null", "12,34"])
def test_missing_markers_and_invalid_thousands_are_never_bound_as_zero(raw_value):
    with pytest.raises(ValueBindingError, match="Decimal literal"):
        bind_financial_value(
            _arguments(raw_value),
            _evidence(f"The reported value was {raw_value}."),
            value_id="value-invalid",
        )


def test_decimal_parser_handles_parentheses_sign_and_negative_zero_canonically():
    negative = bind_financial_value(
        _arguments("(1,200.00)"),
        _evidence("The loss was (1,200.00)."),
        value_id="value-negative",
    )
    assert negative.normalized_value == "-1200"

    zero = bind_financial_value(
        _arguments("-0.000"),
        _evidence("The balance was -0.000."),
        value_id="value-zero",
    )
    assert zero.normalized_value == "0"

    with pytest.raises(ValueBindingError, match="explicit sign"):
        bind_financial_value(
            _arguments("(-10)"),
            _evidence("The loss was (-10)."),
            value_id="value-invalid",
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"unit": "unknown"},
        {"period": "unknown"},
    ],
)
def test_mandatory_binding_fails_closed_on_unknown_unit_or_period(updates):
    with pytest.raises(ValueBindingError, match="unit or period ambiguity"):
        bind_financial_value(
            _arguments("10", **updates),
            _evidence("Revenue was 10."),
            value_id="value-mandatory",
        )

    flag = (
        ValueAmbiguityFlag.UNIT_AMBIGUOUS
        if "unit" in updates
        else ValueAmbiguityFlag.PERIOD_AMBIGUOUS
    )
    optional = bind_financial_value(
        _arguments("10", **updates),
        _evidence("Revenue was 10."),
        value_id="value-optional",
        mandatory=False,
        ambiguity_flags=(ValueAmbiguityFlag.OCR_AMBIGUOUS,),
    )
    assert flag in optional.ambiguity_flags
    assert ValueAmbiguityFlag.OCR_AMBIGUOUS in optional.ambiguity_flags


def test_trusted_unit_or_period_ambiguity_blocks_mandatory_binding():
    for flag in (
        ValueAmbiguityFlag.UNIT_AMBIGUOUS,
        ValueAmbiguityFlag.PERIOD_AMBIGUOUS,
    ):
        with pytest.raises(ValueBindingError, match="unit or period ambiguity"):
            bind_financial_value(
                _arguments("10"),
                _evidence("Revenue was 10."),
                value_id="value-ambiguous",
                ambiguity_flags=(flag,),
            )


@pytest.mark.parametrize(
    ("raw_value", "updates", "message"),
    [
        (
            "12%",
            {"numeric_type": "money", "unit": "percentage"},
            "numeric_type percentage",
        ),
        ("$1 million", {"scale": "thousand"}, "scale metadata"),
        ("€10", {"currency": "USD"}, "currency metadata"),
    ],
)
def test_explicit_evidence_markers_cannot_conflict_with_supplied_metadata(
    raw_value, updates, message
):
    with pytest.raises(ValueBindingError, match=message):
        bind_financial_value(
            _arguments(raw_value, **updates),
            _evidence(f"The value was {raw_value}."),
            value_id="value-conflict",
        )


def test_duration_and_count_literals_remain_decimal_bound():
    duration = bind_financial_value(
        _arguments(
            "3 years",
            numeric_type="duration",
            currency="unknown",
            unit="years",
            metric="remaining term",
        ),
        _evidence("The remaining term was 3 years."),
        value_id="value-duration",
    )
    assert duration.normalized_value == "3"

    count = bind_financial_value(
        _arguments(
            "1,200 shares",
            numeric_type="count",
            currency="unknown",
            unit="shares",
            metric="share count",
        ),
        _evidence("The issuer reported 1,200 shares."),
        value_id="value-count",
    )
    assert count.normalized_value == "1200"


@pytest.mark.parametrize(
    ("raw_value", "numeric_type", "unit", "normalized"),
    [
        ("2024-12-31", "date", "date", "2024-12-31"),
        ("YES", "boolean", "boolean", "true"),
        ("false", "boolean", "boolean", "false"),
    ],
)
def test_date_and_boolean_values_bind_exactly_without_entering_decimal_arithmetic(
    raw_value, numeric_type, unit, normalized
):
    bound = bind_financial_value(
        _arguments(
            raw_value,
            numeric_type=numeric_type,
            currency="unknown",
            unit=unit,
            scale="one",
        ),
        _evidence(f"The exact value was {raw_value} in FY2024."),
        value_id=f"value-{numeric_type}",
    )
    assert bound.normalized_value == normalized
    assert bound.numeric_type == numeric_type


@pytest.mark.parametrize(
    ("raw_value", "numeric_type", "message"),
    [
        ("2024-99-99", "date", "valid ISO"),
        ("maybe", "boolean", "true, false, yes, or no"),
    ],
)
def test_invalid_date_and_boolean_literals_fail_closed(raw_value, numeric_type, message):
    with pytest.raises(ValueBindingError, match=message):
        bind_financial_value(
            _arguments(
                raw_value,
                numeric_type=numeric_type,
                currency="unknown",
                unit=numeric_type,
                scale="one",
            ),
            _evidence(f"The exact value was {raw_value} in FY2024."),
            value_id="value-invalid",
        )


def test_binding_module_has_no_float_dynamic_execution_or_path_capability():
    path = Path("src/findver_agent/findoasis/value_binding.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert not {"eval", "exec", "float", "compile", "__import__"} & called_names
    assert not {"importlib", "pathlib", "os", "subprocess"} & imported_roots
