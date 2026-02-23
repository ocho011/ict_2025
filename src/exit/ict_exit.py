"""
ICT exit determination module.

Extracted from ICTStrategy.should_exit() (lines 829-1252).
Implements 4 exit strategies: trailing_stop, breakeven, timed, indicator_based.

Key design decision: ExitConfig is passed as a constructor parameter,
NOT read from context.config. This enables explicit dependency injection
and makes the determiner testable without full config setup.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.detectors.ict_market_structure import get_current_trend
from src.detectors.ict_smc import detect_displacement, detect_inducement
from src.exit.base import ExitContext, ExitDeterminer
from src.models.module_requirements import ModuleRequirements
from src.models.signal import Signal, SignalType
from src.utils.config_manager import ExitConfig


class ICTExitDeterminer(ExitDeterminer):
    """
    ICT exit determination using 4 exit strategies.

    Extracted from ICTStrategy.should_exit() and its 4 helper methods.
    ExitConfig is received via constructor (not from context.config).

    Persistent state:
    - _trailing_levels: dict tracking trailing stop levels across candles
      Key: "{symbol}_{side}", Value: current trailing stop price

    Exit Strategies:
    1. trailing_stop: Trailing stop with activation threshold (Issue #99)
    2. breakeven: Move SL to entry when profitable
    3. timed: Exit after specified time period
    4. indicator_based: Exit based on ICT indicator reversal
    """

    def __init__(
        self,
        exit_config: Optional[ExitConfig] = None,
        swing_lookback: int = 5,
        displacement_ratio: float = 1.5,
        mtf_interval: str = "1h",
        htf_interval: str = "4h",
    ):
        self.exit_config = exit_config or ExitConfig()
        self.swing_lookback = swing_lookback
        self.displacement_ratio = displacement_ratio
        self.mtf_interval = mtf_interval
        self.htf_interval = htf_interval
        self.logger = logging.getLogger(__name__)

        # Trailing stop level persistence across candles (Issue #99)
        self._trailing_levels: dict[str, float] = {}

    @property
    def trailing_levels(self) -> dict[str, float]:
        """Trailing stop levels for TrailingLevelProvider protocol."""
        return self._trailing_levels

    @property
    def requirements(self) -> ModuleRequirements:
        """ICT exit needs mtf/htf timeframes for indicator-based exit."""
        return ModuleRequirements(
            timeframes=frozenset({self.mtf_interval, self.htf_interval}),
            min_candles={
                self.mtf_interval: 50,
                self.htf_interval: 50,
            },
        )

    def should_exit(self, context: ExitContext) -> Optional[Signal]:
        """
        Evaluate whether position should be exited using ICT exit logic.

        Extracted from ICTStrategy.should_exit() lines 829-878.

        Args:
            context: Exit context with position, candle, buffers

        Returns:
            Signal with CLOSE_LONG/CLOSE_SHORT if exit triggered, None otherwise
        """
        if not context.candle.is_closed:
            return None

        exit_config = self.exit_config
        if not exit_config.dynamic_exit_enabled:
            return None

        # Route to appropriate exit strategy
        if exit_config.exit_strategy == "trailing_stop":
            return self._check_trailing_stop_exit(context)
        elif exit_config.exit_strategy == "breakeven":
            return self._check_breakeven_exit(context)
        elif exit_config.exit_strategy == "timed":
            return self._check_timed_exit(context)
        elif exit_config.exit_strategy == "indicator_based":
            return self._check_indicator_based_exit(context)
        else:
            self.logger.warning(
                f"[{context.symbol}] Unknown exit strategy: {exit_config.exit_strategy}"
            )
            return None

    def _check_trailing_stop_exit(self, context: ExitContext) -> Optional[Signal]:
        """
        Check trailing stop exit conditions with persistent state (Issue #99).

        Trailing stop levels are persisted in self._trailing_levels across candles,
        so the stop only ever ratchets in the profitable direction.
        """
        try:
            position = context.position
            candle = context.candle
            exit_config = self.exit_config
            trail_key = f"{context.symbol}_{position.side}"

            pnl_pct = ((candle.close - position.entry_price) / position.entry_price * 100
                        if position.side == "LONG"
                        else (position.entry_price - candle.close) / position.entry_price * 100)
            self.logger.debug(
                "[%s] Trailing stop analysis: side=%s, entry=%.4f, close=%.4f, "
                "pnl=%.2f%%, activation_threshold=%.2f%%",
                context.symbol, position.side, position.entry_price, candle.close,
                pnl_pct, exit_config.trailing_activation * 100,
            )

            if position.side == "LONG":
                initial_stop = position.entry_price * (1 - exit_config.trailing_distance)
                trailing_stop = self._trailing_levels.get(trail_key, initial_stop)

                activation_price = position.entry_price * (1 + exit_config.trailing_activation)
                if candle.close > activation_price:
                    new_stop = candle.close * (1 - exit_config.trailing_distance)
                    if new_stop > trailing_stop:
                        old_stop = trailing_stop
                        trailing_stop = new_stop
                        self.logger.debug(
                            "[%s] Trailing stop ratcheted: %.4f -> %.4f (delta=%.2f%%)",
                            context.symbol, old_stop, trailing_stop,
                            (trailing_stop - old_stop) / old_stop * 100,
                        )
                else:
                    self.logger.debug(
                        "[%s] Trailing stop not activated: close=%.4f < activation=%.4f "
                        "(need +%.2f%%)",
                        context.symbol, candle.close, activation_price,
                        (activation_price - candle.close) / candle.close * 100,
                    )

                self._trailing_levels[trail_key] = trailing_stop

                distance_pct = (candle.close - trailing_stop) / trailing_stop * 100
                self.logger.debug(
                    "[%s] Trailing stop status: level=%.4f, close=%.4f, "
                    "distance=%.2f%% (trigger when <=0)",
                    context.symbol, trailing_stop, candle.close, distance_pct,
                )

                if candle.close <= trailing_stop:
                    self.logger.info(
                        f"[{context.symbol}] Trailing stop exit triggered: "
                        f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                        f"stop={trailing_stop:.2f}"
                    )
                    self._trailing_levels.pop(trail_key, None)
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        symbol=context.symbol,
                        entry_price=candle.close,
                        strategy_name="ICTExitDeterminer",
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop",
                    )

            else:  # SHORT position
                initial_stop = position.entry_price * (1 + exit_config.trailing_distance)
                trailing_stop = self._trailing_levels.get(trail_key, initial_stop)

                activation_price = position.entry_price * (1 - exit_config.trailing_activation)
                if candle.close < activation_price:
                    new_stop = candle.close * (1 + exit_config.trailing_distance)
                    if new_stop < trailing_stop:
                        old_stop = trailing_stop
                        trailing_stop = new_stop
                        self.logger.debug(
                            "[%s] Trailing stop ratcheted: %.4f -> %.4f (delta=%.2f%%)",
                            context.symbol, old_stop, trailing_stop,
                            (old_stop - trailing_stop) / old_stop * 100,
                        )
                else:
                    self.logger.debug(
                        "[%s] Trailing stop not activated: close=%.4f > activation=%.4f "
                        "(need -%.2f%%)",
                        context.symbol, candle.close, activation_price,
                        (candle.close - activation_price) / activation_price * 100,
                    )

                self._trailing_levels[trail_key] = trailing_stop

                distance_pct = (trailing_stop - candle.close) / trailing_stop * 100
                self.logger.debug(
                    "[%s] Trailing stop status: level=%.4f, close=%.4f, "
                    "distance=%.2f%% (trigger when <=0)",
                    context.symbol, trailing_stop, candle.close, distance_pct,
                )

                if candle.close >= trailing_stop:
                    self.logger.info(
                        f"[{context.symbol}] Trailing stop exit triggered: "
                        f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                        f"stop={trailing_stop:.2f}"
                    )
                    self._trailing_levels.pop(trail_key, None)
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT,
                        symbol=context.symbol,
                        entry_price=candle.close,
                        strategy_name="ICTExitDeterminer",
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop",
                    )

        except Exception as e:
            self.logger.error(f"[{context.symbol}] Error in trailing stop check: {e}")
            return None

        return None

    def _check_breakeven_exit(self, context: ExitContext) -> Optional[Signal]:
        """Check breakeven exit conditions."""
        try:
            position = context.position
            candle = context.candle
            exit_config = self.exit_config

            if not exit_config.breakeven_enabled:
                return None

            breakeven_level = position.entry_price
            profit_threshold = position.entry_price * exit_config.breakeven_offset

            pnl_pct = ((candle.close - position.entry_price) / position.entry_price * 100
                        if position.side == "LONG"
                        else (position.entry_price - candle.close) / position.entry_price * 100)
            self.logger.debug(
                "[%s] Breakeven analysis: side=%s, entry=%.4f, close=%.4f, "
                "pnl=%.2f%%, breakeven_offset=%.2f%%",
                context.symbol, position.side, position.entry_price, candle.close,
                pnl_pct, exit_config.breakeven_offset * 100,
            )

            if position.side == "LONG":
                if candle.close > position.entry_price + profit_threshold:
                    if candle.close <= breakeven_level:
                        self.logger.info(
                            f"[{context.symbol}] Breakeven exit triggered: "
                            f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                            f"breakeven={breakeven_level:.2f}"
                        )
                        return Signal(
                            signal_type=SignalType.CLOSE_LONG,
                            symbol=context.symbol,
                            entry_price=candle.close,
                            strategy_name="ICTExitDeterminer",
                            timestamp=datetime.now(timezone.utc),
                            exit_reason="breakeven",
                        )
                else:
                    self.logger.debug(
                        "[%s] Breakeven not activated: close=%.4f, "
                        "need > entry+threshold=%.4f (threshold=%.4f)",
                        context.symbol, candle.close,
                        position.entry_price + profit_threshold, profit_threshold,
                    )

            else:  # SHORT position
                if candle.close < position.entry_price - profit_threshold:
                    if candle.close >= breakeven_level:
                        self.logger.info(
                            f"[{context.symbol}] Breakeven exit triggered: "
                            f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                            f"breakeven={breakeven_level:.2f}"
                        )
                        return Signal(
                            signal_type=SignalType.CLOSE_SHORT,
                            symbol=context.symbol,
                            entry_price=candle.close,
                            strategy_name="ICTExitDeterminer",
                            timestamp=datetime.now(timezone.utc),
                            exit_reason="breakeven",
                        )
                else:
                    self.logger.debug(
                        "[%s] Breakeven not activated: close=%.4f, "
                        "need < entry-threshold=%.4f (threshold=%.4f)",
                        context.symbol, candle.close,
                        position.entry_price - profit_threshold, profit_threshold,
                    )

        except Exception as e:
            self.logger.error(f"[{context.symbol}] Error in breakeven check: {e}")
            return None

        return None

    def _check_timed_exit(self, context: ExitContext) -> Optional[Signal]:
        """Check time-based exit conditions."""
        try:
            position = context.position
            candle = context.candle
            exit_config = self.exit_config

            if not exit_config.timeout_enabled or not position.entry_time:
                return None

            elapsed_time = candle.open_time - position.entry_time
            timeout_duration = exit_config.timeout_minutes * 60

            if elapsed_time.total_seconds() >= timeout_duration:
                self.logger.info(
                    f"[{context.symbol}] Time-based exit triggered: "
                    f"elapsed={elapsed_time}, timeout={exit_config.timeout_minutes}min"
                )
                signal_type = (
                    SignalType.CLOSE_LONG
                    if position.side == "LONG"
                    else SignalType.CLOSE_SHORT
                )
                return Signal(
                    signal_type=signal_type,
                    symbol=context.symbol,
                    entry_price=candle.close,
                    strategy_name="ICTExitDeterminer",
                    timestamp=datetime.now(timezone.utc),
                    exit_reason="timed",
                )

        except Exception as e:
            self.logger.error(f"[{context.symbol}] Error in timed exit check: {e}")
            return None

        return None

    def _check_indicator_based_exit(self, context: ExitContext) -> Optional[Signal]:
        """
        Check indicator-based exit conditions using ICT analysis.

        Uses ICT Smart Money Concepts to detect trend reversals and liquidity
        that warrant exiting positions before TP/SL are hit.
        """
        try:
            position = context.position
            candle = context.candle

            mtf_buffer = context.buffers.get(self.mtf_interval)
            if not mtf_buffer or len(mtf_buffer) < 50:
                return None

            # Get current trend from ICT analysis
            trend = None
            if context.indicator_cache is not None:
                htf_structure = context.indicator_cache.get_market_structure(
                    self.htf_interval
                )
                mtf_structure = context.indicator_cache.get_market_structure(
                    self.mtf_interval
                )
                trend = (
                    htf_structure.trend
                    if htf_structure and hasattr(htf_structure, "trend")
                    else (
                        mtf_structure.trend
                        if mtf_structure and hasattr(mtf_structure, "trend")
                        else None
                    )
                )
            else:
                trend = get_current_trend(
                    mtf_buffer, swing_lookback=self.swing_lookback
                )

            if trend is None:
                return None

            displacements = detect_displacement(
                mtf_buffer, displacement_ratio=self.displacement_ratio
            )
            inducements = detect_inducement(mtf_buffer, lookback=10)

            should_exit_position = False
            exit_reason = None

            if position.side == "LONG":
                if trend == "bearish":
                    should_exit_position = True
                    exit_reason = "htf_trend_reversal"

                bearish_displacements = [
                    d for d in displacements if d.direction == "bearish"
                ]
                if bearish_displacements and len(bearish_displacements) >= 2:
                    should_exit_position = True
                    exit_reason = "bearish_displacement"

                recent_inducement = any(
                    ind.direction == "bullish"
                    for ind in inducements[-3:]
                    if inducements
                )
                if recent_inducement:
                    should_exit_position = True
                    exit_reason = "bullish_inducement"

            else:  # SHORT position
                if trend == "bullish":
                    should_exit_position = True
                    exit_reason = "htf_trend_reversal"

                bullish_displacements = [
                    d for d in displacements if d.direction == "bullish"
                ]
                if bullish_displacements and len(bullish_displacements) >= 2:
                    should_exit_position = True
                    exit_reason = "bullish_displacement"

                recent_inducement = any(
                    ind.direction == "bearish"
                    for ind in inducements[-3:]
                    if inducements
                )
                if recent_inducement:
                    should_exit_position = True
                    exit_reason = "bearish_inducement"

            if should_exit_position:
                self.logger.info(
                    f"[{context.symbol}] ICT indicator-based exit triggered: "
                    f"position_side={position.side}, trend={trend}, reason={exit_reason}"
                )
                signal_type = (
                    SignalType.CLOSE_LONG
                    if position.side == "LONG"
                    else SignalType.CLOSE_SHORT
                )
                return Signal(
                    signal_type=signal_type,
                    symbol=context.symbol,
                    entry_price=candle.close,
                    strategy_name="ICTExitDeterminer",
                    timestamp=datetime.now(timezone.utc),
                    exit_reason=exit_reason,
                )

        except Exception as e:
            self.logger.error(
                f"[{context.symbol}] Error in indicator-based exit check: {e}"
            )
            return None

        return None
