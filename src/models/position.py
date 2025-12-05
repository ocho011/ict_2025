"""
Position model
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    """
    Active futures position.

    Attributes:
        symbol: Trading pair
        side: 'LONG' or 'SHORT'
        entry_price: Average entry price
        quantity: Position size (contracts)
        leverage: Leverage multiplier
        unrealized_pnl: Current profit/loss
        liquidation_price: Liquidation price (if available)
        entry_time: Position open time
    """

    symbol: str
    side: str  # 'LONG' or 'SHORT'
    entry_price: float
    quantity: float
    leverage: int
    unrealized_pnl: float = 0.0
    liquidation_price: Optional[float] = None
    entry_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate position parameters."""
        if self.side not in ("LONG", "SHORT"):
            raise ValueError(f"Side must be 'LONG' or 'SHORT', got {self.side}")
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be > 0, got {self.quantity}")
        if self.leverage < 1:
            raise ValueError(f"Leverage must be >= 1, got {self.leverage}")

    @property
    def notional_value(self) -> float:
        """Total position value (quantity * entry_price)."""
        return self.quantity * self.entry_price

    @property
    def margin_used(self) -> float:
        """Margin used for position (notional / leverage)."""
        return self.notional_value / self.leverage
