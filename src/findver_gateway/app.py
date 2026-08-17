"""A narrow, fixed-upstream OpenAI-compatible gateway."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator


LOGGER = logging.getLogger("findver_gateway")
MAX_SHARED_CONNECTIONS = 32


@dataclass(frozen=True, slots=True)
class Settings:
    upstream_base_url: str
    upstream_model: str
    model_aliases: frozenset[str]
    upstream_api_key: str | None = None
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.upstream_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("upstream base URL must be one fixed HTTP(S) origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("upstream base URL cannot contain credentials, query, or fragment")
        if not self.upstream_model:
            raise ValueError("upstream model is required")
        if not self.model_aliases or any(not alias for alias in self.model_aliases):
            raise ValueError("at least one non-empty model alias is required")
        if not 0 < self.timeout_seconds <= 600:
            raise ValueError("timeout must be between 0 and 600 seconds")

    @property
    def chat_url(self) -> str:
        return f"{self.upstream_base_url.rstrip('/')}/chat/completions"

    @classmethod
    def from_env(cls) -> "Settings":
        aliases = frozenset(
            item.strip()
            for item in os.environ["FINDVER_GATEWAY_MODEL_ALIASES"].split(",")
            if item.strip()
        )
        return cls(
            upstream_base_url=os.environ["FINDVER_GATEWAY_UPSTREAM_BASE_URL"],
            upstream_model=os.environ["FINDVER_GATEWAY_UPSTREAM_MODEL"],
            model_aliases=aliases,
            upstream_api_key=os.environ.get("FINDVER_GATEWAY_UPSTREAM_API_KEY") or None,
            timeout_seconds=float(os.environ.get("FINDVER_GATEWAY_TIMEOUT_SECONDS", "180")),
        )


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: str = Field(pattern=r"^(system|user|assistant)$")
    content: str


class Thinking(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["disabled"]


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    seed: int | None = None
    thinking: Thinking | None = None

    @model_validator(mode="before")
    @classmethod
    def explicit_thinking_cannot_be_null(cls, value: object) -> object:
        if isinstance(value, dict) and "thinking" in value and value["thinking"] is None:
            raise ValueError("thinking must be the explicit disabled structure")
        return value


def create_app(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.client = httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            transport=transport,
            limits=httpx.Limits(
                max_connections=MAX_SHARED_CONNECTIONS,
                max_keepalive_connections=MAX_SHARED_CONNECTIONS,
            ),
        )
        yield
        await application.state.client.aclose()

    application = FastAPI(
        title="FinDVer Fixed Model Gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @application.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/v1/chat/completions")
    async def chat(payload: ChatCompletionRequest, request: Request) -> Response:
        if payload.model not in settings.model_aliases:
            raise HTTPException(status_code=400, detail="model alias is not allowed")
        upstream_payload = payload.model_dump(mode="json", exclude_none=True)
        upstream_payload["model"] = settings.upstream_model
        headers = {"content-type": "application/json"}
        if settings.upstream_api_key:
            headers["authorization"] = f"Bearer {settings.upstream_api_key}"
        try:
            upstream = await request.app.state.client.post(
                settings.chat_url,
                json=upstream_payload,
                headers=headers,
            )
        except httpx.HTTPError as error:
            LOGGER.warning("fixed upstream request failed: %s", type(error).__name__)
            raise HTTPException(status_code=502, detail="fixed model upstream unavailable") from error
        if upstream.status_code >= 400:
            LOGGER.warning("fixed upstream returned HTTP status %d", upstream.status_code)
        response_headers = {}
        if "retry-after" in upstream.headers:
            response_headers["retry-after"] = upstream.headers["retry-after"]
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type="application/json",
            headers=response_headers,
        )

    return application


def app_factory() -> FastAPI:
    return create_app(Settings.from_env())
