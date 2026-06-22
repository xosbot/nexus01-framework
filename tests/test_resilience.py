"""Tests for resilience primitives — circuit breaker, retry, timeout."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from core.resilience import CircuitBreaker, CircuitState, with_retry, with_timeout


class TestCircuitBreaker:
    def test_closed_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_open_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=999)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.can_execute()

    def test_half_open_after_recovery_timeout(self, monkeypatch):
        import time
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 0.1)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_after_success_in_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
        cb.record_failure()
        cb._last_failure_time = 0
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_record_success_in_closed_reduces_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_success()
        assert cb._failures == 0


@pytest.mark.asyncio
class TestWithRetry:
    async def test_succeeds_on_first_attempt(self):
        mock = AsyncMock(return_value="ok")
        result = await with_retry(lambda: mock(), max_attempts=3)
        assert result == "ok"
        assert mock.await_count == 1

    async def test_retries_on_failure(self):
        mock = AsyncMock(side_effect=[ValueError("fail"), "ok"])
        result = await with_retry(lambda: mock(), max_attempts=3, base_delay=0.01)
        assert result == "ok"
        assert mock.await_count == 2

    async def test_raises_after_all_retries_exhausted(self):
        mock = AsyncMock(side_effect=ValueError("persistent"))
        with pytest.raises(ValueError):
            await with_retry(lambda: mock(), max_attempts=3, base_delay=0.01)
        assert mock.await_count == 3

    async def test_respects_max_delay(self):
        mock = AsyncMock(side_effect=[ValueError("fail")] * 5)
        with pytest.raises(ValueError):
            await with_retry(lambda: mock(), max_attempts=5, base_delay=999, max_delay=0.02)
        assert mock.await_count == 5


@pytest.mark.asyncio
class TestWithTimeout:
    async def test_returns_result_before_timeout(self):
        async def fast():
            return "done"
        result = await with_timeout(fast(), timeout_seconds=5)
        assert result == "done"

    async def test_raises_on_timeout(self):
        async def slow():
            await asyncio.sleep(999)
            return "never"

        with pytest.raises(TimeoutError):
            await with_timeout(slow(), timeout_seconds=0.01)