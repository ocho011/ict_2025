"""
Unit tests for data models
"""

from datetime import datetime

import pytest

from src.models import (
    Candle,
    Event,
    EventType,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Signal,
    SignalType,
)


class TestCandle:
    """Tests for Candle dataclass"""

    def test_valid_bullish_candle(self):
        """Test creating a valid bullish candle"""
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime(2025, 1, 1, 0, 0),
            open=50000.0,
            high=51000.0,
            low=49500.0,
            close=50800.0,
            volume=100.5,
            close_time=datetime(2025, 1, 1, 0, 5), is_closed=True,
        )

        assert candle.is_bullish is True
        assert candle.body_size == 800.0
        assert candle.upper_wick == 200.0
        assert candle.lower_wick == 500.0
        assert candle.total_range == 1500.0

    def test_valid_bearish_candle(self):
        """Test creating a valid bearish candle"""
        candle = Candle(
            symbol="ETHUSDT",
            interval="1h",
            open_time=datetime(2025, 1, 1, 0, 0),
            open=3000.0,
            high=3100.0,
            low=2900.0,
            close=2950.0,
            volume=50.0,
            close_time=datetime(2025, 1, 1, 1, 0),
            is_closed=True,
        )

        assert candle.is_bullish is False
        assert candle.body_size == 50.0
        assert candle.upper_wick == 100.0
        assert candle.lower_wick == 50.0

    def test_invalid_high_raises_error(self):
        """Test that invalid high price raises ValueError"""
        with pytest.raises(ValueError, match="High.*must be"):
            Candle(
                symbol="BTCUSDT",
                interval="5m",
                open_time=datetime(2025, 1, 1),
                open=50000.0,
                high=49000.0,  # Invalid: high < close
                low=48000.0,
                close=50000.0,
                volume=100.0,
                close_time=datetime(2025, 1, 1, 0, 5), is_closed=True,
            )

    def test_invalid_low_raises_error(self):
        """Test that invalid low price raises ValueError"""
        with pytest.raises(ValueError, match="Low.*must be"):
            Candle(
                symbol="BTCUSDT",
                interval="5m",
                open_time=datetime(2025, 1, 1),
                open=50000.0,
                high=51000.0,
                low=51000.0,  # Invalid: low > open
                close=50500.0,
                volume=100.0,
                close_time=datetime(2025, 1, 1, 0, 5), is_closed=True,
            )

    def test_negative_volume_raises_error(self):
        """Test that negative volume raises ValueError"""
        with pytest.raises(ValueError, match="Volume.*cannot be negative"):
            Candle(
                symbol="BTCUSDT",
                interval="5m",
                open_time=datetime(2025, 1, 1),
                open=50000.0,
                high=51000.0,
                low=49000.0,
                close=50500.0,
                volume=-10.0,  # Invalid
                close_time=datetime(2025, 1, 1, 0, 5),
                is_closed=True,
            )


class TestSignal:
    """Tests for Signal dataclass"""

    def test_valid_long_entry_signal(self):
        """Test creating a valid LONG_ENTRY signal"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            strategy_name="test_strategy",
            timestamp=datetime(2025, 1, 1),
            confidence=0.85,
        )

        assert signal.risk_amount == 1000.0
        assert signal.reward_amount == 2000.0
        assert signal.risk_reward_ratio == 2.0

    def test_valid_short_entry_signal(self):
        """Test creating a valid SHORT_ENTRY signal"""
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="ETHUSDT",
            entry_price=3000.0,
            take_profit=2700.0,
            stop_loss=3150.0,
            strategy_name="test_strategy",
            timestamp=datetime(2025, 1, 1),
        )

        assert signal.risk_amount == 150.0
        assert signal.reward_amount == 300.0
        assert signal.risk_reward_ratio == 2.0

    def test_invalid_confidence_raises_error(self):
        """Test that invalid confidence raises ValueError"""
        with pytest.raises(ValueError, match="Confidence must be 0.0-1.0"):
            Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                strategy_name="test",
                timestamp=datetime(2025, 1, 1),
                confidence=1.5,  # Invalid
            )

    def test_invalid_long_tp_raises_error(self):
        """Test that invalid LONG take_profit raises ValueError"""
        with pytest.raises(ValueError, match="LONG: take_profit must be > entry_price"):
            Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000.0,
                take_profit=49000.0,  # Invalid: TP < entry for LONG
                stop_loss=48000.0,
                strategy_name="test",
                timestamp=datetime(2025, 1, 1),
            )

    def test_invalid_short_tp_raises_error(self):
        """Test that invalid SHORT take_profit raises ValueError"""
        with pytest.raises(ValueError, match="SHORT: take_profit must be < entry_price"):
            Signal(
                signal_type=SignalType.SHORT_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000.0,
                take_profit=51000.0,  # Invalid: TP > entry for SHORT
                stop_loss=52000.0,
                strategy_name="test",
                timestamp=datetime(2025, 1, 1),
            )


class TestOrder:
    """Tests for Order dataclass"""

    def test_valid_market_order(self):
        """Test creating a valid MARKET order"""
        order = Order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )

        assert order.status == OrderStatus.NEW
        assert order.order_id is None

    def test_valid_limit_order(self):
        """Test creating a valid LIMIT order"""
        order = Order(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=0.1,
            price=3000.0,
        )

        assert order.price == 3000.0

    def test_limit_order_without_price_raises_error(self):
        """Test that LIMIT order without price raises ValueError"""
        with pytest.raises(ValueError, match="LIMIT orders require price"):
            Order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=0.001,
                # Missing price
            )

    def test_stop_market_without_stop_price_raises_error(self):
        """Test that STOP_MARKET without stop_price raises ValueError"""
        with pytest.raises(ValueError, match="STOP_MARKET requires stop_price"):
            Order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.STOP_MARKET,
                quantity=0.001,
                # Missing stop_price
            )

    def test_invalid_quantity_raises_error(self):
        """Test that zero or negative quantity raises ValueError"""
        with pytest.raises(ValueError, match="Quantity must be > 0"):
            Order(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0.0,  # Invalid
            )

    def test_order_enum_values_match_binance(self):
        """Verify enum values match Binance API exactly"""
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.NEW.value == "NEW"


class TestPosition:
    """Tests for Position dataclass"""

    def test_valid_long_position(self):
        """Test creating a valid LONG position"""
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=10,
        )

        assert position.notional_value == 5000.0
        assert position.margin_used == 500.0

    def test_valid_short_position(self):
        """Test creating a valid SHORT position"""
        position = Position(
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=3000.0,
            quantity=1.0,
            leverage=20,
        )

        assert position.notional_value == 3000.0
        assert position.margin_used == 150.0

    def test_invalid_side_raises_error(self):
        """Test that invalid side raises ValueError"""
        with pytest.raises(ValueError, match="Side must be 'LONG' or 'SHORT'"):
            Position(
                symbol="BTCUSDT",
                side="INVALID",
                entry_price=50000.0,
                quantity=0.1,
                leverage=10,
            )

    def test_invalid_quantity_raises_error(self):
        """Test that zero or negative quantity raises ValueError"""
        with pytest.raises(ValueError, match="Quantity must be > 0"):
            Position(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000.0,
                quantity=0.0,
                leverage=10,
            )

    def test_invalid_leverage_raises_error(self):
        """Test that leverage < 1 raises ValueError"""
        with pytest.raises(ValueError, match="Leverage must be >= 1"):
            Position(
                symbol="BTCUSDT",
                side="LONG",
                entry_price=50000.0,
                quantity=0.1,
                leverage=0,
            )


class TestEvent:
    """Tests for Event dataclass"""

    def test_create_candle_update_event(self):
        """Test creating a CANDLE_UPDATE event"""
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime(2025, 1, 1),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            close_time=datetime(2025, 1, 1, 0, 5), is_closed=True,
        )

        event = Event(
            event_type=EventType.CANDLE_UPDATE,
            data=candle,
            source="data_collector",
        )

        assert event.event_type == EventType.CANDLE_UPDATE
        assert isinstance(event.data, Candle)
        assert event.source == "data_collector"
        assert isinstance(event.timestamp, datetime)

    def test_create_signal_generated_event(self):
        """Test creating a SIGNAL_GENERATED event"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            strategy_name="test",
            timestamp=datetime(2025, 1, 1),
        )

        event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            data=signal,
            source="strategy_engine",
        )

        assert event.event_type == EventType.SIGNAL_GENERATED
        assert isinstance(event.data, Signal)
