"""
Real-time market data collection using Binance WebSocket.

This module provides the BinanceDataCollector class for streaming live candle data
from Binance USDT-M Futures markets via WebSocket, with REST API support for
historical data retrieval.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, List, Optional

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from src.models.candle import Candle
from src.core.binance_service import BinanceServiceClient


class BinanceDataCollector:
    """
    Real-time market data collector for Binance USDT-M Futures.

    Provides dual data access:
    - WebSocket streaming for real-time candle updates
    - REST API for historical candle retrieval

    The collector supports both testnet and mainnet environments, with automatic
    symbol normalization.

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
        binance_service: BinanceServiceClient,
        symbols: List[str],
        intervals: List[str], # From .ini config (e.g., trading_config.ini)
        on_candle_callback: Optional[Callable[[Candle], None]] = None,
    ) -> None:
        """
        Initialize BinanceDataCollector.

        Args:
            binance_service: Centralized BinanceServiceClient instance
            symbols: List of trading pairs to monitor (e.g., ['BTCUSDT', 'ETHUSDT'])
            intervals: List of timeframes to collect (e.g., ['1m', '5m', '1h', '4h'])
            on_candle_callback: Optional callback function invoked on each candle update.
                               Signature: callback(candle: Candle) -> None
        """
        # Validate inputs
        if not symbols:
            raise ValueError("symbols list cannot be empty")
        if not intervals:
            raise ValueError("intervals list cannot be empty")

        # Store configuration and service
        self.binance_service = binance_service
        self.is_testnet = binance_service.is_testnet
        self.symbols = [s.upper() for s in symbols]  # Normalize to uppercase
        self.intervals = intervals
        self.on_candle_callback = on_candle_callback

        # WebSocket clients (one per symbol) - initialized in start_streaming
        # Dictionary mapping symbol -> UMFuturesWebsocketClient
        self.ws_clients: dict[str, UMFuturesWebsocketClient] = {}

        # State management
        self._running = False
        self._is_connected = False

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"BinanceDataCollector initialized: "
            f"{len(self.symbols)} symbols, {len(self.intervals)} intervals, "
            f"environment={'TESTNET' if self.is_testnet else 'MAINNET'}"
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"BinanceDataCollector("
            f"symbols={self.symbols}, "
            f"intervals={self.intervals}, "
            f"is_testnet={self.is_testnet}, "
            f"running={self._running}, "
            f"active_connections={len(self.ws_clients)})"
        )

    @property
    def is_connected(self) -> bool:
        """
        Check if WebSocket connections are active.

        Returns:
            True if all required symbol connections are active, False otherwise.
        """
        if not self._is_connected or not self.ws_clients:
            return False
            
        # Consider connected if we have clients for all symbols
        return len(self.ws_clients) == len(self.symbols)

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
                message = json.loads(message)

            # Step 1: Validate message type
            event_type = message.get("e")
            if event_type != "kline":
                # WebSocket initialization messages (subscription confirmations, etc.)
                # are expected and can be safely ignored without logging
                # Note: Debug logging removed for hot path performance
                return

            # Step 2: Extract kline data
            kline = message.get("k")
            if not kline:
                self.logger.error(f"Message missing 'k' (kline data): {message}")
                return

            # Step 3-4: Parse and convert all fields
            candle = Candle(
                symbol=kline["s"],
                interval=kline["i"],
                open_time=datetime.fromtimestamp(kline["t"] / 1000, tz=timezone.utc).replace(
                    tzinfo=None
                ),
                close_time=datetime.fromtimestamp(kline["T"] / 1000, tz=timezone.utc).replace(
                    tzinfo=None
                ),
                open=float(kline["o"]),
                high=float(kline["h"]),
                low=float(kline["l"]),
                close=float(kline["c"]),
                volume=float(kline["v"]),
                is_closed=kline["x"],
            )

            # Step 6: Invoke user callback if configured
            if self.on_candle_callback:
                self.on_candle_callback(candle)

            # Note: Debug logging removed from hot path for performance
            # Candle updates occur 4+ times per second and logging adds ~500μs overhead

        except KeyError as e:
            # Missing required field in kline data
            self.logger.error(
                f"Missing required field in kline message: {e} | Message: {message}", exc_info=True
            )
        except (ValueError, TypeError) as e:
            # Invalid data type (e.g., non-numeric string, wrong type)
            self.logger.error(
                f"Invalid data type in kline message: {e} | Message: {message}", exc_info=True
            )
        except Exception as e:
            # Unexpected error (including Candle validation errors)
            self.logger.error(
                f"Unexpected error parsing kline message: {e} | Message: {message}", exc_info=True
            )

    async def start_streaming(self) -> None:
        """
        Start WebSocket streaming for all configured symbol/interval pairs.

        Establishes separate WebSocket connections for each symbol to ensure reliability
        on Binance Testnet (avoids single-connection stream limits).

        Raises:
            ConnectionError: If WebSocket connection fails

        Structure:
            - Creates one WebSocket client per symbol
            - Subscribes to all configured intervals for that symbol
            - Manages multiple connections in self.ws_clients
        """
        # Idempotency check
        if self._running:
            self.logger.warning("Streaming already active, ignoring start request")
            return

        try:
            # Select WebSocket URL based on environment
            stream_url = self.TESTNET_WS_URL if self.is_testnet else self.MAINNET_WS_URL
            
            self.logger.info(
                f"Initializing {len(self.symbols)} WebSocket connections to {stream_url}"
            )

            total_stream_count = 0
            
            # Create a separate client for each symbol
            for symbol in self.symbols:
                self.logger.info(f"Establishing connection for {symbol}...")
                
                # Initialize WebSocket client with message handler
                client = UMFuturesWebsocketClient(
                    stream_url=stream_url, on_message=self._handle_kline_message
                )
                
                # Subscribe to all intervals for this symbol
                symbol_stream_count = 0
                for interval in self.intervals:
                    stream_name = f"{symbol.lower()}@kline_{interval}"
                    self.logger.debug(f"[{symbol}] Subscribing to: {stream_name}")
                    
                    # Subscribe
                    client.kline(symbol=symbol.lower(), interval=interval)
                    symbol_stream_count += 1
                
                # Store the client
                self.ws_clients[symbol] = client
                total_stream_count += symbol_stream_count
                
                # Small delay to prevent connection rate limiting if many symbols
                if len(self.symbols) > 1:
                    await asyncio.sleep(0.1)

            # Update state flags
            self._running = True
            self._is_connected = True

            self.logger.info(
                f"Successfully started streaming {total_stream_count} streams "
                f"across {len(self.ws_clients)} connections"
            )

        except Exception as e:
            self.logger.error(f"Failed to start WebSocket streaming: {e}", exc_info=True)
            # Cleanup any partially started connections
            await self.stop()
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
                open_time=datetime.fromtimestamp(
                    int(kline_array[0]) / 1000, tz=timezone.utc
                ).replace(tzinfo=None),
                close_time=datetime.fromtimestamp(
                    int(kline_array[6]) / 1000, tz=timezone.utc
                ).replace(tzinfo=None),
                open=float(kline_array[1]),
                high=float(kline_array[2]),
                low=float(kline_array[3]),
                close=float(kline_array[4]),
                volume=float(kline_array[5]),
                is_closed=True,  # Historical candles are always closed
            )
            return candle

        except (IndexError, ValueError, TypeError) as e:
            self.logger.error(
                f"Failed to parse REST kline data: {e} | Data: {kline_array}", exc_info=True
            )
            raise ValueError(f"Invalid kline data format: {e}")

    def get_historical_candles(self, symbol: str, interval: str, limit: int = 500) -> List[Candle]:
        """
        Fetch historical kline data via Binance REST API.

        Retrieves historical candlestick data for strategy initialization
        or analysis. All returned candles are marked as closed (is_closed=True).

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

        self.logger.info(f"Fetching {limit} historical candles for {symbol} {interval}")

        try:
            # Call Binance REST API
            klines_data = self.binance_service.klines(symbol=symbol, interval=interval, limit=limit)

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
                    f"(range: {candles[0].open_time.isoformat()} to "
                    f"{candles[-1].open_time.isoformat()})"
                )
            else:
                self.logger.warning(
                    f"No historical candles returned for {symbol} {interval} (limit={limit})"
                )

            return candles

        except Exception as e:
            self.logger.error(
                f"Failed to fetch historical candles for {symbol} {interval}: {e}", exc_info=True
            )
            raise ConnectionError(f"REST API request failed: {e}")



    async def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop data collection and cleanup resources.

        Execution Order:
            1. Check if already stopped (idempotency)
            2. Set state flags to prevent new operations
            3. Stop all WebSocket clients with timeout
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
        """
        # Step 1: Idempotency check
        if not self._running and not self.ws_clients:
            self.logger.debug("Collector already stopped, ignoring stop request")
            return

        self.logger.info("Initiating graceful shutdown...")

        # Step 2: Set flags to prevent new operations
        self._running = False
        self._is_connected = False

        try:
            # Step 3: Stop all WebSocket clients
            if self.ws_clients:
                self.logger.debug(f"Stopping {len(self.ws_clients)} WebSocket clients...")
                
                # Create stop tasks for all clients
                stop_tasks = []
                for symbol, client in self.ws_clients.items():
                    stop_tasks.append(asyncio.to_thread(client.stop))
                
                if stop_tasks:
                    try:
                        # Wait for all clients to stop
                        await asyncio.wait_for(asyncio.gather(*stop_tasks), timeout=timeout)
                        self.logger.info("All WebSocket clients stopped successfully")
                    except asyncio.TimeoutError:
                        self.logger.warning(
                            f"WebSocket stop exceeded {timeout}s timeout, forcing cleanup"
                        )
                    except Exception as e:
                        self.logger.error(f"Error stopping WebSocket clients: {e}", exc_info=True)
                
                # Clear references
                self.ws_clients.clear()

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
        self, exc_type: Optional[type], exc_val: Optional[BaseException], exc_tb: Optional[object]
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
            self.logger.warning(f"Exiting context with exception: {exc_type.__name__}: {exc_val}")
        else:
            self.logger.debug("Exiting async context manager normally")

        # Always attempt cleanup
        try:
            await self.stop()
        except Exception as e:
            self.logger.error(f"Error during context manager cleanup: {e}", exc_info=True)

        # Don't suppress exceptions from the context
        return None
        # Don't re-raise - best effort cleanup
