"""
Order execution and management with Binance Futures API integration.
"""

import logging
import time
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.core.audit_logger import AuditEventType, AuditLogger
from src.core.async_binance_client import AsyncBinanceClient
from src.core.async_circuit_breaker import AsyncCircuitBreaker
from src.core.exceptions import OrderExecutionError, OrderRejectedError, ValidationError
from src.core.async_retry import async_retry_with_backoff
from src.models.order import Order, OrderSide, OrderStatus, OrderType
from src.models.position import Position
from src.models.signal import Signal, SignalType

from src.execution.base import ExecutionGateway, ExchangeProvider

# RequestWeightTracker moved to src.core.binance_service


class OrderGateway(ExecutionGateway, ExchangeProvider):
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
        >>> manager = OrderGateway(is_testnet=True)

        >>> # Providing keys directly
        >>> manager = OrderGateway(
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
        audit_logger: Optional[AuditLogger] = None,
        binance_service: Optional[AsyncBinanceClient] = None,
    ) -> None:
        """
        Initialize OrderGateway.

        Args:
            audit_logger: Optional AuditLogger instance for structured logging.
                         If None, uses singleton instance from AuditLogger.get_instance()
            binance_service: Centralized AsyncBinanceClient instance
        """
        # Store injected service and components
        self.client = binance_service
        self.binance_service = binance_service
        self.audit_logger = audit_logger or AuditLogger.get_instance()
        self.weight_tracker = None # Async client handles weight internally or later

        # Configure logger
        self.logger = logging.getLogger(__name__)

        # Initialize state tracking
        self._open_orders: Dict[str, List[Order]] = {}

        # Open orders cache to reduce API calls (Issue #41 rate limit fix)
        # Cache structure: {symbol: (orders_list, timestamp)}
        self._open_orders_cache: Dict[str, tuple[List[Dict[str, Any]], float]] = {}
        self._open_orders_cache_ttl: float = 30.0  # 30 second TTL

        # Circuit breaker for position queries - more tolerant settings
        self._position_circuit_breaker = AsyncCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,  # Increased from 3 to 5, 30s to 60s
        )

        # Exchange info cache with 24h TTL
        self._exchange_info_cache: Dict[str, Dict[str, float]] = {}
        self._cache_timestamp: Optional[datetime] = None

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
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
            # Call Binance API asynchronously
            response = await self.client.request(
                "POST", "/fapi/v1/leverage", signed=True,
                params={"symbol": symbol, "leverage": leverage}
            )

            # Audit log success
            self.audit_logger.log_event(
                event_type=AuditEventType.LEVERAGE_SET,
                operation="set_leverage",
                symbol=symbol,
                response={"leverage": leverage, "status": "success", "api_response": response},
            )

            # Log success
            self.logger.info(f"Leverage successfully set to {leverage}x for {symbol}")
            return True

        except Exception as e:
            # Audit log failure
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_leverage",
                symbol=symbol,
                error=str(e),
            )
            self.logger.error(f"Failed to set leverage for {symbol}: {e}")
            return False

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
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
            # Call Binance API asynchronously
            response = await self.client.request(
                "POST", "/fapi/v1/marginType", signed=True,
                params={"symbol": symbol, "marginType": margin_type}
            )

            # Audit log success
            self.audit_logger.log_event(
                event_type=AuditEventType.MARGIN_TYPE_SET,
                operation="set_margin_type",
                symbol=symbol,
                response={"margin_type": margin_type, "status": "success", "api_response": response},
            )

            # Log success
            self.logger.info(f"Margin type successfully set to {margin_type} for {symbol}")
            return True

        except Exception as e:
            # Error -4046: "No need to change margin type."
            # This is a success case: the exchange is already in the desired state.
            if "-4046" in str(e) or "No need to change margin type" in str(e):
                self.logger.debug(
                    f"Margin type already set to {margin_type} for {symbol}"
                )
                return True

            # Audit log failure
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_margin_type",
                symbol=symbol,
                error=str(e),
            )
            self.logger.error(f"Failed to set margin type for {symbol}: {e}")
            return False

    async def _format_price(self, price: float, symbol: str) -> str:
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
            >>> await manager._format_price(50123.456, 'BTCUSDT')
            '50123.46'  # 2 decimals for BTCUSDT

            >>> await manager._format_price(492.1234, 'BNBUSDT')
            '492.123'  # 3 decimals for BNBUSDT
        """
        # 1. Get symbol-specific tick size (with caching)
        tick_size = await self._get_tick_size(symbol)

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

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def _refresh_exchange_info(self) -> None:
        """Fetch and cache exchange information from Binance."""
        self.logger.info("Fetching exchange information from Binance asynchronously")

        try:
            # Call Binance API to fetch exchange info asynchronously
            exchange_data = await self.client.get_exchange_info()

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

        except Exception as e:
            self.logger.error(f"Failed to fetch exchange info: {e}")
            raise OrderExecutionError(f"Exchange info fetch failed: {e}") from e

    async def refresh_exchange_info(self) -> None:
        """Public method to refresh exchange info cache."""
        await self._refresh_exchange_info()

    async def _get_tick_size(self, symbol: str) -> float:
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
            await self._refresh_exchange_info()

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

    async def _get_step_size(self, symbol: str) -> float:
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
            await self._refresh_exchange_info()

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

    async def _format_quantity(self, quantity: float, symbol: str) -> str:
        """
        Format quantity according to symbol's step size specification.

        Args:
            quantity: Raw quantity value
            symbol: Trading symbol (e.g., 'BTCUSDT')

        Returns:
            Quantity formatted as string with symbol-specific precision

        Example:
            >>> await manager._format_quantity(10.123456, 'XRPUSDT')
            '10.1'  # 1 decimal for XRPUSDT
        """
        # 1. Get symbol-specific step size (with caching)
        step_size = await self._get_step_size(symbol)

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
        self,
        response: Dict[str, Any],
        symbol: str,
        side: OrderSide,
        expected_order_type: Optional[OrderType] = None,
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
            expected_order_type: Optional hint for order type (used for Algo Order API
                responses which may not include type field)

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
            # Algo Order API returns algoId, regular API returns orderId
            order_id = str(order_data.get("algoId") or order_data.get("orderId"))
            status_str = order_data.get("status", "NEW")

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

            # Determine order type from response or use expected type hint
            # Algo Order API responses may not include type field
            if expected_order_type is not None:
                order_type = expected_order_type
            else:
                order_type_str = order_data.get("type", "MARKET")
                order_type = OrderType[order_type_str]

            # Extract stop price for STOP/TP orders
            # Regular API uses "stopPrice", Algo API uses "triggerPrice" or "activatePrice" (for Trailing Stop)
            stop_price = None
            stop_price_str = (
                order_data.get("stopPrice")
                or order_data.get("triggerPrice")
                or order_data.get("activatePrice")
            )
            if stop_price_str:
                stop_price = float(stop_price_str)

            # Extract callbackRate for TRAILING_STOP_MARKET
            callback_rate = None
            callback_rate_str = order_data.get("callbackRate")
            if callback_rate_str:
                callback_rate = float(callback_rate_str)

            # Create Order object
            return Order(
                symbol=symbol,
                side=side,
                order_type=order_type,  # Will be MARKET, STOP_MARKET, or TAKE_PROFIT_MARKET
                quantity=quantity,
                price=avg_price if avg_price > 0 else None,
                stop_price=stop_price,
                callback_rate=callback_rate,
                order_id=order_id,
                client_order_id=order_data.get("clientOrderId"),
                status=status,
                timestamp=timestamp,
            )

        except KeyError as e:
            raise OrderExecutionError(f"Missing required field in API response: {e}")
        except (ValueError, TypeError) as e:
            raise OrderExecutionError(f"Invalid data type in API response: {e}")

    @async_retry_with_backoff(max_retries=3)
    async def _place_sl_order(
        self,
        signal: Signal,
        side: OrderSide,
        adjusted_stop_loss: Optional[float] = None,
    ) -> Optional[Order]:
        """
        Place STOP_MARKET order for position exit.

        Args:
            signal: Trading signal with stop_loss price
            side: Order side to close position (opposite of entry)
            adjusted_stop_loss: Optional pre-adjusted stop loss price

        Returns:
            Order object if successful, None if placement fails

        Note:
            Uses retry decorator to handle transient API failures.
        """
        try:
            # Validate stop_loss exists
            if signal.stop_loss is None:
                self.logger.error(
                    f"Cannot place SL order: stop_loss is None for {signal.symbol}"
                )
                return None

            # Use provided adjusted_stop_loss or original signal.stop_loss
            if adjusted_stop_loss is None:
                adjusted_stop_loss = signal.stop_loss

            # Validate and adjust SL to prevent immediate trigger (code -2021)
            # CRITICAL: Order uses workingType=MARK_PRICE, so validate against mark price
            if adjusted_stop_loss:
                try:
                    mark_price = await self.client.get_mark_price(signal.symbol)
                except Exception as e:
                    self.logger.warning(f"Failed to get mark price, using entry: {e}")
                    mark_price = signal.entry_price if hasattr(signal, "entry_price") else 0.0

                min_buffer = mark_price * 0.002  # 0.2% minimum distance from mark price
                original_stop_loss = adjusted_stop_loss

                # STOP_MARKET trigger logic:
                # - SELL side (closing LONG): triggers when mark price <= stopPrice
                #   → SL must be BELOW mark price
                # - BUY side (closing SHORT): triggers when mark price >= stopPrice
                #   → SL must be ABOVE mark price
                if side == OrderSide.SELL:
                    # Closing LONG - SL must be below mark price
                    if adjusted_stop_loss >= mark_price:
                        adjusted_stop_loss = mark_price - min_buffer
                        self.logger.warning(
                            f"SL (SELL) adjusted: {original_stop_loss:.4f} >= mark {mark_price:.4f}, "
                            f"new SL: {adjusted_stop_loss:.4f}"
                        )
                    elif mark_price - adjusted_stop_loss < min_buffer:
                        adjusted_stop_loss = mark_price - min_buffer
                        self.logger.warning(
                            f"SL (SELL) too close to mark price, adjusted: "
                            f"{original_stop_loss:.4f} → {adjusted_stop_loss:.4f}"
                        )
                else:  # OrderSide.BUY
                    # Closing SHORT - SL must be above mark price
                    if adjusted_stop_loss <= mark_price:
                        adjusted_stop_loss = mark_price + min_buffer
                        self.logger.warning(
                            f"SL (BUY) adjusted: {original_stop_loss:.4f} <= mark {mark_price:.4f}, "
                            f"new SL: {adjusted_stop_loss:.4f}"
                        )
                    elif adjusted_stop_loss - mark_price < min_buffer:
                        adjusted_stop_loss = mark_price + min_buffer
                        self.logger.warning(
                            f"SL (BUY) too close to mark price, adjusted: "
                            f"{original_stop_loss:.4f} → {adjusted_stop_loss:.4f}"
                        )

            # Format stop price for API
            stop_price_str = await self._format_price(adjusted_stop_loss, signal.symbol)

            # Place STOP_MARKET order via Binance Algo Order API
            # Since 2025-12-09, conditional orders require /fapi/v1/algoOrder endpoint
            response = await self.client.new_algo_order(
                symbol=signal.symbol,
                side=side.value,  # SELL for long, BUY for short
                type=OrderType.STOP_MARKET.value,  # "STOP_MARKET"
                triggerPrice=stop_price_str,  # Algo API uses triggerPrice, not stopPrice
                closePosition="true",  # Close entire position
                workingType="MARK_PRICE",  # Use mark price for trigger
            )

            # Parse API response into Order object
            # Pass expected_order_type for Algo API which may not include type field
            order = self._parse_order_response(
                response=response,
                symbol=signal.symbol,
                side=side,
                expected_order_type=OrderType.STOP_MARKET,
            )

            # Override stop_price (response may not have correct value)
            order.stop_price = adjusted_stop_loss

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
                        "stop_price": adjusted_stop_loss,
                        "close_position": True,
                    },
                    response={"order_id": order.order_id, "status": order.status.value},
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            return order

        except Exception as e:
            # Handle -4130: Duplicate TP/SL order with closePosition exists
            if "-4130" in str(e):
                self.logger.warning(
                    f"SL order rejected (-4130): existing algo order with closePosition "
                    f"detected for {signal.symbol}. Attempting to cancel existing algo orders..."
                )
                try:
                    # Cancel existing algo orders (TP/SL) for future attempts
                    algo_results = await self.client.cancel_all_algo_orders(signal.symbol)
                    algo_cancelled = len(algo_results) if algo_results else 0
                    if algo_cancelled > 0:
                        self.logger.info(
                            f"Cancelled {algo_cancelled} existing algo orders for {signal.symbol}. "
                            f"Next signal should succeed."
                        )
                except Exception as cancel_err:
                    self.logger.warning(
                        f"Failed to cancel existing algo orders: {cancel_err}"
                    )

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

    async def update_stop_loss(
        self,
        symbol: str,
        new_stop_price: float,
        side: OrderSide,
    ) -> Optional[Order]:
        """
        Dynamically update Stop Loss order for an open position.
        
        This robust implementation follows a "Fetch -> Filter -> Cancel -> Place" flow:
        1. Query all current open algo orders.
        2. Identify and filter matching STOP_MARKET orders.
        3. Deterministically cancel existing orders (ignoring already-processed errors).
        4. Place new order with collision detection (-4130) and automatic re-sync.
        """
        try:
            # 1. Validation and adjustment logic
            try:
                mark_price = await self.client.get_mark_price(symbol)
            except Exception as e:
                self.logger.warning(f"Failed to get mark price for SL update: {e}")
                return None

            min_buffer = mark_price * 0.001  # 0.1% minimum buffer
            if side == OrderSide.SELL: # Position is LONG, SL must be below mark
                if new_stop_price >= mark_price:
                    self.logger.warning(f"SL update skipped: new SL {new_stop_price:.4f} >= mark {mark_price:.4f}")
                    return None
                if mark_price - new_stop_price < min_buffer:
                    new_stop_price = mark_price - min_buffer
            else: # Position is SHORT, SL must be above mark
                if new_stop_price <= mark_price:
                    self.logger.warning(f"SL update skipped: new SL {new_stop_price:.4f} <= mark {mark_price:.4f}")
                    return None
                if new_stop_price - mark_price < min_buffer:
                    new_stop_price = mark_price + min_buffer

            # 2. Robust SL Sync Logic (Fetch -> Filter -> Cancel -> Place)
            try:
                open_algo_orders = await self.client.get_open_algo_orders(symbol)
                # CRITICAL FIX: Include TRAILING_STOP_MARKET in filter to avoid -4130 collisions
                # Binance only allows one closePosition=true order per side.
                existing_exits = [
                    o for o in open_algo_orders 
                    if o.get("type") in ["STOP", "STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"]
                ]

                for old_order in existing_exits:
                    old_price = float(old_order.get("stopPrice", 0) or old_order.get("triggerPrice", 0))
                    algo_id = str(old_order.get("algoId"))
                    order_type = old_order.get("type")
                    
                    # Only skip if it's the SAME type and SAME price
                    if order_type in ["STOP", "STOP_MARKET"] and abs(old_price - new_stop_price) < 1e-8:
                        self.logger.info(f"Existing SL for {symbol} matches target {new_stop_price}. Skipping update.")
                        return self._parse_order_response(old_order, symbol, side, OrderType.STOP_MARKET)

                    try:
                        await self.client.cancel_algo_order(symbol, algo_id)
                        self.logger.debug(f"Cancelled old {order_type} {algo_id} for {symbol}")
                    except Exception as e:
                        if any(code in str(e) for code in ["-2011", "-4137", "-4138"]):
                            self.logger.warning(f"SL {algo_id} for {symbol} already gone. Proceeding.")
                            continue
                        raise e

            except Exception as e:
                self.logger.error(f"Failed to synchronize existing SL orders for {symbol}: {e}")
                return None

            # 3. Place new SL order with collision handling and retries
            stop_price_str = await self._format_price(new_stop_price, symbol)
            max_place_retries = 5
            
            for attempt in range(max_place_retries + 1):
                try:
                    response = await self.client.new_algo_order(
                        symbol=symbol, side=side.value, type=OrderType.STOP_MARKET.value,
                        triggerPrice=stop_price_str, closePosition="true", workingType="MARK_PRICE"
                    )
                    order = self._parse_order_response(response, symbol, side, OrderType.STOP_MARKET)
                    order.stop_price = new_stop_price
                    self.logger.info(f"SL dynamically updated for {symbol}: new stopPrice={stop_price_str} (Attempt {attempt+1})")
                    
                    try:
                        self.audit_logger.log_order_placed(
                            symbol=symbol,
                            order_data={"order_type": "STOP_MARKET", "side": side.value, "stop_price": new_stop_price, "close_position": True, "update_reason": "trailing_stop_dynamic_update"},
                            response={"order_id": order.order_id, "status": order.status.value},
                        )
                    except Exception: pass
                    return order

                except Exception as e:
                    if "-4130" in str(e) and attempt < max_place_retries:
                        self.logger.warning(f"SL collision (-4130) for {symbol}. Attempting recovery {attempt+1}/{max_place_retries}...")
                        try:
                            fresh = await self.client.get_open_algo_orders(symbol)
                            for o in fresh:
                                # Fix: Include TRAILING_STOP_MARKET to fully clear potential collisions
                                if o.get("type") in ["STOP", "STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"]:
                                    try:
                                        algo_id = str(o.get("algoId"))
                                        await self.client.cancel_algo_order(symbol, algo_id)
                                        self.logger.info(f"Recovery: Cancelled conflicting order {algo_id} for {symbol}")
                                    except Exception: pass
                            await asyncio.sleep(1.5) # Increased delay for engine synchronization
                            continue
                        except Exception: break
                    
                    if "-4112" in str(e):
                        self.logger.critical(f"ReduceOnly rejected for {symbol} SL: {e}")
                        break
                        
                    self.logger.error(f"New SL placement failed for {symbol} (Attempt {attempt+1}): {e}")
                    if attempt < max_place_retries: await asyncio.sleep(0.5 * (attempt + 1))
                    else: break

            return None
        except Exception as e:
            self.logger.error(f"SL dynamic update failed: {e}")
            return None

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def _place_tp_order(
        self,
        signal: Signal,
        side: OrderSide,
        adjusted_take_profit: Optional[float] = None,
    ) -> Optional[Order]:
        """
        Place TAKE_PROFIT_MARKET order for position exit.

        Critical Implementation Details:
        - Price buffer adjustment (0.1% minimum distance)
        - Tick size formatting per symbol specifications
        - Comprehensive audit logging
        - Retry logic with exponential backoff
        - Error handling without raising exceptions
        """
        try:
            # Validate take_profit exists
            if signal.take_profit is None:
                self.logger.error(
                    f"Cannot place TP order: take_profit is None for {signal.symbol}"
                )
                return None

            # Validate and adjust TP to prevent immediate trigger (code -2021)
            # CRITICAL: Order uses workingType=MARK_PRICE, so validate against mark price
            original_take_profit = signal.take_profit
            adjusted_take_profit = original_take_profit

            try:
                mark_price = await self.client.get_mark_price(signal.symbol)
            except Exception as e:
                self.logger.warning(f"Failed to get mark price, using entry: {e}")
                mark_price = signal.entry_price if hasattr(signal, "entry_price") else 0.0

            min_buffer = mark_price * 0.002  # 0.2% minimum distance from mark price

            # TAKE_PROFIT_MARKET trigger logic:
            # - SELL side (closing LONG): triggers when mark price >= stopPrice
            #   → TP must be ABOVE mark price
            # - BUY side (closing SHORT): triggers when mark price <= stopPrice
            #   → TP must be BELOW mark price
            if side == OrderSide.SELL:
                # Closing LONG - TP must be above mark price
                if adjusted_take_profit <= mark_price:
                    adjusted_take_profit = mark_price + min_buffer
                    self.logger.warning(
                        f"TP (SELL) adjusted: {original_take_profit:.4f} <= mark {mark_price:.4f}, "
                        f"new TP: {adjusted_take_profit:.4f}"
                    )
                elif adjusted_take_profit - mark_price < min_buffer:
                    adjusted_take_profit = mark_price + min_buffer
                    self.logger.warning(
                        f"TP (SELL) too close to mark price, adjusted: "
                        f"{original_take_profit:.4f} → {adjusted_take_profit:.4f}"
                    )
            else:  # OrderSide.BUY
                # Closing SHORT - TP must be below mark price
                if adjusted_take_profit >= mark_price:
                    adjusted_take_profit = mark_price - min_buffer
                    self.logger.warning(
                        f"TP (BUY) adjusted: {original_take_profit:.4f} >= mark {mark_price:.4f}, "
                        f"new TP: {adjusted_take_profit:.4f}"
                    )
                elif mark_price - adjusted_take_profit < min_buffer:
                    adjusted_take_profit = mark_price - min_buffer
                    self.logger.warning(
                        f"TP (BUY) too close to mark price, adjusted: "
                        f"{original_take_profit:.4f} → {adjusted_take_profit:.4f}"
                    )

            # Format stop price for API
            stop_price_str = await self._format_price(adjusted_take_profit, signal.symbol)

            # Place TAKE_PROFIT_MARKET order via Binance Algo Order API
            # Since 2025-12-09, conditional orders require /fapi/v1/algoOrder endpoint
            response = await self.client.new_algo_order(
                symbol=signal.symbol,
                side=side.value,  # SELL for long, BUY for short
                type=OrderType.TAKE_PROFIT_MARKET.value,  # "TAKE_PROFIT_MARKET"
                triggerPrice=stop_price_str,  # Algo API uses triggerPrice, not stopPrice
                closePosition="true",  # Close entire position
                workingType="MARK_PRICE",  # Use mark price for trigger
            )

            # Parse API response into Order object
            # Pass expected_order_type for Algo API which may not include type field
            order = self._parse_order_response(
                response=response,
                symbol=signal.symbol,
                side=side,
                expected_order_type=OrderType.TAKE_PROFIT_MARKET,
            )

            # Override stop_price (response may not have correct value)
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

        except Exception as e:
            # Handle -4130: Duplicate TP/SL order with closePosition exists
            if "-4130" in str(e):
                self.logger.warning(
                    f"TP order rejected (-4130): existing algo order with closePosition "
                    f"detected for {signal.symbol}. Attempting to cancel existing algo orders..."
                )
                try:
                    # Cancel existing algo orders (TP/SL) for future attempts
                    algo_results = await self.client.cancel_all_algo_orders(signal.symbol)
                    algo_cancelled = len(algo_results) if algo_results else 0
                    if algo_cancelled > 0:
                        self.logger.info(
                            f"Cancelled {algo_cancelled} existing algo orders for {signal.symbol}. "
                            f"Next signal should succeed."
                        )
                except Exception as cancel_err:
                    self.logger.warning(
                        f"Failed to cancel existing algo orders: {cancel_err}"
                    )

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

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def execute_signal(
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
            >>> entry_order, tpsl_orders = await manager.execute_signal(signal, quantity=0.001)
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
            f"Executing {signal.signal_type.value} signal asynchronously: "
            f"{signal.symbol} {side.value} {quantity} "
            f"(strategy: {signal.strategy_name})"
        )
        # Prepare order parameters for market entry order
        # Format quantity according to symbol's step size (precision)
        formatted_qty = await self._format_quantity(quantity, signal.symbol)

        order_params = {
            "symbol": signal.symbol,
            "side": side.value,
            "type": OrderType.MARKET.value,
            "quantity": formatted_qty,
            "reduceOnly": reduce_only,
        }

        try:
            # Submit market order to Binance asynchronously
            response = await self.client.new_order(**order_params)

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

        except Exception as e:
            # Handle order rejection and execution errors
            self.audit_logger.log_order_rejected(
                symbol=signal.symbol,
                order_data=order_params,
                error=str(e),
            )

            self.logger.error(f"Entry order failed for {signal.symbol}: {e}")
            raise OrderExecutionError(f"Failed to execute order: {e}") from e

        # Check if TP/SL orders are needed
        tpsl_orders: list[Order] = []

        # Determine TP/SL side (opposite of entry side)
        tpsl_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        # Handle different signal types
        if signal.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
            # Entry signals: Cancel existing orders before placing new TP/SL orders
            try:
                cancelled_count = await self.cancel_all_orders(signal.symbol)
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

        # Place TP order
        tp_order = await self._place_tp_order(signal, tpsl_side)
        if tp_order:
            tpsl_orders.append(tp_order)

        # Place SL order
        sl_order = await self._place_sl_order(signal, tpsl_side)
        if sl_order:
            tpsl_orders.append(sl_order)

        # Handle different post-entry processing based on signal type
        if signal.signal_type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            # Close signals: Cancel all remaining TP/SL orders
            try:
                cancelled_count = await self.cancel_all_orders(signal.symbol)
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
        else:
            # Entry signals: TP/SL completeness check with retry + escalation
            tpsl_orders = await self._ensure_tpsl_completeness(
                signal=signal,
                tpsl_orders=tpsl_orders,
                tpsl_side=tpsl_side,
                entry_order=entry_order,
            )

        # Return entry order and TP/SL orders
        return (entry_order, tpsl_orders)

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def get_position(self, symbol: str) -> Optional[Position]:
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
            >>> position = await manager.get_position('BTCUSDT')
            >>> if position:
            ...     print(f"{position.side} position: {position.quantity} @ {position.entry_price}")
            ... else:
            ...     print("No position")
        """
        # 1. Validate input
        if not symbol or not isinstance(symbol, str):
            raise ValidationError(f"Invalid symbol: {symbol}")

        # 2. Log API call
        self.logger.info(f"Querying position for {symbol} asynchronously")

        try:
            # 3. Call Binance API asynchronously through circuit breaker
            response = await self._position_circuit_breaker.call(
                self.client.get_position_risk, symbol=symbol
            )
            self.logger.debug(
                f"get_position_risk response for {symbol}: {type(response)} - {response}"
            )

            # 4. Parse response
            if response is None:
                self.logger.error(f"Position API failed for {symbol} - no response")
                return None

            if isinstance(response, list):
                if len(response) == 0:
                    self.logger.info(f"No active position for {symbol} (empty data)")
                    return None
                position_data = response[0]
            else:
                raise OrderExecutionError(
                    f"Unexpected response type: {type(response).__name__}"
                )

            # Extract position amount
            position_amt = float(position_data.get("positionAmt", 0))

            # 5. Check if position exists
            if position_amt == 0:
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
            unrealized_pnl = float(position_data.get("unRealizedProfit", 0))

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

        except Exception as e:
            # Audit log failure
            try:
                from src.core.audit_logger import AuditEventType
                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="get_position",
                    symbol=symbol,
                    error=str(e),
                )
            except Exception:
                pass

            raise OrderExecutionError(f"Position query failed for {symbol}: {e}") from e
        except (KeyError, ValueError, TypeError) as e:
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

    async def get_account_balance(self) -> float:
        """
        Query USDT wallet balance.

        Retrieves account information from Binance Futures API and extracts
        USDT wallet balance from the assets array.

        Returns:
            USDT wallet balance as float (returns 0.0 if USDT not found)

        Raises:
            OrderExecutionError: API call fails or response parsing error

        Example:
            >>> balance = await manager.get_account_balance()
            >>> print(f"Available USDT: {balance:.2f}")
        """
        # 1. Log API call
        self.logger.info("Querying account balance asynchronously")

        try:
            # 2. Call Binance API asynchronously
            account_data = await self.client.request("GET", "/fapi/v2/account", signed=True)

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

        except Exception as e:
            # Wrap API errors in OrderExecutionError
            error_msg = f"Failed to query account balance: {e}"
            self.logger.error(error_msg)

            # Audit log
            try:
                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="get_account_balance",
                    symbol="GLOBAL",
                    error=str(e),
                )
            except Exception:
                pass

            raise OrderExecutionError(error_msg) from e

    async def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Query all open orders for a symbol.

        Uses Binance REST API: GET /fapi/v1/openOrders

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            List of open order dictionaries with keys:
            - orderId: int
            - symbol: str
            - status: str (e.g., 'NEW')
            - type: str (e.g., 'LIMIT', 'STOP_MARKET')
            - side: str ('BUY' or 'SELL')
            - price: str
            - origQty: str

        Raises:
            ValidationError: Invalid symbol format
            OrderExecutionError: API call fails

        Example:
            >>> orders = await manager.get_open_orders('BTCUSDT')
            >>> for order in orders:
            ...     print(f"Order {order['orderId']}: {order['type']}")
        """
        # Validate input
        if not symbol or not isinstance(symbol, str):
            raise ValidationError(f"Invalid symbol: {symbol}")

        self.logger.debug(f"Querying open orders for {symbol} asynchronously")

        try:
            # Call Binance API asynchronously
            response = await self.client.request(
                "GET", "/fapi/v1/openOrders", signed=True, params={"symbol": symbol}
            )

            if isinstance(response, list):
                self.logger.debug(f"Found {len(response)} open orders for {symbol}")
                return response
            else:
                self.logger.warning(
                    f"Unexpected response format for open orders: {response}"
                )
                return []

        except Exception as e:
            if "Invalid symbol" in str(e):
                raise ValidationError(f"Invalid symbol: {symbol}")
            raise OrderExecutionError(f"Failed to query open orders: {e}")

    async def get_open_orders_cached(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get open orders with caching to reduce API calls.

        Uses cached data if available and not expired.
        Falls back to REST API if cache miss or expired.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')

        Returns:
            List of open order dictionaries (may be from cache)

        Note:
            Cache is invalidated when orders are placed, cancelled, or filled.
            WebSocket ORDER_TRADE_UPDATE events can update the cache in real-time.
        """
        current_time = time.time()

        # Check if cache exists and is still valid
        if symbol in self._open_orders_cache:
            cached_orders, cache_time = self._open_orders_cache[symbol]
            if current_time - cache_time < self._open_orders_cache_ttl:
                self.logger.debug(
                    f"Open orders cache hit for {symbol}: {len(cached_orders)} orders"
                )
                return cached_orders

        # Cache miss or expired - query from API
        try:
            orders = await self.get_open_orders(symbol)
            self._open_orders_cache[symbol] = (orders, current_time)
            return orders
        except Exception as e:
            self.logger.warning(f"Failed to refresh open orders cache for {symbol}: {e}")
            # Return stale cache data if available
            if symbol in self._open_orders_cache:
                cached_orders, _ = self._open_orders_cache[symbol]
                self.logger.debug(
                    f"Returning stale cache for {symbol}: {len(cached_orders)} orders"
                )
                return cached_orders
            raise

    def invalidate_open_orders_cache(self, symbol: str) -> None:
        """
        Invalidate open orders cache for a symbol.

        Called after order operations (place, cancel, fill) to ensure
        fresh data is fetched on next check.

        Args:
            symbol: Trading pair to invalidate cache for
        """
        if symbol in self._open_orders_cache:
            del self._open_orders_cache[symbol]
            self.logger.debug(f"Open orders cache invalidated for {symbol}")

    def update_order_cache_from_websocket(
        self, symbol: str, order_id: str, order_status: str, order_data: Dict[str, Any]
    ) -> None:
        """
        Update open orders cache based on WebSocket ORDER_TRADE_UPDATE events.

        This enables real-time order tracking without REST API calls,
        reducing rate limit pressure (Issue #41 rate limit fix).

        Args:
            symbol: Trading pair
            order_id: Order ID from WebSocket event
            order_status: Order status (NEW, FILLED, CANCELED, etc.)
            order_data: Full order data from WebSocket event
        """
        current_time = time.time()

        # Get current cache or create empty
        if symbol in self._open_orders_cache:
            cached_orders, _ = self._open_orders_cache[symbol]
            cached_orders = list(cached_orders)  # Make a copy
        else:
            cached_orders = []

        # Update cache based on status
        if order_status == "NEW":
            # New order - add to cache if not already present
            existing_ids = {str(o.get("orderId")) for o in cached_orders}
            if order_id not in existing_ids:
                cached_orders.append(order_data)
                self.logger.debug(f"Added order {order_id} to cache for {symbol}")

        elif order_status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
            # Order closed - remove from cache
            cached_orders = [
                o for o in cached_orders if str(o.get("orderId")) != order_id
            ]
            self.logger.debug(
                f"Removed order {order_id} from cache for {symbol} (status: {order_status})"
            )

        elif order_status == "PARTIALLY_FILLED":
            # Update existing order in cache
            for i, order in enumerate(cached_orders):
                if str(order.get("orderId")) == order_id:
                    cached_orders[i] = order_data
                    self.logger.debug(f"Updated order {order_id} in cache for {symbol}")
                    break

        # Update cache with new timestamp
        self._open_orders_cache[symbol] = (cached_orders, current_time)

    async def _cancel_order_by_id(self, symbol: str, order_id: int) -> bool:
        """
        Cancel a single order by its ID.

        Uses Binance REST API: DELETE /fapi/v1/order

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            order_id: The order ID to cancel

        Returns:
            True if cancellation successful, False otherwise

        Example:
            >>> success = await manager._cancel_order_by_id('BTCUSDT', 123456789)
            >>> if success:
            ...     print("Order cancelled")
        """
        try:
            self.logger.debug(f"Cancelling order {order_id} for {symbol} asynchronously")
            response = await self.client.request(
                "DELETE", "/fapi/v1/order", signed=True,
                params={"symbol": symbol, "orderId": order_id}
            )

            # Check if cancelled successfully
            if isinstance(response, dict):
                status = response.get("status", "")
                if status == "CANCELED":
                    self.logger.debug(f"Successfully cancelled order {order_id}")
                    return True
                else:
                    self.logger.debug(f"Order {order_id} status: {status}")
                    return True  # Consider any response as success

            return True

        except Exception as e:
            # Order already cancelled or doesn't exist - not an error
            if "-2011" in str(e) or "-2013" in str(e):
                self.logger.debug(
                    f"Order {order_id} already cancelled or doesn't exist: {e}"
                )
                return True
            else:
                self.logger.warning(
                    f"Failed to cancel order {order_id} for {symbol}: {e}"
                )
                return False

    @async_retry_with_backoff(max_retries=3, initial_delay=1.0)
    async def cancel_all_orders(
        self,
        symbol: str,
        verify: bool = True,
        max_retries: int = 3,
    ) -> int:
        """
        Cancel all open orders for a symbol with optional verification.

        Cancels all active orders for the specified trading symbol using
        Binance Futures API. When verify=True, confirms all orders are
        cancelled and retries if any remain.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            verify: If True, verify all orders cancelled and retry if needed
            max_retries: Maximum retry attempts when verify=True (default: 3)

        Returns:
            Number of orders cancelled

        Raises:
            ValidationError: Invalid symbol format
            OrderExecutionError: API call fails

        Example:
            >>> cancelled_count = await manager.cancel_all_orders('BTCUSDT')
            >>> print(f"Cancelled {cancelled_count} orders")

            >>> # Without verification (legacy behavior)
            >>> cancelled_count = await manager.cancel_all_orders('BTCUSDT', verify=False)
        """
        # 1. Validate input
        if not symbol or not isinstance(symbol, str):
            raise ValidationError(f"Invalid symbol: {symbol}")

        # 2. Check for open orders first to avoid unnecessary API calls (Issue #65, #41)
        # Use cached version to reduce rate limit pressure
        open_orders = None
        try:
            coro = self.get_open_orders_cached(symbol)
            open_orders = await coro
            
            # Defensive check for nested coroutines
            while asyncio.iscoroutine(open_orders):
                self.logger.warning(f"Double await required for get_open_orders_cached on {symbol}")
                open_orders = await open_orders
                
            if not open_orders:
                self.logger.debug(
                    f"No open orders for {symbol}, skipping cancel API call"
                )
                return 0
        except Exception as e:
            # If we can't check, proceed with cancel attempt as fallback
            self.logger.warning(
                f"Failed to check open orders for {symbol}: {e}, "
                f"proceeding with cancel attempt"
            )
            open_orders = None  # Unknown state, proceed with cancel

        # 3. Log API call (only when orders exist)
        num_to_cancel = len(open_orders) if isinstance(open_orders, list) else "all"
        self.logger.info(
            f"Cancelling {num_to_cancel} orders for {symbol}"
        )

        try:
            # 4. Call Binance API (bulk cancel) asynchronously
            response = await self.client.request(
                "DELETE", "/fapi/v1/allOpenOrders", signed=True, params={"symbol": symbol}
            )

            # 5. Parse response
            cancelled_count = 0
            if isinstance(response, list):
                cancelled_count = len(response)
                self.logger.info(f"Cancelled {cancelled_count} orders for {symbol}")
            elif isinstance(response, dict) and response.get("code") == 200:
                cancelled_count = 0
                self.logger.info(
                    f"Success: {response.get('msg', 'Orders cancelled')} for {symbol}"
                )
            else:
                self.logger.warning(f"Unexpected response format: {response}")
                cancelled_count = 0

            # 5.5 Cancel Algo Orders (TP/SL placed via Algo Order API)
            try:
                algo_results = await self.client.cancel_all_algo_orders(symbol)
                algo_cancelled = len(algo_results) if isinstance(algo_results, (list, dict)) else 0
                if algo_cancelled > 0:
                    self.logger.info(
                        f"Cancelled {algo_cancelled} algo orders (TP/SL) for {symbol}"
                    )
                    cancelled_count += algo_cancelled
            except Exception as e:
                self.logger.debug(f"Algo order cancellation note: {e}")

            # 6. Invalidate cache after cancel API call
            self.invalidate_open_orders_cache(symbol)

            # 7. Verification loop (if enabled)
            if verify:
                for attempt in range(max_retries):
                    try:
                        if attempt > 0:
                            await asyncio.sleep(0.5)

                        remaining = await self.get_open_orders(symbol)
                        self._open_orders_cache[symbol] = (remaining, time.time())

                        if not remaining:
                            self.logger.debug(
                                f"Verification passed: all orders cancelled for {symbol}"
                            )
                            break

                        self.logger.warning(
                            f"Verification attempt {attempt + 1}/{max_retries}: "
                            f"{len(remaining)} orders still open for {symbol}"
                        )

                        for order in remaining:
                            order_id = order.get("orderId")
                            if order_id:
                                if await self._cancel_order_by_id(symbol, order_id):
                                    cancelled_count += 1

                    except Exception as e:
                        if "-1003" in str(e):
                            self.logger.warning(
                                f"Rate limited during verification, skipping: {e}"
                            )
                            break
                        self.logger.warning(
                            f"Verification attempt {attempt + 1} failed: {e}"
                        )

            # Audit log: order cancellation
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.ORDER_CANCELLED,
                    operation="cancel_all_orders",
                    symbol=symbol,
                    response={
                        "cancelled_count": cancelled_count,
                        "verified": verify,
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

        except Exception as e:
            if "Invalid symbol" in str(e):
                raise ValidationError(f"Invalid symbol: {symbol}")
            raise OrderExecutionError(f"Failed to cancel orders: {e}")

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
            # Call Binance API asynchronously without symbol parameter to get all positions
            response = await self.client.get_position_risk()

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

        except Exception as e:
            # Audit log failure
            try:
                from src.core.audit_logger import AuditEventType
                self.audit_logger.log_event(
                    event_type=AuditEventType.API_ERROR,
                    operation="get_all_positions",
                    error=str(e),
                )
            except Exception:
                pass

            raise OrderExecutionError(f"Position query failed: {e}")

    async def _ensure_tpsl_completeness(
        self,
        signal: Signal,
        tpsl_orders: list[Order],
        tpsl_side: OrderSide,
        entry_order: Order,
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ) -> list[Order]:
        """Ensure both TP and SL orders are placed after entry.

        Retries missing orders up to max_retries times. If still incomplete,
        escalates to emergency market close (reduce_only=True).

        Args:
            signal: Original trading signal
            tpsl_orders: Currently placed TP/SL orders
            tpsl_side: Side for TP/SL orders (opposite of entry)
            entry_order: The filled entry order
            max_retries: Maximum retry attempts (default 2)
            retry_delay: Seconds between retries (default 1.0)

        Returns:
            Updated list of TP/SL orders (may be empty if emergency close triggered)
        """
        if len(tpsl_orders) >= 2:
            self.logger.info("TP/SL placement complete: 2/2 orders placed")
            return tpsl_orders

        self.logger.warning(
            f"Partial TP/SL placement: {len(tpsl_orders)}/2 orders placed. "
            f"Retrying missing orders (max {max_retries} attempts)."
        )

        # Identify what's missing
        has_tp = any(
            o.order_type in (OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT)
            for o in tpsl_orders
        )
        has_sl = any(
            o.order_type in (OrderType.STOP_MARKET, OrderType.STOP)
            for o in tpsl_orders
        )

        for attempt in range(1, max_retries + 1):
            await asyncio.sleep(retry_delay)
            self.logger.info(
                f"TP/SL retry attempt {attempt}/{max_retries} for {signal.symbol}"
            )

            if not has_tp:
                tp_order = await self._place_tp_order(signal, tpsl_side)
                if tp_order:
                    tpsl_orders.append(tp_order)
                    has_tp = True
                    self.logger.info("TP order placed on retry")

            if not has_sl:
                sl_order = await self._place_sl_order(signal, tpsl_side)
                if sl_order:
                    tpsl_orders.append(sl_order)
                    has_sl = True
                    self.logger.info("SL order placed on retry")

            if len(tpsl_orders) >= 2:
                self.logger.info(
                    f"TP/SL placement complete after {attempt} retry: "
                    f"2/2 orders placed"
                )
                return tpsl_orders

        # All retries exhausted — escalate to emergency close
        self.logger.error(
            f"CRITICAL: TP/SL placement failed after {max_retries} retries "
            f"for {signal.symbol}. Only {len(tpsl_orders)}/2 placed. "
            f"Executing emergency market close."
        )

        # Determine close side (opposite of entry)
        close_side = "SELL" if entry_order.side == OrderSide.BUY else "BUY"
        qty = entry_order.quantity

        try:
            # Use the already updated async execute_market_close
            result = await self.execute_market_close(
                symbol=signal.symbol,
                position_amt=qty,
                side=close_side,
                reduce_only=True,
            )

            if result.get("success"):
                self.logger.warning(
                    f"Emergency close executed for {signal.symbol}: "
                    f"order_id={result.get('order_id')}"
                )
                # Cancel any partial TP/SL that were placed
                try:
                    await self.cancel_all_orders(signal.symbol)
                except Exception:
                    pass

                # Audit log emergency close
                try:
                    self.audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="ensure_tpsl_completeness",
                        symbol=signal.symbol,
                        response={
                            "reason": "incomplete_tpsl_emergency_close",
                            "placed_count": len(tpsl_orders),
                            "retry_attempts": max_retries,
                            "close_order_id": result.get("order_id"),
                        },
                    )
                except Exception:
                    pass

                return []  # Empty — position was closed
            else:
                self.logger.error(
                    f"Emergency close FAILED for {signal.symbol}: "
                    f"{result.get('error')}. Manual intervention required!"
                )
        except Exception as e:
            self.logger.error(
                f"Emergency close exception for {signal.symbol}: {e}. "
                f"Manual intervention required!"
            )

        return tpsl_orders

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
            # Place market order with reduceOnly asynchronously
            response = await self.client.new_order(
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
            # Extract execution price for realized PnL calculation
            avg_price = float(order_data.get("avgPrice", "0"))
            executed_qty = float(order_data.get("executedQty", "0"))

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
                        "avg_price": avg_price,
                        "executed_qty": executed_qty,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            self.logger.info(
                f"Position close order executed: ID={order_id}, status={status}, avgPrice={avg_price}"
            )

            return {
                "success": True,
                "order_id": order_id,
                "status": status,
                "avg_price": avg_price,
                "executed_qty": executed_qty,
            }

        except Exception as e:
            # Audit log rejection
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.ORDER_REJECTED,
                    operation="execute_market_close",
                    symbol=symbol,
                    error=str(e),
                )
            except Exception:
                pass

            self.logger.error(
                f"Market close order error for {symbol}: {e}"
            )

            return {
                "success": False,
                "error": str(e),
            }

