"""
Order model
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderType(Enum):
    """Order types"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderSide(Enum):
    """Order sides"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status"""
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """
    Exchange order
    """
    symbol: str
    order_type: OrderType
    side: OrderSide
    quantity: float
    price: float = None
    stop_price: float = None
    order_id: str = None
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime = None
    filled_quantity: float = 0.0

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
