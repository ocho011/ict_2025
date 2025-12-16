"""
Order execution and management with Binance Futures API integration.
"""

import os
import logging
from typing import Optional, Dict, List

from binance.um_futures import UMFutures
from binance.error import ClientError

from src.models.order import Order
from src.models.position import Position
from src.core.exceptions import OrderExecutionError


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
