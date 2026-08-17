"""OpenAI-compatible chat-completions backend used only through Model Gateway."""

from __future__ import annotations

import time
from typing import Any

import httpx

from findver_agent.model_backends.base import (
    ContextWindowExceededError,
    GenerationConfig,
    ModelResponse,
    context_window_metadata,
)
from findver_agent.model_backends.retry_policy import retry_async


class BackendError(RuntimeError):
    """A model backend returned an unusable response."""


class OpenAICompatibleBackend:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        model_context_window_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_name = model
        self.model_context_window_tokens = model_context_window_tokens
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    @staticmethod
    def _retryable(error: BaseException) -> bool:
        if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        return isinstance(error, httpx.HTTPStatusError) and (
            error.response.status_code == 429 or error.response.status_code >= 500
        )

    async def generate(
        self,
        messages: list[dict[str, str]],
        config: GenerationConfig,
    ) -> ModelResponse:
        context = context_window_metadata(
            messages,
            max_output_tokens=config.max_output_tokens,
            model_context_window_tokens=self.model_context_window_tokens,
        )
        if context["overflow_status"] == "estimated_overflow":
            raise ContextWindowExceededError(
                "context window overflow before request: "
                f"estimated_input_tokens={context['estimated_input_tokens']} "
                f"max_output_tokens={config.max_output_tokens} "
                f"model_context_window_tokens={self.model_context_window_tokens}"
            )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "max_tokens": config.max_output_tokens,
        }
        if config.seed is not None:
            payload["seed"] = config.seed

        started = time.perf_counter()

        async def request() -> httpx.Response:
            response = await self._client.post(self._url, json=payload)
            response.raise_for_status()
            return response

        response = await retry_async(
            request,
            max_retries=self._max_retries,
            retryable=self._retryable,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise BackendError("gateway returned an invalid chat completion") from error
        if not isinstance(content, str):
            raise BackendError("gateway completion content must be a string")
        input_tokens = int(usage.get("prompt_tokens") or 0)
        if (
            input_tokens > 0
            and input_tokens + config.max_output_tokens
            > self.model_context_window_tokens
        ):
            raise ContextWindowExceededError(
                "context window overflow from provider usage: "
                f"actual_provider_input_tokens={input_tokens} "
                f"max_output_tokens={config.max_output_tokens} "
                f"model_context_window_tokens={self.model_context_window_tokens}"
            )
        return ModelResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
            response_id=data.get("id"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

