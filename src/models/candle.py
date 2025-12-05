"""
Candlestick data model
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Candle:
    """
    OHLCV candlestick data
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    interval: str

    @property
    def is_bullish(self) -> bool:
        """Check if candle is bullish"""
        return self.close > self.open

    @property
    def body_size(self) -> float:
        """Calculate candle body size"""
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        """Calculate total candle range"""
        return self.high - self.low
