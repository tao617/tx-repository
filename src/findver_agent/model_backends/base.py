"""Common model backend protocol."""

from __future__ import annotations

import math
from typing import Literal, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ContextWindowExceededError(RuntimeError):
    """A request violates the locally declared model context capacity."""


class ProtocolDriftError(RuntimeError):
    """An upstream response violates the selected request profile."""


FinishReason = Literal["stop", "length", "content_filter"]


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    seed: int | None = None
    max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    prompt_budget_tokens: int = Field(
        default=32768,
        ge=1024,
        validation_alias=AliasChoices("prompt_budget_tokens", "max_context_tokens"),
    )

    @property
    def max_context_tokens(self) -> int:
        """Compatibility view for historical configs and callers."""

        return self.prompt_budget_tokens


def estimate_message_input_tokens(messages: list[dict[str, str]]) -> int:
    """Model-independent deterministic estimate; provider usage remains authoritative."""

    characters = sum(len(message.get("content", "")) for message in messages)
    whitespace_units = sum(
        len(message.get("content", "").split()) for message in messages
    )
    content_estimate = max(
        math.ceil(characters / 4.2),
        math.ceil(whitespace_units * 1.5),
    )
    return content_estimate + 4 * len(messages) + 3


def context_window_metadata(
    messages: list[dict[str, str]],
    *,
    max_output_tokens: int,
    model_context_window_tokens: int | None,
) -> dict[str, int | str | None]:
    estimated = estimate_message_input_tokens(messages)
    total = estimated + max_output_tokens
    if model_context_window_tokens is None:
        status = "not_enforced"
    elif total > model_context_window_tokens:
        status = "estimated_overflow"
    else:
        status = "within_window"
    return {
        "estimated_input_tokens": estimated,
        "max_output_tokens": max_output_tokens,
        "estimated_total_tokens": total,
        "model_context_window_tokens": model_context_window_tokens,
        "overflow_status": status,
    }


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0
    response_id: str | None = None
    finish_reason: FinishReason = "stop"


class ModelBackend(Protocol):
    model_name: str

    async def generate(
        self,
        messages: list[dict[str, str]],
        config: GenerationConfig,
    ) -> ModelResponse:
        """Generate exactly one assistant response."""
        ...

    async def aclose(self) -> None:
        """Release backend resources."""
        ...
