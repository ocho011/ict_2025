"""
Position model
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PositionSide(Enum):
    """Position sides"""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Position:
    """
    Trading position
    """
    symbol: str
    side: PositionSide
    entry_price: float
    quantity: float
    leverage: int
    stop_loss: float = None
    take_profit: float = None
    opened_at: datetime = None
    unrealized_pnl: float = 0.0

    def __post_init__(self):
        if self.opened_at is None:
            self.opened_at = datetime.now()

    def calculate_pnl(self, current_price: float) -> float:
        """
        Calculate current PnL

        Args:
            current_price: Current market price

        Returns:
            Unrealized PnL
        """
        if self.side == PositionSide.LONG:
            pnl = (current_price - self.entry_price) * self.quantity
        else:  # SHORT
            pnl = (self.entry_price - current_price) * self.quantity

        return pnl * self.leverage
