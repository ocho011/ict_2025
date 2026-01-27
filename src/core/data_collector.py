"""
Real-time market data collection using Binance WebSocket.

This module provides the BinanceDataCollector class as a facade for managing
data collection from Binance USDT-M Futures markets. It coordinates:
- PublicMarketStreamer: Real-time candlestick data via WebSocket
- PrivateUserStreamer: Real-time order updates via User Data Stream
- REST API: Historical candle retrieval

Issue #57: Refactored to use composition pattern with dependency injection.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, List, Optional

from src.models.candle import Candle
from src.core.public_market_streamer import PublicMarketStreamer
from src.core.private_user_streamer import PrivateUserStreamer

if TYPE_CHECKING:
    from src.core.binance_service import BinanceServiceClient
    from src.core.event_handler import EventBus


class BinanceDataCollector:
    """
    Facade for Binance data collection (Issue #57 Refactoring).

    This class acts as a coordinator/facade that manages the lifecycle of:
    - PublicMarketStreamer: Kline/candlestick WebSocket streaming
    - PrivateUserStreamer: User Data Stream for order updates
    - REST API: Historical candle retrieval via BinanceServiceClient

    The design follows composition pattern with dependency injection:
    - All streamers are created externally and injected
    - BinanceDataCollector only manages lifecycle (start/stop)
    - Each streamer is responsible for its own connection and parsing

    Example (New Composition Pattern):
        >>> # Create individual components
        >>> market_streamer = PublicMarketStreamer(
        ...     symbols=['BTCUSDT'],
        ...     intervals=['1m', '5m'],
        ...     is_testnet=True,
        ...     on_candle_callback=handle_candle
        ... )
        >>> user_streamer = PrivateUserStreamer(
        ...     binance_service=binance_service,
        ...     is_testnet=True
        ... )
        >>>
        >>> # Inject into facade
        >>> collector = BinanceDataCollector(
        ...     binance_service=binance_service,
        ...     market_streamer=market_streamer,
        ...     user_streamer=user_streamer
        ... )
        >>> await collector.start_streaming()
        >>> await collector.start_user_data_stream(event_bus)
        >>> # ... data collection active ...
        >>> await collector.stop()

    Attributes:
        binance_service: REST API client for historical data
        market_streamer: Public market data WebSocket streamer
        user_streamer: Private user data WebSocket streamer
    """

    def __init__(
        self,
        binance_service: "BinanceServiceClient",
        market_streamer: PublicMarketStreamer,
        user_streamer: Optional[PrivateUserStreamer] = None,
    ) -> None:
        """
        Initialize BinanceDataCollector facade.

        Args:
            binance_service: Centralized BinanceServiceClient instance for REST API
            market_streamer: PublicMarketStreamer instance for kline WebSocket
            user_streamer: Optional PrivateUserStreamer instance for order updates

        Note:
            All components are created externally and injected. This allows:
            - Independent testing of each component
            - Easy mocking for unit tests
            - Clear separation of concerns
        """
        # Store injected components
        self.binance_service = binance_service
        self.market_streamer = market_streamer
        self.user_streamer = user_streamer

        # Expose configuration from market streamer for backward compatibility
        self.is_testnet = binance_service.is_testnet
        self.symbols = market_streamer.symbols
        self.intervals = market_streamer.intervals

        # State management
        self._running = False

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"BinanceDataCollector facade initialized: "
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
            f"market_connected={self.market_streamer.is_connected if self.market_streamer else False})"
        )

    @property
    def is_connected(self) -> bool:
        """
        Check if all required WebSocket connections are active.

        Returns True only if:
        - Market streamer is connected (always required)
        - User streamer is connected (if configured)

        This ensures the system reports disconnected status when User Data
        Stream drops, preventing silent failures in TP/SL orphan prevention.

        Issue #58: Added conditional User Data Stream connection check.

        Returns:
            True if all configured streamers are connected, False otherwise.
        """
        if self.market_streamer is None:
            return False
        if not self.market_streamer.is_connected:
            return False
        # Conditional check: only if user_streamer was initialized
        if self.user_streamer is not None:
            return self.user_streamer.is_connected
        return True

    @property
    def on_candle_callback(self) -> Optional[Callable[[Candle], None]]:
        """Get candle callback from market streamer."""
        if self.market_streamer:
            return self.market_streamer.on_candle_callback
        return None

    async def start_streaming(self) -> None:
        """
        Start WebSocket streaming for all configured symbol/interval pairs.

        Delegates to PublicMarketStreamer for actual WebSocket management.

        Raises:
            ConnectionError: If WebSocket connection fails
        """
        # Idempotency check
        if self._running:
            self.logger.warning("Streaming already active, ignoring start request")
            return

        try:
            self.logger.info("Starting market data streaming via PublicMarketStreamer...")

            # Delegate to market streamer
            await self.market_streamer.start()

            # Update state
            self._running = True

            self.logger.info("Market data streaming started successfully")

        except Exception as e:
            self.logger.error(
                f"Failed to start WebSocket streaming: {e}", exc_info=True
            )
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

        Delegates to sub-streamers for actual cleanup.

        Args:
            timeout: Maximum time in seconds to wait for cleanup (default: 5.0)

        Note:
            - Method is idempotent - safe to call multiple times
            - Logs warnings if cleanup exceeds timeout
            - Does not raise exceptions on cleanup failures
        """
        # Idempotency check
        if not self._running and not self.market_streamer.is_connected:
            self.logger.debug("Collector already stopped, ignoring stop request")
            return

        self.logger.info("Initiating graceful shutdown...")

        # Update state
        self._running = False

        try:
            # Stop market streamer
            if self.market_streamer:
                self.logger.info("Stopping PublicMarketStreamer...")
                await self.market_streamer.stop(timeout=timeout)

            # Stop user streamer
            if self.user_streamer:
                self.logger.info("Stopping PrivateUserStreamer...")
                await self.user_streamer.stop(timeout=timeout)

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

    # =========================================================================
    # User Data Stream Methods (Issue #54, #57)
    # =========================================================================

    async def start_user_data_stream(self, event_bus: "EventBus") -> None:
        """
        Start User Data Stream WebSocket for real-time order updates.

        Delegates to PrivateUserStreamer for actual WebSocket management.

        Args:
            event_bus: EventBus instance for publishing ORDER_FILLED events

        Raises:
            ConnectionError: If WebSocket connection fails
            Exception: If listen key creation fails
        """
        if self.user_streamer is None:
            self.logger.warning(
                "PrivateUserStreamer not configured, skipping user data stream"
            )
            return

        # Configure event bus for publishing
        self.user_streamer.set_event_bus(event_bus)

        # Start the streamer
        await self.user_streamer.start()

    async def stop_user_data_stream(self) -> None:
        """
        Stop User Data Stream and cleanup resources.

        Delegates to PrivateUserStreamer for cleanup.

        Note:
            - Method is idempotent - safe to call multiple times
            - Called automatically by stop() method
        """
        if self.user_streamer:
            await self.user_streamer.stop()
