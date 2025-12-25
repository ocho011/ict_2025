# Ticker-Specific Design Analysis (2025-12-20)

이 분석은 시스템의 주요 컴포넌트(`DataCollector`, `Strategy`, `OrderManager`, `TradingEngine`)가 특정 티커(ticker/symbol)를 전제로 설계되었는지 확인한 결과입니다.

## 요약

현재 시스템 설계상 **`DataCollector`와 `OrderManager`는 여러 티커를 동시에 처리**할 수 있도록 설계되어 있으나, **`BaseStrategy`(및 그 하위 클래스)는 인스턴스당 하나의 티커**를 담당하도록 설계되어 있습니다. 또한, **`TradingEngine`은 현재 하나의 전략 인스턴스만 보유**할 수 있어, 실질적으로 전체 파이프라인이 단일 티커에 집중된 구조입니다.

| 컴포넌트 | 다중 티커 지원 여부 | 분석 근거 |
| :--- | :---: | :--- |
| **`BinanceDataCollector`** | **Yes** | 초기화 시 `symbols: List[str]`를 받으며, 심볼별로 독립된 `candle_buffers`를 관리합니다. |
| **`OrderExecutionManager`** | **Yes** | 주문 실행 및 설정(`set_leverage`, `create_order` 등) 메서드 호출 시마다 `symbol`을 파라미터로 명시적으로 받습니다. |
| **`BaseStrategy`** | **No** | 초기화 시 단일 `symbol`을 받으며, 내부에 단일 `candle_buffer`를 가집니다. 다른 심볼의 캔들이 들어오면 버퍼가 오염될 수 있습니다. |
| **`TradingEngine`** | **No** (현재) | 단일 `self.strategy` 인스턴스만 가집니다. `DataCollector`가 여러 심볼의 데이터를 보내도 동일한 전략 인스턴스의 `analyze()`를 호출하게 됩니다. |

---

## 컴포넌트별 상세 분석

### 1. [DataCollector](file:///Users/osangwon/github/ict_2025/src/core/data_collector.py)
- `__init__`에서 `symbols: List[str]`를 인자로 받아 여러 코인을 동시에 구독할 수 있습니다.
- `self._candle_buffers`가 `Dict[str, deque]` 형태로 선언되어 있어, `BTCUSDT_1m`, `ETHUSDT_1m`과 같이 심볼 및 인터벌별로 데이터를 분리하여 관리합니다.

### 2. [BaseStrategy](file:///Users/osangwon/github/ict_2025/src/strategies/base.py) 및 [Subclasses](file:///Users/osangwon/github/ict_2025/src/strategies/mock_strategy.py)
- `BaseStrategy.__init__`은 `symbol: str`와 `config: dict`를 인자로 받습니다.
- `update_buffer(candle)` 메서드는 들어오는 캔들의 심볼을 체크하지 않고 `self.candle_buffer`에 무조건 추가합니다.
- 따라서 하나의 전략 인스턴스에 여러 심볼의 캔들을 흘려보내면 히스토리 데이터가 섞이게 되어 기술적 분석 결과가 왜곡됩니다.

### 3. [OrderExecutionManager](file:///Users/osangwon/github/ict_2025/src/execution/order_manager.py)
- 인스턴스 생성 시 특정 심볼에 종속되지 않습니다.
- 모든 주요 명령(`set_leverage`, `set_margin_type`, `new_order` 등)이 호출 시마다 심볼을 요구하며, 내부 상태(`_open_orders`, `_exchange_info_cache`)도 심볼 단위로 맵핑되어 관리됩니다.

### 4. [TradingEngine](file:///Users/osangwon/github/ict_2025/src/core/trading_engine.py)
- `self.strategy`라는 단일 속성만 가지고 있습니다.
- `_on_candle_closed` 이벤트 핸들러는 어떤 심볼의 캔들이든 들어오는 즉시 `self.strategy.analyze(candle)`를 호출합니다.
- 만약 `DataCollector`가 다중 심볼을 수집할 경우, `TradingEngine` 레벨에서 이를 심볼별 전략 인스턴스로 분기(routing)해주는 로직이 현재는 없습니다.

---

## 결론 및 제언

현재 구조에서 여러 티커를 동시에 거래하려면 다음과 같은 접근이 필요합니다:
1.  **Ticker별 TradingEngine 실행**: 각 코인마다 별도의 엔진 인스턴스를 실행하는 방식.
2.  **TradingEngine 확장**: `self.strategy`를 심볼별 전략 인스턴스의 맵(`Dict[str, BaseStrategy]`)으로 관리하도록 엔진 코드를 수정.
3.  **Multi-Ticker Strategy 개발**: `BaseStrategy`를 수정하여 내부적으로 심볼별 버퍼를 관리하도록 하는 방식 (이 경우 전략 로직이 복잡해질 수 있음).

현재 코드는 **"전략 1개당 티커 1개"**를 처리하는 것을 기본 단위로 설계되어 있습니다.
