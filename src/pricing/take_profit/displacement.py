"""ICT displacement-based take profit calculation."""

from dataclasses import dataclass
from src.pricing.base import TakeProfitDeterminer, PriceContext


@dataclass(frozen=True)
class DisplacementTakeProfit(TakeProfitDeterminer):
    """
    ICT displacement-based take profit.

    Uses displacement size as the risk measure instead of SL distance.
    Falls back to SL-based calculation if no displacement provided.
    """
    risk_reward_ratio: float = 2.0
    fallback_risk_percent: float = 0.02  # 2% fallback

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        # Calculate actual SL distance as the true risk measure (Issue #102)
        sl_distance = abs(context.entry_price - stop_loss)

        # Use displacement size if available
        if context.displacement_size and context.displacement_size > 0:
            displacement_risk = context.displacement_size
        else:
            displacement_risk = context.entry_price * self.fallback_risk_percent

        # Use the more conservative (larger) risk for consistent R:R (Issue #102)
        # This ensures TP is never closer than what the actual SL distance warrants
        risk_amount = max(sl_distance, displacement_risk) if sl_distance > 0 else displacement_risk

        reward_amount = risk_amount * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + reward_amount
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - reward_amount
            return tp if tp < context.entry_price else context.entry_price * 0.98
