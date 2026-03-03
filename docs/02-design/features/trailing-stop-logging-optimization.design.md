# Design: Trailing Stop Logging Optimization

> **Feature**: trailing-stop-logging-optimization
> **Created**: 2026-03-03
> **Status**: Draft
> **Plan**: [trailing-stop-logging-optimization.plan.md](../../01-plan/features/trailing-stop-logging-optimization.plan.md)

---

## 1. 설계 개요

포지션 보유 중 MFE/MAE/HWM 등 중간 상태를 추적하여 트레일링 스탑 파라미터 최적화 근거를 확보한다.
ICTExitDeterminer 내부에 `_position_metrics` dict를 추가하고, 매 캔들마다 경량 갱신 후 청산 시 감사 로그에 포함한다.

### 설계 원칙
1. **ICTExitDeterminer 자체 관리**: `_trailing_levels`와 동일한 패턴으로 `_position_metrics` dict를 관리. ExitContext 변경 불필요.
2. **TradeCoordinator에 metrics 전달**: 청산 시 metrics를 Signal의 metadata로 전달하거나, exit determiner에서 직접 audit 로깅.
3. **Hot Path 최소 영향**: float 비교/대입만 수행, 조건부 감사 로그는 QueueHandler 경유.

## 2. 데이터 구조

### 2.1 PositionMetrics (신규 dataclass)

**위치**: `src/models/position.py`

```python
@dataclass(slots=True)
class PositionMetrics:
    """
    포지션 보유 중 MFE/MAE/HWM 추적을 위한 경량 구조체.

    ICTExitDeterminer._position_metrics dict에서 관리.
    키: "{symbol}_{side}" (trailing_levels와 동일 패턴)
    """
    entry_price: float
    side: str  # "LONG" or "SHORT"
    mfe_pct: float = 0.0       # Maximum Favorable Excursion (%)
    mae_pct: float = 0.0       # Maximum Adverse Excursion (%, 음수)
    hwm_price: float = 0.0     # High-water mark 가격 (MFE 시점)
    lwm_price: float = 0.0     # Low-water mark 가격 (MAE 시점)
    ratchet_count: int = 0     # 트레일링 래칫 횟수
    last_trailing_stop: float = 0.0  # 최종 트레일링 스탑 레벨
    candle_count: int = 0      # 진입 이후 경과 캔들 수
```

**설계 결정**:
- `slots=True` 사용: 메모리 효율, attribute access 빠름
- `hwm_timestamp` 제외: datetime 파싱은 Hot Path 위반. 필요 시 래칫 이벤트 로그의 timestamp로 대체 가능
- `lwm_price` 추가: MAE 시점의 실제 가격 (분석에서 유용)

### 2.2 AuditEventType 추가

**위치**: `src/core/audit_logger.py`

```python
class AuditEventType(Enum):
    # ... 기존 이벤트 ...

    # Trailing stop optimization events
    TRAILING_STOP_RATCHETED = "trailing_stop_ratcheted"
```

**1개만 추가**하는 이유:
- 래칫 이벤트만 신규 이벤트 타입 필요 (빈도: 포지션당 수~십수 회)
- MFE/MAE 데이터는 기존 `POSITION_CLOSED`/`TRADE_CLOSED` 이벤트의 data 필드에 추가 (이벤트 타입 신규 불필요)

## 3. 구현 상세

### 3.1 ICTExitDeterminer 변경

**파일**: `src/strategies/ict/exit.py`

#### 3.1.1 `__init__` 변경

```python
def __init__(self, ...):
    # ... 기존 코드 ...
    self._trailing_levels: dict[str, float] = {}
    self._position_metrics: dict[str, "PositionMetrics"] = {}  # 신규
```

#### 3.1.2 `_check_trailing_stop_exit` 변경

`_check_trailing_stop_exit()` 메서드 내에서 MFE/MAE 갱신 및 래칫 이벤트 로깅을 추가한다.

**삽입 위치 1**: 메서드 시작부 (pnl_pct 계산 직후, LONG/SHORT 분기 전)

```python
def _check_trailing_stop_exit(self, context: ExitContext) -> Optional[Signal]:
    try:
        position = context.position
        candle = context.candle
        exit_config = self.exit_config
        trail_key = f"{context.symbol}_{position.side}"

        pnl_pct = (...)  # 기존 코드

        # --- 신규: MFE/MAE 갱신 ---
        metrics = self._position_metrics.get(trail_key)
        if metrics is None:
            metrics = PositionMetrics(
                entry_price=position.entry_price,
                side=position.side,
                hwm_price=position.entry_price,
                lwm_price=position.entry_price,
            )
            self._position_metrics[trail_key] = metrics

        metrics.candle_count += 1

        if pnl_pct > metrics.mfe_pct:
            metrics.mfe_pct = pnl_pct
            metrics.hwm_price = candle.close
        if pnl_pct < metrics.mae_pct:
            metrics.mae_pct = pnl_pct
            metrics.lwm_price = candle.close
        # --- 신규 끝 ---

        if position.side == "LONG":
            # ... 기존 코드 ...
```

**Hot Path 비용**: `dict.get()` 1회 + `float` 비교 2회 + 조건부 대입 ≈ **< 200ns**

**삽입 위치 2**: 래칫 발생 시점 (LONG 케이스 line 178-185, SHORT 케이스 line 226-233)

```python
# LONG 래칫 발생 후 (기존 debug 로그 바로 아래)
if new_stop > trailing_stop:
    old_stop = trailing_stop
    trailing_stop = new_stop
    self.logger.debug(...)  # 기존

    # --- 신규: 래칫 이벤트 감사 로그 ---
    metrics.ratchet_count += 1
    metrics.last_trailing_stop = trailing_stop
    self._log_ratchet_event(
        symbol=context.symbol,
        side=position.side,
        old_stop=old_stop,
        new_stop=trailing_stop,
        trigger_price=candle.close,
        metrics=metrics,
    )
    # --- 신규 끝 ---
```

SHORT 케이스도 동일 패턴.

**삽입 위치 3**: 트레일링 스탑 트리거 시 (exit signal 반환 직전)

```python
if candle.close <= trailing_stop:  # LONG exit
    self.logger.info(...)  # 기존
    self._trailing_levels.pop(trail_key, None)

    # --- 신규: metrics 최종 업데이트 후 보존 (청산 로그에서 사용) ---
    metrics.last_trailing_stop = trailing_stop
    # _position_metrics는 여기서 pop하지 않음!
    # TradeCoordinator가 get_and_clear_metrics()로 가져감
    # --- 신규 끝 ---

    return Signal(...)
```

#### 3.1.3 신규 메서드

```python
def _log_ratchet_event(
    self,
    symbol: str,
    side: str,
    old_stop: float,
    new_stop: float,
    trigger_price: float,
    metrics: "PositionMetrics",
) -> None:
    """래칫 발생 시 감사 로그 기록. QueueHandler 경유 비동기."""
    try:
        from src.core.audit_logger import AuditLogger, AuditEventType

        audit = AuditLogger.get_instance()
        ratchet_delta_pct = abs(new_stop - old_stop) / old_stop * 100

        audit.log_event(
            event_type=AuditEventType.TRAILING_STOP_RATCHETED,
            operation="trailing_stop_ratchet",
            symbol=symbol,
            data={
                "side": side,
                "old_stop": round(old_stop, 6),
                "new_stop": round(new_stop, 6),
                "trigger_price": round(trigger_price, 6),
                "ratchet_delta_pct": round(ratchet_delta_pct, 4),
                "current_mfe_pct": round(metrics.mfe_pct, 4),
                "current_mae_pct": round(metrics.mae_pct, 4),
                "ratchet_count": metrics.ratchet_count,
                "candle_count_since_entry": metrics.candle_count,
            },
        )
    except Exception as e:
        self.logger.debug("Ratchet audit log failed: %s", e)

def get_and_clear_metrics(self, symbol: str, side: str) -> Optional["PositionMetrics"]:
    """
    포지션 청산 시 TradeCoordinator가 호출하여 metrics를 가져가고 삭제.

    Args:
        symbol: 심볼 (e.g., "BTCUSDT")
        side: 포지션 사이드 ("LONG" or "SHORT")

    Returns:
        PositionMetrics if exists, None otherwise
    """
    trail_key = f"{symbol}_{side}"
    return self._position_metrics.pop(trail_key, None)
```

### 3.2 TradeCoordinator 변경

**파일**: `src/execution/trade_coordinator.py`

#### 3.2.1 exit determiner 참조 추가

TradeCoordinator가 ICTExitDeterminer의 `get_and_clear_metrics()`를 호출할 수 있어야 한다.

**방법**: TradeCoordinator 생성자에 `exit_determiner` 참조를 optional로 추가하거나,
EventBus를 통해 전달.

**선택**: EventDispatcher가 이미 strategy(→ exit_determiner) 참조를 가지고 있으므로,
TradeCoordinator 생성 시 `exit_determiner` callable을 주입한다.

```python
class TradeCoordinator:
    def __init__(
        self,
        # ... 기존 파라미터 ...
        get_position_metrics: Optional[Callable[[str, str], Optional["PositionMetrics"]]] = None,
    ):
        # ... 기존 코드 ...
        self._get_position_metrics = get_position_metrics
```

#### 3.2.2 `log_position_closure` 변경 (POSITION_CLOSED)

`closure_data` 딕셔너리에 metrics 필드 추가:

```python
def log_position_closure(self, order: Order) -> None:
    # ... 기존 closure_data 구성 ...

    entry_data = self._position_entry_data.pop(order.symbol, None)
    if entry_data:
        # ... 기존 PnL/duration/slippage 계산 ...

        # --- 신규: MFE/MAE metrics 추가 ---
        if self._get_position_metrics:
            metrics = self._get_position_metrics(order.symbol, entry_data.side)
            if metrics:
                closure_data["mfe_pct"] = round(metrics.mfe_pct, 4)
                closure_data["mae_pct"] = round(metrics.mae_pct, 4)
                closure_data["hwm_price"] = round(metrics.hwm_price, 6)
                closure_data["lwm_price"] = round(metrics.lwm_price, 6)
                closure_data["trailing_ratchet_count"] = metrics.ratchet_count
                closure_data["trailing_final_stop"] = round(metrics.last_trailing_stop, 6)
                closure_data["candle_count"] = metrics.candle_count

                # 되돌림 폭 계산 (HWM 대비 청산가)
                if metrics.hwm_price > 0 and entry_data.side == "LONG":
                    drawdown = (metrics.hwm_price - order.price) / metrics.hwm_price * 100
                    closure_data["drawdown_from_hwm_pct"] = round(drawdown, 4)
                elif metrics.lwm_price > 0 and entry_data.side == "SHORT":
                    drawdown = (order.price - metrics.lwm_price) / metrics.lwm_price * 100
                    closure_data["drawdown_from_hwm_pct"] = round(drawdown, 4)
        # --- 신규 끝 ---

    # ... 기존 audit log 발행 ...
```

#### 3.2.3 `execute_exit_signal` 변경 (TRADE_CLOSED)

`data` 딕셔너리에 metrics 필드 추가:

```python
async def execute_exit_signal(self, signal: Signal, position: "Position") -> None:
    # ... 기존 코드 ...

    if result.get("success"):
        # ... 기존 PnL 계산 ...

        # --- 신규: MFE/MAE metrics 추가 ---
        trade_data = {
            "exit_price": exit_price,
            "realized_pnl": realized_pnl,
            "exit_reason": signal.exit_reason,
            "duration_seconds": duration_seconds,
            "entry_price": position.entry_price,
            "quantity": executed_qty,
            "position_side": position.side,
            "leverage": position.leverage,
            "signal_type": signal.signal_type.value,
        }

        if self._get_position_metrics:
            metrics = self._get_position_metrics(signal.symbol, position.side)
            if metrics:
                trade_data["mfe_pct"] = round(metrics.mfe_pct, 4)
                trade_data["mae_pct"] = round(metrics.mae_pct, 4)
                trade_data["hwm_price"] = round(metrics.hwm_price, 6)
                trade_data["lwm_price"] = round(metrics.lwm_price, 6)
                trade_data["trailing_ratchet_count"] = metrics.ratchet_count
                trade_data["trailing_final_stop"] = round(metrics.last_trailing_stop, 6)
                trade_data["candle_count"] = metrics.candle_count

                if metrics.hwm_price > 0 and position.side == "LONG":
                    drawdown = (metrics.hwm_price - exit_price) / metrics.hwm_price * 100
                    trade_data["drawdown_from_hwm_pct"] = round(drawdown, 4)
                elif metrics.lwm_price > 0 and position.side == "SHORT":
                    drawdown = (exit_price - metrics.lwm_price) / metrics.lwm_price * 100
                    trade_data["drawdown_from_hwm_pct"] = round(drawdown, 4)

        self._audit_logger.log_event(
            event_type=AuditEventType.TRADE_CLOSED,
            operation="execute_exit",
            symbol=signal.symbol,
            data=trade_data,
            response={...},
        )
        # --- 신규 끝 ---
```

### 3.3 의존성 주입 (Wiring)

**파일**: TradeCoordinator를 생성하는 곳 (TradingEngine 또는 EventDispatcher)

ICTExitDeterminer 인스턴스의 `get_and_clear_metrics` 메서드를 TradeCoordinator에 주입:

```python
# EventDispatcher 또는 TradingEngine에서 TradeCoordinator 생성 시:
trade_coordinator = TradeCoordinator(
    # ... 기존 파라미터 ...
    get_position_metrics=exit_determiner.get_and_clear_metrics,
)
```

**대안 검토 후 기각**:
- ~~Signal.metadata에 metrics 첨부~~ → Signal은 frozen dataclass, metadata 필드 없음
- ~~EventBus로 전달~~ → 불필요한 복잡도, 직접 참조가 더 명확

## 4. 로그 출력 예시

### 4.1 TRAILING_STOP_RATCHETED 이벤트

```json
{
  "timestamp": "2026-03-03T12:30:45.123456",
  "event_type": "trailing_stop_ratcheted",
  "operation": "trailing_stop_ratchet",
  "symbol": "BTCUSDT",
  "data": {
    "side": "LONG",
    "old_stop": 94000.0,
    "new_stop": 94500.0,
    "trigger_price": 96500.0,
    "ratchet_delta_pct": 0.5319,
    "current_mfe_pct": 3.2,
    "current_mae_pct": -0.5,
    "ratchet_count": 3,
    "candle_count_since_entry": 15
  }
}
```

### 4.2 POSITION_CLOSED (MFE/MAE 포함)

```json
{
  "timestamp": "2026-03-03T14:00:00.000000",
  "event_type": "position_closed",
  "operation": "tp_sl_order_filled",
  "symbol": "BTCUSDT",
  "data": {
    "close_reason": "TRAILING_STOP",
    "exit_price": 95000.0,
    "entry_price": 93000.0,
    "position_side": "LONG",
    "gross_pnl": 2.0,
    "net_pnl": 1.82,
    "total_commission": 0.12,
    "total_funding": 0.06,
    "held_duration_seconds": 5400.0,
    "mfe_pct": 3.76,
    "mae_pct": -0.54,
    "hwm_price": 96500.0,
    "lwm_price": 92500.0,
    "drawdown_from_hwm_pct": 1.5544,
    "trailing_ratchet_count": 4,
    "trailing_final_stop": 94500.0,
    "candle_count": 18,
    "balance_after": 1051.82
  }
}
```

### 4.3 TRADE_CLOSED (전략 기반 청산, MFE/MAE 포함)

```json
{
  "timestamp": "2026-03-03T14:00:00.000000",
  "event_type": "trade_closed",
  "operation": "execute_exit",
  "symbol": "BTCUSDT",
  "data": {
    "exit_price": 95000.0,
    "realized_pnl": 2.0,
    "exit_reason": "trailing_stop",
    "duration_seconds": 5400.0,
    "entry_price": 93000.0,
    "quantity": 0.001,
    "position_side": "LONG",
    "leverage": 10,
    "signal_type": "CLOSE_LONG",
    "mfe_pct": 3.76,
    "mae_pct": -0.54,
    "hwm_price": 96500.0,
    "lwm_price": 92500.0,
    "drawdown_from_hwm_pct": 1.5544,
    "trailing_ratchet_count": 4,
    "trailing_final_stop": 94500.0,
    "candle_count": 18
  }
}
```

## 5. 변경 파일 요약

| # | 파일 | 변경 내용 | 영향도 |
|---|------|----------|--------|
| 1 | `src/models/position.py` | `PositionMetrics` dataclass 추가 | Low (신규 추가) |
| 2 | `src/core/audit_logger.py` | `TRAILING_STOP_RATCHETED` enum 추가 | Low (1줄) |
| 3 | `src/strategies/ict/exit.py` | `_position_metrics` dict, MFE/MAE 갱신, 래칫 이벤트 로깅, `get_and_clear_metrics()` | Medium (핵심 변경) |
| 4 | `src/execution/trade_coordinator.py` | `get_position_metrics` 주입, `log_position_closure`/`execute_exit_signal`에 metrics 필드 추가 | Medium |
| 5 | TradeCoordinator 생성 위치 | `get_position_metrics` callable 주입 와이어링 | Low (1줄) |
| 6 | `tests/unit/test_position_metrics.py` | 단위 테스트 (신규) | - |

## 6. 테스트 설계

### 6.1 단위 테스트 케이스

| # | 테스트 | 검증 항목 |
|---|--------|----------|
| 1 | `test_mfe_mae_updated_on_each_candle` | LONG/SHORT 각각 MFE/MAE가 매 캔들마다 올바르게 갱신되는지 |
| 2 | `test_hwm_lwm_price_recorded` | MFE 달성 시 hwm_price, MAE 달성 시 lwm_price 기록 |
| 3 | `test_ratchet_event_logged` | 래칫 발생 시 `TRAILING_STOP_RATCHETED` 이벤트 발행 확인 |
| 4 | `test_ratchet_count_incremented` | 래칫 횟수 정확히 증가 |
| 5 | `test_metrics_included_in_position_closed` | `log_position_closure`에 MFE/MAE 필드 포함 |
| 6 | `test_metrics_included_in_trade_closed` | `execute_exit_signal`에 MFE/MAE 필드 포함 |
| 7 | `test_drawdown_from_hwm_calculation` | LONG: (hwm - exit) / hwm * 100, SHORT: (exit - lwm) / lwm * 100 |
| 8 | `test_metrics_cleared_on_position_close` | `get_and_clear_metrics()` 호출 후 dict에서 제거 확인 |
| 9 | `test_metrics_initialized_on_first_candle` | 첫 캔들에서 metrics 생성, entry_price/side 설정 |
| 10 | `test_no_metrics_when_callback_none` | `get_position_metrics=None`일 때 기존 동작 그대로 (회귀 없음) |

### 6.2 테스트 전략

```python
# 공통 fixture
@pytest.fixture
def exit_determiner():
    return ICTExitDeterminer(exit_config=ExitConfig(
        trailing_distance=0.02,
        trailing_activation=0.01,
    ))

@pytest.fixture
def long_position():
    return Position(symbol="BTCUSDT", side="LONG",
                    entry_price=100.0, quantity=1.0, leverage=10)

# MFE/MAE 시나리오: 100 → 103 → 99 → 101 → exit at 99.5
# Expected: mfe_pct=3.0%, mae_pct=-1.0%, hwm=103, lwm=99, drawdown=3.39%
```

## 7. 성능 영향 분석

| 변경 | Hot Path | 비용 | 빈도 |
|------|----------|------|------|
| PositionMetrics dict.get() | Yes | ~50ns | 매 캔들 |
| MFE/MAE float 비교 2회 | Yes | ~20ns | 매 캔들 |
| 조건부 float 대입 | Yes | ~10ns | MFE/MAE 갱신 시만 |
| candle_count += 1 | Yes | ~5ns | 매 캔들 |
| ratchet_count += 1 | Yes | ~5ns | 래칫 시만 |
| TRAILING_STOP_RATCHETED audit | No (QueueHandler) | ~1μs enqueue | 래칫 시만 |
| POSITION_CLOSED 추가 필드 | No (청산 시) | 무시 가능 | 1회/포지션 |

**총 Hot Path 추가**: **< 100ns/캔들** (기존 < 1ms p99 기준 대비 0.01%)

## 8. 후방 호환성

| 항목 | 호환성 | 설명 |
|------|--------|------|
| 기존 JSONL 파서 | 호환 | 새 필드 추가만, 기존 필드 변경 없음 |
| ExitContext | 변경 없음 | frozen dataclass 수정 불필요 |
| ExitDeterminer ABC | 변경 없음 | `get_and_clear_metrics`는 ICTExitDeterminer에만 추가 |
| TradeCoordinator API | 호환 | `get_position_metrics`는 Optional, 기본값 None |
| 기존 테스트 | 영향 없음 | 새 파라미터 Optional이므로 기존 코드 수정 불필요 |
