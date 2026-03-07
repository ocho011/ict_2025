#!/usr/bin/env python3
"""Debug aggregator to see what's happening."""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Enable debug logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from monitoring import EventID, MetricsCollector, measure_async


async def main():
    """Debug aggregator functionality."""
    print("=" * 80)
    print("AGGREGATOR DEBUG TEST")
    print("=" * 80)

    collector = MetricsCollector()

    # Start aggregator
    print("\n1. Starting aggregator...")
    collector.start()

    # Wait longer
    print("2. Waiting 2 seconds for initialization...")
    await asyncio.sleep(2.0)

    # Generate test events
    @measure_async(EventID.CANDLE_PROCESSING)
    async def test_function():
        await asyncio.sleep(0.010)  # 10ms

    print("\n3. Generating 10 test events...")
    for i in range(10):
        await test_function()
        print(f"   Event {i+1} completed")
        await asyncio.sleep(0.1)  # 100ms between events

    # Wait for aggregation with multiple checks
    print("\n4. Waiting for aggregation (checking every second)...")
    for i in range(5):
        await asyncio.sleep(1.0)
        stats = collector.get_stats(EventID.CANDLE_PROCESSING, window_seconds=60)
        print(f"   Check {i+1}: stats={'available' if stats else 'None'}")
        if stats:
            print(f"     Count: {stats.count}, P50: {stats.p50 / 1_000_000:.2f}ms")

    # Final check
    print("\n5. Final statistics check:")
    stats = collector.get_stats(EventID.CANDLE_PROCESSING, window_seconds=60)
    if stats:
        print(f"   ✅ Statistics available!")
        print(f"   Count:  {stats.count}")
        print(f"   P50:    {stats.p50 / 1_000_000:.2f}ms")
        print(f"   P95:    {stats.p95 / 1_000_000:.2f}ms")
        print(f"   Mean:   {stats.mean / 1_000_000:.2f}ms")
    else:
        print("   ❌ No statistics available")

        # Check ring buffer
        buffer = collector.get_buffer()
        available = buffer.get_available_count()
        print(f"   Ring buffer available entries: {available}")

    # Stop
    print("\n6. Stopping aggregator...")
    collector.stop()
    print("   ✅ Stopped")


if __name__ == "__main__":
    asyncio.run(main())
