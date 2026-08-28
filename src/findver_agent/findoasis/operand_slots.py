"""Deterministic one-to-one matching for typed numeric operand slots."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Protocol

from .contracts import OperandSlot


_UNKNOWN = {"", "?", "n/a", "na", "none", "unknown", "unspecified"}


class NumericValueLike(Protocol):
    value_id: str
    metric: str
    entity: str
    period: str
    numeric_type: str
    currency: str
    unit: str
    scale: str


def _normalized(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").split())


def _normalized_period(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.strip().casefold())
    if re.fullmatch(r"fy(?:19|20|21)\d{2}", normalized):
        return normalized[2:]
    return normalized


def _matches(required: str, actual: str, *, period: bool = False) -> bool:
    normalized_required = _normalized(required)
    if normalized_required in _UNKNOWN:
        return True
    if period:
        return _normalized_period(required) == _normalized_period(actual)
    return normalized_required == _normalized(actual)


def value_matches_slot(slot: OperandSlot, value: NumericValueLike) -> bool:
    return all(
        (
            _matches(slot.metric, value.metric),
            _matches(slot.entity, value.entity),
            _matches(slot.period, value.period, period=True),
            _matches(slot.numeric_type, value.numeric_type),
            _matches(slot.currency, value.currency),
            _matches(slot.unit, value.unit),
            _matches(slot.scale, value.scale),
        )
    )


def match_operand_slots(
    slots: Sequence[OperandSlot],
    values: Mapping[str, NumericValueLike],
) -> dict[str, str] | None:
    """Return a complete slot-to-ValueRef assignment, or ``None``.

    The bounded backtracking matcher considers the most constrained slots first
    and never assigns one report ValueRef to more than one slot.
    """

    if not slots:
        return None
    candidates = {
        slot.slot_id: tuple(
            sorted(
                value_id
                for value_id, value in values.items()
                if value_matches_slot(slot, value)
            )
        )
        for slot in slots
    }
    if any(not refs for refs in candidates.values()):
        return None
    ordered = sorted(
        slots, key=lambda slot: (len(candidates[slot.slot_id]), slot.slot_id)
    )
    assignment: dict[str, str] = {}
    used: set[str] = set()

    def assign(index: int) -> bool:
        if index == len(ordered):
            return True
        slot = ordered[index]
        for value_id in candidates[slot.slot_id]:
            if value_id in used:
                continue
            assignment[slot.slot_id] = value_id
            used.add(value_id)
            if assign(index + 1):
                return True
            used.remove(value_id)
            del assignment[slot.slot_id]
        return False

    if not assign(0):
        return None
    return {slot.slot_id: assignment[slot.slot_id] for slot in slots}


__all__ = ["match_operand_slots", "value_matches_slot"]
