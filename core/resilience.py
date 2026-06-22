"""Resilience primitives — circuit breaker, retry with backoff, timeout."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    name: str = "default"

    _failures: int = field(default=0, init=False)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("[circuit_breaker] %s transitioning to HALF_OPEN", self.name)
        return self._state

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._failures = 0
                self._state = CircuitState.CLOSED
                logger.info("[circuit_breaker] %s CLOSED after recovery", self.name)
        elif self._state == CircuitState.CLOSED:
            self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("[circuit_breaker] %s OPEN after half_open failure", self.name)
        elif self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning("[circuit_breaker] %s OPEN after %d failures", self.name, self._failures)

    def can_execute(self) -> bool:
        return self.state != CircuitState.OPEN


async def with_retry(
    factory,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
):
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            coro = factory() if callable(factory) else factory
            return await coro
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            delay = min(base_delay * (exponential_base ** attempt), max_delay)
            logger.warning(
                "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                attempt + 1, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc


async def with_timeout(coro, timeout_seconds: float, task_name: str = "task"):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{task_name} timed out after {timeout_seconds}s") from None