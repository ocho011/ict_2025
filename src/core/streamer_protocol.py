"""
Data Streamer Protocol for Binance WebSocket connections.

This module defines the interface for all data streamers (market data, user data)
following the composition pattern for BinanceDataCollector (Issue #57).
"""

from abc import ABC, abstractmethod
from typing import Optional


class IDataStreamer(ABC):
    """
    Abstract base class for WebSocket data streamers.

    Defines the common interface for both public market data streams
    and private user data streams. Implementations must handle:
    - Connection lifecycle (start/stop)
    - Connection status monitoring
    - Graceful cleanup

    Implementations:
        - PublicMarketStreamer: Handles kline/candlestick WebSocket streams
        - PrivateUserStreamer: Handles user data stream (order updates)

    Example:
        >>> class MyStreamer(IDataStreamer):
        ...     async def start(self) -> None:
        ...         # Connect to WebSocket
        ...         pass
        ...
        ...     async def stop(self, timeout: float = 5.0) -> None:
        ...         # Disconnect and cleanup
        ...         pass
        ...
        ...     @property
        ...     def is_connected(self) -> bool:
        ...         return self._connected
    """

    @abstractmethod
    async def start(self) -> None:
        """
        Start the WebSocket streaming connection.

        Establishes WebSocket connection(s) and begins receiving data.
        Should be idempotent (safe to call multiple times).

        Raises:
            ConnectionError: If WebSocket connection fails
        """
        pass

    @abstractmethod
    async def stop(self, timeout: float = 5.0) -> None:
        """
        Stop streaming and cleanup resources.

        Gracefully closes WebSocket connection(s) and releases resources.
        Should be idempotent (safe to call multiple times).

        Args:
            timeout: Maximum time in seconds to wait for cleanup (default: 5.0)
        """
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if WebSocket connection is active.

        Returns:
            True if connection is established and healthy, False otherwise.
        """
        pass
