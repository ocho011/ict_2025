# CircuitBreaker 모듈 분석

> 분석 일자: 2026-02-11
> 파일 위치: `src/core/circuit_breaker.py`

## 1. 개요

**Circuit Breaker 패턴 구현체** - API 호출 실패 시 연쇄 장애(cascading failure)를 방지하는 회로 차단기.

### 핵심 기능
- **3가지 상태 관리**:
  - `CLOSED`: 정상 동작, 요청 통과
  - `OPEN`: 요청 차단 (실패 임계값 초과 시)
  - `HALF_OPEN`: 복구 테스트 (제한적 요청 허용)

### 동작 방식
1. 연속 실패가 `failure_threshold`(기본 5회) 도달 → OPEN 상태로 전환
2. `recovery_timeout`(기본 60초) 경과 → HALF_OPEN으로 전환
3. HALF_OPEN에서 성공 → CLOSED 복구, 실패 → OPEN 복귀

---

## 2. 예상 시나리오

### 2.1 Binance API 일시적 장애
```
상황: Binance 서버 점검, 과부하, CDN 이슈
문제: 주문 요청이 계속 타임아웃/실패
해결: Circuit Breaker가 OPEN → 불필요한 재시도 차단, 60초 후 자동 복구 테스트
```

### 2.2 Rate Limit 도달
```
상황: API 호출 한도 초과 (분당 1200회 등)
문제: 429 Too Many Requests 반복
해결: 실패 5회 누적 후 차단 → Rate Limit 리셋 대기 후 재시도
```

### 2.3 네트워크 불안정
```
상황: 사용자 네트워크 끊김, DNS 해싱 실패, SSL 인증서 문제
문제: 연결 실패가 반복되며 이벤트 루프 블로킹
해결: 즉시 차단하여 리소스 낭비 방지
```

### 2.4 주문 실행 중 서버 응답 지연
```python
# 코드에서 OrderExecutionError를 raise하는 이유
# 주문 실패가 반복되면 → 포지션 정리 불가 → 손실 확대 방지
```

### 2.5 WebSocket 연결 장애 시 Fallback API 호출
```
WebSocket 끊김 → REST API로 전환하여 데이터 수집
REST API도 실패 반복 → Circuit Breaker OPEN → 시스템 안전 모드 진입
```

---

## 3. 런타임 동작 구조

```
┌─────────────────────────────────────────────────────────────────┐
│                        프로그램 실행 흐름                         │
└─────────────────────────────────────────────────────────────────┘

1. 초기화 단계
   ┌──────────────────┐
   │   main.py 시작   │
   └────────┬─────────┘
            ↓
   ┌──────────────────┐
   │ OrderGateway 생성 │  ← src/execution/order_gateway.py 89번째 줄
   └────────┬─────────┘
            ↓
   ┌──────────────────────────────────────┐
   │ _position_circuit_breaker 인스턴스화  │
   │ - failure_threshold = 5              │
   │ - recovery_timeout = 60초            │
   └──────────────────────────────────────┘

2. 런타임 단계 (포지션 조회 시)
   ┌──────────────────────────────────────────────────────────────┐
   │                    get_position(symbol) 호출                 │
   │                       (1455번째 줄)                          │
   └──────────────────────────────────────────────────────────────┘
                              ↓
   ┌──────────────────────────────────────────────────────────────┐
   │  _position_circuit_breaker.call(                             │
   │      self.client.get_position_risk, symbol=symbol            │
   │  )                                                           │
   └──────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────┴─────────────────────┐
        ↓                                           ↓
   ┌─────────┐                               ┌─────────┐
   │ CLOSED  │ → API 호출 실행               │  OPEN   │ → 즉시 실패
   │ (정상)  │   client.get_position_risk() │ (차단)  │   OrderExecutionError
   └────┬────┘                               └────┬────┘
        ↓                                           ↓
   성공 → 유지                               60초 경과 → HALF_OPEN
   실패 → failure_count++                         ↓
   5회 누적 → OPEN                          테스트 호출 1회
                                            성공 → CLOSED
                                            실패 → OPEN
```

### 상태 전이 시나리오

| 상황 | CircuitBreaker 상태 | 결과 |
|------|---------------------|------|
| 정상 API 호출 | CLOSED | `get_position_risk()` 실행 → Position 반환 |
| API 5회 연속 실패 | CLOSED → OPEN | 이후 호출 즉시 `OrderExecutionError` |
| OPEN 상태에서 60초 대기 | OPEN → HALF_OPEN | 1회 테스트 호출 허용 |
| HALF_OPEN에서 성공 | HALF_OPEN → CLOSED | 정상 복구 |
| HALF_OPEN에서 실패 | HALF_OPEN → OPEN | 다시 차단 |

---

## 4. 적용 현황

### 현재 적용된 API

| API 호출 | 보호 메커니즘 | 위치 |
|----------|---------------|------|
| `get_position()` | **CircuitBreaker** | order_gateway.py 1455번째 줄 |
| `set_leverage()` | `@retry_with_backoff` | order_gateway.py 98번째 줄 |
| `set_margin_type()` | `@retry_with_backoff` | order_gateway.py 185번째 줄 |
| `execute_signal()` | `@retry_with_backoff` | order_gateway.py 1206번째 줄 |
| `_place_sl_order()` | `@retry_with_backoff` | order_gateway.py 721번째 줄 |
| `_place_tp_order()` | `@retry_with_backoff` | order_gateway.py 1022번째 줄 |
| `_refresh_exchange_info()` | `@retry_with_backoff` | order_gateway.py 363번째 줄 |

### 왜 포지션 조회에만 CircuitBreaker인가?

```python
# 포지션 조회는 "읽기" 작업 - 실패해도 안전하게 차단 가능
response = self._position_circuit_breaker.call(
    self.client.get_position_risk, symbol=symbol
)

# 주문 실행은 "쓰기" 작업 - 차단보다는 재시도가 더 안전
@retry_with_backoff(max_retries=3, initial_delay=1.0)
def execute_signal(...):
    ...
```

**설계 의도:**
- **읽기 API**: CircuitBreaker로 차단 (잘못된 데이터로 결정하는 것보다 중단이 나음)
- **쓰기 API**: Retry로 복구 시도 (주문 기회를 놓치는 것보다 재시도가 나음)

---

## 5. 확장 가능성

### 잠재적 확장 방안 (현재 미구현)

```python
class OrderGateway:
    def __init__(self, ...):
        # 포지션 조회용 (현재 구현)
        self._position_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
        )
        
        # (가능한 확장) 계좌 정보 조회용
        self._account_circuit_breaker = CircuitBreaker(...)
        
        # (가능한 확장) 시장 데이터 조회용
        self._market_data_circuit_breaker = CircuitBreaker(...)
```

### 확장 고려사항

| API 유형 | CircuitBreaker 적합성 | 이유 |
|----------|----------------------|------|
| 포지션 조회 | ✅ 적합 | 읽기 전용, 실패 시 안전하게 차단 |
| 계좌 잔고 조회 | ✅ 적합 | 읽기 전용, 리스크 계산 의존성 |
| 시장 데이터 조회 | ⚠️ 고려 | 읽기 전용이지만 대체 데이터源 가능 |
| 주문 실행 | ❌ 부적합 | 쓰기 작업, Retry가 더 적합 |
| 주문 취소 | ❌ 부적합 | 쓰기 작업, 즉시 실행 필요 |

---

## 6. 요약

| 항목 | 내용 |
|------|------|
| **용도** | API 연속 실패 시 연쇄 장애 방지 |
| **패턴** | Circuit Breaker (CLOSED → OPEN → HALF_OPEN) |
| **현재 적용** | `get_position()` API만 |
| **다른 API** | `@retry_with_backoff` 데코레이터 사용 |
| **확장 계획** | 코드상 명시된 계획 없음 |
| **핵심 의도** | 실시간 자동매매에서 API 장애 반복 시 즉시 거래 중단 |

---

## 7. 관련 파일

- `src/core/circuit_breaker.py` - CircuitBreaker 구현
- `src/execution/order_gateway.py` - CircuitBreaker 사용처
- `tests/test_position_manager_resilience.py` - 관련 테스트
