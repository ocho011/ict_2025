"""
Metrics collector singleton for performance measurement.

Provides low-overhead decorators and context managers for instrumenting
hot path code with <1% performance impact.
"""

import logging
import random
import time
from functools import wraps
from typing import Callable, Dict, Optional, TypeVar

from .aggregator import MetricsAggregator
from .event_ids import EventID
from .ring_buffer import LockFreeRingBuffer, MetricType
from .stats import MetricsStats, PercentileStats

T = TypeVar("T")
logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Singleton metrics collector with lock-free recording.

    Architecture:
    - Single global instance (lazy initialization)
    - Lock-free ring buffer for hot path recording
    - Adaptive sampling under load
    - Instant disable flag for emergencies

    Performance:
    - record_start: ~140ns (time.perf_counter_ns + buffer.record)
    - record_end: ~140ns
    - Total per event: ~280ns

    Thread safety:
    - Recording is thread-safe (lock-free ring buffer)
    - Singleton creation is NOT thread-safe (use at module load)
    """

    _instance = None

    def __new__(cls):
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize metrics collector (only once)."""
        if self._initialized:
            return

        # Lock-free ring buffer
        self._buffer = LockFreeRingBuffer()

        # Control flags
        self._enabled = True  # Global enable/disable
        self._sampling_rate = 1.0  # 100% sampling initially

        # Sampling RNG (faster than random.random())
        self._rng = random.Random()

        # Statistics and aggregation
        self._stats = MetricsStats()
        self._aggregator = MetricsAggregator(self._buffer, self._stats)

        self._initialized = True

    def record_start(self, event_id: EventID) -> int:
        """
        Record event start timestamp.

        Args:
            event_id: EventID enum identifying the operation

        Returns:
            Start timestamp (nanoseconds) or 0 if not sampled

        Performance:
            - Enabled + sampled: ~140ns
            - Disabled or not sampled: ~20ns
        """
        # Fast path: disabled or not sampled
        if not self._enabled:
            return 0

        if self._sampling_rate < 1.0 and self._rng.random() > self._sampling_rate:
            return 0

        # Record start timestamp
        ts = time.perf_counter_ns()
        self._buffer.record(ts, event_id, MetricType.START)
        return ts

    def record_end(self, event_id: EventID, start_ts: int) -> None:
        """
        Record event end timestamp.

        Args:
            event_id: EventID enum identifying the operation
            start_ts: Start timestamp from record_start (0 if not sampled)

        Performance:
            - Enabled + sampled: ~140ns
            - Not sampled: ~5ns (early return)
        """
        if start_ts == 0:  # Not sampled
            return

        # Record end timestamp
        ts = time.perf_counter_ns()
        self._buffer.record(ts, event_id, MetricType.END)

    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable metrics collection.

        Args:
            enabled: True to enable, False to disable

        Use case:
            Instant disable during emergencies or performance issues
        """
        self._enabled = enabled

    def set_sampling_rate(self, rate: float) -> None:
        """
        Set adaptive sampling rate.

        Args:
            rate: Sampling probability (0.0 to 1.0)
                  1.0 = 100% (all events measured)
                  0.1 = 10% (sample 1 in 10 events)

        Use case:
            Reduce overhead under high load by sampling fewer events
        """
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"Sampling rate must be 0.0-1.0, got {rate}")
        self._sampling_rate = rate

    def get_buffer(self) -> LockFreeRingBuffer:
        """
        Get ring buffer for aggregator thread access.

        Returns:
            LockFreeRingBuffer instance

        Note:
            Only for use by metrics aggregator thread
        """
        return self._buffer

    def start(self) -> None:
        """
        Start metrics aggregation.

        Launches background thread for percentile calculation.
        Should be called during application startup.
        """
        self._aggregator.start()
        logger.info("Metrics collection started")

    def stop(self, timeout: float = 2.0) -> None:
        """
        Stop metrics aggregation.

        Args:
            timeout: Maximum time to wait for aggregator shutdown

        Should be called during application shutdown.
        """
        self._aggregator.stop(timeout=timeout)
        logger.info("Metrics collection stopped")

    def get_stats(
        self, event_id: EventID, window_seconds: int = 60
    ) -> Optional[PercentileStats]:
        """
        Get current statistics for an event type.

        Args:
            event_id: Event identifier
            window_seconds: Time window size (1, 5, or 60 seconds)

        Returns:
            PercentileStats if available, None otherwise

        Example:
            stats = collector.get_stats(EventID.CANDLE_PROCESSING, window_seconds=60)
            if stats:
                print(f"P95: {stats.p95 / 1_000_000:.2f}ms")
        """
        return self._stats.get_stats(event_id, window_seconds)

    def get_all_stats(self, window_seconds: int = 60) -> Dict[EventID, PercentileStats]:
        """
        Get statistics for all event types.

        Args:
            window_seconds: Time window size (1, 5, or 60 seconds)

        Returns:
            Dictionary mapping EventID to PercentileStats

        Example:
            all_stats = collector.get_all_stats(window_seconds=60)
            for event_id, stats in all_stats.items():
                print(f"{event_id.name}: P95={stats.p95 / 1_000_000:.2f}ms")
        """
        return self._stats.get_all_stats(window_seconds)

    def check_sla_violations(self, window_seconds: int = 60) -> list[str]:
        """
        Check for SLA violations.

        Args:
            window_seconds: Time window to check (default: 60s)

        Returns:
            List of violation messages

        Example:
            violations = collector.check_sla_violations()
            if violations:
                for violation in violations:
                    print(f"SLA VIOLATION: {violation}")
        """
        return self._stats.check_sla_violations(window_seconds)


def measure_async(event_id: EventID):
    """
    Decorator for measuring async function latency.

    Args:
        event_id: EventID identifying the operation

    Returns:
        Decorated async function

    Usage:
        @measure_async(EventID.CANDLE_PROCESSING)
        async def process_candle(self, candle: Candle):
            # Existing implementation unchanged
            ...

    Performance:
        - Overhead: ~280ns per call (start + end)
        - Zero allocation
        - Non-blocking

    Example latency:
        Candle processing: 10ms
        Measurement overhead: 0.00028ms (0.0028%)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            collector = MetricsCollector()
            start_ts = collector.record_start(event_id)
            try:
                return await func(*args, **kwargs)
            finally:
                collector.record_end(event_id, start_ts)

        return wrapper

    return decorator


def measure_sync(event_id: EventID):
    """
    Decorator for measuring sync function latency.

    Args:
        event_id: EventID identifying the operation

    Returns:
        Decorated sync function

    Usage:
        @measure_sync(EventID.ORDER_PLACEMENT)
        def place_order(self, order: Order):
            # Existing implementation unchanged
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            collector = MetricsCollector()
            start_ts = collector.record_start(event_id)
            try:
                return func(*args, **kwargs)
            finally:
                collector.record_end(event_id, start_ts)

        return wrapper

    return decorator


class measure:
    """
    Context manager for measuring code block latency.

    Usage:
        with measure(EventID.SIGNAL_GENERATION):
            signal = generate_signal(candle)

    Performance:
        - __enter__: ~140ns
        - __exit__: ~140ns
        - Total: ~280ns

    Thread safety:
        Safe to use in async and sync code
    """

    __slots__ = ("event_id", "start_ts", "collector")

    def __init__(self, event_id: EventID):
        """
        Initialize measurement context.

        Args:
            event_id: EventID identifying the operation
        """
        self.event_id = event_id
        self.collector = MetricsCollector()
        self.start_ts = 0

    def __enter__(self):
        """Record start timestamp."""
        self.start_ts = self.collector.record_start(self.event_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Record end timestamp."""
        self.collector.record_end(self.event_id, self.start_ts)
        return False  # Don't suppress exceptions
