"""
Order execution and management with Binance Futures API integration.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from binance.um_futures import UMFutures
from binance.error import ClientError, ServerError

from src.models.order import Order, OrderSide, OrderType, OrderStatus
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.core.exceptions import (
    OrderExecutionError,
    ValidationError,
    OrderRejectedError
)
from src.core.retry import retry_with_backoff
from src.core.audit_logger import AuditLogger, AuditEventType


class RequestWeightTracker:
    """
    Tracks API request weight to prevent rate limit violations.

    Binance provides weight usage in response headers when client is initialized
    with show_limit_usage=True. This tracker monitors the usage and warns when
    approaching limits.

    Attributes:
        current_weight: Current weight used in 1-minute window
        weight_limit: Maximum weight allowed per minute (default: 2400)
        last_reset: Timestamp of last weight reset
    """

    def __init__(self):
        """Initialize weight tracker."""
        self.current_weight = 0
        self.weight_limit = 2400  # Binance limit: 2400 requests/minute
        self.last_reset = datetime.now()
        self.logger = logging.getLogger(__name__)

    def update_from_response(self, response_headers: Optional[Dict] = None):
        """
        Update weight tracking from API response headers.

        Binance returns weight information in headers:
        - 'X-MBX-USED-WEIGHT-1M': Current weight used in 1-minute window

        Args:
            response_headers: Response headers from Binance API
        """
        if not response_headers:
            return

        # Extract weight from headers
        weight_str = response_headers.get('X-MBX-USED-WEIGHT-1M')
        if weight_str:
            try:
                self.current_weight = int(weight_str)

                # Log warning if approaching limit (80% threshold)
                if self.current_weight > self.weight_limit * 0.8:
                    self.logger.warning(
                        f"Approaching rate limit: {self.current_weight}/{self.weight_limit} "
                        f"({self.current_weight / self.weight_limit * 100:.1f}%)"
                    )
            except ValueError:
                self.logger.error(f"Invalid weight value in header: {weight_str}")

    def check_limit(self) -> bool:
        """
        Check if we're approaching rate limit.

        Returns:
            True if safe to proceed, False if should wait
        """
        # Allow up to 90% of limit
        return self.current_weight < self.weight_limit * 0.9

    def get_status(self) -> Dict[str, Any]:
        """
        Get current weight tracking status.

        Returns:
            Dictionary with weight usage information
        """
        return {
            'current_weight': self.current_weight,
            'weight_limit': self.weight_limit,
            'usage_percent': (self.current_weight / self.weight_limit * 100),
            'safe_to_proceed': self.check_limit()
        }


class OrderExecutionManager:
    """
    Binance Futures 주문 실행 관리자.

    Market 주문 실행, TP/SL 자동 배치, 포지션 관리, 레버리지 설정 등을 담당합니다.

    Attributes:
        client (UMFutures): Binance UMFutures REST API 클라이언트
        logger (logging.Logger): 로거 인스턴스
        _open_orders (Dict[str, List[Order]]): 오픈 주문 추적 (심볼별)

    Example:
        >>> # 환경변수 사용 (권장)
        >>> manager = OrderExecutionManager(is_testnet=True)

        >>> # 직접 키 제공
        >>> manager = OrderExecutionManager(
        ...     api_key='your_key',
        ...     api_secret='your_secret',
        ...     is_testnet=False
        ... )

        >>> # 레버리지 설정
        >>> manager.set_leverage('BTCUSDT', 10)
        True

        >>> # 마진 타입 설정
        >>> manager.set_margin_type('BTCUSDT', 'ISOLATED')
        True
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        is_testnet: bool = True
    ) -> None:
        """
        OrderExecutionManager 초기화.

        API 키는 환경변수(BINANCE_API_KEY, BINANCE_API_SECRET)에서 자동으로 로드되며,
        파라미터로 전달하여 override할 수 있습니다.

        Args:
            api_key: Binance API 키 (None이면 환경변수 BINANCE_API_KEY 사용)
            api_secret: Binance API 시크릿 (None이면 환경변수 BINANCE_API_SECRET 사용)
            is_testnet: Testnet 사용 여부 (기본값: True)

        Raises:
            ValueError: API 키 또는 시크릿이 제공되지 않은 경우

        Example:
            >>> # 환경변수 사용
            >>> import os
            >>> os.environ['BINANCE_API_KEY'] = 'your_key'
            >>> os.environ['BINANCE_API_SECRET'] = 'your_secret'
            >>> manager = OrderExecutionManager(is_testnet=True)

            >>> # 직접 키 제공 (테스트 용도)
            >>> manager = OrderExecutionManager(
            ...     api_key='test_key',
            ...     api_secret='test_secret',
            ...     is_testnet=True
            ... )
        """
        # API 키 로딩 (환경변수 우선, 파라미터로 override 가능)
        api_key_value = api_key or os.getenv('BINANCE_API_KEY')
        api_secret_value = api_secret or os.getenv('BINANCE_API_SECRET')

        # 필수 검증
        if not api_key_value or not api_secret_value:
            raise ValueError(
                "API credentials required. "
                "Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables, "
                "or pass api_key and api_secret parameters."
            )

        # Base URL 선택
        base_url = (
            "https://testnet.binancefuture.com"
            if is_testnet
            else "https://fapi.binance.com"
        )

        # UMFutures 클라이언트 초기화 (Task 6.6: enable weight tracking)
        self.client = UMFutures(
            key=api_key_value,
            secret=api_secret_value,
            base_url=base_url,
            show_limit_usage=True  # Enable weight usage tracking in headers
        )

        # 로거 설정
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        # 상태 초기화
        self._open_orders: Dict[str, List[Order]] = {}

        # Exchange info cache (Task 6.5)
        self._exchange_info_cache: Dict[str, Dict[str, float]] = {}
        self._cache_timestamp: Optional[datetime] = None

        # Task 6.6: Initialize audit logger and weight tracker
        self.audit_logger = AuditLogger(log_dir='logs/audit')
        self.weight_tracker = RequestWeightTracker()

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        심볼의 레버리지 설정.

        Binance Futures는 심볼별로 레버리지를 설정할 수 있으며,
        1x부터 125x까지 지원합니다 (심볼에 따라 다름).

        Args:
            symbol: 거래 쌍 (예: 'BTCUSDT', 'ETHUSDT')
            leverage: 레버리지 배수 (1-125)

        Returns:
            성공 여부 (True: 성공, False: 실패)

        Note:
            - Hedge Mode에서는 LONG과 SHORT 포지션이 동일한 레버리지를 사용합니다.
            - 레버리지 변경은 오픈 포지션이 없을 때 권장됩니다.
            - Task 6.6: Retry logic with exponential backoff on transient failures

        Example:
            >>> manager.set_leverage('BTCUSDT', 10)
            True

            >>> manager.set_leverage('ETHUSDT', 20)
            True

            >>> # 잘못된 레버리지 (API가 거부)
            >>> manager.set_leverage('BTCUSDT', 200)
            False
        """
        try:
            # Binance API 호출
            response = self.client.change_leverage(
                symbol=symbol,
                leverage=leverage
            )

            # Task 6.6: Update weight tracker from response headers
            if hasattr(response, 'headers'):
                self.weight_tracker.update_from_response(response.headers)

            # Task 6.6: Audit log success
            self.audit_logger.log_event(
                event_type=AuditEventType.LEVERAGE_SET,
                operation="set_leverage",
                symbol=symbol,
                response={'leverage': leverage, 'status': 'success'}
            )

            # 성공 로깅
            self.logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True

        except ClientError as e:
            # Task 6.6: Audit log error
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_leverage",
                symbol=symbol,
                error={
                    'status_code': e.status_code,
                    'error_code': e.error_code,
                    'error_message': e.error_message
                }
            )

            # Binance API 오류 (4xx)
            self.logger.error(
                f"Failed to set leverage for {symbol}: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            return False

        except ServerError as e:
            # Task 6.6: Handle server errors
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_leverage",
                symbol=symbol,
                error={
                    'status_code': e.status_code,
                    'message': e.message
                }
            )

            self.logger.error(
                f"Server error setting leverage for {symbol}: "
                f"status={e.status_code}, msg={e.message}"
            )
            return False

        except Exception as e:
            # 예상치 못한 오류
            self.logger.error(
                f"Unexpected error setting leverage for {symbol}: {e}"
            )
            return False

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def set_margin_type(
        self,
        symbol: str,
        margin_type: str = 'ISOLATED'
    ) -> bool:
        """
        마진 타입 설정 (ISOLATED 또는 CROSSED).

        - ISOLATED: 포지션별로 독립적인 마진 사용
        - CROSSED: 계좌 전체 잔고를 마진으로 사용

        Args:
            symbol: 거래 쌍 (예: 'BTCUSDT')
            margin_type: 'ISOLATED' 또는 'CROSSED' (기본값: 'ISOLATED')

        Returns:
            성공 여부 (True: 성공, False: 실패)

        Note:
            - 이미 설정된 마진 타입으로 변경 시도 시 "No need to change" 에러는 무시됩니다.
            - Hedge Mode에서는 LONG과 SHORT 포지션이 동일한 마진 타입을 사용합니다.
            - ISOLATED 마진에서는 LONG과 SHORT가 독립적인 마진을 가집니다.
            - Task 6.6: Retry logic with exponential backoff on transient failures

        Example:
            >>> # ISOLATED 마진 설정 (권장)
            >>> manager.set_margin_type('BTCUSDT', 'ISOLATED')
            True

            >>> # CROSSED 마진 설정
            >>> manager.set_margin_type('ETHUSDT', 'CROSSED')
            True

            >>> # 이미 설정된 경우 (여전히 True 반환)
            >>> manager.set_margin_type('BTCUSDT', 'ISOLATED')
            True
        """
        try:
            # Binance API 호출
            response = self.client.change_margin_type(
                symbol=symbol,
                marginType=margin_type
            )

            # Task 6.6: Update weight tracker
            if hasattr(response, 'headers'):
                self.weight_tracker.update_from_response(response.headers)

            # Task 6.6: Audit log success
            self.audit_logger.log_event(
                event_type=AuditEventType.MARGIN_TYPE_SET,
                operation="set_margin_type",
                symbol=symbol,
                response={'margin_type': margin_type, 'status': 'success'}
            )

            # 성공 로깅
            self.logger.info(f"Margin type set to {margin_type} for {symbol}")
            return True

        except ClientError as e:
            # "No need to change" 에러는 성공으로 간주
            if 'No need to change margin type' in e.error_message:
                self.logger.debug(
                    f"Margin type already set to {margin_type} for {symbol}"
                )
                return True

            # Task 6.6: Audit log error
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_margin_type",
                symbol=symbol,
                error={
                    'status_code': e.status_code,
                    'error_code': e.error_code,
                    'error_message': e.error_message
                }
            )

            # 다른 ClientError는 실패
            self.logger.error(
                f"Failed to set margin type for {symbol}: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            return False

        except ServerError as e:
            # Task 6.6: Handle server errors
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="set_margin_type",
                symbol=symbol,
                error={
                    'status_code': e.status_code,
                    'message': e.message
                }
            )

            self.logger.error(
                f"Server error setting margin type for {symbol}: "
                f"status={e.status_code}, msg={e.message}"
            )
            return False

        except Exception as e:
            # 예상치 못한 오류
            self.logger.error(
                f"Unexpected error setting margin type for {symbol}: {e}"
            )
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
        tick_str = f"{tick_size:.10f}".rstrip('0')  # Remove trailing zeros

        if '.' not in tick_str:
            return 0  # Integer tick size

        # Count digits after decimal point
        decimal_part = tick_str.split('.')[1]
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
            # 1. Call Binance API
            response = self.client.exchange_info()

            # Task 6.6: Update weight tracker
            if hasattr(response, 'headers'):
                self.weight_tracker.update_from_response(response.headers)

            # 2. Parse symbols and extract tick sizes
            symbols_parsed = 0
            for symbol_data in response['symbols']:
                symbol = symbol_data['symbol']

                # Find PRICE_FILTER
                price_filter = None
                for filter_item in symbol_data['filters']:
                    if filter_item['filterType'] == 'PRICE_FILTER':
                        price_filter = filter_item
                        break

                if price_filter:
                    tick_size = float(price_filter['tickSize'])
                    self._exchange_info_cache[symbol] = {
                        'tickSize': tick_size,
                        'minPrice': float(price_filter['minPrice']),
                        'maxPrice': float(price_filter['maxPrice'])
                    }
                    symbols_parsed += 1

            # 3. Update cache timestamp
            self._cache_timestamp = datetime.now()

            self.logger.info(
                f"Exchange info cached: {symbols_parsed} symbols loaded"
            )

        except ClientError as e:
            # Task 6.6: Audit log error
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="_refresh_exchange_info",
                error={
                    'status_code': e.status_code,
                    'error_code': e.error_code,
                    'error_message': e.error_message
                }
            )

            self.logger.error(f"Failed to fetch exchange info: {e}")
            raise OrderExecutionError(
                f"Exchange info fetch failed: code={e.error_code}, msg={e.error_message}"
            )

        except ServerError as e:
            # Task 6.6: Handle server errors
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="_refresh_exchange_info",
                error={
                    'status_code': e.status_code,
                    'message': e.message
                }
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
            tick_size = self._exchange_info_cache[symbol]['tickSize']
            self.logger.debug(f"Cache hit for {symbol}: tickSize={tick_size}")
            return tick_size

        # 3. Symbol not found - graceful fallback
        self.logger.warning(
            f"Symbol {symbol} not found in exchange info. "
            f"Using default tickSize=0.01 (2 decimals). "
            f"This may cause order rejection for non-standard pairs."
        )
        return 0.01  # Default for USDT pairs

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
            raise ValidationError(
                f"Unknown signal type: {signal.signal_type}"
            )

        return mapping[signal.signal_type]

    def _parse_order_response(
        self,
        response: Dict[str, Any],
        symbol: str,
        side: OrderSide
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
            # Extract required fields
            order_id = str(response["orderId"])
            status_str = response["status"]

            # For MARKET orders: origQty is filled quantity
            # For STOP/TP orders: origQty may be "0" when using closePosition
            quantity = float(response.get("origQty", "0"))

            # Parse execution price (avgPrice for market orders)
            avg_price = float(response.get("avgPrice", "0"))

            # Convert timestamp (milliseconds → datetime)
            timestamp_ms = response["updateTime"]
            timestamp = datetime.fromtimestamp(
                timestamp_ms / 1000,
                tz=timezone.utc
            )

            # Map Binance status string to OrderStatus enum
            status = OrderStatus[status_str]  # Raises KeyError if invalid

            # Determine order type from response
            order_type_str = response.get("type", "MARKET")
            order_type = OrderType[order_type_str]

            # Extract stop price for STOP/TP orders
            stop_price = None
            if "stopPrice" in response and response["stopPrice"]:
                stop_price = float(response["stopPrice"])

            # Create Order object
            return Order(
                symbol=symbol,
                side=side,
                order_type=order_type,  # Will be MARKET, STOP_MARKET, or TAKE_PROFIT_MARKET
                quantity=quantity,
                price=avg_price if avg_price > 0 else None,
                stop_price=stop_price,
                order_id=order_id,
                client_order_id=response.get("clientOrderId"),
                status=status,
                timestamp=timestamp
            )

        except KeyError as e:
            raise OrderExecutionError(
                f"Missing required field in API response: {e}"
            )
        except (ValueError, TypeError) as e:
            raise OrderExecutionError(
                f"Invalid data type in API response: {e}"
            )

    def _place_tp_order(
        self,
        signal: Signal,
        side: OrderSide
    ) -> Optional[Order]:
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
                side=side.value,                      # SELL for long, BUY for short
                type=OrderType.TAKE_PROFIT_MARKET.value,  # "TAKE_PROFIT_MARKET"
                stopPrice=stop_price_str,             # Trigger price (formatted)
                closePosition="true",                 # Close entire position
                workingType="MARK_PRICE"              # Use mark price for trigger
            )

            # Parse API response into Order object
            order = self._parse_order_response(
                response=response,
                symbol=signal.symbol,
                side=side
            )

            # Override order_type and stop_price (response may not have correct values)
            order.order_type = OrderType.TAKE_PROFIT_MARKET
            order.stop_price = signal.take_profit

            # Log successful placement
            self.logger.info(
                f"TP order placed: ID={order.order_id}, "
                f"stopPrice={stop_price_str}"
            )

            return order

        except ClientError as e:
            # Binance API error (4xx) - log but don't raise
            self.logger.error(
                f"TP order rejected: code={e.error_code}, "
                f"msg={e.error_message}"
            )
            return None

        except Exception as e:
            # Unexpected error - log but don't raise
            self.logger.error(
                f"TP order placement failed: {type(e).__name__}: {e}"
            )
            return None

    def _place_sl_order(
        self,
        signal: Signal,
        side: OrderSide
    ) -> Optional[Order]:
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
                side=side.value,                      # SELL for long, BUY for short
                type=OrderType.STOP_MARKET.value,     # "STOP_MARKET"
                stopPrice=stop_price_str,             # Trigger price (formatted)
                closePosition="true",                 # Close entire position
                workingType="MARK_PRICE"              # Use mark price for trigger
            )

            # Parse API response into Order object
            order = self._parse_order_response(
                response=response,
                symbol=signal.symbol,
                side=side
            )

            # Override order_type and stop_price
            order.order_type = OrderType.STOP_MARKET
            order.stop_price = signal.stop_loss

            # Log successful placement
            self.logger.info(
                f"SL order placed: ID={order.order_id}, "
                f"stopPrice={stop_price_str}"
            )

            return order

        except ClientError as e:
            # Binance API error - log but don't raise
            self.logger.error(
                f"SL order rejected: code={e.error_code}, "
                f"msg={e.error_message}"
            )
            return None

        except Exception as e:
            # Unexpected error - log but don't raise
            self.logger.error(
                f"SL order placement failed: {type(e).__name__}: {e}"
            )
            return None

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def execute_signal(
        self,
        signal: Signal,
        quantity: float,
        reduce_only: bool = False
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
            Task 6.6: Retry logic with exponential backoff on transient failures.

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
        # 1. Validate inputs
        if quantity <= 0:
            raise ValidationError(f"Quantity must be > 0, got {quantity}")

        # 2. Determine order side from signal type
        side = self._determine_order_side(signal)

        # 3. Log order intent
        self.logger.info(
            f"Executing {signal.signal_type.value} signal: "
            f"{signal.symbol} {side.value} {quantity} "
            f"(strategy: {signal.strategy_name})"
        )

        # 4-6. Place market entry order (existing logic from 6.2)
        # Prepare order data for audit logging
        order_params = {
            'symbol': signal.symbol,
            'side': side.value,
            'type': OrderType.MARKET.value,
            'quantity': quantity,
            'reduceOnly': reduce_only
        }

        try:
            response = self.client.new_order(**order_params)

            # Task 6.6: Update weight tracker
            if hasattr(response, 'headers'):
                self.weight_tracker.update_from_response(response.headers)

            # Parse API response into Order object
            entry_order = self._parse_order_response(
                response=response,
                symbol=signal.symbol,
                side=side
            )

            # Task 6.6: Audit log successful order
            self.audit_logger.log_order_placed(
                symbol=signal.symbol,
                order_data=order_params,
                response={
                    'order_id': entry_order.order_id,
                    'status': entry_order.status.value,
                    'price': str(entry_order.price),
                    'quantity': str(entry_order.quantity)
                }
            )

            # Log successful execution
            self.logger.info(
                f"Entry order executed: ID={entry_order.order_id}, "
                f"status={entry_order.status.value}, "
                f"filled={entry_order.quantity} @ {entry_order.price}"
            )

        except ClientError as e:
            # Task 6.6: Audit log order rejection
            self.audit_logger.log_order_rejected(
                symbol=signal.symbol,
                order_data=order_params,
                error={
                    'status_code': e.status_code,
                    'error_code': e.error_code,
                    'error_message': e.error_message
                }
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
            # Task 6.6: Handle server errors
            self.audit_logger.log_event(
                event_type=AuditEventType.API_ERROR,
                operation="execute_signal",
                symbol=signal.symbol,
                order_data=order_params,
                error={
                    'status_code': e.status_code,
                    'message': e.message
                }
            )

            self.logger.error(
                f"Binance server error placing order: "
                f"status={e.status_code}, msg={e.message}"
            )
            raise OrderExecutionError(
                f"Binance server error: {e.message}"
            ) from e

        except Exception as e:
            # Unexpected errors (network, parsing, etc.)
            self.logger.error(
                f"Entry order execution failed: {type(e).__name__}: {e}"
            )
            raise OrderExecutionError(
                f"Failed to execute order: {e}"
            ) from e

        # 7. Check if TP/SL orders are needed
        tpsl_orders: list[Order] = []

        # Only place TP/SL for entry signals (not for close signals)
        if signal.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
            # 8a. Determine TP/SL side (opposite of entry side)
            # For LONG_ENTRY: entry is BUY → TP/SL are SELL
            # For SHORT_ENTRY: entry is SELL → TP/SL are BUY
            tpsl_side = (
                OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
            )

            # 8b. Place TP order
            tp_order = self._place_tp_order(signal, tpsl_side)
            if tp_order:
                tpsl_orders.append(tp_order)

            # 8c. Place SL order
            sl_order = self._place_sl_order(signal, tpsl_side)
            if sl_order:
                tpsl_orders.append(sl_order)

            # 8e. Log TP/SL summary
            self.logger.info(
                f"TP/SL placement complete: {len(tpsl_orders)}/2 orders placed"
            )

            if len(tpsl_orders) < 2:
                self.logger.warning(
                    f"Partial TP/SL placement: entry filled but "
                    f"only {len(tpsl_orders)}/2 exit orders placed"
                )

        # 9. Return entry order and TP/SL orders
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

        # 2. Log API call
        self.logger.info(f"Querying position for {symbol}")

        try:
            # 3. Call Binance API
            response = self.client.get_position_risk(symbol=symbol)

            # 4. Parse response
            if not response or len(response) == 0:
                self.logger.warning(f"No position data returned for {symbol}")
                return None

            position_data = response[0]  # First element
            position_amt = float(position_data["positionAmt"])

            # 5. Check if position exists
            if position_amt == 0:
                self.logger.info(f"No active position for {symbol}")
                return None

            # 6. Determine position side
            side = "LONG" if position_amt > 0 else "SHORT"
            quantity = abs(position_amt)

            # 7. Extract required fields
            entry_price = float(position_data["entryPrice"])
            leverage = int(position_data["leverage"])
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
                liquidation_price=liquidation_price
            )

            self.logger.info(
                f"Position retrieved: {side} {quantity} {symbol} @ {entry_price}, "
                f"PnL: {unrealized_pnl}"
            )

            return position

        except ClientError as e:
            # Handle Binance API errors
            if e.error_code == -1121:
                raise ValidationError(f"Invalid symbol: {symbol}")
            elif e.error_code == -2015:
                raise OrderExecutionError(f"API authentication failed: {e.error_message}")
            else:
                raise OrderExecutionError(
                    f"Position query failed: code={e.error_code}, msg={e.error_message}"
                )
        except (KeyError, ValueError, TypeError) as e:
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

            # 3. Extract assets array
            if "assets" not in response:
                raise OrderExecutionError("Account response missing 'assets' field")

            assets = response["assets"]

            # 4. Find USDT balance
            usdt_balance = None

            for asset in assets:
                if asset.get("asset") == "USDT":
                    usdt_balance = float(asset["walletBalance"])
                    break

            if usdt_balance is None:
                # USDT not found in assets array
                self.logger.warning("USDT not found in account assets, returning 0.0")
                return 0.0

            # 5. Log and return
            self.logger.info(f"USDT balance: {usdt_balance:.2f}")
            return usdt_balance

        except ClientError as e:
            # Handle Binance API errors
            if e.error_code == -2015:
                raise OrderExecutionError(f"API authentication failed: {e.error_message}")
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

            # 4. Parse response
            cancelled_count = 0

            if isinstance(response, list):
                # Response is a list of cancelled order objects
                cancelled_count = len(response)
                self.logger.info(f"Cancelled {cancelled_count} orders for {symbol}")
            elif isinstance(response, dict) and response.get("code") == 200:
                # Response is a success message (no orders to cancel)
                cancelled_count = 0
                self.logger.info(f"No open orders to cancel for {symbol}")
            else:
                # Unexpected response format
                self.logger.warning(f"Unexpected response format: {response}")
                cancelled_count = 0

            return cancelled_count

        except ClientError as e:
            # Handle Binance API errors
            if e.error_code == -1121:
                raise ValidationError(f"Invalid symbol: {symbol}")
            elif e.error_code == -2015:
                raise OrderExecutionError(f"API authentication failed: {e.error_message}")
            else:
                raise OrderExecutionError(
                    f"Order cancellation failed: code={e.error_code}, msg={e.error_message}"
                )
        except Exception as e:
            raise OrderExecutionError(f"Unexpected error during order cancellation: {e}")
