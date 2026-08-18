import json

import httpx
import pytest
from fastapi.testclient import TestClient

from findver_gateway.app import MAX_SHARED_CONNECTIONS, Settings, create_app


def test_gateway_forwards_only_to_fixed_chat_endpoint_and_rewrites_model():
    assert MAX_SHARED_CONNECTIONS == 32
    def upstream(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://fixed.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-token"
        payload = json.loads(request.content)
        assert payload["model"] == "provider-model"
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    settings = Settings(
        upstream_base_url="https://fixed.example/v1",
        upstream_model="provider-model",
        model_aliases=frozenset({"runtime-alias"}),
        upstream_api_key="private-token",
    )
    with TestClient(create_app(settings, transport=httpx.MockTransport(upstream))) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "runtime-alias",
                "messages": [{"role": "user", "content": "claim"}],
                "temperature": 0,
                "top_p": 1,
                "max_tokens": 32,
                "thinking": {"type": "disabled"},
            },
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"


def test_gateway_rejects_unknown_alias_and_arbitrary_fields():
    settings = Settings(
        upstream_base_url="http://fixed-upstream:8000/v1",
        upstream_model="provider-model",
        model_aliases=frozenset({"allowed"}),
    )
    with TestClient(create_app(settings, transport=httpx.MockTransport(lambda request: httpx.Response(500)))) as client:
        unknown = client.post(
            "/v1/chat/completions",
            json={"model": "other", "messages": [{"role": "user", "content": "claim"}]},
        )
        proxy_attempt = client.post(
            "/v1/chat/completions",
            json={
                "model": "allowed",
                "messages": [{"role": "user", "content": "claim"}],
                "url": "https://attacker.example",
            },
        )

    assert unknown.status_code == 400
    assert proxy_attempt.status_code == 422


@pytest.mark.parametrize(
    "thinking",
    [
        None,
        {"type": "enabled"},
        {"type": "disabled", "effort": "high"},
        {"mode": "disabled"},
    ],
)
def test_gateway_rejects_non_disabled_or_extended_thinking(thinking):
    settings = Settings(
        upstream_base_url="http://fixed-upstream:8000/v1",
        upstream_model="provider-model",
        model_aliases=frozenset({"allowed"}),
    )
    with TestClient(
        create_app(
            settings,
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "allowed",
                "messages": [{"role": "user", "content": "claim"}],
                "thinking": thinking,
            },
        )
    assert response.status_code == 422


def test_gateway_generic_request_does_not_invent_deepseek_thinking():
    def upstream(request: httpx.Request) -> httpx.Response:
        assert "thinking" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": []})

    settings = Settings(
        upstream_base_url="http://fixed-upstream:8000/v1",
        upstream_model="provider-model",
        model_aliases=frozenset({"allowed"}),
    )
    with TestClient(
        create_app(settings, transport=httpx.MockTransport(upstream))
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "allowed",
                "messages": [{"role": "user", "content": "claim"}],
            },
        )
    assert response.status_code == 200


def test_gateway_forwards_only_disabled_qwen_thinking():
    def upstream(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["enable_thinking"] is False
        assert "thinking" not in payload
        return httpx.Response(200, json={"choices": []})

    settings = Settings(
        upstream_base_url="http://fixed-upstream:8000/v1",
        upstream_model="qwen3.5-27b",
        model_aliases=frozenset({"allowed"}),
    )
    with TestClient(
        create_app(settings, transport=httpx.MockTransport(upstream))
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "allowed",
                "messages": [{"role": "user", "content": "claim"}],
                "enable_thinking": False,
            },
        )
    assert response.status_code == 200


@pytest.mark.parametrize("enable_thinking", [None, True, "false", 0])
def test_gateway_rejects_non_false_qwen_thinking(enable_thinking):
    settings = Settings(
        upstream_base_url="http://fixed-upstream:8000/v1",
        upstream_model="qwen3.5-27b",
        model_aliases=frozenset({"allowed"}),
    )
    with TestClient(
        create_app(
            settings,
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "allowed",
                "messages": [{"role": "user", "content": "claim"}],
                "enable_thinking": enable_thinking,
            },
        )
    assert response.status_code == 422


def test_gateway_rejects_mixed_provider_thinking_fields():
    settings = Settings(
        upstream_base_url="http://fixed-upstream:8000/v1",
        upstream_model="provider-model",
        model_aliases=frozenset({"allowed"}),
    )
    with TestClient(
        create_app(
            settings,
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        )
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "allowed",
                "messages": [{"role": "user", "content": "claim"}],
                "thinking": {"type": "disabled"},
                "enable_thinking": False,
            },
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    ["file:///private/gold.jsonl", "http://user:secret@host/v1", "https://host/v1?target=other"],
)
def test_gateway_settings_reject_unsafe_upstream_urls(url):
    with pytest.raises(ValueError):
        Settings(
            upstream_base_url=url,
            upstream_model="model",
            model_aliases=frozenset({"alias"}),
        )
