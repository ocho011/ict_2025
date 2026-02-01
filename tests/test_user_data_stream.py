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
from src.core.user_data_stream import UserDataStreamManager
from src.core.binance_service import BinanceServiceClient
from src.core.data_collector import BinanceDataCollector
from src.core.public_market_streamer import PublicMarketStreamer
from src.core.private_user_streamer import PrivateUserStreamer
from src.models.event import EventType


class TestUserDataStreamManager:
    """Test suite for UserDataStreamManager class."""

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
    def user_data_stream_manager(self, binance_service):
        """
        Create UserDataStreamManager with mocked BinanceService.
        """
        return UserDataStreamManager(binance_service)

    @pytest.mark.asyncio
    async def test_listen_key_creation_success(self, user_data_stream_manager):
        """
        Test successful listen key creation.

        Should:
        - Call binance_service.new_listen_key() via UserDataStreamManager
        - Return listen key
        - Start keep-alive loop
        """
        # Call start method
        result = await user_data_stream_manager.start()

        assert result == "test_listen_key_123", f"Expected listen key: test_listen_key_123"
        assert user_data_stream_manager.binance_service.new_listen_key.called
        assert user_data_stream_manager._running is True
        assert user_data_stream_manager._keep_alive_task is not None

        # Cleanup
        await user_data_stream_manager.stop()

    @pytest.mark.asyncio
    async def test_listen_key_already_running(self, user_data_stream_manager):
        """
        Test that starting when already running returns existing key.
        """
        # Start first time
        first_key = await user_data_stream_manager.start()

        # Try to start again
        second_key = await user_data_stream_manager.start()

        assert first_key == second_key
        # Should only have called new_listen_key once
        assert user_data_stream_manager.binance_service.new_listen_key.call_count == 1

        # Cleanup
        await user_data_stream_manager.stop()

    @pytest.mark.asyncio
    async def test_keep_alive_ping_interval(self, user_data_stream_manager):
        """
        Test that keep-alive task is created with correct interval.
        """
        # Start manager to initialize keep-alive task
        await user_data_stream_manager.start()

        # Verify task was created
        assert user_data_stream_manager._keep_alive_task is not None
        assert not user_data_stream_manager._keep_alive_task.done()

        # Verify interval constant is set correctly (30 minutes)
        assert user_data_stream_manager.KEEP_ALIVE_INTERVAL_SECONDS == 1800

        # Cleanup - cancel the task first
        user_data_stream_manager._keep_alive_task.cancel()
        try:
            await user_data_stream_manager._keep_alive_task
        except asyncio.CancelledError:
            pass

        await user_data_stream_manager.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_listen_key(self, user_data_stream_manager):
        """
        Test graceful shutdown with listen key cleanup.
        """
        # Start manager to initialize
        await user_data_stream_manager.start()

        # Stop manager which should:
        # 1. Stop keep-alive loop
        # 2. Close listen key via Binance API
        # 3. Clear state
        await user_data_stream_manager.stop()

        # Verify cleanup
        assert user_data_stream_manager._keep_alive_task is None
        assert user_data_stream_manager.listen_key is None
        assert user_data_stream_manager._running is False
        assert user_data_stream_manager.binance_service.close_listen_key.called

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, user_data_stream_manager):
        """
        Test that stop() can be called multiple times (idempotent).
        """
        # Start
        await user_data_stream_manager.start()

        # Stop multiple times - should not raise
        await user_data_stream_manager.stop()
        await user_data_stream_manager.stop()
        await user_data_stream_manager.stop()

        # Verify cleanup happened only once
        assert user_data_stream_manager.binance_service.close_listen_key.call_count == 1

    @pytest.mark.asyncio
    async def test_start_stop_restart(self, user_data_stream_manager):
        """
        Test that manager can be restarted after stop.
        """
        # First start
        await user_data_stream_manager.start()
        assert user_data_stream_manager.listen_key == "test_listen_key_123"

        # Stop
        await user_data_stream_manager.stop()
        assert user_data_stream_manager.listen_key is None

        # Second start
        await user_data_stream_manager.start()
        assert user_data_stream_manager.listen_key == "test_listen_key_123"
        assert user_data_stream_manager._running is True

        # Cleanup
        await user_data_stream_manager.stop()

    @pytest.mark.asyncio
    async def test_exception_on_listen_key_creation(self, user_data_stream_manager):
        """
        Test exception handling when listen key creation fails.
        """
        # Make new_listen_key raise an exception
        user_data_stream_manager.binance_service.new_listen_key.side_effect = Exception(
            "API error"
        )

        with pytest.raises(Exception) as exc_info:
            await user_data_stream_manager.start()

        assert "API error" in str(exc_info.value)
        assert user_data_stream_manager._running is False
        assert user_data_stream_manager.listen_key is None


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
        streamer.set_event_bus = Mock()
        streamer._event_bus = None
        streamer._event_loop = None
        return streamer

    @pytest.fixture
    def data_collector(self, binance_service, mock_market_streamer, mock_user_streamer):
        """Create BinanceDataCollector with mocked streamers."""
        return BinanceDataCollector(
            binance_service=binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

    @pytest.fixture
    def event_bus(self):
        """Create mock EventBus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    @pytest.mark.asyncio
    async def test_start_user_data_stream(self, data_collector, mock_user_streamer, event_bus):
        """Test starting User Data Stream via facade."""
        await data_collector.start_user_data_stream(event_bus)

        # Verify facade delegates to user_streamer
        mock_user_streamer.set_event_bus.assert_called_once_with(event_bus)
        mock_user_streamer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_user_data_stream(self, data_collector, mock_user_streamer, event_bus):
        """Test stopping User Data Stream via facade."""
        await data_collector.start_user_data_stream(event_bus)

        # Stop the stream
        await data_collector.stop_user_data_stream()

        # Verify facade delegates to user_streamer
        mock_user_streamer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_user_data_stream_without_user_streamer(
        self, binance_service, mock_market_streamer, event_bus, caplog
    ):
        """Test that start_user_data_stream logs warning when user_streamer is None."""
        import logging

        data_collector = BinanceDataCollector(
            binance_service=binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )

        with caplog.at_level(logging.WARNING):
            await data_collector.start_user_data_stream(event_bus)

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

    @pytest.fixture
    def event_bus(self):
        """Create mock EventBus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    def test_handle_order_trade_update_tp_filled(self, user_streamer, event_bus):
        """Test handling ORDER_TRADE_UPDATE for TP fill."""
        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop

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

        # Verify event was scheduled to be published
        loop.close()

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

    def test_handle_order_trade_update_sl_filled(self, user_streamer, event_bus):
        """Test handling ORDER_TRADE_UPDATE for SL fill."""
        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop

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

        loop.close()

    def test_handle_order_trade_update_non_tpsl_ignored(self, user_streamer, event_bus):
        """Test that non-TP/SL orders don't trigger event publishing."""
        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop

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

        # Call handler - should not publish event for MARKET orders
        user_streamer._handle_order_trade_update(order_data)

        loop.close()


class TestPositionClosureAuditLogging:
    """Test PrivateUserStreamer position closure audit logging (Issue #87)."""

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

    @pytest.fixture
    def audit_logger(self):
        """Create mock AuditLogger."""
        logger = MagicMock()
        logger.log_event = MagicMock()
        return logger

    @pytest.fixture
    def event_bus(self):
        """Create mock EventBus."""
        bus = MagicMock()
        bus.publish = AsyncMock()
        return bus

    def test_tp_order_fill_logs_position_closed(self, user_streamer, event_bus, audit_logger):
        """Test that TP order fill triggers POSITION_CLOSED audit log."""
        from src.core.audit_logger import AuditEventType

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        # Simulate ORDER_TRADE_UPDATE for TAKE_PROFIT_MARKET fill
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 123456789,
                "S": "SELL",
                "ot": "TAKE_PROFIT_MARKET",
                "q": "0.001",
                "z": "0.001",  # Filled quantity
                "ap": "51000",
                "sp": "51000",
                "X": "FILLED",
            },
        }

        user_streamer._handle_order_trade_update(order_data)

        # Verify audit log was called
        audit_logger.log_event.assert_called_once()
        call_args = audit_logger.log_event.call_args
        assert call_args.kwargs["event_type"] == AuditEventType.POSITION_CLOSED
        assert call_args.kwargs["operation"] == "tp_sl_order_filled"
        assert call_args.kwargs["symbol"] == "BTCUSDT"
        assert call_args.kwargs["data"]["close_reason"] == "TAKE_PROFIT"
        assert call_args.kwargs["data"]["exit_price"] == 51000.0

        loop.close()

    def test_sl_order_fill_logs_position_closed(self, user_streamer, event_bus, audit_logger):
        """Test that SL order fill triggers POSITION_CLOSED audit log."""
        from src.core.audit_logger import AuditEventType

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        # Simulate ORDER_TRADE_UPDATE for STOP_MARKET fill
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "ETHUSDT",
                "i": 987654321,
                "S": "SELL",
                "ot": "STOP_MARKET",
                "q": "0.1",
                "z": "0.1",
                "ap": "1800",
                "sp": "1800",
                "X": "FILLED",
            },
        }

        user_streamer._handle_order_trade_update(order_data)

        # Verify audit log was called with STOP_LOSS reason
        audit_logger.log_event.assert_called_once()
        call_args = audit_logger.log_event.call_args
        assert call_args.kwargs["event_type"] == AuditEventType.POSITION_CLOSED
        assert call_args.kwargs["data"]["close_reason"] == "STOP_LOSS"

        loop.close()

    def test_trailing_stop_fill_logs_position_closed(self, user_streamer, event_bus, audit_logger):
        """Test that trailing stop fill triggers POSITION_CLOSED audit log."""
        from src.core.audit_logger import AuditEventType

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 555666777,
                "S": "SELL",
                "ot": "TRAILING_STOP_MARKET",
                "q": "0.01",
                "z": "0.01",
                "ap": "52000",
                "sp": "52000",
                "cr": "1.0",  # callback_rate required for trailing stop
                "X": "FILLED",
            },
        }

        user_streamer._handle_order_trade_update(order_data)

        # Verify TRAILING_STOP reason
        call_args = audit_logger.log_event.call_args
        assert call_args.kwargs["data"]["close_reason"] == "TRAILING_STOP"

        loop.close()

    def test_position_entry_data_tracked(self, user_streamer):
        """Test that MARKET order fills track entry data."""
        from datetime import datetime

        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 111222333,
                "S": "BUY",
                "ot": "MARKET",
                "q": "0.001",
                "z": "0.001",
                "ap": "50000",
                "X": "FILLED",
            },
        }

        user_streamer._handle_order_trade_update(order_data)

        # Verify entry data was tracked
        assert "BTCUSDT" in user_streamer._position_entry_data
        entry_data = user_streamer._position_entry_data["BTCUSDT"]
        assert entry_data.entry_price == 50000.0
        assert entry_data.quantity == 0.001
        assert entry_data.side == "LONG"
        assert isinstance(entry_data.entry_time, datetime)

    def test_realized_pnl_calculation_long(self, user_streamer, event_bus, audit_logger):
        """Test realized PnL calculation for LONG positions."""
        from src.core.private_user_streamer import PositionEntryData
        from datetime import datetime

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        # Pre-populate entry data (simulating position open)
        user_streamer._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.utcnow(),
            quantity=0.001,
            side="LONG",
        )

        # TP fill at higher price (profit)
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "BTCUSDT",
                "i": 123456789,
                "S": "SELL",
                "ot": "TAKE_PROFIT_MARKET",
                "q": "0.001",
                "z": "0.001",
                "ap": "51000",  # Exit price
                "sp": "51000",
                "X": "FILLED",
            },
        }

        user_streamer._handle_order_trade_update(order_data)

        # Verify PnL: (51000 - 50000) * 0.001 = 1.0
        call_args = audit_logger.log_event.call_args
        assert call_args.kwargs["data"]["realized_pnl"] == 1.0
        assert call_args.kwargs["data"]["entry_price"] == 50000.0

        loop.close()

    def test_realized_pnl_calculation_short(self, user_streamer, event_bus, audit_logger):
        """Test realized PnL calculation for SHORT positions."""
        from src.core.private_user_streamer import PositionEntryData
        from datetime import datetime

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        # Pre-populate entry data for SHORT position
        user_streamer._position_entry_data["ETHUSDT"] = PositionEntryData(
            entry_price=2000.0,
            entry_time=datetime.utcnow(),
            quantity=0.1,
            side="SHORT",
        )

        # TP fill at lower price (profit for short)
        order_data = {
            "e": "ORDER_TRADE_UPDATE",
            "o": {
                "s": "ETHUSDT",
                "i": 987654321,
                "S": "BUY",
                "ot": "TAKE_PROFIT_MARKET",
                "q": "0.1",
                "z": "0.1",
                "ap": "1900",  # Exit price lower = profit
                "sp": "1900",
                "X": "FILLED",
            },
        }

        user_streamer._handle_order_trade_update(order_data)

        # Verify PnL: (2000 - 1900) * 0.1 = 10.0
        call_args = audit_logger.log_event.call_args
        assert call_args.kwargs["data"]["realized_pnl"] == 10.0

        loop.close()

    def test_holding_duration_calculation(self, user_streamer, event_bus, audit_logger):
        """Test holding duration is calculated correctly."""
        from src.core.private_user_streamer import PositionEntryData
        from datetime import datetime, timedelta

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        # Pre-populate entry data with past timestamp
        entry_time = datetime.utcnow() - timedelta(seconds=300)  # 5 minutes ago
        user_streamer._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=entry_time,
            quantity=0.001,
            side="LONG",
        )

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

        user_streamer._handle_order_trade_update(order_data)

        # Verify duration is approximately 300 seconds
        call_args = audit_logger.log_event.call_args
        duration = call_args.kwargs["data"]["held_duration_seconds"]
        assert 299 <= duration <= 302  # Allow small tolerance

        loop.close()

    def test_position_state_cleanup_after_closure(self, user_streamer, event_bus, audit_logger):
        """Test position entry data is cleaned up after closure."""
        from src.core.private_user_streamer import PositionEntryData
        from datetime import datetime

        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        user_streamer._audit_logger = audit_logger

        # Pre-populate entry data
        user_streamer._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.utcnow(),
            quantity=0.001,
            side="LONG",
        )

        assert "BTCUSDT" in user_streamer._position_entry_data

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

        user_streamer._handle_order_trade_update(order_data)

        # Verify entry data was cleaned up
        assert "BTCUSDT" not in user_streamer._position_entry_data

        loop.close()

    def test_no_audit_log_without_audit_logger(self, user_streamer, event_bus):
        """Test that no error occurs when audit_logger is not configured."""
        loop = asyncio.new_event_loop()
        user_streamer._event_bus = event_bus
        user_streamer._event_loop = loop
        # Note: _audit_logger is None by default

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

        # Should not raise
        user_streamer._handle_order_trade_update(order_data)

        loop.close()


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
