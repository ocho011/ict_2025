"""
Candlestick data model
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Candle:
    """
    OHLCV candlestick data from Binance futures market.

    Attributes:
        symbol: Trading pair (e.g., 'BTCUSDT')
        interval: Timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        open_time: Candle opening timestamp (UTC)
        open: Opening price
        high: Highest price in period
        low: Lowest price in period
        close: Closing/current price
        volume: Trading volume in base asset
        close_time: Candle closing timestamp (UTC)
        is_closed: Whether candle period has ended
    """

    symbol: str
    interval: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: datetime
    is_closed: bool = False

    def __post_init__(self) -> None:
        """Validate price coherence."""
        if self.high < max(self.open, self.close):
            raise ValueError(
                f"High ({self.high}) must be >= max(open={self.open}, close={self.close})"
            )
        if self.low > min(self.open, self.close):
            raise ValueError(
                f"Low ({self.low}) must be <= min(open={self.open}, close={self.close})"
            )
        if self.volume < 0:
            raise ValueError(f"Volume ({self.volume}) cannot be negative")

    @property
    def body_size(self) -> float:
        """Absolute size of candle body (close - open)."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """True if closing price > opening price."""
        return self.close > self.open

    @property
    def upper_wick(self) -> float:
        """Upper shadow/wick size."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Lower shadow/wick size."""
        return min(self.open, self.close) - self.low

    @property
    def total_range(self) -> float:
        """Total price range (high - low)."""
        return self.high - self.low
