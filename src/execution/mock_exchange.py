"""In-memory exchange simulator for backtesting and paper trading.

Implements ExecutionGateway, ExchangeProvider, and PositionProvider ABCs
to provide a drop-in replacement for OrderGateway + PositionCacheManager
in non-live environments.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.execution.base import ExecutionGateway, ExchangeProvider, PositionProvider
from src.models.order import Order, OrderSide, OrderStatus, OrderType
from src.models.position import Position
from src.models.signal import Signal, SignalType


class MockExchange(ExecutionGateway, ExchangeProvider, PositionProvider):
    """In-memory exchange for backtesting and paper trading.

    Simulates order execution with configurable fees and slippage.
    All orders fill instantly at the signal price (adjusted for slippage).

    Attributes:
        _balance: Current account balance
        _initial_balance: Starting balance for PnL calculation
        _fee_rate: Trading fee rate (default 0.04% = taker fee)
        _slippage_bps: Slippage in basis points
        _positions: Active positions by symbol
        _open_orders: Pending TP/SL orders by symbol
        _filled_orders: History of filled orders
        _leverage: Leverage settings by symbol
        _realized_pnl: Cumulative realized PnL
        _total_fees: Cumulative fees paid
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        fee_rate: float = 0.0004,
        slippage_bps: float = 1.0,
    ):
        self._initial_balance = initial_balance
        self._balance = initial_balance
        self._fee_rate = fee_rate
        self._slippage_bps = slippage_bps
        self._positions: Dict[str, Position] = {}
        self._open_orders: Dict[str, List[Order]] = {}
        self._filled_orders: List[Order] = []
        self._order_counter = 0
        self._leverage: Dict[str, int] = {}
        self._margin_type: Dict[str, str] = {}
        self._realized_pnl = 0.0
        self._total_fees = 0.0
        self._cache: Dict[str, tuple[Optional[Position], float]] = {}
        self._last_signal_time: Dict[str, float] = {}
        self.logger = logging.getLogger(__name__)

    def _next_order_id(self) -> str:
        """Generate sequential order ID."""
        self._order_counter += 1
        return f"MOCK-{self._order_counter}"

    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        """Apply slippage to fill price.

        Buys fill slightly higher, sells fill slightly lower.
        """
        direction = 1 if is_buy else -1
        return price * (1 + self._slippage_bps / 10000 * direction)

    def _calculate_fee(self, quantity: float, price: float) -> float:
        """Calculate trading fee."""
        return quantity * price * self._fee_rate

    # ── ExecutionGateway methods ──────────────────────────────────

    def execute_signal(
        self, signal: Signal, quantity: float, reduce_only: bool = False
    ) -> tuple[Order, list[Order]]:
        """Execute signal with instant fill model."""
        side = (
            OrderSide.BUY
            if signal.signal_type == SignalType.LONG_ENTRY
            else OrderSide.SELL
        )

        # Apply slippage
        fill_price = self._apply_slippage(signal.entry_price, side == OrderSide.BUY)

        # Calculate and deduct fee
        fee = self._calculate_fee(quantity, fill_price)
        self._total_fees += fee
        self._balance -= fee

        # Create entry order (already filled)
        entry_order = Order(
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=fill_price,
            order_id=self._next_order_id(),
            status=OrderStatus.FILLED,
            filled_quantity=quantity,
            timestamp=datetime.now(timezone.utc),
        )
        self._filled_orders.append(entry_order)

        # Update position
        position_side = "LONG" if signal.signal_type == SignalType.LONG_ENTRY else "SHORT"
        leverage = self._leverage.get(signal.symbol, 1)
        self._positions[signal.symbol] = Position(
            symbol=signal.symbol,
            side=position_side,
            entry_price=fill_price,
            quantity=quantity,
            leverage=leverage,
            entry_time=datetime.now(timezone.utc),
        )
        # Update cache
        self._cache[signal.symbol] = (self._positions[signal.symbol], time.time())

        # Create TP/SL pending orders
        tpsl_orders: list[Order] = []

        if signal.take_profit is not None:
            tp_side = OrderSide.SELL if position_side == "LONG" else OrderSide.BUY
            tp_order = Order(
                symbol=signal.symbol,
                side=tp_side,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                quantity=quantity,
                price=signal.take_profit,
                order_id=self._next_order_id(),
                status=OrderStatus.NEW,
                stop_price=signal.take_profit,
            )
            tpsl_orders.append(tp_order)
            self._open_orders.setdefault(signal.symbol, []).append(tp_order)

        if signal.stop_loss is not None:
            sl_side = OrderSide.SELL if position_side == "LONG" else OrderSide.BUY
            sl_order = Order(
                symbol=signal.symbol,
                side=sl_side,
                order_type=OrderType.STOP_MARKET,
                quantity=quantity,
                price=signal.stop_loss,
                order_id=self._next_order_id(),
                status=OrderStatus.NEW,
                stop_price=signal.stop_loss,
            )
            tpsl_orders.append(sl_order)
            self._open_orders.setdefault(signal.symbol, []).append(sl_order)

        return entry_order, tpsl_orders

    async def execute_market_close(
        self,
        symbol: str,
        position_amt: float,
        side: str,
        reduce_only: bool = True,
    ) -> Dict[str, Any]:
        """Close position with market order."""
        position = self._positions.get(symbol)
        if position is None:
            return {"success": False, "error": "No position to close"}

        is_buy = side == "BUY"
        fill_price = self._apply_slippage(position.entry_price, is_buy)

        # Calculate PnL
        if position.side == "LONG":
            pnl = (fill_price - position.entry_price) * position_amt
        else:
            pnl = (position.entry_price - fill_price) * position_amt

        # Calculate and deduct fee
        fee = self._calculate_fee(position_amt, fill_price)
        self._total_fees += fee
        self._balance -= fee

        self._realized_pnl += pnl
        self._balance += pnl

        # Create close order
        close_order = Order(
            symbol=symbol,
            side=OrderSide.BUY if is_buy else OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=position_amt,
            price=fill_price,
            order_id=self._next_order_id(),
            status=OrderStatus.FILLED,
            filled_quantity=position_amt,
            timestamp=datetime.now(timezone.utc),
        )
        self._filled_orders.append(close_order)

        # Remove position
        del self._positions[symbol]
        self._cache[symbol] = (None, time.time())

        # Cancel remaining orders for this symbol
        self._open_orders.pop(symbol, None)

        return {
            "success": True,
            "order_id": close_order.order_id,
            "avg_price": fill_price,
            "executed_qty": position_amt,
            "status": "FILLED",
        }

    def cancel_all_orders(
        self, symbol: str, verify: bool = True, max_retries: int = 3
    ) -> int:
        """Cancel all open orders for a symbol."""
        orders = self._open_orders.pop(symbol, [])
        for order in orders:
            order.status = OrderStatus.CANCELED
        return len(orders)

    def get_account_balance(self) -> float:
        """Return current balance."""
        return self._balance

    def update_stop_loss(
        self,
        symbol: str,
        new_stop_price: float,
        side: OrderSide,
    ) -> Optional[Order]:
        """Update SL order by replacing it."""
        orders = self._open_orders.get(symbol, [])

        # Find existing SL order
        sl_index = None
        for i, order in enumerate(orders):
            if order.order_type in (OrderType.STOP_MARKET, OrderType.STOP):
                sl_index = i
                break

        if sl_index is None:
            return None

        # Cancel old SL
        old_sl = orders.pop(sl_index)
        old_sl.status = OrderStatus.CANCELED

        # Create new SL
        new_sl = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP_MARKET,
            quantity=old_sl.quantity,
            price=new_stop_price,
            order_id=self._next_order_id(),
            status=OrderStatus.NEW,
            stop_price=new_stop_price,
        )
        orders.append(new_sl)
        self._open_orders[symbol] = orders
        return new_sl

    # ── ExchangeProvider methods ──────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol."""
        self._leverage[symbol] = leverage
        return True

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """Set margin type."""
        self._margin_type[symbol] = margin_type
        return True

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for symbol."""
        return self._positions.get(symbol)

    async def get_all_positions(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """Get all positions for given symbols."""
        result = []
        for symbol in symbols:
            pos = self._positions.get(symbol)
            if pos:
                result.append({
                    "symbol": symbol,
                    "positionAmt": str(pos.quantity if pos.side == "LONG" else -pos.quantity),
                    "entryPrice": str(pos.entry_price),
                    "unRealizedProfit": str(pos.unrealized_pnl),
                    "leverage": str(pos.leverage),
                })
        return result

    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Get open orders for symbol."""
        orders = self._open_orders.get(symbol, [])
        return [
            {
                "orderId": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "type": order.order_type.value,
                "origQty": str(order.quantity),
                "price": str(order.price),
                "stopPrice": str(order.stop_price) if order.stop_price else "0",
                "status": order.status.value,
            }
            for order in orders
            if order.status == OrderStatus.NEW
        ]

    # ── PositionProvider methods ──────────────────────────────────

    def get(self, symbol: str) -> Optional[Position]:
        """Get position (same as get_position for mock)."""
        return self._positions.get(symbol)

    def get_fresh(self, symbol: str) -> Optional[Position]:
        """Get fresh position (always fresh in mock)."""
        return self._positions.get(symbol)

    def invalidate(self, symbol: str) -> None:
        """No-op for mock (positions are always fresh)."""
        pass

    @property
    def cache(self) -> dict:
        """Return cache dict for compatibility with EventDispatcher."""
        return self._cache

    # ── Mock-specific methods (not in ABCs) ───────────────────────

    def check_pending_orders(
        self, symbol: str, current_price: float
    ) -> list[Order]:
        """Check if any pending TP/SL orders trigger at current price.

        Called by backtesting event loop to simulate TP/SL fills.

        Args:
            symbol: Trading pair
            current_price: Current market price

        Returns:
            List of orders that were filled
        """
        orders = self._open_orders.get(symbol, [])
        if not orders:
            return []

        position = self._positions.get(symbol)
        if position is None:
            return []

        filled = []
        remaining = []

        for order in orders:
            if order.status != OrderStatus.NEW:
                continue

            triggered = False

            if order.order_type == OrderType.TAKE_PROFIT_MARKET:
                # TP triggers: LONG when price >= TP, SHORT when price <= TP
                if position.side == "LONG" and current_price >= order.stop_price:
                    triggered = True
                elif position.side == "SHORT" and current_price <= order.stop_price:
                    triggered = True

            elif order.order_type in (OrderType.STOP_MARKET, OrderType.STOP):
                # SL triggers: LONG when price <= SL, SHORT when price >= SL
                if position.side == "LONG" and current_price <= order.stop_price:
                    triggered = True
                elif position.side == "SHORT" and current_price >= order.stop_price:
                    triggered = True

            if triggered:
                fill_price = self._apply_slippage(
                    current_price, order.side == OrderSide.BUY
                )
                order.price = fill_price
                order.status = OrderStatus.FILLED
                order.filled_quantity = order.quantity
                order.timestamp = datetime.now(timezone.utc)
                filled.append(order)
                self._filled_orders.append(order)

                # Update PnL
                if position.side == "LONG":
                    pnl = (fill_price - position.entry_price) * order.quantity
                else:
                    pnl = (position.entry_price - fill_price) * order.quantity

                fee = self._calculate_fee(order.quantity, fill_price)
                self._total_fees += fee
                self._balance -= fee
                self._realized_pnl += pnl
                self._balance += pnl

                # Remove position
                del self._positions[symbol]
                self._cache[symbol] = (None, time.time())
            else:
                remaining.append(order)

        if filled:
            self._open_orders[symbol] = remaining

        return filled

    @property
    def realized_pnl(self) -> float:
        """Cumulative realized PnL."""
        return self._realized_pnl

    @property
    def total_fees(self) -> float:
        """Cumulative trading fees."""
        return self._total_fees

    @property
    def filled_orders(self) -> List[Order]:
        """History of all filled orders."""
        return list(self._filled_orders)
