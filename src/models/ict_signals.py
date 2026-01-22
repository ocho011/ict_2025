"""
ICT (Inner Circle Trader) signal and structure data models (Events)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class SwingPoint:
    """
    Swing high or swing low point in market structure.

    Attributes:
        index: Position in candle sequence
        price: Swing point price level
        type: Whether this is a 'high' or 'low' swing point
        timestamp: When this swing point occurred
        strength: Number of bars on each side that validate this swing
    """

    index: int
    price: float
    type: Literal["high", "low"]
    timestamp: datetime
    strength: int = 5  # Default lookback on each side


@dataclass
class StructureBreak:
    """
    Break of Structure (BOS) or Change of Character (CHoCH) event.

    Attributes:
        index: Position where break occurred
        type: 'BOS' (trend continuation) or 'CHoCH' (trend reversal)
        direction: 'bullish' or 'bearish' market direction
        broken_level: Price level that was broken
        timestamp: When the break occurred
    """

    index: int
    type: Literal["BOS", "CHoCH"]
    direction: Literal["bullish", "bearish"]
    broken_level: float
    timestamp: datetime


@dataclass
class LiquiditySweep:
    """
    Liquidity sweep event (stop hunt before reversal).

    Attributes:
        index: Index where sweep occurred
        direction: 'bullish' (swept SSL) or 'bearish' (swept BSL)
        swept_level: Price level that was swept
        reversal_started: Whether price reversed after sweep
        timestamp: When the sweep occurred
    """

    index: int
    direction: Literal["bullish", "bearish"]
    swept_level: float
    reversal_started: bool
    timestamp: datetime


@dataclass
class Inducement:
    """
    Inducement - fake move to trap retail traders.

    Attributes:
        index: Index where inducement occurred
        type: 'false_breakout' or 'liquidity_grab'
        direction: Direction of the fake move
        price_level: Price level of the trap
        timestamp: When inducement occurred
    """

    index: int
    type: Literal["false_breakout", "liquidity_grab"]
    direction: Literal["bullish", "bearish"]
    price_level: float
    timestamp: datetime


@dataclass
class Displacement:
    """
    Strong impulsive move (1.5x-2x average range).

    Attributes:
        index: Starting index of displacement
        direction: 'bullish' (up) or 'bearish' (down)
        start_price: Price at displacement start
        end_price: Price at displacement end
        displacement_ratio: Size relative to average range
        timestamp: When displacement started
    """

    index: int
    direction: Literal["bullish", "bearish"]
    start_price: float
    end_price: float
    displacement_ratio: float  # displacement / avg_range
    timestamp: datetime

    @property
    def size(self) -> float:
        """Absolute size of the displacement."""
        return abs(self.end_price - self.start_price)


@dataclass
class MitigationZone:
    """
    Mitigation zone - area where price fills imbalance/OB.

    Attributes:
        index: Index of the mitigation zone
        type: 'FVG' or 'OB' (what is being mitigated)
        high: Upper boundary
        low: Lower boundary
        timestamp: When the zone formed
        mitigated: Whether the zone has been fully mitigated
    """

    index: int
    type: Literal["FVG", "OB"]
    high: float
    low: float
    timestamp: datetime
    mitigated: bool = False

    @property
    def zone_size(self) -> float:
        """Size of the mitigation zone."""
        return self.high - self.low
