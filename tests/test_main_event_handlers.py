"""
Unit tests for TradingBot event handler setup (Subtask 10.2).

Tests the event wiring between components:
1. _setup_event_handlers() correctly subscribes to all event types
2. _on_candle_received() bridges WebSocket callbacks to EventBus
3. Event type differentiation (CANDLE_CLOSED vs CANDLE_UPDATE)
4. Non-blocking async publish pattern
5. Debug logging for closed candles
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, call, AsyncMock
from src.main import TradingBot
from src.models.event import EventType, Event
from src.models.candle import Candle


class TestSetupEventHandlers:
    """Tests for TradingBot._setup_event_handlers() method."""

    @patch('src.main.ConfigManager')
    @patch('src.main.TradingLogger')
    @patch('src.main.BinanceDataCollector')
    @patch('src.main.OrderExecutionManager')
    @patch('src.main.RiskManager')
    @patch('src.main.StrategyFactory')
    @patch('src.main.EventBus')
    @patch('logging.getLogger')
    def test_setup_event_handlers_subscribes_to_all_events(
        self,
        mock_get_logger,
        mock_event_bus_class,
        mock_strategy_factory,
        mock_risk_manager,
        mock_order_manager,
        mock_data_collector,
        mock_trading_logger,
        mock_config_manager
    ):
        """Test _setup_event_handlers subscribes to all required event types."""
        # Setup ConfigManager mock
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key='test_key',
            api_secret='test_secret',
            is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol='BTCUSDT',
            intervals=['1m'],
            strategy='mock_sma',
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {}
        mock_config_manager.return_value = config_instance

        # Setup OrderManager mock
        mock_order_instance = Mock()
        mock_order_instance.set_leverage.return_value = True
        mock_order_manager.return_value = mock_order_instance

        # Setup EventBus mock
        mock_event_bus_instance = Mock()
        mock_event_bus_class.return_value = mock_event_bus_instance

        # Setup logger mock
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Execute
        bot = TradingBot()
        bot.initialize()

        # Verify EventBus subscribe calls
        assert mock_event_bus_instance.subscribe.call_count == 3, \
            "Should subscribe to 3 event types"

        # Verify specific subscriptions
        subscribe_calls = mock_event_bus_instance.subscribe.call_args_list

        # Extract event types from calls
        subscribed_event_types = [call[0][0] for call in subscribe_calls]

        assert EventType.CANDLE_CLOSED in subscribed_event_types, \
            "Should subscribe to CANDLE_CLOSED"
        assert EventType.SIGNAL_GENERATED in subscribed_event_types, \
            "Should subscribe to SIGNAL_GENERATED"
        assert EventType.ORDER_FILLED in subscribed_event_types, \
            "Should subscribe to ORDER_FILLED"

    @patch('src.main.ConfigManager')
    @patch('src.main.TradingLogger')
    @patch('src.main.BinanceDataCollector')
    @patch('src.main.OrderExecutionManager')
    @patch('src.main.RiskManager')
    @patch('src.main.StrategyFactory')
    @patch('src.main.EventBus')
    @patch('logging.getLogger')
    def test_setup_event_handlers_passes_correct_callbacks(
        self,
        mock_get_logger,
        mock_event_bus_class,
        mock_strategy_factory,
        mock_risk_manager,
        mock_order_manager,
        mock_data_collector,
        mock_trading_logger,
        mock_config_manager
    ):
        """Test event handlers are wired to correct callback methods."""
        # Setup mocks (same as previous test)
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key='test_key',
            api_secret='test_secret',
            is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol='BTCUSDT',
            intervals=['1m'],
            strategy='mock_sma',
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {}
        mock_config_manager.return_value = config_instance

        mock_order_instance = Mock()
        mock_order_instance.set_leverage.return_value = True
        mock_order_manager.return_value = mock_order_instance

        mock_event_bus_instance = Mock()
        mock_event_bus_class.return_value = mock_event_bus_instance

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Execute
        bot = TradingBot()
        bot.initialize()

        # Verify callback references (not calls)
        subscribe_calls = mock_event_bus_instance.subscribe.call_args_list

        # Create mapping of event type to callback
        event_to_callback = {
            call[0][0]: call[0][1] for call in subscribe_calls
        }

        assert event_to_callback[EventType.CANDLE_CLOSED] == bot._on_candle_closed, \
            "CANDLE_CLOSED should map to _on_candle_closed"
        assert event_to_callback[EventType.SIGNAL_GENERATED] == bot._on_signal_generated, \
            "SIGNAL_GENERATED should map to _on_signal_generated"
        assert event_to_callback[EventType.ORDER_FILLED] == bot._on_order_filled, \
            "ORDER_FILLED should map to _on_order_filled"


class TestOnCandleReceived:
    """Tests for TradingBot._on_candle_received() callback method."""

    @pytest.fixture
    def bot_with_mocks(self):
        """Create bot with mocked components for testing."""
        bot = TradingBot()
        bot.event_bus = Mock()
        bot.event_bus.publish = AsyncMock()
        bot.logger = Mock()
        return bot

    @pytest.mark.asyncio
    async def test_on_candle_received_closed_candle(self, bot_with_mocks):
        """Test _on_candle_received correctly handles closed candles."""
        # Create closed candle
        candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=1000000,
            close_time=1060000,
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            is_closed=True
        )

        # Call method
        bot_with_mocks._on_candle_received(candle)

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Verify event was published
        assert bot_with_mocks.event_bus.publish.called, \
            "EventBus.publish should be called"

        # Verify correct event type and data
        call_args = bot_with_mocks.event_bus.publish.call_args
        event = call_args[0][0]
        queue_name = call_args.kwargs.get('queue_name')

        assert event.event_type == EventType.CANDLE_CLOSED, \
            "Closed candle should create CANDLE_CLOSED event"
        assert event.data == candle, \
            "Event should contain candle data"
        assert queue_name == 'data', \
            "Should publish to 'data' queue"

        # Verify debug logging for closed candle
        assert bot_with_mocks.logger.debug.called, \
            "Should log closed candle"
        debug_message = str(bot_with_mocks.logger.debug.call_args)
        assert 'BTCUSDT' in debug_message, \
            "Debug log should contain symbol"
        assert '1m' in debug_message, \
            "Debug log should contain interval"

    @pytest.mark.asyncio
    async def test_on_candle_received_update_candle(self, bot_with_mocks):
        """Test _on_candle_received correctly handles candle updates."""
        # Create update candle (not closed)
        candle = Candle(
            symbol='BTCUSDT',
            interval='5m',
            open_time=1000000,
            close_time=1300000,
            open=50000.0,
            high=50200.0,
            low=49800.0,
            close=50100.0,
            volume=150.0,
            is_closed=False  # Update, not closed
        )

        # Call method
        bot_with_mocks._on_candle_received(candle)

        # Wait for async task to complete
        await asyncio.sleep(0.1)

        # Verify event was published
        assert bot_with_mocks.event_bus.publish.called, \
            "EventBus.publish should be called"

        # Verify correct event type
        call_args = bot_with_mocks.event_bus.publish.call_args
        event = call_args[0][0]

        assert event.event_type == EventType.CANDLE_UPDATE, \
            "Update candle should create CANDLE_UPDATE event"
        assert event.data == candle, \
            "Event should contain candle data"

        # Verify NO debug logging for updates (avoid spam)
        assert not bot_with_mocks.logger.debug.called, \
            "Should NOT log candle updates to avoid spam"

    @pytest.mark.asyncio
    async def test_on_candle_received_non_blocking(self, bot_with_mocks):
        """Test _on_candle_received is non-blocking (uses asyncio.create_task)."""
        # Create slow-publishing event bus
        slow_publish_event = asyncio.Event()

        async def slow_publish(event, queue_name='data'):
            await slow_publish_event.wait()  # Block until signaled

        bot_with_mocks.event_bus.publish = slow_publish

        # Create candle
        candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=1000000,
            close_time=1060000,
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            is_closed=True
        )

        # Call method - should return immediately even though publish is blocked
        bot_with_mocks._on_candle_received(candle)

        # Method should return immediately (non-blocking)
        # If it blocks, this assertion will hang

        # Verify we can continue without waiting
        assert True, "Method returned immediately (non-blocking)"

        # Signal publish to complete
        slow_publish_event.set()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_on_candle_received_multiple_candles(self, bot_with_mocks):
        """Test _on_candle_received handles multiple candles correctly."""
        # Create multiple candles (mix of closed and updates)
        candles = [
            Candle(
                symbol='BTCUSDT', interval='1m', open_time=i * 60000,
                close_time=(i + 1) * 60000, open=50000.0 + i,
                high=50100.0 + i, low=49900.0 + i, close=50050.0 + i,
                volume=100.0, is_closed=(i % 2 == 0)  # Every other closed
            )
            for i in range(5)
        ]

        # Process all candles
        for candle in candles:
            bot_with_mocks._on_candle_received(candle)

        # Wait for all async tasks
        await asyncio.sleep(0.2)

        # Verify all events were published
        assert bot_with_mocks.event_bus.publish.call_count == 5, \
            "Should publish 5 events"

        # Verify closed candles were logged
        debug_call_count = bot_with_mocks.logger.debug.call_count
        closed_count = sum(1 for c in candles if c.is_closed)
        assert debug_call_count == closed_count, \
            f"Should log {closed_count} closed candles"


class TestEventHandlerIntegration:
    """Integration tests for event handler system."""

    @pytest.mark.asyncio
    async def test_event_flow_from_websocket_to_eventbus(self):
        """Test complete event flow from WebSocket callback to EventBus."""
        # Create bot with real EventBus
        with patch('src.main.ConfigManager') as mock_config, \
             patch('src.main.TradingLogger'), \
             patch('src.main.BinanceDataCollector'), \
             patch('src.main.OrderExecutionManager') as mock_order, \
             patch('src.main.RiskManager'), \
             patch('src.main.StrategyFactory'), \
             patch('logging.getLogger'):

            # Setup config
            config_instance = Mock()
            config_instance.validate.return_value = True
            config_instance.api_config = Mock(
                api_key='test', api_secret='test', is_testnet=True
            )
            config_instance.trading_config = Mock(
                symbol='BTCUSDT', intervals=['1m'], strategy='mock',
                leverage=10, max_risk_per_trade=0.01,
                take_profit_ratio=2.0, stop_loss_percent=0.01
            )
            config_instance.logging_config = Mock()
            config_instance.logging_config.__dict__ = {}
            mock_config.return_value = config_instance

            mock_order_instance = Mock()
            mock_order_instance.set_leverage.return_value = True
            mock_order.return_value = mock_order_instance

            bot = TradingBot()
            bot.initialize()

            # Mock the EventBus publish method to capture events
            published_events = []

            async def capture_publish(event, queue_name='data'):
                published_events.append((event, queue_name))
                # Don't actually publish to avoid needing running event loop
                return

            bot.event_bus.publish = capture_publish

            # Simulate WebSocket callback with closed candle
            candle = Candle(
                symbol='BTCUSDT', interval='1m',
                open_time=1000000, close_time=1060000,
                open=50000.0, high=50100.0, low=49900.0,
                close=50050.0, volume=100.0, is_closed=True
            )

            bot._on_candle_received(candle)

            # Wait for async task to complete
            await asyncio.sleep(0.1)

            # Verify event was published
            assert len(published_events) == 1, \
                "Should publish exactly one event"

            # Verify event data
            event, queue_name = published_events[0]
            assert event.event_type == EventType.CANDLE_CLOSED, \
                "Event type should be CANDLE_CLOSED"
            assert event.data == candle, \
                "Event data should be the candle"
            assert queue_name == 'data', \
                "Should publish to 'data' queue"
