"""Bounded deterministic retry helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    retryable: Callable[[BaseException], bool],
    base_delay_seconds: float = 0.25,
) -> T:
    attempt = 0
    while True:
        try:
            return await operation()
        except BaseException as error:
            if attempt >= max_retries or not retryable(error):
                raise
            await asyncio.sleep(min(base_delay_seconds * (2**attempt), 4.0))
            attempt += 1

