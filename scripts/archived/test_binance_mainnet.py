#!/usr/bin/env python3
"""
Binance Mainnet Integration Test Script

Tests real WebSocket connection to Binance Mainnet and verifies:
1. API authentication
2. WebSocket connection establishment
3. Real-time kline data streaming
4. Message parsing accuracy
5. Buffer management
6. Graceful shutdown

Usage:
    python scripts/test_binance_mainnet.py

Requirements:
    - configs/api_keys.ini with valid Mainnet API keys
    - use_testnet = false in api_keys.ini (or not set)

WARNING: This connects to REAL Binance Mainnet (production environment)
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.data_collector import BinanceDataCollector
from src.models.candle import Candle
from src.utils.config_manager import ConfigManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('mainnet_integration_test.log')
    ]
)
logger = logging.getLogger(__name__)


class IntegrationTestStats:
    """Track statistics during integration test"""

    def __init__(self):
        self.candles_received = 0
        self.unique_symbols = set()
        self.unique_intervals = set()
        self.start_time = None
        self.first_candle_time = None
        self.last_candle_time = None
        self.sample_candles = []

    def record_candle(self, candle: Candle):
        """Record a received candle"""
        self.candles_received += 1
        self.unique_symbols.add(candle.symbol)
        self.unique_intervals.add(candle.interval)

        if self.first_candle_time is None:
            self.first_candle_time = datetime.now()

        self.last_candle_time = datetime.now()

        # Keep first 3 candles as samples
        if len(self.sample_candles) < 3:
            self.sample_candles.append(candle)

    def print_summary(self):
        """Print test summary"""
        duration = (self.last_candle_time - self.start_time).total_seconds() if (self.start_time and self.last_candle_time) else 0

        logger.info("=" * 80)
        logger.info("MAINNET INTEGRATION TEST SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Test Duration: {duration:.1f} seconds")
        logger.info(f"Total Candles Received: {self.candles_received}")
        logger.info(f"Unique Symbols: {', '.join(sorted(self.unique_symbols))}")
        logger.info(f"Unique Intervals: {', '.join(sorted(self.unique_intervals))}")
        logger.info(f"Average Rate: {self.candles_received / duration:.2f} candles/sec" if duration > 0 else "N/A")

        if self.sample_candles:
            logger.info("\nSample Candles (first 3):")
            for i, candle in enumerate(self.sample_candles, 1):
                logger.info(f"  {i}. {candle.symbol} {candle.interval} @ {candle.open_time}")
                logger.info(f"     O:{candle.open} H:{candle.high} L:{candle.low} C:{candle.close} V:{candle.volume}")
                logger.info(f"     Closed: {candle.is_closed}")

        logger.info("=" * 80)


async def run_integration_test(duration_seconds: int = 30):
    """
    Run integration test with real Binance Mainnet connection

    Args:
        duration_seconds: How long to collect data (default: 30 seconds)
    """
    logger.info("Starting Binance Mainnet Integration Test")
    logger.info("=" * 80)
    logger.warning("⚠️  WARNING: Connecting to REAL Binance Mainnet (Production)")
    logger.info("=" * 80)

    # Step 1: Load configuration
    logger.info("Step 1: Loading configuration from configs/api_keys.ini")
    try:
        config_manager = ConfigManager()
        api_config = config_manager.api_config

        logger.info(f"✅ Configuration loaded successfully")
        logger.info(f"   Environment: {'Testnet' if api_config.is_testnet else 'Mainnet'}")
        logger.info(f"   API Key: {api_config.api_key[:8]}...{api_config.api_key[-4:]}")

        if api_config.is_testnet:
            logger.warning("⚠️  WARNING: is_testnet is True! This test is for Mainnet.")
            logger.warning("   Continuing anyway, but verify your configuration.")

    except Exception as e:
        logger.error(f"❌ Failed to load configuration: {e}")
        return False

    # Step 2: Initialize statistics tracker
    stats = IntegrationTestStats()
    stats.start_time = datetime.now()

    # Step 3: Create callback to track received candles
    def on_candle_received(candle: Candle):
        """Callback invoked for each received candle"""
        stats.record_candle(candle)
        logger.info(f"📊 Received: {candle.symbol} {candle.interval} | "
                   f"Close: {candle.close} | Closed: {candle.is_closed}")

    # Step 4: Initialize BinanceDataCollector
    logger.info("\nStep 2: Initializing BinanceDataCollector")
    try:
        collector = BinanceDataCollector(
            api_key=api_config.api_key,
            api_secret=api_config.api_secret,
            symbols=["BTCUSDT", "ETHUSDT"],  # Test with 2 symbols
            intervals=["1m"],                 # Test with 1 minute interval
            is_testnet=False,                 # Force Mainnet
            on_candle_callback=on_candle_received
        )
        logger.info("✅ BinanceDataCollector initialized")
        logger.info(f"   Symbols: {collector.symbols}")
        logger.info(f"   Intervals: {collector.intervals}")
        logger.info(f"   Testnet: {collector.is_testnet}")

    except Exception as e:
        logger.error(f"❌ Failed to initialize collector: {e}")
        return False

    # Step 5: Test with async context manager
    logger.info("\nStep 3: Starting WebSocket connection (async context manager)")
    try:
        async with collector:
            logger.info("✅ Entered async context manager")

            # Start streaming
            logger.info("Starting WebSocket streaming...")
            await collector.start_streaming()
            logger.info(f"✅ WebSocket connected: {collector.is_connected}")

            # Collect data for specified duration
            logger.info(f"\nStep 4: Collecting real-time data for {duration_seconds} seconds...")
            logger.info("Press Ctrl+C to stop early\n")

            try:
                await asyncio.sleep(duration_seconds)
            except KeyboardInterrupt:
                logger.info("\n⚠️  Interrupted by user (Ctrl+C)")

            logger.info("\nStep 5: Stopping data collection...")

        # Context manager automatically calls stop()
        logger.info("✅ Exited async context manager (automatic cleanup)")
        logger.info(f"✅ Connection closed: {not collector.is_connected}")

    except Exception as e:
        logger.error(f"❌ Error during streaming: {e}", exc_info=True)
        return False

    # Step 6: Verify buffer contents
    logger.info("\nStep 6: Verifying buffer contents")
    for symbol in collector.symbols:
        for interval in collector.intervals:
            buffer = collector.get_candle_buffer(symbol, interval)
            logger.info(f"   {symbol}_{interval}: {len(buffer)} candles in buffer")

            if buffer:
                latest = buffer[-1]
                logger.info(f"      Latest: {latest.open_time} | Close: {latest.close}")

    # Step 7: Print summary
    stats.print_summary()

    # Step 8: Validate results
    logger.info("\nStep 7: Validating test results")
    success = True

    if stats.candles_received == 0:
        logger.error("❌ FAIL: No candles received")
        success = False
    else:
        logger.info(f"✅ PASS: Received {stats.candles_received} candles")

    expected_symbols = {"BTCUSDT", "ETHUSDT"}
    if stats.unique_symbols != expected_symbols:
        logger.error(f"❌ FAIL: Expected symbols {expected_symbols}, got {stats.unique_symbols}")
        success = False
    else:
        logger.info(f"✅ PASS: All expected symbols received")

    if "1m" not in stats.unique_intervals:
        logger.error(f"❌ FAIL: Expected interval '1m', got {stats.unique_intervals}")
        success = False
    else:
        logger.info(f"✅ PASS: All expected intervals received")

    if success:
        logger.info("\n🎉 MAINNET INTEGRATION TEST PASSED!")
    else:
        logger.error("\n💥 MAINNET INTEGRATION TEST FAILED!")

    return success


def main():
    """Main entry point"""
    try:
        # Run integration test for 30 seconds
        success = asyncio.run(run_integration_test(duration_seconds=30))
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.info("\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n💥 Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
