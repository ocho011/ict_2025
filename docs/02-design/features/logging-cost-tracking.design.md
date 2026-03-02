# Logging Cost Tracking - Design Document

> **Feature**: logging-cost-tracking
> **Status**: Draft
> **Author**: Claude Code (PDCA Design)
> **Created**: 2026-03-02
> **PDCA Phase**: Design
> **Plan Reference**: `docs/01-plan/features/logging-cost-tracking.plan.md`

---

## 1. Design Overview

### 1.1 목표

AuditLogger JSONL 기록에 **커미션·펀딩비·슬리피지·잔고·position_id·거래소 타임스탬프**를 추가하여, 단일 `jq` 쿼리로 **Net PnL = Gross PnL − Commission − Funding** 분석이 가능한 로깅 파이프라인을 구축한다.

### 1.2 설계 원칙

1. **Audit-only**: 모든 변경은 감사 로그 기록에만 영향. 거래 로직(주문 실행, 리스크 관리) 변경 없음
2. **Hot Path 무영향**: QueueHandler 비동기 I/O 유지, 추가 필드는 메모리 연산만
3. **하위 호환**: 기존 필드(`realized_pnl`)는 유지하되 `gross_pnl`로 명칭 추가, 새 필드는 모두 default 값
4. **기존 모델 재활용**: `AccountUpdate`, `BalanceUpdate`, `OrderUpdate`의 기존 파서 최대 활용

### 1.3 사용자 결정사항

| # | 결정 | 설계 반영 |
|---|------|-----------|
| 1 | Binance USDT-M | USDT 결제 기준 PnL, 펀딩비 8h 주기 |
| 2 | 중저빈도 + 복합 | Hot path 빈도 낮음 → 필드 추가 성능 영향 무시 가능 |
| 3 | 분석 목표: 전부 | Net PnL, 전략 비교, 리스크 메트릭 모두 지원 |

---

## 2. 데이터 모델 변경

### 2.1 Order dataclass 확장

**파일**: `src/models/order.py`

```python
@dataclass
class Order:
    # ... 기존 필드 (변경 없음) ...
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    callback_rate: Optional[float] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: Optional[float] = None
    timestamp: Optional[datetime] = None

    # ── Phase 1: Commission fields (G1) ──
    commission: float = 0.0
    commission_asset: Optional[str] = None

    # ── Phase 3: Exchange timestamps (G6) ──
    event_time: Optional[int] = None        # ms epoch from Binance
    transaction_time: Optional[int] = None   # ms epoch from Binance
```

**설계 근거:**
- `Order`는 `frozen=True`가 아님 (일반 `@dataclass`) → 필드 추가 자유
- 기존 `__post_init__` 검증 로직에 영향 없음 (신규 필드는 검증 대상 아님)
- 모든 신규 필드에 default 값 → 기존 `Order(...)` 호출 100% 호환

### 2.2 PositionEntryData 확장

**파일**: `src/models/position.py`

```python
from uuid import uuid4

@dataclass
class PositionEntryData:
    entry_price: float
    entry_time: datetime
    quantity: float
    side: str  # "LONG" or "SHORT"

    # ── Phase 3: Position lifecycle tracking (G5) ──
    position_id: str = field(default_factory=lambda: str(uuid4()))

    # ── Phase 1: Commission accumulator (G1) ──
    total_commission: float = 0.0

    # ── Phase 2: Funding fee accumulator (G2) ──
    total_funding: float = 0.0

    # ── Phase 4: Slippage tracking (G3) ──
    intended_entry_price: Optional[float] = None  # signal.entry_price
```

**설계 근거:**
- `PositionEntryData`도 일반 `@dataclass` → 필드 추가 안전
- `position_id`는 생성 시점에 자동 발급 (uuid4, ~1μs)
- `total_commission`/`total_funding`은 포지션 수명 동안 누적, 종료 시 audit log에 기록
- `intended_entry_price`는 시그널 발생 시 기록, 실제 체결가와 비교하여 슬리피지 산출

### 2.3 AuditEventType enum 추가

**파일**: `src/core/audit_logger.py`

```python
class AuditEventType(Enum):
    # ... 기존 enum 값 (변경 없음) ...

    # ── Phase 2: Funding fee event (G2) ──
    FUNDING_FEE_RECEIVED = "funding_fee_received"

    # ── Phase 4: Balance snapshot (G4) ──
    BALANCE_SNAPSHOT = "balance_snapshot"
```

**설계 근거:**
- 기존 `BALANCE_QUERY`는 REST API 조회 이벤트 (query vs snapshot 구분)
- `FUNDING_FEE_RECEIVED`는 WebSocket 이벤트 수신 기록용

---

## 3. 상세 설계

### 3.1 Phase 1: 커미션 파이프라인 복원 (G1)

#### 3.1.1 TradingEngine._on_order_fill_from_websocket() 변경

**파일**: `src/core/trading_engine.py` (line ~670)

**현재 코드:**
```python
order = Order(
    order_id=order_id,
    symbol=symbol,
    side=OrderSide(order_data.get("S")),
    order_type=OrderType(order_type),
    quantity=float(order_data.get("q", 0)),
    price=float(order_data.get("ap", 0)),
    stop_price=float(order_data.get("sp", 0)) if order_data.get("sp") else None,
    callback_rate=callback_rate,
    status=OrderStatus.FILLED if is_filled else OrderStatus.PARTIALLY_FILLED,
    filled_quantity=float(order_data.get("z", 0)),
)
```

**변경 후:**
```python
order = Order(
    order_id=order_id,
    symbol=symbol,
    side=OrderSide(order_data.get("S")),
    order_type=OrderType(order_type),
    quantity=float(order_data.get("q", 0)),
    price=float(order_data.get("ap", 0)),
    stop_price=float(order_data.get("sp", 0)) if order_data.get("sp") else None,
    callback_rate=callback_rate,
    status=OrderStatus.FILLED if is_filled else OrderStatus.PARTIALLY_FILLED,
    filled_quantity=float(order_data.get("z", 0)),
    # Phase 1: Commission pipeline restoration (G1)
    commission=float(order_data.get("n", 0)) if order_data.get("n") else 0.0,
    commission_asset=order_data.get("N"),
    # Phase 3: Exchange timestamps (G6)
    event_time=int(order_data.get("E")) if order_data.get("E") else None,
    transaction_time=int(order_data.get("T")) if order_data.get("T") else None,
)
```

**변경 범위**: Order 생성자 인자 4개 추가. 기존 로직 변경 없음.

#### 3.1.2 TradeCoordinator.on_order_filled() — 커미션 누적

**파일**: `src/execution/trade_coordinator.py` (line ~527)

엔트리 주문 체결 시 `PositionEntryData` 생성 직후 커미션 누적:

```python
# 기존: PositionEntryData 생성
self._position_entry_data[order.symbol] = PositionEntryData(
    entry_price=order.price,
    entry_time=datetime.now(timezone.utc),
    quantity=order.quantity,
    side=position_side,
    intended_entry_price=signal_entry_price,  # Phase 4 추가
)
# Phase 1: 엔트리 커미션 누적
self._position_entry_data[order.symbol].total_commission += order.commission
```

TP/SL 주문 체결 시 (exit) 커미션 추가 누적:

```python
# line ~576 부근, log_position_closure 호출 전
entry_data = self._position_entry_data.get(order.symbol)
if entry_data:
    entry_data.total_commission += order.commission
```

#### 3.1.3 TradeCoordinator.log_position_closure() — 커미션 기록

**파일**: `src/execution/trade_coordinator.py` (line ~612)

```python
if entry_data:
    closure_data["entry_price"] = entry_data.entry_price
    closure_data["position_side"] = entry_data.side
    closure_data["position_id"] = entry_data.position_id          # Phase 3
    closure_data["held_duration_seconds"] = held_duration.total_seconds()

    # Gross PnL (기존 로직, 명칭만 추가)
    if entry_data.side == "LONG":
        gross_pnl = (order.price - entry_data.entry_price) * order.quantity
    else:
        gross_pnl = (entry_data.entry_price - order.price) * order.quantity

    closure_data["realized_pnl"] = gross_pnl      # 하위 호환 유지
    closure_data["gross_pnl"] = gross_pnl          # 명시적 명칭
    closure_data["total_commission"] = entry_data.total_commission   # Phase 1
    closure_data["total_funding"] = entry_data.total_funding         # Phase 2
    closure_data["net_pnl"] = gross_pnl - entry_data.total_commission - entry_data.total_funding  # Phase 5
```

### 3.2 Phase 2: 펀딩비 파이프라인 (G2)

#### 3.2.1 PrivateUserStreamer._handle_account_update() 확장

**파일**: `src/core/private_user_streamer.py` (line ~306)

**현재**: Position 배열(P)만 파싱, Balance 배열(B)과 update_reason 무시.

**변경**: FUNDING_FEE reason 분기 추가 + 펀딩비 콜백 도입.

```python
def _handle_account_update(self, data: dict) -> None:
    account_data = data.get("a", {})
    update_reason = account_data.get("m", "unknown")
    positions_data = account_data.get("P", [])

    # ── Phase 2: Funding fee handling (G2) ──
    if update_reason == "FUNDING_FEE":
        self._handle_funding_fee(data)

    # ... 기존 position 파싱 로직 (변경 없음) ...
```

#### 3.2.2 신규 메서드: _handle_funding_fee()

**파일**: `src/core/private_user_streamer.py`

```python
def _handle_funding_fee(self, data: dict) -> None:
    """Process FUNDING_FEE event from ACCOUNT_UPDATE."""
    from src.models.account import AccountUpdate

    account_update = AccountUpdate.from_websocket_data(data)

    # Find USDT balance change (funding fee amount)
    usdt_balance = account_update.get_balance("USDT")
    if usdt_balance is None:
        self.logger.warning("FUNDING_FEE event without USDT balance change")
        return

    funding_fee = usdt_balance.balance_change  # + = received, - = paid

    self.logger.info(
        f"Funding fee received: {funding_fee:.4f} USDT "
        f"(wallet: {usdt_balance.wallet_balance:.4f})"
    )

    # Invoke funding fee callback if configured
    if self._funding_fee_callback:
        try:
            self._funding_fee_callback(funding_fee, usdt_balance.wallet_balance)
        except Exception as e:
            self.logger.error(f"Funding fee callback failed: {e}", exc_info=True)
```

#### 3.2.3 PrivateUserStreamer — 콜백 추가

```python
# __init__에 추가:
self._funding_fee_callback: Optional[Callable[[float, float], None]] = None

# 새 setter 메서드:
def set_funding_fee_callback(
    self, callback: Callable[[float, float], None]
) -> None:
    """Set callback for funding fee events.

    Args:
        callback: Function(funding_fee, wallet_balance)
    """
    self._funding_fee_callback = callback
```

#### 3.2.4 TradingEngine — 펀딩비 콜백 등록 + audit log

**파일**: `src/core/trading_engine.py`

```python
# start() 또는 _register_callbacks() 내:
self.private_user_streamer.set_funding_fee_callback(
    self._on_funding_fee_received
)

def _on_funding_fee_received(self, funding_fee: float, wallet_balance: float) -> None:
    """Handle funding fee event from WebSocket."""
    from src.core.audit_logger import AuditEventType

    # 1. Audit log
    self.audit_logger.log_event(
        event_type=AuditEventType.FUNDING_FEE_RECEIVED,
        operation="funding_fee",
        additional_data={
            "funding_fee": funding_fee,
            "wallet_balance": wallet_balance,
        },
    )

    # 2. Accumulate to open positions (pro-rata by symbol not possible
    #    from funding event alone — accumulate to all open positions)
    if self.trade_coordinator:
        self.trade_coordinator.accumulate_funding_fee(funding_fee)
```

#### 3.2.5 TradeCoordinator.accumulate_funding_fee()

**파일**: `src/execution/trade_coordinator.py`

```python
def accumulate_funding_fee(self, funding_fee: float) -> None:
    """Accumulate funding fee to all open position entry data.

    Binance FUNDING_FEE event does not specify which symbol the fee
    is for (it's a per-position fee applied to all open positions).
    We distribute proportionally by notional value.

    For single-position systems (common case), this is exact.

    Args:
        funding_fee: Total funding fee amount (+ = received, - = paid)
    """
    open_positions = {
        sym: data for sym, data in self._position_entry_data.items()
    }

    if not open_positions:
        self.logger.debug(
            f"Funding fee {funding_fee:.4f} received but no open positions"
        )
        return

    # Single position: assign directly (most common case)
    if len(open_positions) == 1:
        sym, data = next(iter(open_positions.items()))
        data.total_funding += abs(funding_fee)  # Store as cost (always positive)
        self.logger.info(
            f"Funding fee accumulated: {sym} += {abs(funding_fee):.4f}"
        )
        return

    # Multiple positions: distribute by notional value
    total_notional = sum(
        d.entry_price * d.quantity for d in open_positions.values()
    )
    if total_notional == 0:
        return

    for sym, data in open_positions.items():
        notional = data.entry_price * data.quantity
        share = abs(funding_fee) * (notional / total_notional)
        data.total_funding += share

    self.logger.info(
        f"Funding fee {abs(funding_fee):.4f} distributed to "
        f"{len(open_positions)} positions"
    )
```

**설계 결정: `abs(funding_fee)`**
- 펀딩비는 **비용**으로 취급 (항상 양수로 저장)
- Net PnL 계산 시 `gross_pnl - total_commission - total_funding`
- 펀딩비 수령(+) 시: `abs(+) = +` → Net PnL이 낮아짐 (보수적)
- 펀딩비 지불(−) 시: `abs(−) = +` → Net PnL이 낮아짐 (정확)
- **대안**: 부호 보존하여 `gross_pnl - commission + funding_fee` → 더 정확하지만 분석 쿼리 복잡
- **결정**: 부호 보존 방식 채택 — `total_funding`에 원본 부호 유지, Net PnL = `gross_pnl - commission - total_funding` (음수 funding = 비용 증가, 양수 funding = 비용 감소)

**최종 수정:**
```python
# 부호 보존: funding_fee 원본 그대로 누적
data.total_funding += funding_fee  # + = received, - = paid
# Net PnL = gross_pnl - commission - total_funding
# funding_fee가 -0.5이면: net = gross - comm - (-0.5) = gross - comm + 0.5 ← 비용 반영
# funding_fee가 +0.3이면: net = gross - comm - (+0.3) = gross - comm - 0.3 ← 수령분 차감 (보수적)
```

**재검토**: 위 부호가 직관적이지 않음. Binance에서 `balance_change > 0`이면 수령, `< 0`이면 지불.

**최종 설계:**
```python
# total_funding: 누적 펀딩비 비용 (양수 = 비용, 음수 = 수익)
data.total_funding -= funding_fee
# funding_fee = +0.3 (수령) → total_funding -= 0.3 → -0.3 (수익)
# funding_fee = -0.5 (지불) → total_funding -= (-0.5) → +0.5 (비용)
# Net PnL = gross_pnl - commission - total_funding
# 수령 시: net = gross - comm - (-0.3) = gross - comm + 0.3 ← 수익 반영 ✓
# 지불 시: net = gross - comm - (+0.5) = gross - comm - 0.5 ← 비용 반영 ✓
```

### 3.3 Phase 3: position_id + 거래소 타임스탬프 (G5, G6)

#### 3.3.1 PositionEntryData.position_id

Section 2.2에서 정의. 생성 시 `uuid4()` 자동 발급.

모든 audit log 이벤트에 `position_id` 포함:
- `SIGNAL_PROCESSING` (entry signal) → `position_id` 기록 시작
- `ORDER_PLACED` → `position_id` 포함
- `POSITION_CLOSED` → `position_id` 포함하여 라이프사이클 완결

#### 3.3.2 Order.event_time / transaction_time

Section 2.1에서 정의. `_on_order_fill_from_websocket()`에서 전달.

`log_position_closure()`에서 audit log에 포함:
```python
if order.event_time:
    closure_data["exchange_event_time"] = order.event_time
if order.transaction_time:
    closure_data["exchange_transaction_time"] = order.transaction_time
```

### 3.4 Phase 4: 슬리피지 추적 + 잔고 스냅샷 (G3, G4)

#### 3.4.1 슬리피지 계산

**TradeCoordinator.on_order_filled()** — 엔트리 주문 체결 시:

```python
# PositionEntryData 생성 시 signal의 의도 가격 저장
# signal은 on_signal_generated()에서 전달된 원본
self._position_entry_data[order.symbol] = PositionEntryData(
    entry_price=order.price,
    entry_time=datetime.now(timezone.utc),
    quantity=order.quantity,
    side=position_side,
    intended_entry_price=signal.entry_price,  # 시그널의 의도 가격
)
```

**log_position_closure()** — 포지션 종료 시:

```python
# 엔트리 슬리피지 (bps)
if entry_data.intended_entry_price and entry_data.intended_entry_price > 0:
    slippage_entry_bps = (
        (entry_data.entry_price - entry_data.intended_entry_price)
        / entry_data.intended_entry_price * 10000
    )
    closure_data["slippage_entry_bps"] = round(slippage_entry_bps, 2)

# Exit 슬리피지는 TP/SL 가격 vs 실제 체결가로 계산
if order.stop_price and order.stop_price > 0:
    slippage_exit_bps = (
        (order.price - order.stop_price)
        / order.stop_price * 10000
    )
    closure_data["slippage_exit_bps"] = round(slippage_exit_bps, 2)
```

#### 3.4.2 잔고 스냅샷 (balance_after)

**PrivateUserStreamer._handle_account_update()** — 모든 ACCOUNT_UPDATE에서 B 배열 파싱:

```python
# Phase 4: Balance 파싱 (모든 update_reason에서)
balances_data = account_data.get("B", [])
if balances_data and self._balance_update_callback:
    from src.models.account import BalanceUpdate
    for bal in balances_data:
        try:
            balance = BalanceUpdate.from_websocket_data(bal)
            if balance.asset == "USDT":
                self._balance_update_callback(balance.wallet_balance)
                break
        except (ValueError, TypeError):
            continue
```

**TradingEngine**: 최신 잔고를 메모리에 캐시.

```python
self._latest_wallet_balance: Optional[float] = None

def _on_balance_update(self, wallet_balance: float) -> None:
    self._latest_wallet_balance = wallet_balance
```

**TradeCoordinator.log_position_closure()**: 종료 시 잔고 기록.

```python
# balance_after는 TradingEngine에서 주입
if self._get_wallet_balance:
    balance = self._get_wallet_balance()
    if balance is not None:
        closure_data["balance_after"] = balance
```

### 3.5 Phase 5: Net PnL 계산 (핵심)

Section 3.1.3에서 이미 통합. `log_position_closure()`의 최종 출력:

```json
{
  "timestamp": "2026-03-02T12:00:00.123456",
  "event_type": "position_closed",
  "operation": "tp_sl_order_filled",
  "symbol": "BTCUSDT",
  "data": {
    "position_id": "a1b2c3d4-...",
    "position_side": "LONG",
    "entry_price": 85000.0,
    "exit_price": 86500.0,
    "exit_quantity": 0.01,
    "close_reason": "TAKE_PROFIT",
    "held_duration_seconds": 3600.0,
    "realized_pnl": 15.0,
    "gross_pnl": 15.0,
    "total_commission": 0.0692,
    "total_funding": -0.12,
    "net_pnl": 15.0508,
    "slippage_entry_bps": 1.2,
    "slippage_exit_bps": -0.5,
    "balance_after": 10015.05,
    "exchange_event_time": 1740916800123,
    "exchange_transaction_time": 1740916800100,
    "order_id": "12345",
    "order_type": "TAKE_PROFIT_MARKET",
    "exit_side": "SELL"
  }
}
```

### 3.6 Phase 6: 코드 위생 정리 (G7~G9)

#### 3.6.1 StrategyHotReloader 버그 수정 (G9)

**파일**: `src/core/strategy_hot_reloader.py` (line ~117)

```python
# Before (bug):
self._audit_logger.log_event(
    event_type="STRATEGY_HOT_RELOAD",  # ← raw string!
    ...
)

# After (fix): AuditEventType에 해당 enum이 없으므로 가장 가까운 것 사용
# 또는 새 enum 추가
```

**결정**: `STRATEGY_HOT_RELOAD`에 해당하는 enum이 없으므로 기존 가장 가까운 enum 사용 또는 신규 추가. 구현 시 확인.

#### 3.6.2 data vs additional_data 통일 (G8)

**규칙**:
- `additional_data`: 보조/메타 정보 (strategy name, confidence 등)
- `data`: 핵심 비즈니스 데이터 (PnL, prices, quantities)
- 기존 호출은 점진적으로 통일 (이번 스코프에서는 신규 호출만 규칙 준수)

#### 3.6.3 미사용 AuditEventType 정리 (G7)

구현 시점에 실제 사용 여부 grep으로 확인 후 판단. 미사용 확인 시 주석 추가 (삭제는 하위 호환 리스크).

---

## 4. 인터페이스 변경 요약

### 4.1 신규 콜백 (PrivateUserStreamer)

| 콜백 | 시그니처 | 설정 메서드 |
|------|----------|-------------|
| funding_fee | `(funding_fee: float, wallet_balance: float) -> None` | `set_funding_fee_callback()` |
| balance_update | `(wallet_balance: float) -> None` | `set_balance_update_callback()` |

### 4.2 신규 메서드 (TradeCoordinator)

| 메서드 | 용도 |
|--------|------|
| `accumulate_funding_fee(funding_fee: float)` | 펀딩비를 열린 포지션에 배분 |

### 4.3 ABC 변경 — 없음

기존 `ExecutionGateway`, `ExchangeProvider`, `PositionProvider` ABC 변경 없음.

---

## 5. 데이터 흐름도

### 5.1 커미션 흐름 (G1)

```
WebSocket ORDER_TRADE_UPDATE
  │ "n": "0.0346"  (commission)
  │ "N": "USDT"    (commission_asset)
  ▼
TradingEngine._on_order_fill_from_websocket()
  │ Order(commission=0.0346, commission_asset="USDT")
  ▼
TradeCoordinator.on_order_filled()
  │ entry_data.total_commission += order.commission
  ▼
TradeCoordinator.log_position_closure()
  │ closure_data["total_commission"] = entry_data.total_commission
  ▼
AuditLogger → audit_YYYYMMDD.jsonl
```

### 5.2 펀딩비 흐름 (G2)

```
WebSocket ACCOUNT_UPDATE (m="FUNDING_FEE")
  │ "B": [{"a":"USDT", "bc":"-0.12"}]
  ▼
PrivateUserStreamer._handle_funding_fee()
  │ funding_fee = -0.12
  ▼
TradingEngine._on_funding_fee_received()
  │ ① AuditLogger.log_event(FUNDING_FEE_RECEIVED)
  │ ② TradeCoordinator.accumulate_funding_fee(-0.12)
  ▼
TradeCoordinator: entry_data.total_funding -= (-0.12) → +0.12
  ▼
(포지션 종료 시)
log_position_closure()
  │ net_pnl = gross_pnl - commission - 0.12
  ▼
AuditLogger → audit_YYYYMMDD.jsonl
```

### 5.3 잔고 흐름 (G4)

```
WebSocket ACCOUNT_UPDATE (모든 reason)
  │ "B": [{"a":"USDT", "wb":"10015.05"}]
  ▼
PrivateUserStreamer → balance_update_callback
  ▼
TradingEngine._latest_wallet_balance = 10015.05
  ▼
(포지션 종료 시)
log_position_closure()
  │ closure_data["balance_after"] = 10015.05
  ▼
AuditLogger → audit_YYYYMMDD.jsonl
```

---

## 6. 테스트 전략

### 6.1 단위 테스트

| 테스트 | 파일 | 검증 내용 |
|--------|------|-----------|
| Order commission 필드 | `tests/models/test_order.py` | 기존 Order 생성 호환성 + commission 전달 |
| PositionEntryData.position_id | `tests/models/test_position.py` | UUID 자동 생성, 고유성 |
| Commission 누적 | `tests/execution/test_trade_coordinator.py` | entry + exit commission 합산 |
| Funding fee 누적 | `tests/execution/test_trade_coordinator.py` | single/multi position 배분 |
| Net PnL 계산 | `tests/execution/test_trade_coordinator.py` | `net = gross - comm - funding` 등식 |
| Slippage 계산 | `tests/execution/test_trade_coordinator.py` | bps 계산 정확도 |
| FUNDING_FEE 파싱 | `tests/core/test_private_user_streamer.py` | ACCOUNT_UPDATE reason="FUNDING_FEE" |
| AuditEventType 사용 | `tests/core/test_audit_logger.py` | 모든 호출이 enum 사용 |

### 6.2 통합 테스트

| 테스트 | 검증 내용 |
|--------|-----------|
| Full lifecycle | Signal → Entry → Funding → TP/SL → POSITION_CLOSED with all fields |
| JSONL 분석 | `jq` 쿼리로 Net PnL 합산 가능 |

### 6.3 jq 검증 쿼리 (성공 기준)

```bash
# 전략별 Net PnL 합산
jq -s '[.[] | select(.event_type == "position_closed") | {strategy: .data.strategy_name, net: .data.net_pnl}] | group_by(.strategy) | map({strategy: .[0].strategy, total_net_pnl: (map(.net) | add)})' audit_*.jsonl

# 총 커미션
jq -s '[.[] | select(.event_type == "position_closed") | .data.total_commission] | add' audit_*.jsonl

# 총 펀딩비
jq -s '[.[] | select(.event_type == "funding_fee_received") | .additional_data.funding_fee] | add' audit_*.jsonl
```

---

## 7. 영향받는 파일 요약

| 파일 | 변경 유형 | Phase |
|------|-----------|-------|
| `src/models/order.py` | 필드 4개 추가 | 1, 3 |
| `src/models/position.py` | 필드 4개 추가 (PositionEntryData) | 1, 2, 3, 4 |
| `src/core/audit_logger.py` | enum 2개 추가 | 2, 4 |
| `src/core/trading_engine.py` | Order 생성 인자 추가, 콜백 등록 2개, 핸들러 2개 | 1, 2, 3, 4 |
| `src/core/private_user_streamer.py` | _handle_funding_fee() 신규, 콜백 2개 추가 | 2, 4 |
| `src/execution/trade_coordinator.py` | log_position_closure 확장, accumulate_funding_fee 신규 | 1, 2, 3, 4, 5 |
| `src/core/strategy_hot_reloader.py` | raw string → enum 수정 | 6 |
| `tests/` (신규/수정) | 각 Phase별 단위 테스트 | 1~6 |

---

## 8. 구현 전 확인사항

- [x] `Order`는 `@dataclass` (not frozen) → 필드 추가 안전
- [x] `PositionEntryData`는 `@dataclass` (not frozen) → 필드 추가 안전
- [x] `AccountUpdate.from_websocket_data()` 이미 B 배열 파싱 → 재활용 가능
- [x] `BalanceUpdate.from_websocket_data()` 이미 구현됨 → 재활용 가능
- [x] `AuditEventType`에 `FUNDING_FEE_RECEIVED` 없음 → 신규 추가 필요
- [x] `AuditEventType`에 `BALANCE_SNAPSHOT` 없음 → 신규 추가 필요 (BALANCE_QUERY와 별도)
- [x] `PrivateUserStreamer`의 콜백 패턴 기존과 동일 (set_xxx_callback)
