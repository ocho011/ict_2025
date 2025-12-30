"""
Real-time market data collection using Binance WebSocket.

This module provides the BinanceDataCollector class for streaming live candle data
from Binance USDT-M Futures markets via WebSocket, with REST API support for
historical data retrieval.
"""

from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from datetime import datetime, timezone
from typing import Callable, List, Optional
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
        >>> # Explicit lifecycle management
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
        >>> await collector.stop()

        >>> # Or use async context manager (recommended)
        >>> async with BinanceDataCollector(...) as collector:
        ...     await collector.start_streaming()
        ...     # ... data collection active ...
        >>> # Automatic cleanup on exit

    Attributes:
        TESTNET_BASE_URL: Binance Futures testnet REST API endpoint
        MAINNET_BASE_URL: Binance Futures mainnet REST API endpoint
        TESTNET_WS_URL: Binance Futures testnet WebSocket endpoint
        MAINNET_WS_URL: Binance Futures mainnet WebSocket endpoint
    """

    # Environment URLs
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"
    MAINNET_BASE_URL = "https://fapi.binance.com"
    TESTNET_WS_URL = "wss://stream.binancefuture.com"
    MAINNET_WS_URL = "wss://fstream.binance.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbols: List[str],
        intervals: List[str],
        is_testnet: bool = True,
        on_candle_callback: Optional[Callable[[Candle], None]] = None
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

    @property
    def is_connected(self) -> bool:
        """
        Check if WebSocket connection is active.

        Returns:
            True if WebSocket is connected and streaming, False otherwise

        Note:
            - Returns False if WebSocket client not initialized
            - Returns internal _is_connected flag state
        """
        return self._is_connected and self.ws_client is not None


    def _handle_kline_message(self, _, message) -> None:
        """
        Handle incoming kline WebSocket messages.

        Parses Binance WebSocket kline messages into Candle objects.
        Invokes callback if configured and logs parsing errors gracefully.

        Args:
            _: Unused first parameter (WebSocket client passes it)
            message: Raw WebSocket message (str or dict) from Binance
                    Expected format: {'e': 'kline', 'k': {...}}

        Processing Steps:
            0. Parse JSON string if message is str (library sends JSON strings)
            1. Validate message type (must be 'kline')
            2. Extract kline data from message['k']
            3. Convert timestamps (ms → datetime)
            4. Convert prices/volume (str → float)
            5. Create Candle object (validates in __post_init__)
            6. Invoke user callback if configured
            7. Log debug info on success

        Error Handling:
            - JSONDecodeError: Invalid JSON string
            - KeyError: Missing required field in message
            - ValueError: Invalid data type conversion (e.g., non-numeric string)
            - TypeError: Unexpected data type in message
            - Candle validation errors from __post_init__

        All errors are logged with full stack trace but do not raise exceptions
        to prevent WebSocket disconnection on malformed messages.
        """
        try:
            # Step 0: Parse JSON string if needed
            if isinstance(message, str):
                import json
                message = json.loads(message)

            # Step 1: Validate message type
            event_type = message.get('e')
            if event_type != 'kline':
                # WebSocket initialization messages (subscription confirmations, etc.)
                # are expected and can be safely ignored without logging
                if event_type is not None:
                    # Only log if it's an actual event type we don't recognize
                    self.logger.debug(
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

            # Step 6: Invoke user callback if configured
            if self.on_candle_callback:
                self.on_candle_callback(candle)

            # Step 7: Log debug info
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

            # Initialize WebSocket client with message handler
            # IMPORTANT: on_message must be set during client initialization
            self.ws_client = UMFuturesWebsocketClient(
                stream_url=stream_url,
                on_message=self._handle_kline_message
            )

            # Subscribe to kline streams for all symbol/interval combinations
            stream_count = 0
            for symbol in self.symbols:
                for interval in self.intervals:
                    stream_name = f"{symbol.lower()}@kline_{interval}"
                    self.logger.debug(f"Subscribing to stream: {stream_name}")

                    # Subscribe without callback parameter (handled by on_message)
                    self.ws_client.kline(
                        symbol=symbol.lower(),
                        interval=interval
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


    def _parse_rest_kline(self, kline_array: List) -> Candle:
        """
        Parse REST API kline array into a Candle object.

        Binance REST API kline format (array indices):
        [0] open_time (ms), [1] open, [2] high, [3] low, [4] close,
        [5] volume, [6] close_time (ms), [7] quote_asset_volume,
        [8] number_of_trades, [9] taker_buy_base_asset_volume,
        [10] taker_buy_quote_asset_volume, [11] ignore

        Args:
            kline_array: Raw kline array from Binance REST API

        Returns:
            Candle object with parsed and validated data

        Raises:
            ValueError: If kline_array format is invalid
            IndexError: If required array indices are missing
        """
        try:
            # Extract required fields from array
            # Note: We need symbol and interval from context, not from array
            candle = Candle(
                symbol="",  # Will be set by caller
                interval="",  # Will be set by caller
                open_time=datetime.fromtimestamp(int(kline_array[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                close_time=datetime.fromtimestamp(int(kline_array[6]) / 1000, tz=timezone.utc).replace(tzinfo=None),
                open=float(kline_array[1]),
                high=float(kline_array[2]),
                low=float(kline_array[3]),
                close=float(kline_array[4]),
                volume=float(kline_array[5]),
                is_closed=True  # Historical candles are always closed
            )
            return candle

        except (IndexError, ValueError, TypeError) as e:
            self.logger.error(
                f"Failed to parse REST kline data: {e} | Data: {kline_array}",
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

    def backfill_all(self, limit: int = 100) -> bool:
        """
        Backfill historical candles for all symbol/interval pairs.

        Fetches historical data for each configured symbol/interval combination
        to populate buffers before starting real-time streaming. This enables
        strategies to analyze immediately without waiting for real-time data
        accumulation.

        Args:
            limit: Number of historical candles to fetch per pair (1-1000).
                  Default is 100. 0 means no backfilling.

        Returns:
            bool: True if all pairs backfilled successfully, False if any failed

        Behavior:
            - Iterates through all symbols and intervals
            - Calls get_historical_candles() for each pair
            - Buffers are automatically populated by get_historical_candles()
            - Partial failures are logged but don't stop execution
            - Returns summary of success/failure counts

        Example:
            >>> collector = BinanceDataCollector(...)
            >>> success = collector.backfill_all(limit=200)
            >>> if success:
            ...     print("All pairs backfilled successfully")
            >>> else:
            ...     print("Some pairs failed to backfill")

        Note:
            - Should be called BEFORE start_streaming()
            - Each pair fetches independently (no parallelization)
            - Failed pairs will rely on real-time data only
        """
        # Skip if limit is 0
        if limit == 0:
            self.logger.info("Backfill disabled (limit=0), skipping historical data fetch")
            return True

        # Validate limit
        if limit < 0 or limit > 1000:
            self.logger.error(f"Invalid backfill limit: {limit}. Must be 0-1000.")
            return False

        self.logger.info(f"Starting backfill: {len(self.symbols)} symbols × {len(self.intervals)} intervals = {len(self.symbols) * len(self.intervals)} pairs")

        success_count = 0
        failed_pairs = []
        total_pairs = len(self.symbols) * len(self.intervals)

        # Iterate all symbol/interval combinations
        for symbol in self.symbols:
            for interval in self.intervals:
                try:
                    # Fetch historical candles (automatically adds to buffer)
                    candles = self.get_historical_candles(symbol, interval, limit)
                    success_count += 1
                    self.logger.info(
                        f"✅ Backfilled {symbol} {interval}: {len(candles)} candles loaded"
                    )
                except Exception as e:
                    # Log failure but continue with other pairs
                    failed_pairs.append(f"{symbol}_{interval}")
                    self.logger.error(
                        f"❌ Failed to backfill {symbol} {interval}: {e}"
                    )

        # Summary logging
        if success_count == total_pairs:
            self.logger.info(
                f"✅ Backfill complete: {success_count}/{total_pairs} pairs successful"
            )
            return True
        else:
            self.logger.warning(
                f"⚠️ Partial backfill: {success_count}/{total_pairs} pairs successful "
                f"(failed: {', '.join(failed_pairs)})"
            )
            return False

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop data collection and cleanup resources.

        Execution Order:
            1. Check if already stopped (idempotency)
            2. Set state flags to prevent new operations
            3. Stop WebSocket client with timeout
            4. Close REST API client session
            5. Clear state flags

        Args:
            timeout: Maximum time in seconds to wait for cleanup (default: 5.0)

        Raises:
            asyncio.TimeoutError: If cleanup exceeds timeout (logged as warning)

        Note:
            - Method is idempotent - safe to call multiple times
            - Logs warnings if cleanup exceeds timeout
            - Does not raise exceptions on cleanup failures

        Example:
            >>> collector = BinanceDataCollector(...)
            >>> await collector.start_streaming()
            >>> # ... data collection active ...
            >>> await collector.stop()
        """
        # Step 1: Idempotency check
        if not self._running and not self._is_connected:
            self.logger.debug("Collector already stopped, ignoring stop request")
            return

        self.logger.info("Initiating graceful shutdown...")

        # Step 2: Set flags to prevent new operations
        self._running = False
        self._is_connected = False

        try:
            # Step 3: Stop WebSocket client with timeout
            if self.ws_client is not None:
                self.logger.debug("Stopping WebSocket client...")
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.ws_client.stop),
                        timeout=timeout
                    )
                    self.logger.info("WebSocket client stopped successfully")
                except asyncio.TimeoutError:
                    self.logger.warning(
                        f"WebSocket stop exceeded {timeout}s timeout, forcing cleanup"
                    )
                except Exception as e:
                    self.logger.error(f"Error stopping WebSocket client: {e}", exc_info=True)

            # Step 4: Close REST API client (if it has a close method)
            # Note: UMFutures uses requests.Session internally, which doesn't require explicit close
            # But we log for completeness
            self.logger.debug("REST API client cleanup complete")

            # Step 5: Final state
            self.logger.info("Graceful shutdown complete")

        except Exception as e:
            self.logger.error(f"Unexpected error during shutdown: {e}", exc_info=True)

    async def __aenter__(self) -> "BinanceDataCollector":
        """
        Async context manager entry.

        Returns:
            Self instance for use in async with statement

        Example:
            >>> async with BinanceDataCollector(...) as collector:
            ...     await collector.start_streaming()
            ...     # ... use collector ...
            >>> # Automatic cleanup on exit

        Note:
            - Does NOT automatically call start_streaming()
            - User must explicitly start streaming within context
            - Provides automatic cleanup on context exit
        """
        self.logger.debug("Entering async context manager")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object]
    ) -> None:
        """
        Async context manager exit with automatic cleanup.

        Args:
            exc_type: Exception type if exception occurred
            exc_val: Exception value if exception occurred
            exc_tb: Exception traceback if exception occurred

        Note:
            - Calls stop() automatically
            - Handles exceptions during cleanup
            - Does not suppress context exceptions (returns None)
            - Logs context exceptions for debugging
        """
        if exc_type is not None:
            self.logger.warning(
                f"Exiting context with exception: {exc_type.__name__}: {exc_val}"
            )
        else:
            self.logger.debug("Exiting async context manager normally")

        # Always attempt cleanup
        try:
            await self.stop()
        except Exception as e:
            self.logger.error(
                f"Error during context manager cleanup: {e}",
                exc_info=True
            )

        # Don't suppress exceptions from the context
        return None
            # Don't re-raise - best effort cleanup
