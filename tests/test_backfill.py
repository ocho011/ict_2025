#!/usr/bin/env python3
"""Test script to verify backfilling functionality."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from src.main import TradingBot

async def main():
    """Test backfilling during bot initialization."""
    print("=" * 80)
    print("🧪 Backfilling Functionality Test")
    print("=" * 80)
    print("\nObjective: Verify historical candles are loaded at startup")
    print("Expected behavior:")
    print("  1. ConfigManager loads backfill_limit from config (100)")
    print("  2. DataCollector created")
    print("  3. Backfill executes for all symbol/interval pairs")
    print("  4. Logs show candle counts per pair")
    print("  5. Buffers populated before WebSocket starts")
    print("\nStarting test...\n")
    print("=" * 80)

    try:
        # Create bot (triggers initialize())
        bot = TradingBot()

        # Initialize (this should trigger backfilling)
        print("\n🔄 Calling bot.initialize()...\n")
        await bot.initialize()

        # Check buffer contents
        print("\n" + "=" * 80)
        print("📊 Verifying Buffer Contents")
        print("=" * 80)

        for symbol, strategy in bot.trading_engine.strategies.items():
            for interval, buffer in strategy.buffers.items():
                print(f"\n{symbol} {interval}:")
                print(f"  Buffer size: {len(buffer)} candles")

                if len(buffer) > 0:
                    print(f"  Oldest: {buffer[0].open_time.isoformat()}")
                    print(f"  Newest: {buffer[-1].open_time.isoformat()}")
                    print(f"  Price range: {buffer[0].close:.2f} - {buffer[-1].close:.2f}")
                    print(f"  ✅ Backfill successful")
                else:
                    print(f"  ❌ Buffer empty - backfill failed")

        print("\n" + "=" * 80)
        print("✅ Backfilling test completed")
        print("=" * 80)

        return True

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
