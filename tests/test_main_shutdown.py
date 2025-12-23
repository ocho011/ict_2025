"""
Unit tests for TradingBot.shutdown() method (Subtask 10.4).

Tests graceful shutdown behavior:
- Idempotency (safe to call multiple times)
- Component shutdown ordering (DataCollector → EventBus)
- Timeout handling
- Logging verification
"""

import pytest
from unittest.mock import AsyncMock, Mock
from src.main import TradingBot


@pytest.fixture
def trading_bot():
    """Create TradingBot instance with mocked dependencies."""
    # Create bot instance
    bot = TradingBot()

    # Mock components with AsyncMock for async methods
    bot.data_collector = Mock()
    bot.data_collector.stop = AsyncMock()

    bot.event_bus = Mock()
    bot.event_bus.shutdown = AsyncMock()

    bot.logger = Mock()

    # Set initial running state
    bot._running = True

    return bot


@pytest.mark.asyncio
async def test_shutdown_sets_running_flag(trading_bot):
    """Verify shutdown sets _running flag to False."""
    # Arrange
    trading_bot._running = True

    # Act
    await trading_bot.shutdown()

    # Assert
    assert trading_bot._running is False


@pytest.mark.asyncio
async def test_shutdown_is_idempotent(trading_bot):
    """Verify shutdown can be called multiple times safely."""
    # Arrange
    trading_bot._running = True

    # Act - call shutdown twice
    await trading_bot.shutdown()
    await trading_bot.shutdown()

    # Assert - components only stopped once
    assert trading_bot.data_collector.stop.call_count == 1
    assert trading_bot.event_bus.shutdown.call_count == 1


@pytest.mark.asyncio
async def test_shutdown_stops_data_collector(trading_bot):
    """Verify DataCollector.stop() called with correct timeout."""
    # Arrange
    trading_bot._running = True

    # Act
    await trading_bot.shutdown()

    # Assert
    trading_bot.data_collector.stop.assert_called_once_with(timeout=5.0)


@pytest.mark.asyncio
async def test_shutdown_stops_event_bus(trading_bot):
    """Verify EventBus.shutdown() called with correct timeout."""
    # Arrange
    trading_bot._running = True

    # Act
    await trading_bot.shutdown()

    # Assert
    trading_bot.event_bus.shutdown.assert_called_once_with(timeout=5.0)


@pytest.mark.asyncio
async def test_shutdown_correct_order(trading_bot):
    """Verify DataCollector stopped before EventBus."""
    # Arrange
    trading_bot._running = True
    call_order = []

    # Track call order
    async def track_collector_stop(*args, **kwargs):
        call_order.append('data_collector')

    async def track_eventbus_shutdown(*args, **kwargs):
        call_order.append('event_bus')

    trading_bot.data_collector.stop = AsyncMock(side_effect=track_collector_stop)
    trading_bot.event_bus.shutdown = AsyncMock(side_effect=track_eventbus_shutdown)

    # Act
    await trading_bot.shutdown()

    # Assert
    assert call_order == ['data_collector', 'event_bus']


@pytest.mark.asyncio
async def test_shutdown_when_not_running(trading_bot):
    """Verify shutdown is no-op when _running is already False."""
    # Arrange
    trading_bot._running = False

    # Act
    await trading_bot.shutdown()

    # Assert - no components stopped
    trading_bot.data_collector.stop.assert_not_called()
    trading_bot.event_bus.shutdown.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_logs_correctly(trading_bot, caplog):
    """Verify shutdown logs correctly."""
    # Arrange
    trading_bot._running = True

    # Use real logger for this test (not mocked)
    import logging
    trading_bot.logger = logging.getLogger('test_shutdown')
    trading_bot.logger.setLevel(logging.INFO)

    # Act
    await trading_bot.shutdown()

    # Assert
    log_messages = [rec.message for rec in caplog.records]
    assert any('Shutting down' in msg for msg in log_messages)
    assert any('Shutdown complete' in msg for msg in log_messages)
