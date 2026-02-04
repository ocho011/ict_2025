"""
Position model
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PositionEntryData:
    """
    Tracks position entry data for PnL and duration calculations.

    Used by PrivateUserStreamer to track entry details when a position
    is opened via MARKET/LIMIT fill, enabling accurate PnL calculation
    when the position is closed via TP/SL.

    Attributes:
        entry_price: Average fill price at entry
        entry_time: Timestamp when position was opened
        quantity: Position size at entry
        side: Position direction ("LONG" or "SHORT")
    """

    entry_price: float
    entry_time: datetime
    quantity: float
    side: str  # "LONG" or "SHORT"


@dataclass
class PositionUpdate:
    """
    Position update data from ACCOUNT_UPDATE WebSocket event.

    Represents real-time position changes received via User Data Stream,
    enabling position cache updates without REST API calls (Issue #41).

    Attributes:
        symbol: Trading pair (e.g., "BTCUSDT")
        position_amt: Position amount (positive for LONG, negative for SHORT)
        entry_price: Average entry price
        unrealized_pnl: Current unrealized profit/loss
        margin_type: Margin mode ("cross" or "isolated")
        position_side: Position side mode ("BOTH", "LONG", or "SHORT")

    Binance ACCOUNT_UPDATE position structure:
        {
            "s": "BTCUSDT",      // Symbol
            "pa": "0.001",       // Position amount
            "ep": "9000.0",      // Entry price
            "up": "0.0",         // Unrealized PnL
            "mt": "cross",       // Margin type
            "ps": "BOTH"         // Position side
        }
    """

    symbol: str
    position_amt: float  # Positive for LONG, negative for SHORT
    entry_price: float
    unrealized_pnl: float
    margin_type: str  # "cross" or "isolated"
    position_side: str  # "BOTH", "LONG", or "SHORT"


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
