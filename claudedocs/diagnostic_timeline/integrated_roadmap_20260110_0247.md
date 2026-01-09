# GitHub 이슈 통합 실행 로드맵 (v3)
**작성일시**: 2026-01-10 02:47

이 프로젝트의 현재 상태와 GitHub 이슈 #5, #6, #7, #8, #9 간의 기술적 의존성 및 시급성을 분석한 결과, **아키텍처 및 안전성 확보 → 데이터 모델 → 도메인 로직 → 멀티 심볼 확장** 순으로 접근하는 것이 가장 타당합니다.

## 제안 작업 순서 (Roadmap)

1.  **[Step 1] 아키텍처 정비 (#5) 및 고아 주문 방지 (#9)**
    - **핵심**: Bot/Engine 책임 분리 + 포지션 종료 시 TP/SL 잔량 자동 취소.
    - **이유**: 시스템 구조 정립과 동시에 자금 안전(Safety)을 위협하는 버그(#9)를 해결합니다.

2.  **[Step 2] 인메모리 EnrichedCandle 모델 설계 (#6)**
    - **핵심**: ICT 지표를 내장한 확장형 캔들 모델 및 전용 버퍼 구축.
    - **이유**: 후속 전략 로직(#7) 및 확장(#8)의 근간이 되는 데이터 표준을 정의합니다.

3.  **[Step 3] 이슈 #7: 전략 버퍼 격리 보장 및 ICT 전략 MTF 전환 (Domain Logic)**
    - **핵심**: 인터벌 간 데이터 혼입 해결 및 멀티 타임프레임(HTF/LTF) 분석 로직 완성.
    - **이유**: 현재 발생 중인 데이터 오염 버그를 해결하고 단일 심볼 트레이딩 완성도 확보.

4.  **[Step 4] 이슈 #8: 멀티 코인 트레이딩 지원 (Scaling)**
    - **핵심**: 1 Coin = 1 Strategy Instance 구조로 확장.
    - **이유**: 준비된 인프라(#5, #6, #7)를 활용하여 안정적으로 여러 심볼을 동시 트레이딩.

---

## 상세 구현 계획

### [Step 1] 아키텍처 리팩토링 및 안전성 강화
- **대상**: [main.py](file:///Users/osangwon/github/ict_2025/src/main.py), [trading_engine.py](file:///Users/osangwon/github/ict_2025/src/core/trading_engine.py), [order_manager.py](file:///Users/osangwon/github/ict_2025/src/execution/order_manager.py)
- **변경**: 
    - `TradingBot`은 라이프사이클 관리만 담당, `TradingEngine`이 오케스트레이션 전담 (#5).
    - **#9 통합**: 포지션이 종료(CLOSE 신호 혹은 TP/SL 체결)될 때, 해당 심볼의 나머지 주문들을 즉시 취소하는 로직 구현.
- **통합**: 세션 `0d55662b`의 주기적 시그널 통계 로깅 기능을 새로운 엔진 구조에 이식.

### [Step 2] 이슈 #6: EnrichedCandle 인프라 구축
- **대상**: `src/models/enriched_candle.py` [NEW], `src/data/enriched_buffer.py` [NEW]
- **변경**: 단순 `Candle`을 감싸고 ICT 지표 계산 로직을 내장한 모델 도입. `deque` 기반의 고성능 전용 버퍼 구현.

### [Step 3] 이슈 #7: MTF 전략 전환 및 버퍼 격리
- **대상**: `src/strategies/base.py`, `src/strategies/ict_strategy.py`
- **변경**: `BaseStrategy`를 `MultiTimeframeStrategy`로 확장. 인터벌별 독립 버퍼(`Dict[interval, EnrichedBuffer]`)를 사용하여 데이터 혼입 원천 차단.
- **연계**: 세션 `0d55662b`에서 디버깅한 **시그널 미발생 문제**의 근본 원인인 '데이터 오염'을 이 단계에서 원천 해결.

### [Step 4] 이슈 #8: 멀티 코인 확장
- **대상**: [config.py](file:///Users/osangwon/github/ict_2025/src/utils/config.py), `trading_engine.py`
- **변경**: `TradingConfig.symbols` (List) 지원. `TradingEngine`이 심볼별로 전략 인스턴스를 생성하고 관리. 순차적 백필을 통한 Rate Limit 보호 로직 추가.

---

## 검증 계획

### Automated Tests
- **구조 검증**: 리팩토링 후 기존 단일 코인 페이퍼 트레이딩이 정상 작동하는지 확인.
- **격리 검증**: HTF/LTF 데이터가 섞이지 않는지, 각 심볼별 전략이 독립적으로 작동하는지 유닛 테스트 수행.

### Manual Verification
- **로그 및 지표 확인**: `ict_strategy`에서 계산된 FVG, OB 값이 차트 데이터와 일치하는지 전수 검사.
- **Rate Limit 모니터링**: 멀티 코인 백필 시 바이낸스 API 제한에 걸리지 않는지 확인.
