"""Static skill catalog and strict JSON action parsing for generic tasks."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from findver_agent.generic.models import (
    GenericActionControl,
    GenericActionEnvelope,
    GenericSubmitArguments,
    GenericTask,
)
from findver_agent.skills.base import SkillError
from findver_agent.skills.calculator import CalculatorSkill


class GenericActionParseError(ValueError):
    """A model response is not one valid allowlisted action."""


class RuntimeSkill(Protocol):
    name: str
    description: str
    arguments_model: type[BaseModel]

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        ...


SkillFactory = Callable[[GenericTask], RuntimeSkill]


@dataclass(frozen=True, slots=True)
class ParsedGenericAction:
    action: str
    arguments: BaseModel
    control: GenericActionControl


class SearchContextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class ReadContextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    unit_ids: list[str] = Field(min_length=1, max_length=12)


class CalculatorArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expression: str = Field(min_length=1, max_length=256)


class LookupDataArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: list[str | int] = Field(default_factory=list, max_length=32)


class CompareValuesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    left: JsonValue
    right: JsonValue
    mode: Literal["exact", "casefold", "numeric"] = "exact"
    tolerance: float = Field(default=0, ge=0, le=1e100)


_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_TOKEN_PATTERN = re.compile(
    r"\d+(?:,\d{3})*(?:\.\d+)?%?|[^\W\d_]+",
    re.IGNORECASE | re.UNICODE,
)


def tokenise_generic(text: str) -> list[str]:
    """Deterministic Unicode-aware tokens with CJK characters and bigrams."""

    tokens: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text.casefold()):
        token = raw.replace(",", "")
        cjk = _CJK_PATTERN.findall(token)
        if cjk:
            tokens.extend(cjk)
            tokens.extend("".join(cjk[index : index + 2]) for index in range(len(cjk) - 1))
            if len(cjk) > 1:
                tokens.append("".join(cjk))
        else:
            tokens.append(token)
    return tokens


class SearchContextSkill:
    name = "search_context"
    description = "Search the public context units and return ranked snippets and unit IDs."
    arguments_model = SearchContextArguments

    def __init__(self, task: GenericTask, *, snippet_characters: int = 500) -> None:
        self._units = task.context
        self._snippet_characters = snippet_characters
        self._documents = [tokenise_generic(unit.text) for unit in self._units]
        self._frequencies = [Counter(document) for document in self._documents]
        self._lengths = [len(document) for document in self._documents]
        self._average_length = (
            sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        )
        self._document_frequency: Counter[str] = Counter()
        for document in self._documents:
            self._document_frequency.update(set(document))

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        arguments = SearchContextArguments.model_validate(kwargs)
        query_tokens = tokenise_generic(arguments.query)
        if not query_tokens:
            raise SkillError("query contains no searchable tokens")
        count = len(self._documents)
        scored: list[tuple[float, int]] = []
        for index, frequencies in enumerate(self._frequencies):
            score = 0.0
            document_length = self._lengths[index]
            for term in query_tokens:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_frequency = math.log(
                    1 + (count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                normaliser = frequency + 1.5 * (
                    1 - 0.75
                    + 0.75 * document_length / (self._average_length or 1)
                )
                score += inverse_frequency * frequency * 2.5 / normaliser
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], self._units[item[1]].unit_id))
        hits: list[JsonValue] = []
        for score, index in scored[: arguments.top_k]:
            unit = self._units[index]
            snippet = (
                unit.text
                if len(unit.text) <= self._snippet_characters
                else f"{unit.text[: self._snippet_characters]}…"
            )
            hits.append(
                {
                    "unit_id": unit.unit_id,
                    "title": unit.title,
                    "score": round(score, 6),
                    "snippet": snippet,
                }
            )
        return {"query": arguments.query, "hits": hits}


class ReadContextSkill:
    name = "read_context"
    description = "Read exact public context units by unit_id so they enter the evidence ledger."
    arguments_model = ReadContextArguments

    def __init__(self, task: GenericTask) -> None:
        self._units = {unit.unit_id: unit for unit in task.context}

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        arguments = ReadContextArguments.model_validate(kwargs)
        if len(arguments.unit_ids) != len(set(arguments.unit_ids)):
            raise SkillError("unit_ids must be unique")
        try:
            units = [self._units[unit_id] for unit_id in arguments.unit_ids]
        except KeyError as error:
            raise SkillError(f"unknown context unit_id: {error.args[0]}") from error
        return {
            "units": [
                {"unit_id": unit.unit_id, "title": unit.title, "text": unit.text}
                for unit in units
            ]
        }


class CalculatorRuntimeSkill:
    name = "calculator"
    description = "Evaluate bounded arithmetic with the existing AST-allowlisted calculator."
    arguments_model = CalculatorArguments

    def __init__(self, task: GenericTask) -> None:
        del task
        self._calculator = CalculatorSkill()

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        arguments = CalculatorArguments.model_validate(kwargs)
        result = self._calculator.execute(expression=arguments.expression)
        return {"expression": str(result["expression"]), "result": result["result"]}  # type: ignore[dict-item]


class LookupDataSkill:
    name = "lookup_data"
    description = "Traverse the task's public structured data by a bounded string/integer path."
    arguments_model = LookupDataArguments

    def __init__(self, task: GenericTask, *, max_result_characters: int = 8_000) -> None:
        self._data = task.data
        self._max_result_characters = max_result_characters

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        arguments = LookupDataArguments.model_validate(kwargs)
        if self._data is None:
            raise SkillError("this task has no structured data")
        value: JsonValue = self._data
        for part in arguments.path:
            if isinstance(value, dict) and isinstance(part, str):
                if part not in value:
                    raise SkillError(f"unknown object key: {part}")
                value = value[part]
            elif isinstance(value, list) and isinstance(part, int) and not isinstance(part, bool):
                if part < 0 or part >= len(value):
                    raise SkillError(f"list index out of range: {part}")
                value = value[part]
            else:
                raise SkillError("lookup path does not match the structured data")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > self._max_result_characters:
            raise SkillError("lookup result exceeds the bounded observation size")
        return {"path": list(arguments.path), "value": value}


class CompareValuesSkill:
    name = "compare_values"
    description = "Compare two JSON scalar values exactly, case-insensitively, or numerically."
    arguments_model = CompareValuesArguments

    def __init__(self, task: GenericTask) -> None:
        del task

    @staticmethod
    def _number(value: JsonValue) -> float:
        if isinstance(value, bool):
            raise SkillError("boolean values are not numeric")
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            text = value.strip().replace(",", "")
            percentage = text.endswith("%")
            if percentage:
                text = text[:-1]
            try:
                number = float(text)
            except ValueError as error:
                raise SkillError("value cannot be parsed as a number") from error
            if percentage:
                number /= 100
        else:
            raise SkillError("numeric comparison accepts only numbers or numeric strings")
        if not math.isfinite(number):
            raise SkillError("numeric comparison requires finite values")
        return number

    def execute(self, **kwargs: object) -> dict[str, JsonValue]:
        arguments = CompareValuesArguments.model_validate(kwargs)
        if arguments.mode == "exact":
            return {"mode": "exact", "equal": arguments.left == arguments.right}
        if arguments.mode == "casefold":
            if not isinstance(arguments.left, str) or not isinstance(arguments.right, str):
                raise SkillError("casefold comparison requires two strings")
            return {
                "mode": "casefold",
                "equal": arguments.left.casefold() == arguments.right.casefold(),
            }
        left = self._number(arguments.left)
        right = self._number(arguments.right)
        difference = left - right
        return {
            "mode": "numeric",
            "equal": abs(difference) <= arguments.tolerance,
            "left": left,
            "right": right,
            "difference": difference,
            "absolute_difference": abs(difference),
            "tolerance": arguments.tolerance,
        }


class SkillCatalog:
    """Code-owned skill factories; profiles may select names but cannot import code."""

    def __init__(self, factories: Mapping[str, SkillFactory] | None = None) -> None:
        self._factories: dict[str, SkillFactory] = dict(factories or {})

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._factories)

    def register(self, name: str, factory: SkillFactory) -> None:
        if name == "submit_answer" or not name:
            raise ValueError("invalid generic skill name")
        if name in self._factories:
            raise ValueError(f"generic skill is already registered: {name}")
        self._factories[name] = factory

    def build(
        self, task: GenericTask, allowed_names: list[str]
    ) -> dict[str, RuntimeSkill]:
        unknown = set(allowed_names) - set(self._factories)
        if unknown:
            raise ValueError(f"task profile references unknown skills: {sorted(unknown)}")
        return {name: self._factories[name](task) for name in allowed_names}

    @staticmethod
    def parse_action(
        content: str,
        skills: Mapping[str, RuntimeSkill],
    ) -> ParsedGenericAction:
        text = content.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
                text = "\n".join(lines[1:-1]).strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as error:
            raise GenericActionParseError(
                f"response must be one JSON object: {error.msg}"
            ) from error
        try:
            envelope = GenericActionEnvelope.model_validate(raw)
        except ValidationError as error:
            raise GenericActionParseError(f"invalid action envelope: {error}") from error
        if envelope.action == "submit_answer":
            try:
                arguments = GenericSubmitArguments.model_validate(envelope.arguments)
            except ValidationError as error:
                raise GenericActionParseError(f"invalid submit arguments: {error}") from error
            return ParsedGenericAction(
                action=envelope.action,
                arguments=arguments,
                control=envelope.control,
            )
        try:
            skill = skills[envelope.action]
        except KeyError as error:
            raise GenericActionParseError(
                f"action is not in the task skill allowlist: {envelope.action}"
            ) from error
        try:
            arguments = skill.arguments_model.model_validate(envelope.arguments)
        except ValidationError as error:
            raise GenericActionParseError(
                f"invalid arguments for {envelope.action}: {error}"
            ) from error
        return ParsedGenericAction(
            action=envelope.action,
            arguments=arguments,
            control=envelope.control,
        )


def default_skill_catalog() -> SkillCatalog:
    return SkillCatalog(
        {
            SearchContextSkill.name: SearchContextSkill,
            ReadContextSkill.name: ReadContextSkill,
            CalculatorRuntimeSkill.name: CalculatorRuntimeSkill,
            LookupDataSkill.name: LookupDataSkill,
            CompareValuesSkill.name: CompareValuesSkill,
        }
    )
