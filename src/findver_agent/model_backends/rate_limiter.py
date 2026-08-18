"""Deterministic sliding-window admission control for provider API quotas."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class SlidingWindowRateLimiter:
    """Share one RPM/TPM budget across all concurrent question workers."""

    def __init__(
        self,
        *,
        requests_per_minute: int,
        tokens_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if requests_per_minute < 1 or tokens_per_minute < 1:
            raise ValueError("rate limits must be positive")
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self._clock = clock
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()
        self._token_total = 0
        self._lock = asyncio.Lock()

    def _purge(self, now: float) -> None:
        cutoff = now - 60.0
        while self._events and self._events[0][0] <= cutoff:
            _, tokens = self._events.popleft()
            self._token_total -= tokens

    def _required_wait(self, now: float, reserved_tokens: int) -> float:
        waits = [0.0]
        if len(self._events) >= self.requests_per_minute:
            request_event = self._events[
                len(self._events) - self.requests_per_minute
            ]
            waits.append(request_event[0] + 60.0 - now)
        excess = self._token_total + reserved_tokens - self.tokens_per_minute
        if excess > 0:
            removed = 0
            for timestamp, tokens in self._events:
                removed += tokens
                if removed >= excess:
                    waits.append(timestamp + 60.0 - now)
                    break
        return max(0.0, *waits)

    async def acquire(self, reserved_tokens: int) -> float:
        """Reserve one request and return aggregate queue wait in milliseconds."""

        if reserved_tokens < 1:
            raise ValueError("reserved_tokens must be positive")
        if reserved_tokens > self.tokens_per_minute:
            raise ValueError("one request exceeds the configured TPM admission limit")
        waited_seconds = 0.0
        while True:
            async with self._lock:
                now = self._clock()
                self._purge(now)
                wait_seconds = self._required_wait(now, reserved_tokens)
                if wait_seconds <= 0:
                    self._events.append((now, reserved_tokens))
                    self._token_total += reserved_tokens
                    return waited_seconds * 1000.0
            await self._sleep(wait_seconds)
            waited_seconds += wait_seconds
