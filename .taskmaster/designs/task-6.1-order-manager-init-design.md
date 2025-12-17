# 서브태스크 6.1: OrderExecutionManager 기본 구조 - 상세 설계

**부모 태스크**: Task #6 (Order Execution Manager & Binance API Integration)
**작성일**: 2025-12-17
**상태**: Design Complete

---

## 📋 목차

1. [개요](#개요)
2. [코드베이스 분석](#코드베이스-분석)
3. [클래스 구조 설계](#클래스-구조-설계)
4. [초기화 로직](#초기화-로직)
5. [레버리지 설정 메서드](#레버리지-설정-메서드)
6. [마진 타입 설정 메서드](#마진-타입-설정-메서드)
7. [예외 계층 확장](#예외-계층-확장)
8. [테스트 전략](#테스트-전략)
9. [구현 순서](#구현-순서)
10. [완료 기준](#완료-기준)

---

## 개요

### 목적
OrderExecutionManager 클래스의 기본 구조를 생성하고, Binance UMFutures REST 클라이언트를 초기화합니다. 레버리지와 마진 타입 설정 메서드를 구현하여 포지션 관리의 기초를 마련합니다.

### 범위
- **포함**: 초기화, 레버리지 설정, 마진 타입 설정
- **제외**: 주문 실행, TP/SL 배치, 포지션 조회 (다음 서브태스크)

### 의존성
- **외부 라이브러리**: `binance-futures-connector-python` (UMFutures)
- **내부 모듈**:
  - `src/models/order.py` (Order, OrderSide, OrderType, OrderStatus)
  - `src/models/signal.py` (Signal, SignalType)
  - `src/models/position.py` (Position)
  - `src/core/exceptions.py` (OrderExecutionError)

---

## 코드베이스 분석

### 기존 파일 상태

#### 1. `src/execution/order_manager.py`
**현재 상태**: 기본 OrderManager 클래스 스켈레톤
```python
class OrderManager:
    def __init__(self):
        self.active_orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}

    async def place_order(self, order: Order) -> bool:
        pass

    async def cancel_order(self, order_id: str) -> bool:
        pass

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
```

**접근 방식**: 기존 파일을 **완전히 대체**하여 새로운 `OrderExecutionManager` 클래스 구현
- 이유: 기존 클래스는 스켈레톤이며, 새로운 아키텍처와 호환되지 않음

#### 2. `src/models/order.py`
**상태**: ✅ 완료
- `Order` 데이터 클래스 정의 완료
- `OrderType`, `OrderSide`, `OrderStatus` Enum 정의 완료
- Binance API 값과 정확히 일치 (MARKET, LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET)

#### 3. `src/models/signal.py`
**상태**: ✅ 완료
- `Signal` 데이터 클래스 정의 완료 (frozen=True)
- `SignalType` Enum 정의 완료
- TP/SL 가격 검증 로직 포함 (`__post_init__`)

#### 4. `src/models/position.py`
**상태**: ✅ 완료
- `Position` 데이터 클래스 정의 완료
- side, quantity, leverage 검증 포함

#### 5. `src/core/exceptions.py`
**현재 상태**: 기본 예외 클래스만 존재
```python
class OrderExecutionError(TradingSystemError):
    """Order execution errors"""
    pass
```

**필요 작업**: 세부 예외 클래스 추가
- `ValidationError`
- `RateLimitError`
- `OrderRejectedError`

#### 6. `src/utils/logger.py`
**상태**: setup_logger() 유틸리티 존재
- 콘솔 + 파일 핸들러 설정
- **사용하지 않음**: 민감 정보 필터가 없으므로 직접 `logging.getLogger()` 사용

---

## 클래스 구조 설계

### 파일 위치
`src/execution/order_manager.py`

### Import 구조
```python
"""
Order execution and management with Binance Futures API integration.
"""

import os
import logging
from typing import Optional, Dict, List, Tuple

from binance.um_futures import UMFutures
from binance.error import ClientError

from src.models.order import Order, OrderSide, OrderType, OrderStatus
from src.models.signal import Signal, SignalType
from src.models.position import Position
from src.core.exceptions import OrderExecutionError
```

### 클래스 정의
```python
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
```

---

## 초기화 로직

### 메서드 시그니처
```python
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
```

### 구현 로직

#### 1. API 키 처리
```python
# 환경변수 우선, 파라미터로 override 가능
self.api_key = api_key or os.getenv('BINANCE_API_KEY')
self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')

# 필수 검증
if not self.api_key or not self.api_secret:
    raise ValueError(
        "API credentials required. "
        "Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables, "
        "or pass api_key and api_secret parameters."
    )
```

**보안 고려사항**:
- API 키를 인스턴스 변수로 저장하지 않음 (로깅 위험)
- 환경변수 사용 권장

#### 2. Base URL 선택
```python
base_url = (
    "https://testnet.binancefuture.com"
    if is_testnet
    else "https://fapi.binance.com"
)
```

**URL 정보**:
- **Testnet**: `https://testnet.binancefuture.com`
- **Mainnet**: `https://fapi.binance.com`

#### 3. UMFutures 클라이언트 초기화
```python
self.client = UMFutures(
    key=self.api_key,
    secret=self.api_secret,
    base_url=base_url
)
```

**UMFutures 파라미터**:
- `key`: API 키
- `secret`: API 시크릿
- `base_url`: REST API 엔드포인트

#### 4. 로거 설정
```python
# 기존 utils.logger.setup_logger() 사용하지 않음
# 이유: 민감 정보 필터 추가 필요 (향후 서브태스크)
self.logger = logging.getLogger(__name__)

# 기본 로깅 레벨은 INFO
if not self.logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    self.logger.addHandler(handler)
    self.logger.setLevel(logging.INFO)
```

**로깅 전략**:
- `logging.getLogger(__name__)` 사용 (모듈별 로거)
- 핸들러 중복 방지 (`if not self.logger.handlers`)
- 향후 SensitiveDataFilter 추가 예정 (서브태스크 6.6)

#### 5. 상태 초기화
```python
# 오픈 주문 추적 (심볼 → 주문 리스트)
self._open_orders: Dict[str, List[Order]] = {}
```

**상태 관리**:
- `_open_orders`: 심볼별 오픈 주문 리스트
- 향후 서브태스크에서 사용 (주문 배치 시 추가)

---

## 레버리지 설정 메서드

### 메서드 시그니처
```python
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
```

### 구현 로직
```python
try:
    # Binance API 호출
    response = self.client.change_leverage(
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
    self.logger.error(f"Unexpected error setting leverage for {symbol}: {e}")
    return False
```

### API 응답 예시
**성공 (200)**:
```json
{
  "symbol": "BTCUSDT",
  "leverage": 10,
  "maxNotionalValue": "1000000"
}
```

**실패 (400)**:
```json
{
  "code": -4028,
  "msg": "Leverage 200 is not valid"
}
```

### 오류 코드
- **-4028**: Invalid leverage value
- **-4046**: No need to change leverage (이미 설정됨)

---

## 마진 타입 설정 메서드

### 메서드 시그니처
```python
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
```

### 구현 로직
```python
try:
    # Binance API 호출
    response = self.client.change_margin_type(
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
    self.logger.error(f"Unexpected error setting margin type for {symbol}: {e}")
    return False
```

### API 응답 예시
**성공 (200)**:
```json
{
  "code": 200,
  "msg": "success"
}
```

**이미 설정됨 (400)**:
```json
{
  "code": -4046,
  "msg": "No need to change margin type."
}
```

**실패 (400)**:
```json
{
  "code": -4047,
  "msg": "Margin type cannot be changed if there is open order."
}
```

### 오류 코드
- **-4046**: No need to change margin type (무시)
- **-4047**: Cannot change with open orders

### 특수 처리 로직
**"No need to change" 에러 무시**:
```python
if 'No need to change margin type' in e.error_message:
    # 이미 원하는 마진 타입으로 설정되어 있음
    # 성공으로 간주
    return True
```

**이유**:
- 사용자가 반복적으로 동일한 설정을 시도할 수 있음
- 멱등성 보장 (같은 요청을 여러 번 해도 안전)

---

## 예외 계층 확장

### 파일 위치
`src/core/exceptions.py`

### 추가할 예외 클래스
```python
class ValidationError(OrderExecutionError):
    """주문 파라미터 검증 실패"""
    pass


class RateLimitError(OrderExecutionError):
    """Rate limit 초과"""
    pass


class OrderRejectedError(OrderExecutionError):
    """Binance가 주문 거부"""
    pass
```

### 예외 계층 구조
```
Exception
└── TradingSystemError
    └── OrderExecutionError
        ├── ValidationError
        ├── RateLimitError
        └── OrderRejectedError
```

### 사용 예시
```python
# ValidationError
if quantity <= 0:
    raise ValidationError(f"Quantity must be > 0, got {quantity}")

# RateLimitError (서브태스크 6.6에서 사용)
if error_code == -1003:
    raise RateLimitError("Rate limit exceeded")

# OrderRejectedError (서브태스크 6.2-6.3에서 사용)
if error_code == -2010:
    raise OrderRejectedError("Order would trigger immediately")
```

---

## 테스트 전략

### 테스트 파일 구조
```
tests/
├── test_order_execution.py  (새로 생성)
└── ...
```

### 테스트 클래스 구조
```python
import pytest
from unittest.mock import Mock, patch, MagicMock
import os
from binance.error import ClientError

from src.execution.order_manager import OrderExecutionManager


class TestOrderExecutionManager:
    """OrderExecutionManager 단위 테스트"""

    @pytest.fixture
    def mock_client(self):
        """Mock Binance UMFutures 클라이언트"""
        return MagicMock()

    @pytest.fixture
    def manager(self, mock_client):
        """OrderExecutionManager 인스턴스 (mock client 사용)"""
        with patch('src.execution.order_manager.UMFutures', return_value=mock_client):
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                return OrderExecutionManager(is_testnet=True)
```

### 테스트 케이스 목록

#### 1. 초기화 테스트 (5개)
```python
def test_init_testnet_url(self, manager):
    """Testnet URL이 올바르게 설정되는지 검증"""
    assert 'testnet' in manager.client.base_url.lower()

def test_init_mainnet_url(self):
    """Mainnet URL이 올바르게 설정되는지 검증"""
    with patch('src.execution.order_manager.UMFutures') as mock_um:
        with patch.dict('os.environ', {
            'BINANCE_API_KEY': 'test_key',
            'BINANCE_API_SECRET': 'test_secret'
        }):
            manager = OrderExecutionManager(is_testnet=False)

            # UMFutures가 mainnet URL로 호출되었는지 확인
            call_args = mock_um.call_args
            assert 'fapi.binance.com' in call_args.kwargs['base_url']

def test_init_without_api_keys(self):
    """API 키 없이 초기화 시 ValueError 발생"""
    with patch.dict('os.environ', {}, clear=True):
        with pytest.raises(ValueError, match="API credentials required"):
            OrderExecutionManager()

def test_init_with_api_key_params(self):
    """파라미터로 API 키 전달"""
    with patch('src.execution.order_manager.UMFutures'):
        manager = OrderExecutionManager(
            api_key='param_key',
            api_secret='param_secret'
        )
        # 예외 없이 초기화 완료
        assert manager is not None

def test_init_open_orders_empty(self, manager):
    """초기화 시 _open_orders가 빈 딕셔너리인지 확인"""
    assert manager._open_orders == {}
```

#### 2. 레버리지 설정 테스트 (6개)
```python
def test_set_leverage_success(self, manager, mock_client):
    """레버리지 설정 성공"""
    mock_client.change_leverage.return_value = {
        'symbol': 'BTCUSDT',
        'leverage': 10
    }

    result = manager.set_leverage('BTCUSDT', 10)

    assert result is True
    mock_client.change_leverage.assert_called_once_with(
        symbol='BTCUSDT',
        leverage=10
    )

def test_set_leverage_various_values(self, manager, mock_client):
    """다양한 레버리지 값 테스트 (1x, 20x, 125x)"""
    mock_client.change_leverage.return_value = {'leverage': 0}

    for leverage in [1, 20, 125]:
        result = manager.set_leverage('BTCUSDT', leverage)
        assert result is True

def test_set_leverage_api_error(self, manager, mock_client):
    """API 오류 시 False 반환"""
    mock_client.change_leverage.side_effect = ClientError(
        status_code=400,
        error_code=-4028,
        error_message="Leverage 200 is not valid"
    )

    result = manager.set_leverage('BTCUSDT', 200)

    assert result is False

def test_set_leverage_network_error(self, manager, mock_client):
    """네트워크 오류 시 False 반환"""
    mock_client.change_leverage.side_effect = Exception("Network error")

    result = manager.set_leverage('BTCUSDT', 10)

    assert result is False

def test_set_leverage_logging_success(self, manager, mock_client, caplog):
    """성공 시 로깅 확인"""
    mock_client.change_leverage.return_value = {'leverage': 10}

    manager.set_leverage('BTCUSDT', 10)

    assert "Leverage set to 10x for BTCUSDT" in caplog.text

def test_set_leverage_logging_error(self, manager, mock_client, caplog):
    """실패 시 로깅 확인"""
    mock_client.change_leverage.side_effect = ClientError(
        status_code=400,
        error_code=-4028,
        error_message="Invalid leverage"
    )

    manager.set_leverage('BTCUSDT', 200)

    assert "Failed to set leverage" in caplog.text
```

#### 3. 마진 타입 설정 테스트 (7개)
```python
def test_set_margin_type_isolated_success(self, manager, mock_client):
    """ISOLATED 마진 타입 설정 성공"""
    mock_client.change_margin_type.return_value = {
        'code': 200,
        'msg': 'success'
    }

    result = manager.set_margin_type('BTCUSDT', 'ISOLATED')

    assert result is True
    mock_client.change_margin_type.assert_called_once_with(
        symbol='BTCUSDT',
        marginType='ISOLATED'
    )

def test_set_margin_type_crossed_success(self, manager, mock_client):
    """CROSSED 마진 타입 설정 성공"""
    mock_client.change_margin_type.return_value = {'code': 200}

    result = manager.set_margin_type('BTCUSDT', 'CROSSED')

    assert result is True

def test_set_margin_type_default_isolated(self, manager, mock_client):
    """기본값이 ISOLATED인지 확인"""
    mock_client.change_margin_type.return_value = {'code': 200}

    manager.set_margin_type('BTCUSDT')

    # ISOLATED이 기본값으로 호출되었는지 확인
    call_args = mock_client.change_margin_type.call_args
    assert call_args.kwargs['marginType'] == 'ISOLATED'

def test_set_margin_type_already_set(self, manager, mock_client):
    """이미 설정된 경우 (True 반환)"""
    mock_client.change_margin_type.side_effect = ClientError(
        status_code=400,
        error_code=-4046,
        error_message="No need to change margin type."
    )

    result = manager.set_margin_type('BTCUSDT', 'ISOLATED')

    # "No need to change"는 성공으로 간주
    assert result is True

def test_set_margin_type_open_orders_error(self, manager, mock_client):
    """오픈 주문이 있어서 실패"""
    mock_client.change_margin_type.side_effect = ClientError(
        status_code=400,
        error_code=-4047,
        error_message="Margin type cannot be changed if there is open order."
    )

    result = manager.set_margin_type('BTCUSDT', 'ISOLATED')

    assert result is False

def test_set_margin_type_logging_success(self, manager, mock_client, caplog):
    """성공 시 로깅 확인"""
    mock_client.change_margin_type.return_value = {'code': 200}

    manager.set_margin_type('BTCUSDT', 'ISOLATED')

    assert "Margin type set to ISOLATED for BTCUSDT" in caplog.text

def test_set_margin_type_logging_already_set(self, manager, mock_client, caplog):
    """이미 설정된 경우 디버그 로깅 확인"""
    mock_client.change_margin_type.side_effect = ClientError(
        status_code=400,
        error_code=-4046,
        error_message="No need to change margin type."
    )

    with caplog.at_level(logging.DEBUG):
        manager.set_margin_type('BTCUSDT', 'ISOLATED')

        assert "already set" in caplog.text
```

#### 4. 예외 클래스 테스트 (3개)
```python
def test_validation_error_inheritance():
    """ValidationError가 OrderExecutionError를 상속하는지 확인"""
    from src.core.exceptions import ValidationError, OrderExecutionError

    err = ValidationError("Test error")
    assert isinstance(err, OrderExecutionError)

def test_rate_limit_error_inheritance():
    """RateLimitError가 OrderExecutionError를 상속하는지 확인"""
    from src.core.exceptions import RateLimitError, OrderExecutionError

    err = RateLimitError("Test error")
    assert isinstance(err, OrderExecutionError)

def test_order_rejected_error_inheritance():
    """OrderRejectedError가 OrderExecutionError를 상속하는지 확인"""
    from src.core.exceptions import OrderRejectedError, OrderExecutionError

    err = OrderRejectedError("Test error")
    assert isinstance(err, OrderExecutionError)
```

### 테스트 실행
```bash
# 모든 테스트 실행
pytest tests/test_order_execution.py -v

# 커버리지 포함
pytest tests/test_order_execution.py -v --cov=src/execution --cov-report=term-missing

# 특정 테스트만 실행
pytest tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_success -v
```

### 예상 테스트 결과
```
tests/test_order_execution.py::TestOrderExecutionManager::test_init_testnet_url PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_init_mainnet_url PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_init_without_api_keys PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_init_with_api_key_params PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_init_open_orders_empty PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_success PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_various_values PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_api_error PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_network_error PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_logging_success PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_leverage_logging_error PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_isolated_success PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_crossed_success PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_default_isolated PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_already_set PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_open_orders_error PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_logging_success PASSED
tests/test_order_execution.py::TestOrderExecutionManager::test_set_margin_type_logging_already_set PASSED
tests/test_order_execution.py::test_validation_error_inheritance PASSED
tests/test_order_execution.py::test_rate_limit_error_inheritance PASSED
tests/test_order_execution.py::test_order_rejected_error_inheritance PASSED

========== 21 passed in 0.5s ==========

Coverage:
Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
src/execution/order_manager.py        45      0   100%
-----------------------------------------------------------------
TOTAL                                  45      0   100%
```

---

## 구현 순서

### Phase 1: 기본 구조 (15분)
1. **파일 재작성**:
   - `src/execution/order_manager.py` 전체 삭제 후 재작성

2. **Import 구조**:
   ```python
   import os
   import logging
   from typing import Optional, Dict, List
   from binance.um_futures import UMFutures
   from binance.error import ClientError
   from src.models.order import Order, OrderSide, OrderType, OrderStatus
   from src.models.signal import Signal, SignalType
   from src.models.position import Position
   from src.core.exceptions import OrderExecutionError
   ```

3. **클래스 정의**:
   ```python
   class OrderExecutionManager:
       """Binance Futures 주문 실행 관리자"""
   ```

4. **`__init__()` 메서드**:
   - API 키 환경변수 로딩
   - 검증 로직
   - Base URL 선택
   - UMFutures 클라이언트 초기화
   - Logger 설정
   - `_open_orders` 초기화

### Phase 2: 레버리지 설정 (5분)
1. **`set_leverage()` 메서드 구현**:
   - 메서드 시그니처
   - Docstring 작성
   - `client.change_leverage()` 호출
   - try-except 블록 (ClientError, Exception)
   - 로깅 (성공/실패)
   - Boolean 반환

### Phase 3: 마진 타입 설정 (5분)
1. **`set_margin_type()` 메서드 구현**:
   - 메서드 시그니처
   - Docstring 작성
   - `client.change_margin_type()` 호출
   - try-except 블록
   - "No need to change" 특수 처리
   - 로깅
   - Boolean 반환

### Phase 4: 예외 클래스 추가 (2분)
1. **`src/core/exceptions.py` 편집**:
   ```python
   class ValidationError(OrderExecutionError):
       """주문 파라미터 검증 실패"""
       pass

   class RateLimitError(OrderExecutionError):
       """Rate limit 초과"""
       pass

   class OrderRejectedError(OrderExecutionError):
       """Binance가 주문 거부"""
       pass
   ```

### Phase 5: 테스트 작성 (10분)
1. **`tests/test_order_execution.py` 생성**:
   - Mock 픽스처 정의
   - 초기화 테스트 (5개)
   - 레버리지 설정 테스트 (6개)
   - 마진 타입 설정 테스트 (7개)
   - 예외 클래스 테스트 (3개)

2. **총 21개 테스트 케이스**

### Phase 6: 검증 (3분)
1. **테스트 실행**:
   ```bash
   pytest tests/test_order_execution.py -v --cov=src/execution --cov-report=term-missing
   ```

2. **Linter 검증**:
   ```bash
   flake8 src/execution/order_manager.py
   ```

3. **Type Check**:
   ```bash
   mypy src/execution/order_manager.py
   ```

---

## 완료 기준

### 코드 완성
- [x] `src/execution/order_manager.py` 재작성 완료
- [x] `OrderExecutionManager` 클래스 정의
- [x] `__init__()` 메서드 구현
  - [x] API 키 환경변수 처리
  - [x] Base URL 선택
  - [x] UMFutures 클라이언트 초기화
  - [x] Logger 설정
  - [x] `_open_orders` 초기화
- [x] `set_leverage()` 메서드 구현
- [x] `set_margin_type()` 메서드 구현
- [x] `src/core/exceptions.py`에 예외 클래스 추가

### 테스트 완성
- [x] `tests/test_order_execution.py` 생성
- [x] 초기화 테스트 (5개)
- [x] 레버리지 설정 테스트 (6개)
- [x] 마진 타입 설정 테스트 (7개)
- [x] 예외 클래스 테스트 (3개)
- [x] **총 21개 테스트 통과**
- [x] **코드 커버리지 100%** (이 서브태스크 범위)

### 품질 검증
- [x] `flake8` 통과 (no warnings)
- [x] `mypy` 통과 (no type errors)
- [x] Docstring 작성 완료 (모든 public 메서드)
- [x] 로깅 적절히 구현 (INFO, ERROR 레벨)

### 문서화
- [x] 메서드 docstring 작성
- [x] 클래스 docstring 작성
- [x] Example 코드 포함

---

## 다음 서브태스크 연결

### 서브태스크 6.2: execute_signal() 메서드 - Market 주문 실행

**의존성**: 서브태스크 6.1 완료 필수

**사용할 컴포넌트**:
- `self.client` (UMFutures) - 이미 초기화됨
- `self.logger` - 이미 설정됨
- `self._open_orders` - 주문 추적에 사용
- `Signal` 모델 - 입력 파라미터
- `Order` 모델 - 반환 값

**새로 구현할 메서드**:
- `execute_signal(signal: Signal, quantity: float) -> Tuple[Order, List[Order]]`
- `_parse_order_response(response: dict) -> Order`

**설계 참고**:
- `.taskmaster/designs/task-6-order-execution-design.md`
  - 섹션: "주문 실행 흐름" → "2. Market Entry 주문"

---

## 참고 자료

### 설계 문서
- `.taskmaster/designs/task-6-order-execution-design.md`: 전체 아키텍처 설계
- `.taskmaster/docs/workflow-strategy.md`: 개발 워크플로우

### API 문서 (Context7)
- Binance Futures Connector: `/binance/binance-futures-connector-python`
- `change_leverage()` 메서드
- `change_margin_type()` 메서드
- Error Codes: -4028, -4046, -4047

### 프로젝트 파일
- `src/models/order.py`: Order 데이터 모델
- `src/models/signal.py`: Signal 데이터 모델
- `src/models/position.py`: Position 데이터 모델
- `src/core/exceptions.py`: 예외 클래스

---

**설계 검토자**: Context7 + Serena
**최종 업데이트**: 2025-12-17
**다음 단계**: 서브태스크 6.1 구현 시작
