"""
Tests for User Data Stream Manager implementation (Issue #54).

This test suite verifies:
1. Listen key lifecycle management (creation, keep-alive, cleanup)
2. BinanceService listen key method wrappers
3. DataCollector integration with User Data Stream
4. PrivateUserStreamer ORDER_TRADE_UPDATE event handling

Updated for Issue #57: Uses new composition pattern with injected streamers.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from src.core.listen_key_manager import ListenKeyManager
from src.core.binance_service import BinanceServiceClient
from src.core.data_collector import BinanceDataCollector
from src.core.public_market_streamer import PublicMarketStreamer
from src.core.private_user_streamer import PrivateUserStreamer
from src.models.event import EventType


class TestListenKeyManager:
    """Test suite for ListenKeyManager class."""

    @pytest.fixture
    def binance_service(self):
        """
        Create mock BinanceServiceClient instance.
        """
        client = MagicMock(spec=BinanceServiceClient)
        client.new_listen_key.return_value = {"listenKey": "test_listen_key_123"}
        client.renew_listen_key.return_value = {"listenKey": "test_renewed_key_456"}
        client.close_listen_key.return_value = {}
        return client

    @pytest.fixture
    def listen_key_manager(self, binance_service):
        """
        Create ListenKeyManager with mocked BinanceService.
        """
        return ListenKeyManager(binance_service)

    @pytest.mark.asyncio
    async def test_listen_key_creation_success(self, listen_key_manager):
        """
        Test successful listen key creation.

        Should:
        - Call binance_service.new_listen_key() via ListenKeyManager
        - Return listen key
        - Start keep-alive loop
        """
        # Call start method
        result = await listen_key_manager.start()

        assert result == "test_listen_key_123", f"Expected listen key: test_listen_key_123"
        assert listen_key_manager.binance_service.new_listen_key.called
        assert listen_key_manager._running is True
        assert listen_key_manager._keep_alive_task is not None

        # Cleanup
        await listen_key_manager.stop()

    @pytest.mark.asyncio
    async def test_listen_key_already_running(self, listen_key_manager):
        """
        Test that starting when already running returns existing key.
        """
        # Start first time
        first_key = await listen_key_manager.start()

        # Try to start again
        second_key = await listen_key_manager.start()

        assert first_key == second_key
        # Should only have called new_listen_key once
        assert listen_key_manager.binance_service.new_listen_key.call_count == 1

        # Cleanup
        await listen_key_manager.stop()

    @pytest.mark.asyncio
    async def test_keep_alive_ping_interval(self, listen_key_manager):
        """
        Test that keep-alive task is created with correct interval.
        """
        # Start manager to initialize keep-alive task
        await listen_key_manager.start()

        # Verify task was created
        assert listen_key_manager._keep_alive_task is not None
        assert not listen_key_manager._keep_alive_task.done()

        # Verify interval constant is set correctly (30 minutes)
        assert listen_key_manager.KEEP_ALIVE_INTERVAL_SECONDS == 1800

        # Cleanup - cancel the task first
        listen_key_manager._keep_alive_task.cancel()
        try:
            await listen_key_manager._keep_alive_task
        except asyncio.CancelledError:
            pass

        await listen_key_manager.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_listen_key(self, listen_key_manager):
        """
        Test graceful shutdown with listen key cleanup.
        """
        # Start manager to initialize
        await listen_key_manager.start()

        # Stop manager which should:
        # 1. Stop keep-alive loop
        # 2. Close listen key via Binance API
        # 3. Clear state
        await listen_key_manager.stop()

        # Verify cleanup
        assert listen_key_manager._keep_alive_task is None
        assert listen_key_manager.listen_key is None
        assert listen_key_manager._running is False
        assert listen_key_manager.binance_service.close_listen_key.called

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, listen_key_manager):
        """
        Test that stop() can be called multiple times (idempotent).
        """
        # Start
        await listen_key_manager.start()

        # Stop multiple times - should not raise
        await listen_key_manager.stop()
        await listen_key_manager.stop()
        await listen_key_manager.stop()

        # Verify cleanup happened only once
        assert listen_key_manager.binance_service.close_listen_key.call_count == 1

    @pytest.mark.asyncio
    async def test_start_stop_restart(self, listen_key_manager):
        """
        Test that manager can be restarted after stop.
        """
        # First start
        await listen_key_manager.start()
        assert listen_key_manager.listen_key == "test_listen_key_123"

        # Stop
        await listen_key_manager.stop()
        assert listen_key_manager.listen_key is None

        # Second start
        await listen_key_manager.start()
        assert listen_key_manager.listen_key == "test_listen_key_123"
        assert listen_key_manager._running is True

        # Cleanup
        await listen_key_manager.stop()

    @pytest.mark.asyncio
    async def test_exception_on_listen_key_creation(self, listen_key_manager):
        """
        Test exception handling when listen key creation fails.
        """
        # Make new_listen_key raise an exception
        listen_key_manager.binance_service.new_listen_key.side_effect = Exception(
            "API error"
        )

        with pytest.raises(Exception) as exc_info:
            await listen_key_manager.start()

        assert "API error" in str(exc_info.value)
        assert listen_key_manager._running is False
        assert listen_key_manager.listen_key is None


class TestBinanceServiceListenKey:
    """Test BinanceService listen key methods."""

    @pytest.fixture
    def mock_client(self):
        """Create mock UMFutures client."""
        return MagicMock()

    @pytest.fixture
    def binance_service(self, mock_client):
        """Create BinanceServiceClient with mocked internal client."""
        with patch("src.core.binance_service.UMFutures", return_value=mock_client):
            service = BinanceServiceClient(
                api_key="test_key",
                api_secret="test_secret",
                is_testnet=True
            )
            service.client = mock_client
            return service

    def test_new_listen_key(self, binance_service, mock_client):
        """Test new_listen_key method calls underlying client."""
        mock_client.new_listen_key.return_value = {"listenKey": "new_key_123"}

        result = binance_service.new_listen_key()

        assert result == {"listenKey": "new_key_123"}
        mock_client.new_listen_key.assert_called_once()

    def test_renew_listen_key(self, binance_service, mock_client):
        """Test renew_listen_key method calls underlying client."""
        mock_client.renew_listen_key.return_value = {"listenKey": "renewed_key"}

        result = binance_service.renew_listen_key("test_key_123")

        assert result == {"listenKey": "renewed_key"}
        mock_client.renew_listen_key.assert_called_once_with(listenKey="test_key_123")

    def test_close_listen_key(self, binance_service, mock_client):
        """Test close_listen_key method calls underlying client with listen key."""
        mock_client.close_listen_key.return_value = {}

        result = binance_service.close_listen_key("test_key_123")

        assert result == {}
        mock_client.close_listen_key.assert_called_once_with(listenKey="test_key_123")


class TestDataCollectorUserDataStream:
    """Test DataCollector User Data Stream integration (Issue #57)."""

    @pytest.fixture
    def binance_service(self):
        """Create mock BinanceServiceClient."""
        service = MagicMock(spec=BinanceServiceClient)
        service.is_testnet = True
        service.new_listen_key.return_value = {"listenKey": "test_key"}
        service.renew_listen_key.return_value = {"listenKey": "test_key"}
        service.close_listen_key.return_value = {}
        return service

    @pytest.fixture
    def mock_market_streamer(self):
        """Create mock PublicMarketStreamer."""
        streamer = Mock(spec=PublicMarketStreamer)
        streamer.symbols = ["BTCUSDT"]
        streamer.intervals = ["1h"]
        streamer.is_connected = False
        streamer.on_candle_callback = None
        streamer.start = AsyncMock()
        streamer.stop = AsyncMock()
        return streamer

    @pytest.fixture
    def mock_user_streamer(self, binance_service):
        """Create mock PrivateUserStreamer with real-like behavior."""
        streamer = Mock(spec=PrivateUserStreamer)
        streamer.is_connected = False
        streamer.start = AsyncMock()
        streamer.stop = AsyncMock()
        streamer.set_order_fill_callback = Mock()
        streamer.set_position_update_callback = Mock()
        streamer.set_order_update_callback = Mock()
        return streamer

    @pytest.fixture
    def data_collector(self, binance_service, mock_market_streamer, mock_user_streamer):
        """Create BinanceDataCollector with mocked streamers."""
        return BinanceDataCollector(
            binance_service=binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

    @pytest.mark.asyncio
    async def test_start_user_streaming(self, data_collector, mock_user_streamer):
        """Test starting user data streaming via facade (Issue #124)."""
        await data_collector.start_user_streaming(order_fill_callback=lambda d: None)

        # Verify facade delegates to user_streamer
        mock_user_streamer.set_order_fill_callback.assert_called_once()
        mock_user_streamer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_user_streaming_without_user_streamer(
        self, binance_service, mock_market_streamer, caplog
    ):
        """Test that start_user_streaming() logs warning when user_streamer is None."""
        import logging

        data_collector = BinanceDataCollector(
            binance_service=binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )

        with caplog.at_level(logging.WARNING):
            await data_collector.start_user_streaming()

        assert "PrivateUserStreamer not configured" in caplog.text


class TestPrivateUserStreamerOrderHandling:
    """Test PrivateUserStreamer ORDER_TRADE_UPDATE event handling."""

    @pytest.fixture
    def binance_service(self):
        """Create mock BinanceServiceClient."""
        service = MagicMock(spec=BinanceServiceClient)
        service.is_testnet = True
        service.new_listen_key.return_value = {"listenKey": "test_key"}
        return service

    @pytest.fixture
    def user_streamer(self, binance_service):
        """Create PrivateUserStreamer instance."""
        return PrivateUserStreamer(
            binance_service=binance_service,
            is_testnet=True,
        )

    def test_handle_order_trade_update_tp_filled(self, user_streamer):
        """Test handling ORDER_TRADE_UPDATE for TP fill."""
        mock_callback = Mock()
        user_streamer.set_order_fill_callback(mock_callback)

        # Simulate ORDER_TRADE_UPDATE for TAKE_PROFIT_MARKET fill
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 123456789,
                "S": "SELL",
                "ot": "TAKE_PROFIT_MARKET",
                "q": "0.001",
                "ap": "51000",
                "sp": "51000",
                "X": "FILLED",
            },
        }

        # Call handler
        user_streamer._handle_order_trade_update(order_data)

        # Verify callback was called with order data
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0][0]
        assert call_args["s"] == "BTCUSDT"
        assert call_args["X"] == "FILLED"

    def test_handle_user_data_message_order_update(self, user_streamer):
        """Test _handle_user_data_message routes ORDER_TRADE_UPDATE correctly."""
        with patch.object(
            user_streamer, "_handle_order_trade_update"
        ) as mock_handler:
            message = {
                "e": "ORDER_TRADE_UPDATE",
                "o": {"s": "BTCUSDT", "X": "FILLED"},
            }

            user_streamer._handle_user_data_message(None, message)

            mock_handler.assert_called_once_with(message)

    def test_handle_user_data_message_account_update(self, user_streamer):
        """Test _handle_user_data_message handles ACCOUNT_UPDATE."""
        # Should not raise, just log
        message = {
            "e": "ACCOUNT_UPDATE",
            "a": {"m": "ORDER", "B": [], "P": []},
        }

        # Should not raise
        user_streamer._handle_user_data_message(None, message)

    def test_handle_user_data_message_json_string(self, user_streamer):
        """Test _handle_user_data_message parses JSON strings."""
        import json

        with patch.object(
            user_streamer, "_handle_order_trade_update"
        ) as mock_handler:
            message = json.dumps({
                "e": "ORDER_TRADE_UPDATE",
                "o": {"s": "BTCUSDT", "X": "NEW"},
            })

            user_streamer._handle_user_data_message(None, message)

            mock_handler.assert_called_once()

    def test_handle_order_trade_update_sl_filled(self, user_streamer):
        """Test handling ORDER_TRADE_UPDATE for SL fill."""
        mock_callback = Mock()
        user_streamer.set_order_fill_callback(mock_callback)

        # Simulate ORDER_TRADE_UPDATE for STOP_MARKET fill
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "ETHUSDT",
                "i": 987654321,
                "S": "SELL",
                "ot": "STOP_MARKET",
                "q": "0.1",
                "ap": "1800",
                "sp": "1800",
                "X": "FILLED",
            },
        }

        # Should not raise
        user_streamer._handle_order_trade_update(order_data)

        # Verify callback was called
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0][0]
        assert call_args["s"] == "ETHUSDT"
        assert call_args["X"] == "FILLED"

    def test_handle_order_trade_update_non_tpsl_ignored(self, user_streamer):
        """Test that MARKET order fills trigger callback relay."""
        mock_callback = Mock()
        user_streamer.set_order_fill_callback(mock_callback)

        # Simulate ORDER_TRADE_UPDATE for regular MARKET order
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 111222333,
                "S": "BUY",
                "ot": "MARKET",  # Not TP/SL
                "q": "0.001",
                "ap": "50000",
                "X": "FILLED",
            },
        }

        # Call handler - should trigger callback for MARKET orders too (Issue #97)
        user_streamer._handle_order_trade_update(order_data)

        # Verify callback was called
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0][0]
        assert call_args["s"] == "BTCUSDT"
        assert call_args["X"] == "FILLED"


class TestPositionClosureAuditLogging:
    """
    Test PrivateUserStreamer data relay behavior (Issue #87, #96).

    Note: Position closure audit logging was moved from PrivateUserStreamer
    to TradingEngine in Issue #96. These tests verify that PrivateUserStreamer
    correctly relays data WITHOUT performing business logic.
    """

    @pytest.fixture
    def binance_service(self):
        """Create mock BinanceServiceClient."""
        service = MagicMock(spec=BinanceServiceClient)
        service.is_testnet = True
        service.new_listen_key.return_value = {"listenKey": "test_key"}
        return service

    @pytest.fixture
    def user_streamer(self, binance_service):
        """Create PrivateUserStreamer instance."""
        return PrivateUserStreamer(
            binance_service=binance_service,
            is_testnet=True,
        )

    def test_tp_sl_fill_publishes_event_without_audit_logging(self, user_streamer):
        """
        Test that TP/SL fills trigger callback relay without audit logging.

        Issue #96: PrivateUserStreamer is now a pure data relay.
        Issue #107: Uses callback pattern instead of EventBus.
        Audit logging is handled by TradeCoordinator.on_order_filled.
        """
        mock_callback = Mock()
        user_streamer.set_order_fill_callback(mock_callback)

        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 123456789,
                "S": "SELL",
                "ot": "TAKE_PROFIT_MARKET",
                "q": "0.001",
                "z": "0.001",
                "ap": "51000",
                "sp": "51000",
                "X": "FILLED",
            },
        }

        # Should not raise any errors - just relays data
        user_streamer._handle_order_trade_update(order_data)

        # Verify callback was called
        mock_callback.assert_called_once()
        call_args = mock_callback.call_args[0][0]
        assert call_args["s"] == "BTCUSDT"
        assert call_args["X"] == "FILLED"


class TestEventType:
    """Test EventType enum includes ORDER_UPDATE."""

    def test_order_update_exists(self):
        """Verify ORDER_UPDATE event type exists."""
        assert hasattr(EventType, "ORDER_UPDATE")
        assert EventType.ORDER_UPDATE.value == "order_update"

    def test_order_filled_exists(self):
        """Verify ORDER_FILLED event type exists (used for publishing)."""
        assert hasattr(EventType, "ORDER_FILLED")
        assert EventType.ORDER_FILLED.value == "order_filled"
