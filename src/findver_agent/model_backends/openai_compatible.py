"""OpenAI-compatible chat-completions backend used only through Model Gateway."""

from __future__ import annotations

import time
from typing import Any

import httpx

from findver_agent.model_backends.base import (
    ContextWindowExceededError,
    GenerationConfig,
    ModelResponse,
    ProtocolDriftError,
    context_window_metadata,
)
from findver_agent.model_backends.retry_policy import retry_async
from findver_agent.model_backends.rate_limiter import SlidingWindowRateLimiter
from findver_agent.model_backends.transport_adapters import (
    ResponseFormat,
    get_transport_adapter,
    validate_transport_thinking,
)


class BackendError(RuntimeError):
    """A model backend returned an unusable response."""


MAX_SHARED_CONNECTIONS = 32
SUPPORTED_FINISH_REASONS = frozenset({"stop", "length", "content_filter"})
class OpenAICompatibleBackend:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        model_context_window_tokens: int,
        transport_profile: str | None = None,
        request_profile: str | None = None,
        thinking_type: str | None = None,
        response_format: ResponseFormat = "text",
        rate_limit_requests_per_minute: int | None = None,
        rate_limit_tokens_per_minute: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if transport_profile is not None and request_profile is not None:
            raise ValueError("configure transport_profile, not both profile names")
        selected_profile = transport_profile or request_profile or "openai_standard"
        thinking_mode = thinking_type or "unsupported"
        validate_transport_thinking(selected_profile, thinking_mode)
        adapter = get_transport_adapter(selected_profile)
        if (
            response_format == "json_object"
            and "response_format" not in adapter.allowed_request_fields
        ):
            raise ValueError(
                f"{adapter.profile} does not support response_format=json_object"
            )
        rate_limit_group = (
            rate_limit_requests_per_minute,
            rate_limit_tokens_per_minute,
        )
        if any(value is not None for value in rate_limit_group) and not all(
            value is not None for value in rate_limit_group
        ):
            raise ValueError("RPM and TPM admission limits must be configured together")
        self.model_name = model
        self.model_context_window_tokens = model_context_window_tokens
        self.transport_profile = adapter.profile
        self.request_profile = adapter.profile
        self.thinking_mode = thinking_mode
        self.response_format = response_format
        self._adapter = adapter
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._max_retries = max_retries
        self._rate_limiter = (
            SlidingWindowRateLimiter(
                requests_per_minute=rate_limit_requests_per_minute,
                tokens_per_minute=rate_limit_tokens_per_minute,
            )
            if rate_limit_requests_per_minute is not None
            and rate_limit_tokens_per_minute is not None
            else None
        )
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            limits=httpx.Limits(
                max_connections=MAX_SHARED_CONNECTIONS,
                max_keepalive_connections=MAX_SHARED_CONNECTIONS,
            ),
        )

    @staticmethod
    def _retryable(error: BaseException) -> bool:
        if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        return isinstance(error, httpx.HTTPStatusError) and (
            error.response.status_code == 429 or error.response.status_code >= 500
        )

    @staticmethod
    def _retry_after_seconds(error: BaseException, attempt: int) -> float:
        del attempt
        if not isinstance(error, httpx.HTTPStatusError):
            return 0.0
        value = error.response.headers.get("retry-after")
        if value is None:
            return 0.0
        try:
            seconds = float(value)
        except ValueError:
            return 0.0
        return min(max(seconds, 0.0), 60.0)

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
        payload: dict[str, Any] = self._adapter.build_request(
            model=self.model_name,
            messages=messages,
            temperature=config.temperature,
            top_p=config.top_p,
            max_tokens=config.max_output_tokens,
            seed=config.seed,
            response_format=self.response_format,
        )

        started = time.perf_counter()
        rate_limit_wait_ms = 0.0
        transport_attempts = 0

        async def request() -> httpx.Response:
            nonlocal rate_limit_wait_ms, transport_attempts
            transport_attempts += 1
            if self._rate_limiter is not None:
                rate_limit_wait_ms += await self._rate_limiter.acquire(
                    int(context["estimated_total_tokens"])
                )
            response = await self._client.post(self._url, json=payload)
            response.raise_for_status()
            return response

        response = await retry_async(
            request,
            max_retries=self._max_retries,
            retryable=self._retryable,
            delay_for=self._retry_after_seconds,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            content = message["content"]
            finish_reason = choice["finish_reason"]
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise BackendError("gateway returned an invalid chat completion") from error
        if not isinstance(content, str):
            raise BackendError("gateway completion content must be a string")
        if finish_reason not in SUPPORTED_FINISH_REASONS:
            raise BackendError("gateway returned an unsupported finish_reason")
        reasoning_content = message.get("reasoning_content")
        if (
            self.thinking_mode == "disabled"
            and reasoning_content is not None
            and reasoning_content != ""
        ):
            raise ProtocolDriftError(
                "upstream returned non-empty hidden reasoning while thinking was disabled"
            )
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
            finish_reason=finish_reason,
            rate_limit_wait_ms=rate_limit_wait_ms,
            transport_retries=max(transport_attempts - 1, 0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
