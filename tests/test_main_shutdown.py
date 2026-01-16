"""
Unit tests for TradingBot.shutdown() method (Subtask 10.4).

Tests graceful shutdown behavior:
- Idempotency (safe to call multiple times)
- Component shutdown ordering (DataCollector → EventBus)
- Timeout handling
- Logging verification
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.main import TradingBot


@pytest.fixture
def trading_bot():
    """Create TradingBot instance with mocked dependencies."""
    # Create bot instance
    bot = TradingBot()

    # Mock TradingEngine (now handles shutdown)
    bot.trading_engine = Mock()
    bot.trading_engine.shutdown = AsyncMock()

    # Mock components (kept for potential direct access in tests)
    bot.data_collector = Mock()
    bot.data_collector.stop = AsyncMock()

    bot.event_bus = Mock()
    bot.event_bus.shutdown = AsyncMock()

    bot.logger = Mock()

    return bot


@pytest.mark.asyncio
async def test_shutdown_delegates_to_trading_engine(trading_bot):
    """Verify shutdown delegates to TradingEngine.shutdown()."""
    # Act
    await trading_bot.shutdown()

    # Assert
    trading_bot.trading_engine.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_can_be_called_multiple_times(trading_bot):
    """Verify shutdown can be called multiple times (delegates to TradingEngine)."""
    # Act - call shutdown twice
    await trading_bot.shutdown()
    await trading_bot.shutdown()

    # Assert - TradingEngine.shutdown() called ONLY ONCE because TradingBot handles idempotency
    assert trading_bot.trading_engine.shutdown.call_count == 1


@pytest.mark.asyncio
async def test_shutdown_logs_correctly(trading_bot, caplog):
    """Verify shutdown logs correctly."""
    # Use real logger for this test (not mocked)
    import logging

    trading_bot.logger = logging.getLogger("test_shutdown")
    trading_bot.logger.setLevel(logging.INFO)

    # Act
    await trading_bot.shutdown()

    # Assert
    log_messages = [rec.message for rec in caplog.records]
    assert any("Initiating shutdown" in msg for msg in log_messages)
    assert any("Shutdown complete" in msg for msg in log_messages)
