"""
Background aggregator thread for metrics processing.

Reads ring buffer periodically, calculates percentiles, and updates statistics.
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Dict, Deque

from .event_ids import EventID
from .ring_buffer import LockFreeRingBuffer, MetricEntry, MetricType
from .stats import MetricsStats, PercentileStats

logger = logging.getLogger(__name__)


class MetricsAggregator:
    """
    Background thread for metrics aggregation and percentile calculation.

    Architecture:
    - Runs in separate daemon thread
    - Reads ring buffer every 100ms
    - Maintains sliding windows (1s, 5s, 60s)
    - Calculates percentiles using simple sorting (O(n log n))
    - Updates MetricsStats with calculated statistics

    Performance:
    - Non-blocking to hot path (separate thread)
    - Processes ~1000 entries per batch
    - Calculation overhead: ~1-5ms per batch
    """

    # Configuration
    POLL_INTERVAL_MS = 100  # Read ring buffer every 100ms
    BATCH_SIZE = 1000  # Max entries per read batch
    WINDOW_SIZES = [1, 5, 60]  # Sliding window sizes in seconds

    def __init__(self, ring_buffer: LockFreeRingBuffer, stats: MetricsStats):
        """
        Initialize metrics aggregator.

        Args:
            ring_buffer: Ring buffer to read from
            stats: MetricsStats to update with calculated statistics
        """
        self._ring_buffer = ring_buffer
        self._stats = stats

        # Sliding windows: {event_id: {window_seconds: deque of latencies}}
        self._windows: Dict[EventID, Dict[int, Deque[float]]] = defaultdict(
            lambda: {seconds: deque() for seconds in self.WINDOW_SIZES}
        )

        # Pending start timestamps: {event_id: start_timestamp}
        self._pending_starts: Dict[EventID, int] = {}

        # Thread control
        self._thread: threading.Thread = None
        self._running = False
        self._shutdown_event = threading.Event()

    def start(self) -> None:
        """Start aggregator background thread."""
        if self._running:
            logger.warning("Aggregator already running")
            return

        self._running = True
        self._shutdown_event.clear()

        self._thread = threading.Thread(target=self._run, daemon=True, name="metrics-aggregator")
        self._thread.start()
        logger.info("Metrics aggregator started")

    def stop(self, timeout: float = 2.0) -> None:
        """
        Stop aggregator background thread.

        Args:
            timeout: Maximum time to wait for thread shutdown (seconds)
        """
        if not self._running:
            return

        self._running = False
        self._shutdown_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        logger.info("Metrics aggregator stopped")

    def _run(self) -> None:
        """Background thread main loop."""
        logger.debug("Aggregator thread started")

        while self._running:
            try:
                # Read batch from ring buffer
                entries = self._ring_buffer.read_batch(self.BATCH_SIZE)

                if entries:
                    # Process entries
                    self._process_batch(entries)

                    # Calculate and update statistics
                    self._update_statistics()

                # Sleep until next poll interval
                time.sleep(self.POLL_INTERVAL_MS / 1000.0)

            except Exception as e:
                logger.error(f"Error in aggregator thread: {e}", exc_info=True)
                time.sleep(1.0)  # Back off on error

        logger.debug("Aggregator thread stopped")

    def _process_batch(self, entries: list[MetricEntry]) -> None:
        """
        Process batch of metric entries.

        Matches START/END pairs and calculates latencies.

        Args:
            entries: List of metric entries from ring buffer
        """
        for entry in entries:
            event_id = EventID(entry.event_id)

            if entry.metric_type == MetricType.START:
                # Store start timestamp
                self._pending_starts[event_id] = entry.timestamp

            elif entry.metric_type == MetricType.END:
                # Match with start timestamp
                start_ts = self._pending_starts.pop(event_id, None)
                if start_ts is None:
                    continue  # Orphaned END (start not captured)

                # Calculate latency (nanoseconds)
                latency_ns = entry.timestamp - start_ts

                # Add to sliding windows
                current_time = time.time()
                for window_seconds in self.WINDOW_SIZES:
                    window = self._windows[event_id][window_seconds]

                    # Add latency with timestamp
                    window.append((current_time, latency_ns))

                    # Remove entries outside window
                    cutoff_time = current_time - window_seconds
                    while window and window[0][0] < cutoff_time:
                        window.popleft()

    def _update_statistics(self) -> None:
        """Calculate percentiles and update MetricsStats."""
        for event_id, windows in self._windows.items():
            for window_seconds, window in windows.items():
                if not window:
                    continue

                # Extract latencies (discard timestamps)
                latencies = [latency for _, latency in window]

                # Calculate percentiles
                stats = self._calculate_percentiles(
                    event_id, window_seconds, latencies
                )

                # Update global stats
                self._stats.update_stats(event_id, window_seconds, stats)

    def _calculate_percentiles(
        self, event_id: EventID, window_seconds: int, latencies: list[float]
    ) -> PercentileStats:
        """
        Calculate percentile statistics.

        Uses simple sorting approach (O(n log n)).
        For high-frequency scenarios, could be optimized with t-digest.

        Args:
            event_id: Event identifier
            window_seconds: Time window size
            latencies: List of latency values (nanoseconds)

        Returns:
            PercentileStats with calculated values
        """
        if not latencies:
            return PercentileStats(event_id=event_id, window_seconds=window_seconds)

        # Sort for percentile calculation
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)

        # Calculate percentiles
        p50 = sorted_latencies[int(n * 0.50)]
        p95 = sorted_latencies[int(n * 0.95)]
        p99 = sorted_latencies[int(n * 0.99)]
        p99_9 = sorted_latencies[int(n * 0.999)] if n >= 1000 else sorted_latencies[-1]

        # Summary statistics
        min_latency = sorted_latencies[0]
        max_latency = sorted_latencies[-1]
        mean_latency = sum(latencies) / n

        return PercentileStats(
            event_id=event_id,
            window_seconds=window_seconds,
            p50=p50,
            p95=p95,
            p99=p99,
            p99_9=p99_9,
            count=n,
            min=min_latency,
            max=max_latency,
            mean=mean_latency,
        )
