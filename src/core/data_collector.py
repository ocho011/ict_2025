"""
Real-time market data collection using Binance WebSocket.

This module provides the BinanceDataCollector class for streaming live candle data
from Binance USDT-M Futures markets via WebSocket, with REST API support for
historical data retrieval.
"""

from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from typing import Callable, Dict, List, Optional
import asyncio
import logging

from src.models.candle import Candle


class BinanceDataCollector:
    """
    Real-time market data collector for Binance USDT-M Futures.

    Provides dual data access:
    - WebSocket streaming for real-time candle updates
    - REST API for historical candle retrieval

    The collector supports both testnet and mainnet environments, with automatic
    symbol normalization and thread-safe buffer management using asyncio.Queue.

    Example:
        >>> collector = BinanceDataCollector(
        ...     api_key='your_key',
        ...     api_secret='your_secret',
        ...     symbols=['BTCUSDT'],
        ...     intervals=['1h'],
        ...     is_testnet=True,
        ...     on_candle_callback=handle_candle
        ... )
        >>> await collector.start_streaming()
        >>> # ... data collection active ...
        >>> collector.stop()

    Attributes:
        TESTNET_BASE_URL: Binance Futures testnet REST API endpoint
        MAINNET_BASE_URL: Binance Futures mainnet REST API endpoint
        TESTNET_WS_URL: Binance Futures testnet WebSocket endpoint
        MAINNET_WS_URL: Binance Futures mainnet WebSocket endpoint
        DEFAULT_BUFFER_SIZE: Default maximum candles per buffer (500)
    """

    # Environment URLs
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"
    MAINNET_BASE_URL = "https://fapi.binance.com"
    TESTNET_WS_URL = "wss://stream.binancefuture.com"
    MAINNET_WS_URL = "wss://fstream.binance.com"

    # Buffer Configuration
    DEFAULT_BUFFER_SIZE = 500  # ~8.3 hours for 1m interval

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbols: List[str],
        intervals: List[str],
        is_testnet: bool = True,
        on_candle_callback: Optional[Callable[[Candle], None]] = None,
        buffer_size: int = DEFAULT_BUFFER_SIZE
    ) -> None:
        """
        Initialize BinanceDataCollector.

        Args:
            api_key: Binance API key for authentication
            api_secret: Binance API secret for authentication
            symbols: List of trading pairs to monitor (e.g., ['BTCUSDT', 'ETHUSDT'])
            intervals: List of timeframes to collect (e.g., ['1m', '5m', '1h', '4h'])
            is_testnet: Use testnet (True) or mainnet (False). Default is True.
            on_candle_callback: Optional callback function invoked on each candle update.
                               Signature: callback(candle: Candle) -> None
            buffer_size: Maximum number of candles to buffer per symbol/interval pair.
                        Default is 500.

        Note:
            - Constructor does NOT start streaming. Call start_streaming() explicitly.
            - Testnet is strongly recommended for development and testing to avoid
              trading with real funds.
            - Symbols are automatically normalized to uppercase for API compatibility.
            - WebSocket client is initialized lazily in start_streaming().

        Raises:
            ValueError: If symbols or intervals lists are empty
        """
        # Validate inputs
        if not symbols:
            raise ValueError("symbols list cannot be empty")
        if not intervals:
            raise ValueError("intervals list cannot be empty")

        # Store configuration
        self.is_testnet = is_testnet
        self.symbols = [s.upper() for s in symbols]  # Normalize to uppercase
        self.intervals = intervals
        self.on_candle_callback = on_candle_callback
        self.buffer_size = buffer_size

        # Initialize candle buffers (lazy initialization per symbol/interval)
        # Key format: '{SYMBOL}_{INTERVAL}' -> asyncio.Queue
        self._candle_buffers: Dict[str, asyncio.Queue] = {}

        # Initialize REST client for historical data and account queries
        base_url = self.TESTNET_BASE_URL if is_testnet else self.MAINNET_BASE_URL
        self.rest_client = UMFutures(
            key=api_key,
            secret=api_secret,
            base_url=base_url
        )

        # WebSocket client (initialized in start_streaming)
        self.ws_client: Optional[UMFuturesWebsocketClient] = None

        # State management
        self._running = False
        self._is_connected = False

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"BinanceDataCollector initialized: "
            f"{len(self.symbols)} symbols, {len(self.intervals)} intervals, "
            f"environment={'TESTNET' if is_testnet else 'MAINNET'}"
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"BinanceDataCollector("
            f"symbols={self.symbols}, "
            f"intervals={self.intervals}, "
            f"is_testnet={self.is_testnet}, "
            f"running={self._running})"
        )


    def _handle_kline_message(self, message: Dict) -> None:
        """
        Handle incoming kline WebSocket messages.

        Args:
            message: Raw WebSocket message dictionary from Binance

        Note:
            Full implementation in Subtask 3.3 - Message Parsing.
            This stub allows Subtask 3.2 (WebSocket connection) to be
            implemented and tested independently.
        """
        pass  # Implementation in Subtask 3.3


    async def start_streaming(self) -> None:
        """
        Start WebSocket streaming for all configured symbol/interval pairs.

        Establishes WebSocket connection and subscribes to kline streams for each
        combination of symbols and intervals configured in the constructor.

        Raises:
            ConnectionError: If WebSocket connection fails

        Example:
            >>> collector = BinanceDataCollector(...)
            >>> await collector.start_streaming()
            >>> # Now receiving real-time kline updates

        Note:
            - Method is idempotent - multiple calls are ignored
            - Connection is automatic via binance-futures-connector library
            - Messages routed to _handle_kline_message() callback
        """
        # Idempotency check
        if self._running:
            self.logger.warning("Streaming already active, ignoring start request")
            return

        try:
            # Select WebSocket URL based on environment
            stream_url = self.TESTNET_WS_URL if self.is_testnet else self.MAINNET_WS_URL

            self.logger.info(
                f"Initializing WebSocket connection to {stream_url}"
            )

            # Initialize WebSocket client
            self.ws_client = UMFuturesWebsocketClient(stream_url=stream_url)

            # Subscribe to kline streams for all symbol/interval combinations
            stream_count = 0
            for symbol in self.symbols:
                for interval in self.intervals:
                    stream_name = f"{symbol.lower()}@kline_{interval}"
                    self.logger.debug(f"Subscribing to stream: {stream_name}")

                    self.ws_client.kline(
                        symbol=symbol.lower(),
                        interval=interval,
                        callback=self._handle_kline_message
                    )
                    stream_count += 1

            # Update state flags
            self._running = True
            self._is_connected = True

            self.logger.info(
                f"Successfully started streaming {stream_count} streams "
                f"({len(self.symbols)} symbols × {len(self.intervals)} intervals)"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to start WebSocket streaming: {e}",
                exc_info=True
            )
            raise ConnectionError(f"WebSocket initialization failed: {e}")
