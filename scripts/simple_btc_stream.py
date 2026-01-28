
import asyncio
import logging
import sys
import os
from pathlib import Path

# Add project root directory to Python path (for module recognition when running from scripts folder)
# Parent (scripts) of current file (scripts/simple_btc_stream.py) -> Parent (project_root)
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from src.core.data_collector import BinanceDataCollector
from src.models.candle import Candle

# Logging configuration: Use a human-readable time format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Reduce unnecessary library logs
logging.getLogger("binance.websocket").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

def print_candle_info(candle: Candle) -> None:
    """Function called whenever new candle data arrives"""
    status = "🔴 Closed" if candle.is_closed else "🟢 In-progress"
    
    # Readable output format
    print(
        f"[{candle.close_time.strftime('%H:%M:%S')}] "
        f"{candle.symbol} {candle.interval} | "
        f"Close: {candle.close:10.2f} | "
        f"Volume: {candle.volume:10.3f} | {status}"
    )

async def main():
    print("=" * 60)
    print("🚀 ZECUSDT 1m Real-time Stream Test (Binance Mainnet)")
    print("Press Ctrl+C to terminate.")
    print("=" * 60)

    # 1. Initialize Collector
    # Simple real-time price reception (Public Stream) often works without actual API keys,
    # but dummy values are provided to satisfy library requirements.
    # If an error occurs, use actual Testnet keys from api_keys.ini.
    collector = BinanceDataCollector(
        api_key="DUMMY_KEY",
        api_secret="DUMMY_SECRET",
        symbols=["ZECUSDT"],
        intervals=["1m", "5m", "1h"],
        is_testnet=False,
        on_candle_callback=print_candle_info
    )

    try:
        # 2. Start Streaming
        await collector.start_streaming()
        print("📡 WebSocket connected! Waiting for data...\n")

        # 3. Infinite wait (prevent program termination)
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n👋 Terminating by user request.")
    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
    finally:
        # 4. Graceful shutdown
        print("Shutting down system...")
        await collector.stop()
        print("System shutdown successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Prevents forced event loop termination errors that may occur on Windows, etc.
        pass
