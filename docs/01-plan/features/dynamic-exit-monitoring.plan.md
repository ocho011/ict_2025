# Feature Plan: Dynamic Position Exit Monitoring (Issue #117)

## 1. 개요 (Overview)
Dynamic Exit 메커니즘(Trailing Stop, Breakeven)의 내부 상태를 실시간으로 관찰할 수 있는 모니터링 로깅을 추가합니다. 현재 exit이 트리거될 때만 로그가 남아, 가격이 activation threshold에 미달하여 작동하지 않는 것인지 로직 자체에 결함이 있는 것인지 구분할 수 없는 문제를 해결합니다.

## 2. 목표 (Goals)
- **관찰 가능성(Observability) 확보:** Exit 전략 분석이 시작되었는지, 현재 PnL 및 trailing level이 얼마인지, SL 업데이트가 왜 skip되었는지를 로그로 확인 가능하게 함
- **Silent Failure 탐지:** 메커니즘이 실행되지 않거나 조용히 실패하는 경우를 식별 가능하게 함
- **Hot Path 성능 유지:** CLAUDE.md 가이드라인에 따라 INFO 레벨은 주문 시에만, DEBUG 레벨은 운영환경에서 비활성화 기준 준수
- **Testnet 검증:** 추가된 로깅이 실제 환경에서 올바르게 동작하는지 확인

## 3. 범위 (Scope)
### 포함 (In-Scope)
- `ICTExitDeterminer._check_trailing_stop_exit()`: 분석 시작, PnL 상태, trailing level ratchet 로깅
- `ICTExitDeterminer._check_breakeven_exit()`: 분석 시작, PnL 상태 로깅
- `EventDispatcher.maybe_update_exchange_sl()`: SL 업데이트 skip 사유 로깅
- 기존 테스트 호환성 유지

### 제외 (Out-of-Scope)
- 새로운 exit 전략 로직 개발
- `_check_timed_exit()`, `_check_indicator_based_exit()` (이슈에서 요구하지 않음)
- UI/대시보드 변경
- 성능 메트릭 수집 인프라

## 4. 현행 분석 (Current State Analysis)

### 4.1 실행 플로우
```
EventDispatcher.on_candle_closed()
  → process_exit_strategy(candle, strategy, position)
    → ComposableStrategy.should_exit(position, candle)
      → ICTExitDeterminer.should_exit(context)
        → _check_trailing_stop_exit(context)  ← 모니터링 대상 1
    → (exit_signal이 None이면)
    → maybe_update_exchange_sl(candle, strategy, position)  ← 모니터링 대상 2
```

### 4.2 현재 로깅 상태 (Gaps)

| 위치 | 현재 로그 | 누락된 정보 |
|------|-----------|-------------|
| `ict_exit.py:124-128` | Trailing stop **trigger** 시에만 INFO | 분석 시작, PnL, activation 미달 사유 |
| `ict_exit.py:118-119` | Ratchet(level 갱신) 시 **로그 없음** | 새 trailing level, 이전 대비 변화량 |
| `ict_exit.py:189-193` | Breakeven **trigger** 시에만 INFO | 분석 시작, PnL, threshold 미달 사유 |
| `event_dispatcher.py:253` | Movement < 0.1% 시 **silent return** | Skip 사유 및 현재 movement 값 |
| `event_dispatcher.py:246` | trailing_levels에 key 없을 때 **silent return** | trail_key 부재 사유 |

### 4.3 관련 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/exit/ict_exit.py` | Trailing stop/breakeven DEBUG 로깅 추가 |
| `src/core/event_dispatcher.py` | SL update skip 사유 DEBUG 로깅 추가 |
| `tests/test_exit/test_ict_exit.py` | 로깅 출력 검증 테스트 (선택) |

## 5. 구현 계획 (Implementation Plan)

### Phase 1: `_check_trailing_stop_exit` 모니터링 로깅 추가

**파일:** `src/exit/ict_exit.py`

**추가할 로그 포인트:**

1. **분석 시작 로그** (line ~105, try 블록 시작 후)
   ```python
   self.logger.debug(
       "[%s] Trailing stop analysis: side=%s, entry=%.4f, close=%.4f, "
       "pnl=%.2f%%, activation_threshold=%.2f%%",
       context.symbol, position.side, position.entry_price, candle.close,
       pnl_pct, exit_config.trailing_activation * 100
   )
   ```

2. **Activation 미달 로그** (line ~116, activation 조건 불충족 시)
   ```python
   self.logger.debug(
       "[%s] Trailing stop not activated: close=%.4f < activation=%.4f (need +%.2f%%)",
       context.symbol, candle.close, activation_price, shortfall_pct
   )
   ```

3. **Trailing level ratchet 로그** (line ~118-119, level 갱신 시)
   ```python
   self.logger.debug(
       "[%s] Trailing stop ratcheted: %.4f → %.4f (Δ%.2f%%)",
       context.symbol, old_stop, trailing_stop, delta_pct
   )
   ```

4. **캔들 종가 vs trailing stop 거리 로그** (line ~121, level 저장 후)
   ```python
   self.logger.debug(
       "[%s] Trailing stop status: level=%.4f, close=%.4f, distance=%.2f%% (trigger when ≤0)",
       context.symbol, trailing_stop, candle.close, distance_pct
   )
   ```

### Phase 2: `_check_breakeven_exit` 모니터링 로깅 추가

**파일:** `src/exit/ict_exit.py`

**추가할 로그 포인트:**

1. **분석 시작 로그** (line ~176, try 블록 시작 후)
   ```python
   self.logger.debug(
       "[%s] Breakeven analysis: side=%s, entry=%.4f, close=%.4f, pnl=%.2f%%",
       context.symbol, position.side, position.entry_price, candle.close, pnl_pct
   )
   ```

2. **Threshold 미달 로그** (조건 불충족 시)
   ```python
   self.logger.debug(
       "[%s] Breakeven not activated: profit_threshold=%.4f not reached",
       context.symbol, profit_threshold
   )
   ```

### Phase 3: `maybe_update_exchange_sl` 모니터링 로깅 추가

**파일:** `src/core/event_dispatcher.py`

**추가할 로그 포인트:**

1. **TrailingLevelProvider 미구현** (line ~237)
   ```python
   self.logger.debug("Strategy does not implement TrailingLevelProvider for %s", candle.symbol)
   ```

2. **trailing_levels 비어있음** (line ~241)
   ```python
   self.logger.debug("No trailing levels available for %s", candle.symbol)
   ```

3. **trail_key 부재** (line ~246)
   ```python
   self.logger.debug("No trailing level for key %s", trail_key)
   ```

4. **Movement threshold 미달** (line ~253)
   ```python
   self.logger.debug(
       "Exchange SL update skipped for %s: movement=%.4f%% < threshold=0.1%%",
       candle.symbol, movement * 100
   )
   ```

### Phase 4: Testnet 검증

1. DEBUG 레벨 활성화 후 Testnet에서 포지션 오픈
2. 로그에서 다음을 확인:
   - "Trailing stop analysis" 로그가 매 캔들마다 출력되는지
   - Activation 미달/ratchet/status 로그가 상황에 맞게 출력되는지
   - Exchange SL skip 사유가 명시되는지
3. 전략 동작에 영향이 없는지 확인 (기존 테스트 통과)

## 6. 설계 원칙 (Design Principles)

### Hot Path 성능 보호
- 모든 모니터링 로그는 **DEBUG 레벨**로 추가 (운영환경에서 비활성화)
- 문자열 포매팅은 `%` 스타일 사용 (lazy evaluation, DEBUG 비활성화 시 포매팅 안 함)
- 새로운 객체 할당이나 I/O 없이 기존 변수만 활용

### 기존 로그 체계 유지
- 기존 INFO 레벨 로그(trigger 시) 변경 없음
- 기존 ERROR 로그 변경 없음
- DEBUG 로그만 추가하여 backward compatible

## 7. 리스크 및 완화 (Risks & Mitigations)

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| DEBUG 로그 과다로 디스크 I/O 증가 | Low | 운영환경 DEBUG 비활성화 정책 준수 |
| 로그 포맷 변경으로 기존 파싱 도구 영향 | Low | 기존 로그 변경 없음, 새 로그만 추가 |
| 로깅 추가로 인한 Hot Path 지연 | Low | `%` 스타일 + DEBUG 레벨 = lazy eval |

## 8. 완료 기준 (Done Criteria)
- [ ] `_check_trailing_stop_exit`: 분석 시작, PnL, activation 상태, ratchet, distance 로그 추가
- [ ] `_check_breakeven_exit`: 분석 시작, PnL, threshold 상태 로그 추가
- [ ] `maybe_update_exchange_sl`: skip 사유별 로그 추가
- [ ] 기존 테스트 통과
- [ ] Testnet에서 포지션 활성 상태에서 DEBUG 로그 출력 확인
