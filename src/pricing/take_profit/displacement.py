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
        # Use displacement size if available, else fallback to entry percentage
        if context.displacement_size and context.displacement_size > 0:
            risk_amount = context.displacement_size
        else:
            risk_amount = context.entry_price * self.fallback_risk_percent

        reward_amount = risk_amount * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + reward_amount
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - reward_amount
            return tp if tp < context.entry_price else context.entry_price * 0.98
