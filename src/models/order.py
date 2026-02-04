"""
Order model
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderType(Enum):
    """Binance order types (EXACT API values)."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"


class OrderSide(Enum):
    """Binance order sides (EXACT API values)."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Binance order statuses (EXACT API values)."""

    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class OrderUpdate:
    """
    Order update data from ORDER_TRADE_UPDATE WebSocket event.

    Represents real-time order status changes received via User Data Stream,
    enabling order cache updates without REST API calls (Issue #41).

    Attributes:
        symbol: Trading pair (e.g., "BTCUSDT")
        order_id: Binance order ID
        client_order_id: Client-defined order ID
        side: Order side (BUY or SELL)
        order_type: Order type (MARKET, LIMIT, STOP_MARKET, etc.)
        order_status: Current status (NEW, FILLED, CANCELED, etc.)
        price: Order price (for LIMIT orders)
        average_price: Average fill price
        quantity: Original order quantity
        filled_quantity: Executed quantity
        commission: Trading fee amount
        commission_asset: Fee currency (e.g., "USDT")
        trade_id: Trade ID (for fills)
        realized_pnl: Realized profit/loss (for position-closing fills)
        event_time: Event timestamp (milliseconds)
        transaction_time: Transaction timestamp (milliseconds)

    Binance ORDER_TRADE_UPDATE structure:
        {
            "s": "BTCUSDT",          // Symbol
            "i": 123456789,          // Order ID
            "c": "client_order_id",  // Client order ID
            "S": "BUY",              // Side
            "ot": "MARKET",          // Order type (original)
            "X": "FILLED",           // Order status
            "p": "0",                // Price
            "ap": "9000.0",          // Average price
            "q": "0.001",            // Quantity
            "z": "0.001",            // Filled quantity
            "n": "0.01",             // Commission
            "N": "USDT",             // Commission asset
            "t": 12345,              // Trade ID
            "rp": "10.5",            // Realized PnL
            "E": 1234567890123,      // Event time
            "T": 1234567890123       // Transaction time
        }
    """

    symbol: str
    order_id: str
    client_order_id: str
    side: str  # "BUY" or "SELL"
    order_type: str  # "MARKET", "LIMIT", "STOP_MARKET", etc.
    order_status: str  # "NEW", "FILLED", "CANCELED", etc.
    price: float
    average_price: float
    quantity: float
    filled_quantity: float
    commission: float = 0.0
    commission_asset: Optional[str] = None
    trade_id: Optional[int] = None
    realized_pnl: float = 0.0
    event_time: Optional[int] = None
    transaction_time: Optional[int] = None

    @classmethod
    def from_websocket_data(cls, data: dict) -> "OrderUpdate":
        """
        Create OrderUpdate from raw WebSocket ORDER_TRADE_UPDATE data.

        Args:
            data: The 'o' object from ORDER_TRADE_UPDATE event

        Returns:
            OrderUpdate instance
        """
        return cls(
            symbol=data.get("s", ""),
            order_id=str(data.get("i", "")),
            client_order_id=data.get("c", ""),
            side=data.get("S", ""),
            order_type=data.get("ot", ""),
            order_status=data.get("X", ""),
            price=float(data.get("p", 0)),
            average_price=float(data.get("ap", 0)),
            quantity=float(data.get("q", 0)),
            filled_quantity=float(data.get("z", 0)),
            commission=float(data.get("n", 0)) if data.get("n") else 0.0,
            commission_asset=data.get("N"),
            trade_id=int(data.get("t")) if data.get("t") else None,
            realized_pnl=float(data.get("rp", 0)) if data.get("rp") else 0.0,
            event_time=int(data.get("E")) if data.get("E") else None,
            transaction_time=int(data.get("T")) if data.get("T") else None,
        )


@dataclass
class Order:
    """
    Binance futures order representation.

    Attributes:
        symbol: Trading pair
        side: BUY or SELL
        order_type: Order type (MARKET, LIMIT, etc.)
        quantity: Order size in base asset
        price: Limit price (required for LIMIT orders)
        stop_price: Trigger price (required for STOP orders)
        order_id: Binance order ID (set after submission)
        client_order_id: Client-defined ID (optional)
        status: Current order status
        timestamp: Order creation/update time
    """

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    callback_rate: Optional[float] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate order parameters."""
        # For TP/SL orders with closePosition=True, quantity can be 0
        # since Binance manages the position closure automatically
        is_tpsl_order = self.order_type in (
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.STOP,
            OrderType.TAKE_PROFIT,
            OrderType.TRAILING_STOP_MARKET,
        )

        if not is_tpsl_order and self.quantity <= 0:
            raise ValueError(f"Quantity must be > 0, got {self.quantity}")

        # LIMIT orders and Algo Limit orders require price
        if self.order_type in (OrderType.LIMIT, OrderType.STOP, OrderType.TAKE_PROFIT):
            if self.price is None:
                raise ValueError(f"{self.order_type.value} requires price")

        # STOP orders require stop_price
        # TRAILING_STOP_MARKET uses activationPrice (mapped to stop_price) or callbackRate
        if is_tpsl_order and self.order_type != OrderType.TRAILING_STOP_MARKET:
            if self.stop_price is None:
                raise ValueError(f"{self.order_type.value} requires stop_price")

        # TRAILING_STOP_MARKET validation
        if self.order_type == OrderType.TRAILING_STOP_MARKET:
            if self.callback_rate is None:
                raise ValueError("TRAILING_STOP_MARKET requires callback_rate")
