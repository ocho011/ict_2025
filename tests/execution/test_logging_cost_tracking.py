"""Tests for logging-cost-tracking feature (PDCA cycle).

Covers:
- Order commission fields propagation
- PositionEntryData position_id and cost fields
- Commission accumulation (entry + exit)
- Funding fee distribution
- Net PnL calculation in log_position_closure
- Slippage bps calculation
- Wallet balance callback
- Partial fill commission preservation
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.execution.trade_coordinator import TradeCoordinator
from src.models.event import Event, EventType
from src.models.order import Order, OrderSide, OrderType, OrderStatus
from src.models.position import PositionEntryData


@pytest.fixture
def audit_logger():
    al = MagicMock()
    al.log_event = MagicMock()
    return al


@pytest.fixture
def coordinator(audit_logger):
    """Minimal TradeCoordinator with mocked dependencies."""
    tc = TradeCoordinator(
        order_gateway=MagicMock(),
        risk_guard=MagicMock(),
        config_manager=MagicMock(),
        audit_logger=audit_logger,
        position_cache_manager=MagicMock(),
    )
    tc._get_wallet_balance = lambda: 10000.0
    return tc


def _make_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    price=50000.0,
    quantity=0.1,
    commission=0.5,
    commission_asset="USDT",
    event_time=1700000000000,
    transaction_time=1700000000001,
    stop_price=None,
    order_id="123",
) -> Order:
    return Order(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        order_id=order_id,
        status=OrderStatus.FILLED,
        commission=commission,
        commission_asset=commission_asset,
        event_time=event_time,
        transaction_time=transaction_time,
        stop_price=stop_price,
    )


class TestOrderCommissionFields:
    """Test Order dataclass commission field extensions."""

    def test_order_has_commission_fields(self):
        order = _make_order(commission=1.23, commission_asset="BNB")
        assert order.commission == 1.23
        assert order.commission_asset == "BNB"

    def test_order_commission_defaults(self):
        order = Order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=50000.0,
        )
        assert order.commission == 0.0
        assert order.commission_asset is None
        assert order.event_time is None
        assert order.transaction_time is None

    def test_order_event_timestamps(self):
        order = _make_order(event_time=123456, transaction_time=789012)
        assert order.event_time == 123456
        assert order.transaction_time == 789012


class TestPositionEntryData:
    """Test PositionEntryData extensions."""

    def test_position_id_auto_generated(self):
        data1 = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )
        data2 = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )
        assert data1.position_id != data2.position_id
        assert len(data1.position_id) > 0

    def test_cost_fields_default_zero(self):
        data = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )
        assert data.total_commission == 0.0
        assert data.total_funding == 0.0
        assert data.intended_entry_price is None

    def test_intended_entry_price(self):
        data = PositionEntryData(
            entry_price=50100.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
            intended_entry_price=50000.0,
        )
        assert data.intended_entry_price == 50000.0


class TestCommissionAccumulation:
    """Test commission accumulation in on_order_filled."""

    @pytest.mark.asyncio
    async def test_entry_commission_tracked(self, coordinator):
        """Entry fill stores commission in PositionEntryData."""
        entry_order = _make_order(
            order_type=OrderType.MARKET,
            side=OrderSide.BUY,
            commission=0.5,
        )
        event = Event(EventType.ORDER_FILLED, entry_order)
        await coordinator.on_order_filled(event)

        entry_data = coordinator._position_entry_data.get("BTCUSDT")
        assert entry_data is not None
        assert entry_data.total_commission == 0.5

    @pytest.mark.asyncio
    async def test_exit_commission_accumulated(self, coordinator):
        """Exit fill adds commission to existing entry data."""
        # Setup: entry already tracked
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
            total_commission=0.5,  # entry commission
        )

        # Exit via TP
        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            side=OrderSide.SELL,
            price=55000.0,
            commission=0.55,
            stop_price=55000.0,
        )
        event = Event(EventType.ORDER_FILLED, exit_order)
        await coordinator.on_order_filled(event)

        # Entry data consumed by log_position_closure (popped)
        assert "BTCUSDT" not in coordinator._position_entry_data


class TestFundingFeeDistribution:
    """Test funding fee accumulation to open positions."""

    def test_single_position_funding(self, coordinator):
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )

        # Binance: positive = received (revenue for trader)
        coordinator.accumulate_funding_fee(1.0)

        # total_funding sign: positive = cost, so received fee is negative cost
        assert coordinator._position_entry_data["BTCUSDT"].total_funding == -1.0

    def test_paid_funding_fee(self, coordinator):
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="SHORT",
        )

        # Binance: negative = paid by trader
        coordinator.accumulate_funding_fee(-0.5)

        # Paid fee: total_funding should be positive (cost)
        assert coordinator._position_entry_data["BTCUSDT"].total_funding == 0.5

    def test_no_open_positions_no_error(self, coordinator):
        """Funding fee with no positions should not crash."""
        coordinator.accumulate_funding_fee(1.0)  # Should not raise

    def test_multi_position_proportional(self, coordinator):
        """Funding fee distributed proportionally by notional."""
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )
        coordinator._position_entry_data["ETHUSDT"] = PositionEntryData(
            entry_price=2500.0,
            entry_time=datetime.now(timezone.utc),
            quantity=2.0,
            side="SHORT",
        )
        # BTC notional: 5000, ETH notional: 5000 → 50/50 split
        coordinator.accumulate_funding_fee(2.0)

        assert coordinator._position_entry_data["BTCUSDT"].total_funding == pytest.approx(-1.0)
        assert coordinator._position_entry_data["ETHUSDT"].total_funding == pytest.approx(-1.0)


class TestNetPnlCalculation:
    """Test Net PnL = Gross - Commission - Funding in log_position_closure."""

    def test_long_net_pnl(self, coordinator, audit_logger):
        """LONG: gross_pnl = (exit - entry) * qty, net = gross - comm - funding."""
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
            total_commission=1.0,
            total_funding=0.5,
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            price=51000.0,
            stop_price=51000.0,
        )
        coordinator.log_position_closure(exit_order)

        # Verify audit log call
        call_args = audit_logger.log_event.call_args
        data = call_args.kwargs.get("data", {})

        expected_gross = (51000.0 - 50000.0) * 0.1  # 10.0
        expected_net = expected_gross - 1.0 - 0.5  # 8.5

        assert data["gross_pnl"] == pytest.approx(expected_gross)
        assert data["total_commission"] == 1.0
        assert data["total_funding"] == 0.5
        assert data["net_pnl"] == pytest.approx(expected_net)
        assert data["realized_pnl"] == pytest.approx(expected_gross)  # backward compat

    def test_short_net_pnl(self, coordinator, audit_logger):
        """SHORT: gross_pnl = (entry - exit) * qty."""
        coordinator._position_entry_data["ETHUSDT"] = PositionEntryData(
            entry_price=3000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=1.0,
            side="SHORT",
            total_commission=2.0,
            total_funding=-0.3,  # negative = revenue
        )

        exit_order = _make_order(
            symbol="ETHUSDT",
            order_type=OrderType.STOP_MARKET,
            side=OrderSide.BUY,
            price=3100.0,
            quantity=1.0,
            stop_price=3100.0,
        )
        coordinator.log_position_closure(exit_order)

        call_args = audit_logger.log_event.call_args
        data = call_args.kwargs.get("data", {})

        expected_gross = (3000.0 - 3100.0) * 1.0  # -100.0
        expected_net = expected_gross - 2.0 - (-0.3)  # -101.7

        assert data["gross_pnl"] == pytest.approx(expected_gross)
        assert data["net_pnl"] == pytest.approx(expected_net)

    def test_position_id_in_closure(self, coordinator, audit_logger):
        """Position ID flows through to closure log."""
        entry_data = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )
        pid = entry_data.position_id
        coordinator._position_entry_data["BTCUSDT"] = entry_data

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=55000.0,
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        assert data["position_id"] == pid

    def test_balance_after_in_closure(self, coordinator, audit_logger):
        """Wallet balance callback result included in closure."""
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=55000.0,
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        assert data["balance_after"] == 10000.0

    def test_no_balance_callback(self, coordinator, audit_logger):
        """No crash when wallet balance callback is None."""
        coordinator._get_wallet_balance = None
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=55000.0,
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        assert "balance_after" not in data


class TestSlippageTracking:
    """Test entry/exit slippage calculation in bps."""

    def test_entry_slippage_bps(self, coordinator, audit_logger):
        """Entry slippage = (actual - intended) / intended * 10000."""
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50050.0,  # actual fill
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
            intended_entry_price=50000.0,  # signal price
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=55000.0,
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        # (50050 - 50000) / 50000 * 10000 = 10.0 bps
        assert data["slippage_entry_bps"] == pytest.approx(10.0)

    def test_exit_slippage_bps(self, coordinator, audit_logger):
        """Exit slippage = (actual - stop_price) / stop_price * 10000."""
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            price=55010.0,  # actual fill
            stop_price=55000.0,  # trigger price
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        # (55010 - 55000) / 55000 * 10000 ≈ 1.82 bps
        assert data["slippage_exit_bps"] == pytest.approx(1.82, abs=0.01)

    def test_no_intended_price_no_entry_slippage(self, coordinator, audit_logger):
        """No entry slippage when intended_entry_price is None."""
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            stop_price=55000.0,
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        assert "slippage_entry_bps" not in data


class TestPartialFillPreservation:
    """Test that partial fills preserve cost tracking fields."""

    @pytest.mark.asyncio
    async def test_partial_fill_preserves_position_id(self, coordinator):
        """Partial fill update should keep original position_id."""
        # First partial fill
        first_order = _make_order(
            order_type=OrderType.MARKET,
            quantity=0.1,
            commission=0.3,
        )
        first_order.filled_quantity = 0.05
        event = Event(EventType.ORDER_PARTIALLY_FILLED, first_order)
        await coordinator.on_order_partially_filled(event)

        pid = coordinator._position_entry_data["BTCUSDT"].position_id

        # Second partial fill
        second_order = _make_order(
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=50010.0,
            commission=0.3,
        )
        second_order.filled_quantity = 0.1
        event2 = Event(EventType.ORDER_PARTIALLY_FILLED, second_order)
        await coordinator.on_order_partially_filled(event2)

        # position_id preserved
        assert coordinator._position_entry_data["BTCUSDT"].position_id == pid

    @pytest.mark.asyncio
    async def test_partial_fill_accumulates_commission(self, coordinator):
        """Multiple partial fills accumulate commission."""
        first_order = _make_order(
            order_type=OrderType.MARKET,
            commission=0.3,
        )
        first_order.filled_quantity = 0.05
        event = Event(EventType.ORDER_PARTIALLY_FILLED, first_order)
        await coordinator.on_order_partially_filled(event)

        second_order = _make_order(
            order_type=OrderType.MARKET,
            commission=0.2,
        )
        second_order.filled_quantity = 0.1
        event2 = Event(EventType.ORDER_PARTIALLY_FILLED, second_order)
        await coordinator.on_order_partially_filled(event2)

        assert coordinator._position_entry_data["BTCUSDT"].total_commission == pytest.approx(0.5)


class TestIntendedEntryPrice:
    """Test intended entry price flow from signal to closure."""

    @pytest.mark.asyncio
    async def test_intended_price_stored_on_entry(self, coordinator):
        """Signal's entry_price stored as intended_entry_price in PositionEntryData."""
        # Simulate signal execution storing intended price
        coordinator._pending_intended_prices["BTCUSDT"] = 50000.0

        entry_order = _make_order(
            order_type=OrderType.MARKET,
            price=50010.0,  # actual fill with slippage
        )
        event = Event(EventType.ORDER_FILLED, entry_order)
        await coordinator.on_order_filled(event)

        entry_data = coordinator._position_entry_data["BTCUSDT"]
        assert entry_data.intended_entry_price == 50000.0
        assert entry_data.entry_price == 50010.0  # actual fill

    @pytest.mark.asyncio
    async def test_intended_price_consumed(self, coordinator):
        """Pending intended price is consumed (popped) after use."""
        coordinator._pending_intended_prices["BTCUSDT"] = 50000.0

        entry_order = _make_order(order_type=OrderType.MARKET)
        event = Event(EventType.ORDER_FILLED, entry_order)
        await coordinator.on_order_filled(event)

        assert "BTCUSDT" not in coordinator._pending_intended_prices


class TestExchangeTimestamps:
    """Test exchange timestamp propagation to closure log."""

    def test_timestamps_in_closure(self, coordinator, audit_logger):
        coordinator._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=50000.0,
            entry_time=datetime.now(timezone.utc),
            quantity=0.1,
            side="LONG",
        )

        exit_order = _make_order(
            order_type=OrderType.TAKE_PROFIT_MARKET,
            event_time=1700000001000,
            transaction_time=1700000001001,
            stop_price=55000.0,
        )
        coordinator.log_position_closure(exit_order)

        data = audit_logger.log_event.call_args.kwargs.get("data", {})
        assert data["exchange_event_time"] == 1700000001000
        assert data["exchange_transaction_time"] == 1700000001001
