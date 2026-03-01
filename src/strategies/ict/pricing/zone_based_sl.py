"""ICT zone-based stop loss calculation."""

from dataclasses import dataclass
from typing import Tuple
from src.pricing.base import StopLossDeterminer, PriceContext
from src.pricing.stop_loss.percentage import PercentageStopLoss
from pydantic import BaseModel, Field
from src.strategies.decorators import register_module


@register_module(
    'stop_loss', 'zone_based_sl',
    description='FVG/OB 존 기반 손절가 결정자',
)
@dataclass(frozen=True)
class ZoneBasedStopLoss(StopLossDeterminer):
    """
    ICT zone-based stop loss using pre-calculated FVG/OB zones.

    Design Decision: Zone extraction happens BEFORE calling the determiner.
    This avoids circular imports: strategy calls get_entry_zone() -> passes tuple to context.
    """

    class ParamSchema(BaseModel):
        """Pydantic schema for zone-based SL parameters."""
        buffer_percent: float = Field(0.001, ge=0.0001, le=0.01, description="존 경계 버퍼 비율")
        fallback_percent: float = Field(0.01, ge=0.001, le=0.05, description="폴백 SL 비율")
        min_sl_percent: float = Field(0.005, ge=0.001, le=0.02, description="최소 SL 거리 비율")
        max_sl_percent: float = Field(0.02, ge=0.005, le=0.05, description="최대 SL 거리 비율")

    @classmethod
    def from_validated_params(cls, params: "ZoneBasedStopLoss.ParamSchema") -> "ZoneBasedStopLoss":
        """Create instance from Pydantic-validated params."""
        return cls(**params.model_dump())

    buffer_percent: float = 0.001  # 0.1%
    fallback_percent: float = 0.01  # 1% fallback
    min_sl_percent: float = 0.005  # 0.5% minimum SL distance floor (Issue #100)
    max_sl_percent: float = 0.02  # 2% maximum SL distance cap

    def calculate_stop_loss(self, context: PriceContext) -> float:
        # Priority: FVG zone > OB zone > fallback percentage
        zone = context.extras.get("fvg_zone") or context.extras.get("ob_zone")

        if zone:
            return self._apply_buffer(context, zone)

        # Fallback to percentage-based SL
        return PercentageStopLoss(self.fallback_percent).calculate_stop_loss(context)

    def _apply_buffer(self, context: PriceContext, zone: Tuple[float, float]) -> float:
        zone_low, zone_high = zone
        buffer = context.entry_price * self.buffer_percent

        if context.side == "LONG":
            # 1. Calculate zone-based SL
            sl = zone_low - buffer
            # 2. Sanity check: SL on wrong side of entry
            if sl >= context.entry_price:
                return context.entry_price * (1 - self.fallback_percent)
            # 3. Calculate distance percentage
            distance_pct = (context.entry_price - sl) / context.entry_price
            # 4. Enforce minimum floor (Issue #100)
            if distance_pct < self.min_sl_percent:
                sl = context.entry_price * (1 - self.min_sl_percent)
                distance_pct = self.min_sl_percent
            # 5. Enforce maximum cap
            if distance_pct > self.max_sl_percent:
                sl = context.entry_price * (1 - self.max_sl_percent)
            return sl
        else:  # SHORT
            # 1. Calculate zone-based SL
            sl = zone_high + buffer
            # 2. Sanity check: SL on wrong side of entry
            if sl <= context.entry_price:
                return context.entry_price * (1 + self.fallback_percent)
            # 3. Calculate distance percentage
            distance_pct = (sl - context.entry_price) / context.entry_price
            # 4. Enforce minimum floor (Issue #100)
            if distance_pct < self.min_sl_percent:
                sl = context.entry_price * (1 + self.min_sl_percent)
                distance_pct = self.min_sl_percent
            # 5. Enforce maximum cap
            if distance_pct > self.max_sl_percent:
                sl = context.entry_price * (1 + self.max_sl_percent)
            return sl
