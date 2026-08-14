import json

import httpx
import pytest

from findver_agent.model_backends.base import GenerationConfig
from findver_agent.model_backends.openai_compatible import OpenAICompatibleBackend


@pytest.mark.asyncio
async def test_openai_backend_calls_gateway_without_authorization_header():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://model-gateway:8080/v1/chat/completions"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "fixed-model"
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

