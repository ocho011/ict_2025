"""
Real-time market data collection using Binance WebSocket.

This module provides the BinanceDataCollector class for streaming live candle data
from Binance USDT-M Futures markets via WebSocket, with REST API support for
historical data retrieval.
"""

from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from datetime import datetime, timezone
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

        Parses Binance WebSocket kline messages into Candle objects.
        Invokes callback if configured and logs parsing errors gracefully.

        Args:
            message: Raw WebSocket message dictionary from Binance
                    Expected format: {'e': 'kline', 'k': {...}}

        Processing Steps:
            1. Validate message type (must be 'kline')
            2. Extract kline data from message['k']
            3. Convert timestamps (ms → datetime)
            4. Convert prices/volume (str → float)
            5. Create Candle object (validates in __post_init__)
            6. Invoke user callback if configured
            7. Log debug info on success

        Error Handling:
            - KeyError: Missing required field in message
            - ValueError: Invalid data type conversion (e.g., non-numeric string)
            - TypeError: Unexpected data type in message
            - Candle validation errors from __post_init__

        All errors are logged with full stack trace but do not raise exceptions
        to prevent WebSocket disconnection on malformed messages.
        """
        try:
            # Step 1: Validate message type
            event_type = message.get('e')
            if event_type != 'kline':
                self.logger.warning(
                    f"Received non-kline message: type='{event_type}'"
                )
                return

            # Step 2: Extract kline data
            kline = message.get('k')
            if not kline:
                self.logger.error(
                    f"Message missing 'k' (kline data): {message}"
                )
                return

            # Step 3-4: Parse and convert all fields
            candle = Candle(
                symbol=kline['s'],
                interval=kline['i'],
                open_time=datetime.fromtimestamp(kline['t'] / 1000, tz=timezone.utc).replace(tzinfo=None),
                close_time=datetime.fromtimestamp(kline['T'] / 1000, tz=timezone.utc).replace(tzinfo=None),
                open=float(kline['o']),
                high=float(kline['h']),
                low=float(kline['l']),
                close=float(kline['c']),
                volume=float(kline['v']),
                is_closed=kline['x']
            )

            # Step 5: Invoke user callback if configured
            if self.on_candle_callback:
                self.on_candle_callback(candle)

            # Step 6: Log debug info
            self.logger.debug(
                f"Parsed candle: {candle.symbol} {candle.interval} "
                f"@ {candle.close_time.isoformat()} "
                f"(close={candle.close}, closed={candle.is_closed})"
            )

        except KeyError as e:
            # Missing required field in kline data
            self.logger.error(
                f"Missing required field in kline message: {e} | Message: {message}",
                exc_info=True
            )
        except (ValueError, TypeError) as e:
            # Invalid data type (e.g., non-numeric string, wrong type)
            self.logger.error(
                f"Invalid data type in kline message: {e} | Message: {message}",
                exc_info=True
            )
        except Exception as e:
            # Unexpected error (including Candle validation errors)
            self.logger.error(
                f"Unexpected error parsing kline message: {e} | Message: {message}",
                exc_info=True
            )


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


    def _parse_rest_kline(self, kline_data: List) -> Candle:
        """
        Parse REST API kline array into a Candle object.

        Binance REST API kline format (array indices):
        [0] open_time (ms), [1] open, [2] high, [3] low, [4] close,
        [5] volume, [6] close_time (ms), [7] quote_asset_volume,
        [8] number_of_trades, [9] taker_buy_base_asset_volume,
        [10] taker_buy_quote_asset_volume, [11] ignore

        Args:
            kline_data: Raw kline array from Binance REST API

        Returns:
            Candle object with parsed and validated data

        Raises:
            ValueError: If kline_data format is invalid
            IndexError: If required array indices are missing
        """
        try:
            # Extract required fields from array
            # Note: We need symbol and interval from context, not from array
            candle = Candle(
                symbol="",  # Will be set by caller
                interval="",  # Will be set by caller
                open_time=datetime.fromtimestamp(int(kline_data[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                close_time=datetime.fromtimestamp(int(kline_data[6]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                open=float(kline_data[1]),
                high=float(kline_data[2]),
                low=float(kline_data[3]),
                close=float(kline_data[4]),
                volume=float(kline_data[5]),
                is_closed=True  # Historical candles are always closed
            )
            return candle

        except (IndexError, ValueError, TypeError) as e:
            self.logger.error(
                f"Failed to parse REST kline data: {e} | Data: {kline_data}",
                exc_info=True
            )
            raise ValueError(f"Invalid kline data format: {e}")


    def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        limit: int = 500
    ) -> List[Candle]:
        """
        Fetch historical kline data via Binance REST API.

        Retrieves historical candlestick data for initial buffer population
        or backfilling. All returned candles are marked as closed (is_closed=True).

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT'). Will be normalized to uppercase.
            interval: Timeframe (e.g., '1m', '5m', '1h', '4h')
            limit: Number of candles to retrieve. Default 500, max 1000.

        Returns:
            List of Candle objects sorted by open_time (oldest first)

        Raises:
            ValueError: If symbol/interval invalid or limit out of range
            ConnectionError: If API request fails (rate limit, network error)

        Example:
            >>> candles = collector.get_historical_candles('BTCUSDT', '1h', limit=100)
            >>> print(f"Retrieved {len(candles)} candles")
            >>> print(f"Oldest: {candles[0].open_time}, Newest: {candles[-1].open_time}")
        """
        # Normalize symbol to uppercase
        symbol = symbol.upper()

        # Validate limit
        if not 1 <= limit <= 1000:
            raise ValueError(f"limit must be between 1 and 1000, got {limit}")

        self.logger.info(
            f"Fetching {limit} historical candles for {symbol} {interval}"
        )

        try:
            # Call Binance REST API
            klines_data = self.rest_client.klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )

            # Parse each kline array into Candle object
            candles = []
            for kline_array in klines_data:
                candle = self._parse_rest_kline(kline_array)
                # Set symbol and interval from request context
                candle.symbol = symbol
                candle.interval = interval
                candles.append(candle)

            # Log success with time range if candles exist
            if candles:
                self.logger.info(
                    f"Successfully retrieved {len(candles)} candles for {symbol} {interval} "
                    f"(range: {candles[0].open_time.isoformat()} to {candles[-1].open_time.isoformat()})"
                )
            else:
                self.logger.warning(
                    f"No historical candles returned for {symbol} {interval} (limit={limit})"
                )

            return candles

        except Exception as e:
            self.logger.error(
                f"Failed to fetch historical candles for {symbol} {interval}: {e}",
                exc_info=True
            )
            raise ConnectionError(f"REST API request failed: {e}")
