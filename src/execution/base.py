"""Abstract base classes for execution layer.

Defines interfaces for order execution, exchange state queries, and position
management. Concrete implementations include OrderGateway (live trading)
and MockExchange (backtesting/paper trading).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.models.order import Order, OrderSide
    from src.models.position import Position
    from src.models.signal import Signal


class ExecutionGateway(ABC):
    """Abstract interface for order execution.

    Used by TradeCoordinator and EventDispatcher for core trading operations.
    Implementations: OrderGateway (live), MockExchange (backtest/paper).
    """

    @abstractmethod
    async def execute_signal(
        self, signal: "Signal", quantity: float, reduce_only: bool = False
    ) -> tuple["Order", list["Order"]]:
        """Execute trading signal with TP/SL orders."""
        ...

    @abstractmethod
    async def execute_market_close(
        self,
        symbol: str,
        position_amt: float,
        side: str,
        reduce_only: bool = True,
    ) -> Dict[str, Any]:
        """Close position with market order."""
        ...

    @abstractmethod
    async def cancel_all_orders(
        self, symbol: str, verify: bool = True, max_retries: int = 3
    ) -> int:
        """Cancel all open orders for a symbol."""
        ...

    @abstractmethod
    async def get_account_balance(self) -> float:
        """Query account balance."""
        ...

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Query all open orders for a symbol."""
        ...

    @abstractmethod
    async def update_stop_loss(
        self,
        symbol: str,
        new_stop_price: float,
        side: "OrderSide",
    ) -> Optional["Order"]:
        """Update exchange stop-loss order."""
        ...


class ExchangeProvider(ABC):
    """Abstract interface for exchange state queries and setup."""

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol."""
        ...

    @abstractmethod
    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """Set margin type (ISOLATED or CROSSED)."""
        ...

    @abstractmethod
    async def get_position(self, symbol: str) -> Optional["Position"]:
        """Query current position for a symbol."""
        ...

    @abstractmethod
    async def get_all_positions(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Query all open positions for given symbols."""
        ...

    @abstractmethod
    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Query all open orders for a symbol."""
        ...


class PositionProvider(ABC):
    """Abstract interface for position state management.

    Used by TradeCoordinator and EventDispatcher for position queries.
    Implementations: PositionCacheManager (live), MockExchange (backtest/paper).
    """

    @abstractmethod
    async def get(self, symbol: str) -> Optional["Position"]:
        """Get cached position for symbol."""
        ...

    @abstractmethod
    async def get_fresh(self, symbol: str) -> Optional["Position"]:
        """Get guaranteed-fresh position (bypasses cache)."""
        ...

    @abstractmethod
    def invalidate(self, symbol: str) -> None:
        """Invalidate cached position for symbol.

        Args:
            symbol: Trading pair
        """
        ...

    @property
    @abstractmethod
    def cache(self) -> dict:
        """Access internal cache dict."""
        ...
