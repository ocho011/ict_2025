"""
Unit tests for BinanceDataCollector lifecycle management (Task 3.6).

Tests cover:
- is_connected property
- stop() method (graceful shutdown)
- Async context manager (__aenter__, __aexit__)
- Integration scenarios

Updated for Issue #57: Uses new composition pattern with injected streamers.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.data_collector import BinanceDataCollector
from src.core.public_market_streamer import PublicMarketStreamer
from src.core.private_user_streamer import PrivateUserStreamer
from src.core.binance_service import BinanceServiceClient
from src.models.candle import Candle


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_binance_service():
    """Provide mock BinanceServiceClient for testing."""
    service = Mock(spec=BinanceServiceClient)
    service.is_testnet = True
    return service


@pytest.fixture
def mock_market_streamer():
    """Provide mock PublicMarketStreamer for testing."""
    streamer = Mock(spec=PublicMarketStreamer)
    streamer.symbols = ["BTCUSDT"]
    streamer.intervals = ["1m"]
    streamer.is_connected = False
    streamer.on_candle_callback = None
    streamer.start = AsyncMock()
    streamer.stop = AsyncMock()
    return streamer


@pytest.fixture
def mock_user_streamer():
    """Provide mock PrivateUserStreamer for testing."""
    streamer = Mock(spec=PrivateUserStreamer)
    streamer.is_connected = False
    streamer.start = AsyncMock()
    streamer.stop = AsyncMock()
    streamer.set_order_fill_callback = Mock()
    streamer.set_position_update_callback = Mock()
    streamer.set_order_update_callback = Mock()
    return streamer


@pytest.fixture
def basic_config():
    """Provide basic configuration for testing."""
    return {
        "symbols": ["BTCUSDT"],
        "intervals": ["1m"],
    }


@pytest.fixture
def data_collector(mock_binance_service, mock_market_streamer, mock_user_streamer):
    """Create BinanceDataCollector instance for testing."""
    return BinanceDataCollector(
        binance_service=mock_binance_service,
        market_streamer=mock_market_streamer,
        user_streamer=mock_user_streamer,
    )


# =============================================================================
# Connection State Tests
# =============================================================================


class TestBinanceDataCollectorConnectionState:
    """Test suite for is_connected property"""

    def test_is_connected_false_when_not_started(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify is_connected returns False before start_streaming()"""
        mock_market_streamer.is_connected = False

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        assert data_collector.is_connected is False

    @pytest.mark.asyncio
    async def test_is_connected_true_after_start(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify is_connected returns True after successful start_streaming()"""
        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Start streaming
        await data_collector.start_streaming()

        # Update mock to reflect connected state (both streamers must be connected)
        mock_market_streamer.is_connected = True
        mock_user_streamer.is_connected = True

        # Verify is_connected
        assert data_collector.is_connected is True
        assert data_collector._running is True

    @pytest.mark.asyncio
    async def test_is_connected_false_after_stop(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify is_connected returns False after stop()"""
        mock_market_streamer.is_connected = True
        mock_user_streamer.is_connected = True

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        data_collector._running = True

        # Stop
        await data_collector.stop()

        # Update mock to reflect disconnected state
        mock_market_streamer.is_connected = False
        mock_user_streamer.is_connected = False

        # Verify is_connected
        assert data_collector.is_connected is False
        assert data_collector._running is False


# =============================================================================
# Stop Method Tests
# =============================================================================


class TestBinanceDataCollectorStop:
    """Test suite for stop() method"""

    @pytest.mark.asyncio
    async def test_stop_idempotency(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify multiple stop() calls are safe"""
        mock_market_streamer.is_connected = False

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Call stop multiple times
        await data_collector.stop()
        await data_collector.stop()
        await data_collector.stop()

        # Should not raise, flags should be False
        assert data_collector._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_websocket(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify market_streamer.stop() is called"""
        mock_market_streamer.is_connected = True

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        data_collector._running = True

        # Stop collector
        await data_collector.stop()

        # Verify market_streamer.stop was called
        mock_market_streamer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_timeout_handling(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify timeout parameter is passed to streamer"""
        mock_market_streamer.is_connected = True

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        data_collector._running = True

        # Stop with custom timeout
        await data_collector.stop(timeout=0.1)

        # Verify stop was called with timeout
        mock_market_streamer.stop.assert_called_once_with(timeout=0.1)
        assert data_collector._running is False

    @pytest.mark.asyncio
    async def test_stop_without_websocket(
        self, mock_binance_service, mock_market_streamer
    ):
        """Verify stop() works when user_streamer is None"""
        mock_market_streamer.is_connected = False

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )

        # Don't start streaming, just call stop
        await data_collector.stop()

        # Should complete without errors
        assert data_collector._running is False

    @pytest.mark.asyncio
    async def test_stop_handles_websocket_errors(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify cleanup continues if streamer stop() raises"""
        mock_market_streamer.is_connected = True
        mock_market_streamer.stop = AsyncMock(side_effect=RuntimeError("WebSocket error"))

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        data_collector._running = True

        # Stop should not raise, should log error
        await data_collector.stop()

        # Flags should still be updated
        assert data_collector._running is False

    @pytest.mark.asyncio
    async def test_stop_updates_state_flags(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify _running is set to False"""
        mock_market_streamer.is_connected = True

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Start streaming
        await data_collector.start_streaming()
        assert data_collector._running is True

        # Stop
        await data_collector.stop()

        # Verify flags
        assert data_collector._running is False


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestBinanceDataCollectorContextManager:
    """Test suite for async context manager"""

    @pytest.mark.asyncio
    async def test_context_manager_enter_returns_self(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify __aenter__ returns collector instance"""
        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        returned = await data_collector.__aenter__()
        assert returned is data_collector

    @pytest.mark.asyncio
    async def test_context_manager_exit_calls_stop(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify __aexit__ calls stop() automatically"""
        mock_market_streamer.is_connected = True

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Enter context
        await data_collector.__aenter__()

        # Start streaming
        await data_collector.start_streaming()
        assert data_collector._running is True

        # Exit context
        await data_collector.__aexit__(None, None, None)

        # Verify stop was called (flags should be False)
        assert data_collector._running is False
        mock_market_streamer.stop.assert_called()

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify cleanup runs even with context exception"""
        mock_market_streamer.is_connected = True

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Enter context
        await data_collector.__aenter__()

        # Start streaming
        await data_collector.start_streaming()

        # Exit with exception
        await data_collector.__aexit__(ValueError, ValueError("test error"), None)

        # Verify cleanup still happened
        assert data_collector._running is False

    @pytest.mark.asyncio
    async def test_context_manager_does_not_suppress_exceptions(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Verify context exceptions propagate correctly"""
        mock_market_streamer.is_connected = False

        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # __aexit__ should return None (falsy) to not suppress exceptions
        result = await data_collector.__aexit__(ValueError, ValueError("test"), None)
        assert result is None

    @pytest.mark.asyncio
    async def test_context_manager_full_lifecycle(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Integration: async with → start_streaming → cleanup"""
        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Use async context manager
        async with data_collector as collector:
            # Verify we got the collector
            assert collector is data_collector

            # Start streaming
            await collector.start_streaming()
            mock_market_streamer.is_connected = True
            mock_user_streamer.is_connected = True
            assert collector.is_connected is True

        # After context exit, should be stopped
        assert data_collector._running is False


# =============================================================================
# Lifecycle Integration Tests
# =============================================================================


class TestBinanceDataCollectorLifecycleIntegration:
    """Integration tests for lifecycle management"""

    @pytest.mark.asyncio
    async def test_start_and_stop_lifecycle(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Full lifecycle: start → stop → verify cleanup"""
        data_collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Initial state
        assert data_collector.is_connected is False

        # Start
        await data_collector.start_streaming()
        mock_market_streamer.is_connected = True
        mock_user_streamer.is_connected = True
        assert data_collector.is_connected is True

        # Stop
        await data_collector.stop()
        mock_market_streamer.is_connected = False
        mock_user_streamer.is_connected = False
        assert data_collector.is_connected is False
        assert data_collector._running is False

    @pytest.mark.asyncio
    async def test_context_manager_usage_pattern(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Real-world usage pattern with context manager"""
        collected_candles = []

        def callback(candle: Candle):
            collected_candles.append(candle)

        # Configure mock to use callback
        mock_market_streamer.on_candle_callback = callback

        # Create collector with callback
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Use context manager
        async with collector:
            await collector.start_streaming()
            mock_market_streamer.is_connected = True

            # Simulate receiving candles via callback
            for i in range(3):
                candle = Candle(
                    symbol="BTCUSDT",
                    interval="1m",
                    open_time=datetime.now(timezone.utc),
                    close_time=datetime.now(timezone.utc),
                    open=50000.0 + i,
                    high=50100.0 + i,
                    low=49900.0 + i,
                    close=50050.0 + i,
                    volume=10.5,
                    is_closed=True,
                )
                if collector.on_candle_callback:
                    collector.on_candle_callback(candle)

        # After context, verify cleanup
        mock_market_streamer.is_connected = False
        assert collector.is_connected is False

        # Verify callbacks were invoked
        assert len(collected_candles) == 3
