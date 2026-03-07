#!/usr/bin/env python3
"""
Performance benchmark for metrics collection system.

Validates <1% overhead target by measuring:
1. Ring buffer write latency
2. MetricsCollector record overhead
3. Decorator overhead on hot path functions
4. System throughput impact

Usage:
    python scripts/benchmark_metrics.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from monitoring import EventID, MetricsCollector, measure, measure_async
from monitoring.ring_buffer import LockFreeRingBuffer, MetricType


def benchmark_ring_buffer():
    """Benchmark ring buffer write performance."""
    print("=" * 60)
    print("1. Ring Buffer Write Performance")
    print("=" * 60)

    buffer = LockFreeRingBuffer()
    iterations = 100_000

    # Warm up
    for i in range(1000):
        buffer.record(time.perf_counter_ns(), 1, MetricType.START)

    # Benchmark
    start = time.perf_counter_ns()
    for i in range(iterations):
        buffer.record(time.perf_counter_ns(), 1, MetricType.START)
    end = time.perf_counter_ns()

    total_ns = end - start
    avg_ns = total_ns / iterations

    print(f"Iterations: {iterations:,}")
    print(f"Total time: {total_ns / 1_000_000:.2f}ms")
    print(f"Average write: {avg_ns:.0f}ns")
    print(f"Target: <100ns per write")
    print(f"Status: {'✅ PASS' if avg_ns < 100 else '❌ FAIL'}")
    print()

    return avg_ns < 100


def benchmark_metrics_collector():
    """Benchmark MetricsCollector overhead."""
    print("=" * 60)
    print("2. MetricsCollector Record Performance")
    print("=" * 60)

    collector = MetricsCollector()
    iterations = 100_000

    # Warm up
    for i in range(1000):
        start_ts = collector.record_start(EventID.CANDLE_PROCESSING)
        collector.record_end(EventID.CANDLE_PROCESSING, start_ts)

    # Benchmark
    start = time.perf_counter_ns()
    for i in range(iterations):
        start_ts = collector.record_start(EventID.CANDLE_PROCESSING)
        collector.record_end(EventID.CANDLE_PROCESSING, start_ts)
    end = time.perf_counter_ns()

    total_ns = end - start
    avg_ns = total_ns / iterations

    print(f"Iterations: {iterations:,}")
    print(f"Total time: {total_ns / 1_000_000:.2f}ms")
    print(f"Average record (start+end): {avg_ns:.0f}ns")
    print(f"Target: <300ns per measurement")
    print(f"Status: {'✅ PASS' if avg_ns < 300 else '❌ FAIL'}")
    print()

    return avg_ns < 300


async def benchmark_async_decorator():
    """Benchmark async decorator overhead."""
    print("=" * 60)
    print("3. Async Decorator Performance")
    print("=" * 60)

    # Baseline: undecorated function
    async def baseline_function():
        await asyncio.sleep(0)  # Simulate minimal async work

    # Decorated function
    @measure_async(EventID.CANDLE_PROCESSING)
    async def decorated_function():
        await asyncio.sleep(0)  # Same work as baseline

    iterations = 10_000

    # Warm up
    for _ in range(100):
        await baseline_function()
        await decorated_function()

    # Benchmark baseline
    start = time.perf_counter_ns()
    for _ in range(iterations):
        await baseline_function()
    end = time.perf_counter_ns()
    baseline_ns = (end - start) / iterations

    # Benchmark decorated
    start = time.perf_counter_ns()
    for _ in range(iterations):
        await decorated_function()
    end = time.perf_counter_ns()
    decorated_ns = (end - start) / iterations

    overhead_ns = decorated_ns - baseline_ns
    overhead_pct = (overhead_ns / decorated_ns) * 100 if decorated_ns > 0 else 0

    print(f"Iterations: {iterations:,}")
    print(f"Baseline: {baseline_ns:.0f}ns per call")
    print(f"Decorated: {decorated_ns:.0f}ns per call")
    print(f"Overhead: {overhead_ns:.0f}ns ({overhead_pct:.3f}%)")
    print(f"Target: <500ns overhead")
    print(f"Status: {'✅ PASS' if overhead_ns < 500 else '❌ FAIL'}")
    print()

    return overhead_ns < 500


def benchmark_context_manager():
    """Benchmark context manager overhead."""
    print("=" * 60)
    print("4. Context Manager Performance")
    print("=" * 60)

    iterations = 100_000

    # Warm up
    for _ in range(1000):
        with measure(EventID.SIGNAL_GENERATION):
            pass

    # Benchmark
    start = time.perf_counter_ns()
    for _ in range(iterations):
        with measure(EventID.SIGNAL_GENERATION):
            pass
    end = time.perf_counter_ns()

    total_ns = end - start
    avg_ns = total_ns / iterations

    print(f"Iterations: {iterations:,}")
    print(f"Total time: {total_ns / 1_000_000:.2f}ms")
    print(f"Average overhead: {avg_ns:.0f}ns")
    print(f"Target: <300ns per measurement")
    print(f"Status: {'✅ PASS' if avg_ns < 300 else '❌ FAIL'}")
    print()

    return avg_ns < 300


def benchmark_realistic_scenario():
    """Benchmark realistic candle processing scenario."""
    print("=" * 60)
    print("5. Realistic Scenario: Candle Processing")
    print("=" * 60)

    collector = MetricsCollector()

    # Simulate realistic candle processing function
    def process_candle_baseline():
        """Baseline: no measurement."""
        # Simulate 10ms processing
        time.sleep(0.010)

    def process_candle_instrumented():
        """Instrumented: with measurement."""
        start_ts = collector.record_start(EventID.CANDLE_PROCESSING)
        try:
            # Simulate 10ms processing
            time.sleep(0.010)
        finally:
            collector.record_end(EventID.CANDLE_PROCESSING, start_ts)

    iterations = 100

    # Benchmark baseline
    start = time.perf_counter()
    for _ in range(iterations):
        process_candle_baseline()
    end = time.perf_counter()
    baseline_s = (end - start) / iterations

    # Benchmark instrumented
    start = time.perf_counter()
    for _ in range(iterations):
        process_candle_instrumented()
    end = time.perf_counter()
    instrumented_s = (end - start) / iterations

    overhead_us = (instrumented_s - baseline_s) * 1_000_000
    overhead_pct = (overhead_us / (baseline_s * 1_000_000)) * 100

    print(f"Iterations: {iterations}")
    print(f"Baseline: {baseline_s * 1000:.3f}ms per call")
    print(f"Instrumented: {instrumented_s * 1000:.3f}ms per call")
    print(f"Overhead: {overhead_us:.1f}μs ({overhead_pct:.4f}%)")
    print(f"Target: <1% overhead")
    print(f"Status: {'✅ PASS' if overhead_pct < 1.0 else '❌ FAIL'}")
    print()

    return overhead_pct < 1.0


async def benchmark_aggregation_layer():
    """Benchmark aggregation layer functionality."""
    print("=" * 60)
    print("6. Aggregation Layer: End-to-End Test")
    print("=" * 60)

    collector = MetricsCollector()

    # Start aggregator
    collector.start()
    print("Aggregator started, waiting for initialization...")
    await asyncio.sleep(1.0)  # Increased from 0.5s to 1.0s

    # Generate test data
    @measure_async(EventID.CANDLE_PROCESSING)
    async def test_function():
        await asyncio.sleep(0.010)  # 10ms

    iterations = 50
    print(f"Generating {iterations} test events...")

    for _ in range(iterations):
        await test_function()
        await asyncio.sleep(0.05)  # 50ms between events

    # Wait for aggregation
    print("Waiting for aggregation...")
    await asyncio.sleep(2.0)  # Increased from 1.0s to 2.0s

    # Verify statistics are available
    stats = collector.get_stats(EventID.CANDLE_PROCESSING, window_seconds=60)

    if stats is None:
        print("Status: ❌ FAIL - No statistics available")
        collector.stop()
        return False

    print(f"Statistics collected:")
    print(f"  Count:  {stats.count}")
    print(f"  P50:    {stats.p50 / 1_000_000:.2f}ms")
    print(f"  P95:    {stats.p95 / 1_000_000:.2f}ms")
    print(f"  P99:    {stats.p99 / 1_000_000:.2f}ms")
    print(f"  Mean:   {stats.mean / 1_000_000:.2f}ms")

    # Verify reasonable values (10ms ± some overhead)
    expected_min_ms = 8.0
    expected_max_ms = 15.0
    p50_ms = stats.p50 / 1_000_000

    passed = expected_min_ms <= p50_ms <= expected_max_ms and stats.count >= iterations

    print(f"Target: {expected_min_ms:.1f}ms ≤ P50 ≤ {expected_max_ms:.1f}ms, Count ≥ {iterations}")
    print(f"Status: {'✅ PASS' if passed else '❌ FAIL'}")

    # Cleanup
    collector.stop()
    print()

    return passed


async def main():
    """Run all benchmarks."""
    print()
    print("🚀 Performance Metrics Benchmark Suite")
    print()

    results = []

    # Run benchmarks
    # IMPORTANT: Aggregation layer test MUST run first because MetricsCollector is a singleton
    results.append(("Aggregation Layer", await benchmark_aggregation_layer()))
    results.append(("Ring Buffer Write", benchmark_ring_buffer()))
    results.append(("MetricsCollector Record", benchmark_metrics_collector()))
    results.append(("Async Decorator", await benchmark_async_decorator()))
    results.append(("Context Manager", benchmark_context_manager()))
    results.append(("Realistic Scenario", benchmark_realistic_scenario()))

    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)

    all_pass = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{name:30} {status}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("✅ All benchmarks PASSED - <1% overhead target achieved!")
    else:
        print("❌ Some benchmarks FAILED - overhead exceeds 1% target")

    return 0 if all_pass else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
