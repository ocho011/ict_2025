# Logging Cost Tracking Plan

> **Feature**: logging-cost-tracking
> **Status**: Draft
> **Author**: Claude Code (PDCA Plan)
> **Created**: 2026-03-02
> **PDCA Phase**: Plan

---

## 1. Overview

### 1.1 목적

AuditLogger의 JSONL 기록만으로 **실질 순손익(Net P&L)** 분석이 가능하도록 로깅 파이프라인을 보강한다. 현재 시스템은 Gross PnL(`(exit - entry) * qty`)만 기록하며, 커미션·펀딩비·슬리피지·잔고 스냅샷이 누락되어 실제 수익률 분석이 불가능하다.

### 1.2 배경

- **거래 환경**: Binance USDT-M Futures
- **전략 유형**: 중저빈도 + 복합(Multi-timeframe)
- **현재 문제**: 진단 분석(2026-03-02)에서 9개 갭(G1~G9) 식별
- **핵심 목표**: 트레이드별 Net PnL, 전략 비교, 리스크 메트릭 산출을 위한 로깅 완성

### 1.3 선행 분석 결과 요약 (진단 보고서 기준)

| Gap | 발견 사항 | 심각도 | 현재 상태 |
|-----|-----------|--------|-----------|
| G1 | **커미션 데이터 유실** — OrderUpdate→Order 변환 시 commission 필드 탈락 | **CRITICAL** | Order dataclass에 commission 필드 없음 |
| G2 | **펀딩비 파이프라인 미구현** — ACCOUNT_UPDATE "FUNDING_FEE" 이벤트 무시 | **CRITICAL** | `_handle_account_update()`가 Position만 파싱 |
| G3 | **슬리피지 추적 부재** — 의도 가격 vs 실제 체결가 비교 불가 | **MEDIUM** | signal.entry_price와 fill_price 분리 미기록 |
| G4 | **잔고 스냅샷 미기록** — equity curve / drawdown 산출 불가 | **HIGH** | BalanceUpdate 파싱 미사용, BALANCE_QUERY 미발행 |
| G5 | **position_id 부재** — 포지션 라이프사이클 추적 불가 | **HIGH** | symbol 키만 사용, 동일 심볼 연속 진입 구분 불가 |
| G6 | **거래소 타임스탬프 미사용** — event_time/transaction_time 미기록 | **MEDIUM** | OrderUpdate에 파싱됨, Order로 미전달 |
| G7 | AuditEventType 10개 미사용 enum 정리 | **LOW** | 코드 위생 |
| G8 | `data` vs `additional_data` 필드 불일치 | **LOW** | 호출부마다 다른 키 사용 |
| G9 | StrategyHotReloader 감사 로그 버그 (raw string vs enum) | **LOW** | 동작에는 영향 없으나 파싱 불일치 |

### 1.4 범위

| 항목 | 포함 | 제외 |
|------|------|------|
| G1: Order 모델에 commission 필드 추가 + 파이프라인 관통 | O | - |
| G2: 펀딩비 WebSocket 이벤트 처리 + 감사 로그 | O | - |
| G3: 슬리피지 추적 (intended_price vs fill_price) | O | - |
| G4: 잔고 스냅샷 주기적 기록 | O | - |
| G5: position_id UUID 도입 | O | - |
| G6: 거래소 타임스탬프 audit log 포함 | O | - |
| G7~G9: 코드 위생 정리 | O | - |
| Net PnL 계산 로직 (trade_coordinator) | O | - |
| 분석 스크립트/대시보드 구현 | - | O (별도 PDCA) |
| MockExchange 반영 (백테스트 동기화) | - | O (별도 PDCA) |
| MetricsCollector 시스템 확장 | - | O (별도 PDCA) |

---

## 2. 사용자 결정사항

| # | 질문 | 결정 |
|---|------|------|
| 1 | 거래 환경 | **Binance USDT-M Futures** |
| 2 | 전략 구조 | **중저빈도 + 복합(Multi-timeframe)** |
| 3 | 비용 데이터 현황 | **코드 확인 결과 누락** — 진단에서 G1~G6 확인 |
| 4 | 분석 목표 | **전부** — 트레이드별 Net PnL, 전략 비교, 리스크 메트릭 |

---

## 3. AS-IS / TO-BE

### 3.1 AS-IS: 현재 PnL 기록 흐름

```
WebSocket ORDER_TRADE_UPDATE
  → TradingEngine._on_order_fill_from_websocket()
    → OrderUpdate 파싱 (commission ✓, realized_pnl ✓, event_time ✓)
    → Order 객체 생성 (commission ✗, realized_pnl ✗, event_time ✗)  ← 데이터 유실!
  → TradeCoordinator.on_order_filled()
    → realized_pnl = (exit_price - entry_price) * quantity  ← Gross PnL만
    → AuditLogger.log_event(POSITION_CLOSED, realized_pnl=gross_pnl)
    → 커미션·펀딩비·슬리피지 = 기록 없음
```

**누락되는 비용 요소:**

| 비용 항목 | Binance 기준 | 연간 영향 (예상) | 현재 기록 |
|-----------|-------------|-----------------|-----------|
| 커미션 (Taker) | 0.04% per trade | 포지션당 ~0.08% | ✗ |
| 펀딩비 | 8시간마다, ±0.01~0.1% | 일일 ±0.03~0.3% | ✗ |
| 슬리피지 | 시장가 주문 시 1~5 bps | 포지션당 ~0.02% | ✗ |

### 3.2 TO-BE: 목표 PnL 기록 흐름

```
WebSocket ORDER_TRADE_UPDATE
  → TradingEngine._on_order_fill_from_websocket()
    → OrderUpdate 파싱 (기존 동일)
    → Order 객체 생성 (commission ✓, event_time ✓, transaction_time ✓)
  → TradeCoordinator.on_order_filled()
    → realized_pnl = gross_pnl
    → net_pnl = gross_pnl - total_commission - funding_fees
    → slippage = intended_price - fill_price
    → AuditLogger.log_event(POSITION_CLOSED, {
        gross_pnl, net_pnl, total_commission, total_funding,
        slippage_entry, slippage_exit, position_id, balance_after
      })

WebSocket ACCOUNT_UPDATE (reason="FUNDING_FEE")
  → PrivateUserStreamer._handle_account_update()
    → BalanceUpdate 파싱 (balance_change 추출)
    → AuditLogger.log_event(FUNDING_FEE_RECEIVED, {
        symbol, funding_rate, funding_fee, balance_after
      })

주기적 (매 closed candle 또는 설정 간격)
  → AuditLogger.log_event(BALANCE_SNAPSHOT, {
      wallet_balance, unrealized_pnl, equity, margin_ratio
    })
```

---

## 4. 구현 단계 (Phases)

### Phase 1: 커미션 파이프라인 복원 (G1 — CRITICAL)

**목표**: WebSocket에서 수신한 commission 데이터가 최종 audit log까지 관통

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/models/order.py` | `Order` dataclass에 `commission: float = 0.0`, `commission_asset: Optional[str] = None` 추가 |
| `src/core/trading_engine.py` | `_on_order_fill_from_websocket()`에서 Order 생성 시 commission 필드 전달 |
| `src/execution/trade_coordinator.py` | `on_order_filled()`에서 commission 누적, `log_position_closure()`에 total_commission 포함 |

**검증 기준:**
- `audit_YYYYMMDD.jsonl`의 POSITION_CLOSED 이벤트에 `total_commission` 필드 존재
- 값이 0이 아닌 실수 (Binance 테스트넷 또는 단위 테스트)

### Phase 2: 펀딩비 파이프라인 신규 구현 (G2 — CRITICAL)

**목표**: ACCOUNT_UPDATE "FUNDING_FEE" 이벤트를 파싱하여 audit log에 기록

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/core/audit_logger.py` | `AuditEventType.FUNDING_FEE_RECEIVED` enum 추가 |
| `src/core/private_user_streamer.py` | `_handle_account_update()`에서 B(Balance) 배열 파싱 + FUNDING_FEE reason 분기 |
| `src/execution/trade_coordinator.py` | 펀딩비 누적기 `_funding_fees: Dict[str, float]` 추가, 포지션 종료 시 합산 |

**검증 기준:**
- FUNDING_FEE_RECEIVED 이벤트가 8시간마다 기록됨
- POSITION_CLOSED 이벤트에 `total_funding` 필드 포함

### Phase 3: position_id + 거래소 타임스탬프 (G5, G6)

**목표**: 포지션 라이프사이클 추적을 위한 고유 ID 및 정확한 시간 기록

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/models/position.py` | `PositionEntryData`에 `position_id: str = field(default_factory=lambda: str(uuid4()))` 추가 |
| `src/models/order.py` | `Order`에 `event_time: Optional[datetime] = None`, `transaction_time: Optional[datetime] = None` 추가 |
| `src/core/trading_engine.py` | Order 생성 시 event_time/transaction_time 전달 |
| `src/execution/trade_coordinator.py` | 모든 audit log에 position_id 포함 |

**검증 기준:**
- 동일 심볼 연속 진입 시 서로 다른 position_id 부여
- audit log의 timestamp가 거래소 event_time 기준

### Phase 4: 슬리피지 추적 + 잔고 스냅샷 (G3, G4)

**목표**: 슬리피지 정량화 및 equity curve 산출 기반 마련

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/execution/trade_coordinator.py` | `on_order_filled()`에서 `signal.entry_price`(intended) vs `order.price`(fill) 차이 기록 |
| `src/core/audit_logger.py` | `AuditEventType.BALANCE_SNAPSHOT` enum 추가 (이미 정의되어 있으면 활성화) |
| `src/core/private_user_streamer.py` | ACCOUNT_UPDATE에서 B 배열의 wallet_balance 추출 |
| `src/execution/trade_coordinator.py` | 포지션 종료 시 balance_after 기록 |

**검증 기준:**
- POSITION_CLOSED에 `slippage_entry_bps`, `slippage_exit_bps` 필드 포함
- BALANCE_SNAPSHOT 이벤트 존재 또는 POSITION_CLOSED에 `balance_after` 필드 포함

### Phase 5: Net PnL 계산 로직 (핵심 목표)

**목표**: Gross PnL에서 모든 비용을 차감한 Net PnL 산출

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/execution/trade_coordinator.py` | `log_position_closure()`에서 `net_pnl = gross_pnl - total_commission - total_funding` 계산 |
| `src/execution/trade_coordinator.py` | audit log의 `realized_pnl` → `gross_pnl` 명명 변경, `net_pnl` 필드 추가 |

**검증 기준:**
- `net_pnl = gross_pnl - total_commission - total_funding` 등식 성립
- JSONL 파일에서 `jq` 쿼리로 전략별 Net PnL 합산 가능

### Phase 6: 코드 위생 정리 (G7~G9 — LOW)

**변경 파일:**
| 파일 | 변경 내용 |
|------|-----------|
| `src/core/audit_logger.py` | 미사용 AuditEventType 정리 또는 주석 표기 |
| `src/core/audit_logger.py` | `data` / `additional_data` 필드명 통일 가이드라인 추가 |
| `src/core/strategy_hot_reloader.py` | raw string → `AuditEventType.STRATEGY_HOT_RELOAD` enum 사용 |

**검증 기준:**
- 모든 `log_event()` 호출이 AuditEventType enum 사용
- grep으로 raw string 직접 전달 패턴 없음

---

## 5. 의존성 및 순서

```
Phase 1 (G1: commission) ──┐
                           ├── Phase 5 (Net PnL) ── Phase 6 (cleanup)
Phase 2 (G2: funding)   ──┤
                           │
Phase 3 (G5,G6: id/time) ─┤
                           │
Phase 4 (G3,G4: slip/bal) ─┘
```

- Phase 1~4는 **독립적으로 병렬 구현 가능**
- Phase 5는 Phase 1, 2 완료 필수 (commission + funding 데이터 필요)
- Phase 6는 언제든 진행 가능 (의존성 없음)

---

## 6. 리스크 및 완화

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| Order dataclass 필드 추가 시 기존 테스트 호환성 | Medium | default 값 사용 (commission=0.0), 기존 호출 영향 없음 |
| 펀딩비 이벤트 파싱 오류 시 잔고 불일치 | High | 감사 로그 only (거래 로직과 분리), 잘못 기록해도 실제 잔고 무관 |
| JSONL 파일 크기 증가 | Low | 기존 RotatingFileHandler 설정 활용, 필요시 보존 기간 조정 |
| Hot path 성능 영향 | Medium | audit log는 QueueHandler 비동기, 추가 필드는 메모리 연산만 |
| position_id UUID 생성 비용 | Low | uuid4()는 ~1μs, 진입 시 1회만 호출 |

---

## 7. 성공 기준 (Acceptance Criteria)

### 필수 (Must-Have)
- [ ] POSITION_CLOSED audit event에 `gross_pnl`, `net_pnl`, `total_commission`, `total_funding` 필드 존재
- [ ] `net_pnl = gross_pnl - total_commission - total_funding` 등식 성립
- [ ] FUNDING_FEE_RECEIVED audit event가 펀딩비 발생 시 기록됨
- [ ] 각 포지션에 고유 `position_id` 부여됨
- [ ] 모든 ORDER audit event에 `event_time` (거래소 기준) 포함

### 권장 (Should-Have)
- [ ] 슬리피지 bps 기록 (`slippage_entry_bps`, `slippage_exit_bps`)
- [ ] 포지션 종료 시 `balance_after` 기록
- [ ] AuditEventType raw string 사용 0건
- [ ] `jq` 1-liner로 전략별 Net PnL 합산 가능

### 선택 (Nice-to-Have)
- [ ] BALANCE_SNAPSHOT 주기적 이벤트
- [ ] 미사용 AuditEventType enum 정리

---

## 8. 영향받는 파일 요약

| 파일 | Phase | 변경 유형 |
|------|-------|-----------|
| `src/models/order.py` | 1, 3 | 필드 추가 |
| `src/models/position.py` | 3 | 필드 추가 |
| `src/core/trading_engine.py` | 1, 3 | Order 생성 로직 수정 |
| `src/execution/trade_coordinator.py` | 1, 2, 4, 5 | PnL 계산/로깅 핵심 변경 |
| `src/core/private_user_streamer.py` | 2, 4 | WebSocket 이벤트 파싱 확장 |
| `src/core/audit_logger.py` | 2, 4, 6 | enum 추가/정리 |
| `src/core/strategy_hot_reloader.py` | 6 | 버그 수정 |
| `tests/` (신규/수정) | 1~6 | 각 Phase별 단위 테스트 |

---

## 9. 구현 전 체크리스트

- [ ] Order dataclass 필드 추가가 frozen=True 와 호환되는지 확인
- [ ] PositionEntryData의 uuid 생성이 기존 직렬화와 호환되는지 확인
- [ ] AuditEventType에 FUNDING_FEE_RECEIVED가 이미 존재하는지 확인
- [ ] BALANCE_SNAPSHOT enum이 이미 정의되어 있는지 확인
- [ ] `_handle_account_update()`의 현재 이벤트 구조 재확인 (Binance API 문서)
