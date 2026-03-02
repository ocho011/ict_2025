# Pre-flight Order Check Plan

> **Feature**: pre-flight-order-check
> **Status**: Draft
> **Author**: Claude Code (PDCA Plan)
> **Created**: 2026-03-02
> **PDCA Phase**: Plan

---

## 1. Overview

### 1.1 목적

`TradeCoordinator.on_signal_generated`에서 `execute_signal` 호출 **전** 대기 주문(open orders) 존재 여부를 검증하여, 잔여 TP/SL 주문이 새 포지션을 즉시 청산하는 CRITICAL 위험을 선제적으로 차단한다.

### 1.2 배경

- 현재 진입 게이트: **포지션 존재 여부**만 확인 (`RiskGuard.validate_risk` → `position is not None` 시 거절)
- 대기 주문 상태는 진입 판단에 **반영되지 않음**
- `cancel_all_orders`는 진입 MARKET 주문 체결 **후**에 호출 → 시간 갭(t3~t4) 존재
- 이 갭 동안 이전 포지션의 SL(`closePosition=true`)이 트리거되면 새 포지션 전량 즉시 청산
- `LiquidationManager`는 셧다운 시에만 작동 → 정상 운영 중 시나리오 커버 불가

### 1.3 선행 분석 결과 요약

| # | 발견 사항 | 심각도 | 현재 방어 |
|---|-----------|--------|-----------|
| 1 | 진입 전 대기 주문 검증 부재 — 잔여 TP/SL이 새 포지션 즉시 청산 가능 | **CRITICAL** | `cancel_all_orders` 사후 호출 (타이밍 갭) |
| 2 | 중복 시그널 방지 없음 — `get_fresh()` 반영 지연 시 동일 진입 2회 | **HIGH** | 없음 |
| 3 | 부분 TP/SL (1/2) 시 경고만 출력, SL 미배치 상태 운영 가능 | **CRITICAL** | 경고 로그 |

### 1.4 범위

| 항목 | 포함 | 제외 |
|------|------|------|
| Pre-flight open order 검증 (P0) | O | - |
| Per-symbol entry guard / asyncio.Lock (P1) | O | - |
| TP/SL 완전성 보장 — 재시도 + 즉시 청산 (P0) | O | - |
| 최소 R:R ratio 강제 (P2) | - | O (별도 PDCA) |
| `execute_signal` 내 exit dead code 정리 (P2) | - | O (별도 PDCA) |
| MockExchange 동기화 | - | O (별도 PDCA) |

---

## 2. 사용자 결정사항

| # | 질문 | 결정 |
|---|------|------|
| 1 | Fail-Open vs Fail-Close 정책 | **조건부 Fail-Open** — 캐시 히트 시 캐시 기준 판단, 캐시 미스+API 실패 시에만 Fail-Open |
| 2 | Entry cooldown 방식 | **asyncio.Lock per-symbol** — finally 블록에서 release 보장 |
| 3 | 부분 TP/SL 에스컬레이션 정책 | **재시도 후 즉시 청산** — 최대 2회 재시도, 실패 시 `execute_market_close(reduce_only=True)` |

---

## 3. AS-IS / TO-BE

### 3.1 AS-IS (현재 진입 흐름)

```
on_signal_generated(event)
  │
  ├── get_fresh(symbol)          → position 조회 (거래소 API)
  ├── validate_risk(signal, pos) → position 존재 시 거절
  │                                TP/SL 가격 논리 검증
  │                                ⚠️ open orders 미검증
  │                                ⚠️ 중복 시그널 방어 없음
  │
  ├── get_account_balance()
  ├── calculate_position_size()
  │
  └── execute_signal(signal, qty)
        ├── MARKET 주문 실행         ← 이미 체결됨
        ├── cancel_all_orders()      ← 사후 정리 (타이밍 갭)
        ├── _place_tp_order()
        └── _place_sl_order()        ← 실패 시 경고만 (1/2 허용)
```

**위험 시퀀스 (시나리오 A — 잔여 TP/SL + 새 진입):**
```
t0: LONG 포지션 보유 중 (TP/SL 대기 중)
t1: 수동으로 거래소에서 직접 청산 (WebSocket 미감지)
t2: get_fresh() → position=None
t3: validate_risk() → 통과 (position 없으므로)
t4: execute_signal() → MARKET BUY 체결 ← 새 LONG 진입
t5: cancel_all_orders() 호출 시도
    ⚠️ t4~t5 사이: 이전 SL(closePosition=true) 트리거 가능
    → 새 포지션 전량 즉시 청산
```

### 3.2 TO-BE (목표 진입 흐름)

```
on_signal_generated(event)
  │
  ├── ★ entry_locks[symbol].acquire()    ← P1: 중복 시그널 방지
  │
  ├── get_fresh(symbol)
  ├── validate_risk(signal, pos)
  │
  ├── ★ pre_flight_check(symbol)          ← P0: 신규 단계
  │     ├── get_open_orders_cached(symbol)
  │     │   ├── 캐시 히트 + 주문 있음 → cancel_all_orders() 선행
  │     │   ├── 캐시 히트 + 주문 없음 → 진행
  │     │   └── 캐시 미스 → get_open_orders(symbol) fresh 호출
  │     │       ├── 성공 → 주문 유무에 따라 처리
  │     │       └── 실패 → Fail-Open (경고 + 진행)
  │     └── cancel 실패 → 진입 거절 + audit log
  │
  ├── get_account_balance()
  ├── calculate_position_size()
  │
  └── execute_signal(signal, qty)
        ├── MARKET 주문 실행
        ├── _place_tp_order()
        ├── _place_sl_order()
        └── ★ TP/SL 완전성 검증              ← P0: 신규 단계
              ├── 2/2 배치 → 정상 완료
              ├── 1/2 → 재시도 (최대 2회)
              └── 재시도 실패 → execute_market_close(reduce_only=True)
  │
  └── ★ entry_locks[symbol].release()    ← finally 블록
```

---

## 4. 구현 항목

### 4.1 P0: Pre-flight Open Order Check

**위치**: `trade_coordinator.py` — `on_signal_generated` 내, `validate_risk` 후 `execute_signal` 전

**로직**:
1. `order_gateway.get_open_orders_cached(symbol)` 호출 (캐시 우선)
2. 캐시 미스 시 `order_gateway.get_open_orders(symbol)` fresh 호출
3. 주문 존재 시 → `cancel_all_orders(symbol)` 선행 실행
   - 취소 성공 → 진행
   - 취소 실패 → 진입 거절 + `RISK_REJECTION` audit log
4. API 호출 실패 시 (캐시 미스 + fresh 실패) → **Fail-Open** (경고 로그 + 진행)

**성능 예산**:
- `get_open_orders_cached`: 0ms (메모리 캐시 히트)
- `get_open_orders` fresh: ~50-200ms
- 기존 `execute_signal`: ~300-500ms → 상대적 오버헤드 허용 범위

**audit 기록**:
- 잔여 주문 감지 + 취소: `AuditEventType.ORDER_CANCELLED` + `reason: "pre_flight_cleanup"`
- 취소 실패로 진입 거절: `AuditEventType.RISK_REJECTION` + `reason: "orphaned_orders_cancel_failed"`
- API 실패 Fail-Open: WARNING 로그 + `reason: "pre_flight_api_failure_fallthrough"`

### 4.2 P0: TP/SL 완전성 보장

**위치**: `order_gateway.py` — `execute_signal` 내, TP/SL 배치 후 (`line 1412` 부근)

**로직**:
1. TP/SL 배치 결과: `len(tpsl_orders) < 2`
2. 부족한 주문 식별 (TP 누락 vs SL 누락)
3. 최대 2회 재시도 (1초 간격, 동기 — `execute_signal` 자체가 동기 메서드)
4. 재시도 후에도 `< 2`:
   - `execute_market_close(symbol, qty, close_side, reduce_only=True)` 호출
   - Audit log: `AuditEventType.RISK_REJECTION` + `reason: "incomplete_tpsl_emergency_close"`
   - 반환값을 통해 TradeCoordinator에 청산 사실 전달

**현재 코드** (`order_gateway.py:1412-1416`):
```python
if len(tpsl_orders) < 2:
    self.logger.warning(
        f"Partial TP/SL placement: entry filled but "
        f"only {len(tpsl_orders)}/2 exit orders placed"
    )
```

### 4.3 P1: Per-symbol Entry Guard

**위치**: `trade_coordinator.py` — `on_signal_generated` 최상단

**로직**:
1. `self._entry_locks: Dict[str, asyncio.Lock]` — 심볼별 Lock (defaultdict)
2. `on_signal_generated` 진입 시 `async with self._entry_locks[symbol]:` 으로 감싸기
3. 동일 심볼에 대해 동시 실행되는 시그널은 Lock 대기 → 순차 처리
4. Lock 내부에서 `get_fresh()` 호출 → 두 번째 시그널은 첫 번째 진입 반영된 포지션 조회

**대안 검토 (기각)**:
- Timestamp cooldown: 고정 시간 기반이라 유연성 낮고, 빠른 시장 전환 시 불필요한 거절 발생

---

## 5. 영향 받는 파일

| 파일 | 변경 내용 | 위험도 |
|------|-----------|--------|
| `src/execution/trade_coordinator.py` | pre-flight check 추가, entry_locks 추가 | 중 |
| `src/execution/order_gateway.py` | TP/SL 완전성 보장 로직 (재시도 + 즉시 청산) | 중 |
| `tests/execution/test_trade_coordinator_with_mock.py` | 신규 테스트 케이스 | 낮음 |
| `tests/test_order_execution.py` | TP/SL 에스컬레이션 테스트 | 낮음 |

---

## 6. 리스크 및 완화

| 리스크 | 확률 | 영향 | 완화 방안 |
|--------|------|------|-----------|
| Pre-flight API 실패로 Fail-Open 빈발 | 낮 | 중 | 캐시 우선 사용 + WARNING 모니터링 |
| Entry Lock으로 시그널 처리 지연 | 낮 | 낮 | Lock 범위를 execute_signal 완료까지만 한정 |
| TP/SL 재시도 중 가격 급변 | 낮 | 중 | 재시도 시 mark price 재조회 + 0.2% 조정 로직 재활용 |
| 즉시 청산이 슬리피지 발생 | 중 | 낮 | MARKET 주문 특성상 불가피, reduce_only로 안전 보장 |

---

## 7. 테스트 전략

| 테스트 | 검증 대상 | 유형 |
|--------|-----------|------|
| 잔여 주문 존재 시 선행 취소 후 정상 진입 | Pre-flight check 정상 동작 | Unit |
| 잔여 주문 취소 실패 시 진입 거절 | Fail-safe 동작 | Unit |
| 캐시 미스 + API 실패 시 Fail-Open 진행 | 조건부 Fail-Open 정책 | Unit |
| 캐시 히트 + 주문 존재 시 cancel 선행 | 캐시 기반 판단 | Unit |
| 중복 시그널 동시 도착 시 순차 처리 | asyncio.Lock 동작 | Integration |
| TP/SL 1/2 배치 → 재시도 → 완전 배치 | 재시도 로직 | Unit |
| TP/SL 재시도 실패 → 즉시 청산 | 에스컬레이션 동작 | Unit |
| 즉시 청산 시 reduce_only 강제 확인 | 안전장치 검증 | Unit |

---

## 8. 성능 검증 기준

| 메트릭 | 현재 | 목표 | 측정 방법 |
|--------|------|------|-----------|
| 진입 신호 → 주문 실행 지연 | ~300-500ms | ≤ 700ms | `time.perf_counter_ns()` |
| Pre-flight 추가 지연 | 0ms | ≤ 200ms (캐시 시 0ms) | API 호출 시간 측정 |
| Entry guard Lock 오버헤드 | 없음 | < 1μs (비경합 시) | Lock 래퍼 측정 |
| TP/SL 재시도 최대 지연 | 0ms | ≤ 2초 (2회 * 1초) | 재시도 루프 시간 측정 |

---

## 9. 구현 순서

```
Phase 1 (P0): Pre-flight open order check
  ├── trade_coordinator.py: pre_flight_check 메서드 추가
  ├── on_signal_generated 흐름에 삽입
  ├── audit log 연동
  └── 단위 테스트 4건

Phase 2 (P0): TP/SL 완전성 보장
  ├── order_gateway.py: 재시도 루프 추가 (line 1412 부근)
  ├── 재시도 실패 시 execute_market_close 호출
  ├── audit log 연동
  └── 단위 테스트 3건

Phase 3 (P1): Per-symbol entry guard
  ├── trade_coordinator.py: _entry_locks Dict 추가
  ├── on_signal_generated을 async with lock으로 감싸기
  ├── 통합 테스트 1건 (중복 시그널 시나리오)
  └── 기존 테스트 호환성 확인
```
