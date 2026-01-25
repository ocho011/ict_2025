"""
Real-time market data collection using Binance WebSocket.

This module provides the BinanceDataCollector class for streaming live candle data
from Binance USDT-M Futures markets via WebSocket, with REST API support for
historical data retrieval.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from src.models.candle import Candle
from src.core.binance_service import BinanceServiceClient
from src.core.user_data_stream import UserDataStreamManager


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

    # User Data Stream WebSocket URLs (same base, different path)
    TESTNET_USER_WS_URL = "wss://stream.binancefuture.com/ws"
    MAINNET_USER_WS_URL = "wss://fstream.binance.com/ws"

    def __init__(
        self,
        binance_service: BinanceServiceClient,
        symbols: List[str],
        intervals: List[str],  # From .ini config (e.g., trading_config.ini)
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

        # Connection monitoring
        self._last_heartbeat_time = 0.0
        self._heartbeat_interval = 30.0  # seconds
        self._heartbeat_task: Optional[asyncio.Task] = None

        # User Data Stream components (Issue #54)
        self.user_stream_manager: Optional[UserDataStreamManager] = None
        self._user_ws_client: Optional[UMFuturesWebsocketClient] = None
        self._event_bus = None  # Set when starting user data stream
        self._event_loop = None  # Captured for thread-safe event publishing

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
                open_time=datetime.fromtimestamp(
                    kline["t"] / 1000, tz=timezone.utc
                ).replace(tzinfo=None),
                close_time=datetime.fromtimestamp(
                    kline["T"] / 1000, tz=timezone.utc
                ).replace(tzinfo=None),
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
                f"Missing required field in kline message: {e} | Message: {message}",
                exc_info=True,
            )
        except (ValueError, TypeError) as e:
            # Invalid data type (e.g., non-numeric string, wrong type)
            self.logger.error(
                f"Invalid data type in kline message: {e} | Message: {message}",
                exc_info=True,
            )
        except Exception as e:
            # Unexpected error (including Candle validation errors)
            self.logger.error(
                f"Unexpected error parsing kline message: {e} | Message: {message}",
                exc_info=True,
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
                # The _handle_kline_message method is not called manually;
                # the WebSocket engine (internal library loop) automatically invokes this registered
                # handler whenever a new message is received from the server.
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

            # Start heartbeat monitoring
            self._last_heartbeat_time = time.time()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())

            self.logger.info(
                f"Successfully started streaming {total_stream_count} streams "
                f"across {len(self.ws_clients)} connections"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to start WebSocket streaming: {e}", exc_info=True
            )
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
                f"Failed to parse REST kline data: {e} | Data: {kline_array}",
                exc_info=True,
            )
            raise ValueError(f"Invalid kline data format: {e}")

    def get_historical_candles(
        self, symbol: str, interval: str, limit: int = 500
    ) -> List[Candle]:
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
            klines_data = self.binance_service.klines(
                symbol=symbol, interval=interval, limit=limit
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
                f"Failed to fetch historical candles for {symbol} {interval}: {e}",
                exc_info=True,
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

        # Step 2: Stop heartbeat monitor
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Step 3: Set flags to prevent new operations
        self._running = False
        self._is_connected = False

        try:
            # Step 3: Stop all WebSocket clients
            if self.ws_clients:
                self.logger.debug(
                    f"Stopping {len(self.ws_clients)} WebSocket clients..."
                )

                # Create stop tasks for all clients
                stop_tasks = []
                for symbol, client in self.ws_clients.items():
                    stop_tasks.append(asyncio.to_thread(client.stop))

                if stop_tasks:
                    try:
                        # Wait for all clients to stop
                        await asyncio.wait_for(
                            asyncio.gather(*stop_tasks), timeout=timeout
                        )
                        self.logger.info("All WebSocket clients stopped successfully")
                    except asyncio.TimeoutError:
                        self.logger.warning(
                            f"WebSocket stop exceeded {timeout}s timeout, forcing cleanup"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Error stopping WebSocket clients: {e}", exc_info=True
                        )

                # Clear references
                self.ws_clients.clear()

            # Step 4: Stop User Data Stream (Issue #54)
            await self.stop_user_data_stream()

            # Step 5: Close REST API client (if it has a close method)
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
        exc_tb: Optional[object],
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
                f"Error during context manager cleanup: {e}", exc_info=True
            )

        # Don't suppress exceptions from the context
        return None
        # Don't re-raise - best effort cleanup

    async def _heartbeat_monitor(self) -> None:
        """
        Monitor WebSocket connection status with periodic heartbeat logging.

        Logs connection status every 30 seconds to detect silent failures.
        """
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)

                if not self._running:
                    break

                current_time = time.time()

                # Check if any WebSocket clients exist
                active_connections = len(self.ws_clients)

                # Log heartbeat with connection status
                self.logger.info(
                    f"WebSocket heartbeat: {active_connections} active connections, "
                    f"status={'CONNECTED' if self._is_connected else 'DISCONNECTED'}, "
                    f"uptime={current_time - self._last_heartbeat_time:.1f}s"
                )

                self._last_heartbeat_time = current_time

            except asyncio.CancelledError:
                self.logger.info("Heartbeat monitor cancelled")
                break
            except Exception as e:
                self.logger.error(f"Heartbeat monitor error: {e}", exc_info=True)
                await asyncio.sleep(5.0)  # Brief pause before retry

    # =========================================================================
    # User Data Stream Methods (Issue #54: Orphaned TP/SL Order Prevention)
    # =========================================================================

    async def start_user_data_stream(self, event_bus) -> None:
        """
        Start User Data Stream WebSocket for real-time order updates.

        Creates a listen key via REST API and establishes WebSocket connection
        to receive ORDER_TRADE_UPDATE events for TP/SL order fill detection.

        Args:
            event_bus: EventBus instance for publishing ORDER_FILLED events

        Raises:
            ConnectionError: If WebSocket connection fails
            Exception: If listen key creation fails

        Note:
            The event_bus is stored for thread-safe event publishing from
            the WebSocket callback (which runs in a different thread).
        """
        self._event_bus = event_bus
        self._event_loop = asyncio.get_running_loop()

        # Initialize UserDataStreamManager for listen key lifecycle
        self.user_stream_manager = UserDataStreamManager(self.binance_service)

        try:
            # Create listen key (also starts keep-alive loop)
            listen_key = await self.user_stream_manager.start()

            # Determine WebSocket URL based on environment
            base_url = (
                self.TESTNET_USER_WS_URL if self.is_testnet else self.MAINNET_USER_WS_URL
            )
            ws_url = f"{base_url}/{listen_key}"

            # Create WebSocket client for user data stream
            self._user_ws_client = UMFuturesWebsocketClient(
                stream_url=ws_url,
                on_message=self._handle_user_data_message,
            )

            self.logger.info(
                f"User Data Stream connected: {ws_url[:60]}... "
                f"(testnet={self.is_testnet})"
            )

        except Exception as e:
            self.logger.error(f"Failed to start User Data Stream: {e}", exc_info=True)
            # Cleanup on failure
            if self.user_stream_manager:
                await self.user_stream_manager.stop()
                self.user_stream_manager = None
            raise

    def _handle_user_data_message(self, _, message) -> None:
        """
        Handle incoming User Data Stream WebSocket messages.

        Routes messages by event type:
        - ORDER_TRADE_UPDATE: Order status changes (fills, cancellations)
        - ACCOUNT_UPDATE: Position and balance changes
        - Other events: Ignored (MARGIN_CALL, etc.)

        Args:
            _: Unused WebSocket client parameter
            message: Raw message (str or dict) from Binance

        Note:
            This callback runs in a separate thread managed by the
            WebSocket library. Event publishing must be thread-safe.
        """
        try:
            # Parse JSON string if needed
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = message

            event_type = data.get("e")

            if event_type == "ORDER_TRADE_UPDATE":
                self._handle_order_trade_update(data)
            elif event_type == "ACCOUNT_UPDATE":
                # Log account updates for monitoring (position changes, etc.)
                update_reason = data.get("a", {}).get("m", "unknown")
                self.logger.debug(f"Account update received: reason={update_reason}")
            # Ignore other event types (MARGIN_CALL, listenKeyExpired, etc.)

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in user data message: {e}")
        except Exception as e:
            self.logger.error(
                f"Error handling user data message: {e}", exc_info=True
            )

    def _handle_order_trade_update(self, data: dict) -> None:
        """
        Process ORDER_TRADE_UPDATE event and publish ORDER_FILLED to EventBus.

        Extracts order information from the event and publishes an ORDER_FILLED
        event to trigger orphaned order cancellation in TradingEngine.

        Args:
            data: ORDER_TRADE_UPDATE event data from Binance

        Event Structure (from Binance):
            {
                "e": "ORDER_TRADE_UPDATE",
                "T": 1234567890123,  # Transaction time
                "o": {
                    "s": "BTCUSDT",       # Symbol
                    "c": "client_id",     # Client order ID
                    "S": "BUY",           # Side
                    "o": "LIMIT",         # Order type (original)
                    "ot": "TAKE_PROFIT_MARKET",  # Order type (for TP/SL)
                    "q": "0.001",         # Original quantity
                    "p": "50000",         # Original price
                    "ap": "50100",        # Average fill price
                    "X": "FILLED",        # Order status
                    "i": 123456789,       # Order ID
                    ...
                }
            }

        Only publishes events for FILLED TP/SL orders to minimize noise.
        """
        order_data = data.get("o", {})

        order_status = order_data.get("X")  # FILLED, CANCELED, NEW, etc.
        order_type = order_data.get("ot")  # TAKE_PROFIT_MARKET, STOP_MARKET, etc.
        symbol = order_data.get("s")
        order_id = str(order_data.get("i", ""))

        self.logger.info(
            f"Order update: {symbol} {order_type} -> {order_status} (ID: {order_id})"
        )

        # Only publish for FILLED TP/SL orders (triggers orphan prevention)
        if order_status == "FILLED" and order_type in (
            "TAKE_PROFIT_MARKET",
            "STOP_MARKET",
        ):
            from src.models.event import Event, EventType
            from src.models.event import QueueType
            from src.models.order import Order, OrderType, OrderStatus, OrderSide

            # Create Order object for event payload
            # Note: TP/SL orders require stop_price (trigger price)
            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=OrderSide(order_data.get("S")),
                order_type=OrderType(order_type),
                quantity=float(order_data.get("q", 0)),
                price=float(order_data.get("ap", 0)),  # Average fill price
                stop_price=float(order_data.get("sp", 0)),  # Stop/trigger price
                status=OrderStatus.FILLED,
            )

            event = Event(
                event_type=EventType.ORDER_FILLED,
                data=order,
                source="user_data_stream",
            )

            # Publish to EventBus (thread-safe via run_coroutine_threadsafe)
            if self._event_bus and self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._event_bus.publish(event, queue_type=QueueType.ORDER),
                    self._event_loop,
                )
                self.logger.info(
                    f"Published ORDER_FILLED event for {symbol} {order_type}"
                )

    async def stop_user_data_stream(self) -> None:
        """
        Stop User Data Stream and cleanup resources.

        Gracefully shuts down:
        1. WebSocket client connection
        2. UserDataStreamManager (listen key cleanup)

        Note:
            - Method is idempotent - safe to call multiple times
            - Called automatically by stop() method
        """
        # Stop WebSocket client
        if self._user_ws_client:
            try:
                self._user_ws_client.stop()
                self.logger.info("User Data Stream WebSocket stopped")
            except Exception as e:
                self.logger.warning(f"Error stopping user WebSocket: {e}")
            self._user_ws_client = None

        # Stop UserDataStreamManager (closes listen key)
        if self.user_stream_manager:
            await self.user_stream_manager.stop()
            self.user_stream_manager = None

        # Clear references
        self._event_bus = None
        self._event_loop = None
