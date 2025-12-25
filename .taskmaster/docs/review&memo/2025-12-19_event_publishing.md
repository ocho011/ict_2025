# Q&A Log: 2025-12-19 Event Publishing and Injection

## Q1: 트레이딩 엔진 동작 전 의존성 주입 시점
**Q:** `run()` 메서드 호출 전에 `set_data_collector` 등으로 외부 주입이 선행되어야 하는가? 이 주입은 어느 단계에서 수행되는가?

**A:**
네, `run()` 호출 전에 `set_data_collector`, `set_strategy` 등을 통한 의존성 주입이 필수적입니다.
이 과정은 프로젝트의 **진입점(Entry Point)**인 `main.py` (또는 실행 스크립트)에서 수행됩니다.

**일반적인 실행 흐름:**
1. **설정 로드:** Config 파일 등 로드
2. **컴포넌트 생성:** `TradingEngine`, `DataCollector`, `Strategy` 등 개별 객체 생성
3. **조립(Assembly):** `engine.set_data_collector(collector)` 등으로 연결
4. **실행:** `await engine.run()`

---

## Q2: CANDLE_CLOSED 이벤트의 발생 위치
**Q:** `CANDLE_CLOSED` 이벤트는 어디서 이벤트 버스 큐로 Publish 되는가?

**A:**
`TradingEngine`이 `DataCollector`를 설정(`set_data_collector`)할 때 연결하는 **콜백 함수 내부**에서 발생해야 합니다.

**구현 원리:**
1. `DataCollector`는 웹소켓 수신 시 `self.on_candle_callback(candle)`을 호출합니다.
2. `TradingEngine`은 이 `on_candle_callback`에 자신의 핸들러(예: `_handle_incoming_candle`)를 연결합니다.
3. 연결된 핸들러 내부에서 `candle.is_closed`를 확인하고, 마감된 캔들이면 `event_bus.publish(Event(EventType.CANDLE_CLOSED, ...))`를 호출합니다.

**특이사항:**
현재 코드상으로는 `TradingEngine.set_data_collector` 내부에 이 연결 로직이 명시적으로 보이지 않으므로, 향후 리팩토링이나 구현 시 이 부분을 추가해야 합니다.
