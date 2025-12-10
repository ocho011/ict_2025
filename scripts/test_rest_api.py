#!/usr/bin/env python3
"""
Test Binance REST API for historical candles
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.data_collector import BinanceDataCollector
from src.utils.config import ConfigManager

def test_rest_api():
    """Test REST API historical candles"""
    print("=" * 80)
    print("Binance REST API Test")
    print("=" * 80)

    # Load config
    print("\n1. Loading configuration...")
    config = ConfigManager()
    api_config = config.api_config

    print(f"   Environment: {'Testnet' if api_config.is_testnet else 'Mainnet'}")
    print(f"   API Key: {api_config.api_key[:8]}...{api_config.api_key[-4:]}")

    # Initialize collector
    print("\n2. Initializing BinanceDataCollector...")
    collector = BinanceDataCollector(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        symbols=["BTCUSDT"],
        intervals=["1m"],
        is_testnet=True
    )
    print(f"   ✅ Initialized")

    # Get historical candles
    print("\n3. Fetching historical candles (last 10)...")
    try:
        candles = collector.get_historical_candles(
            symbol="BTCUSDT",
            interval="1m",
            limit=10
        )

        print(f"   ✅ Received {len(candles)} candles")

        if candles:
            print("\n4. Sample candles:")
            for i, candle in enumerate(candles[:5], 1):
                print(f"   {i}. {candle.symbol} {candle.interval} @ {candle.open_time}")
                print(f"      O:{candle.open} H:{candle.high} L:{candle.low} C:{candle.close} V:{candle.volume}")
                print(f"      Closed: {candle.is_closed}")

        print("\n" + "=" * 80)
        print("✅ REST API TEST PASSED!")
        print("=" * 80)
        return True

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_rest_api()
    sys.exit(0 if success else 1)
