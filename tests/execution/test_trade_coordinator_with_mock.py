"""Integration tests: TradeCoordinator with MockExchange."""

import pytest
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

from src.execution.mock_exchange import MockExchange
from src.execution.trade_coordinator import TradeCoordinator
from src.models.event import Event, EventType
from src.models.signal import Signal, SignalType


def make_signal(
    signal_type: SignalType,
    symbol: str,
    entry_price: float,
    take_profit: Optional[float] = None,
    stop_loss: Optional[float] = None,
    exit_reason: Optional[str] = None,
    strategy_name: str = "test",
) -> Signal:
    """Helper to construct a Signal with a required timestamp."""
    return Signal(
        signal_type=signal_type,
        symbol=symbol,
        entry_price=entry_price,
        strategy_name=strategy_name,
        timestamp=datetime.now(timezone.utc),
        take_profit=take_profit,
        stop_loss=stop_loss,
        exit_reason=exit_reason,
    )


@pytest.fixture
def mock_exchange():
    return MockExchange(initial_balance=10000.0)


@pytest.fixture
def risk_guard():
    guard = MagicMock()
    guard.validate_risk.return_value = True
    guard.calculate_position_size.return_value = 0.1
    return guard


@pytest.fixture
def config_manager():
    cm = MagicMock()
    cm.trading_config.leverage = 10
    return cm


@pytest.fixture
def audit_logger():
    al = MagicMock()
    al.log_event = MagicMock()
    return al


@pytest.fixture
def coordinator(mock_exchange, risk_guard, config_manager, audit_logger):
    """TradeCoordinator using MockExchange as both gateway and position provider."""
    return TradeCoordinator(
        order_gateway=mock_exchange,
        risk_guard=risk_guard,
        config_manager=config_manager,
        audit_logger=audit_logger,
        position_cache_manager=mock_exchange,
    )


class TestEntrySignalFlow:
    """Test entry signal processing through TradeCoordinator with MockExchange."""

    @pytest.mark.asyncio
    async def test_long_entry_signal(self, coordinator, mock_exchange):
        signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)

        await coordinator.on_signal_generated(event)

        pos = mock_exchange.get_position("BTCUSDT")
        assert pos is not None
        assert pos.side == "LONG"
        assert pos.quantity == 0.1  # from risk_guard fixture

    @pytest.mark.asyncio
    async def test_short_entry_signal(self, coordinator, mock_exchange):
        signal = make_signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="ETHUSDT",
            entry_price=3000.0,
            take_profit=2700.0,
            stop_loss=3200.0,
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)

        await coordinator.on_signal_generated(event)

        pos = mock_exchange.get_position("ETHUSDT")
        assert pos is not None
        assert pos.side == "SHORT"

    @pytest.mark.asyncio
    async def test_rejected_signal_no_position(self, coordinator, mock_exchange, risk_guard):
        risk_guard.validate_risk.return_value = False

        signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)

        await coordinator.on_signal_generated(event)

        assert mock_exchange.get_position("BTCUSDT") is None


class TestExitSignalFlow:
    """Test exit signal processing through TradeCoordinator with MockExchange."""

    @pytest.mark.asyncio
    async def test_exit_closes_position(self, coordinator, mock_exchange):
        # First open a position
        entry_signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        entry_event = Event(EventType.SIGNAL_GENERATED, entry_signal)
        await coordinator.on_signal_generated(entry_event)

        assert mock_exchange.get_position("BTCUSDT") is not None

        # Now close it with exit signal
        position = mock_exchange.get_position("BTCUSDT")
        exit_signal = make_signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=52000.0,
            exit_reason="strategy_exit",
        )
        await coordinator.execute_exit_signal(exit_signal, position)

        assert mock_exchange.get_position("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_exit_cancels_pending_orders(self, coordinator, mock_exchange):
        # Open position with TP/SL
        signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)
        await coordinator.on_signal_generated(event)

        assert len(mock_exchange.get_open_orders("BTCUSDT")) == 2

        # Exit signal
        position = mock_exchange.get_position("BTCUSDT")
        exit_signal = make_signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=52000.0,
            exit_reason="strategy_exit",
        )
        await coordinator.execute_exit_signal(exit_signal, position)

        assert len(mock_exchange.get_open_orders("BTCUSDT")) == 0

    @pytest.mark.asyncio
    async def test_exit_via_on_signal_generated(self, coordinator, mock_exchange):
        """Exit signal routed through on_signal_generated closes position."""
        # Open position
        entry_signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        await coordinator.on_signal_generated(Event(EventType.SIGNAL_GENERATED, entry_signal))
        assert mock_exchange.get_position("BTCUSDT") is not None

        # Close via on_signal_generated
        exit_signal = make_signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=52000.0,
            exit_reason="strategy_exit",
        )
        await coordinator.on_signal_generated(Event(EventType.SIGNAL_GENERATED, exit_signal))

        assert mock_exchange.get_position("BTCUSDT") is None


class TestBalanceIntegration:
    """Test balance tracking through the full flow."""

    @pytest.mark.asyncio
    async def test_balance_after_trade_cycle(self, coordinator, mock_exchange):
        initial_balance = mock_exchange.get_account_balance()

        # Entry
        signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)
        await coordinator.on_signal_generated(event)

        # Balance should be reduced by fee after entry
        assert mock_exchange.get_account_balance() < initial_balance

        # Close position
        position = mock_exchange.get_position("BTCUSDT")
        exit_signal = make_signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=52000.0,
            exit_reason="test",
        )
        await coordinator.execute_exit_signal(exit_signal, position)

        # Fees should have been deducted (total_fees > 0)
        assert mock_exchange.total_fees > 0

    @pytest.mark.asyncio
    async def test_multiple_symbols_independent(self, coordinator, mock_exchange):
        """Positions for different symbols are independent."""
        btc_signal = make_signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
        )
        eth_signal = make_signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="ETHUSDT",
            entry_price=3000.0,
            take_profit=2700.0,
            stop_loss=3200.0,
        )

        await coordinator.on_signal_generated(Event(EventType.SIGNAL_GENERATED, btc_signal))
        await coordinator.on_signal_generated(Event(EventType.SIGNAL_GENERATED, eth_signal))

        btc_pos = mock_exchange.get_position("BTCUSDT")
        eth_pos = mock_exchange.get_position("ETHUSDT")

        assert btc_pos is not None and btc_pos.side == "LONG"
        assert eth_pos is not None and eth_pos.side == "SHORT"

        # Close BTC only
        exit_signal = make_signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=51000.0,
            exit_reason="test",
        )
        await coordinator.execute_exit_signal(exit_signal, btc_pos)

        assert mock_exchange.get_position("BTCUSDT") is None
        assert mock_exchange.get_position("ETHUSDT") is not None
