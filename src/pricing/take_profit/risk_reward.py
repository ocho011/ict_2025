"""Risk-reward ratio based take profit calculation."""

from dataclasses import dataclass
from src.pricing.base import TakeProfitDeterminer, PriceContext


@dataclass(frozen=True)
class RiskRewardTakeProfit(TakeProfitDeterminer):
    """Take profit based on risk-reward ratio from stop loss distance."""
    risk_reward_ratio: float = 2.0

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        sl_distance = abs(context.entry_price - stop_loss)
        tp_distance = sl_distance * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + tp_distance
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - tp_distance
            return tp if tp < context.entry_price else context.entry_price * 0.98
