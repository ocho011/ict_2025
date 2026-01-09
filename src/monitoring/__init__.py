"""
Performance monitoring and metrics collection.

This package provides low-overhead performance metrics collection
for real-time trading system observability.

Usage:
    # Start metrics collection
    from monitoring import MetricsCollector, EventID, measure_async

    collector = MetricsCollector()
    collector.start()  # Start background aggregation

    # Instrument code
    @measure_async(EventID.CANDLE_PROCESSING)
    async def process_candle(candle):
        # ... your code ...
        pass

    # Query statistics
    stats = collector.get_stats(EventID.CANDLE_PROCESSING, window_seconds=60)
    if stats:
        print(f"P95: {stats.p95 / 1_000_000:.2f}ms")

    # Shutdown
    collector.stop()
"""

from .aggregator import MetricsAggregator
from .event_ids import EventID
from .metrics_collector import MetricsCollector, measure, measure_async, measure_sync
from .stats import MetricsStats, PercentileStats, SLAThreshold

__all__ = [
    "MetricsCollector",
    "measure",
    "measure_async",
    "measure_sync",
    "EventID",
    "MetricsAggregator",
    "MetricsStats",
    "PercentileStats",
    "SLAThreshold",
]
