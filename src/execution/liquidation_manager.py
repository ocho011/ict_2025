"""
Emergency position liquidation manager with fail-safe design.

Design Principles (Business Panel Recommendations):
- Taleb's Paranoia: Assume failures, design for antifragility
- Meadows' Systems Thinking: State machine with feedback loops
- Collins' Disciplined Execution: Systematic, methodical, auditable

Security Architecture:
- Layer 1: Configuration validation (LiquidationConfig)
- Layer 2: State machine (prevents re-entrant calls)
- Layer 3: API call safety (reduceOnly enforcement, timeout, retry)
- Layer 4: Audit trail (comprehensive logging with correlation IDs)
- Layer 5: Fail-safe (shutdown continues even if liquidation fails)
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from src.core.audit_logger import AuditLogger, AuditEventType
from src.utils.config import LiquidationConfig


class LiquidationState(Enum):
    """
    Liquidation state machine states.

    State Transitions:
        IDLE → IN_PROGRESS → {COMPLETED, PARTIAL, FAILED, SKIPPED}
                      ↓
                  (timeout/error)

    State Meanings:
        IDLE: Ready to execute liquidation
        IN_PROGRESS: Liquidation operation in progress (prevents re-entry)
        COMPLETED: All positions and orders successfully liquidated
        PARTIAL: Some positions/orders liquidated, some failed
        FAILED: Liquidation failed completely (but shutdown continues)
        SKIPPED: Liquidation skipped (emergency_liquidation=False)
    """

    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class LiquidationResult:
    """
    Result of a liquidation operation.

    Attributes:
        state: Final state after liquidation attempt
        positions_closed: Number of positions successfully closed
        positions_failed: Number of positions that failed to close
        orders_cancelled: Number of orders successfully cancelled
        orders_failed: Number of orders that failed to cancel
        total_duration_seconds: Total time taken for liquidation
        error_message: Error message if liquidation failed (None if success)
    """

    state: LiquidationState
    positions_closed: int = 0
    positions_failed: int = 0
    orders_cancelled: int = 0
    orders_failed: int = 0
    total_duration_seconds: float = 0.0
    error_message: Optional[str] = None

    def is_success(self) -> bool:
        """Check if liquidation was completely successful."""
        return self.state == LiquidationState.COMPLETED and self.positions_failed == 0 and self.orders_failed == 0

    def is_partial(self) -> bool:
        """Check if liquidation was partially successful."""
        return self.state == LiquidationState.PARTIAL or (
            (self.positions_closed > 0 or self.orders_cancelled > 0)
            and (self.positions_failed > 0 or self.orders_failed > 0)
        )

    def to_dict(self) -> dict:
        """Export result as dictionary for audit logging."""
        return {
            "state": self.state.value,
            "positions_closed": self.positions_closed,
            "positions_failed": self.positions_failed,
            "orders_cancelled": self.orders_cancelled,
            "orders_failed": self.orders_failed,
            "total_duration_seconds": round(self.total_duration_seconds, 3),
            "error_message": self.error_message,
        }


class LiquidationManager:
    """
    Emergency position liquidation manager with fail-safe design.

    Responsibilities:
    1. Coordinate emergency liquidation sequence (cancel orders → close positions)
    2. Enforce state machine to prevent re-entrant calls
    3. Apply retry logic with exponential backoff
    4. Comprehensive audit logging with correlation IDs
    5. Fail-safe guarantee: never block shutdown

    State Machine:
        IDLE → IN_PROGRESS → {COMPLETED, PARTIAL, FAILED, SKIPPED}

    Fail-Safe Guarantee:
        - Liquidation has timeout (default 5 seconds)
        - Liquidation errors are logged but do NOT raise exceptions
        - Shutdown ALWAYS continues regardless of liquidation outcome
        - Partial success is acceptable (logged for manual cleanup)
    """

    def __init__(
        self,
        order_manager,  # OrderExecutionManager instance
        audit_logger: Optional[AuditLogger] = None,
        config: Optional[LiquidationConfig] = None,
    ):
        """
        Initialize liquidation manager.

        Args:
            order_manager: OrderExecutionManager instance for API calls
            audit_logger: Optional AuditLogger instance for audit trail.
                         If None, uses singleton instance from AuditLogger.get_instance()
            config: LiquidationConfig instance with validated configuration
        """
        self.order_manager = order_manager
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.config = config
        self.logger = logging.getLogger(__name__)

        # State machine
        self._state = LiquidationState.IDLE
        self._state_lock = asyncio.Lock()  # Protect state transitions

        # Metrics
        self._last_execution_time: Optional[float] = None
        self._execution_count = 0

        # Log initialization
        self.logger.info(
            f"LiquidationManager initialized with config: {self.config}"
        )

    @property
    def state(self) -> LiquidationState:
        """Get current state (thread-safe read)."""
        return self._state

    async def execute_liquidation(self, symbols: List[str]) -> LiquidationResult:
        """
        Execute emergency liquidation with fail-safe design.

        Liquidation Sequence:
        1. State validation (prevent re-entry)
        2. Query open positions and orders
        3. Cancel all pending orders (parallel with retry)
        4. Close all open positions (parallel with retry)
        5. Audit logging with correlation ID
        6. State transition to final state

        Fail-Safe Guarantee:
        - Operation has timeout (config.timeout_seconds)
        - Errors are logged but do NOT raise exceptions
        - Partial success is acceptable
        - Shutdown ALWAYS continues

        Args:
            symbols: List of symbols to liquidate (e.g., ['BTCUSDT'])

        Returns:
            LiquidationResult: Detailed liquidation outcome

        Design Note:
        This method NEVER raises exceptions to external callers.
        All errors are captured in LiquidationResult.error_message.
        """
        start_time = time.perf_counter()

        # Generate correlation ID for audit trail
        correlation_id = f"liquidation_{int(time.time() * 1000)}"

        try:
            # State machine: IDLE → IN_PROGRESS
            async with self._state_lock:
                if self._state == LiquidationState.IN_PROGRESS:
                    self.logger.warning(
                        f"Liquidation already in progress (correlation_id={correlation_id})"
                    )
                    return LiquidationResult(
                        state=LiquidationState.FAILED,
                        error_message="Liquidation already in progress (re-entrant call blocked)",
                    )

                self._state = LiquidationState.IN_PROGRESS
                self.logger.info(
                    f"Starting emergency liquidation (correlation_id={correlation_id}, symbols={symbols})"
                )

            # Execute liquidation with timeout
            result = await asyncio.wait_for(
                self._execute_liquidation_internal(symbols, correlation_id),
                timeout=self.config.timeout_seconds,
            )

            # Update metrics
            self._last_execution_time = time.perf_counter() - start_time
            self._execution_count += 1
            result.total_duration_seconds = self._last_execution_time

            return result

        except asyncio.TimeoutError:
            duration = time.perf_counter() - start_time
            self.logger.error(
                f"Liquidation timeout after {duration:.2f}s "
                f"(limit={self.config.timeout_seconds}s, correlation_id={correlation_id})"
            )
            result = LiquidationResult(
                state=LiquidationState.FAILED,
                total_duration_seconds=duration,
                error_message=f"Timeout after {duration:.2f}s",
            )
            await self._audit_log_result(result, symbols, correlation_id)
            return result

        except Exception as e:
            duration = time.perf_counter() - start_time
            self.logger.exception(
                f"Unexpected error during liquidation (correlation_id={correlation_id}): {e}"
            )
            result = LiquidationResult(
                state=LiquidationState.FAILED,
                total_duration_seconds=duration,
                error_message=f"Unexpected error: {str(e)}",
            )
            await self._audit_log_result(result, symbols, correlation_id)
            return result

        finally:
            # State machine: IN_PROGRESS → final state
            async with self._state_lock:
                self._state = LiquidationState.IDLE
                self.logger.info(
                    f"Liquidation complete, state reset to IDLE (correlation_id={correlation_id})"
                )

    async def _execute_liquidation_internal(
        self, symbols: List[str], correlation_id: str
    ) -> LiquidationResult:
        """
        Internal liquidation execution (called within timeout wrapper).

        Strategy:
        1. Cancel orders first (prevent new fills)
        2. Close positions second (reduce capital exposure)
        3. Parallel execution where possible
        4. Retry failed operations with exponential backoff
        5. Comprehensive audit logging

        Args:
            symbols: List of symbols to liquidate
            correlation_id: Correlation ID for audit trail

        Returns:
            LiquidationResult: Detailed outcome
        """
        result = LiquidationResult(state=LiquidationState.IN_PROGRESS)

        # Check if liquidation is enabled
        if not self.config.emergency_liquidation:
            self.logger.info(
                f"Emergency liquidation DISABLED (correlation_id={correlation_id}). "
                "Skipping position closure."
            )
            result.state = LiquidationState.SKIPPED
            await self._audit_log_result(result, symbols, correlation_id)
            return result

        # Step 1: Cancel all pending orders (if enabled)
        if self.config.cancel_orders:
            orders_result = await self._cancel_all_orders(symbols, correlation_id)
            result.orders_cancelled = orders_result["cancelled"]
            result.orders_failed = orders_result["failed"]

        # Step 2: Close all open positions (if enabled)
        if self.config.close_positions:
            positions_result = await self._close_all_positions(symbols, correlation_id)
            result.positions_closed = positions_result["closed"]
            result.positions_failed = positions_result["failed"]

        # Determine final state
        total_operations = (
            result.positions_closed
            + result.positions_failed
            + result.orders_cancelled
            + result.orders_failed
        )

        if total_operations == 0:
            # No positions or orders found
            result.state = LiquidationState.COMPLETED
            self.logger.info(
                f"No positions or orders to liquidate (correlation_id={correlation_id})"
            )
        elif result.positions_failed == 0 and result.orders_failed == 0:
            # Complete success
            result.state = LiquidationState.COMPLETED
            self.logger.info(
                f"Liquidation completed successfully: "
                f"{result.positions_closed} positions closed, "
                f"{result.orders_cancelled} orders cancelled "
                f"(correlation_id={correlation_id})"
            )
        elif result.positions_closed > 0 or result.orders_cancelled > 0:
            # Partial success
            result.state = LiquidationState.PARTIAL
            result.error_message = (
                f"Partial liquidation: {result.positions_failed} positions failed, "
                f"{result.orders_failed} orders failed"
            )
            self.logger.warning(
                f"Partial liquidation: "
                f"{result.positions_closed}/{result.positions_closed + result.positions_failed} positions closed, "
                f"{result.orders_cancelled}/{result.orders_cancelled + result.orders_failed} orders cancelled "
                f"(correlation_id={correlation_id})"
            )
        else:
            # Complete failure
            result.state = LiquidationState.FAILED
            result.error_message = "All liquidation operations failed"
            self.logger.error(
                f"Liquidation failed completely (correlation_id={correlation_id})"
            )

        # Audit log final result
        await self._audit_log_result(result, symbols, correlation_id)

        return result

    async def _cancel_all_orders(
        self, symbols: List[str], correlation_id: str
    ) -> Dict[str, int]:
        """
        Cancel all pending orders for symbols with retry logic.

        Args:
            symbols: List of symbols
            correlation_id: Correlation ID for audit trail

        Returns:
            dict: {"cancelled": count, "failed": count}
        """
        self.logger.info(
            f"Cancelling orders for symbols={symbols} (correlation_id={correlation_id})"
        )

        cancelled_total = 0
        failed_total = 0

        # Cancel orders for each symbol with retry logic
        for symbol in symbols:
            for attempt in range(self.config.max_retries):
                try:
                    # Call OrderExecutionManager.cancel_all_orders()
                    cancelled_count = self.order_manager.cancel_all_orders(symbol)
                    cancelled_total += cancelled_count

                    # Audit log success
                    self.audit_logger.log_event(
                        event_type=AuditEventType.ORDER_CANCELLED,
                        operation="liquidation_cancel_orders",
                        data={
                            "correlation_id": correlation_id,
                            "symbol": symbol,
                            "cancelled": cancelled_count,
                            "attempt": attempt + 1,
                        },
                    )

                    self.logger.info(
                        f"Cancelled {cancelled_count} orders for {symbol} "
                        f"(attempt {attempt + 1}/{self.config.max_retries}, "
                        f"correlation_id={correlation_id})"
                    )

                    # Success - break retry loop
                    break

                except Exception as e:
                    # Log error
                    self.logger.error(
                        f"Failed to cancel orders for {symbol} (attempt {attempt + 1}/"
                        f"{self.config.max_retries}): {e}"
                    )

                    # Audit log retry attempt
                    self.audit_logger.log_event(
                        event_type=AuditEventType.API_ERROR,
                        operation="liquidation_cancel_orders_retry",
                        data={
                            "correlation_id": correlation_id,
                            "symbol": symbol,
                            "attempt": attempt + 1,
                            "max_retries": self.config.max_retries,
                            "error": str(e),
                        },
                    )

                    # Check if this was the last attempt
                    if attempt + 1 >= self.config.max_retries:
                        failed_total += 1
                        self.logger.error(
                            f"Max retries reached for cancelling orders {symbol} "
                            f"(correlation_id={correlation_id})"
                        )
                        break

                    # Exponential backoff: delay * (2 ^ attempt)
                    delay = self.config.retry_delay_seconds * (2 ** attempt)
                    self.logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)

        return {"cancelled": cancelled_total, "failed": failed_total}

    async def _close_all_positions(
        self, symbols: List[str], correlation_id: str
    ) -> Dict[str, int]:
        """
        Close all open positions for symbols using market orders with retry logic.

        Args:
            symbols: List of symbols
            correlation_id: Correlation ID for audit trail

        Returns:
            dict: {"closed": count, "failed": count}
        """
        self.logger.info(
            f"Closing positions for symbols={symbols} (correlation_id={correlation_id})"
        )

        closed_total = 0
        failed_total = 0

        # Step 1: Query all open positions for symbols
        try:
            positions = await self.order_manager.get_all_positions(symbols)

            if not positions:
                self.logger.info(
                    f"No open positions to close for symbols={symbols} "
                    f"(correlation_id={correlation_id})"
                )
                return {"closed": 0, "failed": 0}

            self.logger.info(
                f"Found {len(positions)} positions to close (correlation_id={correlation_id})"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to query positions: {e} (correlation_id={correlation_id})",
                exc_info=True,
            )
            # Cannot proceed without position data
            return {"closed": 0, "failed": len(symbols)}

        # Step 2: Close each position with retry logic
        for position in positions:
            symbol = position["symbol"]
            position_amt = float(position["positionAmt"])

            # Determine close side (opposite of position side)
            # positionAmt > 0 = LONG → close with SELL
            # positionAmt < 0 = SHORT → close with BUY
            close_side = "SELL" if position_amt > 0 else "BUY"
            abs_position_amt = abs(position_amt)

            # Validate position amount
            if abs_position_amt <= 0:
                self.logger.warning(
                    f"Invalid position amount for {symbol}: {position_amt}. Skipping."
                )
                failed_total += 1
                continue

            self.logger.info(
                f"Closing position: {symbol} {close_side} {abs_position_amt} "
                f"(entry={position['entryPrice']}, PnL={position['unrealizedProfit']}, "
                f"correlation_id={correlation_id})"
            )

            # Retry loop with exponential backoff
            position_closed = False
            for attempt in range(self.config.max_retries):
                try:
                    # Execute market close order with reduceOnly=True (enforced in execute_market_close)
                    result = await self.order_manager.execute_market_close(
                        symbol=symbol,
                        position_amt=abs_position_amt,
                        side=close_side,
                        reduce_only=True,  # SECURITY: Always True
                    )

                    if result["success"]:
                        closed_total += 1
                        position_closed = True

                        # Extract exit details for realized PnL calculation
                        exit_price = result.get("avg_price", 0.0)
                        executed_qty = result.get("executed_qty", abs_position_amt)
                        entry_price = float(position.get("entryPrice", 0))
                        position_side = "LONG" if position_amt > 0 else "SHORT"

                        # Calculate realized PnL
                        if position_side == "LONG":
                            realized_pnl = (exit_price - entry_price) * executed_qty
                        else:
                            realized_pnl = (entry_price - exit_price) * executed_qty

                        # Audit log: trade_closed event with full exit details
                        self.audit_logger.log_event(
                            event_type=AuditEventType.TRADE_CLOSED,
                            operation="liquidation_close_position",
                            symbol=symbol,
                            data={
                                "correlation_id": correlation_id,
                                "exit_price": exit_price,
                                "realized_pnl": realized_pnl,
                                "exit_reason": "emergency_liquidation",
                                "entry_price": entry_price,
                                "quantity": executed_qty,
                                "position_side": position_side,
                                "order_id": result.get("order_id"),
                                "attempt": attempt + 1,
                            },
                        )

                        self.logger.info(
                            f"Position closed: {symbol} order_id={result.get('order_id')} "
                            f"exit_price={exit_price} realized_pnl={realized_pnl:.4f} "
                            f"(attempt {attempt + 1}/{self.config.max_retries}, "
                            f"correlation_id={correlation_id})"
                        )

                        # Success - break retry loop
                        break

                    else:
                        # Order rejected but not an exception
                        self.logger.error(
                            f"Position close rejected for {symbol}: {result.get('error')} "
                            f"(attempt {attempt + 1}/{self.config.max_retries})"
                        )

                        # Audit log rejection
                        self.audit_logger.log_event(
                            event_type=AuditEventType.ORDER_REJECTED,
                            operation="liquidation_close_position",
                            data={
                                "correlation_id": correlation_id,
                                "symbol": symbol,
                                "error": result.get("error"),
                                "attempt": attempt + 1,
                            },
                        )

                        # Check if this was the last attempt
                        if attempt + 1 >= self.config.max_retries:
                            failed_total += 1
                            self.logger.error(
                                f"Max retries reached for closing position {symbol} "
                                f"(correlation_id={correlation_id})"
                            )
                            break

                        # Exponential backoff
                        delay = self.config.retry_delay_seconds * (2 ** attempt)
                        self.logger.info(f"Retrying in {delay}s...")
                        await asyncio.sleep(delay)

                except Exception as e:
                    # Unexpected exception
                    self.logger.error(
                        f"Failed to close position {symbol} (attempt {attempt + 1}/"
                        f"{self.config.max_retries}): {e}",
                        exc_info=True,
                    )

                    # Audit log retry attempt
                    self.audit_logger.log_event(
                        event_type=AuditEventType.API_ERROR,
                        operation="liquidation_close_position_retry",
                        data={
                            "correlation_id": correlation_id,
                            "symbol": symbol,
                            "attempt": attempt + 1,
                            "max_retries": self.config.max_retries,
                            "error": str(e),
                        },
                    )

                    # Check if this was the last attempt
                    if attempt + 1 >= self.config.max_retries:
                        failed_total += 1
                        self.logger.error(
                            f"Max retries reached for closing position {symbol} "
                            f"(correlation_id={correlation_id})"
                        )
                        break

                    # Exponential backoff
                    delay = self.config.retry_delay_seconds * (2 ** attempt)
                    self.logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)

            # Log final status for this position
            if not position_closed and failed_total == 0:
                # This should not happen, but handle edge case
                failed_total += 1

        return {"closed": closed_total, "failed": failed_total}

    async def _audit_log_result(
        self, result: LiquidationResult, symbols: List[str], correlation_id: str
    ) -> None:
        """
        Log liquidation result to audit trail.

        Args:
            result: LiquidationResult to log
            symbols: Symbols that were liquidated
            correlation_id: Correlation ID for this operation
        """
        self.audit_logger.log_event(
            event_type=AuditEventType.LIQUIDATION_COMPLETE,
            operation="emergency_liquidation",
            data={
                "correlation_id": correlation_id,
                "symbols": symbols,
                "result": result.to_dict(),
                "config": self.config.to_dict(),
            },
        )

    def get_metrics(self) -> dict:
        """
        Get liquidation metrics for monitoring.

        Returns:
            dict: Metrics including execution count, last execution time, current state
        """
        return {
            "execution_count": self._execution_count,
            "last_execution_time_seconds": self._last_execution_time,
            "current_state": self._state.value,
            "config": self.config.to_dict(),
        }
