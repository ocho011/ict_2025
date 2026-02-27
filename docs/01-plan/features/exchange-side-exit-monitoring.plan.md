# Plan: Exchange-side Exit Monitoring Optimization

- **Status:** Planning
- **Date:** 2026-02-25
- **Author:** Gemini CLI Agent

## 1. 문제 정의 (Objective)

현재 봇은 캔들 마감 시점에만 익절/손절(Exit) 조건을 평가하고 거래소에 주문을 보냅니다. 이는 다음과 같은 문제를 야기합니다:
- **실행 지연:** 캔들 진행 중에 손절가나 익절가에 도달하더라도 마감 전까지는 봇이 대응하지 않음.
- **슬리피지:** 캔들 마감 직후의 급격한 변동성으로 인해 실제 체결가가 유리하지 않게 형성될 가능성이 큼.
- **감시 부재:** 봇이 오프라인일 때나 캔들 중간의 가격 변동에 대한 보호 장치가 부족함.

## 2. 해결 방안 (Proposed Solution)

사용자의 요구사항(All Strategies, Exchange Native Trailing, Real-time Aggressive)을 반영하여, 거래소의 실시간 감시 기능을 최대한 활용하도록 개선합니다.

### 2.1 Trailing Stop (바이낸스 네이티브 활용)
- 봇의 계산 대신 바이낸스의 `TRAILING_STOP_MARKET` 주문 타입을 사용하여 거래소 엔진이 직접 수익 추적 및 손절을 수행하게 함.
- 이를 통해 봇의 로직 지연 없이 즉각적인 익절 보호 가능.

### 2.2 Breakeven & Numeric Exit (실시간 업데이트)
- `CANDLE_UPDATE` 이벤트를 수신하여 캔들 마감 전이라도 가격이 유리한 방향으로 움직이면 거래소의 Stop Loss/Take Profit 주문 가격을 즉시 갱신(Move)함.
- 가격이 진입가 대비 설정된 오프셋 이상 수익권에 도달하면 즉시 거래소 SL을 진입가로 이동.

### 2.3 Indicator & Timed Exit (보조 감시)
- 지표 기반이나 시간 기반 탈출은 봇의 계산이 필수적이나, 이 경우에도 거래소에 '안전 장치'로서 넓은 TP/SL 주문을 상시 유지함.

## 3. 상세 작업 내역 (Tasks)

- [ ] **Task 1: OrderGateway 확장** - `TRAILING_STOP_MARKET` 주문 생성을 위한 API 파라미터(callbackRate) 및 메서드 추가.
- [ ] **Task 2: ExitDeterminer 수정** - `ICTExitDeterminer`가 캔들 마감 전(`is_closed=False`) 상태에서도 현재가(Close)를 기반으로 임계치 도달 여부를 판단하도록 개선.
- [ ] **Task 3: EventDispatcher 최적화** - `on_candle_received`에서 `CANDLE_UPDATE` 이벤트 발생 시에도 `process_exit_strategy`를 실행하도록 조건 완화 및 중복 호출 방지 로직 추가.
- [ ] **Task 4: TradeCoordinator 연동** - 포지션 오픈 직후 전략 설정에 따라 적절한 거래소 감시 주문(Native Trailing 또는 SL/TP)을 즉시 생성하도록 로직 수정.

## 4. 검증 계획 (Verification)

- **단위 테스트:** `TRAILING_STOP_MARKET` 주문 생성 로직 검증.
- **로그 분석 (Zero Script QA):** 실시간 캔들 업데이트 중 SL 가격이 거래소에 성공적으로 갱신되는지 로그로 확인.
- **백테스트:** 실시간(Tick-level 또는 Minute-level) 데이터 상황에서 캔들 마감 전 Exit이 발생하는지 확인.

## 5. 기대 효과 (Expected Outcome)

- 슬리피지 최소화 및 익절 확률 향상.
- 봇의 처리 로직과 무관하게 거래소 차원의 실시간 자산 보호 강화.
- 봇 오프라인 시에도 거래소에 걸린 주문을 통한 리스크 관리 가능.
