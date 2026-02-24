"""Abstract base class for market data providers.

Defines interface for market data access. Concrete implementations include
BinanceDataCollector (live trading) and HistoricalDataProvider (backtesting).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from src.models.candle import Candle


class MarketDataProvider(ABC):
    """Abstract interface for market data provision.

    Used by TradingEngine for candle data access (both streaming and historical).
    Implementations: BinanceDataCollector (live), HistoricalDataProvider (backtest).
    """

    @abstractmethod
    async def start_streaming(self) -> None:
        """Start market data streaming.

        For live: connects to WebSocket.
        For backtest: begins replaying historical data.
        """
        ...

    @abstractmethod
    async def stop(self, timeout: float = 5.0) -> None:
        """Stop streaming and cleanup resources.

        Args:
            timeout: Maximum seconds to wait for cleanup.
        """
        ...

    @abstractmethod
    def get_historical_candles(
        self, symbol: str, interval: str, limit: int = 500
    ) -> List["Candle"]:
        """Fetch historical candle data for strategy initialization.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            interval: Timeframe (e.g., '1m', '5m', '1h')
            limit: Number of candles to retrieve

        Returns:
            List of Candle objects sorted oldest-first
        """
        ...

    @property
    @abstractmethod
    def symbols(self) -> List[str]:
        """List of symbols this provider serves."""
        ...

    @property
    @abstractmethod
    def intervals(self) -> List[str]:
        """List of intervals this provider serves."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the provider is actively streaming data."""
        ...

    @property
    @abstractmethod
    def on_candle_callback(self) -> Optional[Callable[["Candle"], None]]:
        """Get the candle callback function."""
        ...
