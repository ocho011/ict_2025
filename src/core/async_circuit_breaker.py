"""
Async Circuit breaker pattern for API resilience.
"""

import asyncio
import time
from typing import Any, Callable, Awaitable


class AsyncCircuitBreaker:
    """
    Async circuit breaker that prevents repeated calls to failing services.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"
        self._lock = asyncio.Lock()

    async def call(self, func: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        """
        Execute async function through circuit breaker.
        """
        async with self._lock:
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.logger.info("Circuit breaker HALF_OPEN - testing recovery")
                else:
                    from src.core.exceptions import OrderExecutionError
                    func_name = getattr(func, "__name__", str(func))
                    raise OrderExecutionError(
                        f"Circuit breaker OPEN for {func_name}. "
                        f"Recovery in {self.recovery_timeout - (time.time() - self.last_failure_time):.1f}s"
                    )

        try:
            result = await func(*args, **kwargs)
            
            async with self._lock:
                if self.state == "HALF_OPEN":
                    self.reset()
                    self.logger.info("Circuit breaker CLOSED - recovered successfully")
            return result
            
        except Exception as e:
            async with self._lock:
                self.record_failure()
            raise

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            if self.state != "OPEN":
                # self.logger.warning(f"Circuit breaker OPEN after {self.failure_count} failures")
                pass
            self.state = "OPEN"

    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = None
