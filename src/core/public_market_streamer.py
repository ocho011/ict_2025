"""
Public Market Data Streamer for Binance WebSocket.

This module provides the PublicMarketStreamer class for streaming live market data
(klines/candlesticks) from Binance USDT-M Futures via WebSocket (Issue #57).
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from src.core.streamer_protocol import IDataStreamer
from src.models.candle import Candle


class PublicMarketStreamer(IDataStreamer):
    """
    Public market data streamer for Binance USDT-M Futures.

    Handles WebSocket connections for receiving real-time kline (candlestick)
    data from Binance. Supports multiple symbols with separate connections
    per symbol for reliability.

    Responsibilities (Issue #96 - Pure Data Relay, #107 - Callback Pattern):
        - WebSocket connection management (one per symbol)
        - Kline message parsing and Candle object creation
        - Connection heartbeat monitoring
        - Graceful cleanup on shutdown

    Note: Event creation and publishing is handled by TradingEngine via callbacks.
    This streamer is a pure data relay that only parses and forwards Candle objects.

    Example:
        >>> streamer = PublicMarketStreamer(
        ...     symbols=['BTCUSDT', 'ETHUSDT'],
        ...     intervals=['1m', '5m'],
        ...     is_testnet=True,
        ...     on_candle_callback=handle_candle
        ... )
        >>> await streamer.start()
        >>> # ... streaming active ...
        >>> await streamer.stop()

    Attributes:
        TESTNET_WS_URL: Binance Futures testnet WebSocket endpoint
        MAINNET_WS_URL: Binance Futures mainnet WebSocket endpoint
    """

    # Default WebSocket URLs for fallback when no config provided (Issue #92)
    DEFAULT_TESTNET_WS_URL = "wss://stream.binancefuture.com"
    DEFAULT_MAINNET_WS_URL = "wss://fstream.binance.com"

    def __init__(
        self,
        symbols: List[str],
        intervals: List[str],
        is_testnet: bool = True,
        on_candle_callback: Optional[Callable[[Candle], None]] = None,
        ws_url: Optional[str] = None,
    ) -> None:
        """
        Initialize PublicMarketStreamer.

        Args:
            symbols: List of trading pairs to monitor (e.g., ['BTCUSDT', 'ETHUSDT'])
            intervals: List of timeframes to collect (e.g., ['1m', '5m', '1h'])
            is_testnet: Whether to use testnet (default: True)
            on_candle_callback: Optional callback invoked on each candle update.
                               Signature: callback(candle: Candle) -> None
            ws_url: Optional custom WebSocket URL (Issue #92).
                    If None, uses default Binance endpoints.
        """
        # Validate inputs
        if not symbols:
            raise ValueError("symbols list cannot be empty")
        if not intervals:
            raise ValueError("intervals list cannot be empty")

        self.symbols = [s.upper() for s in symbols]
        self.intervals = intervals
        self.is_testnet = is_testnet
        self.on_candle_callback = on_candle_callback

        # Use provided URL or fall back to defaults (Issue #92)
        if ws_url:
            self._ws_url = ws_url
        else:
            self._ws_url = (
                self.DEFAULT_TESTNET_WS_URL
                if is_testnet
                else self.DEFAULT_MAINNET_WS_URL
            )

        # WebSocket clients (one per symbol)
        self.ws_clients: dict[str, UMFuturesWebsocketClient] = {}

        # State management
        self._running = False
        self._is_connected = False

        # Connection monitoring
        self._last_heartbeat_time = 0.0
        self._heartbeat_interval = 30.0  # seconds
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"PublicMarketStreamer initialized: "
            f"{len(self.symbols)} symbols, {len(self.intervals)} intervals, "
            f"environment={'TESTNET' if is_testnet else 'MAINNET'}"
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

        Error Handling:
            All errors are logged but do not raise exceptions to prevent
            WebSocket disconnection on malformed messages.
        """
        try:
            # Parse JSON string if needed
            if isinstance(message, str):
                message = json.loads(message)

            # Validate message type
            event_type = message.get("e")
            if event_type != "kline":
                # Subscription confirmations, etc. - ignore silently
                return

            # Extract kline data
            kline = message.get("k")
            if not kline:
                self.logger.error(f"Message missing 'k' (kline data): {message}")
                return

            # Parse and convert all fields
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

            # Invoke user callback if configured
            if self.on_candle_callback:
                self.on_candle_callback(candle)

        except KeyError as e:
            self.logger.error(
                f"Missing required field in kline message: {e} | Message: {message}",
                exc_info=True,
            )
        except (ValueError, TypeError) as e:
            self.logger.error(
                f"Invalid data type in kline message: {e} | Message: {message}",
                exc_info=True,
            )
        except Exception as e:
            self.logger.error(
                f"Unexpected error parsing kline message: {e} | Message: {message}",
                exc_info=True,
            )

    async def start(self) -> None:
        """
        Start WebSocket streaming for all configured symbol/interval pairs.

        Establishes separate WebSocket connections for each symbol to ensure
        reliability on Binance Testnet.

        Raises:
            ConnectionError: If WebSocket connection fails
        """
        # Idempotency check
        if self._running:
            self.logger.warning("Streaming already active, ignoring start request")
            return

        try:
            stream_url = self._ws_url

            self.logger.info(
                f"Initializing {len(self.symbols)} WebSocket connections to {stream_url}"
            )

            total_stream_count = 0

            # Create a separate client for each symbol
            for symbol in self.symbols:
                self.logger.info(f"Establishing connection for {symbol}...")

                client = UMFuturesWebsocketClient(
                    stream_url=stream_url, on_message=self._handle_kline_message
                )

                # Subscribe to all intervals for this symbol
                symbol_stream_count = 0
                for interval in self.intervals:
                    stream_name = f"{symbol.lower()}@kline_{interval}"
                    self.logger.debug(f"[{symbol}] Subscribing to: {stream_name}")

                    client.kline(symbol=symbol.lower(), interval=interval)
                    symbol_stream_count += 1

                # Store the client
                self.ws_clients[symbol] = client
                total_stream_count += symbol_stream_count

                # Small delay to prevent connection rate limiting
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
            await self.stop()
            raise ConnectionError(f"WebSocket initialization failed: {e}")

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop streaming and cleanup resources.

        Args:
            timeout: Maximum time in seconds to wait for cleanup (default: 5.0)
        """
        # Idempotency check
        if not self._running and not self.ws_clients:
            self.logger.debug("Streamer already stopped, ignoring stop request")
            return

        self.logger.info("Initiating PublicMarketStreamer shutdown...")

        # Stop heartbeat monitor
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Set flags to prevent new operations
        self._running = False
        self._is_connected = False

        try:
            # Stop all WebSocket clients
            if self.ws_clients:
                self.logger.debug(
                    f"Stopping {len(self.ws_clients)} WebSocket clients..."
                )

                stop_tasks = []
                for symbol, client in self.ws_clients.items():
                    stop_tasks.append(asyncio.to_thread(client.stop))

                if stop_tasks:
                    try:
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

            self.logger.info("PublicMarketStreamer shutdown complete")

        except Exception as e:
            self.logger.error(f"Unexpected error during shutdown: {e}", exc_info=True)

    async def _heartbeat_monitor(self) -> None:
        """
        Monitor WebSocket connection status with periodic heartbeat logging.

        Logs connection status at fixed times: :10 and :40 seconds of each minute.
        """
        while self._running:
            try:
                # Calculate seconds until next :10 or :40 mark
                now = datetime.now()
                current_second = now.second

                if current_second < 10:
                    next_target = 10
                elif current_second < 40:
                    next_target = 40
                else:
                    next_target = 70  # :10 of next minute

                sleep_seconds = next_target - current_second
                sleep_seconds -= now.microsecond / 1_000_000

                await asyncio.sleep(sleep_seconds)

                if not self._running:
                    break

                current_time = time.time()
                active_connections = len(self.ws_clients)

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
                await asyncio.sleep(5.0)
