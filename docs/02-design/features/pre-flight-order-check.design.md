# Pre-flight Order Check - Design Document

> **Feature**: pre-flight-order-check
> **Status**: Draft
> **Author**: Claude Code (PDCA Design)
> **Created**: 2026-03-02
> **PDCA Phase**: Design
> **Plan Reference**: `docs/01-plan/features/pre-flight-order-check.plan.md`

---

## 1. Design Overview

### 1.1 목표

진입 시그널 처리 흐름에 3개의 방어 계층을 추가한다:
1. **Pre-flight open order check** — 잔여 주문 선행 정리
2. **TP/SL 완전성 보장** — 재시도 + 즉시 청산 에스컬레이션
3. **Per-symbol entry guard** — asyncio.Lock 기반 중복 시그널 방지

### 1.2 설계 원칙

1. **기존 인프라 재활용**: `get_open_orders_cached`, `cancel_all_orders`, `execute_market_close` 등 기존 메서드 최대 활용
2. **ABC 최소 변경**: `ExecutionGateway`에 `get_open_orders` 1개만 추가
3. **Hot Path 성능 보존**: 캐시 우선, API 호출은 캐시 미스 시에만
4. **Fail-safe 우선**: 불확실한 상태에서는 안전한 쪽(거절 또는 청산)으로 판단

### 1.3 사용자 결정사항

| # | 결정 | 설계 반영 |
|---|------|-----------|
| 1 | 조건부 Fail-Open | `_pre_flight_check`에서 캐시 히트 시 캐시 기준, 캐시 미스+API 실패 시 Fail-Open |
| 2 | asyncio.Lock per-symbol | `_entry_locks: defaultdict(asyncio.Lock)` |
| 3 | 재시도 후 즉시 청산 | `_ensure_tpsl_completeness` 메서드 신규 |

---

## 2. 인터페이스 변경

### 2.1 ExecutionGateway ABC 확장

**파일**: `src/execution/base.py`

현재 `get_open_orders`는 `ExchangeProvider`에만 정의되어 있으나, `TradeCoordinator`는 `ExecutionGateway` 타입만 참조한다. `ExecutionGateway`에 추가한다.

```python
# src/execution/base.py — ExecutionGateway에 추가
class ExecutionGateway(ABC):
    # ... 기존 메서드 ...

    @abstractmethod
    def get_open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """Query all open orders for a symbol.

        Args:
            symbol: Trading pair

        Returns:
            List of open order dictionaries
        """
        ...
```

**영향**:
- `OrderGateway`: 이미 `ExchangeProvider.get_open_orders` 구현 중 → 변경 없음
- `MockExchange`: 이미 `get_open_orders` 구현 중 → 변경 없음
- 둘 다 `ExecutionGateway`와 `ExchangeProvider` 모두 구현하므로 메서드 중복 없음

### 2.2 ExchangeProvider ABC — 변경 없음

`get_open_orders`가 `ExecutionGateway`에도 추가되지만, `ExchangeProvider`에서 제거하지 않는다.
`OrderGateway(ExecutionGateway, ExchangeProvider)` 다중 상속 구조에서 MRO 충돌 없음 (동일 시그니처).

---

## 3. 상세 설계

### 3.1 Phase 1: Pre-flight Open Order Check

#### 3.1.1 TradeCoordinator 변경

**파일**: `src/execution/trade_coordinator.py`

**신규 메서드**: `_pre_flight_check(symbol: str) -> bool`

```python
def _pre_flight_check(self, symbol: str) -> bool:
    """
    진입 전 대기 주문 검증 및 선행 정리.

    Returns:
        True: 진입 가능 (주문 없음 or 취소 완료)
        False: 진입 거절 (취소 실패)
    """
```

**흐름 상세**:

```
_pre_flight_check(symbol)
│
├── try:
│   │   orders = self._order_gateway.get_open_orders(symbol)
│   │
│   ├── orders 비어있음 → return True
│   │
│   └── orders 존재 →
│       ├── self.logger.warning(f"Pre-flight: {len(orders)} orphaned orders for {symbol}")
│       ├── try:
│       │   cancelled = self._order_gateway.cancel_all_orders(symbol)
│       │   ├── audit log: ORDER_CANCELLED, reason="pre_flight_cleanup"
│       │   └── return True
│       └── except:
│           ├── audit log: RISK_REJECTION, reason="orphaned_orders_cancel_failed"
│           └── return False
│
└── except Exception:
    ├── self.logger.warning("Pre-flight API failed, proceeding (fail-open)")
    ├── audit log: WARNING, reason="pre_flight_api_failure_fallthrough"
    └── return True  # 조건부 Fail-Open
```

**참고**: `get_open_orders` 대신 `get_open_orders_cached`를 직접 호출하지 않는다.
- 이유: `get_open_orders_cached`는 `OrderGateway` 전용 메서드 (ABC에 없음)
- 대신 `get_open_orders`를 호출하고, `OrderGateway` 내부에서 캐시 로직을 처리
- 추후 `OrderGateway.get_open_orders`를 캐시 우선으로 변경하는 것은 내부 최적화 영역

#### 3.1.2 on_signal_generated 흐름 삽입 위치

```python
async def on_signal_generated(self, event: Event) -> None:
    signal: Signal = event.data

    # ... (기존) Step 1-3: extract signal, get position, validate risk ...

    if signal.is_exit_signal:
        await self.execute_exit_signal(signal, current_position)
        return

    # ★ NEW: Step 3.5 — Pre-flight open order check
    if not self._pre_flight_check(signal.symbol):
        self.logger.warning(
            f"Signal rejected by pre-flight check: {signal.signal_type.value}"
        )
        # audit log: RISK_REJECTION
        return

    # ... (기존) Step 5-7: balance, position size, execute_signal ...
```

**삽입 위치 근거**:
- `validate_risk` **후**: 기본 검증을 먼저 통과해야 API 호출 비용 지불
- `get_account_balance` **전**: 잔여 주문 존재 시 불필요한 잔고 조회 회피
- 진입 시그널에만 적용 (exit 시그널은 이전에 return됨)

### 3.2 Phase 2: TP/SL 완전성 보장

#### 3.2.1 OrderGateway 변경

**파일**: `src/execution/order_gateway.py`

**신규 메서드**: `_ensure_tpsl_completeness`

```python
def _ensure_tpsl_completeness(
    self,
    signal: Signal,
    tpsl_orders: list[Order],
    tpsl_side: OrderSide,
    entry_order: Order,
) -> list[Order]:
    """
    TP/SL 배치 완전성 보장. 부족 시 재시도, 실패 시 즉시 청산.

    Args:
        signal: 원본 시그널 (TP/SL 가격 참조)
        tpsl_orders: 현재까지 배치된 TP/SL 주문 리스트
        tpsl_side: TP/SL 주문 방향
        entry_order: 진입 주문 (청산 시 수량 참조)

    Returns:
        최종 tpsl_orders 리스트 (2개 또는 빈 리스트 — 청산 시)
    """
```

**흐름 상세**:

```
_ensure_tpsl_completeness(signal, tpsl_orders, tpsl_side, entry_order)
│
├── len(tpsl_orders) >= 2 → return tpsl_orders (정상)
│
├── 부족한 주문 식별:
│   ├── has_tp = any(o for o in tpsl_orders if "TAKE_PROFIT" in o.order_type.value)
│   └── has_sl = any(o for o in tpsl_orders if "STOP" in o.order_type.value)
│
├── for attempt in range(2):  # 최대 2회 재시도
│   ├── time.sleep(1)  # 동기 대기 (execute_signal이 동기 메서드)
│   │
│   ├── if not has_tp:
│   │   tp = self._place_tp_order(signal, tpsl_side)
│   │   if tp: tpsl_orders.append(tp); has_tp = True
│   │
│   ├── if not has_sl:
│   │   sl = self._place_sl_order(signal, tpsl_side)
│   │   if sl: tpsl_orders.append(sl); has_sl = True
│   │
│   └── if len(tpsl_orders) >= 2 → break
│
├── if len(tpsl_orders) < 2:  # 재시도 실패 → 에스컬레이션
│   ├── self.logger.error("TP/SL incomplete after retries, emergency close")
│   │
│   ├── close_side = "SELL" if signal is LONG_ENTRY else "BUY"
│   ├── cancel_all_orders(signal.symbol)  # 배치된 1개도 정리
│   ├── execute_market_close(
│   │     symbol=signal.symbol,
│   │     position_amt=entry_order.quantity,
│   │     side=close_side,
│   │     reduce_only=True
│   │   )
│   │
│   ├── audit log: RISK_REJECTION, reason="incomplete_tpsl_emergency_close",
│   │   data={placed: len(tpsl_orders), missing: "TP"/"SL"/"both"}
│   │
│   └── return []  # 빈 리스트 — 청산되었음을 알림
│
└── return tpsl_orders
```

#### 3.2.2 execute_signal 내 호출 위치

```python
# order_gateway.py — execute_signal 내, 기존 line 1406-1416 대체

    else:
        # Entry signals: TP/SL completeness check
        tpsl_orders = self._ensure_tpsl_completeness(
            signal=signal,
            tpsl_orders=tpsl_orders,
            tpsl_side=tpsl_side,
            entry_order=entry_order,
        )

    return (entry_order, tpsl_orders)
```

#### 3.2.3 TradeCoordinator 측 처리

`execute_signal` 반환값의 `tpsl_orders`가 빈 리스트일 경우, 에스컬레이션으로 청산된 것:

```python
# trade_coordinator.py — on_signal_generated 내
entry_order, tpsl_orders = self._order_gateway.execute_signal(
    signal=signal, quantity=quantity
)

if not tpsl_orders:
    # TP/SL 에스컬레이션으로 즉시 청산됨
    self.logger.warning(
        f"Entry cancelled: TP/SL placement failed, position emergency-closed"
    )
    self._position_cache_manager.invalidate(signal.symbol)
    return
```

#### 3.2.4 execute_market_close 동기/비동기 문제

`execute_market_close`는 `async` 메서드이나, `execute_signal`은 동기 메서드이다.
`_ensure_tpsl_completeness` 내에서 직접 호출 불가.

**해결 방안**: 동기 버전 `_execute_market_close_sync` 내부 메서드 추가.

```python
def _execute_market_close_sync(
    self, symbol: str, position_amt: float, side: str, reduce_only: bool = True
) -> Dict[str, Any]:
    """동기 시장가 청산 — execute_signal 내부용."""
    formatted_qty = self._format_quantity(abs(position_amt), symbol)

    order_params = {
        "symbol": symbol,
        "side": side,
        "type": OrderType.MARKET.value,
        "quantity": formatted_qty,
        "reduceOnly": reduce_only,
    }

    response = self.client.new_order(**order_params)
    # ... parse response, audit log ...
    return {"success": True, "order_id": response.get("orderId"), ...}
```

**근거**: `execute_signal` 자체가 동기이고 `self.client.new_order`도 동기 호출이므로,
별도 이벤트 루프 호출 없이 직접 `client.new_order`를 호출하는 것이 가장 깔끔하다.
기존 `execute_market_close`의 `reduce_only=True` 강제 로직은 동일하게 적용.

### 3.3 Phase 3: Per-symbol Entry Guard

#### 3.3.1 TradeCoordinator 변경

**파일**: `src/execution/trade_coordinator.py`

**신규 속성**: `__init__`에 추가

```python
from collections import defaultdict
import asyncio

class TradeCoordinator:
    def __init__(self, ...):
        # ... 기존 ...
        self._entry_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
```

**on_signal_generated 변경**:

```python
async def on_signal_generated(self, event: Event) -> None:
    signal: Signal = event.data
    self.logger.info(f"Processing signal: {signal.signal_type.value} for {signal.symbol}")

    async with self._entry_locks[signal.symbol]:
        try:
            # ... 기존 전체 로직 (get_fresh → validate → pre_flight → execute) ...
        except Exception as e:
            # ... 기존 에러 처리 ...
```

**설계 결정**:
- `async with` 사용으로 `finally` 블록 불필요 (context manager가 자동 release)
- Lock 범위: 전체 `on_signal_generated` 로직 (get_fresh ~ execute_signal 완료)
- 심볼 간 독립: `BTCUSDT` Lock은 `ETHUSDT` 처리를 차단하지 않음
- exit 시그널도 Lock 범위 내: 동일 심볼의 진입/청산 경합 방지

---

## 4. 시퀀스 다이어그램

### 4.1 정상 진입 (잔여 주문 없음)

```
Strategy     TradeCoordinator          OrderGateway          Binance
   │               │                       │                    │
   ├─ Signal ──────>│                       │                    │
   │               ├─ Lock.acquire()        │                    │
   │               ├─ get_fresh()───────────>├─ get_position()──>│
   │               │<──────── position=None─┤<──────────────────┤
   │               ├─ validate_risk() ✓     │                    │
   │               ├─ _pre_flight_check()───>├─ get_open_orders()>│
   │               │<──────── orders=[] ────┤<──── [] ──────────┤
   │               │  return True           │                    │
   │               ├─ get_account_balance()─>│                    │
   │               ├─ calculate_position_size()                  │
   │               ├─ execute_signal()──────>├─ MARKET order ───>│
   │               │                       ├─ _place_tp_order()─>│
   │               │                       ├─ _place_sl_order()─>│
   │               │                       ├─ _ensure_tpsl: 2/2 ✓│
   │               │<──── (entry, [tp,sl])──┤                    │
   │               ├─ invalidate cache      │                    │
   │               ├─ Lock.release()        │                    │
```

### 4.2 잔여 주문 감지 → 선행 취소

```
Strategy     TradeCoordinator          OrderGateway          Binance
   │               │                       │                    │
   ├─ Signal ──────>│                       │                    │
   │               ├─ Lock.acquire()        │                    │
   │               ├─ get_fresh() → None    │                    │
   │               ├─ validate_risk() ✓     │                    │
   │               ├─ _pre_flight_check()───>├─ get_open_orders()>│
   │               │                       │<── [{SL},{TP}] ────┤
   │               │  ⚠️ 잔여 주문 감지     │                    │
   │               │                       ├─ cancel_all_orders()>│
   │               │<──── cancelled=2 ──────┤<──── OK ──────────┤
   │               │  audit: pre_flight_cleanup                  │
   │               │  return True           │                    │
   │               ├─ execute_signal()──────>│  (정상 진행)       │
```

### 4.3 TP/SL 부분 배치 → 에스컬레이션 청산

```
Strategy     TradeCoordinator          OrderGateway          Binance
   │               │                       │                    │
   │               ├─ execute_signal()──────>├─ MARKET order ───>│ ✓
   │               │                       ├─ _place_tp_order()─>│ ✓
   │               │                       ├─ _place_sl_order()─>│ ✗ 실패
   │               │                       │                    │
   │               │                       ├─ _ensure_tpsl: 1/2  │
   │               │                       ├─ retry 1: SL ──────>│ ✗ 실패
   │               │                       ├─ retry 2: SL ──────>│ ✗ 실패
   │               │                       │                    │
   │               │                       ├─ ⚠️ 에스컬레이션    │
   │               │                       ├─ cancel_all_orders()>│ (TP 정리)
   │               │                       ├─ market_close_sync()>│ (청산)
   │               │                       │  audit: incomplete_tpsl_emergency_close
   │               │<──── (entry, []) ──────┤                    │
   │               │                        │                    │
   │               ├─ tpsl_orders 비어있음   │                    │
   │               ├─ "Entry cancelled"     │                    │
   │               ├─ invalidate cache      │                    │
```

---

## 5. 에러 핸들링 매트릭스

| 상황 | 처리 | 결과 |
|------|------|------|
| `get_open_orders` API 실패 (캐시 미스) | Fail-Open + WARNING | 진입 진행 |
| `get_open_orders` 캐시 히트 + 주문 있음 | `cancel_all_orders` 선행 | 취소 후 진입 |
| `cancel_all_orders` 선행 취소 실패 | 진입 거절 + audit | 시그널 드롭 |
| TP 배치 실패 + SL 성공 (1/2) | 재시도 2회 → 즉시 청산 | 포지션 정리 |
| SL 배치 실패 + TP 성공 (1/2) | 재시도 2회 → 즉시 청산 | 포지션 정리 |
| TP/SL 모두 실패 (0/2) | 재시도 2회 → 즉시 청산 | 포지션 정리 |
| 즉시 청산(`market_close_sync`) 실패 | ERROR 로그 + audit | 수동 대응 필요 |
| Entry Lock 경합 (동일 심볼 시그널) | 후순위 시그널 대기 후 처리 | 순차 실행 |

---

## 6. Audit Log 이벤트

| 이벤트 | EventType | reason | 데이터 |
|--------|-----------|--------|--------|
| 잔여 주문 선행 취소 | `ORDER_CANCELLED` | `pre_flight_cleanup` | `{symbol, cancelled_count}` |
| 취소 실패 → 진입 거절 | `RISK_REJECTION` | `orphaned_orders_cancel_failed` | `{symbol, error}` |
| API 실패 Fail-Open | `RISK_REJECTION` | `pre_flight_api_failure_fallthrough` | `{symbol, error}` |
| TP/SL 재시도 성공 | (없음 — 기존 로그로 충분) | - | - |
| TP/SL 에스컬레이션 청산 | `RISK_REJECTION` | `incomplete_tpsl_emergency_close` | `{symbol, placed, missing}` |

---

## 7. 테스트 설계

### 7.1 Unit Tests — `test_trade_coordinator_with_mock.py`

| # | 테스트명 | 시나리오 | 검증 |
|---|---------|---------|------|
| 1 | `test_pre_flight_no_orders` | open orders = [] | execute_signal 호출됨 |
| 2 | `test_pre_flight_cancel_success` | open orders = [SL, TP], cancel 성공 | cancel 후 execute_signal 호출됨 |
| 3 | `test_pre_flight_cancel_failure` | open orders = [SL], cancel 실패 | execute_signal 미호출, audit log |
| 4 | `test_pre_flight_api_failure_failopen` | get_open_orders 예외 | execute_signal 호출됨 (Fail-Open) |
| 5 | `test_entry_lock_sequential` | 동일 심볼 2개 시그널 동시 | 첫 번째 완료 후 두 번째 실행, 두 번째는 position 존재로 거절 |

### 7.2 Unit Tests — `test_order_execution.py`

| # | 테스트명 | 시나리오 | 검증 |
|---|---------|---------|------|
| 6 | `test_tpsl_retry_success` | TP 성공, SL 실패 → 재시도 1회 성공 | 최종 tpsl_orders = 2 |
| 7 | `test_tpsl_retry_exhaust_emergency_close` | TP 성공, SL 3회 실패 | market_close_sync 호출, tpsl_orders = [] |
| 8 | `test_tpsl_emergency_close_reduce_only` | 에스컬레이션 청산 | reduce_only=True 강제 확인 |

---

## 8. 파일 변경 요약

| 파일 | 변경 유형 | 상세 |
|------|-----------|------|
| `src/execution/base.py` | **수정** | `ExecutionGateway`에 `get_open_orders` 추상 메서드 추가 |
| `src/execution/trade_coordinator.py` | **수정** | `_entry_locks` 속성, `_pre_flight_check` 메서드, `on_signal_generated` 흐름 변경, `tpsl_orders` 빈 리스트 처리 |
| `src/execution/order_gateway.py` | **수정** | `_ensure_tpsl_completeness` 메서드, `_execute_market_close_sync` 메서드, `execute_signal` 내 호출 |
| `tests/execution/test_trade_coordinator_with_mock.py` | **수정** | 테스트 5건 추가 |
| `tests/test_order_execution.py` | **수정** | 테스트 3건 추가 |

---

## 9. 구현 순서 (Phase별)

```
Phase 1 (P0): Pre-flight open order check
  1. base.py: ExecutionGateway에 get_open_orders 추가
  2. trade_coordinator.py: _pre_flight_check 메서드 구현
  3. trade_coordinator.py: on_signal_generated에 삽입
  4. 테스트 #1-4 작성 및 통과 확인

Phase 2 (P0): TP/SL 완전성 보장
  5. order_gateway.py: _execute_market_close_sync 구현
  6. order_gateway.py: _ensure_tpsl_completeness 구현
  7. order_gateway.py: execute_signal 내 기존 warning → 신규 메서드 호출로 대체
  8. trade_coordinator.py: tpsl_orders 빈 리스트 처리
  9. 테스트 #6-8 작성 및 통과 확인

Phase 3 (P1): Per-symbol entry guard
  10. trade_coordinator.py: _entry_locks 속성 추가
  11. trade_coordinator.py: on_signal_generated async with lock 적용
  12. 테스트 #5 작성 및 통과 확인
  13. 기존 테스트 회귀 확인
```
