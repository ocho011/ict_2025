"""
Unit tests for BinanceDataCollector lifecycle management (Task 3.6).

Tests cover:
- is_connected property
- stop() method (graceful shutdown)
- Async context manager (__aenter__, __aexit__)
- Integration scenarios
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.core.data_collector import BinanceDataCollector
from src.core.binance_service import BinanceServiceClient
from src.models.candle import Candle
from unittest.mock import Mock, patch


class TestBinanceDataCollectorConnectionState:
    """Test suite for is_connected property"""

    @pytest.fixture
    def mock_binance_service(self):
        """Provide mock BinanceServiceClient for testing."""
        service = Mock(spec=BinanceServiceClient)
        service.is_testnet = True
        return service

    @pytest.fixture
    def basic_config(self):
        """Provide basic configuration for testing."""
        return {
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
        }

    @pytest.fixture
    def data_collector(self, mock_binance_service, basic_config):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            binance_service=mock_binance_service,
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
        )

    def test_is_connected_false_when_not_started(self, data_collector):
        """Verify is_connected returns False before start_streaming()"""
        assert data_collector.is_connected is False
        assert data_collector._is_connected is False
        assert len(data_collector.ws_clients) == 0

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_is_connected_true_after_start(self, mock_ws_client_class, data_collector):
        """Verify is_connected returns True after successful start_streaming()"""
        # Start streaming
        await data_collector.start_streaming()

        # Verify is_connected
        assert data_collector.is_connected is True
        assert data_collector._is_connected is True
        assert len(data_collector.ws_clients) > 0

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_is_connected_false_after_stop(self, mock_ws_client_class, data_collector):
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
    def mock_binance_service(self):
        """Provide mock BinanceServiceClient for testing."""
        service = Mock(spec=BinanceServiceClient)
        service.is_testnet = True
        return service

    @pytest.fixture
    def basic_config(self):
        """Provide basic configuration for testing."""
        return {
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
        }

    @pytest.fixture
    def data_collector(self, mock_binance_service, basic_config):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            binance_service=mock_binance_service,
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
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

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_stop_closes_websocket(self, mock_ws_client_class, data_collector):
        """Verify WebSocket client stop() is called"""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance
        
        # Start streaming
        await data_collector.start_streaming()

        # Stop collector
        await data_collector.stop()

        # Verify ws_client.stop was called
        mock_ws_instance.stop.assert_called()

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_stop_timeout_handling(self, mock_ws_client_class, data_collector):
        """Verify timeout parameter works correctly"""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance
        
        # Start streaming
        await data_collector.start_streaming()

        # Mock ws_client.stop to take longer than timeout
        async def slow_stop():
            await asyncio.sleep(10)  # Longer than timeout

        mock_ws_instance.stop.side_effect = lambda: asyncio.run(slow_stop())

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

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_stop_handles_websocket_errors(self, mock_ws_client_class, data_collector):
        """Verify cleanup continues if WebSocket stop() raises"""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance
        
        # Start streaming
        await data_collector.start_streaming()

        # Mock ws_client.stop to raise exception
        mock_ws_instance.stop.side_effect = RuntimeError("WebSocket error")

        # Stop should not raise, should log error
        await data_collector.stop()

        # Flags should still be updated
        assert data_collector._running is False
        assert data_collector._is_connected is False

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_stop_updates_state_flags(self, mock_ws_client_class, data_collector):
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
    def mock_binance_service(self):
        """Provide mock BinanceServiceClient for testing."""
        service = Mock(spec=BinanceServiceClient)
        service.is_testnet = True
        return service

    @pytest.fixture
    def basic_config(self):
        """Provide basic configuration for testing."""
        return {
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
        }

    @pytest.fixture
    def data_collector(self, mock_binance_service, basic_config):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            binance_service=mock_binance_service,
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
        )

    async def test_context_manager_enter_returns_self(self, data_collector):
        """Verify __aenter__ returns collector instance"""
        returned = await data_collector.__aenter__()
        assert returned is data_collector

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_context_manager_exit_calls_stop(self, mock_ws_client_class, data_collector):
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

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_context_manager_with_exception(self, mock_ws_client_class, data_collector):
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

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_context_manager_full_lifecycle(self, mock_ws_client_class, data_collector):
        """Integration: async with → start_streaming → cleanup"""
        # Use async context manager
        async with data_collector as collector:
            # Verify we got the collector
            assert collector is data_collector

            # Start streaming
            await collector.start_streaming()
            assert collector.is_connected is True

        # After context exit, should be stopped
        assert data_collector.is_connected is False
        assert data_collector._running is False


class TestBinanceDataCollectorLifecycleIntegration:
    """Integration tests for lifecycle management"""

    @pytest.fixture
    def mock_binance_service(self):
        """Provide mock BinanceServiceClient for testing."""
        service = Mock(spec=BinanceServiceClient)
        service.is_testnet = True
        return service

    @pytest.fixture
    def basic_config(self):
        """Provide basic configuration for testing."""
        return {
            "symbols": ["BTCUSDT"],
            "intervals": ["1m"],
        }

    @pytest.fixture
    def data_collector(self, mock_binance_service, basic_config):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            binance_service=mock_binance_service,
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
        )

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_start_and_stop_lifecycle(self, mock_ws_client_class, data_collector):
        """Full lifecycle: start → stop → verify cleanup"""
        # Initial state
        assert data_collector.is_connected is False

        # Start
        await data_collector.start_streaming()
        assert data_collector.is_connected is True
        assert len(data_collector.ws_clients) > 0

        # Stop
        await data_collector.stop()
        assert data_collector.is_connected is False
        assert data_collector._running is False

    @patch("src.core.data_collector.UMFuturesWebsocketClient")
    async def test_context_manager_usage_pattern(self, mock_ws_client_class, data_collector, mock_binance_service):
        """Real-world usage pattern with context manager"""
        collected_candles = []

        def callback(candle: Candle):
            collected_candles.append(candle)

        # Create collector with callback
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            symbols=["BTCUSDT"],
            intervals=["1m"],
            on_candle_callback=callback,
        )

        # Use context manager
        async with collector:
            await collector.start_streaming()

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
        assert collector.is_connected is False

        # Verify callbacks were invoked
        assert len(collected_candles) == 3
