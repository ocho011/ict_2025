"""
Risk management and position sizing
"""

from typing import Optional
from src.models.signal import Signal
from src.models.position import Position


class RiskManager:
    """
    Manages risk and calculates position sizes
    """

    def __init__(self, config: dict):
        """
        Initialize RiskManager with configuration.

        Args:
            config: Risk configuration dictionary with keys:
                - max_risk_per_trade: float (e.g., 0.01 for 1%)
                - max_leverage: int (e.g., 20)
                - default_leverage: int (e.g., 10)
                - max_position_size_percent: float (e.g., 0.1 for 10%)
        """
        self.max_risk_per_trade = config.get('max_risk_per_trade', 0.01)
        self.max_leverage = config.get('max_leverage', 20)
        self.default_leverage = config.get('default_leverage', 10)
        self.max_position_size_percent = config.get('max_position_size_percent', 0.1)

        # Setup logging
        import logging
        self.logger = logging.getLogger(__name__)

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        leverage: int,
        symbol_info: Optional[dict] = None
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
            raise ValueError(
                f"Leverage must be between 1 and {self.max_leverage}, got {leverage}"
            )

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
            self.logger.warning(
                f"Position size {quantity:.4f} exceeds maximum {max_quantity:.4f} "
                f"({self.max_position_size_percent:.1%} of account with {leverage}x leverage), "
                f"capping to {max_quantity:.4f}"
            )
            quantity = max_quantity

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

        # Check for existing position conflict
        if position is not None:
            self.logger.warning(
                f"Signal rejected: existing position for {signal.symbol} "
                f"(side: {position.side}, entry: {position.entry_price})"
            )
            return False

        # Validate LONG_ENTRY signals
        if signal.signal_type == SignalType.LONG_ENTRY:
            if signal.take_profit <= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: LONG TP ({signal.take_profit}) must be > entry ({signal.entry_price})"
                )
                return False
            if signal.stop_loss >= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: LONG SL ({signal.stop_loss}) must be < entry ({signal.entry_price})"
                )
                return False

        # Validate SHORT_ENTRY signals
        elif signal.signal_type == SignalType.SHORT_ENTRY:
            if signal.take_profit >= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: SHORT TP ({signal.take_profit}) must be < entry ({signal.entry_price})"
                )
                return False
            if signal.stop_loss <= signal.entry_price:
                self.logger.warning(
                    f"Signal rejected: SHORT SL ({signal.stop_loss}) must be > entry ({signal.entry_price})"
                )
                return False

        # All validations passed
        return True

    def _round_to_lot_size(
        self,
        quantity: float,
        symbol_info: Optional[dict] = None
    ) -> float:
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

        lot_size = symbol_info.get('lot_size', 0.001)
        quantity_precision = symbol_info.get('quantity_precision', 3)

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
