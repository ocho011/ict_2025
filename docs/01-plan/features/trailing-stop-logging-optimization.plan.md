# Plan: Trailing Stop Logging Optimization

> **Feature**: trailing-stop-logging-optimization
> **Created**: 2026-03-03
> **Status**: Draft
> **Level**: Dynamic

---

## 1. 목표 (Objective)

트레일링 스탑 파라미터(activation, distance) 최적화를 위한 **중간 상태 로깅 시스템**을 구축한다.
현재 진입/청산 가격과 최종 결과만 기록되어 "왜 그 시점에 청산되었는가?"를 사후 분석할 수 없다.
MFE/MAE, High-water mark, Price Path 로그를 추가하여 최적화 근거 데이터를 확보한다.

## 2. 현황 분석 (As-Is)

### 2.1 현재 로깅되는 이벤트

| 이벤트 | AuditEventType | 주요 필드 | 위치 |
|--------|---------------|----------|------|
| 진입 체결 | `TRADE_EXECUTED` | entry_price, quantity, leverage | `trade_coordinator.py` |
| 거래소 SL 업데이트 | `ORDER_PLACED` (재사용) | stop_price, update_reason | `order_gateway.py` |
| TP/SL/Trailing 체결 | `POSITION_CLOSED` | close_reason, gross/net_pnl, commission, funding, slippage, duration | `trade_coordinator.py` |
| 전략 기반 청산 | `TRADE_CLOSED` | exit_price, realized_pnl, exit_reason | `trade_coordinator.py` |

### 2.2 누락된 데이터

| 데이터 | 설명 | 최적화 활용 |
|--------|------|------------|
| **MFE** (Maximum Favorable Excursion) | 진입 이후 최대 수익 도달 지점 (%) | "얼마나 수익이 났었는데 놓쳤나" → activation 조정 |
| **MAE** (Maximum Adverse Excursion) | 진입 이후 최대 손실 도달 지점 (%) | "initial stop이 적절했나" → distance 조정 |
| **High-water mark** | MFE 달성 시점의 가격/시간 | "언제 최고점이었나" → trailing timing 분석 |
| **Trailing stop ratchet 이력** | 래칫 발생 시점, 이전/이후 stop 레벨 | "래칫 몇 번 했고 최종 stop은 얼마였나" |
| **되돌림 폭** (Drawdown from HWM) | 최고점 대비 청산 시 하락 폭 | "distance를 줄이면 더 잡았을까" |

### 2.3 관련 파일

| 파일 | 역할 |
|------|------|
| `src/core/audit_logger.py` | AuditEventType 정의, log_event() |
| `src/strategies/ict/exit.py` | ICTExitDeterminer, _trailing_levels, 래칫 로직 |
| `src/execution/trade_coordinator.py` | 포지션 진입/청산 이벤트 발행, PositionEntryData |
| `src/core/event_dispatcher.py` | maybe_update_exchange_sl(), candle 루프 |
| `src/models/position.py` | Position, PositionEntryData dataclass |

## 3. 설계 방향 (To-Be)

### 3.1 핵심 원칙

1. **Hot Path 성능 보존**: MFE/MAE 추적은 `float` 비교 2회 + 조건부 대입만 수행. Pydantic/datetime 변환 없음.
2. **기존 구조 최소 변경**: 새 클래스 추가보다 기존 `PositionEntryData`에 필드 추가를 우선.
3. **실거래/백테스트 공통**: AuditLogger 기반 JSONL 포맷으로 통일. 백테스트에서도 동일한 AuditLogger 사용 가능.
4. **분석 친화적 필드명**: `mfe_pct`, `mae_pct`, `hwm_price`, `drawdown_from_hwm_pct` 등 표준화.

### 3.2 변경 범위

#### Task 1: PositionEntryData에 MFE/MAE 추적 필드 추가
- **파일**: `src/models/position.py`
- **내용**: `PositionEntryData`에 `mfe_pct`, `mae_pct`, `hwm_price`, `hwm_timestamp` 필드 추가
- **타입**: `float` (slots=True 유지, 성능 영향 없음)

#### Task 2: MFE/MAE 실시간 업데이트 로직
- **파일**: `src/strategies/ict/exit.py` (ICTExitDeterminer)
- **내용**: `_check_trailing_stop_exit()` 내에서 매 캔들마다 MFE/MAE 갱신
- **로직**:
  ```
  LONG: mfe = max(mfe, (close - entry) / entry)
        mae = min(mae, (close - entry) / entry)  # 음수
  SHORT: mfe = max(mfe, (entry - close) / entry)
         mae = min(mae, (entry - close) / entry)  # 음수
  ```
- **접근**: `ExitContext`에 `PositionEntryData` 참조를 통해 갱신 (mutable 필드)
- **주의**: ExitContext는 frozen=True이므로, PositionEntryData를 직접 참조하는 방식 또는 exit determiner 내부에서 별도 dict로 관리

#### Task 3: TRAILING_STOP_RATCHETED 감사 이벤트 추가
- **파일**: `src/core/audit_logger.py`, `src/strategies/ict/exit.py`
- **내용**: 래칫 발생 시 전용 이벤트 발행 (기존 DEBUG 로그 → 감사 로그 승격)
- **이벤트 필드**:
  ```json
  {
    "event_type": "trailing_stop_ratcheted",
    "symbol": "BTCUSDT",
    "data": {
      "side": "LONG",
      "old_stop": 94000.0,
      "new_stop": 94500.0,
      "trigger_price": 96500.0,
      "ratchet_delta_pct": 0.53,
      "current_mfe_pct": 3.2,
      "candle_count_since_entry": 15
    }
  }
  ```

#### Task 4: POSITION_CLOSED / TRADE_CLOSED 이벤트에 MFE/MAE 필드 추가
- **파일**: `src/execution/trade_coordinator.py`
- **내용**: `log_position_closure()` 및 `execute_exit_signal()` 에서 closure_data에 MFE/MAE 관련 필드 추가
- **추가 필드**:
  ```json
  {
    "mfe_pct": 3.2,
    "mae_pct": -1.1,
    "hwm_price": 96500.0,
    "drawdown_from_hwm_pct": 2.1,
    "trailing_ratchet_count": 4,
    "trailing_final_stop": 94500.0
  }
  ```

#### Task 5: MFE/MAE 추적 상태 관리
- **파일**: `src/strategies/ict/exit.py` 또는 `src/execution/trade_coordinator.py`
- **내용**: 포지션별 MFE/MAE 상태를 관리하는 dict 추가 (`_position_metrics: Dict[str, PositionMetrics]`)
- **생명주기**: 포지션 진입 시 초기화 → 매 캔들 갱신 → 청산 시 로그에 포함 후 삭제
- **데이터 구조**:
  ```python
  @dataclass(slots=True)
  class PositionMetrics:
      entry_price: float
      mfe_pct: float = 0.0
      mae_pct: float = 0.0
      hwm_price: float = 0.0
      hwm_timestamp: int = 0  # epoch ms
      ratchet_count: int = 0
      last_trailing_stop: float = 0.0
      candle_count: int = 0
  ```

#### Task 6: 단위 테스트
- **파일**: `tests/unit/test_position_metrics.py` (신규)
- **내용**: MFE/MAE 갱신 로직, 래칫 이벤트 발행, 청산 시 필드 포함 검증

## 4. 성능 영향 분석

| 변경 항목 | Hot Path 영향 | 설명 |
|-----------|-------------|------|
| MFE/MAE float 비교 | < 100ns | `max()`/`min()` 2회 호출 |
| PositionMetrics candle_count 증가 | < 10ns | 정수 증분 |
| TRAILING_STOP_RATCHETED 이벤트 | QueueHandler 경유 | 비동기, 래칫 시에만 (드물게 발생) |
| POSITION_CLOSED 추가 필드 | 0 (청산 시 1회) | Cold Path |

**결론**: Hot Path 추가 지연 < 200ns (p99). 기존 성능 기준 (< 1ms p99) 내 충분히 여유.

## 5. 분석 활용 시나리오

### 5.1 trailing_activation 최적화
```
Query: mfe_pct 분포 vs trailing_activation 설정값
→ "MFE가 3% 이상인 거래가 80%인데 activation이 1%면, 더 높여도 되지 않을까?"
```

### 5.2 trailing_distance 최적화
```
Query: drawdown_from_hwm_pct 분포 vs trailing_distance 설정값
→ "최고점 대비 평균 1.5% 되돌림에서 청산되는데 distance가 2%면, 1.5%로 줄이면 더 잡을 수 있나?"
```

### 5.3 래칫 빈도 분석
```
Query: trailing_ratchet_count vs realized_pnl 상관관계
→ "래칫이 많을수록 수익이 큰가? 아니면 횡보장에서 불필요한 래칫이 많은가?"
```

## 6. 표준 로그 필드 정의

### 6.1 MFE/MAE 관련 필드 (POSITION_CLOSED / TRADE_CLOSED 에 추가)

| 필드명 | 타입 | 단위 | 설명 |
|--------|------|------|------|
| `mfe_pct` | float | % | 진입가 대비 최대 수익률 |
| `mae_pct` | float | % | 진입가 대비 최대 손실률 (음수) |
| `hwm_price` | float | USDT | MFE 달성 시점 가격 |
| `drawdown_from_hwm_pct` | float | % | HWM 대비 청산가 되돌림 폭 |
| `trailing_ratchet_count` | int | 횟수 | 래칫 발생 횟수 |
| `trailing_final_stop` | float | USDT | 최종 트레일링 스탑 레벨 |
| `candle_count` | int | 개수 | 진입 이후 경과 캔들 수 |

### 6.2 래칫 이벤트 필드 (TRAILING_STOP_RATCHETED)

| 필드명 | 타입 | 단위 | 설명 |
|--------|------|------|------|
| `side` | str | - | LONG / SHORT |
| `old_stop` | float | USDT | 래칫 이전 스탑 레벨 |
| `new_stop` | float | USDT | 래칫 이후 스탑 레벨 |
| `trigger_price` | float | USDT | 래칫 트리거한 캔들 종가 |
| `ratchet_delta_pct` | float | % | 스탑 레벨 변동률 |
| `current_mfe_pct` | float | % | 현 시점 MFE |
| `candle_count_since_entry` | int | 개수 | 진입 이후 캔들 수 |

## 7. 구현 순서 및 의존성

```
Task 5 (PositionMetrics 구조 정의)
  └→ Task 1 (PositionEntryData 필드 확장) — 병렬 가능
  └→ Task 2 (MFE/MAE 실시간 갱신)
      └→ Task 3 (TRAILING_STOP_RATCHETED 이벤트)
      └→ Task 4 (POSITION_CLOSED/TRADE_CLOSED 필드 추가)
          └→ Task 6 (단위 테스트)
```

## 8. 리스크 및 고려사항

| 리스크 | 대응 |
|--------|------|
| ExitContext가 frozen dataclass | PositionMetrics는 exit determiner 내부 dict로 관리 (ExitContext 수정 불필요) |
| 백테스트에서 AuditLogger 미사용 가능성 | 백테스트 모드에서도 AuditLogger 초기화 확인 필요 |
| 메모리: 심볼 수만큼 PositionMetrics 유지 | 청산 시 즉시 삭제, 심볼 수 제한적 (10개 미만) |
| 기존 로그 파싱 스크립트 호환성 | 새 필드는 추가만 (기존 필드 변경 없음), 후방 호환 |

## 9. 성공 기준

- [ ] 모든 POSITION_CLOSED / TRADE_CLOSED 이벤트에 `mfe_pct`, `mae_pct`, `hwm_price`, `drawdown_from_hwm_pct` 필드 포함
- [ ] 래칫 발생 시 `TRAILING_STOP_RATCHETED` 감사 이벤트 기록
- [ ] Hot Path 지연 증가 < 1μs (기존 대비)
- [ ] 단위 테스트 커버리지: MFE/MAE 갱신, 래칫 이벤트, 청산 시 필드 포함
- [ ] 기존 테스트 전체 통과 (회귀 없음)
