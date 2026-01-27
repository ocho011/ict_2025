"""Percentage-based stop loss calculation."""

from dataclasses import dataclass
from src.pricing.base import StopLossDeterminer, PriceContext


@dataclass(frozen=True)
class PercentageStopLoss(StopLossDeterminer):
    """Fixed percentage stop loss from entry price."""
    stop_loss_percent: float = 0.01  # 1% default

    def calculate_stop_loss(self, context: PriceContext) -> float:
        if context.side == "LONG":
            return context.entry_price * (1.0 - self.stop_loss_percent)
        else:  # SHORT
            return context.entry_price * (1.0 + self.stop_loss_percent)
