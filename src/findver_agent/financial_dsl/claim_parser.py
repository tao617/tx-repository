"""Deterministically parse bounded numeric claim literals into ClaimValueRefs."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .models import ClaimValueRef


MAX_CLAIM_VALUES = 16

_CLAIM_NUMBER_RE = re.compile(
    r"""
    (?<![\w.+\-])
    (?P<open>\()?
    (?P<sign>[+-])?
    (?P<currency>US\$|C\$|A\$|HK\$|[$€£]|USD|EUR|GBP|CNY|JPY|CAD|AUD|HKD)?
    \s*
    (?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)
    \s*
    (?P<scale>thousands?|millions?|billions?|trillions?|k|mn|bn|tn)?
    \s*
    (?P<unit>%|percent(?:age)?|basis\s+points?|bps?|shares?|years?|months?|days?)?
    (?P<close>\))?
    (?!\w|[.,]\d)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SCALES = {
    None: "one",
    "k": "thousand",
    "thousand": "thousand",
    "thousands": "thousand",
    "mn": "million",
    "million": "million",
    "millions": "million",
    "bn": "billion",
    "billion": "billion",
    "billions": "billion",
    "tn": "trillion",
    "trillion": "trillion",
    "trillions": "trillion",
}
_CURRENCIES = {
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "c$": "CAD",
    "cad": "CAD",
    "a$": "AUD",
    "aud": "AUD",
    "hk$": "HKD",
    "hkd": "HKD",
    "cny": "CNY",
    "jpy": "JPY",
}


def _canonical_decimal(number: str, *, negative: bool) -> str:
    try:
        value = Decimal(("-" if negative else "") + number.replace(",", ""))
    except InvalidOperation as error:  # pragma: no cover - guarded by regex
        raise ValueError("claim contains an invalid Decimal") from error
    if not value.is_finite():
        raise ValueError("claim contains a non-finite Decimal")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", "+0", ""} else rendered


def _relation_hint(prefix: str) -> str:
    lowered = " ".join(prefix.casefold().split())
    for pattern, relation in (
        (r"(?:approximately|about|roughly|around|nearly)\s*$", "approximately_equals"),
        (r"(?:at least|no less than)\s*$", "greater_than_or_equal"),
        (r"(?:more than|greater than|over)\s*$", "greater_than"),
        (r"(?:at most|no more than)\s*$", "less_than_or_equal"),
        (r"(?:less than|under|below)\s*$", "less_than"),
    ):
        if re.search(pattern, lowered):
            return relation
    return "equals"


def parse_claim_values(statement: str) -> tuple[ClaimValueRef, ...]:
    """Return stable claim literals without treating likely year labels as values."""

    values: list[ClaimValueRef] = []
    for match in _CLAIM_NUMBER_RE.finditer(statement):
        if len(values) >= MAX_CLAIM_VALUES:
            break
        if bool(match.group("open")) != bool(match.group("close")):
            continue
        if match.group("open") and match.group("sign"):
            continue
        number = match.group("number")
        currency_token = match.group("currency")
        scale_token = match.group("scale")
        unit_token = match.group("unit")
        bare_integer = (
            currency_token is None
            and scale_token is None
            and unit_token is None
            and "." not in number
            and "," not in number
        )
        integer = int(number) if bare_integer else None
        if integer is not None and 1900 <= integer <= 2199:
            continue

        start, end = match.span()
        raw = statement[start:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw) - len(raw.rstrip())
        start += leading
        end -= trailing
        raw = statement[start:end]

        unit_key = unit_token.casefold() if unit_token else None
        if unit_key in {"%", "percent", "percentage"}:
            numeric_type = "percentage"
            unit = "percentage"
            currency = "unknown"
        elif unit_key in {"bp", "bps", "basis point", "basis points"}:
            numeric_type = "basis_points"
            unit = "basis_points"
            currency = "unknown"
        elif unit_key in {"share", "shares"}:
            numeric_type = "count"
            unit = "shares"
            currency = "unknown"
        elif unit_key in {"year", "years", "month", "months", "day", "days"}:
            numeric_type = "duration"
            unit = unit_key.rstrip("s")
            currency = "unknown"
        elif currency_token is not None:
            numeric_type = "money"
            currency = _CURRENCIES.get(currency_token.casefold(), "unknown")
            unit = currency
        else:
            numeric_type = "scalar"
            currency = "unknown"
            unit = "one"

        ambiguities: list[str] = []
        if currency_token is not None and currency == "unknown":
            ambiguities.append("currency_ambiguous")
        values.append(
            ClaimValueRef(
                claim_value_id=f"claim-value-{len(values) + 1:04d}",
                raw_value=raw,
                normalized_value=_canonical_decimal(
                    number,
                    negative=bool(match.group("open"))
                    or match.group("sign") == "-",
                ),
                numeric_type=numeric_type,
                currency=currency,
                unit=unit,
                scale=_SCALES.get(
                    scale_token.casefold() if scale_token else None, "unknown"
                ),
                relation=_relation_hint(statement[max(0, start - 48) : start]),
                source_span_start=start,
                source_span_end=end,
                ambiguity_flags=ambiguities,
            )
        )
    return tuple(values)


__all__ = ["MAX_CLAIM_VALUES", "parse_claim_values"]
