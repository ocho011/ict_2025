"""
Order execution and management with Binance Futures API integration.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from binance.error import ClientError, ServerError

from src.core.audit_logger import AuditEventType, AuditLogger
from src.core.binance_service import BinanceServiceClient
from src.core.exceptions import OrderExecutionError, OrderRejectedError, ValidationError
from src.core.retry import retry_with_backoff
from src.models.order import Order, OrderSide, OrderStatus, OrderType
from src.models.position import Position
from src.models.signal import Signal, SignalType


# RequestWeightTracker moved to src.core.binance_service


class OrderExecutionManager:
    """
    Binance Futures order execution manager.

    Handles market order execution, automatic TP/SL placement, position management,
    and leverage configuration.

    Attributes:
        client (BinanceServiceClient): Centralized Binance API client service
        logger (logging.Logger): Logger instance
        _open_orders (Dict[str, List[Order]]): Open orders tracking per symbol

    Example:
        >>> # Using environment variables (recommended)
        >>> manager = OrderExecutionManager(is_testnet=True)

        >>> # Providing keys directly
        >>> manager = OrderExecutionManager(
        ...     api_key='your_key',
        ...     api_secret='your_secret',
        ...     is_testnet=False
        ... )

        >>> # Set leverage
        >>> manager.set_leverage('BTCUSDT', 10)
        True

        >>> # Set margin type
        >>> manager.set_margin_type('BTCUSDT', 'ISOLATED')
        True
    """

    def __init__(
        self,
        audit_logger: AuditLogger,
        binance_service: BinanceServiceClient,
    ) -> None:
        """
        Initialize OrderExecutionManager.

        Args:
            audit_logger: AuditLogger instance for structured logging
            binance_service: Centralized BinanceServiceClient instance
        """
        # Store injected service and components
        self.client = binance_service
        self.binance_service = binance_service
        self.audit_logger = audit_logger
        self.weight_tracker = binance_service.weight_tracker

        # Configure logger
        self.logger = logging.getLogger(__name__)

        # Initialize state tracking
        self._open_orders: Dict[str, List[Order]] = {}

        # Position cache with 5-second TTL
        self._position_cache: Dict[str, tuple[Optional[Position], float]] = {}
        self._cache_ttl_seconds = 5.0

        # Exchange info cache with 24h TTL
        self._exchange_info_cache: Dict[str, Dict[str, float]] = {}
        self._cache_timestamp: Optional[datetime] = None

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        Set leverage for a symbol.

        Binance Futures allows symbol-specific leverage configuration,
        supporting 1x to 125x (varies by symbol).

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT', 'ETHUSDT')
            leverage: Leverage multiplier (1-125)

        Returns:
            Success status (True: success, False: failure)

        Note:
            - In Hedge Mode, LONG and SHORT positions use the same leverage
            - Leverage changes are recommended when no open positions exist
            - Implements retry logic with exponential backoff on transient failures

        Example:
            >>> manager.set_leverage('BTCUSDT', 10)
            True

            >>> manager.set_leverage('ETHUSDT', 20)
            True

            >>> # Invalid leverage (API will reject)
            >>> manager.set_leverage('BTCUSDT', 200)
            False
        """
        try:
            # Call Binance API
            response = self.client.change_leverage(symbol=symbol, leverage=leverage)

            # Audit log success
            self.audit_logger.log_event(
                event_type=AuditEventType.LEVERAGE_SET,
                operation="set_leverage",
                symbol=symbol,
                response={"leverage": leverage, "status": "success"},
            )

            # Log success
            self.logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True

        except ClientError as e:
            # Audit log API error
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_leverage",
                symbol=symbol,
                error={
                    "status_code": e.status_code,
                    "error_code": e.error_code,
                    "error_message": e.error_message,
                },
            )

            # Binance API error (4xx status codes)
            self.logger.error(
                f"Failed to set leverage for {symbol}: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            return False

        except ServerError as e:
            # Handle server errors and audit log
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_leverage",
                symbol=symbol,
                error={"status_code": e.status_code, "message": e.message},
            )

            self.logger.error(
                f"Server error setting leverage for {symbol}: "
                f"status={e.status_code}, msg={e.message}"
            )
            return False

        except Exception as e:
            # Unexpected errors
            self.logger.error(f"Unexpected error setting leverage for {symbol}: {e}")
            return False

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """
        Set margin type (ISOLATED or CROSSED).

        - ISOLATED: Independent margin per position
        - CROSSED: Use entire account balance as margin

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            margin_type: 'ISOLATED' or 'CROSSED' (default: 'ISOLATED')

        Returns:
            Success status (True: success, False: failure)

        Note:
            - "No need to change" errors are silently ignored when already set
            - In Hedge Mode, LONG and SHORT positions use the same margin type
            - With ISOLATED margin, LONG and SHORT have independent margins
            - Implements retry logic with exponential backoff on transient failures

        Example:
            >>> # Set ISOLATED margin (recommended)
            >>> manager.set_margin_type('BTCUSDT', 'ISOLATED')
            True

            >>> # Set CROSSED margin
            >>> manager.set_margin_type('ETHUSDT', 'CROSSED')
            True

            >>> # Already set (still returns True)
            >>> manager.set_margin_type('BTCUSDT', 'ISOLATED')
            True
        """
        try:
            # Call Binance API
            response = self.client.change_margin_type(
                symbol=symbol, marginType=margin_type
            )

            # Audit log success
            self.audit_logger.log_event(
                event_type=AuditEventType.MARGIN_TYPE_SET,
                operation="set_margin_type",
                symbol=symbol,
                response={"margin_type": margin_type, "status": "success"},
            )

            # Log success
            self.logger.info(f"Margin type set to {margin_type} for {symbol}")
            return True

        except ClientError as e:
            # Treat "No need to change" error as success
            if "No need to change margin type" in e.error_message:
                self.logger.debug(
                    f"Margin type already set to {margin_type} for {symbol}"
                )
                return True

            # Audit log API error
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_margin_type",
                symbol=symbol,
                error={
                    "status_code": e.status_code,
                    "error_code": e.error_code,
                    "error_message": e.error_message,
                },
            )

            # Other ClientErrors are failures
            self.logger.error(
                f"Failed to set margin type for {symbol}: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            return False

        except ServerError as e:
            # Handle server errors and audit log
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_margin_type",
                symbol=symbol,
                error={"status_code": e.status_code, "message": e.message},
            )

            self.logger.error(
                f"Server error setting margin type for {symbol}: "
                f"status={e.status_code}, msg={e.message}"
            )
            return False

        except Exception as e:
            # Unexpected errors
            self.logger.error(f"Unexpected error setting margin type for {symbol}: {e}")
            return False

    def _format_price(self, price: float, symbol: str) -> str:
        """
        Format price according to symbol's tick size specification.

        Fetches tick size from Binance exchange info (cached), calculates
        precision, and formats price to exact decimal places required.

        Args:
            price: Raw price value
            symbol: Trading symbol (e.g., 'BTCUSDT')

        Returns:
            Price formatted as string with symbol-specific precision

        Raises:
            OrderExecutionError: Exchange info fetch fails critically

        Example:
            >>> manager._format_price(50123.456, 'BTCUSDT')
            '50123.46'  # 2 decimals for BTCUSDT

            >>> manager._format_price(492.1234, 'BNBUSDT')
            '492.123'  # 3 decimals for BNBUSDT
        """
        # 1. Get symbol-specific tick size (with caching)
        tick_size = self._get_tick_size(symbol)

        # 2. Calculate decimal precision from tick size
        decimal_places = self._calculate_precision(tick_size)

        # 3. Format price with calculated precision
        formatted = f"{price:.{decimal_places}f}"

        # 4. Log formatting (debug level)
        self.logger.debug(
            f"Formatted price for {symbol}: {price} → {formatted} "
            f"(tick_size={tick_size}, precision={decimal_places})"
        )

        return formatted

    def _calculate_precision(self, tick_size: float) -> int:
        """
        Calculate decimal precision from tick size.

        Args:
            tick_size: Minimum price increment (e.g., 0.01)

        Returns:
            Number of decimal places (e.g., 2)

        Example:
            >>> self._calculate_precision(0.01)
            2
            >>> self._calculate_precision(0.001)
            3
            >>> self._calculate_precision(1.0)
            0
        """
        # Convert to string to count decimal places
        tick_str = f"{tick_size:.10f}".rstrip("0")  # Remove trailing zeros

        if "." not in tick_str:
            return 0  # Integer tick size

        # Count digits after decimal point
        decimal_part = tick_str.split(".")[1]
        precision = len(decimal_part)

        return precision

    def _is_cache_expired(self) -> bool:
        """Check if exchange info cache has expired (24h TTL)."""
        if self._cache_timestamp is None:
            return True  # Never cached

        age = datetime.now() - self._cache_timestamp
        return age > timedelta(hours=24)

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def _refresh_exchange_info(self) -> None:
        """Fetch and cache exchange information from Binance."""
        self.logger.info("Fetching exchange information from Binance")

        try:
            # Call Binance API to fetch exchange info
            response = self.client.exchange_info()

            # Handle Binance API response structure (already unwrapped by service)
            exchange_data = response

            if not isinstance(exchange_data, dict):
                raise OrderExecutionError(
                    f"Unexpected exchange info response type: {type(exchange_data).__name__}"
                )

            # Validate symbols field exists
            if "symbols" not in exchange_data:
                self.logger.error(f"Exchange info keys: {list(exchange_data.keys())}")
                raise OrderExecutionError(
                    "Exchange info response missing 'symbols' field"
                )

            # Parse symbols and extract tick sizes
            symbols_parsed = 0
            for symbol_data in exchange_data["symbols"]:
                symbol = symbol_data["symbol"]

                # Find PRICE_FILTER and LOT_SIZE in symbol filters
                price_filter = None
                lot_filter = None
                for filter_item in symbol_data["filters"]:
                    if filter_item["filterType"] == "PRICE_FILTER":
                        price_filter = filter_item
                    elif filter_item["filterType"] == "LOT_SIZE":
                        lot_filter = filter_item

                if price_filter or lot_filter:
                    self._exchange_info_cache[symbol] = {
                        "tickSize": float(price_filter["tickSize"])
                        if price_filter
                        else 0.01,
                        "minPrice": float(price_filter["minPrice"])
                        if price_filter
                        else 0.0,
                        "maxPrice": float(price_filter["maxPrice"])
                        if price_filter
                        else 0.0,
                        "stepSize": float(lot_filter["stepSize"])
                        if lot_filter
                        else 0.001,
                        "minQty": float(lot_filter["minQty"]) if lot_filter else 0.0,
                        "maxQty": float(lot_filter["maxQty"]) if lot_filter else 0.0,
                    }
                    symbols_parsed += 1

            # Update cache timestamp
            self._cache_timestamp = datetime.now()

            self.logger.info(f"Exchange info cached: {symbols_parsed} symbols loaded")

        except ClientError as e:
            # Audit log API error
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="_refresh_exchange_info",
                error={
                    "status_code": e.status_code,
                    "error_code": e.error_code,
                    "error_message": e.error_message,
                },
            )

            self.logger.error(f"Failed to fetch exchange info: {e}")
            raise OrderExecutionError(
                f"Exchange info fetch failed: code={e.error_code}, msg={e.error_message}"
            )

        except ServerError as e:
            # Handle server errors and audit log
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="_refresh_exchange_info",
                error={"status_code": e.status_code, "message": e.message},
            )

            self.logger.error(f"Server error fetching exchange info: {e}")
            raise OrderExecutionError(f"Exchange info fetch failed: {e.message}")

        except Exception as e:
            self.logger.error(f"Failed to fetch exchange info: {e}")
            raise OrderExecutionError(f"Exchange info fetch failed: {e}")

    def _get_tick_size(self, symbol: str) -> float:
        """
        Get tick size for symbol from exchange info (cached).

        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')

        Returns:
            Tick size as float (e.g., 0.01)

        Raises:
            OrderExecutionError: Exchange info fetch fails

        Note:
            Falls back to 0.01 (2 decimals) if symbol not found
        """
        # 1. Check cache validity
        if self._is_cache_expired():
            self._refresh_exchange_info()

        # 2. Look up symbol in cache
        if symbol in self._exchange_info_cache:
            tick_size = self._exchange_info_cache[symbol]["tickSize"]
            self.logger.debug(f"Cache hit for {symbol}: tickSize={tick_size}")
            return tick_size

        # 3. Symbol not found - graceful fallback
        self.logger.warning(
            f"Symbol {symbol} not found in exchange info. "
            f"Using default tickSize=0.01 (2 decimals). "
            f"This may cause order rejection for non-standard pairs."
        )
        return 0.01  # Default for USDT pairs

    def _get_step_size(self, symbol: str) -> float:
        """
        Get step size (quantity precision) for symbol from exchange info (cached).

        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')

        Returns:
            Step size as float (e.g., 0.001)

        Note:
            Falls back to 0.001 (3 decimals) if symbol not found
        """
        # 1. Check cache validity
        if self._is_cache_expired():
            self._refresh_exchange_info()

        # 2. Look up symbol in cache
        if symbol in self._exchange_info_cache:
            step_size = self._exchange_info_cache[symbol].get("stepSize", 0.001)
            self.logger.debug(f"Cache hit for {symbol}: stepSize={step_size}")
            return step_size

        # 3. Symbol not found - graceful fallback
        self.logger.warning(
            f"Symbol {symbol} not found in exchange info. "
            f"Using default stepSize=0.001 (3 decimals). "
            f"This may cause order rejection."
        )
        return 0.001  # Default

    def _format_quantity(self, quantity: float, symbol: str) -> str:
        """
        Format quantity according to symbol's step size specification.

        Args:
            quantity: Raw quantity value
            symbol: Trading symbol (e.g., 'BTCUSDT')

        Returns:
            Quantity formatted as string with symbol-specific precision

        Example:
            >>> manager._format_quantity(10.123456, 'XRPUSDT')
            '10.1'  # 1 decimal for XRPUSDT
        """
        # 1. Get symbol-specific step size (with caching)
        step_size = self._get_step_size(symbol)

        # 2. Calculate decimal precision from step size
        decimal_places = self._calculate_precision(step_size)

        # 3. Format quantity with calculated precision
        formatted = f"{quantity:.{decimal_places}f}"

        # 4. Log formatting (debug level)
        self.logger.debug(
            f"Formatted quantity for {symbol}: {quantity} → {formatted} "
            f"(stepSize={step_size}, precision={decimal_places})"
        )

        return formatted

    def _determine_order_side(self, signal: Signal) -> OrderSide:
        """
        Determine Binance order side (BUY/SELL) from signal type.

        Mapping:
            LONG_ENTRY  → BUY   (enter long position)
            SHORT_ENTRY → SELL  (enter short position)
            CLOSE_LONG  → SELL  (close long position)
            CLOSE_SHORT → BUY   (close short position)

        Args:
            signal: Trading signal

        Returns:
            OrderSide enum (BUY or SELL)

        Raises:
            ValidationError: Unknown signal type

        Example:
            >>> signal = Signal(SignalType.LONG_ENTRY, ...)
            >>> side = manager._determine_order_side(signal)
            >>> assert side == OrderSide.BUY
        """
        mapping = {
            SignalType.LONG_ENTRY: OrderSide.BUY,
            SignalType.SHORT_ENTRY: OrderSide.SELL,
            SignalType.CLOSE_LONG: OrderSide.SELL,
            SignalType.CLOSE_SHORT: OrderSide.BUY,
        }

        if signal.signal_type not in mapping:
            raise ValidationError(f"Unknown signal type: {signal.signal_type}")

        return mapping[signal.signal_type]

    def _parse_order_response(
        self, response: Dict[str, Any], symbol: str, side: OrderSide
    ) -> Order:
        """
        Parse Binance API response into Order object.

        Converts Binance's JSON response structure into our internal Order model,
        handling type conversions and timestamp parsing. Supports MARKET,
        STOP_MARKET, and TAKE_PROFIT_MARKET order types.

        Args:
            response: Binance new_order() API response dictionary
            symbol: Trading pair (for validation)
            side: Order side (for validation)

        Returns:
            Order object with populated fields

        Raises:
            OrderExecutionError: Missing required fields or malformed response

        Example Response (MARKET order):
            {
                "orderId": 123456789,
                "symbol": "BTCUSDT",
                "status": "FILLED",
                "type": "MARKET",
                "avgPrice": "59808.02",
                "origQty": "0.001",
                "executedQty": "0.001",
                "updateTime": 1653563095000,
                ...
            }

        Example Response (STOP_MARKET order):
            {
                "orderId": 123456790,
                "symbol": "BTCUSDT",
                "status": "NEW",
                "type": "STOP_MARKET",
                "stopPrice": "49000.00",
                "origQty": "0.000",  # 0 when using closePosition
                "updateTime": 1653563096000,
                ...
            }

        Example:
            >>> response = {...}  # Binance API response
            >>> order = manager._parse_order_response(response, 'BTCUSDT', OrderSide.BUY)
            >>> assert order.order_id == '123456789'
            >>> assert order.status == OrderStatus.FILLED
        """
        try:
            # Handle Binance API response structure (already unwrapped by service)
            order_data = response

            if not isinstance(order_data, dict):
                raise OrderExecutionError(
                    f"Unexpected order response type: {type(order_data).__name__}"
                )

            # Extract required fields
            order_id = str(order_data["orderId"])
            status_str = order_data["status"]

            # For MARKET orders: origQty is filled quantity
            # For STOP/TP orders: origQty may be "0" when using closePosition
            quantity = float(order_data.get("origQty", "0"))

            # Parse execution price (avgPrice for market orders)
            avg_price = float(order_data.get("avgPrice", "0"))

            # Convert timestamp (milliseconds → datetime)
            timestamp_ms = order_data["updateTime"]
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

            # Map Binance status string to OrderStatus enum
            status = OrderStatus[status_str]  # Raises KeyError if invalid

            # Determine order type from response
            order_type_str = order_data.get("type", "MARKET")
            order_type = OrderType[order_type_str]

            # Extract stop price for STOP/TP orders
            stop_price = None
            if "stopPrice" in order_data and order_data["stopPrice"]:
                stop_price = float(order_data["stopPrice"])

            # Create Order object
            return Order(
                symbol=symbol,
                side=side,
                order_type=order_type,  # Will be MARKET, STOP_MARKET, or TAKE_PROFIT_MARKET
                quantity=quantity,
                price=avg_price if avg_price > 0 else None,
                stop_price=stop_price,
                order_id=order_id,
                client_order_id=order_data.get("clientOrderId"),
                status=status,
                timestamp=timestamp,
            )

        except KeyError as e:
            raise OrderExecutionError(f"Missing required field in API response: {e}")
        except (ValueError, TypeError) as e:
            raise OrderExecutionError(f"Invalid data type in API response: {e}")

    def _place_tp_order(self, signal: Signal, side: OrderSide) -> Optional[Order]:
        """
        Place TAKE_PROFIT_MARKET order for position exit.

        Args:
            signal: Trading signal with take_profit price
            side: Order side to close position (opposite of entry)

        Returns:
            Order object if successful, None if placement fails

        Note:
            Failures are logged but not raised to avoid failing the entire trade.

        Example:
            >>> tp_order = manager._place_tp_order(signal, OrderSide.SELL)
            >>> if tp_order:
            ...     print(f"TP placed: {tp_order.order_id}")
        """
        try:
            # Validate take_profit exists
            if signal.take_profit is None:
                self.logger.error(
                    f"Cannot place TP order: take_profit is None for {signal.symbol}"
                )
                return None

            # Format stop price to Binance precision
            stop_price_str = self._format_price(signal.take_profit, signal.symbol)

            # Log TP order intent
            self.logger.info(
                f"Placing TP order: {signal.symbol} {side.value} "
                f"@ {stop_price_str} (close position)"
            )

            # Place TAKE_PROFIT_MARKET order via Binance API
            response = self.client.new_order(
                symbol=signal.symbol,
                side=side.value,  # SELL for long, BUY for short
                type=OrderType.TAKE_PROFIT_MARKET.value,  # "TAKE_PROFIT_MARKET"
                stopPrice=stop_price_str,  # Trigger price (formatted)
                closePosition="true",  # Close entire position
                workingType="MARK_PRICE",  # Use mark price for trigger
            )

            # Parse API response into Order object
            order = self._parse_order_response(
                response=response, symbol=signal.symbol, side=side
            )

            # Override order_type and stop_price (response may not have correct values)
            order.order_type = OrderType.TAKE_PROFIT_MARKET
            order.stop_price = signal.take_profit

            # Log successful placement
            self.logger.info(
                f"TP order placed: ID={order.order_id}, stopPrice={stop_price_str}"
            )

            # Audit log: TP order placed successfully
            try:
                self.audit_logger.log_order_placed(
                    symbol=signal.symbol,
                    order_data={
                        "order_type": "TAKE_PROFIT_MARKET",
                        "side": side.value,
                        "stop_price": signal.take_profit,
                        "close_position": True,
                    },
                    response={"order_id": order.order_id, "status": order.status.value},
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return order

        except ClientError as e:
            # Binance API error (4xx) - log but don't raise
            self.logger.error(
                f"TP order rejected: code={e.error_code}, msg={e.error_message}"
            )

            # Audit log: TP order rejected
            try:
                self.audit_logger.log_order_rejected(
                    symbol=signal.symbol,
                    order_data={
                        "order_type": "TAKE_PROFIT_MARKET",
                        "side": side.value,
                        "stop_price": signal.take_profit,
                    },
                    error={
                        "error_code": e.error_code,
                        "error_message": e.error_message,
                    },
                )
            except Exception:
                pass  # Don't double-log

            return None

        except Exception as e:
            # Unexpected error - log but don't raise
            self.logger.error(f"TP order placement failed: {type(e).__name__}: {e}")

            # Audit log: API error during TP order placement
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="place_tp_order",
                    symbol=signal.symbol,
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass  # Don't double-log

            return None

    def _place_sl_order(self, signal: Signal, side: OrderSide) -> Optional[Order]:
        """
        Place STOP_MARKET order for position exit.

        Args:
            signal: Trading signal with stop_loss price
            side: Order side to close position (opposite of entry)

        Returns:
            Order object if successful, None if placement fails

        Note:
            Failures are logged but not raised to avoid failing the entire trade.

        Example:
            >>> sl_order = manager._place_sl_order(signal, OrderSide.SELL)
            >>> if sl_order:
            ...     print(f"SL placed: {sl_order.order_id}")
        """
        try:
            # Validate stop_loss exists
            if signal.stop_loss is None:
                self.logger.error(
                    f"Cannot place SL order: stop_loss is None for {signal.symbol}"
                )
                return None

            # Format stop price to Binance precision
            stop_price_str = self._format_price(signal.stop_loss, signal.symbol)

            # Log SL order intent
            self.logger.info(
                f"Placing SL order: {signal.symbol} {side.value} "
                f"@ {stop_price_str} (close position)"
            )

            # Place STOP_MARKET order via Binance API
            response = self.client.new_order(
                symbol=signal.symbol,
                side=side.value,  # SELL for long, BUY for short
                type=OrderType.STOP_MARKET.value,  # "STOP_MARKET"
                stopPrice=stop_price_str,  # Trigger price (formatted)
                closePosition="true",  # Close entire position
                workingType="MARK_PRICE",  # Use mark price for trigger
            )

            # Parse API response into Order object
            order = self._parse_order_response(
                response=response, symbol=signal.symbol, side=side
            )

            # Override order_type and stop_price
            order.order_type = OrderType.STOP_MARKET
            order.stop_price = signal.stop_loss

            # Log successful placement
            self.logger.info(
                f"SL order placed: ID={order.order_id}, stopPrice={stop_price_str}"
            )

            # Audit log: SL order placed successfully
            try:
                self.audit_logger.log_order_placed(
                    symbol=signal.symbol,
                    order_data={
                        "order_type": "STOP_MARKET",
                        "side": side.value,
                        "stop_price": signal.stop_loss,
                        "close_position": True,
                    },
                    response={"order_id": order.order_id, "status": order.status.value},
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return order

        except ClientError as e:
            # Binance API error - log but don't raise
            self.logger.error(
                f"SL order rejected: code={e.error_code}, msg={e.error_message}"
            )

            # Audit log: SL order rejected
            try:
                self.audit_logger.log_order_rejected(
                    symbol=signal.symbol,
                    order_data={
                        "order_type": "STOP_MARKET",
                        "side": side.value,
                        "stop_price": signal.stop_loss,
                    },
                    error={
                        "error_code": e.error_code,
                        "error_message": e.error_message,
                    },
                )
            except Exception:
                pass  # Don't double-log

            return None

        except Exception as e:
            # Unexpected error - log but don't raise
            self.logger.error(f"SL order placement failed: {type(e).__name__}: {e}")

            # Audit log: API error during SL order placement
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="place_sl_order",
                    symbol=signal.symbol,
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass  # Don't double-log

            return None

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def execute_signal(
        self, signal: Signal, quantity: float, reduce_only: bool = False
    ) -> tuple[Order, list[Order]]:
        """
        Execute trading signal by placing market order with TP/SL orders.

        Translates Signal objects into Binance market orders, handling order side
        determination, API submission, and response parsing. For entry signals
        (LONG_ENTRY, SHORT_ENTRY), automatically places TP and SL orders.

        Args:
            signal: Trading signal containing entry parameters
            quantity: Order size in base asset (e.g., BTC for BTCUSDT)
            reduce_only: If True, order only reduces existing position

        Returns:
            tuple[Order, list[Order]]: (entry_order, [tp_order, sl_order])
            - For LONG_ENTRY/SHORT_ENTRY: list contains 2 orders [TP, SL]
            - For CLOSE_LONG/CLOSE_SHORT: list is empty []

        Raises:
            ValidationError: Invalid signal type or quantity <= 0
            OrderRejectedError: Binance rejected the entry order
            OrderExecutionError: Entry order API call failed

        Note:
            TP/SL placement failures are logged but don't raise exceptions.
            Entry order must succeed; TP/SL failures result in partial execution.
            Implements retry logic with exponential backoff on transient failures.

        Example:
            >>> signal = Signal(
            ...     signal_type=SignalType.LONG_ENTRY,
            ...     symbol='BTCUSDT',
            ...     entry_price=50000.0,
            ...     take_profit=52000.0,
            ...     stop_loss=49000.0,
            ...     strategy_name='SMA_Crossover',
            ...     timestamp=datetime.now(timezone.utc)
            ... )
            >>> entry_order, tpsl_orders = manager.execute_signal(signal, quantity=0.001)
            >>> print(f"Entry ID: {entry_order.order_id}")
            >>> print(f"TP/SL placed: {len(tpsl_orders)}")
            Entry ID: 123456789
            TP/SL placed: 2
        """
        # Validate inputs
        if quantity <= 0:
            raise ValidationError(f"Quantity must be > 0, got {quantity}")

        # Determine order side from signal type
        side = self._determine_order_side(signal)

        # Log order intent
        self.logger.info(
            f"Executing {signal.signal_type.value} signal: "
            f"{signal.symbol} {side.value} {quantity} "
            f"(strategy: {signal.strategy_name})"
        )
        # Prepare order parameters for market entry order
        # Format quantity according to symbol's step size (precision)
        formatted_qty = self._format_quantity(quantity, signal.symbol)

        order_params = {
            "symbol": signal.symbol,
            "side": side.value,
            "type": OrderType.MARKET.value,
            "quantity": formatted_qty,
            "reduceOnly": reduce_only,
        }

        try:
            # Submit market order to Binance
            response = self.client.new_order(**order_params)

            # Parse API response into Order object
            entry_order = self._parse_order_response(
                response=response, symbol=signal.symbol, side=side
            )

            # Audit log successful order placement
            self.audit_logger.log_order_placed(
                symbol=signal.symbol,
                order_data=order_params,
                response={
                    "order_id": entry_order.order_id,
                    "status": entry_order.status.value,
                    "price": str(entry_order.price),
                    "quantity": str(entry_order.quantity),
                },
            )

            # Log successful execution
            self.logger.info(
                f"Entry order executed: ID={entry_order.order_id}, "
                f"status={entry_order.status.value}, "
                f"filled={entry_order.quantity} @ {entry_order.price}"
            )

        except ClientError as e:
            # Audit log order rejection
            self.audit_logger.log_order_rejected(
                symbol=signal.symbol,
                order_data=order_params,
                error={
                    "status_code": e.status_code,
                    "error_code": e.error_code,
                    "error_message": e.error_message,
                },
            )

            # Binance API errors (4xx status codes)
            self.logger.error(
                f"Entry order rejected by Binance: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            raise OrderRejectedError(
                f"Binance rejected order: {e.error_message}"
            ) from e

        except ServerError as e:
            # Handle server errors and audit log
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="execute_signal",
                symbol=signal.symbol,
                order_data=order_params,
                error={"status_code": e.status_code, "message": e.message},
            )

            self.logger.error(
                f"Binance server error placing order: "
                f"status={e.status_code}, msg={e.message}"
            )
            raise OrderExecutionError(f"Binance server error: {e.message}") from e

        except Exception as e:
            # Unexpected errors (network, parsing, etc.)
            self.logger.error(f"Entry order execution failed: {type(e).__name__}: {e}")
            raise OrderExecutionError(f"Failed to execute order: {e}") from e

        # Check if TP/SL orders are needed
        tpsl_orders: list[Order] = []

        # Handle different signal types
        if signal.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
            # Entry signals: Cancel existing orders before placing new TP/SL orders
            # This prevents orphaned TP/SL orders from previous positions
            try:
                cancelled_count = self.cancel_all_orders(signal.symbol)
                if cancelled_count > 0:
                    self.logger.info(
                        f"Cancelled {cancelled_count} existing orders "
                        f"before placing new TP/SL orders"
                    )
            except Exception as e:
                # Log warning but continue - don't fail the entire order due to cancellation failure
                self.logger.warning(
                    f"Failed to cancel existing orders: {e}. "
                    f"Proceeding with TP/SL placement anyway."
                )

            # Determine TP/SL side (opposite of entry side)
            # LONG_ENTRY: entry is BUY → TP/SL are SELL
            # SHORT_ENTRY: entry is SELL → TP/SL are BUY
            tpsl_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

            # Place TP order
            tp_order = self._place_tp_order(signal, tpsl_side)
            if tp_order:
                tpsl_orders.append(tp_order)

            # Place SL order
            sl_order = self._place_sl_order(signal, tpsl_side)
            if sl_order:
                tpsl_orders.append(sl_order)

            # Log TP/SL placement summary
            self.logger.info(
                f"TP/SL placement complete: {len(tpsl_orders)}/2 orders placed"
            )

            if len(tpsl_orders) < 2:
                self.logger.warning(
                    f"Partial TP/SL placement: entry filled but "
                    f"only {len(tpsl_orders)}/2 exit orders placed"
                )

        elif signal.signal_type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            # Close signals: Cancel all remaining TP/SL orders (Issue #9)
            # Position is being closed, so any remaining TP/SL orders should be cancelled
            try:
                cancelled_count = self.cancel_all_orders(signal.symbol)
                if cancelled_count > 0:
                    self.logger.info(
                        f"Position closed: cancelled {cancelled_count} remaining "
                        f"TP/SL orders for {signal.symbol}"
                    )
                else:
                    self.logger.info(
                        f"Position closed: no remaining orders to cancel for {signal.symbol}"
                    )
            except Exception as e:
                # Log warning - failure to cancel shouldn't block position closure
                self.logger.warning(
                    f"Failed to cancel remaining orders after position closure: {e}. "
                    f"Manual cleanup may be required."
                )

        # Return entry order and TP/SL orders
        return (entry_order, tpsl_orders)

    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Query current position information for a symbol.

        Retrieves position data from Binance Futures API and parses it into
        a Position object. Returns None if no active position exists (positionAmt=0).

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            Position object if position exists, None if no position

        Raises:
            ValidationError: Invalid symbol format
            OrderExecutionError: API call fails or response parsing error

        Example:
            >>> position = manager.get_position('BTCUSDT')
            >>> if position:
            ...     print(f"{position.side} position: {position.quantity} @ {position.entry_price}")
            ... else:
            ...     print("No position")
        """
        # 1. Validate input
        if not symbol or not isinstance(symbol, str):
            raise ValidationError(f"Invalid symbol: {symbol}")

        # 2. Check cache first
        cached_data = self._position_cache.get(symbol)
        current_time = time.time()
        if cached_data and (current_time - cached_data[1]) < self._cache_ttl_seconds:
            return cached_data[0]  # Return cached position

        # 3. Log API call (only if cache miss)
        self.logger.info(f"Querying position for {symbol} (cache miss)")

        try:
            # 3. Call Binance API
            response = self.client.get_position_risk(symbol=symbol)

            # 4. Parse response
            if not response:
                # Cache the None result
                self._position_cache[symbol] = (None, current_time)
                self.logger.error(f"Position API failed for {symbol} - no response")
                return None

            # Handler Binance API response structure (now already unwrapped by BinanceServiceClient)
            unwrapped = response

            if isinstance(unwrapped, list):
                # Direct list response or unwrapped data list
                if len(unwrapped) == 0:
                    # Cache the None result
                    self._position_cache[symbol] = (None, current_time)
                    self.logger.info(f"No active position for {symbol} (empty data)")
                    return None
                position_data = unwrapped[0]
            else:
                raise OrderExecutionError(
                    f"Unexpected response type: {type(unwrapped).__name__}"
                )

            # Extract position amount
            position_amt = float(position_data.get("positionAmt", 0))

            # 5. Check if position exists
            if position_amt == 0:
                # Cache the None result
                self._position_cache[symbol] = (None, current_time)
                self.logger.info(f"No active position for {symbol}")
                return None

            # 6. Determine position side
            side = "LONG" if position_amt > 0 else "SHORT"
            quantity = abs(position_amt)

            # 7. Extract required fields
            entry_price = float(position_data["entryPrice"])
            leverage = int(
                position_data.get("leverage", 1)
            )  # Default to 1x if not provided
            unrealized_pnl = float(position_data["unRealizedProfit"])

            # 8. Extract optional liquidation price
            liquidation_price = None
            if "liquidationPrice" in position_data:
                liq_price_str = position_data["liquidationPrice"]
                if liq_price_str and liq_price_str != "0":
                    liquidation_price = float(liq_price_str)

            # 9. Create Position object
            position = Position(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                leverage=leverage,
                unrealized_pnl=unrealized_pnl,
                liquidation_price=liquidation_price,
            )

            self.logger.info(
                f"Position retrieved: {side} {quantity} {symbol} @ {entry_price}, "
                f"PnL: {unrealized_pnl}"
            )

            # Store in cache
            self._position_cache[symbol] = (position, current_time)

            # Audit log: position query successful
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.POSITION_QUERY,
                    operation="get_position",
                    symbol=symbol,
                    response={
                        "has_position": True,
                        "position_amt": quantity,
                        "entry_price": entry_price,
                        "side": side,
                        "unrealized_pnl": unrealized_pnl,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return position

        except ClientError as e:
            # Audit log: API error during position query
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="get_position",
                    symbol=symbol,
                    error={
                        "error_code": e.error_code,
                        "error_message": e.error_message,
                    },
                )
            except Exception:
                pass  # Don't double-log

            # Cache the error result too
            self._position_cache[symbol] = (None, current_time)

            # Handle Binance API errors
            if e.error_code == -1121:
                raise ValidationError(f"Invalid symbol: {symbol}")
            elif e.error_code == -2015:
                raise OrderExecutionError(
                    f"API authentication failed: {e.error_message}"
                )
            else:
                raise OrderExecutionError(
                    f"Position query failed: code={e.error_code}, msg={e.error_message}"
                )
        except (KeyError, ValueError, TypeError) as e:
            # Cache the None result too
            self._position_cache[symbol] = (None, current_time)

            # Audit log: parsing error
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="get_position",
                    symbol=symbol,
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass  # Don't double-log

            raise OrderExecutionError(f"Failed to parse position data: {e}")

    def get_account_balance(self) -> float:
        """
        Query USDT wallet balance.

        Retrieves account information from Binance Futures API and extracts
        USDT wallet balance from the assets array.

        Returns:
            USDT wallet balance as float (returns 0.0 if USDT not found)

        Raises:
            OrderExecutionError: API call fails or response parsing error

        Example:
            >>> balance = manager.get_account_balance()
            >>> print(f"Available USDT: {balance:.2f}")
        """
        # 1. Log API call
        self.logger.info("Querying account balance")

        try:
            # 2. Call Binance API
            response = self.client.account()

            # 3. Extract account data
            # Handle Binance API response structure (now already unwrapped by BinanceServiceClient)
            account_data = response

            if not isinstance(account_data, dict):
                raise OrderExecutionError(
                    f"Unexpected account response type: {type(account_data).__name__}"
                )

            # 4. Extract assets array
            if "assets" not in account_data:
                self.logger.error(f"Account data keys: {list(account_data.keys())}")
                raise OrderExecutionError("Account response missing 'assets' field")

            assets = account_data["assets"]

            # 5. Find USDT balance
            usdt_balance = None

            for asset in assets:
                if asset.get("asset") == "USDT":
                    usdt_balance = float(asset["walletBalance"])
                    break

            if usdt_balance is None:
                # USDT not found in assets array
                self.logger.warning("USDT not found in account assets, returning 0.0")
                return 0.0

            # 6. Log and return
            self.logger.info(f"USDT balance: {usdt_balance:.2f}")

            # Audit log: balance query successful
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.BALANCE_QUERY,
                    operation="get_account_balance",
                    response={"balance": usdt_balance},
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return usdt_balance

        except ClientError as e:
            # Handle Binance API errors
            if e.error_code == -2015:
                raise OrderExecutionError(
                    f"API authentication failed: {e.error_message}"
                )
            else:
                raise OrderExecutionError(
                    f"Balance query failed: code={e.error_code}, msg={e.error_message}"
                )
        except (KeyError, ValueError, TypeError) as e:
            raise OrderExecutionError(f"Failed to parse account data: {e}")

    def cancel_all_orders(self, symbol: str) -> int:
        """
        Cancel all open orders for a symbol.

        Cancels all active orders for the specified trading symbol using
        Binance Futures API. Returns the count of cancelled orders.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            Number of orders cancelled

        Raises:
            ValidationError: Invalid symbol format
            OrderExecutionError: API call fails

        Example:
            >>> cancelled_count = manager.cancel_all_orders('BTCUSDT')
            >>> print(f"Cancelled {cancelled_count} orders")
        """
        # 1. Validate input
        if not symbol or not isinstance(symbol, str):
            raise ValidationError(f"Invalid symbol: {symbol}")

        # 2. Log API call
        self.logger.info(f"Cancelling all orders for {symbol}")

        try:
            # 3. Call Binance API
            response = self.client.cancel_open_orders(symbol=symbol)

            # 4. Parse response (now already unwrapped by BinanceServiceClient)
            unwrapped = response

            if isinstance(unwrapped, list):
                # Response is a list of cancelled order objects
                cancelled_count = len(unwrapped)
                self.logger.info(f"Cancelled {cancelled_count} orders for {symbol}")
            elif isinstance(unwrapped, dict) and unwrapped.get("code") == 200:
                # Response is a success message (no orders to cancel or success msg)
                cancelled_count = 0
                self.logger.info(
                    f"Success: {unwrapped.get('msg', 'Orders cancelled')} for {symbol}"
                )
            else:
                # Unexpected response format
                self.logger.warning(f"Unexpected response format: {response}")
                cancelled_count = 0

            # Audit log: order cancellation
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.ORDER_CANCELLED,
                    operation="cancel_all_orders",
                    symbol=symbol,
                    response={
                        "cancelled_count": cancelled_count,
                        "order_ids": (
                            [o.get("orderId") for o in response]
                            if isinstance(response, list)
                            else []
                        ),
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return cancelled_count

        except ClientError as e:
            # Handle Binance API errors
            if e.error_code == -1121:
                raise ValidationError(f"Invalid symbol: {symbol}")
            elif e.error_code == -2015:
                raise OrderExecutionError(
                    f"API authentication failed: {e.error_message}"
                )
            else:
                raise OrderExecutionError(
                    f"Order cancellation failed: code={e.error_code}, msg={e.error_message}"
                )
        except Exception as e:
            raise OrderExecutionError(
                f"Unexpected error during order cancellation: {e}"
            )

    async def get_all_positions(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Query all open positions for given symbols.

        Args:
            symbols: List of trading symbols (e.g., ['BTCUSDT', 'ETHUSDT'])

        Returns:
            List of position dictionaries with keys:
            - symbol: str
            - positionAmt: str (quantity, negative for SHORT)
            - entryPrice: str
            - unrealizedProfit: str
            - leverage: str

        Raises:
            OrderExecutionError: API call fails

        Example:
            >>> positions = await manager.get_all_positions(['BTCUSDT'])
            >>> for pos in positions:
            ...     print(f"{pos['symbol']}: {pos['positionAmt']} @ {pos['entryPrice']}")
        """
        self.logger.info(f"Querying positions for symbols: {symbols}")

        try:
            # Call Binance API without symbol parameter to get all positions
            response = self.client.get_position_risk()

            # Handle Binance API response structure
            if isinstance(response, dict) and "data" in response:
                position_list = response["data"]
            elif isinstance(response, list):
                position_list = response
            else:
                raise OrderExecutionError(
                    f"Unexpected response type: {type(response).__name__}"
                )

            # Filter to requested symbols with non-zero positions
            filtered_positions = []
            for pos_data in position_list:
                symbol = pos_data.get("symbol")
                position_amt = float(pos_data.get("positionAmt", 0))

                # Only include positions for requested symbols with non-zero quantity
                if symbol in symbols and position_amt != 0:
                    filtered_positions.append(
                        {
                            "symbol": symbol,
                            "positionAmt": pos_data.get("positionAmt"),
                            "entryPrice": pos_data.get("entryPrice"),
                            "unrealizedProfit": pos_data.get("unRealizedProfit"),
                            "leverage": pos_data.get("leverage"),
                            "liquidationPrice": pos_data.get("liquidationPrice"),
                        }
                    )

            self.logger.info(f"Found {len(filtered_positions)} open positions")

            # Audit log
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.POSITION_QUERY,
                    operation="get_all_positions",
                    data={
                        "symbols": symbols,
                        "positions_count": len(filtered_positions),
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return filtered_positions

        except ClientError as e:
            # Audit log API error
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="get_all_positions",
                    error={
                        "status_code": e.status_code,
                        "error_code": e.error_code,
                        "error_message": e.error_message,
                    },
                )
            except Exception:
                pass

            raise OrderExecutionError(
                f"Position query failed: code={e.error_code}, msg={e.error_message}"
            )
        except Exception as e:
            raise OrderExecutionError(f"Unexpected error querying positions: {e}")

    async def execute_market_close(
        self,
        symbol: str,
        position_amt: float,
        side: str,
        reduce_only: bool = True,
    ) -> Dict[str, Any]:
        """
        Close position with market order (reduceOnly=True).

        Args:
            symbol: Trading symbol
            position_amt: Position size (absolute value)
            side: "BUY" for closing SHORT, "SELL" for closing LONG
            reduce_only: If True, only reduces position (default: True for security)

        Returns:
            Order response from Binance API with keys:
            - success: bool
            - order_id: str (if successful)
            - error: str (if failed)

        Raises:
            ValidationError: Invalid parameters
            OrderExecutionError: API call fails critically

        Security:
            reduceOnly=True is enforced by default to prevent accidental new positions.

        Example:
            >>> result = await manager.execute_market_close(
            ...     symbol='BTCUSDT',
            ...     position_amt=0.1,
            ...     side='SELL',  # Closing LONG position
            ... )
            >>> if result['success']:
            ...     print(f"Position closed: {result['order_id']}")
        """
        # Validate inputs
        if not symbol or not isinstance(symbol, str):
            raise ValidationError(f"Invalid symbol: {symbol}")
        if position_amt <= 0:
            raise ValidationError(f"Position amount must be > 0, got {position_amt}")
        if side not in ("BUY", "SELL"):
            raise ValidationError(f"Side must be BUY or SELL, got {side}")

        # SECURITY: Enforce reduceOnly=True
        if not reduce_only:
            self.logger.warning(
                "SECURITY: reduceOnly=False requested but overridden to True for safety"
            )
            reduce_only = True

        self.logger.info(
            f"Closing position: {symbol} {side} {position_amt} (reduceOnly={reduce_only})"
        )

        try:
            # Place market order with reduceOnly
            response = self.client.new_order(
                symbol=symbol,
                side=side,
                type=OrderType.MARKET.value,
                quantity=position_amt,
                reduceOnly=reduce_only,
            )

            # Parse response
            if isinstance(response, dict) and "data" in response:
                order_data = response["data"]
            elif isinstance(response, dict):
                order_data = response
            else:
                raise OrderExecutionError(
                    f"Unexpected response type: {type(response).__name__}"
                )

            order_id = str(order_data.get("orderId"))
            status = order_data.get("status")

            # Audit log success
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.ORDER_PLACED,
                    operation="execute_market_close",
                    symbol=symbol,
                    response={
                        "order_id": order_id,
                        "status": status,
                        "side": side,
                        "quantity": position_amt,
                        "reduce_only": reduce_only,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            self.logger.info(
                f"Position close order executed: ID={order_id}, status={status}"
            )

            return {
                "success": True,
                "order_id": order_id,
                "status": status,
            }

        except ClientError as e:
            # Audit log rejection
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.ORDER_REJECTED,
                    operation="execute_market_close",
                    symbol=symbol,
                    error={
                        "error_code": e.error_code,
                        "error_message": e.error_message,
                    },
                )
            except Exception:
                pass

            self.logger.error(
                f"Market close order rejected: code={e.error_code}, msg={e.error_message}"
            )

            return {
                "success": False,
                "error": f"Order rejected: {e.error_message}",
            }

        except Exception as e:
            self.logger.error(f"Unexpected error during market close: {e}")

            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
            }
