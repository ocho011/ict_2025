"""TradeCoordinator: Signal-to-order execution coordination.

Extracted from TradingEngine to separate trade execution logic from
engine orchestration (Issue #110 Phase 2).

Responsibilities:
- Signal validation via RiskGuard
- Entry order execution with TP/SL
- Exit order execution with reduce_only
- Order fill tracking and position entry data management
- Position closure logging with PnL calculation
"""

import logging
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.models.position import Position
    from src.core.position_cache_manager import PositionCacheManager

from src.models.order import Order
from src.models.position import PositionEntryData
from src.models.signal import Signal
from src.models.event import Event, EventType


class TradeCoordinator:
    """
    Coordinates signal-to-order execution flow.

    Extracted from TradingEngine to separate concerns:
    - Signal → Risk validation → Order execution
    - Order fill tracking and position entry data
    - Position closure with PnL and duration calculation

    Dependencies:
    - OrderGateway: For order placement and cancellation
    - RiskGuard: For signal validation and position sizing
    - ConfigManager: For trading parameters (leverage)
    - PositionCacheManager: For cache invalidation after execution
    - AuditLogger: For compliance logging
    """

    def __init__(
        self,
        order_gateway,
        risk_guard,
        config_manager,
        audit_logger: "AuditLogger",
        position_cache_manager: "PositionCacheManager",
    ):
        self._order_gateway = order_gateway
        self._risk_guard = risk_guard
        self._config_manager = config_manager
        self._audit_logger = audit_logger
        self._position_cache_manager = position_cache_manager
        self._position_entry_data: Dict[str, PositionEntryData] = {}
        self.logger = logging.getLogger(__name__)

    async def on_signal_generated(self, event: Event) -> None:
        """
        Handle generated signal - validate and execute order.

        This is the critical trading logic that:
        1. Validates signal with RiskGuard
        2. For entry signals: Calculates position size and executes with TP/SL
        3. For exit signals: Uses position quantity and executes with reduce_only

        Args:
            event: Event containing Signal data
        """
        # Step 1: Extract signal from event data
        signal: Signal = event.data

        self.logger.info(
            f"Processing signal: {signal.signal_type.value} for {signal.symbol}"
        )

        try:
            # Step 2: Get current position via PositionCacheManager (fresh query for execution)
            current_position = self._position_cache_manager.get_fresh(signal.symbol)

            # Step 3: Validate signal with RiskGuard
            is_valid = self._risk_guard.validate_risk(signal, current_position)

            if not is_valid:
                self.logger.warning(
                    f"Signal rejected by risk validation: {signal.signal_type.value}"
                )

                # Audit log: risk rejection
                try:
                    from src.core.audit_logger import AuditEventType

                    self._audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="signal_execution",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "entry_price": signal.entry_price,
                        },
                        error={"reason": "risk_validation_failed"},
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")

                return

            # Step 4: Handle exit vs entry signals differently (Issue #25)
            if signal.is_exit_signal:
                # Exit signal: use position quantity and reduce_only
                await self.execute_exit_signal(signal, current_position)
                return

            # Entry signal: calculate position size and execute with TP/SL
            # Step 5: Get account balance
            account_balance = self._order_gateway.get_account_balance()

            if account_balance <= 0:
                self.logger.error(
                    f"Invalid account balance: {account_balance}, cannot execute signal"
                )
                return

            # Step 6: Calculate position size using RiskGuard
            quantity = self._risk_guard.calculate_position_size(
                account_balance=account_balance,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                leverage=self._config_manager.trading_config.leverage,
                symbol_info=None,  # OrderGateway will handle rounding internally
            )

            # Step 7: Execute signal via OrderGateway
            # Returns (entry_order, [tp_order, sl_order])
            entry_order, tpsl_orders = self._order_gateway.execute_signal(
                signal=signal, quantity=quantity
            )

            # Invalidate position cache after order execution
            self._position_cache_manager.invalidate(signal.symbol)

            # Step 7: Log successful trade execution
            self.logger.info(
                f"✅ Trade executed successfully: "
                f"Order ID={entry_order.order_id}, "
                f"Quantity={entry_order.quantity}, "
                f"TP/SL={len(tpsl_orders)}/2 orders"
            )

            # Audit log: trade executed successfully
            try:
                from src.core.audit_logger import AuditEventType

                self._audit_logger.log_event(
                    event_type=AuditEventType.TRADE_EXECUTED,
                    operation="execute_trade",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                        "quantity": quantity,
                        "leverage": self._config_manager.trading_config.leverage,
                    },
                    response={
                        "entry_order_id": entry_order.order_id,
                        "tpsl_count": len(tpsl_orders),
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            # Note: ORDER_FILLED event will be published by PrivateUserStreamer
            # when WebSocket confirms the fill (Issue #97 - removed optimistic fill)

        except Exception as e:
            # Step 9: Catch and log execution errors without crashing
            self.logger.error(
                f"Failed to execute signal for {signal.symbol}: {e}", exc_info=True
            )

            # Audit log: trade execution failed
            try:
                from src.core.audit_logger import AuditEventType

                self._audit_logger.log_event(
                    event_type=AuditEventType.TRADE_EXECUTION_FAILED,
                    operation="execute_trade",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                    },
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass  # Exception context already logged

            # Don't re-raise - system should continue running

    async def execute_exit_signal(self, signal: Signal, position: "Position") -> None:
        """
        Execute an exit signal to close a position.

        Uses position quantity and executes with reduce_only to prevent
        accidentally opening a new position in the opposite direction.

        Args:
            signal: Exit signal (CLOSE_LONG or CLOSE_SHORT)
            position: Current position to close

        Process:
            1. Cancel any existing TP/SL orders
            2. Execute market order with reduce_only=True
            3. Invalidate position cache
            4. Log execution and audit trail
        """
        from src.models.signal import SignalType

        try:
            self.logger.info(
                f"Executing exit signal: {signal.signal_type.value} for {signal.symbol} "
                f"(qty: {position.quantity}, reason: {signal.exit_reason})"
            )

            # Step 1: Cancel any existing TP/SL orders first
            try:
                cancelled_count = self._order_gateway.cancel_all_orders(signal.symbol)
                if cancelled_count > 0:
                    self.logger.info(
                        f"Cancelled {cancelled_count} existing orders before exit"
                    )
            except Exception as e:
                self.logger.warning(f"Failed to cancel existing orders: {e}")

            # Step 2: Execute close order using position quantity
            # Determine side based on signal type (SELL to close LONG, BUY to close SHORT)
            close_side = (
                "SELL" if signal.signal_type == SignalType.CLOSE_LONG else "BUY"
            )

            # Execute close order with reduce_only via async method
            result = await self._order_gateway.execute_market_close(
                symbol=signal.symbol,
                position_amt=position.quantity,
                side=close_side,
                reduce_only=True,
            )

            # Step 3: Invalidate position cache
            self._position_cache_manager.invalidate(signal.symbol)

            # Step 4: Check result and log
            if result.get("success"):
                order_id = result.get("order_id")
                exit_price = result.get("avg_price", 0.0)
                executed_qty = result.get("executed_qty", position.quantity)

                # Calculate realized PnL
                # LONG: (exit_price - entry_price) * quantity
                # SHORT: (entry_price - exit_price) * quantity
                if position.side == "LONG":
                    realized_pnl = (exit_price - position.entry_price) * executed_qty
                else:
                    realized_pnl = (position.entry_price - exit_price) * executed_qty

                # Calculate duration if entry_time is available
                duration_seconds = None
                if position.entry_time:
                    from datetime import datetime, timezone

                    duration = (
                        datetime.now(timezone.utc)
                        - position.entry_time.replace(tzinfo=timezone.utc)
                        if position.entry_time.tzinfo is None
                        else datetime.now(timezone.utc) - position.entry_time
                    )
                    duration_seconds = duration.total_seconds()

                self.logger.info(
                    f"✅ Position closed successfully: "
                    f"Order ID={order_id}, "
                    f"Quantity={executed_qty}, "
                    f"Exit price={exit_price}, "
                    f"Realized PnL={realized_pnl:.4f}, "
                    f"Exit reason={signal.exit_reason}"
                )

                # Audit log: trade_closed event with full exit details
                try:
                    from src.core.audit_logger import AuditEventType

                    self._audit_logger.log_event(
                        event_type=AuditEventType.TRADE_CLOSED,
                        operation="execute_exit",
                        symbol=signal.symbol,
                        data={
                            "exit_price": exit_price,
                            "realized_pnl": realized_pnl,
                            "exit_reason": signal.exit_reason,
                            "duration_seconds": duration_seconds,
                            "entry_price": position.entry_price,
                            "quantity": executed_qty,
                            "position_side": position.side,
                            "leverage": position.leverage,
                            "signal_type": signal.signal_type.value,
                        },
                        response={
                            "close_order_id": order_id,
                            "status": result.get("status"),
                        },
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")
            else:
                error_msg = result.get("error", "Unknown error")
                self.logger.error(
                    f"Failed to close position for {signal.symbol}: {error_msg}"
                )

                # Audit log: exit execution failed
                try:
                    from src.core.audit_logger import AuditEventType

                    self._audit_logger.log_event(
                        event_type=AuditEventType.TRADE_EXECUTION_FAILED,
                        operation="execute_exit",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "exit_price": signal.entry_price,
                            "exit_reason": signal.exit_reason,
                        },
                        error={"reason": error_msg},
                    )
                except Exception:
                    pass

        except Exception as e:
            self.logger.error(
                f"Failed to execute exit signal for {signal.symbol}: {e}", exc_info=True
            )

            # Audit log: exit execution failed
            try:
                from src.core.audit_logger import AuditEventType

                self._audit_logger.log_event(
                    event_type=AuditEventType.TRADE_EXECUTION_FAILED,
                    operation="execute_exit",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "exit_price": signal.entry_price,
                        "exit_reason": signal.exit_reason,
                    },
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass

    async def on_order_filled(self, event: Event) -> None:
        """
        Handle order fill notification (Issue #9: Enhanced with orphan order prevention).

        Logs order fills for tracking and monitoring. When a TP/SL order is filled,
        automatically cancels any remaining orders for the symbol to prevent orphaned orders.

        Args:
            event: Event containing Order data
        """
        # Step 1: Extract order from event data
        order: Order = event.data

        # Step 2: Log order fill confirmation
        self.logger.info(
            f"Order filled: ID={order.order_id}, "
            f"Symbol={order.symbol}, "
            f"Side={order.side.value}, "
            f"Type={order.order_type.value}, "
            f"Quantity={order.quantity}, "
            f"Price={order.price}"
        )

        # Audit log: order filled confirmation
        try:
            from src.core.audit_logger import AuditEventType

            self._audit_logger.log_event(
                event_type=AuditEventType.ORDER_PLACED,  # Reuse existing event type
                operation="order_confirmation",
                symbol=order.symbol,
                response={
                    "order_id": order.order_id,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "price": order.price,
                    "order_type": order.order_type.value,
                },
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        # Track position entry data for MARKET/LIMIT fills (Issue #96)
        # Entry data is used later for PnL and duration calculation when position closes
        from src.models.order import OrderType as OT
        if order.order_type in (OT.MARKET, OT.LIMIT):
            from datetime import datetime, timezone
            position_side = "LONG" if order.side.value == "BUY" else "SHORT"
            self._position_entry_data[order.symbol] = PositionEntryData(
                entry_price=order.price,
                entry_time=datetime.now(timezone.utc),
                quantity=order.quantity,
                side=position_side,
            )
            self.logger.info(
                f"Tracking position entry: {order.symbol} {position_side} "
                f"price={order.price}, qty={order.quantity}"
            )

        # Step 3: Handle TP/SL fills - cancel remaining orders (Issue #9)
        from src.models.order import OrderType

        if order.order_type in (
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.STOP,
            OrderType.TAKE_PROFIT,
            OrderType.TRAILING_STOP_MARKET,
        ):
            # TP or SL was hit - position is closed
            # Cancel any remaining orders (the other TP/SL) to prevent orphaned orders
            self.logger.info(
                f"{order.order_type.value} filled for {order.symbol} - "
                f"cancelling remaining orders to prevent orphans"
            )

            try:
                cancelled_count = self._order_gateway.cancel_all_orders(order.symbol)
                if cancelled_count > 0:
                    self.logger.info(
                        f"TP/SL hit: cancelled {cancelled_count} remaining orders "
                        f"for {order.symbol}"
                    )
                else:
                    self.logger.info(
                        f"TP/SL hit: no remaining orders to cancel for {order.symbol}"
                    )
            except Exception as e:
                # Log error but don't crash - orphaned orders are a data issue, not a critical failure
                self.logger.error(
                    f"Failed to cancel remaining orders after TP/SL fill: {e}. "
                    f"Manual cleanup may be required for {order.symbol}."
                )

            # Log position closure to audit trail (Issue #96 - moved from PrivateUserStreamer)
            self.log_position_closure(order)

    def log_position_closure(self, order: Order) -> None:
        """
        Log position closure to audit trail with PnL and duration.

        Moved from PrivateUserStreamer for proper responsibility separation (Issue #96).
        TradingEngine owns business logic; streamer is pure data relay.

        Args:
            order: The filled TP/SL order that closed the position
        """
        from src.core.audit_logger import AuditEventType
        from datetime import datetime, timezone

        # Map order type to close reason
        close_reason_map = {
            "TAKE_PROFIT_MARKET": "TAKE_PROFIT",
            "TAKE_PROFIT": "TAKE_PROFIT",
            "STOP_MARKET": "STOP_LOSS",
            "STOP": "STOP_LOSS",
            "TRAILING_STOP_MARKET": "TRAILING_STOP",
        }
        close_reason = close_reason_map.get(order.order_type.value, "UNKNOWN")

        # Build closure data
        closure_data = {
            "close_reason": close_reason,
            "exit_price": order.price,
            "exit_quantity": order.quantity,
            "exit_side": order.side.value,
            "order_id": order.order_id,
            "order_type": order.order_type.value,
        }

        # Add entry data if available (for PnL and duration)
        entry_data = self._position_entry_data.pop(order.symbol, None)
        if entry_data:
            closure_data["entry_price"] = entry_data.entry_price
            closure_data["position_side"] = entry_data.side

            # Calculate holding duration
            held_duration = datetime.now(timezone.utc) - entry_data.entry_time
            closure_data["held_duration_seconds"] = held_duration.total_seconds()

            # Calculate realized PnL
            # LONG: profit when exit > entry, SHORT: profit when entry > exit
            if entry_data.side == "LONG":
                realized_pnl = (order.price - entry_data.entry_price) * order.quantity
            else:  # SHORT
                realized_pnl = (entry_data.entry_price - order.price) * order.quantity
            closure_data["realized_pnl"] = realized_pnl

            self.logger.debug(f"Cleaned up position entry data for {order.symbol}")
        else:
            self.logger.warning(
                f"No entry data found for {order.symbol}, PnL and duration unavailable"
            )

        # Log to audit trail
        try:
            self._audit_logger.log_event(
                event_type=AuditEventType.POSITION_CLOSED,
                operation="tp_sl_order_filled",
                symbol=order.symbol,
                data=closure_data,
            )
            self.logger.info(
                f"Position closed via {close_reason}: {order.symbol} "
                f"exit_price={order.price}, qty={order.quantity}"
            )
        except Exception as e:
            self.logger.error(f"Failed to log position closure: {e}")

    async def on_order_partially_filled(self, event: Event) -> None:
        """
        Handle partial fill notification (Issue #97).

        Tracks partial fills for position size adjustments. Entry orders with partial
        fills may need TP/SL quantity adjustments. Exit orders with partial fills
        indicate the position footprint has decreased.

        Args:
            event: Event containing Order data with filled_quantity
        """
        order: Order = event.data

        self.logger.debug(
            f"Order partially filled: ID={order.order_id}, "
            f"Symbol={order.symbol}, "
            f"Type={order.order_type.value}, "
            f"Filled={order.filled_quantity}/{order.quantity}"
        )

        # Audit log: partial fill
        try:
            from src.core.audit_logger import AuditEventType

            self._audit_logger.log_event(
                event_type=AuditEventType.ORDER_PLACED,  # Reuse existing event type
                operation="partial_fill",
                symbol=order.symbol,
                response={
                    "order_id": order.order_id,
                    "side": order.side.value,
                    "filled_quantity": order.filled_quantity,
                    "total_quantity": order.quantity,
                    "fill_ratio": order.filled_quantity / order.quantity if order.quantity else 0,
                    "order_type": order.order_type.value,
                },
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        # Track partial entry fills for position tracking (Issue #97)
        # When entry order is partially filled, update position entry data
        from src.models.order import OrderType as OT
        if order.order_type in (OT.MARKET, OT.LIMIT):
            from datetime import datetime, timezone
            position_side = "LONG" if order.side.value == "BUY" else "SHORT"

            # Update or create position entry data with partial fill info
            existing = self._position_entry_data.get(order.symbol)
            if existing:
                # Update existing entry with new filled quantity
                self._position_entry_data[order.symbol] = PositionEntryData(
                    entry_price=order.price,  # Use average fill price
                    entry_time=existing.entry_time,  # Keep original entry time
                    quantity=order.filled_quantity,  # Update to actual filled qty
                    side=position_side,
                )
            else:
                # First partial fill - create new entry
                self._position_entry_data[order.symbol] = PositionEntryData(
                    entry_price=order.price,
                    entry_time=datetime.now(timezone.utc),
                    quantity=order.filled_quantity,
                    side=position_side,
                )

            self.logger.debug(
                f"Updated position entry (partial): {order.symbol} {position_side} "
                f"price={order.price}, filled_qty={order.filled_quantity}"
            )
