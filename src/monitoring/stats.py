"""
Performance statistics data structures and SLA threshold management.

Stores calculated percentiles and provides SLA violation detection.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from .event_ids import EventID


@dataclass(slots=True)
class PercentileStats:
    """
    Percentile statistics for a single event type.

    All latency values in nanoseconds for precision.
    """

    event_id: EventID
    window_seconds: int  # Time window size (1, 5, or 60)

    # Percentile values (nanoseconds)
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    p99_9: float = 0.0

    # Summary statistics
    count: int = 0
    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0

    # Metadata
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_id": self.event_id.name,
            "window_seconds": self.window_seconds,
            "p50_ms": self.p50 / 1_000_000,
            "p95_ms": self.p95 / 1_000_000,
            "p99_ms": self.p99 / 1_000_000,
            "p99_9_ms": self.p99_9 / 1_000_000,
            "count": self.count,
            "min_ms": self.min / 1_000_000,
            "max_ms": self.max / 1_000_000,
            "mean_ms": self.mean / 1_000_000,
            "last_updated": self.last_updated,
        }


@dataclass(slots=True)
class SLAThreshold:
    """
    SLA threshold configuration for an event type.

    Defines acceptable latency thresholds and violation detection.
    """

    event_id: EventID
    p95_threshold_ms: float  # P95 latency threshold in milliseconds
    p99_threshold_ms: float  # P99 latency threshold in milliseconds

    def check_violation(self, stats: PercentileStats) -> Optional[str]:
        """
        Check if current statistics violate SLA.

        Args:
            stats: Current percentile statistics

        Returns:
            Violation message if SLA violated, None otherwise
        """
        p95_ms = stats.p95 / 1_000_000
        p99_ms = stats.p99 / 1_000_000

        violations = []
        if p95_ms > self.p95_threshold_ms:
            violations.append(
                f"P95 {p95_ms:.2f}ms > {self.p95_threshold_ms:.2f}ms"
            )
        if p99_ms > self.p99_threshold_ms:
            violations.append(
                f"P99 {p99_ms:.2f}ms > {self.p99_threshold_ms:.2f}ms"
            )

        if violations:
            return f"{self.event_id.name}: {', '.join(violations)}"
        return None


class MetricsStats:
    """
    Container for all metrics statistics with SLA management.

    Thread-safe storage of calculated statistics and SLA thresholds.
    """

    def __init__(self):
        """Initialize metrics statistics storage."""
        # Statistics storage: {event_id: {window_seconds: PercentileStats}}
        self._stats: Dict[EventID, Dict[int, PercentileStats]] = {}

        # SLA thresholds: {event_id: SLAThreshold}
        self._sla_thresholds: Dict[EventID, SLAThreshold] = {}

        # Default SLA thresholds (can be overridden)
        self._set_default_thresholds()

    def _set_default_thresholds(self):
        """Set default SLA thresholds for common event types."""
        # Hot path operations: strict thresholds
        self._sla_thresholds[EventID.CANDLE_PROCESSING] = SLAThreshold(
            EventID.CANDLE_PROCESSING, p95_threshold_ms=50.0, p99_threshold_ms=100.0
        )
        self._sla_thresholds[EventID.SIGNAL_GENERATION] = SLAThreshold(
            EventID.SIGNAL_GENERATION, p95_threshold_ms=10.0, p99_threshold_ms=20.0
        )
        self._sla_thresholds[EventID.ORDER_PLACEMENT] = SLAThreshold(
            EventID.ORDER_PLACEMENT, p95_threshold_ms=20.0, p99_threshold_ms=50.0
        )

        # Event bus operations: moderate thresholds
        self._sla_thresholds[EventID.EVENT_BUS_PUBLISH] = SLAThreshold(
            EventID.EVENT_BUS_PUBLISH, p95_threshold_ms=5.0, p99_threshold_ms=10.0
        )
        self._sla_thresholds[EventID.EVENT_BUS_HANDLE] = SLAThreshold(
            EventID.EVENT_BUS_HANDLE, p95_threshold_ms=10.0, p99_threshold_ms=20.0
        )

    def update_stats(
        self, event_id: EventID, window_seconds: int, stats: PercentileStats
    ) -> None:
        """
        Update statistics for an event type and window.

        Args:
            event_id: Event identifier
            window_seconds: Time window size
            stats: Calculated percentile statistics
        """
        if event_id not in self._stats:
            self._stats[event_id] = {}
        self._stats[event_id][window_seconds] = stats

    def get_stats(
        self, event_id: EventID, window_seconds: int = 60
    ) -> Optional[PercentileStats]:
        """
        Get statistics for an event type and window.

        Args:
            event_id: Event identifier
            window_seconds: Time window size (default: 60s)

        Returns:
            PercentileStats if available, None otherwise
        """
        if event_id in self._stats and window_seconds in self._stats[event_id]:
            return self._stats[event_id][window_seconds]
        return None

    def get_all_stats(self, window_seconds: int = 60) -> Dict[EventID, PercentileStats]:
        """
        Get statistics for all event types in a window.

        Args:
            window_seconds: Time window size (default: 60s)

        Returns:
            Dictionary mapping EventID to PercentileStats
        """
        result = {}
        for event_id, windows in self._stats.items():
            if window_seconds in windows:
                result[event_id] = windows[window_seconds]
        return result

    def set_sla_threshold(self, threshold: SLAThreshold) -> None:
        """
        Set SLA threshold for an event type.

        Args:
            threshold: SLA threshold configuration
        """
        self._sla_thresholds[threshold.event_id] = threshold

    def check_sla_violations(self, window_seconds: int = 60) -> list[str]:
        """
        Check all event types for SLA violations.

        Args:
            window_seconds: Time window to check (default: 60s)

        Returns:
            List of violation messages
        """
        violations = []
        for event_id, threshold in self._sla_thresholds.items():
            stats = self.get_stats(event_id, window_seconds)
            if stats and stats.count > 0:
                violation = threshold.check_violation(stats)
                if violation:
                    violations.append(violation)
        return violations
