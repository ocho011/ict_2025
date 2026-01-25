"""
Circuit breaker pattern for API resilience.

This module implements a circuit breaker that prevents cascading failures
by temporarily stopping requests to failing services after repeated failures.
"""

import time
from typing import Any, Callable


class CircuitBreaker:
    """
    Circuit breaker that prevents repeated calls to failing services.

    The circuit breaker has three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Requests are blocked, failure threshold exceeded
    - HALF_OPEN: Limited requests allowed to test recovery

    States transition:
    CLOSED -> OPEN (when failure threshold reached)
    OPEN -> HALF_OPEN (after recovery timeout)
    HALF_OPEN -> CLOSED (on success) or OPEN (on failure)
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

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            OrderExecutionError: When circuit is OPEN
        """
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                from src.execution.exceptions import OrderExecutionError

                raise OrderExecutionError(
                    f"Circuit breaker OPEN for {func.__name__}. "
                    f"Recovery in {self.recovery_timeout - (time.time() - self.last_failure_time):.1f}s"
                )

        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.reset()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = None

    def get_state(self) -> str:
        """Get current circuit breaker state."""
        return self.state

    def get_failure_count(self) -> int:
        """Get current failure count."""
        return self.failure_count
