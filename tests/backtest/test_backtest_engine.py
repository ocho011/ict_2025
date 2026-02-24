"""Tests for BacktestEngine."""

import time

import pytest
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult, TradeRecord
from src.data.historical import HistoricalDataProvider
from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_candle(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 103.0,
    volume: float = 1000.0,
    close_time: Optional[datetime] = None,
    minute_offset: int = 0,
    is_closed: bool = True,
) -> Candle:
    """Create a test candle with sensible defaults."""
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    open_time = base_time + timedelta(minutes=minute_offset)
    if close_time is None:
        close_time = open_time + timedelta(minutes=1)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=open_time,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        close_time=close_time,
        is_closed=is_closed,
    )


def make_candle_series(
    n: int,
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    base_price: float = 100.0,
    trend: float = 0.0,
) -> List[Candle]:
    """Generate a series of candles with optional trend."""
    candles = []
    for i in range(n):
        price = base_price + trend * i
        candles.append(
            make_candle(
                symbol=symbol,
                interval=interval,
                open_=price,
                high=price + 5.0,
                low=price - 5.0,
                close=price + 3.0,  # bullish candles
                minute_offset=i,
            )
        )
    return candles


class AlwaysLongStrategy(BaseStrategy):
    """Test strategy that generates a LONG signal on every closed bullish candle."""

    def __init__(self, symbol: str, config: Optional[dict] = None):
        config = config or {"buffer_size": 5, "default_interval": "1m"}
        super().__init__(symbol=symbol, config=config)

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        if candle.is_bullish:
            return Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol=candle.symbol,
                entry_price=candle.close,
                take_profit=candle.close * 1.05,  # 5% TP
                stop_loss=candle.close * 0.97,  # 3% SL
                strategy_name="always_long",
                timestamp=candle.close_time,
            )
        return None

    async def should_exit(
        self, position: Position, candle: Candle
    ) -> Optional[Signal]:
        # Rely on TP/SL, no strategy exit
        return None


class NeverTradeStrategy(BaseStrategy):
    """Test strategy that never generates signals."""

    def __init__(self, symbol: str, config: Optional[dict] = None):
        config = config or {"buffer_size": 5, "default_interval": "1m"}
        super().__init__(symbol=symbol, config=config)

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        return None

    async def should_exit(
        self, position: Position, candle: Candle
    ) -> Optional[Signal]:
        return None


class ExitAfterNStrategy(BaseStrategy):
    """Strategy that enters LONG once, then exits after N candles."""

    def __init__(
        self, symbol: str, exit_after: int = 3, config: Optional[dict] = None
    ):
        config = config or {"buffer_size": 5, "default_interval": "1m"}
        super().__init__(symbol=symbol, config=config)
        self._entered = False
        self._exit_after = exit_after
        self._candles_since_entry = 0

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        if not self._entered and candle.is_bullish:
            self._entered = True
            self._candles_since_entry = 0
            return Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol=candle.symbol,
                entry_price=candle.close,
                take_profit=candle.close * 1.10,  # 10% TP (unlikely to hit)
                stop_loss=candle.close * 0.50,  # 50% SL (unlikely to hit)
                strategy_name="exit_after_n",
                timestamp=candle.close_time,
            )
        return None

    async def should_exit(
        self, position: Position, candle: Candle
    ) -> Optional[Signal]:
        self._candles_since_entry += 1
        if self._candles_since_entry >= self._exit_after:
            return Signal(
                signal_type=SignalType.CLOSE_LONG,
                symbol=candle.symbol,
                entry_price=candle.close,
                strategy_name="exit_after_n",
                timestamp=candle.close_time,
                exit_reason="time_exit",
            )
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config():
    return BacktestConfig(
        initial_balance=10000.0,
        fee_rate=0.0004,
        slippage_bps=1.0,
        leverage=10,
        risk_per_trade=0.02,
        backfill_limit=5,
    )


def make_data_provider(
    candles: List[Candle],
    symbol: str = "BTCUSDT",
    interval: str = "1m",
) -> HistoricalDataProvider:
    """Create a HistoricalDataProvider from a list of candles."""
    return HistoricalDataProvider(
        candle_data={symbol: {interval: candles}},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBacktestNoSignals:
    """Verify no trades when strategy generates no signals."""

    @pytest.mark.asyncio
    async def test_backtest_with_no_signals(self, default_config):
        candles = make_candle_series(20, base_price=100.0)
        provider = make_data_provider(candles)
        strategy = NeverTradeStrategy("BTCUSDT")
        default_config.backfill_limit = 5

        engine = BacktestEngine(
            strategies={"BTCUSDT": strategy},
            data_provider=provider,
            config=default_config,
        )

        result = await engine.run()

        assert result.total_trades == 0
        assert result.winning_trades == 0
        assert result.losing_trades == 0
        assert result.total_pnl == 0.0
        assert result.final_balance == default_config.initial_balance
        assert result.candles_processed == 15  # 20 - 5 backfill


class TestBacktestBasicLongTrade:
    """Verify basic LONG entry and strategy-driven exit."""

    @pytest.mark.asyncio
    async def test_backtest_basic_long_trade(self, default_config):
        # Create candles: 5 for backfill, then a bullish candle for entry,
        # then 3 more candles, then exit via strategy
        candles = make_candle_series(12, base_price=100.0, trend=0.5)
        provider = make_data_provider(candles)
        strategy = ExitAfterNStrategy("BTCUSDT", exit_after=3)
        default_config.backfill_limit = 5

        engine = BacktestEngine(
            strategies={"BTCUSDT": strategy},
            data_provider=provider,
            config=default_config,
        )

        result = await engine.run()

        assert result.total_trades >= 1
        assert result.candles_processed == 7  # 12 - 5 backfill

        # Verify trade record
        trade = result.trades[0]
        assert trade.symbol == "BTCUSDT"
        assert trade.side == "LONG"
        assert trade.exit_reason == "time_exit"
        assert trade.entry_candle_index < trade.exit_candle_index


class TestTpSlTrigger:
    """Verify TP/SL orders trigger correctly during candle replay."""

    @pytest.mark.asyncio
    async def test_take_profit_triggers(self, default_config):
        """TP triggers when candle high reaches TP price."""
        # Backfill candles
        backfill = make_candle_series(5, base_price=100.0)

        # Entry candle (bullish)
        entry_candle = make_candle(
            open_=103.0, high=108.0, low=98.0, close=106.0, minute_offset=5
        )

        # TP candle: high reaches 5% above entry (106 * 1.05 = 111.3)
        tp_candle = make_candle(
            open_=106.0, high=115.0, low=105.0, close=112.0, minute_offset=6
        )

        candles = backfill + [entry_candle, tp_candle]
        provider = make_data_provider(candles)
        strategy = AlwaysLongStrategy("BTCUSDT")
        default_config.backfill_limit = 5

        engine = BacktestEngine(
            strategies={"BTCUSDT": strategy},
            data_provider=provider,
            config=default_config,
        )

        result = await engine.run()

        assert result.total_trades >= 1
        # Find the TP trade
        tp_trades = [t for t in result.trades if t.exit_reason == "take_profit"]
        assert len(tp_trades) >= 1

    @pytest.mark.asyncio
    async def test_stop_loss_triggers(self, default_config):
        """SL triggers when candle low reaches SL price."""
        # Backfill candles
        backfill = make_candle_series(5, base_price=100.0)

        # Entry candle (bullish)
        entry_candle = make_candle(
            open_=103.0, high=108.0, low=98.0, close=106.0, minute_offset=5
        )

        # SL candle: low reaches 3% below entry (106 * 0.97 = 102.82)
        # Need low to go below SL
        sl_candle = make_candle(
            open_=106.0, high=107.0, low=100.0, close=101.0, minute_offset=6
        )

        candles = backfill + [entry_candle, sl_candle]
        provider = make_data_provider(candles)
        strategy = AlwaysLongStrategy("BTCUSDT")
        default_config.backfill_limit = 5

        engine = BacktestEngine(
            strategies={"BTCUSDT": strategy},
            data_provider=provider,
            config=default_config,
        )

        result = await engine.run()

        assert result.total_trades >= 1
        sl_trades = [t for t in result.trades if t.exit_reason == "stop_loss"]
        assert len(sl_trades) >= 1


class TestEquityCurve:
    """Verify equity curve tracking."""

    @pytest.mark.asyncio
    async def test_equity_curve_tracked(self, default_config):
        candles = make_candle_series(250, base_price=100.0)
        provider = make_data_provider(candles)
        strategy = NeverTradeStrategy("BTCUSDT")
        default_config.backfill_limit = 5

        engine = BacktestEngine(
            strategies={"BTCUSDT": strategy},
            data_provider=provider,
            config=default_config,
        )

        result = await engine.run()

        # At least 1 entry (final balance) + periodic entries (every 100 candles)
        assert len(result.equity_curve) >= 1
        # Final equity should equal initial balance (no trades)
        assert result.equity_curve[-1] == default_config.initial_balance


class TestResultProperties:
    """Verify computed properties on BacktestResult."""

    def test_win_rate_no_trades(self):
        result = BacktestResult()
        assert result.win_rate == 0.0

    def test_win_rate_with_trades(self):
        result = BacktestResult(
            total_trades=4,
            winning_trades=3,
            losing_trades=1,
        )
        assert result.win_rate == 0.75

    def test_return_pct(self):
        result = BacktestResult(
            initial_balance=10000.0,
            final_balance=11000.0,
        )
        assert result.return_pct == pytest.approx(10.0)

    def test_return_pct_zero_balance(self):
        result = BacktestResult(initial_balance=0.0, final_balance=100.0)
        assert result.return_pct == 0.0

    def test_profit_factor_no_losses(self):
        result = BacktestResult(
            trades=[
                TradeRecord(
                    symbol="BTC",
                    side="LONG",
                    entry_price=100,
                    exit_price=110,
                    quantity=1,
                    realized_pnl=10,
                    fee=0,
                    entry_candle_index=0,
                    exit_candle_index=1,
                    exit_reason="tp",
                )
            ]
        )
        assert result.profit_factor == float("inf")

    def test_profit_factor_no_trades(self):
        result = BacktestResult()
        assert result.profit_factor == 0.0

    def test_profit_factor_mixed(self):
        result = BacktestResult(
            trades=[
                TradeRecord(
                    symbol="BTC",
                    side="LONG",
                    entry_price=100,
                    exit_price=120,
                    quantity=1,
                    realized_pnl=20,
                    fee=0,
                    entry_candle_index=0,
                    exit_candle_index=1,
                    exit_reason="tp",
                ),
                TradeRecord(
                    symbol="BTC",
                    side="LONG",
                    entry_price=100,
                    exit_price=90,
                    quantity=1,
                    realized_pnl=-10,
                    fee=0,
                    entry_candle_index=2,
                    exit_candle_index=3,
                    exit_reason="sl",
                ),
            ]
        )
        assert result.profit_factor == pytest.approx(2.0)


class TestMultipleSymbols:
    """Verify backtesting with multiple symbols simultaneously."""

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, default_config):
        btc_candles = make_candle_series(12, symbol="BTCUSDT", base_price=50000.0)
        eth_candles = make_candle_series(12, symbol="ETHUSDT", base_price=3000.0)

        provider = HistoricalDataProvider(
            candle_data={
                "BTCUSDT": {"1m": btc_candles},
                "ETHUSDT": {"1m": eth_candles},
            },
        )

        strategies = {
            "BTCUSDT": ExitAfterNStrategy("BTCUSDT", exit_after=3),
            "ETHUSDT": ExitAfterNStrategy("ETHUSDT", exit_after=3),
        }
        default_config.backfill_limit = 5

        engine = BacktestEngine(
            strategies=strategies,
            data_provider=provider,
            config=default_config,
        )

        result = await engine.run()

        # Both symbols should produce trades
        symbols_traded = {t.symbol for t in result.trades}
        assert "BTCUSDT" in symbols_traded
        assert "ETHUSDT" in symbols_traded


class TestBacktestPerformance:
    """Verify processing speed for large candle datasets."""

    @pytest.mark.asyncio
    async def test_backtest_performance(self, default_config):
        """10000+ candles should process in < 2 seconds."""
        n = 10500
        candles = make_candle_series(n, base_price=100.0, trend=0.01)
        provider = make_data_provider(candles)
        strategy = NeverTradeStrategy("BTCUSDT")
        default_config.backfill_limit = 100

        engine = BacktestEngine(
            strategies={"BTCUSDT": strategy},
            data_provider=provider,
            config=default_config,
        )

        start = time.monotonic()
        result = await engine.run()
        elapsed = time.monotonic() - start

        assert result.candles_processed >= 10000
        assert elapsed < 2.0, f"Processing took {elapsed:.2f}s, expected < 2s"


class TestDrawdownTracking:
    """Verify max drawdown calculation."""

    def test_drawdown_update(self):
        """Drawdown should track peak-to-trough decline."""
        engine = BacktestEngine.__new__(BacktestEngine)
        engine._peak_balance = 10000.0
        engine._max_drawdown = 0.0

        # Balance drops
        engine._update_drawdown(9000.0)
        assert engine._max_drawdown == pytest.approx(0.1)  # 10%

        # Balance recovers partially
        engine._update_drawdown(9500.0)
        assert engine._max_drawdown == pytest.approx(0.1)  # still 10%

        # New peak
        engine._update_drawdown(10500.0)
        assert engine._peak_balance == 10500.0
        assert engine._max_drawdown == pytest.approx(0.1)  # unchanged

        # Bigger drawdown from new peak
        engine._update_drawdown(8400.0)
        assert engine._max_drawdown == pytest.approx(0.2)  # 20%
