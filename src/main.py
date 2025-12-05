"""
Main entry point for the trading system
"""

import asyncio
from src.utils.logger import setup_logger
from src.utils.config import ConfigManager

logger = setup_logger(__name__)


async def main():
    """
    Main async entry point
    """
    logger.info("🚀 Starting ICT 2025 Trading System...")

    # Load configuration
    config = ConfigManager()
    config.validate()

    logger.info(f"Configuration loaded: {config.trading_config.symbol}")
    logger.info(f"Testnet mode: {config.is_testnet}")

    # TODO: Initialize and start trading components
    logger.info("✅ System initialized successfully")


if __name__ == "__main__":
    asyncio.run(main())
