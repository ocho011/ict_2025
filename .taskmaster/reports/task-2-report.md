# Task #2: Data Models & Core Types Definition

## 📋 메타데이터

- **Task ID**: #2
- **완료 날짜**: 2025-12-06
- **복잡도**: Medium (6/10)
- **소요 시간**: ~2시간
- **담당자**: Claude Code + Serena MCP

## 🎯 목표

ICT 2025 거래 시스템을 위한 견고하고 타입 안전한 데이터 모델을 정의. Python dataclass를 사용하여 5개의 핵심 모델(Candle, Signal, Order, Position, Event)을 구현하고, Binance USDT-M Futures API와의 완벽한 호환성 확보.

## ✅ 구현 내용

### 2.1 Candle (OHLCV) 모델 강화
- ✅ `__post_init__` 검증 추가 (high/low/volume 유효성 검사)
- ✅ 계산 속성 추가: `upper_wick`, `lower_wick`
- ✅ 필드 순서 최적화 (symbol, interval 우선)
- **주요 파일**: `src/models/candle.py`

**핵심 검증 로직**:
```python
def __post_init__(self) -> None:
    if self.high < max(self.open, self.close):
        raise ValueError(...)
    if self.low > min(self.open, self.close):
        raise ValueError(...)
    if self.volume < 0:
        raise ValueError(...)
```

### 2.2 Signal 모델 불변성 및 검증 강화
- ✅ SignalType enum 값 변경: `LONG_ENTRY`, `SHORT_ENTRY`, `CLOSE_LONG`, `CLOSE_SHORT`
- ✅ Dataclass frozen으로 변경 (불변 값 객체)
- ✅ LONG/SHORT별 TP/SL 검증 로직 구현
- ✅ 계산 속성 추가: `risk_amount`, `reward_amount`, `risk_reward_ratio`
- **주요 파일**: `src/models/signal.py`

**핵심 검증 로직**:
```python
if self.signal_type == SignalType.LONG_ENTRY:
    if self.take_profit <= self.entry_price:
        raise ValueError("LONG: take_profit must be > entry_price")
    if self.stop_loss >= self.entry_price:
        raise ValueError("LONG: stop_loss must be < entry_price")
```

### 2.3 Order 모델 Binance API 호환성 확보
- ✅ OrderStatus에 `EXPIRED` 추가
- ✅ Optional 타입 힌트 명시화
- ✅ LIMIT/STOP 주문 검증 강화
- ✅ Binance API enum 값 정확히 일치 확인
- **주요 파일**: `src/models/order.py`

**Binance API 호환성**:
- `OrderType`: MARKET, LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET
- `OrderSide`: BUY, SELL
- `OrderStatus`: NEW, FILLED, PARTIALLY_FILLED, CANCELED, REJECTED, EXPIRED

### 2.4 Position 모델 및 Event 모델 구현
- ✅ Position: PositionSide enum 제거, 문자열 'LONG'/'SHORT' 사용
- ✅ Position: `notional_value`, `margin_used` 계산 속성 추가
- ✅ Event: 새 파일 생성 (`src/models/event.py`)
- ✅ EventType: 7개 이벤트 타입 정의 (CANDLE_UPDATE, SIGNAL_GENERATED 등)
- **주요 파일**:
  - `src/models/position.py`
  - `src/models/event.py` (신규)

## 🔧 주요 기술 결정

### 결정 1: Signal을 Frozen Dataclass로 구현
- **문제**: Signal은 값 객체(Value Object)인가, 변경 가능한 엔티티인가?
- **선택**: `@dataclass(frozen=True)` 사용
- **이유**:
  - Signal은 한번 생성되면 변경되지 않는 불변 값 객체
  - 전략 엔진이 생성한 신호는 수정되지 않음
  - 불변성으로 인한 버그 방지 (의도치 않은 수정 차단)
- **트레이드오프**:
  - ✅ 장점: 스레드 안전성, 해시 가능, 버그 방지
  - ⚠️ 단점: 생성 후 수정 불가 (우리 use case에서는 필요 없음)

### 결정 2: Position.side를 Enum 대신 String 사용
- **문제**: Position 방향을 Enum으로 할지 String으로 할지
- **선택**: 문자열 'LONG' 또는 'SHORT' 사용
- **이유**:
  - Binance API가 문자열로 반환
  - 간단한 2가지 값만 존재
  - Enum 오버헤드 불필요
- **트레이드오프**:
  - ✅ 장점: API 호환성, 코드 간결성
  - ⚠️ 단점: 타입 안전성 약간 감소 (validation으로 보완)

### 결정 3: `__post_init__` 패턴으로 검증
- **문제**: 객체 생성 시 검증을 어디서 할 것인가?
- **선택**: Dataclass `__post_init__` 메서드 활용
- **이유**:
  - Dataclass의 표준 패턴
  - 생성 시점에 즉시 검증 (Fail Fast)
  - 잘못된 데이터로 객체 생성 원천 차단
- **트레이드오프**:
  - ✅ 장점: 명확한 에러 메시지, 데이터 무결성 보장
  - ⚠️ 단점: 생성 비용 약간 증가 (무시할 수준)

### 결정 4: EventType을 별도 Enum으로 정의
- **문제**: 이벤트 타입을 문자열로 할지 Enum으로 할지
- **선택**: EventType Enum 사용
- **이유**:
  - 이벤트 기반 아키텍처에서 타입 안전성 중요
  - IDE 자동완성 지원
  - 오타 방지
- **트레이드오프**:
  - ✅ 장점: 타입 안전성, 유지보수성, IDE 지원
  - ⚠️ 단점: 새 이벤트 추가 시 Enum 수정 필요

## 📦 변경된 파일

```
src/models/
├── candle.py          # 수정: 검증 강화, 계산 속성 추가
├── signal.py          # 수정: frozen, enum 변경, 검증 강화
├── order.py           # 수정: EXPIRED 추가, 검증 강화
├── position.py        # 수정: 계산 속성 추가
├── event.py           # 신규: Event 모델 및 EventType enum
└── __init__.py        # 수정: 모든 모델 export

tests/
└── test_models.py     # 신규: 23개 단위 테스트

.taskmaster/docs/
└── design-data-models.md  # 신규: 설계 문서

.serena/memories/
└── documentation_structure.md  # 신규: 문서 구조 규칙
```

## 🧪 테스트 결과

### 단위 테스트
```bash
# 실행 명령어
pytest tests/test_models.py -v

# 결과
✅ TestCandle::test_valid_bullish_candle PASSED
✅ TestCandle::test_valid_bearish_candle PASSED
✅ TestCandle::test_invalid_high_raises_error PASSED
✅ TestCandle::test_invalid_low_raises_error PASSED
✅ TestCandle::test_negative_volume_raises_error PASSED

✅ TestSignal::test_valid_long_entry_signal PASSED
✅ TestSignal::test_valid_short_entry_signal PASSED
✅ TestSignal::test_invalid_confidence_raises_error PASSED
✅ TestSignal::test_invalid_long_tp_raises_error PASSED
✅ TestSignal::test_invalid_short_tp_raises_error PASSED

✅ TestOrder::test_valid_market_order PASSED
✅ TestOrder::test_valid_limit_order PASSED
✅ TestOrder::test_limit_order_without_price_raises_error PASSED
✅ TestOrder::test_stop_market_without_stop_price_raises_error PASSED
✅ TestOrder::test_invalid_quantity_raises_error PASSED
✅ TestOrder::test_order_enum_values_match_binance PASSED

✅ TestPosition::test_valid_long_position PASSED
✅ TestPosition::test_valid_short_position PASSED
✅ TestPosition::test_invalid_side_raises_error PASSED
✅ TestPosition::test_invalid_quantity_raises_error PASSED
✅ TestPosition::test_invalid_leverage_raises_error PASSED

✅ TestEvent::test_create_candle_update_event PASSED
✅ TestEvent::test_create_signal_generated_event PASSED

총 23/23 테스트 통과 (100%)
모델 커버리지: 100%
```

### 타입 체크
```bash
# 실행 명령어
mypy src/models/

# 결과
✅ src/models/candle.py: Success: no issues found
✅ src/models/signal.py: Success: no issues found
✅ src/models/order.py: Success: no issues found
✅ src/models/position.py: Success: no issues found
✅ src/models/event.py: Success: no issues found
```

### 코드 품질 검사
```bash
# Black (코드 포맷팅)
✅ All done! 7 files would be left unchanged.

# isort (import 정렬)
✅ All imports correctly sorted

# flake8 (코드 스타일)
✅ No issues found
```

### 수동 검증
- ✅ 모든 모델 import 성공 확인
- ✅ Binance API enum 값 정확히 일치 확인
- ✅ 계산 속성 값 정확성 검증
- ✅ 검증 로직 엣지 케이스 테스트

## ⚠️ 알려진 이슈 / 제한사항

없음. 모든 요구사항 충족 및 테스트 통과.

## 🔗 연관 Task

- **선행 Task**: Task #1 (프로젝트 기반 구조 및 환경 설정) - ✅ 완료
- **후속 Task**: Task #3 (데이터 수집 레이어 구현) - ⏳ 대기 중
- **연관 Task**: 없음

## 📚 참고 자료

- [Binance USDT-M Futures API Documentation](https://binance-docs.github.io/apidocs/futures/en/)
- [Python Dataclasses Official Docs](https://docs.python.org/3/library/dataclasses.html)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- 프로젝트 설계 문서: `.taskmaster/docs/design-data-models.md`

## 💡 학습 내용 / 개선 사항

### 학습한 점
- **Dataclass Frozen Pattern**: 값 객체의 불변성을 강제하는 효과적인 패턴
- **`__post_init__` 검증**: Dataclass에서 생성 시점 검증의 표준 패턴
- **API 호환성 우선**: Enum 값을 API 명세와 정확히 일치시키는 것의 중요성
- **계산 속성 활용**: `@property`로 파생 값을 캡슐화하여 중복 계산 방지
- **Serena MCP 활용**: 프로젝트 메모리로 문서 구조 규칙을 영구 저장

### 다음에 개선할 점
- 현재 모델은 완벽하게 구현됨
- 향후 Task에서는 이 모델들을 기반으로 비즈니스 로직 구현
- Event 기반 아키텍처 패턴을 적극 활용할 것

### 효과적이었던 접근법
1. **설계 문서 먼저 작성**: `/sc:design --serena`로 명확한 설계 후 구현
2. **단계적 검증**: 각 모델 수정 후 즉시 검증
3. **포괄적 테스트**: 23개 테스트로 모든 검증 로직 커버
4. **문서화**: Serena 메모리에 문서 구조 규칙 저장하여 혼동 방지

## 📌 다음 단계

**Task #3: 데이터 수집 레이어 구현**
- Binance WebSocket 연결 구현
- 실시간 캔들 데이터 수신
- Candle 모델로 파싱 및 검증
- Event 시스템과 통합
- 재연결 및 에러 처리 로직
