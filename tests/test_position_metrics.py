"""
Unit tests for Position Metrics tracking (trailing-stop-logging-optimization).

Tests MFE/MAE update logic, ratchet event logging, closure field inclusion,
drawdown calculation, and metrics lifecycle cleanup.
"""

from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.candle import Candle
from src.models.position import Position, PositionMetrics
from src.models.signal import SignalType
from src.utils.config_manager import ExitConfig


def _make_candle(close: float, is_closed: bool = True) -> Candle:
    """Create a minimal closed candle for testing."""
    return Candle(
        symbol="BTCUSDT",
        interval="5m",
        open_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        close_time=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100.0,
        is_closed=is_closed,
    )


def _make_context(symbol: str, candle: Candle, position: Position):
    """Create an ExitContext for testing."""
    from src.exit.base import ExitContext
    return ExitContext(
        symbol=symbol,
        candle=candle,
        position=position,
        buffers={"5m": deque(maxlen=100)},
        indicator_cache=None,
        timestamp=0,
        config={},
    )


@pytest.fixture
def exit_determiner():
    """ICTExitDeterminer with 2% distance, 1% activation."""
    from src.strategies.ict.exit import ICTExitDeterminer
    return ICTExitDeterminer(
        exit_config=ExitConfig(
            trailing_distance=0.02,
            trailing_activation=0.01,
        )
    )


@pytest.fixture
def long_position():
    return Position(
        symbol="BTCUSDT", side="LONG",
        entry_price=100.0, quantity=1.0, leverage=10,
    )


@pytest.fixture
def short_position():
    return Position(
        symbol="BTCUSDT", side="SHORT",
        entry_price=100.0, quantity=1.0, leverage=10,
    )


class TestMFEMAEUpdate:
    """Test MFE/MAE update logic on each candle."""

    def test_mfe_mae_updated_on_each_candle_long(self, exit_determiner, long_position):
        """LONG: MFE increases with price rise, MAE decreases with price drop."""
        # Candle 1: price at 101 (+1%)
        ctx = _make_context("BTCUSDT", _make_candle(101.0), long_position)
        exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics.get("BTCUSDT_LONG")
        assert metrics is not None
        assert metrics.mfe_pct == pytest.approx(1.0, abs=0.01)
        assert metrics.mae_pct == 0.0  # no loss yet
        assert metrics.candle_count == 1

        # Candle 2: price drops to 99 (-1%)
        ctx = _make_context("BTCUSDT", _make_candle(99.0), long_position)
        exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics.get("BTCUSDT_LONG")
        assert metrics.mfe_pct == pytest.approx(1.0, abs=0.01)  # unchanged
        assert metrics.mae_pct == pytest.approx(-1.0, abs=0.01)
        assert metrics.candle_count == 2

        # Candle 3: price rises to 103 (+3%)
        ctx = _make_context("BTCUSDT", _make_candle(103.0), long_position)
        exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics.get("BTCUSDT_LONG")
        assert metrics.mfe_pct == pytest.approx(3.0, abs=0.01)
        assert metrics.mae_pct == pytest.approx(-1.0, abs=0.01)  # unchanged
        assert metrics.candle_count == 3

    def test_mfe_mae_updated_on_each_candle_short(self, exit_determiner, short_position):
        """SHORT: MFE increases with price drop, MAE decreases with price rise."""
        # Candle 1: price drops to 99 (+1% for short)
        ctx = _make_context("BTCUSDT", _make_candle(99.0), short_position)
        exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics.get("BTCUSDT_SHORT")
        assert metrics is not None
        assert metrics.mfe_pct == pytest.approx(1.0, abs=0.01)

        # Candle 2: price rises to 101 (-1% for short)
        ctx = _make_context("BTCUSDT", _make_candle(101.0), short_position)
        exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics.get("BTCUSDT_SHORT")
        assert metrics.mae_pct == pytest.approx(-1.0, abs=0.01)


class TestHWMLWMPrice:
    """Test high-water mark and low-water mark price recording."""

    def test_hwm_lwm_price_recorded_long(self, exit_determiner, long_position):
        """LONG: HWM at highest close, LWM at lowest close."""
        prices = [101.0, 99.0, 103.0, 100.5]
        for p in prices:
            ctx = _make_context("BTCUSDT", _make_candle(p), long_position)
            exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics["BTCUSDT_LONG"]
        assert metrics.hwm_price == 103.0
        assert metrics.lwm_price == 99.0

    def test_hwm_lwm_price_recorded_short(self, exit_determiner, short_position):
        """SHORT: HWM at lowest close (favorable), LWM at highest (adverse)."""
        prices = [99.0, 101.0, 97.0, 100.0]
        for p in prices:
            ctx = _make_context("BTCUSDT", _make_candle(p), short_position)
            exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics["BTCUSDT_SHORT"]
        assert metrics.hwm_price == 97.0  # best for short
        assert metrics.lwm_price == 101.0  # worst for short


class TestRatchetEvent:
    """Test trailing stop ratchet event logging."""

    @patch("src.core.audit_logger.AuditLogger")
    def test_ratchet_event_logged(self, mock_audit_cls, exit_determiner, long_position):
        """Ratchet event fires when trailing stop advances."""
        mock_audit = MagicMock()
        mock_audit_cls.get_instance.return_value = mock_audit

        # Candle 1: price 102 (activates trailing, > 101 activation threshold)
        ctx = _make_context("BTCUSDT", _make_candle(102.0), long_position)
        exit_determiner.should_exit(ctx)

        # Candle 2: price 104 (ratchet should fire)
        ctx = _make_context("BTCUSDT", _make_candle(104.0), long_position)
        exit_determiner.should_exit(ctx)

        # Verify audit was called for ratchet
        calls = mock_audit.log_event.call_args_list
        ratchet_calls = [
            c for c in calls
            if c.kwargs.get("event_type")
            and c.kwargs["event_type"].value == "trailing_stop_ratcheted"
        ]
        assert len(ratchet_calls) >= 1

        ratchet_data = ratchet_calls[-1].kwargs["data"]
        assert ratchet_data["side"] == "LONG"
        assert ratchet_data["ratchet_count"] >= 1
        assert ratchet_data["trigger_price"] == pytest.approx(104.0, abs=0.01)

    def test_ratchet_count_incremented(self, exit_determiner, long_position):
        """Ratchet count tracks number of stop level advances."""
        # Price sequence: 102 (activate + ratchet), 104 (ratchet), 106 (ratchet)
        for price in [102.0, 104.0, 106.0]:
            ctx = _make_context("BTCUSDT", _make_candle(price), long_position)
            with patch("src.core.audit_logger.AuditLogger"):
                exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics["BTCUSDT_LONG"]
        # Each price above activation that advances the stop counts as a ratchet
        assert metrics.ratchet_count >= 2  # 104 and 106 ratchet from previous


class TestClosureFields:
    """Test metrics inclusion in position closure."""

    def test_metrics_included_in_position_closed(self):
        """log_position_closure includes MFE/MAE fields when metrics available."""
        from src.execution.trade_coordinator import TradeCoordinator
        from src.models.order import Order, OrderType, OrderSide
        from src.models.position import PositionEntryData

        tc = TradeCoordinator(
            order_gateway=MagicMock(),
            risk_guard=MagicMock(),
            config_manager=MagicMock(),
            audit_logger=MagicMock(),
            position_cache_manager=MagicMock(),
        )

        # Setup entry data
        tc._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=100.0,
            entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            quantity=1.0,
            side="LONG",
        )

        # Setup metrics callback
        metrics = PositionMetrics(
            entry_price=100.0, side="LONG",
            mfe_pct=3.5, mae_pct=-1.2,
            hwm_price=103.5, lwm_price=98.8,
            ratchet_count=3, last_trailing_stop=101.4,
            candle_count=15,
        )
        tc._get_position_metrics = MagicMock(return_value=metrics)

        order = MagicMock(spec=Order)
        order.symbol = "BTCUSDT"
        order.price = 102.0
        order.quantity = 1.0
        order.side = OrderSide.SELL
        order.order_type = OrderType.STOP_MARKET
        order.order_id = "123"
        order.stop_price = 101.5
        order.commission = 0.05
        order.event_time = None
        order.transaction_time = None

        tc.log_position_closure(order)

        # Verify audit log was called with metrics
        call_kwargs = tc._audit_logger.log_event.call_args.kwargs
        data = call_kwargs["data"]

        assert data["mfe_pct"] == 3.5
        assert data["mae_pct"] == -1.2
        assert data["hwm_price"] == 103.5
        assert data["trailing_ratchet_count"] == 3
        assert data["candle_count"] == 15
        assert "drawdown_from_hwm_pct" in data

    def test_no_metrics_when_callback_none(self):
        """No crash when get_position_metrics is None (backward compat)."""
        from src.execution.trade_coordinator import TradeCoordinator
        from src.models.order import Order, OrderType, OrderSide
        from src.models.position import PositionEntryData

        tc = TradeCoordinator(
            order_gateway=MagicMock(),
            risk_guard=MagicMock(),
            config_manager=MagicMock(),
            audit_logger=MagicMock(),
            position_cache_manager=MagicMock(),
        )

        tc._position_entry_data["BTCUSDT"] = PositionEntryData(
            entry_price=100.0,
            entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            quantity=1.0,
            side="LONG",
        )

        order = MagicMock(spec=Order)
        order.symbol = "BTCUSDT"
        order.price = 102.0
        order.quantity = 1.0
        order.side = OrderSide.SELL
        order.order_type = OrderType.STOP_MARKET
        order.order_id = "123"
        order.stop_price = 101.5
        order.commission = 0.05
        order.event_time = None
        order.transaction_time = None

        # Should not crash
        tc.log_position_closure(order)

        call_kwargs = tc._audit_logger.log_event.call_args.kwargs
        data = call_kwargs["data"]
        assert "mfe_pct" not in data  # No metrics injected


class TestTradeClosedMetrics:
    """Test metrics inclusion in TRADE_CLOSED event via execute_exit_signal."""

    @pytest.mark.asyncio
    async def test_metrics_included_in_trade_closed(self):
        """execute_exit_signal includes MFE/MAE fields in TRADE_CLOSED audit event."""
        from src.execution.trade_coordinator import TradeCoordinator
        from src.models.signal import Signal

        tc = TradeCoordinator(
            order_gateway=MagicMock(),
            risk_guard=MagicMock(),
            config_manager=MagicMock(),
            audit_logger=MagicMock(),
            position_cache_manager=MagicMock(),
        )

        # Mock async execute_market_close
        tc._order_gateway.execute_market_close = AsyncMock(
            return_value={
                "success": True,
                "order_id": "exit_123",
                "avg_price": 102.0,
                "executed_qty": 1.0,
                "status": "FILLED",
            }
        )
        tc._order_gateway.cancel_all_orders = MagicMock(return_value=0)
        tc._position_cache_manager.invalidate = MagicMock()

        # Setup metrics callback
        metrics = PositionMetrics(
            entry_price=100.0, side="LONG",
            mfe_pct=4.0, mae_pct=-0.5,
            hwm_price=104.0, lwm_price=99.5,
            ratchet_count=2, last_trailing_stop=101.9,
            candle_count=20,
        )
        tc._get_position_metrics = MagicMock(return_value=metrics)

        # Create exit signal and position
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=100.0,
            strategy_name="ict",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            exit_reason="trailing_stop",
        )
        position = MagicMock()
        position.symbol = "BTCUSDT"
        position.side = "LONG"
        position.entry_price = 100.0
        position.quantity = 1.0
        position.leverage = 10
        position.entry_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

        await tc.execute_exit_signal(signal, position)

        # Verify TRADE_CLOSED audit log includes metrics
        call_kwargs = tc._audit_logger.log_event.call_args.kwargs
        data = call_kwargs["data"]

        assert data["mfe_pct"] == 4.0
        assert data["mae_pct"] == -0.5
        assert data["hwm_price"] == 104.0
        assert data["trailing_ratchet_count"] == 2
        assert data["candle_count"] == 20
        assert "drawdown_from_hwm_pct" in data


class TestDrawdownCalculation:
    """Test drawdown from HWM calculation."""

    def test_drawdown_from_hwm_long(self):
        """LONG: drawdown = (hwm - exit) / hwm * 100."""
        metrics = PositionMetrics(
            entry_price=100.0, side="LONG",
            mfe_pct=3.5, mae_pct=-1.0,
            hwm_price=103.5, lwm_price=99.0,
        )
        exit_price = 102.0
        drawdown = (metrics.hwm_price - exit_price) / metrics.hwm_price * 100
        assert drawdown == pytest.approx(1.4493, abs=0.01)

    def test_drawdown_from_hwm_short(self):
        """SHORT: drawdown = (exit - lwm) / lwm * 100."""
        metrics = PositionMetrics(
            entry_price=100.0, side="SHORT",
            mfe_pct=3.0, mae_pct=-1.0,
            hwm_price=97.0, lwm_price=97.0,
        )
        exit_price = 98.0
        drawdown = (exit_price - metrics.lwm_price) / metrics.lwm_price * 100
        assert drawdown == pytest.approx(1.0309, abs=0.01)


class TestMetricsLifecycle:
    """Test metrics initialization and cleanup."""

    def test_metrics_initialized_on_first_candle(self, exit_determiner, long_position):
        """Metrics created on first candle with correct entry_price and side."""
        assert len(exit_determiner._position_metrics) == 0

        ctx = _make_context("BTCUSDT", _make_candle(101.0), long_position)
        exit_determiner.should_exit(ctx)

        metrics = exit_determiner._position_metrics.get("BTCUSDT_LONG")
        assert metrics is not None
        assert metrics.entry_price == 100.0
        assert metrics.side == "LONG"
        assert metrics.hwm_price > 0
        assert metrics.lwm_price > 0

    def test_metrics_cleared_on_get_and_clear(self, exit_determiner, long_position):
        """get_and_clear_metrics returns metrics and removes from dict."""
        ctx = _make_context("BTCUSDT", _make_candle(101.0), long_position)
        exit_determiner.should_exit(ctx)

        assert "BTCUSDT_LONG" in exit_determiner._position_metrics

        result = exit_determiner.get_and_clear_metrics("BTCUSDT", "LONG")
        assert result is not None
        assert result.mfe_pct == pytest.approx(1.0, abs=0.01)

        # Should be removed
        assert "BTCUSDT_LONG" not in exit_determiner._position_metrics

        # Second call returns None
        assert exit_determiner.get_and_clear_metrics("BTCUSDT", "LONG") is None
