# Dynamic Take Profit (TP) Update Design

이 문서는 Price Action(PA) 및 ICT(Inner Circle Trader) 개념을 기반으로 TP를 실시간으로 업데이트하는 전략적 접근 방식과 이를 시스템적으로 구현하기 위한 설계를 제안합니다.

## 전략적 배경: 왜 TP를 업데이트하는가?

정적(Static) TP는 진입 시점에 설정된 리스크 대비 보상 비율(RR)에 의존하지만, 시장은 진행되면서 새로운 정보(Liquidity, Imbalance)를 생성합니다.

### 1. ICT 기반 업데이트 기준
- **Liquidity Hunt**: 가격이 진행되면서 새로운 Old High(BSL)나 Old Low(SSL)가 형성되면, TP를 해당 유동성 지점 너머로 이동시킬 수 있습니다.
- **FVG (Fair Value Gap)**: 진행 방향에 새로운 FVG가 형성되면, 해당 구간의 'Consequent Encroachment'(50% 지점)를 1차 TP로 설정하거나, 돌파 시 다음 타겟으로 업데이트합니다.
- **Order Block (OB)**: 새로운 OB가 형성되면 이를 지지/저항의 근거로 삼아 TP를 공격적으로 또는 보수적으로 조정합니다.

### 2. Fibonacci 기반 업데이트 기준
- **Extension Levels**: 가격인 0.618, 1.0(Equal Leg) 레벨을 돌파할 때, 다음 피보나치 확장 레벨(1.618, 2.0 등)로 TP를 상향 조정합니다.

---

## 시스템 구현 설계

### 1. `BaseStrategy` 확장: `on_position_active`
현재 `analyze`는 진입 시그널용입니다. 포지션이 유지 중일 때 PA를 감시하는 로직이 필요합니다.

```python
async def analyze_active_position(self, candle: Candle, position: Position) -> Optional[TPUpdateSignal]:
    # 1. 새로운 FVG나 Liquidity Pool 감지
    # 2. 기존 TP가 너무 가깝거나 멀다면 업데이트 시그널 생성
    if new_target_detected:
        return TPUpdateSignal(new_tp=new_price, reason="New FVG Formed")
```

### 2. `OrderExecutionManager`의 수정 로직
바이낸스 API는 기존 대기 주문을 직접 '수정'하는 대신, **기존 TP 주문 취소 후 신규 가격으로 재발행**하는 방식을 권장합니다.

```python
async def update_take_profit(self, symbol: str, new_tp: float):
    # 1. 기존 TAKE_PROFIT_MARKET 주문 취소 (cancel_all_orders 또는 ID 지정)
    # 2. _place_tp_order() 호출로 신규 주문 생성
```

### 3. `TradingEngine` 라우팅 개편
- `CANDLE_CLOSED` 이벤트 발생 시, 현재 포지션이 있다면 `strategy.analyze_active_position()`을 호출합니다.
- 업데이트 시그널이 나오면 `SIGNAL_GENERATED` 이벤트를 발생시켜 `OrderManager`가 주문을 교체하게 합니다.

---

## 기대 효과 및 리스크
- **기대 효과**: 추세가 강할 때 수익을 극대화(Runners)하고, 역추세 징후가 보일 때 수익을 조기에 확정할 수 있습니다.
- **리스크**: 잦은 주문 취소/생성으로 인한 API 리스크(Rate Limit) 및 슬리피지가 발생할 수 있습니다.
