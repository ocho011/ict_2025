#!/usr/bin/env python3
"""
Example of metrics collection system usage with periodic reporting.

Demonstrates:
1. Starting metrics collection
2. Instrumenting code with decorators
3. Periodic statistics reporting
4. SLA violation detection
5. Graceful shutdown

Usage:
    python scripts/example_metrics_usage.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from monitoring import EventID, MetricsCollector, measure_async


async def simulate_candle_processing():
    """Simulate candle processing with varying latencies."""

    @measure_async(EventID.CANDLE_PROCESSING)
    async def process_candle(processing_time_ms: float):
        await asyncio.sleep(processing_time_ms / 1000.0)

    # Simulate various processing times
    times_ms = [10, 12, 15, 20, 25, 30, 40, 50, 100]  # ms

    for i, time_ms in enumerate(times_ms * 10):  # Repeat for more data
        await process_candle(time_ms)
        await asyncio.sleep(0.1)  # 100ms between candles


async def simulate_signal_generation():
    """Simulate signal generation with varying latencies."""

    @measure_async(EventID.SIGNAL_GENERATION)
    async def generate_signal(processing_time_ms: float):
        await asyncio.sleep(processing_time_ms / 1000.0)

    times_ms = [2, 3, 5, 7, 10, 15]  # ms

    for time_ms in times_ms * 15:  # Repeat for more data
        await generate_signal(time_ms)
        await asyncio.sleep(0.05)  # 50ms between signals


async def print_periodic_stats(collector: MetricsCollector, interval_seconds: int = 5):
    """Print statistics periodically."""
    print("\n" + "=" * 80)
    print("PERIODIC METRICS REPORT")
    print("=" * 80)

    while True:
        await asyncio.sleep(interval_seconds)

        print(f"\n📊 Stats Report @ {time.strftime('%H:%M:%S')}")
        print("-" * 80)

        # Get all statistics
        all_stats = collector.get_all_stats(window_seconds=60)

        if not all_stats:
            print("  No data collected yet...")
            continue

        # Print statistics for each event type
        for event_id, stats in all_stats.items():
            print(f"\n  {event_id.name}:")
            print(f"    Count:  {stats.count}")
            print(f"    P50:    {stats.p50 / 1_000_000:6.2f}ms")
            print(f"    P95:    {stats.p95 / 1_000_000:6.2f}ms")
            print(f"    P99:    {stats.p99 / 1_000_000:6.2f}ms")
            print(f"    P99.9:  {stats.p99_9 / 1_000_000:6.2f}ms")
            print(f"    Mean:   {stats.mean / 1_000_000:6.2f}ms")
            print(f"    Min:    {stats.min / 1_000_000:6.2f}ms")
            print(f"    Max:    {stats.max / 1_000_000:6.2f}ms")

        # Check SLA violations
        violations = collector.check_sla_violations(window_seconds=60)
        if violations:
            print("\n  ⚠️  SLA VIOLATIONS DETECTED:")
            for violation in violations:
                print(f"    - {violation}")
        else:
            print("\n  ✅ All SLAs met")

        print("-" * 80)


async def main():
    """Main example execution."""
    print("=" * 80)
    print("METRICS COLLECTION SYSTEM - EXAMPLE USAGE")
    print("=" * 80)

    # 1. Initialize metrics collector
    collector = MetricsCollector()

    # 2. Start background aggregation
    print("\n1. Starting metrics collection...")
    collector.start()
    print("   ✅ Aggregator thread started")

    # 3. Wait for aggregator to initialize
    await asyncio.sleep(0.5)

    # 4. Start periodic reporting
    print("\n2. Starting periodic reporting (every 5 seconds)...")
    reporting_task = asyncio.create_task(print_periodic_stats(collector, interval_seconds=5))

    # 5. Simulate workload
    print("\n3. Simulating trading system workload...")
    print("   - Candle processing (varying latencies)")
    print("   - Signal generation (varying latencies)")
    print("\n   Press Ctrl+C to stop...\n")

    try:
        # Run simulations concurrently
        await asyncio.gather(
            simulate_candle_processing(),
            simulate_signal_generation(),
        )

    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping...")

    finally:
        # 6. Stop reporting
        reporting_task.cancel()
        try:
            await reporting_task
        except asyncio.CancelledError:
            pass

        # 7. Print final statistics
        print("\n" + "=" * 80)
        print("FINAL STATISTICS")
        print("=" * 80)

        all_stats = collector.get_all_stats(window_seconds=60)
        for event_id, stats in all_stats.items():
            print(f"\n{event_id.name}:")
            print(f"  Total events: {stats.count}")
            print(f"  P50: {stats.p50 / 1_000_000:.2f}ms")
            print(f"  P95: {stats.p95 / 1_000_000:.2f}ms")
            print(f"  P99: {stats.p99 / 1_000_000:.2f}ms")

        # 8. Stop metrics collection
        print("\n" + "=" * 80)
        print("Shutting down metrics collection...")
        collector.stop(timeout=2.0)
        print("✅ Shutdown complete")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
