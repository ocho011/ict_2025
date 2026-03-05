"""
ICT Dynamic Exit Determiner module.

Transitioned to Full Composable Architecture.
Implements 4 exit strategies: trailing_stop, breakeven, timed, indicator_based.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from src.strategies.decorators import register_module

from src.strategies.modules.detectors.market_structure import get_current_trend
from src.strategies.modules.detectors.smc import detect_displacement, detect_inducement
from src.strategies.modules.base.exit import ExitContext, ExitDeterminer
from src.models.module_requirements import ModuleRequirements
from src.models.position import PositionMetrics
from src.models.signal import Signal, SignalType
from src.utils.config_manager import ExitConfig


@register_module(
    'exit', 'ict_dynamic_exit',
    description='ICT 기반 4단계 동적 청산 결정자',
)
class ICTDynamicExitDeterminer(ExitDeterminer):
    """
    ICT exit determination using 4 exit strategies.
    """

    class ParamSchema(BaseModel):
        """Pydantic schema for ICT exit parameters."""
        dynamic_exit_enabled: bool = Field(True, description="동적 청산 활성화")
        exit_strategy: str = Field("trailing_stop", description="청산 전략")
        trailing_distance: float = Field(0.02, ge=0.001, le=0.1, description="트레일링 거리 (0.02 = 2%)")
        trailing_activation: float = Field(0.01, ge=0.001, le=0.05, description="트레일링 활성화 수익률 (0.01 = 1%)")
        breakeven_enabled: bool = Field(True, description="본절가 청산 활성화")
        breakeven_offset: float = Field(0.001, ge=0.0, le=0.01, description="본절가 오프셋 %")
        timeout_enabled: bool = Field(False, description="시간 기반 청산 활성화")
        timeout_minutes: int = Field(240, ge=1, le=1440, description="타임아웃 (분)")
        swing_lookback: int = Field(5, ge=3, le=20, description="스윙 탐색 범위")
        displacement_ratio: float = Field(1.5, ge=1.0, le=5.0, description="디스플레이스먼트 비율")
        mtf_interval: str = Field("5m", description="Mid Timeframe 인터벌")
        htf_interval: str = Field("15m", description="High Timeframe 인터벌")

    @classmethod
    def from_validated_params(cls, params: "ICTDynamicExitDeterminer.ParamSchema") -> "ICTDynamicExitDeterminer":
        """Create instance from Pydantic-validated params."""
        exit_config = ExitConfig(
            dynamic_exit_enabled=params.dynamic_exit_enabled,
            exit_strategy=params.exit_strategy,
            trailing_distance=params.trailing_distance,
            trailing_activation=params.trailing_activation,
            breakeven_enabled=params.breakeven_enabled,
            breakeven_offset=params.breakeven_offset,
            timeout_enabled=params.timeout_enabled,
            timeout_minutes=params.timeout_minutes,
        )
        return cls(
            exit_config=exit_config,
            swing_lookback=params.swing_lookback,
            displacement_ratio=params.displacement_ratio,
            mtf_interval=params.mtf_interval,
            htf_interval=params.htf_interval,
        )

    def __init__(
        self,
        exit_config: Optional[ExitConfig] = None,
        swing_lookback: int = 5,
        displacement_ratio: float = 1.5,
        mtf_interval: str = "5m",
        htf_interval: str = "15m",
    ):
        self.exit_config = exit_config or ExitConfig()
        self.swing_lookback = swing_lookback
        self.displacement_ratio = displacement_ratio
        self.mtf_interval = mtf_interval
        self.htf_interval = htf_interval
        self.logger = logging.getLogger(__name__)

        # Trailing stop level persistence across candles
        self._trailing_levels: dict[str, float] = {}
        # Position metrics for MFE/MAE tracking
        self._position_metrics: dict[str, PositionMetrics] = {}

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
        Check trailing stop exit conditions with persistent state.
        """
        try:
            position = context.position
            candle = context.candle
            exit_config = self.exit_config
            trail_key = f"{context.symbol}_{position.side}"

            pnl_pct = ((candle.close - position.entry_price) / position.entry_price * 100
                        if position.side == "LONG"
                        else (position.entry_price - candle.close) / position.entry_price * 100)

            # MFE/MAE tracking
            metrics = self._position_metrics.get(trail_key)
            if metrics is None:
                metrics = PositionMetrics(
                    entry_price=position.entry_price,
                    side=position.side,
                    hwm_price=position.entry_price,
                    lwm_price=position.entry_price,
                )
                self._position_metrics[trail_key] = metrics
            
            metrics.candle_count += 1
            if pnl_pct > metrics.mfe_pct:
                metrics.mfe_pct = pnl_pct
                metrics.hwm_price = candle.close
            if pnl_pct < metrics.mae_pct:
                metrics.mae_pct = pnl_pct
                metrics.lwm_price = candle.close

            if position.side == "LONG":
                initial_stop = position.entry_price * (1 - exit_config.trailing_distance)
                trailing_stop = self._trailing_levels.get(trail_key, initial_stop)

                activation_price = position.entry_price * (1 + exit_config.trailing_activation)
                if candle.close > activation_price:
                    new_stop = candle.close * (1 - exit_config.trailing_distance)
                    if new_stop > trailing_stop:
                        old_stop = trailing_stop
                        trailing_stop = new_stop
                        metrics.ratchet_count += 1
                        metrics.last_trailing_stop = trailing_stop
                        self._log_ratchet_event(
                            symbol=context.symbol, side=position.side,
                            old_stop=old_stop, new_stop=trailing_stop,
                            trigger_price=candle.close, metrics=metrics,
                        )

                self._trailing_levels[trail_key] = trailing_stop

                if candle.close <= trailing_stop:
                    self.logger.info(
                        f"[{context.symbol}] Trailing stop exit triggered: "
                        f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                        f"stop={trailing_stop:.2f}"
                    )
                    self._trailing_levels.pop(trail_key, None)
                    metrics.last_trailing_stop = trailing_stop
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        symbol=context.symbol,
                        entry_price=candle.close,
                        strategy_name="ICTDynamicExitDeterminer",
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
                        metrics.ratchet_count += 1
                        metrics.last_trailing_stop = trailing_stop
                        self._log_ratchet_event(
                            symbol=context.symbol, side=position.side,
                            old_stop=old_stop, new_stop=trailing_stop,
                            trigger_price=candle.close, metrics=metrics,
                        )

                self._trailing_levels[trail_key] = trailing_stop

                if candle.close >= trailing_stop:
                    self.logger.info(
                        f"[{context.symbol}] Trailing stop exit triggered: "
                        f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                        f"stop={trailing_stop:.2f}"
                    )
                    self._trailing_levels.pop(trail_key, None)
                    metrics.last_trailing_stop = trailing_stop
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT,
                        symbol=context.symbol,
                        entry_price=candle.close,
                        strategy_name="ICTDynamicExitDeterminer",
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop",
                    )

        except Exception as e:
            self.logger.error(f"[{context.symbol}] Error in trailing stop check: {e}")
            return None

        return None

    def _log_ratchet_event(
        self,
        symbol: str,
        side: str,
        old_stop: float,
        new_stop: float,
        trigger_price: float,
        metrics: PositionMetrics,
    ) -> None:
        """Log trailing stop ratchet event to audit trail."""
        try:
            from src.core.audit_logger import AuditLogger, AuditEventType

            audit = AuditLogger.get_instance()
            ratchet_delta_pct = abs(new_stop - old_stop) / old_stop * 100

            audit.log_event(
                event_type=AuditEventType.TRAILING_STOP_RATCHETED,
                operation="trailing_stop_ratchet",
                symbol=symbol,
                data={
                    "side": side,
                    "old_stop": round(old_stop, 6),
                    "new_stop": round(new_stop, 6),
                    "trigger_price": round(trigger_price, 6),
                    "ratchet_delta_pct": round(ratchet_delta_pct, 4),
                    "current_mfe_pct": round(metrics.mfe_pct, 4),
                    "current_mae_pct": round(metrics.mae_pct, 4),
                    "ratchet_count": metrics.ratchet_count,
                    "candle_count_since_entry": metrics.candle_count,
                },
            )
        except Exception as e:
            self.logger.debug("Ratchet audit log failed: %s", e)

    def get_and_clear_metrics(self, symbol: str, side: str) -> Optional[PositionMetrics]:
        """Retrieve and remove position metrics for a closed position."""
        trail_key = f"{symbol}_{side}"
        return self._position_metrics.pop(trail_key, None)

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

            if position.side == "LONG":
                if candle.close > position.entry_price + profit_threshold:
                    if candle.close <= breakeven_level:
                        return Signal(
                            signal_type=SignalType.CLOSE_LONG,
                            symbol=context.symbol,
                            entry_price=candle.close,
                            strategy_name="ICTDynamicExitDeterminer",
                            timestamp=datetime.now(timezone.utc),
                            exit_reason="breakeven",
                        )
            else:  # SHORT position
                if candle.close < position.entry_price - profit_threshold:
                    if candle.close >= breakeven_level:
                        return Signal(
                            signal_type=SignalType.CLOSE_SHORT,
                            symbol=context.symbol,
                            entry_price=candle.close,
                            strategy_name="ICTDynamicExitDeterminer",
                            timestamp=datetime.now(timezone.utc),
                            exit_reason="breakeven",
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
                signal_type = (
                    SignalType.CLOSE_LONG
                    if position.side == "LONG"
                    else SignalType.CLOSE_SHORT
                )
                return Signal(
                    signal_type=signal_type,
                    symbol=context.symbol,
                    entry_price=candle.close,
                    strategy_name="ICTDynamicExitDeterminer",
                    timestamp=datetime.now(timezone.utc),
                    exit_reason="timed",
                )

        except Exception as e:
            self.logger.error(f"[{context.symbol}] Error in timed exit check: {e}")
            return None

        return None

    def _check_indicator_based_exit(self, context: ExitContext) -> Optional[Signal]:
        """Check indicator-based exit conditions using ICT analysis."""
        try:
            position = context.position
            candle = context.candle

            mtf_buffer = context.buffers.get(self.mtf_interval)
            if not mtf_buffer or len(mtf_buffer) < 50:
                return None

            # Get current trend from ICT analysis
            trend = None
            if context.feature_store is not None:
                htf_structure = context.feature_store.get_market_structure(
                    self.htf_interval
                )
                mtf_structure = context.feature_store.get_market_structure(
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
                signal_type = (
                    SignalType.CLOSE_LONG
                    if position.side == "LONG"
                    else SignalType.CLOSE_SHORT
                )
                return Signal(
                    signal_type=signal_type,
                    symbol=context.symbol,
                    entry_price=candle.close,
                    strategy_name="ICTDynamicExitDeterminer",
                    timestamp=datetime.now(timezone.utc),
                    exit_reason=exit_reason,
                )

        except Exception as e:
            self.logger.error(
                f"[{context.symbol}] Error in indicator-based exit check: {e}"
            )
            return None

        return None
