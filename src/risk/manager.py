"""
Risk management and position sizing
"""

from typing import TYPE_CHECKING, Optional

from src.models.position import Position
from src.models.signal import Signal

if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger


class RiskManager:
    """
    Manages risk and calculates position sizes
    """

    def __init__(self, config: dict, audit_logger: "AuditLogger"):
        """
        Initialize RiskManager with configuration.

        Args:
            config: Risk configuration dictionary with keys:
                - max_risk_per_trade: float (e.g., 0.01 for 1%)
                - max_leverage: int (e.g., 20)
                - default_leverage: int (e.g., 10)
                - max_position_size_percent: float (e.g., 0.1 for 10%)
            audit_logger: AuditLogger instance for structured logging
        """
        self.max_risk_per_trade = config.get("max_risk_per_trade", 0.01)
        self.max_leverage = config.get("max_leverage", 20)
        self.default_leverage = config.get("default_leverage", 10)
        self.max_position_size_percent = config.get("max_position_size_percent", 0.1)

        # Setup logging
        import logging

        self.logger = logging.getLogger(__name__)

        # Inject audit logger
        self.audit_logger = audit_logger

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        leverage: int,
        symbol_info: Optional[dict] = None,
    ) -> float:
        """
        Calculate position size based on risk management rules.

        Formula:
            Risk Amount = Account Balance × Max Risk Per Trade
            SL Distance % = |Entry - SL| / Entry
            Position Value = Risk Amount / SL Distance %
            Quantity = Position Value / Entry Price

        Args:
            account_balance: Total USDT balance
            entry_price: Intended entry price
            stop_loss_price: Stop loss price level
            leverage: Leverage multiplier (1-125)
            symbol_info: Optional exchange symbol specs for rounding

        Returns:
            Position size in base asset units (e.g., BTC for BTCUSDT)

        Raises:
            ValueError: Invalid inputs (negative values, zero prices)

        Example:
            >>> manager = RiskManager({'max_risk_per_trade': 0.01})
            >>> size = manager.calculate_position_size(
            ...     account_balance=10000,
            ...     entry_price=50000,
            ...     stop_loss_price=49000,
            ...     leverage=10
            ... )
            >>> print(f"Position size: {size} BTC")
            Position size: 0.1 BTC
        """
        # Step 1: Input validation
        if account_balance <= 0:
            raise ValueError(f"Account balance must be > 0, got {account_balance}")
        if entry_price <= 0:
            raise ValueError(f"Entry price must be > 0, got {entry_price}")
        if stop_loss_price <= 0:
            raise ValueError(f"Stop loss price must be > 0, got {stop_loss_price}")
        if leverage < 1 or leverage > self.max_leverage:
            raise ValueError(f"Leverage must be between 1 and {self.max_leverage}, got {leverage}")

        # Step 2: Calculate SL distance as percentage
        sl_distance_percent = abs(entry_price - stop_loss_price) / entry_price

        # Step 3: Handle zero SL edge case
        if sl_distance_percent == 0:
            self.logger.warning(
                "Zero SL distance detected. Using minimum 0.1% to prevent division by zero."
            )
            sl_distance_percent = 0.001  # 0.1% minimum

        # Step 4: Calculate risk amount in USDT
        risk_amount = account_balance * self.max_risk_per_trade

        # Step 5: Calculate position value and quantity
        position_value = risk_amount / sl_distance_percent
        quantity = position_value / entry_price

        # Step 6: Calculate maximum position size
        max_position_value = account_balance * self.max_position_size_percent * leverage
        max_quantity = max_position_value / entry_price

        # Step 7: Apply position size limit
        if quantity > max_quantity:
            original_quantity = quantity  # Store for audit logging
            self.logger.warning(
                f"Position size {quantity:.4f} exceeds maximum {max_quantity:.4f} "
                f"({self.max_position_size_percent:.1%} of account with {leverage}x leverage), "
                f"capping to {max_quantity:.4f}"
            )
            quantity = max_quantity

            # Audit log: position size capped
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.POSITION_SIZE_CAPPED,
                    operation="calculate_position_size",
                    symbol=symbol_info.get("symbol") if symbol_info else None,
                    additional_data={
                        "requested_quantity": original_quantity,
                        "capped_quantity": max_quantity,
                        "max_position_percent": self.max_position_size_percent,
                        "leverage": leverage,
                        "account_balance": account_balance,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

        # Step 8: Round to symbol specifications
        if symbol_info is not None:
            quantity = self._round_to_lot_size(quantity, symbol_info)
        else:
            # Default rounding for backward compatibility
            quantity = round(quantity, 3)

        # Step 9: Log final quantity
        self.logger.info(
            f"Final position size: {quantity} "
            f"(risk={risk_amount:.2f} USDT, "
            f"SL distance={sl_distance_percent:.2%}, "
            f"max_allowed={max_quantity:.4f})"
        )

        # Audit log: position size calculated
        try:
            from src.core.audit_logger import AuditEventType

            self.audit_logger.log_event(
                event_type=AuditEventType.POSITION_SIZE_CALCULATED,
                operation="calculate_position_size",
                symbol=symbol_info.get("symbol") if symbol_info else None,
                additional_data={
                    "account_balance": account_balance,
                    "entry_price": entry_price,
                    "stop_loss_price": stop_loss_price,
                    "leverage": leverage,
                    "risk_amount": risk_amount,
                    "sl_distance_percent": sl_distance_percent,
                    "position_value": position_value,
                    "final_quantity": quantity,
                },
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        return quantity

    def validate_risk(self, signal: Signal, position: Optional[Position]) -> bool:
        """
        Validate if signal meets risk requirements

        Args:
            signal: Signal to validate
            position: Current position if exists

        Returns:
            True if risk is acceptable
        """
        # Import SignalType enum
        from src.models.signal import SignalType

        # Handle EXIT signals: require existing position with matching side
        if signal.signal_type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            return self._validate_exit_signal(signal, position)

        # Handle ENTRY signals: require no existing position
        # Check for existing position conflict
        if position is not None:
            self.logger.warning(
                f"Signal rejected: existing position for {signal.symbol} "
                f"(side: {position.side}, entry: {position.entry_price})"
            )

            # Audit log: risk rejection due to existing position
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.RISK_REJECTION,
                    operation="validate_risk",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                    },
                    error={
                        "reason": "existing_position",
                        "position_side": position.side,
                        "position_entry": position.entry_price,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return False

        # Validate LONG_ENTRY signals
        if signal.signal_type == SignalType.LONG_ENTRY:
            if signal.take_profit <= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: LONG TP ({signal.take_profit}) must be > "
                    f"entry ({signal.entry_price})"
                )

                # Audit log: risk rejection due to invalid LONG TP
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="validate_risk",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "entry_price": signal.entry_price,
                            "take_profit": signal.take_profit,
                            "stop_loss": signal.stop_loss,
                        },
                        error={"reason": "invalid_tp_sl_levels", "validation_failed": "LONG_TP"},
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")

                return False
            if signal.stop_loss >= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: LONG SL ({signal.stop_loss}) must be < "
                    f"entry ({signal.entry_price})"
                )

                # Audit log: risk rejection due to invalid LONG SL
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="validate_risk",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "entry_price": signal.entry_price,
                            "take_profit": signal.take_profit,
                            "stop_loss": signal.stop_loss,
                        },
                        error={"reason": "invalid_tp_sl_levels", "validation_failed": "LONG_SL"},
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")

                return False

        # Validate SHORT_ENTRY signals
        elif signal.signal_type == SignalType.SHORT_ENTRY:
            if signal.take_profit >= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: SHORT TP ({signal.take_profit}) must be < "
                    f"entry ({signal.entry_price})"
                )

                # Audit log: risk rejection due to invalid SHORT TP
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="validate_risk",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "entry_price": signal.entry_price,
                            "take_profit": signal.take_profit,
                            "stop_loss": signal.stop_loss,
                        },
                        error={"reason": "invalid_tp_sl_levels", "validation_failed": "SHORT_TP"},
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")

                return False
            if signal.stop_loss <= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: SHORT SL ({signal.stop_loss}) must be > "
                    f"entry ({signal.entry_price})"
                )

                # Audit log: risk rejection due to invalid SHORT SL
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="validate_risk",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "entry_price": signal.entry_price,
                            "take_profit": signal.take_profit,
                            "stop_loss": signal.stop_loss,
                        },
                        error={"reason": "invalid_tp_sl_levels", "validation_failed": "SHORT_SL"},
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")

                return False

        # All validations passed
        # Audit log: risk validation passed
        try:
            from src.core.audit_logger import AuditEventType

            self.audit_logger.log_event(
                event_type=AuditEventType.RISK_VALIDATION,
                operation="validate_risk",
                symbol=signal.symbol,
                order_data={
                    "signal_type": signal.signal_type.value,
                    "entry_price": signal.entry_price,
                    "take_profit": signal.take_profit,
                    "stop_loss": signal.stop_loss,
                },
                additional_data={"validation_passed": True},
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        return True

    def _validate_exit_signal(self, signal: Signal, position: Optional[Position]) -> bool:
        """
        Validate exit signal against current position.

        Exit signals (CLOSE_LONG, CLOSE_SHORT) require:
        1. An existing position must exist
        2. Position side must match the signal type:
           - CLOSE_LONG requires a LONG position
           - CLOSE_SHORT requires a SHORT position

        Args:
            signal: Exit signal to validate
            position: Current position (or None if no position)

        Returns:
            True if exit signal is valid, False otherwise
        """
        from src.models.signal import SignalType

        # Exit signal requires an existing position
        if position is None:
            self.logger.warning(
                f"Exit signal rejected: no position exists for {signal.symbol}"
            )

            # Audit log: exit rejection due to no position
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.RISK_REJECTION,
                    operation="validate_exit_signal",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                        "exit_reason": signal.exit_reason,
                    },
                    error={"reason": "no_position_to_exit"},
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return False

        # Validate position side matches signal type
        expected_side = "LONG" if signal.signal_type == SignalType.CLOSE_LONG else "SHORT"
        if position.side != expected_side:
            self.logger.warning(
                f"Exit signal rejected: {signal.signal_type.value} requires {expected_side} position, "
                f"but found {position.side} position for {signal.symbol}"
            )

            # Audit log: exit rejection due to side mismatch
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.RISK_REJECTION,
                    operation="validate_exit_signal",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                        "exit_reason": signal.exit_reason,
                    },
                    error={
                        "reason": "position_side_mismatch",
                        "expected_side": expected_side,
                        "actual_side": position.side,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return False

        # Exit signal valid
        self.logger.info(
            f"Exit signal validated: {signal.signal_type.value} for {signal.symbol} "
            f"(position: {position.side} @ {position.entry_price}, qty: {position.quantity})"
        )

        # Audit log: exit validation passed
        try:
            from src.core.audit_logger import AuditEventType

            self.audit_logger.log_event(
                event_type=AuditEventType.RISK_VALIDATION,
                operation="validate_exit_signal",
                symbol=signal.symbol,
                order_data={
                    "signal_type": signal.signal_type.value,
                    "entry_price": signal.entry_price,
                    "exit_reason": signal.exit_reason,
                },
                additional_data={
                    "validation_passed": True,
                    "position_side": position.side,
                    "position_quantity": position.quantity,
                },
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        return True

    def _round_to_lot_size(self, quantity: float, symbol_info: Optional[dict] = None) -> float:
        """
        Round quantity to Binance lot size and precision specifications.

        Applies two-stage rounding:
        1. Floor to nearest lot size (stepSize) multiple
        2. Round to required decimal precision

        Args:
            quantity: Raw calculated position size
            symbol_info: Optional dict with 'lot_size' and 'quantity_precision'

        Returns:
            Binance-compliant rounded quantity

        Raises:
            None - Uses safe defaults if symbol_info missing

        Example:
            >>> manager = RiskManager({'max_risk_per_trade': 0.01})
            >>> manager._round_to_lot_size(1.2345, {'lot_size': 0.001, 'quantity_precision': 3})
            1.234

            >>> manager._round_to_lot_size(0.0567, {'lot_size': 0.01, 'quantity_precision': 2})
            0.05
        """
        # Step 1: Extract specs with defaults (BTCUSDT as reference)
        if symbol_info is None:
            symbol_info = {}

        lot_size = symbol_info.get("lot_size", 0.001)
        quantity_precision = symbol_info.get("quantity_precision", 3)

        # Step 2: Floor to lot size (ensures quantity is multiple of stepSize)
        floored = quantity - (quantity % lot_size)

        # Step 3: Round to precision (ensures correct decimal places)
        rounded = round(floored, quantity_precision)

        # Step 4: Log operation (debug level for troubleshooting)
        self.logger.debug(
            f"Quantity rounding: {quantity:.6f} → {rounded} "
            f"(lot_size={lot_size}, precision={quantity_precision})"
        )

        return rounded
