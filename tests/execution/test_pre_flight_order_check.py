"""Tests for pre-flight order check and TP/SL completeness guarantee.

Covers:
- Pre-flight check: orphaned orders detection, cancellation, fail-open
- TP/SL completeness: retry logic, emergency close escalation
- Per-symbol entry guard: asyncio.Lock concurrency control
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.execution.trade_coordinator import TradeCoordinator
from src.models.event import Event, EventType
from src.models.order import Order, OrderSide, OrderStatus, OrderType
from src.models.signal import Signal, SignalType


def make_signal(
    signal_type: SignalType = SignalType.LONG_ENTRY,
    symbol: str = "BTCUSDT",
    entry_price: float = 50000.0,
    take_profit: Optional[float] = 55000.0,
    stop_loss: Optional[float] = 48000.0,
    strategy_name: str = "test",
) -> Signal:
    return Signal(
        signal_type=signal_type,
        symbol=symbol,
        entry_price=entry_price,
        strategy_name=strategy_name,
        timestamp=datetime.now(timezone.utc),
        take_profit=take_profit,
        stop_loss=stop_loss,
    )


def make_order(
    symbol: str = "BTCUSDT",
    side: OrderSide = OrderSide.BUY,
    order_type: OrderType = OrderType.MARKET,
    quantity: float = 0.1,
    status: OrderStatus = OrderStatus.FILLED,
    stop_price: Optional[float] = None,
) -> Order:
    # TP/SL orders require stop_price
    if stop_price is None and order_type in (
        OrderType.STOP_MARKET,
        OrderType.STOP,
        OrderType.TAKE_PROFIT_MARKET,
        OrderType.TAKE_PROFIT,
    ):
        stop_price = 50000.0  # Default for tests
    return Order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        status=status,
        stop_price=stop_price,
    )


@pytest.fixture
def mock_order_gateway():
    gw = MagicMock()
    gw.get_open_orders.return_value = []
    gw.cancel_all_orders.return_value = 0
    gw.get_account_balance.return_value = 10000.0

    entry_order = make_order()
    tp_order = make_order(
        side=OrderSide.SELL, order_type=OrderType.TAKE_PROFIT_MARKET
    )
    sl_order = make_order(side=OrderSide.SELL, order_type=OrderType.STOP_MARKET)
    gw.execute_signal.return_value = (entry_order, [tp_order, sl_order])
    return gw


@pytest.fixture
def mock_position_cache():
    cache = MagicMock()
    cache.get_fresh.return_value = None  # No existing position
    cache.invalidate.return_value = None
    return cache


@pytest.fixture
def mock_risk_guard():
    guard = MagicMock()
    guard.validate_risk.return_value = True
    guard.calculate_position_size.return_value = 0.1
    return guard


@pytest.fixture
def mock_config():
    cm = MagicMock()
    cm.trading_config.leverage = 10
    return cm


@pytest.fixture
def mock_audit():
    al = MagicMock()
    al.log_event = MagicMock()
    return al


@pytest.fixture
def coordinator(
    mock_order_gateway, mock_risk_guard, mock_config, mock_audit, mock_position_cache
):
    return TradeCoordinator(
        order_gateway=mock_order_gateway,
        risk_guard=mock_risk_guard,
        config_manager=mock_config,
        audit_logger=mock_audit,
        position_cache_manager=mock_position_cache,
    )


class TestPreFlightCheck:
    """Tests for _pre_flight_check method in TradeCoordinator."""

    def test_no_orphaned_orders_passes(self, coordinator, mock_order_gateway):
        """Pre-flight passes when no open orders exist."""
        mock_order_gateway.get_open_orders.return_value = []

        result = coordinator._pre_flight_check("BTCUSDT")

        assert result is True
        mock_order_gateway.get_open_orders.assert_called_once_with("BTCUSDT")
        mock_order_gateway.cancel_all_orders.assert_not_called()

    def test_orphaned_orders_cancelled_then_passes(
        self, coordinator, mock_order_gateway
    ):
        """Pre-flight detects orphaned orders, cancels them, then passes."""
        mock_order_gateway.get_open_orders.return_value = [
            {"orderId": "123", "type": "STOP_MARKET"},
            {"orderId": "456", "type": "TAKE_PROFIT_MARKET"},
        ]
        mock_order_gateway.cancel_all_orders.return_value = 2

        result = coordinator._pre_flight_check("BTCUSDT")

        assert result is True
        mock_order_gateway.cancel_all_orders.assert_called_once_with("BTCUSDT")

    def test_orphaned_orders_cancel_fails_rejects(
        self, coordinator, mock_order_gateway
    ):
        """Pre-flight rejects entry when cancel_all_orders fails."""
        mock_order_gateway.get_open_orders.return_value = [
            {"orderId": "123", "type": "STOP_MARKET"},
        ]
        mock_order_gateway.cancel_all_orders.side_effect = Exception(
            "API cancel failed"
        )

        result = coordinator._pre_flight_check("BTCUSDT")

        assert result is False

    def test_api_failure_fail_open(self, coordinator, mock_order_gateway):
        """Pre-flight proceeds (fail-open) when get_open_orders API fails."""
        mock_order_gateway.get_open_orders.side_effect = Exception("API timeout")

        result = coordinator._pre_flight_check("BTCUSDT")

        assert result is True  # Fail-open: proceed with warning
        mock_order_gateway.cancel_all_orders.assert_not_called()

    @pytest.mark.asyncio
    async def test_pre_flight_integrated_in_signal_flow(
        self, coordinator, mock_order_gateway, mock_position_cache
    ):
        """Pre-flight check is called during on_signal_generated flow."""
        signal = make_signal()
        event = Event(EventType.SIGNAL_GENERATED, signal)

        await coordinator.on_signal_generated(event)

        # get_open_orders should have been called for pre-flight
        mock_order_gateway.get_open_orders.assert_called_with("BTCUSDT")

    @pytest.mark.asyncio
    async def test_pre_flight_reject_blocks_entry(
        self, coordinator, mock_order_gateway
    ):
        """Entry is blocked when pre-flight check fails (cancel failure)."""
        mock_order_gateway.get_open_orders.return_value = [
            {"orderId": "999", "type": "STOP_MARKET"}
        ]
        mock_order_gateway.cancel_all_orders.side_effect = Exception("cancel failed")

        signal = make_signal()
        event = Event(EventType.SIGNAL_GENERATED, signal)

        await coordinator.on_signal_generated(event)

        # execute_signal should NOT have been called
        mock_order_gateway.execute_signal.assert_not_called()


class TestTPSLCompleteness:
    """Tests for _ensure_tpsl_completeness in OrderGateway."""

    @pytest.fixture
    def order_gateway(self):
        """Create OrderGateway with mocked Binance service."""
        from src.execution.order_gateway import OrderGateway

        mock_service = MagicMock()
        mock_service._client = MagicMock()
        mock_service.is_testnet = True
        mock_service.weight_tracker = MagicMock()

        # Proxy calls
        mock_service.new_order = mock_service._client.new_order
        mock_service.new_algo_order = mock_service._client.new_algo_order
        mock_service.exchange_info = mock_service._client.exchange_info
        mock_service.cancel_open_orders = mock_service._client.cancel_open_orders
        mock_service.get_position_risk = mock_service._client.get_position_risk
        mock_service.account = mock_service._client.account
        mock_service._client.exchange_info.return_value = {"symbols": []}

        mock_audit = MagicMock()
        return OrderGateway(
            audit_logger=mock_audit, binance_service=mock_service
        )

    def test_both_orders_placed_no_retry(self, order_gateway):
        """No retry needed when both TP and SL are placed."""
        signal = make_signal()
        entry_order = make_order()
        tp = make_order(
            side=OrderSide.SELL, order_type=OrderType.TAKE_PROFIT_MARKET
        )
        sl = make_order(side=OrderSide.SELL, order_type=OrderType.STOP_MARKET)
        tpsl_orders = [tp, sl]

        result = order_gateway._ensure_tpsl_completeness(
            signal=signal,
            tpsl_orders=tpsl_orders,
            tpsl_side=OrderSide.SELL,
            entry_order=entry_order,
        )

        assert len(result) == 2

    @patch("src.execution.order_gateway.time.sleep", return_value=None)
    def test_retry_places_missing_sl(self, mock_sleep, order_gateway):
        """Retry successfully places missing SL order."""
        signal = make_signal()
        entry_order = make_order()
        tp = make_order(
            side=OrderSide.SELL, order_type=OrderType.TAKE_PROFIT_MARKET
        )
        tpsl_orders = [tp]  # SL missing

        sl = make_order(side=OrderSide.SELL, order_type=OrderType.STOP_MARKET)
        order_gateway._place_sl_order = MagicMock(return_value=sl)
        order_gateway._place_tp_order = MagicMock(return_value=None)

        result = order_gateway._ensure_tpsl_completeness(
            signal=signal,
            tpsl_orders=tpsl_orders,
            tpsl_side=OrderSide.SELL,
            entry_order=entry_order,
        )

        assert len(result) == 2
        order_gateway._place_sl_order.assert_called_once()
        # TP already placed, should not be retried
        order_gateway._place_tp_order.assert_not_called()

    @patch("src.execution.order_gateway.time.sleep", return_value=None)
    def test_retry_places_missing_tp(self, mock_sleep, order_gateway):
        """Retry successfully places missing TP order."""
        signal = make_signal()
        entry_order = make_order()
        sl = make_order(side=OrderSide.SELL, order_type=OrderType.STOP_MARKET)
        tpsl_orders = [sl]  # TP missing

        tp = make_order(
            side=OrderSide.SELL, order_type=OrderType.TAKE_PROFIT_MARKET
        )
        order_gateway._place_tp_order = MagicMock(return_value=tp)
        order_gateway._place_sl_order = MagicMock(return_value=None)

        result = order_gateway._ensure_tpsl_completeness(
            signal=signal,
            tpsl_orders=tpsl_orders,
            tpsl_side=OrderSide.SELL,
            entry_order=entry_order,
        )

        assert len(result) == 2
        order_gateway._place_tp_order.assert_called_once()
        order_gateway._place_sl_order.assert_not_called()

    @patch("src.execution.order_gateway.time.sleep", return_value=None)
    def test_retry_exhausted_triggers_emergency_close(
        self, mock_sleep, order_gateway
    ):
        """Emergency close triggered when retries exhausted."""
        signal = make_signal()
        entry_order = make_order()
        tpsl_orders = []  # Both missing

        # Both retries fail
        order_gateway._place_tp_order = MagicMock(return_value=None)
        order_gateway._place_sl_order = MagicMock(return_value=None)
        order_gateway._execute_market_close_sync = MagicMock(
            return_value={"success": True, "order_id": "emergency_123"}
        )
        order_gateway.cancel_all_orders = MagicMock(return_value=0)

        result = order_gateway._ensure_tpsl_completeness(
            signal=signal,
            tpsl_orders=tpsl_orders,
            tpsl_side=OrderSide.SELL,
            entry_order=entry_order,
        )

        assert result == []  # Empty — position was emergency closed
        order_gateway._execute_market_close_sync.assert_called_once_with(
            symbol="BTCUSDT",
            position_amt=0.1,
            side="SELL",  # Opposite of BUY entry
            reduce_only=True,
        )

    @patch("src.execution.order_gateway.time.sleep", return_value=None)
    def test_emergency_close_reduce_only_enforced(
        self, mock_sleep, order_gateway
    ):
        """Emergency close always uses reduce_only=True."""
        signal = make_signal()
        entry_order = make_order()
        tpsl_orders = []

        order_gateway._place_tp_order = MagicMock(return_value=None)
        order_gateway._place_sl_order = MagicMock(return_value=None)
        order_gateway._execute_market_close_sync = MagicMock(
            return_value={"success": True, "order_id": "safe_close"}
        )
        order_gateway.cancel_all_orders = MagicMock(return_value=0)

        order_gateway._ensure_tpsl_completeness(
            signal=signal,
            tpsl_orders=tpsl_orders,
            tpsl_side=OrderSide.SELL,
            entry_order=entry_order,
        )

        call_kwargs = order_gateway._execute_market_close_sync.call_args
        assert call_kwargs.kwargs["reduce_only"] is True


class TestEntryGuard:
    """Tests for per-symbol asyncio.Lock entry guard."""

    @pytest.mark.asyncio
    async def test_concurrent_signals_serialized(
        self, coordinator, mock_order_gateway, mock_position_cache, mock_risk_guard
    ):
        """Two concurrent signals for same symbol are serialized by lock."""
        signal1 = make_signal(symbol="BTCUSDT")
        signal2 = make_signal(symbol="BTCUSDT")
        event1 = Event(EventType.SIGNAL_GENERATED, signal1)
        event2 = Event(EventType.SIGNAL_GENERATED, signal2)

        # Second call sees position from first → risk_guard rejects
        mock_position_cache.get_fresh.side_effect = [None, MagicMock()]
        mock_risk_guard.validate_risk.side_effect = [True, False]

        await asyncio.gather(
            coordinator.on_signal_generated(event1),
            coordinator.on_signal_generated(event2),
        )

        # First signal executed, second rejected by risk guard (position exists)
        assert mock_order_gateway.execute_signal.call_count == 1
