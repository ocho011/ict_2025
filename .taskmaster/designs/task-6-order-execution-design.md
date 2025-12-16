# Task #6: Order Execution Manager - 설계 문서

**작성일**: 2025-12-17
**복잡도**: 8 (High Complexity)
**우선순위**: High
**상태**: Design Complete

---

## 📋 목차

1. [개요](#개요)
2. [아키텍처 설계](#아키텍처-설계)
3. [주문 실행 흐름](#주문-실행-흐름)
4. [보안 설계](#보안-설계)
5. [오류 처리 전략](#오류-처리-전략)
6. [테스트 전략](#테스트-전략)
7. [구현 체크리스트](#구현-체크리스트)

---

## 개요

### 목적
Binance Futures API를 사용하여 거래 시그널을 실제 주문으로 변환하고, TP/SL 보호 장치를 자동으로 설정하는 주문 실행 관리자를 구현합니다.

### 핵심 기능
1. **Market 주문 실행**: Signal 객체를 받아 시장가 주문 배치
2. **자동 TP/SL 배치**: Entry 주문 체결 후 즉시 Take Profit 및 Stop Loss 주문 생성
3. **포지션 관리**: 현재 포지션 조회, 레버리지 및 마진 타입 설정
4. **계좌 조회**: USDT 잔고 및 계좌 정보 조회
5. **오류 처리**: Rate limiting, 네트워크 오류, API 거부 등 포괄적 오류 처리

### 의존성
- **외부 라이브러리**: `binance-futures-connector-python` (UMFutures)
- **내부 모듈**:
  - `src/models/signal.py` (Signal, SignalType)
  - `src/models/order.py` (Order, OrderSide, Position)

---

## 아키텍처 설계

### 클래스 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│                  OrderExecutionManager                      │
├─────────────────────────────────────────────────────────────┤
│ - client: UMFutures                                         │
│ - logger: Logger                                            │
│ - _symbol_info_cache: Dict[str, dict]                      │
│ - _time_offset: int                                         │
├─────────────────────────────────────────────────────────────┤
│ + __init__(api_key, api_secret, is_testnet)                │
│ + execute_signal(signal, quantity) -> (Order, List[Order]) │
│ + set_leverage(symbol, leverage) -> bool                   │
│ + set_margin_type(symbol, margin_type) -> bool             │
│ + get_position(symbol) -> Optional[Position]               │
│ + get_account_balance() -> float                           │
│ + cancel_all_orders(symbol) -> bool                        │
│ - _format_price(symbol, price) -> str                      │
│ - _format_quantity(symbol, quantity) -> str                │
│ - _validate_tp_sl(signal, side) -> None                    │
│ - _parse_order_response(response) -> Order                 │
│ - _api_call_with_retry(api_func, *args, **kwargs)          │
│ - _calculate_time_offset() -> int                          │
│ - _get_symbol_info(symbol) -> dict                         │
└─────────────────────────────────────────────────────────────┘
```

### 메서드 시그니처

#### Public API

```python
class OrderExecutionManager:
    """Binance Futures 주문 실행 관리자"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        is_testnet: bool = True
    ) -> None:
        """
        초기화 및 Binance Futures 클라이언트 설정

        Args:
            api_key: Binance API 키 (None이면 환경변수 BINANCE_API_KEY 사용)
            api_secret: Binance API 시크릿 (None이면 환경변수 BINANCE_API_SECRET 사용)
            is_testnet: Testnet 사용 여부 (기본값: True)

        Raises:
            ValueError: API 키 또는 시크릿이 없을 경우
        """

    def execute_signal(
        self,
        signal: Signal,
        quantity: float
    ) -> Tuple[Order, List[Order]]:
        """
        거래 시그널을 실행하여 Market 주문 + TP/SL 배치

        Args:
            signal: 거래 시그널 (entry, TP, SL 가격 포함)
            quantity: 주문 수량 (계약 수)

        Returns:
            (entry_order, [tp_order, sl_order]) 튜플

        Raises:
            OrderExecutionError: 주문 실행 실패 시
            ValidationError: 파라미터 검증 실패 시
            RateLimitError: Rate limit 초과 시

        Example:
            >>> signal = Signal(
            ...     symbol='BTCUSDT',
            ...     signal_type=SignalType.LONG_ENTRY,
            ...     entry_price=50000.0,
            ...     take_profit=51000.0,
            ...     stop_loss=49000.0
            ... )
            >>> entry, [tp, sl] = manager.execute_signal(signal, 0.001)
        """

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        심볼의 레버리지 설정

        Args:
            symbol: 거래 쌍 (예: 'BTCUSDT')
            leverage: 레버리지 (1-125)

        Returns:
            성공 여부
        """

    def set_margin_type(
        self,
        symbol: str,
        margin_type: str = 'ISOLATED'
    ) -> bool:
        """
        마진 타입 설정 (ISOLATED 또는 CROSSED)

        Args:
            symbol: 거래 쌍
            margin_type: 'ISOLATED' 또는 'CROSSED'

        Returns:
            성공 여부

        Note:
            이미 설정된 경우 "No need to change" 에러는 무시됨
        """

    def get_position(self, symbol: str) -> Optional[Position]:
        """
        현재 포지션 정보 조회

        Args:
            symbol: 거래 쌍

        Returns:
            Position 객체 (포지션 없으면 None)
        """

    def get_account_balance(self) -> float:
        """
        USDT 잔고 조회

        Returns:
            USDT 잔고 (walletBalance)
        """

    def cancel_all_orders(self, symbol: str) -> bool:
        """
        심볼의 모든 오픈 주문 취소

        Args:
            symbol: 거래 쌍

        Returns:
            성공 여부
        """
```

#### Private Helpers

```python
    def _format_price(self, symbol: str, price: float) -> str:
        """
        심볼의 tick size에 맞춰 가격 포맷팅

        Args:
            symbol: 거래 쌍
            price: 원본 가격

        Returns:
            포맷팅된 가격 문자열

        Example:
            >>> self._format_price('BTCUSDT', 50000.12345)
            '50000.1'  # tick_size=0.1인 경우
        """

    def _format_quantity(self, symbol: str, quantity: float) -> str:
        """심볼의 lot size에 맞춰 수량 포맷팅"""

    def _validate_tp_sl(self, signal: Signal, side: OrderSide) -> None:
        """
        TP/SL 가격 방향 검증

        Raises:
            ValidationError: TP/SL 가격이 잘못된 방향일 경우

        Example:
            LONG: TP > entry, SL < entry
            SHORT: TP < entry, SL > entry
        """

    def _parse_order_response(self, response: dict) -> Order:
        """Binance API 응답을 Order 객체로 변환"""

    def _api_call_with_retry(
        self,
        api_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        API 호출을 exponential backoff로 재시도

        Args:
            api_func: API 호출 함수
            *args, **kwargs: API 함수 인자

        Returns:
            API 응답

        Raises:
            RateLimitError: Rate limit 초과 후 재시도 실패
            ClientError: 재시도 불가능한 클라이언트 오류
            ServerError: 서버 오류
        """

    def _calculate_time_offset(self) -> int:
        """서버-클라이언트 시간 차이 계산"""

    def _get_symbol_info(self, symbol: str) -> dict:
        """Exchange info에서 심볼 정보 조회 (캐싱됨)"""
```

---

## 주문 실행 흐름

### 시퀀스 다이어그램

```
Strategy          OrderExecutionManager      Binance API
   |                      |                       |
   |---execute_signal---->|                       |
   |                      |                       |
   |                      |---_validate_tp_sl---->|
   |                      |<----------------------|
   |                      |                       |
   |                      |---new_order(MARKET)-->|
   |                      |<--entry_response------|
   |                      |                       |
   |                      |---new_order(TP)------>|
   |                      |<--tp_response---------|
   |                      |                       |
   |                      |---new_order(SL)------>|
   |                      |<--sl_response---------|
   |                      |                       |
   |<--(entry,[tp,sl])---|                       |
   |                      |                       |
```

### 단계별 세부 흐름

#### 1. 파라미터 검증
```python
# Signal 객체 검증
if not signal or not signal.symbol:
    raise ValidationError("Invalid signal")

# TP/SL 방향 검증
self._validate_tp_sl(signal, side)

# 수량 범위 검증
self._validate_quantity(signal.symbol, quantity)
```

#### 2. Market Entry 주문
```python
entry_response = self.client.new_order(
    symbol=signal.symbol,
    side='BUY' if signal.signal_type == SignalType.LONG_ENTRY else 'SELL',
    type='MARKET',
    quantity=self._format_quantity(signal.symbol, quantity)
)

# 체결 확인
if entry_response['status'] != 'FILLED':
    raise OrderExecutionError("Market order not filled")

# 실제 체결가 저장
actual_entry_price = float(entry_response['avgPrice'])
```

#### 3. Take Profit 주문
```python
close_side = 'SELL' if side == OrderSide.BUY else 'BUY'

tp_response = self.client.new_order(
    symbol=signal.symbol,
    side=close_side,
    type='TAKE_PROFIT_MARKET',
    stopPrice=self._format_price(signal.symbol, signal.take_profit),
    closePosition=True,  # 전체 포지션 청산
    workingType='MARK_PRICE'  # Mark price 기준 트리거
)
```

#### 4. Stop Loss 주문
```python
sl_response = self.client.new_order(
    symbol=signal.symbol,
    side=close_side,
    type='STOP_MARKET',
    stopPrice=self._format_price(signal.symbol, signal.stop_loss),
    closePosition=True,
    workingType='MARK_PRICE'
)
```

#### 5. 응답 파싱 및 반환
```python
entry_order = self._parse_order_response(entry_response)
tp_order = self._parse_order_response(tp_response)
sl_order = self._parse_order_response(sl_response)

return entry_order, [tp_order, sl_order]
```

### TP/SL 실패 처리

**시나리오**: Entry 주문은 성공했지만 TP 또는 SL 배치 실패

**전략**:
1. TP/SL 배치 시 각각 최대 3회 재시도 (exponential backoff)
2. 모든 재시도 실패 시 → `OrderExecutionError` 예외 발생
3. 호출자(Strategy)가 포지션 청산 여부 결정
   - 자동 모드: 즉시 Market 주문으로 포지션 청산
   - 반자동 모드: 알림 발송 후 수동 개입

**구현**:
```python
try:
    tp_order = self._api_call_with_retry(
        self.client.new_order,
        symbol=signal.symbol,
        side=close_side,
        type='TAKE_PROFIT_MARKET',
        stopPrice=tp_price,
        closePosition=True,
        workingType='MARK_PRICE'
    )
except Exception as e:
    self.logger.error(f"TP order failed: {e}")
    raise OrderExecutionError(
        f"Failed to place TP order after entry. "
        f"Position is UNPROTECTED. Entry: {entry_order.order_id}"
    )
```

---

## 보안 설계

### 1. API 키 관리

#### 환경변수 강제
```python
def __init__(self, api_key=None, api_secret=None, is_testnet=True):
    self.api_key = api_key or os.getenv('BINANCE_API_KEY')
    self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')

    if not self.api_key or not self.api_secret:
        raise ValueError(
            "API credentials required. "
            "Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables."
        )
```

#### 로깅 필터 (민감 정보 마스킹)
```python
class SensitiveDataFilter(logging.Filter):
    """API 키, 시크릿을 로그에서 마스킹"""

    SENSITIVE_PATTERNS = [
        r'(api[_-]?key|secret)["\']?\s*[:=]\s*["\']?([\w-]+)',
        r'(X-MBX-APIKEY:\s*)([\w-]+)'
    ]

    def filter(self, record):
        if hasattr(record, 'msg'):
            msg = str(record.msg)
            for pattern in self.SENSITIVE_PATTERNS:
                msg = re.sub(pattern, r'\1***REDACTED***', msg)
            record.msg = msg
        return True
```

### 2. 주문 파라미터 검증

#### TP/SL 방향 검증
```python
def _validate_tp_sl(self, signal: Signal, side: OrderSide) -> None:
    """TP/SL 가격이 올바른 방향인지 검증"""
    entry = signal.entry_price
    tp = signal.take_profit
    sl = signal.stop_loss

    if side == OrderSide.BUY:  # LONG
        if tp <= entry:
            raise ValidationError(
                f"LONG position: TP ({tp}) must be > entry ({entry})"
            )
        if sl >= entry:
            raise ValidationError(
                f"LONG position: SL ({sl}) must be < entry ({entry})"
            )
    else:  # SHORT
        if tp >= entry:
            raise ValidationError(
                f"SHORT position: TP ({tp}) must be < entry ({entry})"
            )
        if sl <= entry:
            raise ValidationError(
                f"SHORT position: SL ({sl}) must be > entry ({entry})"
            )
```

#### 수량 범위 검증
```python
def _validate_quantity(self, symbol: str, quantity: float) -> None:
    """Exchange info의 LOT_SIZE 필터로 수량 검증"""
    symbol_info = self._get_symbol_info(symbol)

    for f in symbol_info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            min_qty = float(f['minQty'])
            max_qty = float(f['maxQty'])
            step_size = float(f['stepSize'])

            if quantity < min_qty:
                raise ValidationError(
                    f"Quantity {quantity} below minimum {min_qty}"
                )
            if quantity > max_qty:
                raise ValidationError(
                    f"Quantity {quantity} exceeds maximum {max_qty}"
                )

            # Step size 검증
            if (quantity - min_qty) % step_size != 0:
                raise ValidationError(
                    f"Quantity {quantity} not aligned with step size {step_size}"
                )
```

### 3. 타임스탬프 동기화

#### 서버 시간 오프셋 계산
```python
def _calculate_time_offset(self) -> int:
    """서버-클라이언트 시간 차이 계산 (밀리초)"""
    try:
        local_time_before = int(time.time() * 1000)
        server_time = self.client.time()['serverTime']
        local_time_after = int(time.time() * 1000)

        # 왕복 시간 보정
        rtt = local_time_after - local_time_before
        adjusted_local_time = local_time_before + (rtt // 2)

        offset = server_time - adjusted_local_time
        self.logger.info(f"Server time offset: {offset}ms")
        return offset

    except Exception as e:
        self.logger.warning(f"Failed to sync server time: {e}")
        return 0
```

#### RecvWindow 설정
```python
# 기본 recvWindow: 5000ms (5초)
# 네트워크 지연 고려하여 10000ms (10초)로 증가
RECV_WINDOW = 10000

response = self.client.new_order(
    symbol=symbol,
    side=side,
    type=order_type,
    quantity=quantity,
    recvWindow=RECV_WINDOW
)
```

### 4. 보안 체크리스트

#### 구현 시 검증 항목
- [ ] API 키가 코드에 하드코딩되지 않음
- [ ] API 키가 Git 저장소에 커밋되지 않음 (.env, .gitignore 설정)
- [ ] 로그에 API 키/시크릿이 노출되지 않음 (SensitiveDataFilter 적용)
- [ ] 모든 주문 파라미터가 검증됨 (TP/SL 방향, 수량 범위)
- [ ] Rate limiting 오류 처리됨 (-1003)
- [ ] Timestamp 동기화 구현됨 (-1021 방지)
- [ ] SSL 인증서 검증 활성화됨 (binance-connector 기본값)
- [ ] Testnet에서 충분히 테스트 후 Mainnet 배포

---

## 오류 처리 전략

### 1. Rate Limiting

#### 오류 코드
- **-1003**: "Too many requests" (초당 요청 수 초과)
- **-1015**: "Too many orders" (오픈 주문 수 초과)

#### 처리 전략
```python
from functools import wraps
import time

def retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0):
    """Exponential backoff 재시도 데코레이터"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)

                except ClientError as e:
                    last_exception = e

                    # Rate limit 오류만 재시도
                    if e.error_code in [-1003, -1015]:
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                                f"Retrying in {delay}s..."
                            )
                            time.sleep(delay)
                            delay *= backoff_factor
                        else:
                            raise RateLimitError(
                                f"Rate limit exceeded after {max_retries} retries"
                            ) from e
                    else:
                        # 다른 ClientError는 즉시 전파
                        raise

                except (ServerError, RequestException) as e:
                    # 네트워크/서버 오류도 재시도
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Network error (attempt {attempt + 1}/{max_retries}). "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        raise

            raise last_exception

        return wrapper
    return decorator
```

### 2. 네트워크 오류

#### 오류 유형
- `requests.exceptions.ConnectionError`
- `requests.exceptions.Timeout`
- `requests.exceptions.RequestException`

#### 처리
```python
@retry_with_backoff(max_retries=3, initial_delay=1.0)
def _api_call_with_retry(self, api_func, *args, **kwargs):
    """
    API 호출을 재시도 로직으로 감싸기

    Rate limit, 네트워크 오류, 서버 오류는 재시도
    클라이언트 오류는 즉시 전파
    """
    try:
        return api_func(*args, **kwargs)
    except ClientError as e:
        # Rate limit 또는 서버 문제는 재시도
        if e.error_code in [-1003, -1015]:
            raise  # retry_with_backoff가 처리
        # 다른 ClientError는 즉시 실패
        raise OrderExecutionError(f"API error: {e.error_message}") from e
```

### 3. 타임스탬프 오류

#### 오류 코드
- **-1021**: "Timestamp for this request is outside of the recvWindow"

#### 처리
```python
def __init__(self, ...):
    # 초기화 시 서버 시간 동기화
    self._time_offset = self._calculate_time_offset()

    # 주기적으로 재동기화 (1시간마다)
    self._last_sync_time = time.time()

def _maybe_resync_time(self):
    """1시간마다 서버 시간 재동기화"""
    if time.time() - self._last_sync_time > 3600:
        self._time_offset = self._calculate_time_offset()
        self._last_sync_time = time.time()
```

### 4. 주문 거부 오류

#### 일반적인 오류 코드
- **-1100**: "Illegal characters found in parameter"
- **-1102**: "Mandatory parameter missing"
- **-2010**: "Order would immediately trigger"
- **-2011**: "Unknown order"
- **-4164**: "Order's position side does not match user's setting"

#### 처리
```python
try:
    response = self.client.new_order(...)
except ClientError as e:
    error_code = e.error_code
    error_msg = e.error_message

    # 로깅
    self.logger.error(
        f"Order rejected: code={error_code}, msg={error_msg}, "
        f"symbol={symbol}, side={side}, qty={quantity}"
    )

    # 구체적인 예외로 변환
    if error_code in [-1100, -1102]:
        raise ValidationError(f"Invalid parameters: {error_msg}") from e
    elif error_code == -2010:
        raise OrderRejectedError(f"Order would trigger immediately: {error_msg}") from e
    else:
        raise OrderExecutionError(f"Order failed: {error_msg}") from e
```

### 5. 오류 계층 구조

```python
class OrderExecutionError(Exception):
    """주문 실행 관련 기본 예외"""
    pass

class RateLimitError(OrderExecutionError):
    """Rate limit 초과"""
    pass

class ValidationError(OrderExecutionError):
    """파라미터 검증 실패"""
    pass

class OrderRejectedError(OrderExecutionError):
    """Binance가 주문 거부"""
    pass

class PositionError(OrderExecutionError):
    """포지션 관련 오류"""
    pass
```

---

## 테스트 전략

### 1. 단위 테스트 (Unit Tests)

#### 테스트 범위
- 초기화 및 설정
- 파라미터 검증 로직
- 가격/수량 포맷팅
- 응답 파싱
- 오류 처리

#### 테스트 예시
```python
# tests/test_order_execution.py
import pytest
from unittest.mock import Mock, patch
from binance.error import ClientError
from src.execution.order_manager import OrderExecutionManager
from src.models.signal import Signal, SignalType

class TestOrderExecutionManager:

    @pytest.fixture
    def mock_client(self):
        """Mock Binance UMFutures 클라이언트"""
        return Mock(spec=UMFutures)

    @pytest.fixture
    def manager(self, mock_client):
        """OrderExecutionManager 인스턴스 (mock client)"""
        with patch('src.execution.order_manager.UMFutures', return_value=mock_client):
            with patch.dict('os.environ', {
                'BINANCE_API_KEY': 'test_key',
                'BINANCE_API_SECRET': 'test_secret'
            }):
                return OrderExecutionManager(is_testnet=True)

    def test_init_testnet_url(self, manager):
        """Testnet URL이 올바르게 설정되는지 검증"""
        assert 'testnet' in manager.client.base_url.lower()

    def test_init_without_api_keys(self):
        """API 키 없이 초기화 시 ValueError 발생"""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="API credentials required"):
                OrderExecutionManager()

    def test_set_leverage_success(self, manager, mock_client):
        """레버리지 설정 성공"""
        mock_client.change_leverage.return_value = {'leverage': 10}

        result = manager.set_leverage('BTCUSDT', 10)

        assert result is True
        mock_client.change_leverage.assert_called_once_with(
            symbol='BTCUSDT',
            leverage=10
        )

    def test_validate_tp_sl_long_correct(self, manager):
        """LONG 포지션의 올바른 TP/SL 검증"""
        signal = Signal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG_ENTRY,
            entry_price=50000.0,
            take_profit=51000.0,  # entry보다 높음 (올바름)
            stop_loss=49000.0     # entry보다 낮음 (올바름)
        )

        # 예외 발생하지 않아야 함
        manager._validate_tp_sl(signal, OrderSide.BUY)

    def test_validate_tp_sl_long_wrong(self, manager):
        """LONG 포지션의 잘못된 TP/SL 검증"""
        signal = Signal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG_ENTRY,
            entry_price=50000.0,
            take_profit=49000.0,  # entry보다 낮음 (잘못됨)
            stop_loss=51000.0     # entry보다 높음 (잘못됨)
        )

        with pytest.raises(ValidationError, match="TP .* must be > entry"):
            manager._validate_tp_sl(signal, OrderSide.BUY)

    def test_execute_signal_long_success(self, manager, mock_client):
        """LONG 시그널 실행 성공"""
        # Mock API 응답
        mock_client.new_order.side_effect = [
            {  # Entry order
                'orderId': 1,
                'symbol': 'BTCUSDT',
                'status': 'FILLED',
                'avgPrice': '50000.0',
                'executedQty': '0.001'
            },
            {  # TP order
                'orderId': 2,
                'symbol': 'BTCUSDT',
                'status': 'NEW'
            },
            {  # SL order
                'orderId': 3,
                'symbol': 'BTCUSDT',
                'status': 'NEW'
            }
        ]

        signal = Signal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG_ENTRY,
            entry_price=50000.0,
            take_profit=51000.0,
            stop_loss=49000.0
        )

        entry, [tp, sl] = manager.execute_signal(signal, 0.001)

        assert entry.order_id == 1
        assert tp.order_id == 2
        assert sl.order_id == 3
        assert mock_client.new_order.call_count == 3

    def test_execute_signal_tp_failure(self, manager, mock_client):
        """TP 주문 실패 시 예외 발생"""
        mock_client.new_order.side_effect = [
            {'orderId': 1, 'status': 'FILLED', 'avgPrice': '50000.0'},  # Entry success
            ClientError(status_code=400, error_code=-1100, error_message="Invalid price")  # TP fail
        ]

        signal = Signal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG_ENTRY,
            entry_price=50000.0,
            take_profit=51000.0,
            stop_loss=49000.0
        )

        with pytest.raises(OrderExecutionError, match="TP order failed"):
            manager.execute_signal(signal, 0.001)

    def test_format_price_btc(self, manager):
        """BTCUSDT 가격 포맷팅 (tick_size=0.1)"""
        # Mock exchange info
        manager._symbol_info_cache['BTCUSDT'] = {
            'filters': [
                {
                    'filterType': 'PRICE_FILTER',
                    'tickSize': '0.1'
                }
            ]
        }

        formatted = manager._format_price('BTCUSDT', 50000.12345)
        assert formatted == '50000.1'

    def test_retry_on_rate_limit(self, manager, mock_client):
        """Rate limit 오류 시 재시도"""
        # 첫 2번 실패, 3번째 성공
        mock_client.new_order.side_effect = [
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
            {'orderId': 1, 'status': 'FILLED'}
        ]

        with patch('time.sleep'):  # 테스트 속도를 위해 sleep 무시
            result = manager._api_call_with_retry(
                mock_client.new_order,
                symbol='BTCUSDT',
                side='BUY',
                type='MARKET',
                quantity=0.001
            )

        assert result['orderId'] == 1
        assert mock_client.new_order.call_count == 3
```

### 2. 통합 테스트 (Integration Tests)

#### 테스트 범위
- 실제 Binance Testnet API 호출
- 주문 배치 및 체결 확인
- 포지션 조회
- 주문 취소

#### 테스트 예시
```python
# tests/integration/test_binance_testnet.py
import pytest
import os
from src.execution.order_manager import OrderExecutionManager
from src.models.signal import Signal, SignalType

@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv('TESTNET_API_KEY'),
    reason="Testnet API key not configured"
)
class TestBinanceTestnetIntegration:

    @pytest.fixture(scope='class')
    def manager(self):
        """실제 Testnet 연결"""
        return OrderExecutionManager(
            api_key=os.getenv('TESTNET_API_KEY'),
            api_secret=os.getenv('TESTNET_API_SECRET'),
            is_testnet=True
        )

    def test_get_account_balance(self, manager):
        """Testnet 계좌 잔고 조회"""
        balance = manager.get_account_balance()
        assert balance >= 0
        print(f"Testnet USDT balance: {balance}")

    def test_set_leverage(self, manager):
        """레버리지 설정"""
        result = manager.set_leverage('BTCUSDT', 10)
        assert result is True

    def test_execute_long_order(self, manager):
        """실제 LONG 주문 배치 및 취소"""
        # 현재 시장가 조회
        # (실제로는 DataCollector에서 가져와야 함)

        signal = Signal(
            symbol='BTCUSDT',
            signal_type=SignalType.LONG_ENTRY,
            entry_price=50000.0,  # 현재가
            take_profit=55000.0,  # +10%
            stop_loss=47500.0     # -5%
        )

        try:
            # 주문 배치
            entry, [tp, sl] = manager.execute_signal(signal, 0.001)

            assert entry.order_id is not None
            assert tp.order_id is not None
            assert sl.order_id is not None

            # 포지션 확인
            position = manager.get_position('BTCUSDT')
            assert position is not None
            assert position.side == 'LONG'

        finally:
            # 정리: 모든 주문 취소 및 포지션 청산
            manager.cancel_all_orders('BTCUSDT')

            position = manager.get_position('BTCUSDT')
            if position:
                # 포지션 청산
                manager.client.new_order(
                    symbol='BTCUSDT',
                    side='SELL' if position.side == 'LONG' else 'BUY',
                    type='MARKET',
                    quantity=position.quantity
                )
```

### 3. E2E 테스트 (End-to-End Tests)

#### 테스트 시나리오
1. **완전한 거래 사이클**:
   - Signal 생성 → 주문 실행 → TP 도달 → 포지션 청산 확인

2. **오류 복구 시나리오**:
   - 네트워크 오류 발생 → 재시도 → 성공

3. **동시 주문**:
   - 여러 심볼에 동시 주문 → Rate limiting 처리 → 모두 성공

#### Playwright를 이용한 UI 검증
```python
# tests/e2e/test_order_ui.py
import pytest
from playwright.sync_api import Page, expect

@pytest.mark.e2e
def test_order_visible_in_ui(page: Page, manager):
    """배치한 주문이 Binance Testnet UI에 표시되는지 확인"""

    # 1. 주문 배치
    signal = Signal(...)
    entry, [tp, sl] = manager.execute_signal(signal, 0.001)

    # 2. Testnet UI 로그인
    page.goto("https://testnet.binancefuture.com")
    # ... 로그인 로직

    # 3. Open Orders 확인
    page.click('text=Open Orders')

    # TP 주문 확인
    expect(page.locator(f'text={tp.order_id}')).to_be_visible()

    # SL 주문 확인
    expect(page.locator(f'text={sl.order_id}')).to_be_visible()

    # 4. 포지션 확인
    page.click('text=Positions')
    expect(page.locator('text=BTCUSDT')).to_be_visible()
```

### 4. 테스트 커버리지 목표

- **전체 커버리지**: ≥ 90%
- **핵심 로직 커버리지**: 100%
  - `execute_signal()`
  - `_validate_tp_sl()`
  - `_api_call_with_retry()`
  - `_format_price()`

---

## 구현 체크리스트

### Phase 1: 기본 구조 (서브태스크 6.1)
- [ ] OrderExecutionManager 클래스 생성
- [ ] UMFutures 클라이언트 초기화 (testnet/mainnet)
- [ ] API 키 환경변수 로딩 및 검증
- [ ] 로깅 설정 (SensitiveDataFilter 포함)
- [ ] set_leverage() 구현
- [ ] set_margin_type() 구현
- [ ] 단위 테스트: 초기화 및 설정 메서드

### Phase 2: Market 주문 실행 (서브태스크 6.2)
- [ ] execute_signal() 기본 구조
- [ ] Signal → OrderSide 변환 로직
- [ ] Market 주문 배치 (client.new_order)
- [ ] _parse_order_response() 구현
- [ ] 단위 테스트: Market 주문 로직

### Phase 3: TP/SL 주문 배치 (서브태스크 6.3)
- [ ] TAKE_PROFIT_MARKET 주문 배치
- [ ] STOP_MARKET 주문 배치
- [ ] closePosition=True 설정
- [ ] workingType='MARK_PRICE' 설정
- [ ] 단위 테스트: TP/SL 로직

### Phase 4: 포지션 및 잔고 조회 (서브태스크 6.4)
- [ ] get_position() 구현
- [ ] Position 객체 파싱
- [ ] get_account_balance() 구현
- [ ] cancel_all_orders() 구현
- [ ] 단위 테스트: 조회 메서드

### Phase 5: 가격 포맷팅 (서브태스크 6.5)
- [ ] Exchange info 조회 및 캐싱
- [ ] _get_symbol_info() 구현
- [ ] _format_price() 구현 (tick size 기반)
- [ ] _format_quantity() 구현 (lot size 기반)
- [ ] 단위 테스트: 포맷팅 로직

### Phase 6: 오류 처리 (서브태스크 6.6)
- [ ] retry_with_backoff 데코레이터 구현
- [ ] _api_call_with_retry() 구현
- [ ] Rate limit 처리 (-1003)
- [ ] 네트워크 오류 처리
- [ ] _calculate_time_offset() 구현
- [ ] _validate_tp_sl() 구현
- [ ] _validate_quantity() 구현
- [ ] 예외 클래스 정의 (OrderExecutionError 등)
- [ ] 단위 테스트: 오류 처리

### Phase 7: 통합 테스트
- [ ] Testnet API 키 설정
- [ ] 실제 Testnet 주문 배치 테스트
- [ ] 레버리지 설정 테스트
- [ ] 포지션 조회 테스트
- [ ] 주문 취소 테스트

### Phase 8: E2E 테스트
- [ ] Playwright 설정
- [ ] LONG 시나리오 테스트
- [ ] SHORT 시나리오 테스트
- [ ] 오류 복구 시나리오 테스트

### Phase 9: 문서화 및 배포
- [ ] 코드 문서화 (docstring)
- [ ] README 업데이트
- [ ] 보안 체크리스트 검증
- [ ] Testnet 최종 검증
- [ ] Mainnet 배포 준비 (환경변수 분리)

---

## 참고 자료

### Binance API 문서
- [Binance Futures Connector Python](https://github.com/binance/binance-futures-connector-python)
- [USDT-M Futures API](https://binance-docs.github.io/apidocs/futures/en/)
- [Error Codes](https://binance-docs.github.io/apidocs/futures/en/#error-codes)

### 프로젝트 파일
- `src/models/signal.py`: Signal 데이터 모델
- `src/models/order.py`: Order, Position 데이터 모델
- `.taskmaster/docs/prd.md`: 프로젝트 요구사항
- `.taskmaster/docs/workflow-strategy.md`: 개발 워크플로우

---

**설계 검토자**: Sequential Thinking + Context7
**최종 업데이트**: 2025-12-17
**다음 단계**: 서브태스크 6.1 구현 시작
