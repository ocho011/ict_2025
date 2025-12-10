"""
Unit tests for BinanceDataCollector lifecycle management (Task 3.6).

Tests cover:
- is_connected property
- stop() method (graceful shutdown)
- Async context manager (__aenter__, __aexit__)
- Integration scenarios
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from src.core.data_collector import BinanceDataCollector
from src.models.candle import Candle


class TestBinanceDataCollectorConnectionState:
    """Test suite for is_connected property"""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide test API credentials"""
        return {"api_key": "test_key", "api_secret": "test_secret"}

    @pytest.fixture
    @patch('src.core.data_collector.UMFutures')
    def data_collector(self, mock_um_futures, mock_api_credentials):
        """Create BinanceDataCollector instance for testing"""
        return BinanceDataCollector(
            api_key=mock_api_credentials["api_key"],
            api_secret=mock_api_credentials["api_secret"],
            symbols=["BTCUSDT"],
            intervals=["1m"],
            is_testnet=True
        )

    def test_is_connected_false_when_not_started(self, data_collector):
        """Verify is_connected returns False before start_streaming()"""
        assert data_collector.is_connected is False
        assert data_collector._is_connected is False
        assert data_collector.ws_client is None

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_is_connected_true_after_start(self, mock_ws_client, data_collector):
        """Verify is_connected returns True after successful start_streaming()"""
        # Start streaming
        await data_collector.start_streaming()

        # Verify is_connected
        assert data_collector.is_connected is True
        assert data_collector._is_connected is True
        assert data_collector.ws_client is not None

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_is_connected_false_after_stop(self, mock_ws_client, data_collector):
        """Verify is_connected returns False after stop()"""
        # Start and then stop
        await data_collector.start_streaming()
        await data_collector.stop()

        # Verify is_connected
        assert data_collector.is_connected is False
        assert data_collector._is_connected is False


class TestBinanceDataCollectorStop:
    """Test suite for stop() method"""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide test API credentials"""
        return {"api_key": "test_key", "api_secret": "test_secret"}

    @pytest.fixture
    @patch('src.core.data_collector.UMFutures')
    def data_collector(self, mock_um_futures, mock_api_credentials):
        """Create BinanceDataCollector instance for testing"""
        return BinanceDataCollector(
            api_key=mock_api_credentials["api_key"],
            api_secret=mock_api_credentials["api_secret"],
            symbols=["BTCUSDT"],
            intervals=["1m"],
            is_testnet=True
        )

    async def test_stop_idempotency(self, data_collector):
        """Verify multiple stop() calls are safe"""
        # Call stop multiple times
        await data_collector.stop()
        await data_collector.stop()
        await data_collector.stop()

        # Should not raise, flags should be False
        assert data_collector._running is False
        assert data_collector._is_connected is False

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_closes_websocket(self, mock_ws_client, data_collector):
        """Verify WebSocket client stop() is called"""
        # Start streaming
        await data_collector.start_streaming()

        # Mock the ws_client.stop method
        data_collector.ws_client.stop = MagicMock()

        # Stop collector
        await data_collector.stop()

        # Verify ws_client.stop was called
        data_collector.ws_client.stop.assert_called_once()

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_preserves_buffers(self, mock_ws_client, data_collector):
        """Verify buffers remain accessible after stop()"""
        # Add candle to buffer
        candle = Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=10.5,
            is_closed=True
        )
        data_collector.add_candle_to_buffer(candle)

        # Start and stop
        await data_collector.start_streaming()
        await data_collector.stop()

        # Verify buffer is still accessible
        buffer = data_collector.get_candle_buffer("BTCUSDT", "1m")
        assert len(buffer) == 1
        assert buffer[0].close == 50050.0

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_timeout_handling(self, mock_ws_client, data_collector):
        """Verify timeout parameter works correctly"""
        # Start streaming
        await data_collector.start_streaming()

        # Mock ws_client.stop to take longer than timeout
        async def slow_stop():
            await asyncio.sleep(10)  # Longer than timeout

        data_collector.ws_client.stop = MagicMock(side_effect=lambda: asyncio.run(slow_stop()))

        # Stop with short timeout (should timeout but not raise)
        await data_collector.stop(timeout=0.1)

        # Should complete without raising, flags should be False
        assert data_collector._running is False
        assert data_collector._is_connected is False

    async def test_stop_without_websocket(self, data_collector):
        """Verify stop() works when ws_client is None"""
        # Don't start streaming, just call stop
        await data_collector.stop()

        # Should complete without errors
        assert data_collector._running is False
        assert data_collector._is_connected is False

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_logs_buffer_states(self, mock_ws_client, data_collector, caplog):
        """Verify buffer states are logged during shutdown"""
        import logging
        caplog.set_level(logging.INFO)

        # Add candles to buffer
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
                is_closed=True
            )
            data_collector.add_candle_to_buffer(candle)

        # Start and stop
        await data_collector.start_streaming()
        await data_collector.stop()

        # Verify buffer state was logged
        assert "Buffer states at shutdown" in caplog.text
        assert "BTCUSDT_1m: 3 candles" in caplog.text

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_handles_websocket_errors(self, mock_ws_client, data_collector):
        """Verify cleanup continues if WebSocket stop() raises"""
        # Start streaming
        await data_collector.start_streaming()

        # Mock ws_client.stop to raise exception
        data_collector.ws_client.stop = MagicMock(side_effect=RuntimeError("WebSocket error"))

        # Stop should not raise, should log error
        await data_collector.stop()

        # Flags should still be updated
        assert data_collector._running is False
        assert data_collector._is_connected is False

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_updates_state_flags(self, mock_ws_client, data_collector):
        """Verify _running and _is_connected are set to False"""
        # Start streaming
        await data_collector.start_streaming()
        assert data_collector._running is True
        assert data_collector._is_connected is True

        # Stop
        await data_collector.stop()

        # Verify flags
        assert data_collector._running is False
        assert data_collector._is_connected is False


class TestBinanceDataCollectorContextManager:
    """Test suite for async context manager"""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide test API credentials"""
        return {"api_key": "test_key", "api_secret": "test_secret"}

    @pytest.fixture
    @patch('src.core.data_collector.UMFutures')
    def data_collector(self, mock_um_futures, mock_api_credentials):
        """Create BinanceDataCollector instance for testing"""
        return BinanceDataCollector(
            api_key=mock_api_credentials["api_key"],
            api_secret=mock_api_credentials["api_secret"],
            symbols=["BTCUSDT"],
            intervals=["1m"],
            is_testnet=True
        )

    async def test_context_manager_enter_returns_self(self, data_collector):
        """Verify __aenter__ returns collector instance"""
        returned = await data_collector.__aenter__()
        assert returned is data_collector

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_context_manager_exit_calls_stop(self, mock_ws_client, data_collector):
        """Verify __aexit__ calls stop() automatically"""
        # Enter context
        await data_collector.__aenter__()

        # Start streaming
        await data_collector.start_streaming()
        assert data_collector._running is True

        # Exit context
        await data_collector.__aexit__(None, None, None)

        # Verify stop was called (flags should be False)
        assert data_collector._running is False
        assert data_collector._is_connected is False

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_context_manager_with_exception(self, mock_ws_client, data_collector):
        """Verify cleanup runs even with context exception"""
        # Enter context
        await data_collector.__aenter__()

        # Start streaming
        await data_collector.start_streaming()

        # Exit with exception
        await data_collector.__aexit__(ValueError, ValueError("test error"), None)

        # Verify cleanup still happened
        assert data_collector._running is False
        assert data_collector._is_connected is False

    async def test_context_manager_does_not_suppress_exceptions(self, data_collector):
        """Verify context exceptions propagate correctly"""
        # __aexit__ should return None (falsy) to not suppress exceptions
        result = await data_collector.__aexit__(ValueError, ValueError("test"), None)
        assert result is None

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_context_manager_full_lifecycle(self, mock_ws_client, data_collector):
        """Integration: async with → start_streaming → use → cleanup"""
        # Use async context manager
        async with data_collector as collector:
            # Verify we got the collector
            assert collector is data_collector

            # Start streaming
            await collector.start_streaming()
            assert collector.is_connected is True

            # Add a candle
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50050.0,
                volume=10.5,
                is_closed=True
            )
            collector.add_candle_to_buffer(candle)

        # After context exit, should be stopped
        assert data_collector.is_connected is False
        assert data_collector._running is False

        # Buffer should still be accessible
        buffer = data_collector.get_candle_buffer("BTCUSDT", "1m")
        assert len(buffer) == 1


class TestBinanceDataCollectorLifecycleIntegration:
    """Integration tests for lifecycle management"""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide test API credentials"""
        return {"api_key": "test_key", "api_secret": "test_secret"}

    @pytest.fixture
    @patch('src.core.data_collector.UMFutures')
    def data_collector(self, mock_um_futures, mock_api_credentials):
        """Create BinanceDataCollector instance for testing"""
        return BinanceDataCollector(
            api_key=mock_api_credentials["api_key"],
            api_secret=mock_api_credentials["api_secret"],
            symbols=["BTCUSDT"],
            intervals=["1m"],
            is_testnet=True
        )

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_start_and_stop_lifecycle(self, mock_ws_client, data_collector):
        """Full lifecycle: start → stop → verify cleanup"""
        # Initial state
        assert data_collector.is_connected is False

        # Start
        await data_collector.start_streaming()
        assert data_collector.is_connected is True
        assert data_collector.ws_client is not None

        # Stop
        await data_collector.stop()
        assert data_collector.is_connected is False
        assert data_collector._running is False

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_stop_with_active_buffers(self, mock_ws_client, data_collector):
        """Stop with candles in buffer, verify accessible afterward"""
        # Start streaming
        await data_collector.start_streaming()

        # Add multiple candles
        for i in range(5):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i * 10,
                high=50100.0 + i * 10,
                low=49900.0 + i * 10,
                close=50050.0 + i * 10,
                volume=10.5,
                is_closed=True
            )
            data_collector.add_candle_to_buffer(candle)

        # Stop
        await data_collector.stop()

        # Verify buffer still accessible
        buffer = data_collector.get_candle_buffer("BTCUSDT", "1m")
        assert len(buffer) == 5
        assert all(c.symbol == "BTCUSDT" for c in buffer)

    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    async def test_context_manager_usage_pattern(self, mock_ws_client, data_collector):
        """Real-world usage pattern with context manager"""
        collected_candles = []

        def callback(candle: Candle):
            collected_candles.append(candle)

        # Create collector with callback
        collector = BinanceDataCollector(
            api_key="test_key",
            api_secret="test_secret",
            symbols=["BTCUSDT"],
            intervals=["1m"],
            is_testnet=True,
            on_candle_callback=callback
        )

        # Use context manager
        async with collector:
            await collector.start_streaming()

            # Simulate receiving candles
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
                    is_closed=True
                )
                collector.add_candle_to_buffer(candle)
                if collector.on_candle_callback:
                    collector.on_candle_callback(candle)

        # After context, verify cleanup
        assert collector.is_connected is False

        # Verify callbacks were invoked
        assert len(collected_candles) == 3

        # Verify buffer still accessible
        buffer = collector.get_candle_buffer("BTCUSDT", "1m")
        assert len(buffer) == 3
