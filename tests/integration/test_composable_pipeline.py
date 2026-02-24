"""
Integration tests for composable strategy pipeline.

Tests the full event-driven pipeline:
  Candle -> EventDispatcher -> ComposableStrategy -> Signal -> EventBus

Uses AlwaysEntryDeterminer for predictable signal generation
with real EventBus, EventDispatcher, and ComposableStrategy.
"""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.event_bus import EventBus
from src.core.event_dispatcher import EventDispatcher
from src.core.exceptions import EngineState
from src.entry import AlwaysEntryDeterminer
from src.exit import NullExitDeterminer
from src.strategies.ict.exit import ICTExitDeterminer
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.models.position import Position
from src.models.signal import SignalType
from src.pricing.base import StrategyModuleConfig
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.strategies import ComposableStrategy, StrategyFactory


def _make_candle(symbol: str = "BTCUSDT", interval: str = "5m", close: float = 50000.0) -> Candle:
    now = datetime.now(timezone.utc)
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=now,
        open=close - 100,
        high=close + 50,
        low=close - 150,
        close=close,
        volume=100.0,
        close_time=now,
        is_closed=True,
    )


def _make_composable_strategy(symbol: str = "BTCUSDT") -> ComposableStrategy:
    module_config = StrategyModuleConfig(
        entry_determiner=AlwaysEntryDeterminer(),
        stop_loss_determiner=PercentageStopLoss(),
        take_profit_determiner=RiskRewardTakeProfit(),
        exit_determiner=NullExitDeterminer(),
    )
    strategy = StrategyFactory.create_composed(
        symbol=symbol,
        config={"rr_ratio": 2.0, "stop_loss_percent": 0.02},
        module_config=module_config,
        intervals=["5m"],
        min_rr_ratio=1.5,
    )
    # Mark buffer as initialized (normally done via initialize_history)
    strategy._initialized["5m"] = True
    return strategy


def _make_position_cache_manager():
    """Create a mock PositionCacheManager."""
    pcm = MagicMock()
    pcm.get.return_value = None  # No position by default
    pcm.cache = {"BTCUSDT": (None, time.time())}
    pcm._last_signal_time = {}
    pcm._ttl = 60.0
    return pcm


def _make_dispatcher(strategies, pcm=None, event_bus=None, order_gateway=None):
    """Create EventDispatcher with mocked dependencies."""
    if pcm is None:
        pcm = _make_position_cache_manager()
    if event_bus is None:
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
    if order_gateway is None:
        order_gateway = MagicMock()

    audit_logger = MagicMock()
    audit_logger.log_event = MagicMock()

    return EventDispatcher(
        strategies=strategies,
        position_cache_manager=pcm,
        event_bus=event_bus,
        audit_logger=audit_logger,
        order_gateway=order_gateway,
        engine_state_getter=lambda: EngineState.RUNNING,
        event_loop_getter=lambda: asyncio.get_event_loop(),
    )


class TestEntryFlow:
    """Test 1: Full entry flow - Candle -> Strategy.analyze() -> Signal -> SIGNAL_GENERATED."""

    @pytest.mark.asyncio
    async def test_composable_strategy_generates_entry_signal(self):
        """AlwaysEntryDeterminer produces a signal through the full pipeline."""
        strategy = _make_composable_strategy()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        dispatcher = _make_dispatcher(
            strategies={"BTCUSDT": strategy},
            event_bus=event_bus,
        )

        candle = _make_candle()
        event = Event(event_type=EventType.CANDLE_CLOSED, data=candle)

        await dispatcher.on_candle_closed(event)

        # EventBus.publish should have been called with a SIGNAL_GENERATED event
        assert event_bus.publish.called
        published_event = event_bus.publish.call_args[1].get("event") or event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.SIGNAL_GENERATED
        assert published_event.data.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY)


class TestExitFlow:
    """Test 2: Full exit flow - Candle + Position -> should_exit() -> Signal."""

    @pytest.mark.asyncio
    async def test_composable_strategy_exit_with_position(self):
        """Exit analysis is triggered when position exists."""
        # Use ICTExitDeterminer for exit logic
        from src.utils.config_manager import ExitConfig

        exit_config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.02,
            trailing_activation=0.001,  # Very low activation for testing
        )
        module_config = StrategyModuleConfig(
            entry_determiner=AlwaysEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=ICTExitDeterminer(
                exit_config=exit_config,
                swing_lookback=5,
                displacement_ratio=1.5,
                mtf_interval="1h",
                htf_interval="4h",
            ),
        )
        strategy = StrategyFactory.create_composed(
            symbol="BTCUSDT",
            config={"rr_ratio": 2.0},
            module_config=module_config,
            intervals=["5m"],
        )
        strategy._initialized["5m"] = True

        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=49000.0,
            quantity=0.1,
            leverage=10,
            entry_time=datetime.now(timezone.utc),
        )

        pcm = _make_position_cache_manager()
        pcm.get.return_value = position  # Position exists

        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        dispatcher = _make_dispatcher(
            strategies={"BTCUSDT": strategy},
            pcm=pcm,
            event_bus=event_bus,
        )

        # Price significantly above entry to trigger trailing stop
        candle = _make_candle(close=50000.0)
        event = Event(event_type=EventType.CANDLE_CLOSED, data=candle)

        await dispatcher.on_candle_closed(event)

        # With position, exit analysis is run (not entry)
        # The exit may or may not generate a signal depending on strategy state,
        # but process_exit_strategy should have been called without error
        # Verify no exception occurred (integration success)


class TestDynamicSLSync:
    """Test 3: Dynamic SL sync - trailing level -> exchange SL update."""

    @pytest.mark.asyncio
    async def test_trailing_level_triggers_sl_update(self):
        """TrailingLevelProvider protocol enables exchange SL sync."""
        from src.utils.config_manager import ExitConfig

        exit_config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.02,
            trailing_activation=0.001,
        )
        exit_det = ICTExitDeterminer(
            exit_config=exit_config,
            swing_lookback=5,
            displacement_ratio=1.5,
            mtf_interval="1h",
            htf_interval="4h",
        )

        module_config = StrategyModuleConfig(
            entry_determiner=AlwaysEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=exit_det,
        )
        strategy = StrategyFactory.create_composed(
            symbol="BTCUSDT",
            config={"rr_ratio": 2.0},
            module_config=module_config,
            intervals=["5m"],
        )
        strategy._initialized["5m"] = True

        # Manually set a trailing level
        exit_det._trailing_levels["BTCUSDT_LONG"] = 49500.0

        # Verify protocol works
        from src.strategies.trailing_level_protocol import TrailingLevelProvider
        assert isinstance(strategy, TrailingLevelProvider)
        assert strategy.trailing_levels["BTCUSDT_LONG"] == 49500.0

        # Setup dispatcher with mock order gateway
        position = Position(
            symbol="BTCUSDT", side="LONG", entry_price=49000.0,
            quantity=0.1, leverage=10, entry_time=datetime.now(timezone.utc),
        )

        order_gateway = MagicMock()
        order_gateway.update_stop_loss.return_value = True

        pcm = _make_position_cache_manager()
        pcm.get.return_value = position

        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        dispatcher = _make_dispatcher(
            strategies={"BTCUSDT": strategy},
            pcm=pcm,
            event_bus=event_bus,
            order_gateway=order_gateway,
        )

        candle = _make_candle(close=50000.0)

        # Call maybe_update_exchange_sl directly
        await dispatcher.maybe_update_exchange_sl(candle, strategy, position)

        # Order gateway should have been called to update SL
        order_gateway.update_stop_loss.assert_called_once()
        call_kwargs = order_gateway.update_stop_loss.call_args[1]
        assert call_kwargs["symbol"] == "BTCUSDT"
        assert call_kwargs["new_stop_price"] == 49500.0


class TestIssue123TrailingStopInitialSL:
    """Test Issue #123: trailing stop initial_stop must not overwrite a better SL."""

    @pytest.mark.asyncio
    async def test_entry_signal_initializes_last_exchange_sl(self):
        """process_entry_strategy stores signal.stop_loss in _last_exchange_sl (Issue #123)."""
        strategy = _make_composable_strategy()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        dispatcher = _make_dispatcher(
            strategies={"BTCUSDT": strategy},
            event_bus=event_bus,
        )

        candle = _make_candle(close=50000.0)
        event = Event(event_type=EventType.CANDLE_CLOSED, data=candle)

        # No position -> runs process_entry_strategy -> generates LONG signal
        await dispatcher.on_candle_closed(event)

        # _last_exchange_sl must be seeded with the strategy's original SL
        assert "BTCUSDT" in dispatcher._last_exchange_sl
        original_sl = dispatcher._last_exchange_sl["BTCUSDT"]
        # PercentageStopLoss default 1% below entry 50000 -> ~49500
        assert original_sl < 50000.0, "LONG SL must be below entry"

    @pytest.mark.asyncio
    async def test_short_trailing_initial_stop_does_not_worsen_sl(self):
        """Direction guard blocks trailing initial_stop from moving SHORT SL higher (Issue #123).

        Scenario (DOGEUSDT SHORT from the bug report):
          Original SL  : 0.10117  (entry * 1.005 — tight, 0.5% above entry)
          Trailing init: 0.10267  (entry * 1.020 — trailing_distance=2%, worse for SHORT)
        Expected: exchange SL stays at 0.10117, update_stop_loss NOT called.
        """
        from src.utils.config_manager import ExitConfig

        exit_config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.02,
            trailing_activation=0.01,
        )
        exit_det = ICTExitDeterminer(
            exit_config=exit_config,
            swing_lookback=5,
            displacement_ratio=1.5,
            mtf_interval="1h",
            htf_interval="4h",
        )
        entry_price = 0.10066
        # Simulate trailing initial_stop for SHORT: entry * (1 + 0.02) = 0.10267
        initial_stop = entry_price * (1 + exit_config.trailing_distance)  # 0.10267
        exit_det._trailing_levels["DOGEUSDT_SHORT"] = initial_stop

        module_config = StrategyModuleConfig(
            entry_determiner=AlwaysEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=exit_det,
        )
        strategy = StrategyFactory.create_composed(
            symbol="DOGEUSDT",
            config={"rr_ratio": 2.0},
            module_config=module_config,
            intervals=["5m"],
        )
        strategy._initialized["5m"] = True

        position = Position(
            symbol="DOGEUSDT", side="SHORT", entry_price=entry_price,
            quantity=100.0, leverage=10, entry_time=datetime.now(timezone.utc),
        )
        order_gateway = MagicMock()
        order_gateway.update_stop_loss.return_value = True

        pcm = _make_position_cache_manager()
        pcm.get.return_value = position
        pcm.cache = {"DOGEUSDT": (position, time.time())}

        dispatcher = _make_dispatcher(
            strategies={"DOGEUSDT": strategy},
            pcm=pcm,
            order_gateway=order_gateway,
        )
        # Seed _last_exchange_sl with the strategy's tight original SL (entry * 1.005)
        original_sl = entry_price * 1.005  # 0.10117
        dispatcher._last_exchange_sl["DOGEUSDT"] = original_sl

        candle = _make_candle(symbol="DOGEUSDT", close=entry_price)
        await dispatcher.maybe_update_exchange_sl(candle, strategy, position)

        # Direction guard must block the worsening update
        order_gateway.update_stop_loss.assert_not_called()
        # _last_exchange_sl must remain at the tight original SL
        assert dispatcher._last_exchange_sl["DOGEUSDT"] == original_sl

    @pytest.mark.asyncio
    async def test_short_trailing_improvement_is_allowed(self):
        """Direction guard allows exchange SL update when trailing moves SHORT SL lower (Issue #123)."""
        from src.utils.config_manager import ExitConfig

        exit_config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.02,
            trailing_activation=0.01,
        )
        exit_det = ICTExitDeterminer(
            exit_config=exit_config,
            swing_lookback=5,
            displacement_ratio=1.5,
            mtf_interval="1h",
            htf_interval="4h",
        )
        entry_price = 0.10066
        original_sl = entry_price * 1.005   # 0.10117  (original, wider)
        improved_sl = entry_price * 0.990   # ~0.09965 (ratcheted lower = better for SHORT)
        exit_det._trailing_levels["DOGEUSDT_SHORT"] = improved_sl

        module_config = StrategyModuleConfig(
            entry_determiner=AlwaysEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=exit_det,
        )
        strategy = StrategyFactory.create_composed(
            symbol="DOGEUSDT",
            config={"rr_ratio": 2.0},
            module_config=module_config,
            intervals=["5m"],
        )
        strategy._initialized["5m"] = True

        position = Position(
            symbol="DOGEUSDT", side="SHORT", entry_price=entry_price,
            quantity=100.0, leverage=10, entry_time=datetime.now(timezone.utc),
        )
        order_gateway = MagicMock()
        order_gateway.update_stop_loss.return_value = True

        pcm = _make_position_cache_manager()
        pcm.get.return_value = position
        pcm.cache = {"DOGEUSDT": (position, time.time())}

        dispatcher = _make_dispatcher(
            strategies={"DOGEUSDT": strategy},
            pcm=pcm,
            order_gateway=order_gateway,
        )
        dispatcher._last_exchange_sl["DOGEUSDT"] = original_sl

        candle = _make_candle(symbol="DOGEUSDT", close=entry_price * 0.985)
        await dispatcher.maybe_update_exchange_sl(candle, strategy, position)

        # Improvement (lower SL for SHORT) must be allowed
        order_gateway.update_stop_loss.assert_called_once()
        call_kwargs = order_gateway.update_stop_loss.call_args[1]
        assert call_kwargs["new_stop_price"] == improved_sl


class TestSignalCooldown:
    """Test 4: Signal cooldown - two rapid candles -> only first generates signal."""

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_signals(self):
        """Second candle within cooldown window does not generate signal."""
        strategy = _make_composable_strategy()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        dispatcher = _make_dispatcher(
            strategies={"BTCUSDT": strategy},
            event_bus=event_bus,
        )

        candle1 = _make_candle(close=50000.0)
        candle2 = _make_candle(close=50100.0)

        event1 = Event(event_type=EventType.CANDLE_CLOSED, data=candle1)
        event2 = Event(event_type=EventType.CANDLE_CLOSED, data=candle2)

        # First candle should generate signal
        await dispatcher.on_candle_closed(event1)
        first_call_count = event_bus.publish.call_count

        # Second candle within cooldown should NOT generate signal
        await dispatcher.on_candle_closed(event2)
        second_call_count = event_bus.publish.call_count

        assert first_call_count > 0, "First candle should generate signal"
        assert second_call_count == first_call_count, "Second candle should be blocked by cooldown"


class TestMultiSymbol:
    """Test 5: Multi-symbol - BTCUSDT + ETHUSDT both composable."""

    @pytest.mark.asyncio
    async def test_multi_symbol_composable_strategies(self):
        """Both symbols create composable strategies and generate signals independently."""
        btc_strategy = _make_composable_strategy("BTCUSDT")
        eth_strategy = _make_composable_strategy("ETHUSDT")

        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        pcm = _make_position_cache_manager()
        pcm.cache["ETHUSDT"] = (None, time.time())

        dispatcher = _make_dispatcher(
            strategies={"BTCUSDT": btc_strategy, "ETHUSDT": eth_strategy},
            pcm=pcm,
            event_bus=event_bus,
        )

        btc_candle = _make_candle(symbol="BTCUSDT", close=50000.0)
        eth_candle = _make_candle(symbol="ETHUSDT", close=3000.0)

        await dispatcher.on_candle_closed(Event(event_type=EventType.CANDLE_CLOSED, data=btc_candle))
        btc_signals = event_bus.publish.call_count

        await dispatcher.on_candle_closed(Event(event_type=EventType.CANDLE_CLOSED, data=eth_candle))
        eth_signals = event_bus.publish.call_count

        # Both symbols should generate signals (AlwaysEntryDeterminer)
        assert btc_signals > 0, "BTCUSDT should generate signal"
        assert eth_signals > btc_signals, "ETHUSDT should also generate signal"
