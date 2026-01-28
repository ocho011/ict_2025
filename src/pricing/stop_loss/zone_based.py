"""ICT zone-based stop loss calculation."""

from dataclasses import dataclass
from typing import Tuple
from src.pricing.base import StopLossDeterminer, PriceContext
from src.pricing.stop_loss.percentage import PercentageStopLoss


@dataclass(frozen=True)
class ZoneBasedStopLoss(StopLossDeterminer):
    """
    ICT zone-based stop loss using pre-calculated FVG/OB zones.

    Design Decision: Zone extraction happens BEFORE calling the determiner.
    This avoids circular imports: strategy calls get_entry_zone() -> passes tuple to context.
    """
    buffer_percent: float = 0.001  # 0.1%
    fallback_percent: float = 0.01  # 1% fallback
    max_sl_percent: float = 0.02  # 2% maximum SL distance cap

    def calculate_stop_loss(self, context: PriceContext) -> float:
        # Priority: FVG zone > OB zone > fallback percentage
        zone = context.fvg_zone or context.ob_zone

        if zone:
            return self._apply_buffer(context, zone)

        # Fallback to percentage-based SL
        return PercentageStopLoss(self.fallback_percent).calculate_stop_loss(context)

    def _apply_buffer(self, context: PriceContext, zone: Tuple[float, float]) -> float:
        zone_low, zone_high = zone
        buffer = context.entry_price * self.buffer_percent

        if context.side == "LONG":
            sl = zone_low - buffer
            if sl >= context.entry_price:
                return context.entry_price * (1 - self.fallback_percent)
            # Cap to maximum SL distance
            distance_pct = (context.entry_price - sl) / context.entry_price
            if distance_pct > self.max_sl_percent:
                return context.entry_price * (1 - self.max_sl_percent)
            return sl
        else:  # SHORT
            sl = zone_high + buffer
            if sl <= context.entry_price:
                return context.entry_price * (1 + self.fallback_percent)
            # Cap to maximum SL distance
            distance_pct = (sl - context.entry_price) / context.entry_price
            if distance_pct > self.max_sl_percent:
                return context.entry_price * (1 + self.max_sl_percent)
            return sl
