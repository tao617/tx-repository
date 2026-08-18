"""Closed request builders for supported OpenAI-compatible API dialects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


CanonicalTransportProfile: TypeAlias = Literal[
    "openai_standard",
    "deepseek_openai_chat",
    "dashscope_openai_chat",
]
TransportProfile: TypeAlias = Literal[
    "openai_standard",
    "deepseek_openai_chat",
    "dashscope_openai_chat",
    # Frozen compatibility names used by historical configs and plans.
    "generic_openai",
    "deepseek_v4_openai",
]
ThinkingMode: TypeAlias = Literal["disabled", "unsupported"]

_COMPATIBILITY_ALIASES: dict[str, CanonicalTransportProfile] = {
    "generic_openai": "openai_standard",
    "deepseek_v4_openai": "deepseek_openai_chat",
}
_COMMON_REQUEST_FIELDS = frozenset(
    {"model", "messages", "temperature", "top_p", "max_tokens", "seed"}
)


@dataclass(frozen=True)
class TransportAdapter:
    """One immutable API-dialect adapter with a fixed provider-field whitelist."""

    profile: CanonicalTransportProfile
    thinking_mode: ThinkingMode
    provider_fields: tuple[str, ...] = ()

    @property
    def allowed_request_fields(self) -> frozenset[str]:
        return _COMMON_REQUEST_FIELDS | set(self.provider_fields)

    def build_request(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        top_p: float,
        max_tokens: int,
        seed: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            payload["seed"] = seed
        if self.profile == "deepseek_openai_chat":
            payload["thinking"] = {"type": "disabled"}
        elif self.profile == "dashscope_openai_chat":
            payload["enable_thinking"] = False
        if not payload.keys() <= self.allowed_request_fields:  # pragma: no cover
            raise RuntimeError("transport adapter produced a non-whitelisted field")
        return payload


_ADAPTERS: dict[CanonicalTransportProfile, TransportAdapter] = {
    "openai_standard": TransportAdapter(
        profile="openai_standard",
        thinking_mode="unsupported",
    ),
    "deepseek_openai_chat": TransportAdapter(
        profile="deepseek_openai_chat",
        thinking_mode="disabled",
        provider_fields=("thinking",),
    ),
    "dashscope_openai_chat": TransportAdapter(
        profile="dashscope_openai_chat",
        thinking_mode="disabled",
        provider_fields=("enable_thinking",),
    ),
}


def canonical_transport_profile(profile: str) -> CanonicalTransportProfile:
    canonical = _COMPATIBILITY_ALIASES.get(profile, profile)
    if canonical not in _ADAPTERS:
        raise ValueError("unsupported transport profile")
    return canonical  # type: ignore[return-value]


def get_transport_adapter(profile: str) -> TransportAdapter:
    return _ADAPTERS[canonical_transport_profile(profile)]


def validate_transport_thinking(profile: str, thinking_mode: ThinkingMode) -> None:
    adapter = get_transport_adapter(profile)
    if thinking_mode != adapter.thinking_mode:
        raise ValueError(
            f"{adapter.profile} requires thinking_mode={adapter.thinking_mode}"
        )
