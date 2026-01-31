"""
Private User Data Streamer for Binance WebSocket.

This module provides the PrivateUserStreamer class for streaming real-time
order execution events from Binance User Data Stream (Issue #57).
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Optional

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from src.core.streamer_protocol import IDataStreamer
from src.core.user_data_stream import UserDataStreamManager

# Imports for type hinting only; prevents circular dependency at runtime
# Only imported during static analysis (e.g., mypy, IDE)
if TYPE_CHECKING:
    from src.core.binance_service import BinanceServiceClient
    from src.core.event_handler import EventBus


class PrivateUserStreamer(IDataStreamer):
    """
    Private user data streamer for Binance USDT-M Futures.

    Handles WebSocket connection for receiving real-time order execution
    events (ORDER_TRADE_UPDATE) from Binance User Data Stream.
    Used for detecting TP/SL fills to prevent orphaned orders.

    Responsibilities:
        - Listen key lifecycle management (via UserDataStreamManager)
        - User data WebSocket connection
        - ORDER_TRADE_UPDATE event parsing
        - ORDER_FILLED event publishing to EventBus
        - Automatic WebSocket reconnection on listen key rotation

    Listen Key Auto-Recovery:
        - Automatically reconnects when listen key expires (error -1125)
        - Minimizes data loss during reconnection
        - Logs all rotation events for monitoring

    Example:
        >>> streamer = PrivateUserStreamer(
        ...     binance_service=binance_service,
        ...     event_bus=event_bus,
        ...     is_testnet=True
        ... )
        >>> await streamer.start()
        >>> # ... receiving order updates ...
        >>> await streamer.stop()

    Attributes:
        TESTNET_USER_WS_URL: Binance Futures testnet user data WebSocket endpoint
        MAINNET_USER_WS_URL: Binance Futures mainnet user data WebSocket endpoint
    """

    # User Data Stream WebSocket URLs
    TESTNET_USER_WS_URL = "wss://stream.binancefuture.com/ws"
    MAINNET_USER_WS_URL = "wss://fstream.binance.com/ws"

    def __init__(
        self,
        binance_service: "BinanceServiceClient",
        is_testnet: bool = True,
    ) -> None:
        """
        Initialize PrivateUserStreamer.

        Args:
            binance_service: BinanceServiceClient instance for REST API calls
            is_testnet: Whether to use testnet (default: True)
        """
        self.binance_service = binance_service
        self.is_testnet = is_testnet

        # User Data Stream components
        self.user_stream_manager: Optional[UserDataStreamManager] = None
        self._user_ws_client: Optional[UMFuturesWebsocketClient] = None

        # EventBus for publishing ORDER_FILLED events
        self._event_bus: Optional["EventBus"] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        # State management
        self._running = False
        self._is_connected = False

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"PrivateUserStreamer initialized: "
            f"environment={'TESTNET' if is_testnet else 'MAINNET'}"
        )

        # Listen key rotation state
        self._reconnecting = False

    @property
    def is_connected(self) -> bool:
        """
        Check if user data stream is connected.

        Returns:
            True if WebSocket connection is active, False otherwise.
        """
        return self._is_connected and self._user_ws_client is not None

    def set_event_bus(self, event_bus: "EventBus") -> None:
        """
        Set the EventBus for publishing ORDER_FILLED events.

        Must be called before start() if order event publishing is required.

        Args:
            event_bus: EventBus instance for event publishing
        """
        self._event_bus = event_bus
        self.logger.debug("EventBus configured for PrivateUserStreamer")

    async def start(self) -> None:
        """
        Start User Data Stream WebSocket for real-time order updates.

        Creates a listen key via REST API and establishes WebSocket connection
        to receive ORDER_TRADE_UPDATE events.

        Raises:
            ConnectionError: If WebSocket connection fails
            Exception: If listen key creation fails
        """
        # Idempotency check
        if self._running:
            self.logger.warning(
                "User data stream already active, ignoring start request"
            )
            return

        # Capture event loop for thread-safe publishing
        self._event_loop = asyncio.get_running_loop()

        # Initialize UserDataStreamManager for listen key lifecycle
        # Register callback for listen key rotation (auto-recovery)
        self.user_stream_manager = UserDataStreamManager(
            self.binance_service,
            listen_key_changed_callback=self._on_listen_key_changed,
        )

        try:
            # Create listen key (also starts keep-alive loop)
            listen_key = await self.user_stream_manager.start()

            # Determine WebSocket URL based on environment
            base_url = (
                self.TESTNET_USER_WS_URL
                if self.is_testnet
                else self.MAINNET_USER_WS_URL
            )
            ws_url = f"{base_url}/{listen_key}"

            # Create WebSocket client for user data stream
            self._user_ws_client = UMFuturesWebsocketClient(
                stream_url=ws_url,
                on_message=self._handle_user_data_message,
            )

            # Update state
            self._running = True
            self._is_connected = True

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

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Stop User Data Stream and cleanup resources.

        Gracefully shuts down WebSocket client and UserDataStreamManager.

        Args:
            timeout: Maximum time in seconds to wait for cleanup (default: 5.0)
        """
        # Idempotency check
        if not self._running and self._user_ws_client is None:
            self.logger.debug(
                "PrivateUserStreamer already stopped, ignoring stop request"
            )
            return

        self.logger.info("Initiating PrivateUserStreamer shutdown...")

        # Update state
        self._running = False
        self._is_connected = False
        self._reconnecting = False

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

        self.logger.info("PrivateUserStreamer shutdown complete")

    def _on_listen_key_changed(self, old_key: str, new_key: str) -> None:
        """
        Handle listen key rotation notification from UserDataStreamManager.

        Called when the listen key expires and a new one is created.
        Reconnects the WebSocket with the new listen key.

        Args:
            old_key: The expired listen key
            new_key: The new listen key
        """
        if self._reconnecting:
            self.logger.warning(
                "Already reconnecting, ignoring duplicate rotation event"
            )
            return

        self.logger.info(f"Listen key rotated: {old_key[:16]}... -> {new_key[:16]}...")
        self.logger.info("Reconnecting User Data Stream WebSocket...")

        # Mark reconnecting state to prevent duplicate reconnections
        self._reconnecting = True

        # Schedule reconnection in the event loop (this callback runs in keep-alive thread)
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self._reconnect_websocket(new_key), self._event_loop
            )
        else:
            self.logger.error("Cannot reconnect: event loop not available")

    async def _reconnect_websocket(self, new_listen_key: str) -> None:
        """
        Reconnect WebSocket with new listen key.

        Stops the old WebSocket connection and creates a new one with
        the updated listen key.

        Args:
            new_listen_key: The new listen key to use for connection
        """
        try:
            # Step 1: Stop old WebSocket connection
            if self._user_ws_client:
                try:
                    self._user_ws_client.stop()
                    self.logger.debug("Old WebSocket connection stopped")
                except Exception as e:
                    self.logger.warning(f"Error stopping old WebSocket: {e}")

            # Step 2: Determine WebSocket URL with new listen key
            base_url = (
                self.TESTNET_USER_WS_URL
                if self.is_testnet
                else self.MAINNET_USER_WS_URL
            )
            ws_url = f"{base_url}/{new_listen_key}"

            # Step 3: Create new WebSocket client with new listen key
            self._user_ws_client = UMFuturesWebsocketClient(
                stream_url=ws_url,
                on_message=self._handle_user_data_message,
            )

            self._is_connected = True
            self.logger.info(f"WebSocket reconnected successfully: {ws_url[:60]}...")

        except Exception as e:
            self.logger.error(f"Failed to reconnect WebSocket: {e}", exc_info=True)
            # Mark as disconnected on failure
            self._is_connected = False
        finally:
            # Reset reconnecting flag regardless of outcome
            self._reconnecting = False

    def _handle_user_data_message(self, _, message) -> None:
        """
        Handle incoming User Data Stream WebSocket messages.

        Routes messages by event type:
        - ORDER_TRADE_UPDATE: Order status changes (fills, cancellations)
        - ACCOUNT_UPDATE: Position and balance changes
        - Other events: Ignored

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
                # Log account updates for monitoring
                update_reason = data.get("a", {}).get("m", "unknown")
                self.logger.debug(f"Account update received: reason={update_reason}")
            # Ignore other event types

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in user data message: {e}")
        except Exception as e:
            self.logger.error(f"Error handling user data message: {e}", exc_info=True)

    def _handle_order_trade_update(self, data: dict) -> None:
        """
        Process ORDER_TRADE_UPDATE event and publish ORDER_FILLED to EventBus.

        Only publishes events for FILLED TP/SL orders to trigger orphaned
        order cancellation in TradingEngine.

        Args:
            data: ORDER_TRADE_UPDATE event data from Binance
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
            "STOP",
            "TAKE_PROFIT",
            "TRAILING_STOP_MARKET",
        ):
            from src.models.event import Event, EventType, QueueType
            from src.models.order import Order, OrderType, OrderStatus, OrderSide

            # Create Order object for event payload
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
            else:
                self.logger.warning(
                    f"Cannot publish ORDER_FILLED event: EventBus not configured"
                )
