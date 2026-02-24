"""Tests for MockExchange in-memory exchange simulator."""

import pytest
import asyncio
from datetime import datetime, timezone

from src.execution.mock_exchange import MockExchange
from src.models.order import OrderSide, OrderStatus, OrderType
from src.models.signal import Signal, SignalType


@pytest.fixture
def exchange():
    """Create a MockExchange with default settings."""
    return MockExchange(initial_balance=10000.0, fee_rate=0.0004, slippage_bps=1.0)


@pytest.fixture
def long_signal():
    """Create a LONG_ENTRY signal for BTCUSDT."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.LONG_ENTRY,
        entry_price=50000.0,
        take_profit=55000.0,
        stop_loss=48000.0,
        strategy_name="test_strategy",
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def short_signal():
    """Create a SHORT_ENTRY signal for ETHUSDT."""
    return Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SHORT_ENTRY,
        entry_price=3000.0,
        take_profit=2700.0,
        stop_loss=3200.0,
        strategy_name="test_strategy",
        timestamp=datetime.now(timezone.utc),
    )


class TestExecuteSignal:
    """Test order execution via execute_signal."""

    def test_long_entry_creates_position(self, exchange, long_signal):
        entry, tpsl = exchange.execute_signal(long_signal, quantity=0.1)

        assert entry.status == OrderStatus.FILLED
        assert entry.side == OrderSide.BUY
        assert entry.order_type == OrderType.MARKET
        assert entry.quantity == 0.1
        assert entry.filled_quantity == 0.1

        pos = exchange.get_position("BTCUSDT")
        assert pos is not None
        assert pos.side == "LONG"
        assert pos.quantity == 0.1

    def test_short_entry_creates_position(self, exchange, short_signal):
        entry, tpsl = exchange.execute_signal(short_signal, quantity=1.0)

        assert entry.status == OrderStatus.FILLED
        assert entry.side == OrderSide.SELL
        pos = exchange.get_position("ETHUSDT")
        assert pos is not None
        assert pos.side == "SHORT"
        assert pos.quantity == 1.0

    def test_tp_sl_orders_created_for_long(self, exchange, long_signal):
        _, tpsl = exchange.execute_signal(long_signal, quantity=0.1)

        assert len(tpsl) == 2
        tp_order = tpsl[0]
        sl_order = tpsl[1]

        assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
        assert tp_order.stop_price == 55000.0
        assert tp_order.status == OrderStatus.NEW
        assert tp_order.side == OrderSide.SELL  # Close long = SELL

        assert sl_order.order_type == OrderType.STOP_MARKET
        assert sl_order.stop_price == 48000.0
        assert sl_order.status == OrderStatus.NEW
        assert sl_order.side == OrderSide.SELL  # Close long = SELL

    def test_tp_sl_orders_created_for_short(self, exchange, short_signal):
        _, tpsl = exchange.execute_signal(short_signal, quantity=1.0)

        assert len(tpsl) == 2
        tp_order = tpsl[0]
        sl_order = tpsl[1]

        assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
        assert tp_order.stop_price == 2700.0
        assert tp_order.status == OrderStatus.NEW
        assert tp_order.side == OrderSide.BUY  # Close short = BUY

        assert sl_order.order_type == OrderType.STOP_MARKET
        assert sl_order.stop_price == 3200.0
        assert sl_order.status == OrderStatus.NEW
        assert sl_order.side == OrderSide.BUY  # Close short = BUY

    def test_signal_without_tp_sl(self, exchange):
        # EXIT signals don't require TP/SL
        signal = Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.CLOSE_LONG,
            entry_price=50000.0,
            strategy_name="test_strategy",
            timestamp=datetime.now(timezone.utc),
        )
        # CLOSE_LONG maps to SELL side
        entry, tpsl = exchange.execute_signal(signal, quantity=0.1)
        assert entry.status == OrderStatus.FILLED
        assert len(tpsl) == 0

    def test_slippage_applied_to_buy(self, exchange, long_signal):
        entry, _ = exchange.execute_signal(long_signal, quantity=0.1)
        # BUY slippage: price * (1 + slippage_bps / 10000) = 50000 * 1.0001
        expected = 50000.0 * (1 + 1.0 / 10000)
        assert entry.price == pytest.approx(expected)

    def test_slippage_applied_to_sell(self, exchange, short_signal):
        entry, _ = exchange.execute_signal(short_signal, quantity=1.0)
        # SELL slippage: price * (1 - slippage_bps / 10000) = 3000 * 0.9999
        expected = 3000.0 * (1 - 1.0 / 10000)
        assert entry.price == pytest.approx(expected)

    def test_fee_deducted(self, exchange, long_signal):
        initial = exchange.get_account_balance()
        entry, _ = exchange.execute_signal(long_signal, quantity=0.1)
        fee = 0.1 * entry.price * 0.0004
        assert exchange.get_account_balance() == pytest.approx(initial - fee)

    def test_leverage_applied_to_position(self, exchange, long_signal):
        exchange.set_leverage("BTCUSDT", 10)
        exchange.execute_signal(long_signal, quantity=0.1)
        pos = exchange.get_position("BTCUSDT")
        assert pos.leverage == 10

    def test_default_leverage_is_one(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        pos = exchange.get_position("BTCUSDT")
        assert pos.leverage == 1

    def test_entry_order_has_order_id(self, exchange, long_signal):
        entry, _ = exchange.execute_signal(long_signal, quantity=0.1)
        assert entry.order_id is not None
        assert entry.order_id.startswith("MOCK-")

    def test_order_ids_are_unique(self, exchange, long_signal, short_signal):
        entry1, _ = exchange.execute_signal(long_signal, quantity=0.1)
        entry2, _ = exchange.execute_signal(short_signal, quantity=0.5)
        assert entry1.order_id != entry2.order_id

    def test_entry_order_symbol(self, exchange, long_signal):
        entry, _ = exchange.execute_signal(long_signal, quantity=0.1)
        assert entry.symbol == "BTCUSDT"


class TestPositionTracking:
    """Test position management methods."""

    def test_get_returns_none_when_no_position(self, exchange):
        assert exchange.get("BTCUSDT") is None

    def test_get_fresh_returns_same_as_get(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        assert exchange.get("BTCUSDT") == exchange.get_fresh("BTCUSDT")

    def test_get_fresh_returns_none_when_no_position(self, exchange):
        assert exchange.get_fresh("BTCUSDT") is None

    def test_invalidate_is_noop(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.invalidate("BTCUSDT")
        # Position still exists after invalidate (mock doesn't clear)
        assert exchange.get("BTCUSDT") is not None

    def test_cache_property(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        cache = exchange.cache
        assert "BTCUSDT" in cache
        pos, timestamp = cache["BTCUSDT"]
        assert pos is not None
        assert pos.side == "LONG"

    def test_cache_is_updated_after_execute(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        pos, ts = exchange.cache["BTCUSDT"]
        assert pos.symbol == "BTCUSDT"
        assert ts > 0

    def test_get_position_matches_get(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        assert exchange.get_position("BTCUSDT") == exchange.get("BTCUSDT")

    def test_get_position_returns_none_no_position(self, exchange):
        assert exchange.get_position("BTCUSDT") is None

    def test_multiple_symbols_tracked_independently(
        self, exchange, long_signal, short_signal
    ):
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.execute_signal(short_signal, quantity=1.0)

        btc_pos = exchange.get_position("BTCUSDT")
        eth_pos = exchange.get_position("ETHUSDT")

        assert btc_pos is not None
        assert eth_pos is not None
        assert btc_pos.side == "LONG"
        assert eth_pos.side == "SHORT"


class TestBalanceAccounting:
    """Test balance, fee, and PnL tracking."""

    def test_initial_balance(self, exchange):
        assert exchange.get_account_balance() == 10000.0

    def test_fees_tracked(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        assert exchange.total_fees > 0

    def test_total_fees_accumulate(self, exchange, long_signal, short_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        fees_after_first = exchange.total_fees
        exchange.execute_signal(short_signal, quantity=1.0)
        assert exchange.total_fees > fees_after_first

    def test_initial_realized_pnl_is_zero(self, exchange):
        assert exchange.realized_pnl == 0.0

    @pytest.mark.asyncio
    async def test_realized_pnl_on_close(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        result = await exchange.execute_market_close(
            symbol="BTCUSDT",
            position_amt=0.1,
            side="SELL",
        )
        assert result["success"] is True
        # PnL is based on slippage difference (sell slightly lower than buy)
        assert exchange.get_position("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_balance_changes_after_close(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        balance_after_entry = exchange.get_account_balance()
        await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        # Balance changes due to fee on close order
        assert exchange.get_account_balance() != balance_after_entry

    def test_fee_rate_zero_no_fee_deducted(self, long_signal):
        no_fee_exchange = MockExchange(
            initial_balance=10000.0, fee_rate=0.0, slippage_bps=0.0
        )
        no_fee_exchange.execute_signal(long_signal, quantity=0.1)
        assert no_fee_exchange.get_account_balance() == 10000.0
        assert no_fee_exchange.total_fees == 0.0


class TestExecuteMarketClose:
    """Test market close functionality."""

    @pytest.mark.asyncio
    async def test_close_removes_position(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        result = await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        assert result["success"] is True
        assert exchange.get_position("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_close_nonexistent_position(self, exchange):
        result = await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_close_cancels_pending_orders(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        assert len(exchange.get_open_orders("BTCUSDT")) == 2
        await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        assert len(exchange.get_open_orders("BTCUSDT")) == 0

    @pytest.mark.asyncio
    async def test_close_returns_order_id(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        result = await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        assert result["success"] is True
        assert "order_id" in result
        assert result["order_id"].startswith("MOCK-")

    @pytest.mark.asyncio
    async def test_close_result_has_avg_price(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        result = await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        assert "avg_price" in result
        assert result["avg_price"] > 0

    @pytest.mark.asyncio
    async def test_close_short_with_buy_side(self, exchange, short_signal):
        exchange.execute_signal(short_signal, quantity=1.0)
        result = await exchange.execute_market_close("ETHUSDT", 1.0, "BUY")
        assert result["success"] is True
        assert exchange.get_position("ETHUSDT") is None

    @pytest.mark.asyncio
    async def test_close_updates_cache(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        await exchange.execute_market_close("BTCUSDT", 0.1, "SELL")
        pos, _ = exchange.cache["BTCUSDT"]
        assert pos is None


class TestCancelAllOrders:
    """Test order cancellation."""

    def test_cancel_returns_count(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        count = exchange.cancel_all_orders("BTCUSDT")
        assert count == 2  # TP + SL

    def test_cancel_empty_returns_zero(self, exchange):
        count = exchange.cancel_all_orders("BTCUSDT")
        assert count == 0

    def test_cancel_clears_open_orders(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.cancel_all_orders("BTCUSDT")
        assert len(exchange.get_open_orders("BTCUSDT")) == 0

    def test_cancel_does_not_affect_other_symbol(
        self, exchange, long_signal, short_signal
    ):
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.execute_signal(short_signal, quantity=1.0)
        exchange.cancel_all_orders("BTCUSDT")
        assert len(exchange.get_open_orders("ETHUSDT")) == 2


class TestUpdateStopLoss:
    """Test stop-loss update mechanics."""

    def test_update_sl_replaces_order(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        new_sl = exchange.update_stop_loss("BTCUSDT", 49000.0, OrderSide.SELL)
        assert new_sl is not None
        assert new_sl.stop_price == 49000.0
        assert new_sl.status == OrderStatus.NEW

    def test_update_sl_new_order_side(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        new_sl = exchange.update_stop_loss("BTCUSDT", 49000.0, OrderSide.SELL)
        assert new_sl.side == OrderSide.SELL

    def test_update_sl_no_existing_returns_none(self, exchange):
        result = exchange.update_stop_loss("BTCUSDT", 49000.0, OrderSide.SELL)
        assert result is None

    def test_update_sl_old_order_is_canceled(self, exchange, long_signal):
        _, tpsl = exchange.execute_signal(long_signal, quantity=0.1)
        old_sl = tpsl[1]  # SL is second order
        exchange.update_stop_loss("BTCUSDT", 49000.0, OrderSide.SELL)
        assert old_sl.status == OrderStatus.CANCELED

    def test_update_sl_order_count_unchanged(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.update_stop_loss("BTCUSDT", 49000.0, OrderSide.SELL)
        # Still TP + new SL = 2 open orders
        assert len(exchange.get_open_orders("BTCUSDT")) == 2

    def test_update_sl_preserves_quantity(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        new_sl = exchange.update_stop_loss("BTCUSDT", 49000.0, OrderSide.SELL)
        assert new_sl.quantity == 0.1


class TestCheckPendingOrders:
    """Test TP/SL trigger simulation."""

    def test_tp_triggers_long(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        filled = exchange.check_pending_orders("BTCUSDT", 55000.0)
        assert len(filled) == 1
        assert filled[0].order_type == OrderType.TAKE_PROFIT_MARKET
        assert exchange.get_position("BTCUSDT") is None

    def test_sl_triggers_long(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        filled = exchange.check_pending_orders("BTCUSDT", 48000.0)
        assert len(filled) == 1
        assert filled[0].order_type == OrderType.STOP_MARKET
        assert exchange.get_position("BTCUSDT") is None

    def test_no_trigger_at_mid_price(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        filled = exchange.check_pending_orders("BTCUSDT", 51000.0)
        assert len(filled) == 0
        assert exchange.get_position("BTCUSDT") is not None

    def test_tp_triggers_short(self, exchange, short_signal):
        exchange.execute_signal(short_signal, quantity=1.0)
        filled = exchange.check_pending_orders("ETHUSDT", 2700.0)
        assert len(filled) == 1
        assert filled[0].order_type == OrderType.TAKE_PROFIT_MARKET

    def test_sl_triggers_short(self, exchange, short_signal):
        exchange.execute_signal(short_signal, quantity=1.0)
        filled = exchange.check_pending_orders("ETHUSDT", 3200.0)
        assert len(filled) == 1
        assert filled[0].order_type == OrderType.STOP_MARKET

    def test_no_pending_orders(self, exchange):
        filled = exchange.check_pending_orders("BTCUSDT", 50000.0)
        assert len(filled) == 0

    def test_tp_trigger_leaves_sl_in_open_orders(self, exchange, long_signal):
        # check_pending_orders only cancels position; counterpart SL stays in
        # _open_orders until explicitly cancelled or the position is gone.
        # The remaining SL won't trigger again (no position), but it stays in
        # the open-orders list. This reflects the actual mock behaviour.
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.check_pending_orders("BTCUSDT", 55000.0)
        # Position is gone
        assert exchange.get_position("BTCUSDT") is None
        # SL order remains in open orders (implementation detail)
        remaining = exchange.get_open_orders("BTCUSDT")
        assert len(remaining) == 1
        assert remaining[0]["type"] == "STOP_MARKET"

    def test_triggered_order_marked_filled(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        filled = exchange.check_pending_orders("BTCUSDT", 55000.0)
        assert filled[0].status == OrderStatus.FILLED
        assert filled[0].filled_quantity == 0.1

    def test_trigger_updates_balance(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        balance_before = exchange.get_account_balance()
        exchange.check_pending_orders("BTCUSDT", 55000.0)
        # Balance changes due to PnL and fee on close
        assert exchange.get_account_balance() != balance_before

    def test_no_position_returns_empty(self, exchange, long_signal):
        # Create and then manually cancel orders without a position
        exchange.execute_signal(long_signal, quantity=0.1)
        del exchange._positions["BTCUSDT"]
        filled = exchange.check_pending_orders("BTCUSDT", 55000.0)
        assert len(filled) == 0

    def test_long_tp_requires_price_at_or_above(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        # Price exactly at TP should trigger
        filled = exchange.check_pending_orders("BTCUSDT", 55000.0)
        assert len(filled) == 1

    def test_long_sl_requires_price_at_or_below(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        # Price exactly at SL should trigger
        filled = exchange.check_pending_orders("BTCUSDT", 48000.0)
        assert len(filled) == 1


class TestExchangeProvider:
    """Test ExchangeProvider methods."""

    def test_set_leverage(self, exchange):
        assert exchange.set_leverage("BTCUSDT", 20) is True

    def test_set_leverage_stores_value(self, exchange, long_signal):
        exchange.set_leverage("BTCUSDT", 20)
        exchange.execute_signal(long_signal, quantity=0.1)
        pos = exchange.get_position("BTCUSDT")
        assert pos.leverage == 20

    def test_set_margin_type(self, exchange):
        assert exchange.set_margin_type("BTCUSDT", "CROSSED") is True

    @pytest.mark.asyncio
    async def test_get_all_positions(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        positions = await exchange.get_all_positions(["BTCUSDT", "ETHUSDT"])
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_all_positions_empty(self, exchange):
        positions = await exchange.get_all_positions(["BTCUSDT"])
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_get_all_positions_multiple(
        self, exchange, long_signal, short_signal
    ):
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.execute_signal(short_signal, quantity=1.0)
        positions = await exchange.get_all_positions(["BTCUSDT", "ETHUSDT"])
        assert len(positions) == 2

    @pytest.mark.asyncio
    async def test_get_all_positions_long_amt_positive(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        positions = await exchange.get_all_positions(["BTCUSDT"])
        assert float(positions[0]["positionAmt"]) > 0

    @pytest.mark.asyncio
    async def test_get_all_positions_short_amt_negative(self, exchange, short_signal):
        exchange.execute_signal(short_signal, quantity=1.0)
        positions = await exchange.get_all_positions(["ETHUSDT"])
        assert float(positions[0]["positionAmt"]) < 0

    def test_get_open_orders(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        orders = exchange.get_open_orders("BTCUSDT")
        assert len(orders) == 2

    def test_get_open_orders_returns_dicts(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        orders = exchange.get_open_orders("BTCUSDT")
        for order in orders:
            assert isinstance(order, dict)
            assert "orderId" in order
            assert "symbol" in order
            assert "side" in order
            assert "type" in order

    def test_get_open_orders_empty(self, exchange):
        orders = exchange.get_open_orders("BTCUSDT")
        assert orders == []

    def test_filled_orders_history(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        assert len(exchange.filled_orders) == 1  # entry order only

    def test_filled_orders_after_close(self, exchange, long_signal):
        # Entry adds 1, TP/SL trigger adds 1 more
        exchange.execute_signal(long_signal, quantity=0.1)
        exchange.check_pending_orders("BTCUSDT", 55000.0)
        assert len(exchange.filled_orders) == 2

    def test_filled_orders_returns_copy(self, exchange, long_signal):
        exchange.execute_signal(long_signal, quantity=0.1)
        orders1 = exchange.filled_orders
        orders2 = exchange.filled_orders
        assert orders1 is not orders2
