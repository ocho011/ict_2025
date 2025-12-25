# 아키텍처 리뷰: 캔들 데이터에서 이벤트로의 브릿지 로직 (CANDLE_CLOSED)

**날짜:** 2025-12-21 10:58:48
**주제:** `DataCollector` 수신 데이터와 `EventBus` 간의 연결 로직 검토 및 수정 계획

---

## 1. 문제 분석 (Current Gap)

현재 프로젝트의 `TradingEngine`은 이벤트 핸들러를 등록(`_setup_handlers`)하고 있으나, 실제 `CANDLE_CLOSED` 이벤트를 생산(Produce)하여 `EventBus`에 발행(Publish)하는 로직이 누락되어 있습니다.

### 상세 현상
- **구독(Subscribed)**: `TradingEngine` 초기화 시 `EventType.CANDLE_CLOSED`에 대한 핸들러는 정상적으로 등록됨.
- **데이터 흐름 단절**: `DataCollector`가 웹소켓으로 캔들을 수신하면 `on_candle_callback`을 호출하지만, `TradingEngine`이 이 콜백을 통해 이벤트를 발행하는 브릿지 로직이 없음.
- **테스트 격차**: 기존 단위 테스트(`test_trading_engine.py`)에서는 이벤트를 수동으로 발행하여 테스트했기 때문에 실제 런타임에서의 누락이 발견되지 않음.

---

## 2. 해결 방안 (Implementation Plan)

`TradingEngine`과 `DataCollector` 사이의 의존성을 활용하여 이벤트 브릿지를 구축합니다.

### 2.1 주요 수정 사항
- **콜백 주입**: `TradingEngine.set_data_collector`가 호출될 때, 엔진의 내부 브릿지 메서드(`_handle_collector_candle`)를 `DataCollector`의 콜백으로 주입합니다.
- **이벤트 발행 로직**:
    - 수신된 캔들의 `is_closed` 상태를 확인합니다.
    - 웹소켓 스레드 세이프티를 고려하여 `asyncio.run_coroutine_threadsafe`를 사용해 메인 루프의 `EventBus.publish`를 호출합니다.

### 2.2 예상 흐름
1. `BinanceDataCollector` → 웹소켓 캔들 수신
2. `on_candle_callback` (브릿지 메서드) 호출
3. `is_closed=True` 확인 시 `Event(EventType.CANDLE_CLOSED)` 생성
4. `EventBus.publish(event)` 실행
5. `TradingEngine._on_candle_closed` 핸들러 실행 (전략 분석 시작)

---

## 3. 검토 의견

사용자가 지적한 초기화 시점과 핸들러 등록의 선후 관계 문제는 본 브릿지 로직을 통해 해결됩니다. `run()` 메서드가 실행되기 전에 주입된 콜백이 런타임에서 안정적으로 이벤트를 발생시키는 구조가 됩니다.

이 문서는 향후 `TradingEngine` 고도화 및 이벤트 파이프라인 디버깅 시 참조 자료로 활용됩니다.
