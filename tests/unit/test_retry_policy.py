import httpx
import pytest

from findver_agent.model_backends.retry_policy import retry_async


@pytest.mark.asyncio
async def test_timeout_is_retried_with_a_strict_bound() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout("builder timeout")
        return "ok"

    result = await retry_async(
        operation,
        max_retries=2,
        retryable=lambda error: isinstance(error, httpx.TimeoutException),
        base_delay_seconds=0,
    )
    assert result == "ok"
    assert attempts == 3


@pytest.mark.asyncio
async def test_non_retryable_error_is_not_repeated() -> None:
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError, match="not retryable"):
        await retry_async(
            operation,
            max_retries=5,
            retryable=lambda error: isinstance(error, httpx.TimeoutException),
            base_delay_seconds=0,
        )
    assert attempts == 1
