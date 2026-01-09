# 스레드 실행 모델 및 이벤트 흐름 분석
작성일: 2025-12-27

## 1. 스레드의 자동 생성 여부
스레드는 프로그램 실행 과정에서 OS나 런타임이 완전히 "임의로" 또는 "자동으로" 생성하는 것이 아닙니다. **반드시 코드 어딘가에서 명시적인 생성 명령(예: `threading.Thread(...).start()`)이 있어야 생성됩니다.**

프로젝트에서 사용 중인 `BinanceDataCollector`의 경우:
- 내부적으로 `binance-connector-python` (또는 유사 라이브러리)의 `UMFuturesWebsocketClient`를 사용합니다.
- 이 라이브러리는 웹소켓 연결 유지와 실시간 메시지 수신을 위해 **백그라운드 스레드를 내부적으로 생성**하여 구동합니다.
- 따라서 사용자가 직접 스레드를 생성하지 않았더라도 라이브러리 초기화 시점(`start_streaming` 등)에 스레드가 명시적으로 생성된 것입니다.

## 2. `_on_candle_received` 및 퍼블리쉬 수행 주체 분석

`src/main.py` 및 `src/core/data_collector.py` 코드 분석 결과에 따른 실행 흐름은 다음과 같습니다.

### A. `_on_candle_received` 수행 주체: 소켓 스레드
- `BinanceDataCollector`가 웹소켓 메시지를 수신하면, 라이브러리가 관리하는 **백그라운드 스레드(소켓 스레드)**가 `_handle_kline_message`를 실행합니다.
- 이어서 설정된 콜백인 `_on_candle_received`가 호출되므로, 이 메서드 진입 시점의 실행 주체는 **메인 스레드가 아닌 소켓 스레드**입니다.

### B. 캔들 퍼블리쉬 작업의 수행 주체: 메인 스레드 (Event Loop)
`TradingBot._on_candle_received` 내부에는 스레드 간 컨텍스트 전환을 위한 로직이 존재합니다:

```python
asyncio.run_coroutine_threadsafe(
    self.event_bus.publish(event, queue_name='data'),
    self._event_loop
)
```

- **호출(Call):** `publish`를 요청하는 코드는 **소켓 스레드**에서 실행됩니다.
- **실행(Execution):** 실제 `publish` 코루틴은 `run_coroutine_threadsafe`를 통해 **메인 스레드의 이벤트 루프(`self._event_loop`)**로 전달되어 스케줄링됩니다.
- **결론:** 실제 이벤트가 큐에 담기는 작업은 메인 스레드에서 안전하게 수행되도록 설계되어 있어 스레드 안전성(Thread Safety)이 보장됩니다.
