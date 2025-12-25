# 분석 및 리팩토링 제안 - TradingBot과 TradingEngine의 역할 중복 개선

## 1. 현황 분석 및 문제점

현재 프로젝트는 시스템의 실행과 제어를 담당하는 두 개의 주요 클래스가 존재하며, 기능이 상당 부분 중복되어 있습니다.

*   **대상 파일**: 
    1.  `src/main.py` (`TradingBot` 클래스)
    2.  `src/core/trading_engine.py` (`TradingEngine` 클래스)

### 주요 문제점 (Redundancy & Confusion)
1.  **이벤트 핸들러 중복 구현**: 캔들이 마감될 때 전략을 실행하고 신호를 처리하는 로직(`_on_candle_closed`, `_on_signal` 등)이 두 클래스 모두에 독립적으로 구현되어 있습니다.
2.  **런타임 루프 중복**: `asyncio.gather`를 통해 `EventBus`와 `DataCollector`를 실행하고 관리하는 루프가 양쪽 모두에 존재하거나 존재할 예정입니다.
3.  **결합도 오류**: `TradingBot`은 원래 시스템을 조립(orchestrate)하는 역할이어야 하나, 현재는 엔진의 핵심 비즈니스 로직까지 직접 수행하고 있습니다.

## 2. 리팩토링 제안 (역할 분리)

시스템 아키텍처의 정체성을 명확히 하기 위해 다음과 같이 역할을 재정의하고 통합해야 합니다.

### [역할 정의]
*   **TradingBot (Bootstrapper)**:
    *   `ConfigManager`를 통한 설정 로드 및 검증.
    *   로깅 시스템(`TradingLogger`) 및 오딧 로거 초기화.
    *   필요한 모든 컴포넌트(`DataCollector`, `Strategy`, `OrderManager`, `RiskManager`) 생성.
    *   **Core Engine(`TradingEngine`) 생성 및 컴포넌트 주입(Dependency Injection).**
    *   시그널 핸들러(SIGINT/SIGTERM) 관리 및 엔진 실행 시작.

*   **TradingEngine (Core Executor)**:
    *   이벤트 기반 트레이딩 파이프라인의 순수 비즈니스 로직 실행.
    *   `EventBus`를 통한 단계별 핸들러 등록 및 이벤트 라우팅.
    *   비동기 런타임 환경(`run`/`shutdown`)의 실제 제어.

### [실행 계획]
1.  `src/main.py`의 `TradingBot`에서 중복된 이벤트 핸들러 메서드들을 제거합니다.
2.  `TradingBot.initialize()` 과정 마지막에 `TradingEngine` 인스턴스를 생성하고, 준비된 객체들을 `set_xxx` 메서드를 통해 전달합니다.
3.  `TradingBot.run()`은 직접 루프를 돌지 않고 `self.engine.run()`을 호출하는 인터페이스 역할만 수행합니다.

## 3. 기대 효과
*   **유지보수성 향상**: 트레이딩 로직 수정 시 `TradingEngine` 한 곳만 수정하면 됩니다.
*   **테스트 용이성**: 엔진이 외부 설정(INI)과 분리되므로 모의 데이터를 이용한 엔진 테스트가 쉬워집니다.
*   **아키텍처 명확성**: 시스템의 "준비 과정"과 "실행 로직"이 엄격히 분리됩니다.
