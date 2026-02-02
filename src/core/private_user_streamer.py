"""
Private User Data Streamer for Binance WebSocket.

This module provides the PrivateUserStreamer class for streaming real-time
order execution events from Binance User Data Stream (Issue #57).
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from src.core.audit_logger import AuditEventType, AuditLogger
from src.core.streamer_protocol import IDataStreamer
from src.core.user_data_stream import UserDataStreamManager

# Imports for type hinting only; prevents circular dependency at runtime
# Only imported during static analysis (e.g., mypy, IDE)
if TYPE_CHECKING:
    from src.core.binance_service import BinanceServiceClient
    from src.core.event_handler import EventBus


@dataclass
class PositionEntryData:
    """Tracks position entry data for PnL and duration calculations."""

    entry_price: float
    entry_time: datetime
    quantity: float
    side: str  # "LONG" or "SHORT"


@dataclass
class PositionUpdate:
    """Position update data from ACCOUNT_UPDATE WebSocket event."""

    symbol: str
    position_amt: float  # Positive for LONG, negative for SHORT
    entry_price: float
    unrealized_pnl: float
    margin_type: str  # "cross" or "isolated"
    position_side: str  # "BOTH", "LONG", or "SHORT"


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

        # AuditLogger for position closure logging (Issue #87)
        self._audit_logger: Optional[AuditLogger] = None

        # Position entry data tracking for PnL and duration calculations
        self._position_entry_data: Dict[str, PositionEntryData] = {}

        # Position update callback for real-time cache updates (Issue #41 rate limit fix)
        self._position_update_callback: Optional[Callable[[List[PositionUpdate]], None]] = None

        # Order update callback for real-time order cache updates (Issue #41 rate limit fix)
        self._order_update_callback: Optional[Callable[[str, str, str, Dict], None]] = None

        # State management
        self._running = False
        self._is_connected = False

        # Logging
        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"PrivateUserStreamer initialized: "
            f"environment={'TESTNET' if is_testnet else 'MAINNET'}"
        )

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

    def set_audit_logger(self, audit_logger: AuditLogger) -> None:
        """
        Set the AuditLogger for position closure logging.

        Must be called before start() if audit logging is required.

        Args:
            audit_logger: AuditLogger instance for audit trail
        """
        self._audit_logger = audit_logger
        self.logger.debug("AuditLogger configured for PrivateUserStreamer")

    def set_position_update_callback(
        self, callback: Callable[[List[PositionUpdate]], None]
    ) -> None:
        """
        Set callback for position updates from ACCOUNT_UPDATE events.

        This enables real-time position cache updates without REST API calls,
        reducing rate limit pressure (Issue #41 rate limit fix).

        Args:
            callback: Function to call with list of PositionUpdate objects
        """
        self._position_update_callback = callback
        self.logger.debug("Position update callback configured for PrivateUserStreamer")

    def set_order_update_callback(
        self, callback: Callable[[str, str, str, Dict], None]
    ) -> None:
        """
        Set callback for order updates from ORDER_TRADE_UPDATE events.

        This enables real-time order cache updates without REST API calls,
        reducing rate limit pressure (Issue #41 rate limit fix).

        Args:
            callback: Function(symbol, order_id, order_status, order_data)
        """
        self._order_update_callback = callback
        self.logger.debug("Order update callback configured for PrivateUserStreamer")

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
        self.user_stream_manager = UserDataStreamManager(self.binance_service)

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
                self._handle_account_update(data)
            # Ignore other event types

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in user data message: {e}")
        except Exception as e:
            self.logger.error(f"Error handling user data message: {e}", exc_info=True)

    def _handle_account_update(self, data: dict) -> None:
        """
        Process ACCOUNT_UPDATE event for real-time position cache updates.

        Parses position data from WebSocket and invokes callback to update
        TradingEngine's position cache without REST API calls (Issue #41 rate limit fix).

        Args:
            data: ACCOUNT_UPDATE event data from Binance

        Binance ACCOUNT_UPDATE structure:
            {
                "e": "ACCOUNT_UPDATE",
                "a": {
                    "m": "ORDER",  // Event reason
                    "P": [         // Positions array
                        {
                            "s": "BTCUSDT",      // Symbol
                            "pa": "0.001",       // Position amount
                            "ep": "9000.0",      // Entry price
                            "up": "0.0",         // Unrealized PnL
                            "mt": "cross",       // Margin type
                            "ps": "BOTH"         // Position side
                        }
                    ]
                }
            }
        """
        account_data = data.get("a", {})
        update_reason = account_data.get("m", "unknown")
        positions_data = account_data.get("P", [])

        self.logger.debug(
            f"Account update received: reason={update_reason}, "
            f"positions_count={len(positions_data)}"
        )

        if not positions_data:
            return

        # Parse position updates
        position_updates: List[PositionUpdate] = []
        for pos in positions_data:
            try:
                position_update = PositionUpdate(
                    symbol=pos.get("s", ""),
                    position_amt=float(pos.get("pa", 0)),
                    entry_price=float(pos.get("ep", 0)),
                    unrealized_pnl=float(pos.get("up", 0)),
                    margin_type=pos.get("mt", "cross"),
                    position_side=pos.get("ps", "BOTH"),
                )
                position_updates.append(position_update)

                self.logger.debug(
                    f"Position update parsed: {position_update.symbol} "
                    f"amt={position_update.position_amt}, "
                    f"entry={position_update.entry_price}"
                )
            except (ValueError, TypeError) as e:
                self.logger.warning(f"Failed to parse position data: {e}")
                continue

        # Invoke callback if configured
        if position_updates and self._position_update_callback:
            try:
                self._position_update_callback(position_updates)
                self.logger.debug(
                    f"Position update callback invoked with {len(position_updates)} updates"
                )
            except Exception as e:
                self.logger.error(f"Position update callback failed: {e}", exc_info=True)

    def _handle_order_trade_update(self, data: dict) -> None:
        """
        Process ORDER_TRADE_UPDATE event and publish ORDER_FILLED to EventBus.

        Handles two scenarios:
        1. Position entry (MARKET/LIMIT fills): Track entry data for later PnL calculation
        2. Position closure (TP/SL fills): Log to audit trail with PnL and duration

        Args:
            data: ORDER_TRADE_UPDATE event data from Binance
        """
        order_data = data.get("o", {})

        order_status = order_data.get("X")  # FILLED, CANCELED, NEW, etc.
        order_type = order_data.get("ot")  # TAKE_PROFIT_MARKET, STOP_MARKET, etc.
        symbol = order_data.get("s")
        order_id = str(order_data.get("i", ""))
        order_side = order_data.get("S")  # BUY or SELL

        self.logger.info(
            f"Order update: {symbol} {order_type} -> {order_status} (ID: {order_id})"
        )

        # Invoke order update callback for real-time cache updates (Issue #41 rate limit fix)
        if self._order_update_callback:
            try:
                self._order_update_callback(symbol, order_id, order_status, order_data)
                self.logger.debug(
                    f"Order update callback invoked: {symbol} {order_id} -> {order_status}"
                )
            except Exception as e:
                self.logger.error(f"Order update callback failed: {e}", exc_info=True)

        # Track position entry data for MARKET/LIMIT fills
        if order_status == "FILLED" and order_type in ("MARKET", "LIMIT"):
            entry_price = float(order_data.get("ap", 0))  # Average fill price
            quantity = float(order_data.get("z", 0))  # Filled quantity
            # Determine position side: BUY opens LONG, SELL opens SHORT
            position_side = "LONG" if order_side == "BUY" else "SHORT"

            self._position_entry_data[symbol] = PositionEntryData(
                entry_price=entry_price,
                entry_time=datetime.utcnow(),
                quantity=quantity,
                side=position_side,
            )
            self.logger.info(
                f"Tracking position entry: {symbol} {position_side} "
                f"price={entry_price}, qty={quantity}"
            )

        # Handle TP/SL order fills (position closure)
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
            # Extract callback_rate for TRAILING_STOP_MARKET orders
            callback_rate = None
            if order_type == "TRAILING_STOP_MARKET":
                callback_rate = float(order_data.get("cr", 0)) if order_data.get("cr") else 1.0

            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=OrderSide(order_data.get("S")),
                order_type=OrderType(order_type),
                quantity=float(order_data.get("q", 0)),
                price=float(order_data.get("ap", 0)),  # Average fill price
                stop_price=float(order_data.get("sp", 0)),  # Stop/trigger price
                callback_rate=callback_rate,
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

            # Log position closure to audit trail (Issue #87)
            self._log_position_closure(symbol, order_data, order_type, order_id)

    def _log_position_closure(
        self,
        symbol: str,
        order_data: dict,
        order_type: str,
        order_id: str,
    ) -> None:
        """
        Log position closure to audit trail with PnL and duration.

        Args:
            symbol: Trading symbol
            order_data: ORDER_TRADE_UPDATE order data
            order_type: Order type (TAKE_PROFIT_MARKET, STOP_MARKET, etc.)
            order_id: Order ID
        """
        # Use singleton pattern if not explicitly set
        audit_logger = self._audit_logger or AuditLogger.get_instance()
        if not audit_logger:
            self.logger.debug("AuditLogger not available, skipping position closure log")
            return

        # Map order type to close reason
        close_reason_map = {
            "TAKE_PROFIT_MARKET": "TAKE_PROFIT",
            "TAKE_PROFIT": "TAKE_PROFIT",
            "STOP_MARKET": "STOP_LOSS",
            "STOP": "STOP_LOSS",
            "TRAILING_STOP_MARKET": "TRAILING_STOP",
        }
        close_reason = close_reason_map.get(order_type, "UNKNOWN")

        # Extract exit details
        exit_price = float(order_data.get("ap", 0))  # Average fill price
        exit_quantity = float(order_data.get("z", 0))  # Filled quantity
        exit_side = order_data.get("S")  # BUY or SELL

        # Build closure data
        closure_data = {
            "close_reason": close_reason,
            "exit_price": exit_price,
            "exit_quantity": exit_quantity,
            "exit_side": exit_side,
            "order_id": order_id,
            "order_type": order_type,
        }

        # Add entry data if available (for PnL and duration)
        entry_data = self._position_entry_data.get(symbol)
        if entry_data:
            closure_data["entry_price"] = entry_data.entry_price
            closure_data["position_side"] = entry_data.side

            # Calculate holding duration
            held_duration = datetime.utcnow() - entry_data.entry_time
            closure_data["held_duration_seconds"] = held_duration.total_seconds()

            # Calculate realized PnL
            # LONG: profit when exit > entry, SHORT: profit when entry > exit
            if entry_data.side == "LONG":
                realized_pnl = (exit_price - entry_data.entry_price) * exit_quantity
            else:  # SHORT
                realized_pnl = (entry_data.entry_price - exit_price) * exit_quantity
            closure_data["realized_pnl"] = realized_pnl

            # Clean up position state
            del self._position_entry_data[symbol]
            self.logger.debug(f"Cleaned up position entry data for {symbol}")
        else:
            self.logger.warning(
                f"No entry data found for {symbol}, PnL and duration unavailable"
            )

        # Log to audit trail
        try:
            audit_logger.log_event(
                event_type=AuditEventType.POSITION_CLOSED,
                operation="tp_sl_order_filled",
                symbol=symbol,
                data=closure_data,
            )
            self.logger.info(
                f"Position closed via {close_reason}: {symbol} "
                f"exit_price={exit_price}, qty={exit_quantity}"
            )
        except Exception as e:
            self.logger.error(f"Failed to log position closure: {e}")
