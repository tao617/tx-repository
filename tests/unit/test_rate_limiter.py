import pytest

from findver_agent.model_backends.rate_limiter import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_rate_limiter_queues_until_token_window_expires():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        requests_per_minute=10,
        tokens_per_minute=100,
        clock=clock,
        sleep=clock.sleep,
    )

    assert await limiter.acquire(40) == 0
    assert await limiter.acquire(40) == 0
    assert await limiter.acquire(40) == 60_000
    assert clock.now == 60.0


@pytest.mark.asyncio
async def test_rate_limiter_queues_until_request_window_expires():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(
        requests_per_minute=2,
        tokens_per_minute=10_000,
        clock=clock,
        sleep=clock.sleep,
    )

    assert await limiter.acquire(1) == 0
    assert await limiter.acquire(1) == 0
    assert await limiter.acquire(1) == 60_000


@pytest.mark.asyncio
async def test_rate_limiter_rejects_one_request_larger_than_tpm_limit():
    limiter = SlidingWindowRateLimiter(
        requests_per_minute=1,
        tokens_per_minute=10,
    )
    with pytest.raises(ValueError, match="exceeds"):
        await limiter.acquire(11)
