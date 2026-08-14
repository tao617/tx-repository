"""Common model backend protocol."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    seed: int | None = None
    max_output_tokens: int = Field(default=1024, ge=1, le=32768)
    max_context_tokens: int = Field(default=32768, ge=1024)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0
    response_id: str | None = None


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

