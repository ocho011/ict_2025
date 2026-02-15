# Feature Design: Event-Driven Pipeline Migration

## 1. 개요 (Overview)
본 문서는 기존 모노리식 전략에서 컴포넌트 조립형, 이벤트 드리븐 파이프라인으로의 마이그레이션을 위한 설계 내용을 담고 있습니다. 시그널 생성, 주문 생성/전송, 포지션 라이프사이클 관리를 이벤트 드리븐 방식으로 재구현하고, 이를 통해 기존 매매 플로우를 완전히 대체하는 것을 목표로 합니다.

## 2. 아키텍처 개요 (Architectural Overview)

### 2.1. 핵심 컴포넌트 (Core Components)
*   **Signal Generator:** 시장 데이터(캔들, 지표 등)를 분석하여 매매 시그널(예: BUY, SELL)을 생성합니다. 생성된 시그널은 이벤트 형태로 발행됩니다.
*   **Order Manager:** Signal Generator에서 발행된 시그널 이벤트를 수신하여 실제 거래소 주문(Market Order, Limit Order 등)을 생성하고 전송합니다. 주문 체결 결과는 다시 이벤트 형태로 발행됩니다.
*   **Position Manager:** Order Manager의 주문 체결 이벤트를 수신하여 현재 포지션 상태(개설, 청산, 부분 청산 등)를 관리합니다. 포지션 변경 시 관련 이벤트를 발행합니다.
*   **Event Bus/Broker:** 각 컴포넌트 간의 비동기적이고 느슨하게 결합된 통신을 중개하는 역할을 합니다. (예: Kafka, RabbitMQ, 또는 내부적인 Pub/Sub 시스템)

### 2.2. 이벤트 흐름 (Event Flow)
1.  **시장 데이터 수신:** (외부 시스템) -> Signal Generator
2.  **시그널 생성:** Signal Generator -> `SignalGeneratedEvent` 발행 -> Event Bus
3.  **주문 생성 및 전송:** Event Bus -> Order Manager (구독) -> 주문 전송 -> 거래소
4.  **주문 체결 통보:** 거래소 -> Order Manager (수신) -> `OrderFilledEvent` 발행 -> Event Bus
5.  **포지션 관리:** Event Bus -> Position Manager (구독) -> 포지션 업데이트 -> `PositionUpdatedEvent` 발행 -> Event Bus
6.  **리스크 관리:** Event Bus -> Risk Manager (구독) -> 포지션 및 전체 리스크 모니터링
7.  **모니터링 및 로깅:** Event Bus -> Monitoring/Logging Service (구독)

## 3. 상세 설계 (Detailed Design)

### 3.1. 이벤트 정의 (Event Definitions)
모든 이벤트는 고유한 타입(`type`), 페이로드(`payload`), 발생 시간(`timestamp`), 이벤트 ID(`event_id`) 등을 포함하는 표준화된 형태로 정의합니다.

*   `SignalGeneratedEvent`:
    *   `signal_type`: "BUY", "SELL", "HOLD"
    *   `symbol`: 거래 심볼 (예: "BTC/USDT")
    *   `price`: 시그널 발생 시점의 가격
    *   `volume`: 주문 희망 수량
    *   `strategy_id`: 시그널을 생성한 전략 ID

*   `OrderPlacementRequestEvent`: (내부용, SignalGeneratedEvent를 기반으로 Order Manager가 발행할 수 있음)
    *   `order_type`: "MARKET", "LIMIT"
    *   `side`: "BUY", "SELL"
    *   `symbol`: 거래 심볼
    *   `quantity`: 주문 수량
    *   `price`: 지정가 주문 시 가격 (선택 사항)
    *   `strategy_id`: 관련 전략 ID

*   `OrderCreatedEvent`:
    *   `order_id`: 거래소에서 발급된 주문 ID
    *   `status`: "NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED"
    *   `client_order_id`: 내부 주문 참조 ID
    *   ... (기타 주문 정보)

*   `OrderFilledEvent`: (OrderCreatedEvent의 `status`가 FILLED일 때 발생)
    *   `order_id`: 체결된 주문 ID
    *   `filled_quantity`: 체결된 수량
    *   `filled_price`: 평균 체결 가격
    *   `commission`: 수수료 정보
    *   ...

*   `PositionUpdateEvent`:
    *   `position_id`: 포지션 ID
    *   `symbol`: 거래 심볼
    *   `current_quantity`: 현재 포지션 수량
    *   `entry_price`: 포지션 진입 평균 가격
    *   `unrealized_pnl`: 미실현 손익
    *   `status`: "OPEN", "CLOSED"
    *   ...

### 3.2. 컴포넌트별 책임 및 인터페이스

*   **Signal Generator**
    *   책임: 시장 데이터 수집 및 분석, 매매 시그널 생성, `SignalGeneratedEvent` 발행
    *   인터페이스: `process_market_data(data)`, `publish_signal(event)`

*   **Order Manager**
    *   책임: `SignalGeneratedEvent` 수신, 거래소 주문 생성/전송, 거래소 응답 처리, `OrderCreatedEvent`, `OrderFilledEvent` 발행
    *   인터페이스: `handle_signal_event(event)`, `send_order_to_exchange(order_params)`, `process_exchange_response(response)`, `publish_order_event(event)`

*   **Position Manager**
    *   책임: `OrderFilledEvent` 수신, 포지션 개설/갱신/청산 관리, `PositionUpdateEvent` 발행
    *   인터페이스: `handle_order_filled_event(event)`, `update_position(position_id, updates)`, `publish_position_event(event)`

### 3.3. 이벤트 버스/브로커 선택 및 구현
*   **선택:** 초기에는 간단한 In-memory Pub/Sub 시스템으로 시작하여 개발 속도를 높이고, 추후 확장성 및 안정성 요구사항에 따라 Kafka 또는 RabbitMQ와 같은 전문 메시지 브로커로 전환을 고려합니다.
*   **구현:**
    *   `EventBus` 클래스: `subscribe(event_type, handler)`, `publish(event)` 메서드 제공
    *   핸들러 등록: 각 컴포넌트 초기화 시 Event Bus에 필요한 이벤트 핸들러를 등록

## 4. 마이그레이션 전략 (Migration Strategy)
1.  **단계적 구현:**
    *   **Phase 1: 인프라 구축:** Event Bus/Broker 구현 또는 통합.
    *   **Phase 2: 시그널 마이그레이션:** Signal Generator 컴포넌트를 먼저 구현하고, Event Bus를 통해 시그널을 발행하도록 변경. 기존 모노리식 전략의 시그널 부분만 대체.
    *   **Phase 3: 주문 마이그레이션:** Order Manager 컴포넌트를 구현하고, `SignalGeneratedEvent`를 받아 주문을 생성하도록 연결. 기존 주문 전송 로직 대체.
    *   **Phase 4: 포지션 마이그레이션:** Position Manager 컴포넌트를 구현하고, `OrderFilledEvent`를 받아 포지션을 관리하도록 연결. 기존 포지션 관리 로직 대체.
    *   **Phase 5: 통합 및 테스트:** 모든 컴포넌트 통합 후 광범위한 테스트 수행.

2.  **병렬 운영 (Blue/Green Deployment 유사):** 초기 마이그레이션 단계에서는 기존 모노리식 전략과 새로운 이벤트 드리븐 파이프라인을 병렬로 운영하며 결과를 비교 검증합니다. 충분한 신뢰가 확보되면 기존 시스템을 중단합니다.

3.  **역방향 호환성:** 마이그레이션 중에도 기존 시스템이 정상 작동할 수 있도록 인터페이스 변경을 최소화하고, 필요한 경우 어댑터(Adapter) 패턴을 적용합니다.

## 5. 테스트 계획 (Test Plan)
*   **단위 테스트:** 각 컴포넌트별 핵심 로직에 대한 단위 테스트
*   **통합 테스트:** Event Bus를 통한 컴포넌트 간 이벤트 흐름 및 데이터 전달 검증
*   **기능 테스트:** 기존 모노리식 전략이 수행하던 모든 매매 플로우가 새로운 시스템에서 동일하게 (또는 개선되어) 작동하는지 검증
*   **성능 테스트:** 마이그레이션 전후 시스템의 latency, throughput, resource usage 비교

## 6. 보안 및 에러 처리 (Security & Error Handling)
*   **이벤트 유효성 검사:** 각 컴포넌트는 수신하는 이벤트의 유효성을 검사하여 잘못된 데이터 처리를 방지합니다.
*   **재시도 메커니즘:** 거래소 통신 등 외부 연동 시 일시적인 오류에 대비한 재시도 로직 구현
*   **데드 레터 큐 (Dead Letter Queue):** 처리 실패한 이벤트를 위한 DLQ를 도입하여 이벤트 유실 방지 및 재처리 메커니즘 마련 (고급 단계)
*   **로깅 및 모니터링:** 각 컴포넌트의 이벤트 처리 과정 및 오류 발생 시 상세 로깅, 통합 모니터링 시스템 구축

## 7. 리스크 및 완화 (Risks & Mitigation)
*   **리스크:** 복잡성 증가 (이벤트 체인 추적 어려움), 이벤트 유실, 성능 병목
*   **완화:** 철저한 문서화, 통합 로깅 및 트레이싱 시스템 구축, 메시지 브로커의 신뢰성 기능 활용, 성능 테스트 및 튜닝

---
