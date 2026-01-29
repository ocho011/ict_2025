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
