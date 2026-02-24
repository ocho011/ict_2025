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
    def execute_signal(
        self, signal: "Signal", quantity: float, reduce_only: bool = False
    ) -> tuple["Order", list["Order"]]:
        """Execute trading signal with TP/SL orders.

        Args:
            signal: Trading signal to execute
            quantity: Position size
            reduce_only: If True, only reduce existing position

        Returns:
            Tuple of (entry_order, [tp_order, sl_order])
        """
        ...

    @abstractmethod
    async def execute_market_close(
        self,
        symbol: str,
        position_amt: float,
        side: str,
        reduce_only: bool = True,
    ) -> Dict[str, Any]:
        """Close position with market order.

        Args:
            symbol: Trading symbol
            position_amt: Position size (absolute value)
            side: "BUY" for closing SHORT, "SELL" for closing LONG
            reduce_only: If True, only reduces position

        Returns:
            Dict with success status and order details
        """
        ...

    @abstractmethod
    def cancel_all_orders(
        self, symbol: str, verify: bool = True, max_retries: int = 3
    ) -> int:
        """Cancel all open orders for a symbol.

        Args:
            symbol: Trading pair
            verify: Whether to verify cancellation
            max_retries: Maximum verification retries

        Returns:
            Number of orders cancelled
        """
        ...

    @abstractmethod
    def get_account_balance(self) -> float:
        """Query account balance.

        Returns:
            Account balance as float
        """
        ...

    @abstractmethod
    def update_stop_loss(
        self,
        symbol: str,
        new_stop_price: float,
        side: "OrderSide",
    ) -> Optional["Order"]:
        """Update exchange stop-loss order.

        Args:
            symbol: Trading pair
            new_stop_price: New stop loss trigger price
            side: Order side for the SL

        Returns:
            New SL Order if successful, None otherwise
        """
        ...


class ExchangeProvider(ABC):
    """Abstract interface for exchange state queries and setup.

    Used by TradingEngine for leverage/margin configuration and position queries.
    Implementations: OrderGateway (live), MockExchange (backtest/paper).
    """

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol.

        Args:
            symbol: Trading pair
            leverage: Leverage multiplier

        Returns:
            True if successful
        """
        ...

    @abstractmethod
    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """Set margin type (ISOLATED or CROSSED).

        Args:
            symbol: Trading pair
            margin_type: 'ISOLATED' or 'CROSSED'

        Returns:
            True if successful
        """
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Optional["Position"]:
        """Query current position for a symbol.

        Args:
            symbol: Trading pair

        Returns:
            Position if exists, None otherwise
        """
        ...

    @abstractmethod
    async def get_all_positions(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Query all open positions for given symbols.

        Args:
            symbols: List of trading symbols

        Returns:
            List of position dictionaries
        """
        ...

    @abstractmethod
    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Query all open orders for a symbol.

        Args:
            symbol: Trading pair

        Returns:
            List of open order dictionaries
        """
        ...


class PositionProvider(ABC):
    """Abstract interface for position state management.

    Used by TradeCoordinator and EventDispatcher for position queries.
    Implementations: PositionCacheManager (live), MockExchange (backtest/paper).
    """

    @abstractmethod
    def get(self, symbol: str) -> Optional["Position"]:
        """Get cached position for symbol.

        Args:
            symbol: Trading pair

        Returns:
            Position if exists, None otherwise
        """
        ...

    @abstractmethod
    def get_fresh(self, symbol: str) -> Optional["Position"]:
        """Get guaranteed-fresh position (bypasses cache).

        Args:
            symbol: Trading pair

        Returns:
            Position if exists, None otherwise
        """
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
