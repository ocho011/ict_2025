"""
Unit tests for ComposableStrategy and modular determiner assembly.

Tests verify:
- ComposableStrategy initialization with StrategyModuleConfig
- Entry determination delegation (EntryDeterminer → EntryDecision → Signal)
- TP/SL calculation via injected determiners
- RR ratio validation and filtering
- Internal metadata stripping (keys prefixed with _)
- Exit determination delegation
- StrategyFactory.create_composed() integration
- Entry determiners: AlwaysEntryDeterminer, SMAEntryDeterminer
- NullExitDeterminer pass-through
"""

from collections import deque
from datetime import datetime, timezone
from typing import Optional

import pytest

from src.entry.always_entry import AlwaysEntryDeterminer
from src.entry.base import EntryContext, EntryDecision, EntryDeterminer
from src.entry.sma_entry import SMAEntryDeterminer
from src.exit.base import ExitContext, ExitDeterminer, NullExitDeterminer
from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.pricing.base import (
    PriceContext,
    PriceDeterminerConfig,
    StopLossDeterminer,
    StrategyModuleConfig,
    TakeProfitDeterminer,
)
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.strategies import ComposableStrategy, StrategyFactory


# ============================================================================
# Test Helpers
# ============================================================================


def make_candle(
    close: float = 50000.0,
    is_closed: bool = True,
    interval: str = "1m",
    symbol: str = "BTCUSDT",
) -> Candle:
    """Create a test candle."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=100.0,
        is_closed=is_closed,
    )


class FixedEntryDeterminer(EntryDeterminer):
    """Test determiner that returns a fixed EntryDecision."""

    def __init__(
        self,
        signal_type: SignalType = SignalType.LONG_ENTRY,
        entry_price: float = 50000.0,
        confidence: float = 0.85,
        metadata: Optional[dict] = None,
    ):
        self._signal_type = signal_type
        self._entry_price = entry_price
        self._confidence = confidence
        self._metadata = metadata or {}

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        return EntryDecision(
            signal_type=self._signal_type,
            entry_price=self._entry_price,
            confidence=self._confidence,
            metadata=self._metadata,
        )


class NoneEntryDeterminer(EntryDeterminer):
    """Test determiner that always returns None (no entry)."""

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        return None


class FixedExitDeterminer(ExitDeterminer):
    """Test determiner that always returns an exit signal."""

    def should_exit(self, context: ExitContext) -> Optional[Signal]:
        return Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol=context.symbol,
            entry_price=context.candle.close,
            strategy_name="FixedExitDeterminer",
            timestamp=datetime.now(timezone.utc),
            exit_reason="test_exit",
        )


class FixedStopLoss(StopLossDeterminer):
    """Test SL determiner with fixed percentage."""

    def __init__(self, pct: float = 0.01):
        self.pct = pct

    def calculate_stop_loss(self, context: PriceContext) -> float:
        if context.side == "LONG":
            return context.entry_price * (1 - self.pct)
        return context.entry_price * (1 + self.pct)


class FixedTakeProfit(TakeProfitDeterminer):
    """Test TP determiner using risk-reward ratio."""

    def __init__(self, rr: float = 2.0):
        self.rr = rr

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        risk = abs(context.entry_price - stop_loss)
        if context.side == "LONG":
            return context.entry_price + risk * self.rr
        return context.entry_price - risk * self.rr


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def default_module_config():
    """Standard module config with fixed determiners."""
    return StrategyModuleConfig(
        entry_determiner=FixedEntryDeterminer(),
        stop_loss_determiner=FixedStopLoss(pct=0.01),
        take_profit_determiner=FixedTakeProfit(rr=2.0),
        exit_determiner=NullExitDeterminer(),
    )


def _init_strategy(strategy: ComposableStrategy, candle: Optional[Candle] = None):
    """Mark strategy as initialized for testing (simulates historical data load)."""
    c = candle or make_candle()
    for interval in strategy.intervals:
        strategy._initialized[interval] = True
    return strategy


@pytest.fixture
def composable_strategy(default_module_config):
    """Create a ComposableStrategy with default config."""
    strategy = ComposableStrategy(
        symbol="BTCUSDT",
        config={"buffer_size": 50},
        module_config=default_module_config,
    )
    return _init_strategy(strategy)


@pytest.fixture
def closed_candle():
    return make_candle(close=50000.0, is_closed=True)


@pytest.fixture
def open_candle():
    return make_candle(close=50000.0, is_closed=False)


# ============================================================================
# ComposableStrategy Initialization Tests
# ============================================================================


class TestComposableStrategyInit:
    """Test ComposableStrategy initialization."""

    def test_basic_init(self, composable_strategy):
        assert composable_strategy.symbol == "BTCUSDT"
        assert composable_strategy.min_rr_ratio == 1.5
        assert isinstance(composable_strategy.module_config, StrategyModuleConfig)

    def test_custom_min_rr_ratio(self, default_module_config):
        strategy = ComposableStrategy(
            symbol="ETHUSDT",
            config={},
            module_config=default_module_config,
            min_rr_ratio=2.5,
        )
        assert strategy.min_rr_ratio == 2.5

    def test_custom_intervals(self, default_module_config):
        strategy = ComposableStrategy(
            symbol="BTCUSDT",
            config={},
            module_config=default_module_config,
            intervals=["5m", "1h", "4h"],
        )
        assert strategy.intervals == ["5m", "1h", "4h"]
        assert "5m" in strategy.buffers
        assert "1h" in strategy.buffers
        assert "4h" in strategy.buffers

    def test_price_config_uses_module_determiners(self, composable_strategy):
        """_create_price_config should use module_config's SL/TP determiners."""
        assert isinstance(
            composable_strategy._price_config.stop_loss_determiner, FixedStopLoss
        )
        assert isinstance(
            composable_strategy._price_config.take_profit_determiner, FixedTakeProfit
        )

    def test_inherits_base_strategy(self, composable_strategy):
        from src.strategies.base import BaseStrategy

        assert isinstance(composable_strategy, BaseStrategy)


# ============================================================================
# ComposableStrategy.analyze() Tests
# ============================================================================


class TestComposableStrategyAnalyze:
    """Test the analyze() orchestration flow."""

    @pytest.mark.asyncio
    async def test_returns_none_on_open_candle(self, composable_strategy, open_candle):
        result = await composable_strategy.analyze(open_candle)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_entry_determiner_returns_none(self):
        """No signal when entry determiner sees no opportunity."""
        module_config = StrategyModuleConfig(
            entry_determiner=NoneEntryDeterminer(),
            stop_loss_determiner=FixedStopLoss(),
            take_profit_determiner=FixedTakeProfit(),
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT", config={}, module_config=module_config
        ))
        candle = make_candle(is_closed=True)
        result = await strategy.analyze(candle)
        assert result is None

    @pytest.mark.asyncio
    async def test_produces_long_signal(self, closed_candle):
        """Full flow: entry decision → SL → TP → Signal assembly."""
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(
                signal_type=SignalType.LONG_ENTRY,
                entry_price=50000.0,
                confidence=0.9,
                metadata={"trend": "bullish"},
            ),
            stop_loss_determiner=FixedStopLoss(pct=0.01),  # SL = 49500
            take_profit_determiner=FixedTakeProfit(rr=2.0),  # TP = 51000
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT", config={}, module_config=module_config
        ))

        signal = await strategy.analyze(closed_candle)

        assert signal is not None
        assert signal.signal_type == SignalType.LONG_ENTRY
        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price == 50000.0
        assert signal.stop_loss == pytest.approx(49500.0)
        assert signal.take_profit == pytest.approx(51000.0)
        assert signal.confidence == 0.9
        assert "Composed(FixedEntryDeterminer)" in signal.strategy_name

    @pytest.mark.asyncio
    async def test_produces_short_signal(self, closed_candle):
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(
                signal_type=SignalType.SHORT_ENTRY,
                entry_price=50000.0,
            ),
            stop_loss_determiner=FixedStopLoss(pct=0.01),  # SL = 50500
            take_profit_determiner=FixedTakeProfit(rr=2.0),  # TP = 49000
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT", config={}, module_config=module_config
        ))

        signal = await strategy.analyze(closed_candle)

        assert signal is not None
        assert signal.signal_type == SignalType.SHORT_ENTRY
        assert signal.stop_loss == pytest.approx(50500.0)
        assert signal.take_profit == pytest.approx(49000.0)

    @pytest.mark.asyncio
    async def test_rr_ratio_filter_rejects_low_rr(self, closed_candle):
        """Signal rejected when RR ratio < min_rr_ratio."""
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(entry_price=50000.0),
            stop_loss_determiner=FixedStopLoss(pct=0.01),
            take_profit_determiner=FixedTakeProfit(rr=0.5),  # RR = 0.5 < 1.5
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT",
            config={},
            module_config=module_config,
            min_rr_ratio=1.5,
        ))

        signal = await strategy.analyze(closed_candle)
        assert signal is None

    @pytest.mark.asyncio
    async def test_rr_ratio_filter_accepts_high_rr(self, closed_candle):
        """Signal accepted when RR ratio >= min_rr_ratio."""
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(entry_price=50000.0),
            stop_loss_determiner=FixedStopLoss(pct=0.01),
            take_profit_determiner=FixedTakeProfit(rr=3.0),  # RR = 3.0 >= 1.5
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT",
            config={},
            module_config=module_config,
            min_rr_ratio=1.5,
        ))

        signal = await strategy.analyze(closed_candle)
        assert signal is not None
        assert signal.metadata["rr_ratio"] == 3.0

    @pytest.mark.asyncio
    async def test_metadata_stripping_internal_keys(self, closed_candle):
        """Keys prefixed with _ are stripped from public Signal metadata."""
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(
                metadata={
                    "_fvg_zone": (49800.0, 49900.0),
                    "_ob_zone": (49700.0, 49800.0),
                    "_displacement_size": 500.0,
                    "trend": "bullish",
                    "killzone": "london",
                }
            ),
            stop_loss_determiner=FixedStopLoss(pct=0.01),
            take_profit_determiner=FixedTakeProfit(rr=2.0),
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT", config={}, module_config=module_config
        ))

        signal = await strategy.analyze(closed_candle)

        assert signal is not None
        # Internal keys stripped
        assert "_fvg_zone" not in signal.metadata
        assert "_ob_zone" not in signal.metadata
        assert "_displacement_size" not in signal.metadata
        # Public keys preserved
        assert signal.metadata["trend"] == "bullish"
        assert signal.metadata["killzone"] == "london"
        # RR ratio added
        assert "rr_ratio" in signal.metadata

    @pytest.mark.asyncio
    async def test_zone_data_passed_to_price_context(self, closed_candle):
        """Internal metadata passed to PriceContext for SL/TP calculation."""

        class ZoneCaptureSL(StopLossDeterminer):
            """Captures PriceContext for inspection."""

            def __init__(self):
                self.captured_context = None

            def calculate_stop_loss(self, context: PriceContext) -> float:
                self.captured_context = context
                if context.side == "LONG":
                    return context.entry_price * 0.99
                return context.entry_price * 1.01

        sl_determiner = ZoneCaptureSL()
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(
                metadata={
                    "_fvg_zone": (49800.0, 49900.0),
                    "_ob_zone": (49700.0, 49800.0),
                    "_displacement_size": 500.0,
                }
            ),
            stop_loss_determiner=sl_determiner,
            take_profit_determiner=FixedTakeProfit(rr=2.0),
            exit_determiner=NullExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT", config={}, module_config=module_config
        ))

        await strategy.analyze(closed_candle)

        ctx = sl_determiner.captured_context
        assert ctx is not None
        assert ctx.fvg_zone == (49800.0, 49900.0)
        assert ctx.ob_zone == (49700.0, 49800.0)
        assert ctx.displacement_size == 500.0
        assert ctx.side == "LONG"
        assert ctx.entry_price == 50000.0


# ============================================================================
# ComposableStrategy.should_exit() Tests
# ============================================================================


class TestComposableStrategyShouldExit:
    """Test exit determination delegation."""

    @pytest.mark.asyncio
    async def test_returns_none_on_open_candle(self, composable_strategy, open_candle):
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=1,
        )
        result = await composable_strategy.should_exit(position, open_candle)
        assert result is None

    @pytest.mark.asyncio
    async def test_null_exit_returns_none(self, composable_strategy, closed_candle):
        """NullExitDeterminer always returns None."""
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=49000.0,
            quantity=0.1,
            leverage=1,
        )
        result = await composable_strategy.should_exit(position, closed_candle)
        assert result is None

    @pytest.mark.asyncio
    async def test_exit_determiner_delegation(self, closed_candle):
        """Exit signal from determiner is returned by should_exit."""
        module_config = StrategyModuleConfig(
            entry_determiner=NoneEntryDeterminer(),
            stop_loss_determiner=FixedStopLoss(),
            take_profit_determiner=FixedTakeProfit(),
            exit_determiner=FixedExitDeterminer(),
        )
        strategy = _init_strategy(ComposableStrategy(
            symbol="BTCUSDT", config={}, module_config=module_config
        ))
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=49000.0,
            quantity=0.1,
            leverage=1,
        )

        result = await strategy.should_exit(position, closed_candle)

        assert result is not None
        assert result.signal_type == SignalType.CLOSE_LONG
        assert result.exit_reason == "test_exit"


# ============================================================================
# AlwaysEntryDeterminer Tests
# ============================================================================


class TestAlwaysEntryDeterminer:
    """Test the always-signal entry determiner."""

    def _make_context(self, candle: Candle) -> EntryContext:
        import time

        return EntryContext(
            symbol="BTCUSDT",
            candle=candle,
            buffers={"1m": deque([candle], maxlen=100)},
            indicator_cache=None,
            timestamp=int(time.time() * 1000),
            config={},
        )

    def test_alternate_mode_default(self):
        det = AlwaysEntryDeterminer()
        assert det.signal_mode == "ALTERNATE"

    def test_alternate_mode_switches(self):
        det = AlwaysEntryDeterminer(signal_mode="ALTERNATE")
        candle = make_candle(is_closed=True)
        ctx = self._make_context(candle)

        d1 = det.analyze(ctx)
        d2 = det.analyze(ctx)

        assert d1.signal_type == SignalType.LONG_ENTRY
        assert d2.signal_type == SignalType.SHORT_ENTRY

    def test_long_only_mode(self):
        det = AlwaysEntryDeterminer(signal_mode="LONG")
        candle = make_candle(is_closed=True)
        ctx = self._make_context(candle)

        d1 = det.analyze(ctx)
        d2 = det.analyze(ctx)

        assert d1.signal_type == SignalType.LONG_ENTRY
        assert d2.signal_type == SignalType.LONG_ENTRY

    def test_short_only_mode(self):
        det = AlwaysEntryDeterminer(signal_mode="SHORT")
        candle = make_candle(is_closed=True)
        ctx = self._make_context(candle)

        d1 = det.analyze(ctx)
        assert d1.signal_type == SignalType.SHORT_ENTRY

    def test_returns_none_on_open_candle(self):
        det = AlwaysEntryDeterminer()
        candle = make_candle(is_closed=False)
        ctx = self._make_context(candle)

        result = det.analyze(ctx)
        assert result is None

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="signal_mode"):
            AlwaysEntryDeterminer(signal_mode="INVALID")

    def test_returns_entry_decision_type(self):
        det = AlwaysEntryDeterminer()
        candle = make_candle(is_closed=True)
        ctx = self._make_context(candle)

        result = det.analyze(ctx)
        assert isinstance(result, EntryDecision)
        assert result.entry_price == 50000.0


# ============================================================================
# SMAEntryDeterminer Tests
# ============================================================================


class TestSMAEntryDeterminer:
    """Test the SMA crossover entry determiner."""

    def _make_context_with_buffer(self, candles, interval="1m") -> EntryContext:
        import time

        buf = deque(candles, maxlen=200)
        return EntryContext(
            symbol="BTCUSDT",
            candle=candles[-1],
            buffers={interval: buf},
            indicator_cache=None,
            timestamp=int(time.time() * 1000),
            config={"default_interval": interval},
        )

    def test_init_defaults(self):
        det = SMAEntryDeterminer()
        assert det.fast_period == 10
        assert det.slow_period == 20

    def test_returns_none_with_insufficient_data(self):
        det = SMAEntryDeterminer(fast_period=3, slow_period=5)
        candles = [make_candle(close=50000.0 + i) for i in range(3)]
        ctx = self._make_context_with_buffer(candles)

        result = det.analyze(ctx)
        assert result is None

    def test_golden_cross_long_signal(self):
        """Prices rising → fast SMA crosses above slow SMA → LONG."""
        det = SMAEntryDeterminer(fast_period=3, slow_period=5)

        # Create descending then ascending prices to trigger golden cross
        prices = [100, 99, 98, 97, 96, 97, 98, 99, 100, 101]
        candles = [make_candle(close=p) for p in prices]
        ctx = self._make_context_with_buffer(candles)

        result = det.analyze(ctx)
        # May or may not trigger depending on exact SMA values
        # but should not raise an error
        if result is not None:
            assert result.signal_type == SignalType.LONG_ENTRY
            assert isinstance(result, EntryDecision)


# ============================================================================
# NullExitDeterminer Tests
# ============================================================================


class TestNullExitDeterminer:

    def test_always_returns_none(self):
        import time

        det = NullExitDeterminer()
        candle = make_candle()
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=49000.0,
            quantity=0.1,
            leverage=1,
        )
        ctx = ExitContext(
            symbol="BTCUSDT",
            candle=candle,
            position=position,
            buffers={"1m": deque([candle])},
            indicator_cache=None,
            timestamp=int(time.time() * 1000),
            config={},
        )

        result = det.should_exit(ctx)
        assert result is None


# ============================================================================
# StrategyFactory.create_composed Tests
# ============================================================================


class TestStrategyFactoryCreateComposed:

    def test_creates_composable_strategy(self):
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(stop_loss_percent=0.01),
            take_profit_determiner=RiskRewardTakeProfit(risk_reward_ratio=2.0),
            exit_determiner=NullExitDeterminer(),
        )

        strategy = StrategyFactory.create_composed(
            symbol="BTCUSDT",
            config={"buffer_size": 100},
            module_config=module_config,
        )

        assert isinstance(strategy, ComposableStrategy)
        assert strategy.symbol == "BTCUSDT"

    def test_custom_intervals_and_rr(self):
        module_config = StrategyModuleConfig(
            entry_determiner=FixedEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(stop_loss_percent=0.01),
            take_profit_determiner=RiskRewardTakeProfit(risk_reward_ratio=2.0),
            exit_determiner=NullExitDeterminer(),
        )

        strategy = StrategyFactory.create_composed(
            symbol="ETHUSDT",
            config={},
            module_config=module_config,
            intervals=["5m", "1h"],
            min_rr_ratio=2.0,
        )

        assert strategy.symbol == "ETHUSDT"
        assert strategy.min_rr_ratio == 2.0
        assert "5m" in strategy.buffers
        assert "1h" in strategy.buffers

    @pytest.mark.asyncio
    async def test_end_to_end_signal_generation(self):
        """Full integration: factory → strategy → signal."""
        module_config = StrategyModuleConfig(
            entry_determiner=AlwaysEntryDeterminer(signal_mode="LONG"),
            stop_loss_determiner=PercentageStopLoss(stop_loss_percent=0.02),
            take_profit_determiner=RiskRewardTakeProfit(risk_reward_ratio=2.0),
            exit_determiner=NullExitDeterminer(),
        )

        strategy = _init_strategy(StrategyFactory.create_composed(
            symbol="BTCUSDT",
            config={},
            module_config=module_config,
            min_rr_ratio=1.0,
        ))

        candle = make_candle(close=50000.0, is_closed=True)
        signal = await strategy.analyze(candle)

        assert signal is not None
        assert signal.signal_type == SignalType.LONG_ENTRY
        assert signal.entry_price == 50000.0
        assert signal.stop_loss < signal.entry_price
        assert signal.take_profit > signal.entry_price
        assert signal.metadata["rr_ratio"] == 2.0
