import json

import httpx
import pytest

from findver_agent.model_backends.base import (
    ContextWindowExceededError,
    GenerationConfig,
    ProtocolDriftError,
)
from findver_agent.model_backends.openai_compatible import (
    BackendError,
    MAX_SHARED_CONNECTIONS,
    OpenAICompatibleBackend,
)


@pytest.mark.asyncio
async def test_openai_backend_calls_gateway_without_authorization_header():
    assert MAX_SHARED_CONNECTIONS == 32
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://model-gateway:8080/v1/chat/completions"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "fixed-model"
        assert "model_context_window_tokens" not in body
        assert "prompt_budget_tokens" not in body
        assert "thinking" not in body
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"submit_answer","arguments":{}}'
                        },
                        "finish_reason": "stop",
                    }
                ],
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
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_openai_backend_transport_retry_reuses_identical_long_context_payload():
    request_bodies: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(json.loads(request.content))
        if len(request_bodies) == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "id": "response-after-retry",
                "choices": [
                    {
                        "message": {
                            "content": '{"action":"submit_answer","arguments":{}}'
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1200, "completion_tokens": 5},
            },
        )

    messages = [
        {"role": "system", "content": "Use the report preview once."},
        {
            "role": "user",
            "content": (
                "<full_report_preview>[paragraph id = 0] text\n"
                "</full_report_preview>"
            ),
        },
    ]
    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=1,
        transport=httpx.MockTransport(handler),
        model_context_window_tokens=100_000,
    )
    try:
        await backend.generate(
            messages,
            GenerationConfig(max_output_tokens=64, prompt_budget_tokens=90_000),
        )
    finally:
        await backend.aclose()

    assert len(request_bodies) == 2
    assert request_bodies[0] == request_bodies[1]
    assert "<full_report_preview>" in request_bodies[0]["messages"][1]["content"]


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
                        },
                        "finish_reason": "stop",
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


@pytest.mark.asyncio
async def test_deepseek_profile_sends_only_explicit_disabled_thinking():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert "extra_body" not in body
        return httpx.Response(
            200,
            json={
                "id": f"deepseek-{calls}",
                "choices": [
                    {
                        "message": {"content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {},
            },
        )

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=100_000,
        request_profile="deepseek_v4_openai",
        thinking_type="disabled",
        transport=httpx.MockTransport(handler),
    )
    try:
        for _ in range(5):
            await backend.generate(
                [{"role": "user", "content": "claim"}], GenerationConfig()
            )
    finally:
        await backend.aclose()
    assert calls == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
async def test_backend_retains_supported_non_stop_finish_reason(finish_reason):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "truncated"},
                        "finish_reason": finish_reason,
                    }
                ]
            },
        )

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=100_000,
        transport=httpx.MockTransport(handler),
    )
    try:
        response = await backend.generate(
            [{"role": "user", "content": "claim"}], GenerationConfig()
        )
    finally:
        await backend.aclose()
    assert response.finish_reason == finish_reason


@pytest.mark.asyncio
async def test_backend_rejects_unknown_finish_reason():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "{}"},
                        "finish_reason": "mystery",
                    }
                ]
            },
        )

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=100_000,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError, match="unsupported finish_reason"):
            await backend.generate(
                [{"role": "user", "content": "claim"}], GenerationConfig()
            )
    finally:
        await backend.aclose()


@pytest.mark.asyncio
async def test_deepseek_profile_rejects_reasoning_content_without_storing_it():
    secret_reasoning = "hidden protocol drift text"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "{}",
                            "reasoning_content": secret_reasoning,
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    backend = OpenAICompatibleBackend(
        base_url="http://model-gateway:8080/v1",
        model="fixed-model",
        timeout_seconds=2,
        max_retries=0,
        model_context_window_tokens=100_000,
        request_profile="deepseek_v4_openai",
        thinking_type="disabled",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProtocolDriftError) as caught:
            await backend.generate(
                [{"role": "user", "content": "claim"}], GenerationConfig()
            )
    finally:
        await backend.aclose()
    assert secret_reasoning not in str(caught.value)
