"""
Order execution and management with Binance Futures API integration.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from binance.um_futures import UMFutures
from binance.error import ClientError

from src.models.order import Order, OrderSide, OrderType, OrderStatus
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.core.exceptions import (
    OrderExecutionError,
    ValidationError,
    OrderRejectedError
)


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

        # UMFutures 클라이언트 초기화
        self.client = UMFutures(
            key=api_key_value,
            secret=api_secret_value,
            base_url=base_url
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
            self.client.change_leverage(
                symbol=symbol,
                leverage=leverage
            )

            # 성공 로깅
            self.logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True

        except ClientError as e:
            # Binance API 오류 (4xx)
            self.logger.error(
                f"Failed to set leverage for {symbol}: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            return False

        except Exception as e:
            # 예상치 못한 오류
            self.logger.error(
                f"Unexpected error setting leverage for {symbol}: {e}"
            )
            return False

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
            self.client.change_margin_type(
                symbol=symbol,
                marginType=margin_type
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

            # 다른 ClientError는 실패
            self.logger.error(
                f"Failed to set margin type for {symbol}: "
                f"code={e.error_code}, msg={e.error_message}"
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
        Format price to appropriate decimal precision for Binance API.

        Args:
            price: Raw price value
            symbol: Trading symbol (e.g., 'BTCUSDT')

        Returns:
            Price formatted as string with 2 decimal places

        Note:
            Subtask 6.5 will implement dynamic precision based on symbol.
            For now, assumes USDT pairs require 2 decimal places.

        Example:
            >>> manager._format_price(50123.456, 'BTCUSDT')
            '50123.46'
        """
        # Fixed 2 decimal precision for USDT pairs
        # TODO (6.5): Fetch precision from exchange info API
        return f"{price:.2f}"

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
        try:
            response = self.client.new_order(
                symbol=signal.symbol,
                side=side.value,           # "BUY" or "SELL"
                type=OrderType.MARKET.value,  # "MARKET"
                quantity=quantity,
                reduceOnly=reduce_only
            )

            # Parse API response into Order object
            entry_order = self._parse_order_response(
                response=response,
                symbol=signal.symbol,
                side=side
            )

            # Log successful execution
            self.logger.info(
                f"Entry order executed: ID={entry_order.order_id}, "
                f"status={entry_order.status.value}, "
                f"filled={entry_order.quantity} @ {entry_order.price}"
            )

        except ClientError as e:
            # Binance API errors (4xx status codes)
            self.logger.error(
                f"Entry order rejected by Binance: "
                f"code={e.error_code}, msg={e.error_message}"
            )
            raise OrderRejectedError(
                f"Binance rejected order: {e.error_message}"
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
