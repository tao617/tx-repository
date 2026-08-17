import json

import httpx
import pytest

from findver_agent.model_backends.base import (
    ContextWindowExceededError,
    GenerationConfig,
)
from findver_agent.model_backends.openai_compatible import OpenAICompatibleBackend


@pytest.mark.asyncio
async def test_openai_backend_calls_gateway_without_authorization_header():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://model-gateway:8080/v1/chat/completions"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "fixed-model"
        assert "model_context_window_tokens" not in body
        assert "prompt_budget_tokens" not in body
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "choices": [{"message": {"content": '{"action":"submit_answer","arguments":{}}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        transport=httpx.MockTransport(handler),
        model_context_window_tokens=100_000,
    )
    try:
        result = await backend.generate(
            [{"role": "user", "content": "claim"}],
            GenerationConfig(max_output_tokens=64, max_context_tokens=4096),
        )
    finally:
        await backend.aclose()

    assert result.input_tokens == 12
    assert result.output_tokens == 5

@pytest.mark.asyncio
async def test_openai_backend_rejects_estimated_overflow_before_transport():
    transport_called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(500)

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=8192,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ContextWindowExceededError, match="before request"):
            await backend.generate(
                [{"role": "user", "content": "x" * 40_000}],
                GenerationConfig(
                    max_output_tokens=1024,
                    prompt_budget_tokens=4096,
                ),
            )
    finally:
        await backend.aclose()

    assert transport_called is False


@pytest.mark.asyncio
async def test_openai_backend_rejects_authoritative_provider_usage_overflow():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "response-overflow",
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"action":"submit_answer","arguments":{}}'
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 8000, "completion_tokens": 5},
            },
        )

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=8192,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ContextWindowExceededError, match="provider usage"):
            await backend.generate(
                [{"role": "user", "content": "claim"}],
                GenerationConfig(
                    max_output_tokens=256,
                    prompt_budget_tokens=4096,
                ),
            )
    finally:
        await backend.aclose()

