"""
Unit tests for TradingBot signal processing pipeline (Subtask 10.3).

Tests the complete trading flow:
1. _on_candle_closed() - Strategy analysis and signal generation
2. _on_signal_generated() - Risk validation and order execution
3. _on_order_filled() - Order fill logging
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

from src.main import TradingBot
from src.models.event import EventType, Event
from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.models.order import Order, OrderSide, OrderStatus, OrderType
from src.models.position import Position


class TestOnCandleClosed:
    """Tests for TradingBot._on_candle_closed() handler."""

    @pytest.fixture
    def bot_with_mocks(self):
        """Create bot with mocked components."""
        bot = TradingBot()
        bot.strategy = Mock()
        bot.event_bus = Mock()
        bot.event_bus.publish = AsyncMock()
        bot.logger = Mock()
        return bot

    @pytest.mark.asyncio
    async def test_on_candle_closed_with_signal(self, bot_with_mocks):
        """Test signal generation and publishing."""
        # Create test candle
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

        # Create test signal
        test_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50050.0,
            take_profit=51050.0,
            stop_loss=49550.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

        # Mock strategy.analyze() to return signal
        bot_with_mocks.strategy.analyze = AsyncMock(return_value=test_signal)

        # Create event
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler
        await bot_with_mocks._on_candle_closed(event)

        # Verify strategy.analyze() was called
        bot_with_mocks.strategy.analyze.assert_called_once_with(candle)

        # Verify event was published
        assert bot_with_mocks.event_bus.publish.called, \
            "Should publish SIGNAL_GENERATED event"

        # Verify correct event type and queue
        call_args = bot_with_mocks.event_bus.publish.call_args
        published_event = call_args[0][0]
        queue_name = call_args.kwargs.get('queue_name')

        assert published_event.event_type == EventType.SIGNAL_GENERATED
        assert published_event.data == test_signal
        assert queue_name == 'signal', \
            "Should publish to 'signal' queue"

        # Verify info logging
        assert bot_with_mocks.logger.info.called

    @pytest.mark.asyncio
    async def test_on_candle_closed_no_signal(self, bot_with_mocks):
        """Test when strategy returns None (no signal)."""
        # Create test candle
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
            is_closed=True
        )

        # Mock strategy.analyze() to return None
        bot_with_mocks.strategy.analyze = AsyncMock(return_value=None)

        # Create event
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler
        await bot_with_mocks._on_candle_closed(event)

        # Verify strategy.analyze() was called
        bot_with_mocks.strategy.analyze.assert_called_once_with(candle)

        # Verify NO event was published
        assert not bot_with_mocks.event_bus.publish.called, \
            "Should NOT publish event when no signal"

        # Verify debug logging (no signal case)
        assert bot_with_mocks.logger.debug.called

    @pytest.mark.asyncio
    async def test_on_candle_closed_strategy_error(self, bot_with_mocks):
        """Test strategy exception handling."""
        # Create test candle
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

        # Mock strategy.analyze() to raise exception
        bot_with_mocks.strategy.analyze = AsyncMock(
            side_effect=Exception("Strategy calculation error")
        )

        # Create event
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler - should NOT raise exception
        await bot_with_mocks._on_candle_closed(event)

        # Verify error was logged
        assert bot_with_mocks.logger.error.called

        # Verify NO event was published
        assert not bot_with_mocks.event_bus.publish.called


class TestOnSignalGenerated:
    """Tests for TradingBot._on_signal_generated() handler."""

    @pytest.fixture
    def bot_with_mocks(self):
        """Create bot with fully mocked components."""
        bot = TradingBot()
        bot.order_manager = Mock()
        bot.risk_manager = Mock()
        bot.config_manager = Mock()
        bot.event_bus = Mock()
        bot.event_bus.publish = AsyncMock()
        bot.logger = Mock()
        return bot

    @pytest.fixture
    def test_signal(self):
        """Create test signal."""
        return Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=51000.0,
            stop_loss=49500.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

    @pytest.mark.asyncio
    async def test_on_signal_generated_success(self, bot_with_mocks, test_signal):
        """Test complete trading flow success."""
        # Setup mocks
        bot_with_mocks.order_manager.get_position.return_value = None  # No position
        bot_with_mocks.risk_manager.validate_risk.return_value = True
        bot_with_mocks.order_manager.get_account_balance.return_value = 10000.0
        bot_with_mocks.risk_manager.calculate_position_size.return_value = 0.1
        bot_with_mocks.config_manager.trading_config = Mock(leverage=10)

        # Create mock order
        entry_order = Order(
            order_id='12345',
            symbol='BTCUSDT',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=50000.0,
            status=OrderStatus.FILLED
        )
        bot_with_mocks.order_manager.execute_signal.return_value = (
            entry_order,
            []  # No TP/SL for simplicity
        )

        # Create event
        event = Event(EventType.SIGNAL_GENERATED, test_signal)

        # Call handler
        await bot_with_mocks._on_signal_generated(event)

        # Verify complete flow
        bot_with_mocks.order_manager.get_position.assert_called_once_with('BTCUSDT')
        bot_with_mocks.risk_manager.validate_risk.assert_called_once_with(
            test_signal, None
        )
        bot_with_mocks.order_manager.get_account_balance.assert_called_once()
        bot_with_mocks.risk_manager.calculate_position_size.assert_called_once()
        bot_with_mocks.order_manager.execute_signal.assert_called_once()

        # Verify ORDER_FILLED event published
        assert bot_with_mocks.event_bus.publish.called
        call_args = bot_with_mocks.event_bus.publish.call_args
        published_event = call_args[0][0]
        queue_name = call_args.kwargs.get('queue_name')

        assert published_event.event_type == EventType.ORDER_FILLED
        assert published_event.data == entry_order
        assert queue_name == 'order'

    @pytest.mark.asyncio
    async def test_on_signal_generated_risk_rejection(self, bot_with_mocks, test_signal):
        """Test risk validation rejection."""
        # Setup mocks - risk validation fails
        bot_with_mocks.order_manager.get_position.return_value = None
        bot_with_mocks.risk_manager.validate_risk.return_value = False

        # Create event
        event = Event(EventType.SIGNAL_GENERATED, test_signal)

        # Call handler
        await bot_with_mocks._on_signal_generated(event)

        # Verify flow stopped at risk validation
        bot_with_mocks.risk_manager.validate_risk.assert_called_once()
        assert not bot_with_mocks.order_manager.get_account_balance.called
        assert not bot_with_mocks.order_manager.execute_signal.called
        assert not bot_with_mocks.event_bus.publish.called

        # Verify warning logged
        assert bot_with_mocks.logger.warning.called

    @pytest.mark.asyncio
    async def test_on_signal_generated_existing_position(self, bot_with_mocks, test_signal):
        """Test rejection due to existing position."""
        # Setup mocks - existing position
        existing_position = Position(
            symbol='BTCUSDT',
            side='LONG',
            entry_price=49000.0,
            quantity=0.1,
            leverage=10
        )
        bot_with_mocks.order_manager.get_position.return_value = existing_position
        bot_with_mocks.risk_manager.validate_risk.return_value = False

        # Create event
        event = Event(EventType.SIGNAL_GENERATED, test_signal)

        # Call handler
        await bot_with_mocks._on_signal_generated(event)

        # Verify rejected by risk validation
        bot_with_mocks.risk_manager.validate_risk.assert_called_once_with(
            test_signal, existing_position
        )
        assert not bot_with_mocks.order_manager.execute_signal.called

    @pytest.mark.asyncio
    async def test_on_signal_generated_zero_balance(self, bot_with_mocks, test_signal):
        """Test rejection due to zero/negative balance."""
        # Setup mocks
        bot_with_mocks.order_manager.get_position.return_value = None
        bot_with_mocks.risk_manager.validate_risk.return_value = True
        bot_with_mocks.order_manager.get_account_balance.return_value = 0.0

        # Create event
        event = Event(EventType.SIGNAL_GENERATED, test_signal)

        # Call handler
        await bot_with_mocks._on_signal_generated(event)

        # Verify stopped at balance check
        assert not bot_with_mocks.risk_manager.calculate_position_size.called
        assert not bot_with_mocks.order_manager.execute_signal.called

        # Verify error logged
        assert bot_with_mocks.logger.error.called

    @pytest.mark.asyncio
    async def test_on_signal_generated_execution_error(self, bot_with_mocks, test_signal):
        """Test order execution failure."""
        # Setup mocks
        bot_with_mocks.order_manager.get_position.return_value = None
        bot_with_mocks.risk_manager.validate_risk.return_value = True
        bot_with_mocks.order_manager.get_account_balance.return_value = 10000.0
        bot_with_mocks.risk_manager.calculate_position_size.return_value = 0.1
        bot_with_mocks.config_manager.trading_config = Mock(leverage=10)

        # Mock execute_signal to raise exception
        bot_with_mocks.order_manager.execute_signal.side_effect = Exception(
            "Order execution failed"
        )

        # Create event
        event = Event(EventType.SIGNAL_GENERATED, test_signal)

        # Call handler - should NOT raise exception
        await bot_with_mocks._on_signal_generated(event)

        # Verify error was logged
        assert bot_with_mocks.logger.error.called

        # Verify NO ORDER_FILLED event published
        assert not bot_with_mocks.event_bus.publish.called


class TestOnOrderFilled:
    """Tests for TradingBot._on_order_filled() handler."""

    @pytest.fixture
    def bot_with_mocks(self):
        """Create bot with logger."""
        bot = TradingBot()
        bot.logger = Mock()
        return bot

    @pytest.mark.asyncio
    async def test_on_order_filled(self, bot_with_mocks):
        """Test order fill logging."""
        # Create test order
        order = Order(
            order_id='ORDER123',
            symbol='BTCUSDT',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=50000.0,
            status=OrderStatus.FILLED
        )

        # Create event
        event = Event(EventType.ORDER_FILLED, order)

        # Call handler
        await bot_with_mocks._on_order_filled(event)

        # Verify logging
        assert bot_with_mocks.logger.info.called

        # Verify log contains order details
        log_message = str(bot_with_mocks.logger.info.call_args)
        assert 'ORDER123' in log_message
        assert 'BTCUSDT' in log_message
        assert '0.1' in log_message


class TestSignalProcessingIntegration:
    """Integration tests for complete signal processing flow."""

    @pytest.mark.asyncio
    async def test_complete_trading_flow(self):
        """Test full flow from candle to order."""
        # This is a simplified integration test
        # Full integration would use real EventBus

        bot = TradingBot()
        bot.strategy = Mock()
        bot.order_manager = Mock()
        bot.risk_manager = Mock()
        bot.config_manager = Mock()
        bot.event_bus = Mock()
        bot.event_bus.publish = AsyncMock()
        bot.logger = Mock()

        # Create test signal
        test_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=51000.0,
            stop_loss=49500.0,
            strategy_name='TestStrategy',
            timestamp=datetime.now(timezone.utc)
        )

        # Create test order
        entry_order = Order(
            order_id='ORDER123',
            symbol='BTCUSDT',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=50000.0,
            status=OrderStatus.FILLED
        )

        # Setup mocks for complete flow
        bot.strategy.analyze = AsyncMock(return_value=test_signal)
        bot.order_manager.get_position.return_value = None
        bot.risk_manager.validate_risk.return_value = True
        bot.order_manager.get_account_balance.return_value = 10000.0
        bot.risk_manager.calculate_position_size.return_value = 0.1
        bot.config_manager.trading_config = Mock(leverage=10)
        bot.order_manager.execute_signal.return_value = (entry_order, [])

        # Step 1: Simulate CANDLE_CLOSED event
        candle = Candle(
            symbol='BTCUSDT', interval='1m',
            open_time=1000000, close_time=1060000,
            open=50000.0, high=50100.0, low=49900.0,
            close=50050.0, volume=100.0, is_closed=True
        )
        candle_event = Event(EventType.CANDLE_CLOSED, candle)
        await bot._on_candle_closed(candle_event)

        # Verify signal event was published
        assert bot.event_bus.publish.call_count >= 1
        first_call = bot.event_bus.publish.call_args_list[0]
        assert first_call[0][0].event_type == EventType.SIGNAL_GENERATED

        # Step 2: Simulate SIGNAL_GENERATED event
        signal_event = Event(EventType.SIGNAL_GENERATED, test_signal)
        await bot._on_signal_generated(signal_event)

        # Verify order event was published
        assert bot.event_bus.publish.call_count >= 2
        second_call = bot.event_bus.publish.call_args_list[1]
        assert second_call[0][0].event_type == EventType.ORDER_FILLED

        # Step 3: Simulate ORDER_FILLED event
        order_event = Event(EventType.ORDER_FILLED, entry_order)
        await bot._on_order_filled(order_event)

        # Verify complete flow executed
        bot.strategy.analyze.assert_called_once()
        bot.order_manager.execute_signal.assert_called_once()
        assert bot.logger.info.call_count >= 3  # Multiple info logs
