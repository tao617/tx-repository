"""Pure evidence-bound financial value creation for FinOASIS protocol v3."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .actions import BindFinancialValueArguments
from .contracts import ReferenceId, SHA256_PATTERN, ShortText
from .state import DECIMAL_PATTERN, EvidenceLedgerEntry


class ValueBindingError(ValueError):
    """The requested value cannot be bound exactly and safely to evidence."""


class ValueAmbiguityFlag(str, Enum):
    CURRENCY_AMBIGUOUS = "currency_ambiguous"
    UNIT_AMBIGUOUS = "unit_ambiguous"
    SCALE_AMBIGUOUS = "scale_ambiguous"
    PERIOD_AMBIGUOUS = "period_ambiguous"
    ENTITY_AMBIGUOUS = "entity_ambiguous"
    METRIC_AMBIGUOUS = "metric_ambiguous"
    TABLE_HEADER_AMBIGUOUS = "table_header_ambiguous"
    OCR_AMBIGUOUS = "ocr_ambiguous"


class ValueRef(BaseModel):
    """One immutable Decimal value bound to an exact evidence occurrence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value_id: ReferenceId
    evidence_ref: ReferenceId
    evidence_text_sha256: str = Field(pattern=SHA256_PATTERN)
    source: Literal["report_paragraph", "table_cell"]
    paragraph_id: int = Field(ge=0)
    source_span_start: int = Field(ge=0)
    source_span_end: int = Field(gt=0)
    table_id: ReferenceId | None = None
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)
    raw_value: str = Field(min_length=1, max_length=128)
    normalized_value: str = Field(pattern=DECIMAL_PATTERN, max_length=128)
    numeric_type: Literal[
        "money",
        "percentage",
        "basis_points",
        "count",
        "ratio",
        "scalar",
        "duration",
        "date",
        "boolean",
    ]
    currency: ShortText
    unit: ShortText
    scale: ShortText
    period: ShortText
    entity: ShortText
    metric: ShortText
    mandatory: bool
    ambiguity_flags: tuple[ValueAmbiguityFlag, ...] = Field(
        default=(), max_length=8
    )

    @field_validator("ambiguity_flags")
    @classmethod
    def ambiguity_flags_are_unique(
        cls, value: tuple[ValueAmbiguityFlag, ...]
    ) -> tuple[ValueAmbiguityFlag, ...]:
        if len(value) != len(set(value)):
            raise ValueError("ambiguity_flags must be unique")
        return value

    @model_validator(mode="after")
    def source_coordinates_and_span_are_consistent(self) -> "ValueRef":
        if self.source_span_end - self.source_span_start != len(self.raw_value):
            raise ValueError("source span must cover raw_value exactly")
        coordinates = (self.table_id, self.row_index, self.column_index)
        if self.source == "table_cell":
            if not all(item is not None for item in coordinates):
                raise ValueError("table_cell ValueRef requires table coordinates")
        elif any(item is not None for item in coordinates):
            raise ValueError("paragraph ValueRef cannot contain table coordinates")
        if self.mandatory and {
            ValueAmbiguityFlag.UNIT_AMBIGUOUS,
            ValueAmbiguityFlag.PERIOD_AMBIGUOUS,
        }.intersection(self.ambiguity_flags):
            raise ValueError(
                "mandatory ValueRef cannot retain unit or period ambiguity"
            )
        return self

    @property
    def source_span(self) -> tuple[int, int]:
        return (self.source_span_start, self.source_span_end)


_NUMBER_RE = re.compile(
    r"""
    ^\s*
    (?P<open>\()?\s*
    (?P<sign>[+-])?\s*
    (?P<prefix_currency>
        US\$|C\$|A\$|HK\$|S\$|NZ\$|[$€£¥]|
        USD|EUR|GBP|CNY|JPY|CAD|AUD|HKD
    )?
    \s*
    (?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)
    \s*
    (?P<scale>thousands?|millions?|billions?|trillions?|k|m|mn|bn|b|tn)?
    \s*
    (?P<unit>
        %|percent(?:age)?|basis\s+points?|bps?|years?|months?|days?|
        shares?|employees?|units?
    )?
    \s*
    (?P<suffix_currency>USD|EUR|GBP|CNY|JPY|CAD|AUD|HKD)?
    \s*(?P<close>\))?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_UNKNOWN = {"", "?", "n/a", "na", "none", "unknown", "unspecified"}
_HARD_NUMERIC_BOUNDARY = set("_+-−$€£¥%()")

_SCALE_ALIASES = {
    "1": "one",
    "one": "one",
    "ones": "one",
    "unit": "one",
    "units": "one",
    "k": "thousand",
    "thousand": "thousand",
    "thousands": "thousand",
    "1000": "thousand",
    "1e3": "thousand",
    "m": "million",
    "mn": "million",
    "million": "million",
    "millions": "million",
    "1000000": "million",
    "1e6": "million",
    "b": "billion",
    "bn": "billion",
    "billion": "billion",
    "billions": "billion",
    "1000000000": "billion",
    "1e9": "billion",
    "tn": "trillion",
    "trillion": "trillion",
    "trillions": "trillion",
    "1000000000000": "trillion",
    "1e12": "trillion",
}

_CURRENCY_COMPATIBILITY = {
    "us$": {"usd"},
    "c$": {"cad"},
    "a$": {"aud"},
    "hk$": {"hkd"},
    "s$": {"sgd"},
    "nz$": {"nzd"},
    "€": {"eur"},
    "£": {"gbp"},
    "usd": {"usd"},
    "eur": {"eur"},
    "gbp": {"gbp"},
    "cny": {"cny", "rmb"},
    "jpy": {"jpy"},
    "cad": {"cad"},
    "aud": {"aud"},
    "hkd": {"hkd"},
}

_UNIT_FAMILIES = {
    "%": "percentage",
    "percent": "percentage",
    "percentage": "percentage",
    "basispoint": "basis_points",
    "basispoints": "basis_points",
    "bp": "basis_points",
    "bps": "basis_points",
    "year": "year",
    "years": "year",
    "month": "month",
    "months": "month",
    "day": "day",
    "days": "day",
    "share": "share",
    "shares": "share",
    "employee": "employee",
    "employees": "employee",
    "unit": "unit",
    "units": "unit",
}


def _metadata_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _is_unknown(value: str) -> bool:
    return value.strip().casefold() in _UNKNOWN


def _has_numeric_boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    before_invalid = before.isalnum() or before in _HARD_NUMERIC_BOUNDARY
    after_invalid = after.isalnum() or after in _HARD_NUMERIC_BOUNDARY
    if before in {".", ","}:
        before_invalid = start < 2 or text[start - 2].isdigit()
    if after in {".", ","} and end + 1 < len(text):
        after_invalid = text[end + 1].isdigit()
    return not before_invalid and not after_invalid


def _exact_unique_span(text: str, raw_value: str) -> tuple[int, int]:
    starts: list[int] = []
    offset = 0
    while True:
        start = text.find(raw_value, offset)
        if start < 0:
            break
        end = start + len(raw_value)
        if _has_numeric_boundary(text, start, end):
            starts.append(start)
        offset = start + 1
    if not starts:
        raise ValueBindingError(
            "raw_value is not an exact standalone occurrence in ledgered evidence"
        )
    if len(starts) != 1:
        raise ValueBindingError(
            "raw_value occurs more than once in ledgered evidence and is ambiguous"
        )
    return (starts[0], starts[0] + len(raw_value))


def _scale_family(value: str) -> str | None:
    key = value.strip().casefold().replace(",", "").replace(" ", "")
    return _SCALE_ALIASES.get(key)


def _unit_family(value: str) -> str | None:
    if value.strip() == "%":
        return "percentage"
    return _UNIT_FAMILIES.get(_metadata_key(value))


def _validate_detected_metadata(
    arguments: BindFinancialValueArguments,
    *,
    currency_token: str | None,
    scale_token: str | None,
    unit_token: str | None,
) -> None:
    if currency_token is not None:
        if arguments.numeric_type != "money":
            raise ValueBindingError(
                "a currency-marked value requires numeric_type money"
            )
        allowed = _CURRENCY_COMPATIBILITY.get(currency_token.casefold())
        currency = arguments.currency.strip().casefold()
        if allowed is not None and currency not in allowed:
            raise ValueBindingError(
                "currency metadata conflicts with the exact evidence token"
            )

    if scale_token is not None:
        detected_scale = _scale_family(scale_token)
        supplied_scale = _scale_family(arguments.scale)
        if supplied_scale != detected_scale:
            raise ValueBindingError(
                "scale metadata conflicts with the exact evidence token"
            )

    if unit_token is None:
        return
    detected_unit = _unit_family(unit_token)
    if detected_unit == "percentage" and arguments.numeric_type != "percentage":
        raise ValueBindingError(
            "percentage evidence requires numeric_type percentage"
        )
    if detected_unit == "basis_points" and arguments.numeric_type != "basis_points":
        raise ValueBindingError(
            "basis-point evidence requires numeric_type basis_points"
        )
    if (
        detected_unit in {"year", "month", "day"}
        and arguments.numeric_type != "duration"
    ):
        raise ValueBindingError("duration evidence requires numeric_type duration")
    if (
        detected_unit in {"share", "employee", "unit"}
        and arguments.numeric_type != "count"
    ):
        raise ValueBindingError("count evidence requires numeric_type count")
    supplied_unit = _unit_family(arguments.unit)
    if supplied_unit is not None and supplied_unit != detected_unit:
        raise ValueBindingError(
            "unit metadata conflicts with the exact evidence token"
        )


def _canonical_decimal(
    arguments: BindFinancialValueArguments,
) -> str:
    if arguments.numeric_type in {"date", "boolean"}:
        raise ValueBindingError(
            f"numeric_type {arguments.numeric_type} is not Decimal-bindable"
        )
    match = _NUMBER_RE.fullmatch(arguments.raw_value)
    if match is None:
        raise ValueBindingError(
            "raw_value is not one bounded financial Decimal literal"
        )
    if bool(match.group("open")) != bool(match.group("close")):
        raise ValueBindingError("financial value parentheses are unbalanced")
    if match.group("open") and match.group("sign"):
        raise ValueBindingError(
            "parenthesized financial value cannot also contain an explicit sign"
        )
    prefix_currency = match.group("prefix_currency")
    suffix_currency = match.group("suffix_currency")
    if prefix_currency is not None and suffix_currency is not None:
        raise ValueBindingError("financial value cannot contain two currency tokens")
    currency_token = prefix_currency or suffix_currency
    _validate_detected_metadata(
        arguments,
        currency_token=currency_token,
        scale_token=match.group("scale"),
        unit_token=match.group("unit"),
    )

    number = match.group("number").replace(",", "")
    sign = "-" if match.group("open") or match.group("sign") == "-" else ""
    try:
        value = Decimal(sign + number)
    except InvalidOperation as error:
        raise ValueBindingError("raw_value is not a finite Decimal") from error
    if not value.is_finite():
        raise ValueBindingError("raw_value is not a finite Decimal")
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical in {"-0", "+0", ""}:
        canonical = "0"
    if len(canonical) > 128:
        raise ValueBindingError("normalized Decimal exceeds the bounded value size")
    return canonical


def _resolved_ambiguity_flags(
    arguments: BindFinancialValueArguments,
    supplied: Iterable[ValueAmbiguityFlag | str],
) -> tuple[ValueAmbiguityFlag, ...]:
    values = list(supplied)
    try:
        normalized = [ValueAmbiguityFlag(value) for value in values]
    except ValueError as error:
        raise ValueBindingError("unknown value ambiguity flag") from error
    if len(normalized) != len(set(normalized)):
        raise ValueBindingError("value ambiguity flags must be unique")
    selected = set(normalized)
    if arguments.numeric_type == "money" and _is_unknown(arguments.currency):
        selected.add(ValueAmbiguityFlag.CURRENCY_AMBIGUOUS)
    inferred = {
        ValueAmbiguityFlag.UNIT_AMBIGUOUS: arguments.unit,
        ValueAmbiguityFlag.SCALE_AMBIGUOUS: arguments.scale,
        ValueAmbiguityFlag.PERIOD_AMBIGUOUS: arguments.period,
        ValueAmbiguityFlag.ENTITY_AMBIGUOUS: arguments.entity,
        ValueAmbiguityFlag.METRIC_AMBIGUOUS: arguments.metric,
    }
    selected.update(flag for flag, value in inferred.items() if _is_unknown(value))
    return tuple(flag for flag in ValueAmbiguityFlag if flag in selected)


class FinancialValueBinder:
    """Stateless binder for exact evidence occurrences."""

    __slots__ = ()

    def bind(
        self,
        arguments: BindFinancialValueArguments,
        evidence: EvidenceLedgerEntry,
        *,
        value_id: str,
        mandatory: bool = True,
        ambiguity_flags: Iterable[ValueAmbiguityFlag | str] = (),
    ) -> ValueRef:
        if type(mandatory) is not bool:
            raise TypeError("mandatory must be a boolean")
        if arguments.evidence_ref != evidence.evidence_id:
            raise ValueBindingError(
                "binding evidence_ref does not match the ledgered evidence entry"
            )
        evidence_hash = hashlib.sha256(
            evidence.exact_text.encode("utf-8")
        ).hexdigest()
        if evidence_hash != evidence.exact_text_sha256:
            raise ValueBindingError(
                "ledgered evidence text does not match its exact-text hash"
            )

        start, end = _exact_unique_span(evidence.exact_text, arguments.raw_value)
        normalized = _canonical_decimal(arguments)
        flags = _resolved_ambiguity_flags(arguments, ambiguity_flags)
        if mandatory and {
            ValueAmbiguityFlag.UNIT_AMBIGUOUS,
            ValueAmbiguityFlag.PERIOD_AMBIGUOUS,
        }.intersection(flags):
            raise ValueBindingError(
                "mandatory value has unresolved unit or period ambiguity"
            )

        return ValueRef(
            value_id=value_id,
            evidence_ref=evidence.evidence_id,
            evidence_text_sha256=evidence.exact_text_sha256,
            source=evidence.source,
            paragraph_id=evidence.paragraph_id,
            source_span_start=start,
            source_span_end=end,
            table_id=evidence.table_id,
            row_index=evidence.row_index,
            column_index=evidence.column_index,
            raw_value=arguments.raw_value,
            normalized_value=normalized,
            numeric_type=arguments.numeric_type,
            currency=arguments.currency,
            unit=arguments.unit,
            scale=arguments.scale,
            period=arguments.period,
            entity=arguments.entity,
            metric=arguments.metric,
            mandatory=mandatory,
            ambiguity_flags=flags,
        )


BINDER = FinancialValueBinder()


def bind_financial_value(
    arguments: BindFinancialValueArguments,
    evidence: EvidenceLedgerEntry,
    *,
    value_id: str,
    mandatory: bool = True,
    ambiguity_flags: Iterable[ValueAmbiguityFlag | str] = (),
) -> ValueRef:
    """Bind one Runtime-owned ID to one exact ledgered evidence occurrence."""

    return BINDER.bind(
        arguments,
        evidence,
        value_id=value_id,
        mandatory=mandatory,
        ambiguity_flags=ambiguity_flags,
    )


ValueBinder = FinancialValueBinder
bind_value = bind_financial_value


__all__ = [
    "BINDER",
    "FinancialValueBinder",
    "ValueAmbiguityFlag",
    "ValueBinder",
    "ValueBindingError",
    "ValueRef",
    "bind_financial_value",
    "bind_value",
]
