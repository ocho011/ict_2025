"""
Composable strategy that assembles modular entry/exit/pricing determiners.

Design Pattern: Strategy + Composition
- EntryDeterminer decides WHEN/WHERE to enter
- StopLossDeterminer calculates SL price
- TakeProfitDeterminer calculates TP price
- ExitDeterminer decides WHEN to exit
- ComposableStrategy orchestrates all four

Flow:
    candle → EntryDeterminer.analyze() → EntryDecision
    → StopLossDeterminer.calculate_stop_loss() → SL price
    → TakeProfitDeterminer.calculate_take_profit() → TP price
    → RR ratio validation
    → Final Signal assembly
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.entry.base import EntryContext, EntryDecision
from src.exit.base import ExitContext
from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.pricing.base import (
    PriceContext,
    PriceDeterminerConfig,
    StrategyModuleConfig,
)
from src.strategies.base import BaseStrategy


class ComposableStrategy(BaseStrategy):
    """
    Strategy assembled from pluggable entry/exit/pricing modules.

    Inherits BaseStrategy for buffer management, indicator cache, and
    TradingEngine integration. Delegates decision logic to injected
    determiners via StrategyModuleConfig.

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        config: Strategy configuration dict
        module_config: StrategyModuleConfig with all 4 determiners
        intervals: Optional list of intervals to track
        min_rr_ratio: Minimum risk-reward ratio filter (default 1.5)
    """

    def __init__(
        self,
        symbol: str,
        config: dict,
        module_config: StrategyModuleConfig,
        intervals: Optional[List[str]] = None,
        min_rr_ratio: float = 1.5,
    ) -> None:
        # Set module_config BEFORE super().__init__ because
        # _create_price_config() is called during super().__init__
        self.module_config = module_config
        self.min_rr_ratio = min_rr_ratio
        super().__init__(symbol, config, intervals)
        self.logger = logging.getLogger(__name__)

    def _create_price_config(self, config: Dict[str, Any]) -> PriceDeterminerConfig:
        """Use module_config's SL/TP determiners instead of defaults."""
        return PriceDeterminerConfig(
            stop_loss_determiner=self.module_config.stop_loss_determiner,
            take_profit_determiner=self.module_config.take_profit_determiner,
        )

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Orchestrate entry determination + TP/SL calculation.

        Flow:
            1. Buffer/cache update
            2. EntryDeterminer.analyze() → EntryDecision
            3. Extract internal metadata (_fvg_zone, _ob_zone, _displacement_size)
            4. Build PriceContext with zone data
            5. Calculate SL → Calculate TP (needs SL for RR)
            6. Validate RR ratio
            7. Strip internal metadata, assemble Signal
        """
        if not candle.is_closed:
            return None

        self.update_buffer(candle)
        self._update_feature_cache(candle)

        if not self.is_ready():
            return None

        # Build entry context
        entry_context = EntryContext(
            symbol=self.symbol,
            candle=candle,
            buffers=self.buffers,
            indicator_cache=self._indicator_cache,
            timestamp=int(time.time() * 1000),
            config=self.config,
            intervals=self.intervals,
        )

        # Delegate to entry determiner
        decision = self.module_config.entry_determiner.analyze(entry_context)
        if decision is None:
            return None

        # Extract internal transport metadata (prefixed with _)
        fvg_zone = decision.metadata.get("_fvg_zone")
        ob_zone = decision.metadata.get("_ob_zone")
        displacement_size = decision.metadata.get("_displacement_size")

        # Determine side string
        side = "LONG" if decision.signal_type == SignalType.LONG_ENTRY else "SHORT"

        # Build price context with zone data for SL/TP determiners
        price_context = PriceContext.from_strategy(
            entry_price=decision.entry_price,
            side=side,
            symbol=self.symbol,
            fvg_zone=fvg_zone,
            ob_zone=ob_zone,
            displacement_size=displacement_size,
        )

        # Calculate SL first, then TP (TP may need SL distance for RR calc)
        stop_loss = self.module_config.stop_loss_determiner.calculate_stop_loss(
            price_context
        )
        take_profit = self.module_config.take_profit_determiner.calculate_take_profit(
            price_context, stop_loss
        )

        # Validate RR ratio
        risk = abs(decision.entry_price - stop_loss)
        if risk <= 0:
            self.logger.warning(
                "[%s] Zero risk distance: entry=%.4f, sl=%.4f",
                self.symbol,
                decision.entry_price,
                stop_loss,
            )
            return None

        reward = abs(take_profit - decision.entry_price)
        rr_ratio = reward / risk

        if rr_ratio < self.min_rr_ratio:
            self.logger.debug(
                "[%s] RR ratio %.2f < min %.2f: skipped",
                self.symbol,
                rr_ratio,
                self.min_rr_ratio,
            )
            return None

        # Strip internal metadata (keys starting with _) for public Signal
        public_metadata = {
            k: v for k, v in decision.metadata.items() if not k.startswith("_")
        }
        public_metadata["rr_ratio"] = round(rr_ratio, 2)

        return Signal(
            signal_type=decision.signal_type,
            symbol=self.symbol,
            entry_price=decision.entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_name=f"Composed({self.module_config.entry_determiner.name})",
            timestamp=datetime.now(timezone.utc),
            confidence=decision.confidence,
            metadata=public_metadata,
        )

    async def should_exit(
        self, position: Position, candle: Candle
    ) -> Optional[Signal]:
        """
        Delegate exit determination to exit determiner module.

        Creates ExitContext and forwards to ExitDeterminer.should_exit().
        """
        if not candle.is_closed:
            return None

        self.update_buffer(candle)
        self._update_feature_cache(candle)

        exit_context = ExitContext(
            symbol=self.symbol,
            candle=candle,
            position=position,
            buffers=self.buffers,
            indicator_cache=self._indicator_cache,
            timestamp=int(time.time() * 1000),
            config=self.config,
            intervals=self.intervals,
        )

        return self.module_config.exit_determiner.should_exit(exit_context)
