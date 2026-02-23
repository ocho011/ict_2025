# Strategy Abstraction Redesign - Deep Analysis Plan

## Executive Summary (결론 먼저)

**결론: 대규모 재설계는 불필요. 타겟팅된 3가지 개선만 권장.**

현재 아키텍처는 composable 전략 패턴으로의 리팩토링이 이미 잘 완료되어 있다. `ComposableStrategy + StrategyModuleConfig + 4개 Determiner ABC`의 조합이 "서브 전략을 주입받아 구성되는 고수준 전략"의 역할을 사실상 이미 수행하고 있다. 그러나 세 가지 구체적인 문제점이 존재하며, 이들은 전면 재설계 없이 점진적으로 해결 가능하다.

| 문제 | 심각도 | 권장 조치 |
|------|--------|-----------|
| PriceContext에 ICT 특화 필드 존재 | MEDIUM | generic extras dict로 전환 |
| `_`-prefixed metadata transport 암묵적 커플링 | MEDIUM | typed intermediate context 도입 |
| BaseStrategy의 이중 책임 (buffer + price delegation) | LOW | 현재 수준에서 수용 가능, 향후 분리 고려 |

"서브 전략"이라는 새로운 추상 레이어를 도입하는 것은 **불필요**하다. 현재의 Determiner ABC들이 이미 그 역할을 충분히 수행하고 있으며, 추가 추상화는 복잡성만 증가시킨다.

---

## Context

### Original Request
기존 monolith 전략을 composable 전략으로 리팩토링한 것에 수반하여, '전략'의 추상화에 대해서도 재설계할 필요성이 있는지 심층 분석.

### Current Architecture Summary
```
TradingEngine
  └── strategies: dict[str, BaseStrategy]  (per-symbol)
        └── ComposableStrategy(BaseStrategy)
              └── StrategyModuleConfig (frozen dataclass)
                    ├── EntryDeterminer (ABC)
                    ├── StopLossDeterminer (ABC)
                    ├── TakeProfitDeterminer (ABC)
                    └── ExitDeterminer (ABC)
```

Assembly chain:
```
INI/YAML → ConfigManager → TradingConfig
→ build_module_config(strategy_name, config, exit_config)
→ (StrategyModuleConfig, intervals, min_rr_ratio)
→ StrategyFactory.create_composed()
→ ComposableStrategy instance per symbol
```

### Key Files
- `/Users/osangwon/github/ict_2025/src/strategies/base.py` - BaseStrategy ABC (1135 lines)
- `/Users/osangwon/github/ict_2025/src/strategies/composable.py` - ComposableStrategy (214 lines)
- `/Users/osangwon/github/ict_2025/src/pricing/base.py` - PriceContext, StrategyModuleConfig, SL/TP ABCs (95 lines)
- `/Users/osangwon/github/ict_2025/src/entry/base.py` - EntryContext, EntryDecision, EntryDeterminer ABC (92 lines)
- `/Users/osangwon/github/ict_2025/src/exit/base.py` - ExitContext, ExitDeterminer ABC (62 lines)
- `/Users/osangwon/github/ict_2025/src/strategies/module_config_builder.py` - Strategy registry/builder (183 lines)
- `/Users/osangwon/github/ict_2025/src/strategies/__init__.py` - StrategyFactory (70 lines)
- `/Users/osangwon/github/ict_2025/src/entry/ict_entry.py` - ICTEntryDeterminer (491 lines)
- `/Users/osangwon/github/ict_2025/src/exit/ict_exit.py` - ICTExitDeterminer (455 lines)
- `/Users/osangwon/github/ict_2025/src/core/event_dispatcher.py` - EventDispatcher (strategy consumer)
- `/Users/osangwon/github/ict_2025/src/core/trading_engine.py` - TradingEngine (strategy creation)

---

## 1. 현재 추상화의 문제점 분석

### 1.1 BaseStrategy의 이중 책임

**현재 상태:**
BaseStrategy는 두 가지 책임을 가진다:
1. **Buffer/Indicator 관리**: `buffers`, `update_buffer()`, `is_ready()`, `_indicator_cache`, `_update_feature_cache()`, `initialize_with_historical_data()`
2. **Price 계산 위임**: `_price_config`, `_create_price_config()`, `_create_price_context()`, `calculate_take_profit()`, `calculate_stop_loss()`

**분석:**
- Buffer 관리는 모든 전략이 공유하는 인프라적 관심사 -- BaseStrategy에 있는 것이 자연스럽다
- Price 계산 위임 (#2)은 ComposableStrategy에서 완전히 오버라이드된다 (`_create_price_config()`에서 module_config의 determiners를 사용)
- BaseStrategy의 `calculate_take_profit()`/`calculate_stop_loss()`는 ComposableStrategy에서 직접 호출되지 않는다 -- ComposableStrategy.analyze()가 직접 `module_config.stop_loss_determiner`/`module_config.take_profit_determiner`를 호출
- 즉, BaseStrategy의 price delegation 코드(lines 185-1135의 상당 부분)는 ComposableStrategy 경로에서 **사용되지 않는 dead path**

**판정: LOW 심각도**
- 현재 monolithic 전략이 제거되었으므로, BaseStrategy의 price delegation 메서드들은 사실상 orphaned code
- 하지만 이것이 런타임 성능에 영향을 주지 않으며, 코드 복잡도도 관리 가능한 수준
- `_create_price_config()`가 `__init__`에서 호출되어 불필요한 `PriceDeterminerConfig` 객체가 생성되지만, ComposableStrategy가 이를 즉시 오버라이드하므로 실질적 문제 없음

**향후 고려사항:**
- BaseStrategy에서 price delegation 관련 코드를 제거하고, buffer/indicator 관리만 남기는 것이 깔끔
- 하지만 이는 "nice to have"이지 urgent하지 않음

### 1.2 PriceContext의 ICT 특화 필드

**현재 상태 (src/pricing/base.py lines 19-56):**
```python
@dataclass(frozen=True)
class PriceContext:
    entry_price: float
    side: str
    symbol: str
    timestamp: int
    # ICT-specific typed fields (optional)
    fvg_zone: Optional[Tuple[float, float]] = None
    ob_zone: Optional[Tuple[float, float]] = None
    displacement_size: Optional[float] = None
```

**문제:**
- `fvg_zone`, `ob_zone`, `displacement_size`는 ICT 전략에만 필요한 필드
- 이들이 generic base인 `PriceContext`에 존재하면, 새로운 전략 (예: RSI-based, Bollinger-based)을 추가할 때마다 PriceContext에 해당 전략의 특화 필드를 추가해야 함
- Open-Closed Principle 위반: 새 전략 추가 시 기존 코드 수정 필요

**판정: MEDIUM 심각도**
- 현재는 ICT만 활성 전략이므로 즉시 문제는 아님
- 하지만 전략 다양화 시 확장성 병목이 됨

### 1.3 `_`-prefixed metadata transport 암묵적 커플링

**현재 상태 (composable.py lines 113-128):**
```python
# Extract internal transport metadata (prefixed with _)
fvg_zone = decision.metadata.get("_fvg_zone")
ob_zone = decision.metadata.get("_ob_zone")
displacement_size = decision.metadata.get("_displacement_size")
```

ICTEntryDeterminer가 `_fvg_zone`, `_ob_zone`, `_displacement_size`를 metadata dict에 넣고, ComposableStrategy가 이를 하드코딩된 키로 추출하여 PriceContext에 전달.

**문제:**
- 타입 안전성 없음: Dict[str, Any]에서 string key로 접근
- 컴파일 타임 검증 불가: key 오타 시 런타임에서만 발견
- ICTEntryDeterminer와 ComposableStrategy 간 암묵적 계약
- 새 전략의 determiner가 다른 metadata를 전달하려면 ComposableStrategy도 수정해야 함

**판정: MEDIUM 심각도**
- ICT 전략만 사용하는 현재는 동작하지만, 구조적으로 fragile
- PriceContext의 ICT 특화 필드 문제와 직접 연결됨

### 1.4 StrategyModuleConfig의 추상화 수준

**현재 상태 (src/pricing/base.py lines 84-94):**
```python
@dataclass(frozen=True)
class StrategyModuleConfig:
    entry_determiner: EntryDeterminer
    stop_loss_determiner: StopLossDeterminer
    take_profit_determiner: TakeProfitDeterminer
    exit_determiner: ExitDeterminer
```

**분석:**
- "전략"을 표현하기엔 너무 저수준이라는 관점이 있지만...
- 실제로 이것은 **정확히 올바른 추상화 수준**이다
- StrategyModuleConfig는 "이 전략을 구성하는 모듈의 집합"이라는 의미를 명확히 전달
- 이것을 "Strategy"라고 이름 붙이면 ComposableStrategy와 명명 충돌이 생김
- `build_module_config()`가 "ict_strategy" → 4개 determiner 매핑을 해주므로, "고수준 전략 이름 → 저수준 모듈 조합"의 변환이 이미 존재

**판정: 문제 없음**
- 현재의 naming과 역할 분리가 적절

---

## 2. 서브 전략 추상화 검토

### 2.1 각 Determiner를 "서브 전략"으로 재정의할 필요성

**질문:** Entry, Exit, SL, TP Determiner를 "SubStrategy"라는 새 ABC로 감싸야 하는가?

**분석:**

현재 Determiner 구조:
```
EntryDeterminer.analyze(EntryContext) -> Optional[EntryDecision]
ExitDeterminer.should_exit(ExitContext) -> Optional[Signal]
StopLossDeterminer.calculate_stop_loss(PriceContext) -> float
TakeProfitDeterminer.calculate_take_profit(PriceContext, float) -> float
```

만약 "SubStrategy" ABC를 도입한다면:
```python
class SubStrategy(ABC):
    @abstractmethod
    def execute(self, context: StrategyContext) -> Any:
        pass
```

**문제점:**
1. 4개 Determiner의 인터페이스가 **의도적으로 다르다**: Entry는 EntryContext를 받아 EntryDecision을 반환하고, SL은 PriceContext를 받아 float를 반환한다. 이들을 하나의 ABC로 통합하면 타입 안전성이 사라진다.
2. "서브 전략"이라는 추상화는 개념적으로는 매력적이지만, 코드에서는 `Any` 타입의 남발로 이어진다.
3. 현재 Determiner ABC들은 이미 명확한 계약(contract)을 정의하고 있다.

**결론: 불필요**
- 현재 Determiner ABC들이 이미 "서브 전략"의 역할을 하고 있다
- 이름만 다를 뿐, 실질적으로 동일한 패턴
- 추가 추상화 레이어는 indirection만 증가시킴

### 2.2 현재 Determiner ABC가 이미 충분한 추상화를 제공하는지

**Yes.** 근거:

1. **교체 가능성**: ICTEntryDeterminer → SMAEntryDeterminer 교체가 config 변경만으로 가능 (`module_config_builder.py`의 registry)
2. **독립적 테스트**: 각 Determiner는 자체 Context를 받아 독립적으로 테스트 가능
3. **단일 책임**: Entry는 진입만, Exit는 퇴출만, SL은 손절가만, TP는 익절가만 계산
4. **조합의 유연성**: ICT Entry + Percentage SL 같은 cross-strategy 조합이 가능 (build_module_config에서 다른 조합을 만들면 됨)

### 2.3 서브 전략 간 통신 메커니즘

**현재:** `_`-prefixed metadata in Dict[str, Any] (암묵적)

**문제:** Section 1.3에서 분석한 대로, 타입 안전성 부재

**권장 개선:** EntryDecision에 typed optional field 추가 (아래 Task 2에서 상세)

---

## 3. 고수준 전략 추상화 검토

### 3.1 "특정 코인에 적용할 단일 전략" 개념의 필요성

**현재 상태:**
```python
# TradingEngine에서:
self.strategies[symbol] = StrategyFactory.create_composed(
    symbol=symbol,
    config=strategy_config,
    module_config=module_config,
    intervals=intervals_override,
    min_rr_ratio=min_rr_ratio,
)
```

**분석:**
- `ComposableStrategy` 인스턴스가 이미 "특정 코인에 적용된 단일 전략"이다
- `symbol` + `module_config` + `intervals` + `min_rr_ratio`의 조합이 하나의 완전한 전략을 구성
- EventDispatcher가 `self._strategies[candle.symbol]`로 접근하여 `strategy.analyze()` / `strategy.should_exit()` 호출

**결론:** 이미 존재하며, 잘 작동하고 있다.

### 3.2 ComposableStrategy + StrategyModuleConfig가 이미 이 역할을 하는지

**Yes.**

| 필요 기능 | 현재 구현 | 충족 여부 |
|-----------|-----------|-----------|
| 서브 전략 조합 | StrategyModuleConfig (4 determiners) | Yes |
| 심볼별 인스턴스 | TradingEngine.strategies dict | Yes |
| 서브 전략 교체 | module_config_builder.py registry | Yes |
| 오케스트레이션 | ComposableStrategy.analyze() | Yes |
| 버퍼 관리 | BaseStrategy 상속 | Yes |

### 3.3 전략 Validation (필수 서브 전략 구비 확인)

**현재 상태:**
- `StrategyModuleConfig`가 frozen dataclass이므로, 4개 필드 모두 필수
- 생성 시 누락하면 TypeError 발생 (Python dataclass 기본 동작)
- 추가적인 validation 로직은 없음

**판정:**
- frozen dataclass의 필수 필드가 이미 "필수 서브 전략 구비" 검증을 제공
- 런타임 타입 검증 (isinstance check)은 Hot Path 가이드라인에 따라 불필요
- Cold Path (factory/builder)에서 추가 검증이 필요하다면, `build_module_config()` 반환 전에 assertion 추가 가능

---

## 4. 리팩토링 필요성 판단

### 결론: 부분적 리팩토링 권장 (전면 재설계 불필요)

**하지 말아야 할 것:**
- "SubStrategy" ABC 도입 -- 현재 Determiner가 이미 그 역할
- "HighLevelStrategy" 새 클래스 도입 -- ComposableStrategy가 이미 그 역할
- BaseStrategy 분할 -- 현재 동작에 문제 없으며 복잡도 대비 이득 미미

**해야 할 것 (3가지 타겟팅 개선):**

### Task 1: PriceContext에서 ICT 특화 필드 제거 → extras dict 전환

**변경 파일:**
- `src/pricing/base.py` - PriceContext 수정
- `src/strategies/composable.py` - PriceContext 생성 부분 수정
- `src/pricing/stop_loss/zone_based.py` - extras에서 zone 접근
- `src/pricing/take_profit/displacement.py` - extras에서 displacement 접근

**변경 내용:**
```python
@dataclass(frozen=True)
class PriceContext:
    entry_price: float
    side: str
    symbol: str
    timestamp: int
    extras: Dict[str, Any] = field(default_factory=dict)  # Strategy-specific data

    # Convenience accessors for common patterns (optional, zero-cost)
    def get_zone(self, key: str) -> Optional[Tuple[float, float]]:
        return self.extras.get(key)
```

**장점:**
- 새 전략 추가 시 PriceContext 수정 불필요 (OCP 준수)
- 기존 SL/TP determiner는 `context.extras.get("fvg_zone")` 형태로 접근
- Hot path 영향: dict lookup은 O(1), 성능 영향 무시 가능

### Task 2: `_`-prefixed metadata transport → typed EntryDecision 확장

**변경 파일:**
- `src/entry/base.py` - EntryDecision에 typed optional fields 추가
- `src/strategies/composable.py` - metadata 추출 대신 typed field 접근
- `src/entry/ict_entry.py` - metadata 대신 typed field 설정

**변경 내용:**
```python
@dataclass(frozen=True)
class EntryDecision:
    signal_type: SignalType
    entry_price: float
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)  # Public metadata only
    # Typed transport for downstream determiners (replaces _-prefixed metadata)
    price_extras: Dict[str, Any] = field(default_factory=dict)  # For PriceContext.extras
```

ComposableStrategy에서:
```python
# Before (implicit):
fvg_zone = decision.metadata.get("_fvg_zone")

# After (explicit):
price_context = PriceContext.from_strategy(
    entry_price=decision.entry_price,
    side=side,
    symbol=self.symbol,
    extras=decision.price_extras,  # Direct passthrough
)
```

ICTEntryDeterminer에서:
```python
# Before:
metadata = {"_fvg_zone": fvg_zone, "_ob_zone": ob_zone, ...}

# After:
price_extras = {"fvg_zone": fvg_zone, "ob_zone": ob_zone, "displacement_size": displacement_size}
metadata = {"trend": trend, "zone": "discount", ...}  # Public only
```

**장점:**
- `_` prefix 컨벤션 제거 -- 명시적 분리
- ComposableStrategy가 key를 하드코딩할 필요 없음 (passthrough)
- 타입 힌팅 개선 (`price_extras: Dict[str, Any]`는 여전히 dynamic이지만, metadata와 분리되어 의미가 명확)

### Task 3: BaseStrategy에서 미사용 price delegation 정리

**변경 파일:**
- `src/strategies/base.py` - `_create_price_config()`, `_create_price_context()`, `calculate_take_profit()`, `calculate_stop_loss()`, `_price_config` 필드 제거 또는 deprecated 마킹

**변경 내용:**
- `_price_config` 초기화를 `__init__`에서 제거 (ComposableStrategy가 유일한 서브클래스이며, 자체 price config를 사용)
- `calculate_take_profit()`/`calculate_stop_loss()`를 abstract에서 제거하고 BaseStrategy에서도 제거
- 관련 docstring/examples 업데이트

**주의사항:**
- 테스트에서 BaseStrategy를 직접 서브클래싱하는 mock이 있을 수 있음 -- 확인 필요
- `PriceDeterminerConfig` 클래스 자체는 유지 (StrategyModuleConfig가 개별 determiner로 이를 대체했지만, 참조가 있을 수 있음)

**판정:** LOW priority -- 코드 정리 성격이며, 기능/성능에 영향 없음

---

## 5. Trade-off 분석

### 추상화 수준 증가 vs 복잡성 증가

| 옵션 | 추상화 수준 | 복잡성 | 권장 |
|------|------------|--------|------|
| A: 현재 유지 (No change) | 현재 | 현재 | 가능하지만 기술 부채 누적 |
| B: 타겟팅 3개 개선 (권장) | 약간 개선 | 거의 동일 | **권장** |
| C: SubStrategy + HighLevelStrategy 도입 | 높음 | 크게 증가 | 비권장 |

### 유연성 향상 vs 런타임 성능 영향

**Task 1 (PriceContext extras):**
- 성능 영향: dict.get() → dict.get() (동일, O(1))
- frozen dataclass field 수 감소 (3개 Optional → 1개 dict)
- 메모리: 약간 감소 (빈 extras dict vs 3개 None 필드)

**Task 2 (EntryDecision price_extras):**
- 성능 영향: dict access 패턴 동일
- ComposableStrategy.analyze()에서 key-by-key 추출 → dict passthrough로 변경 시 약간 빠름
- Hot path: candle당 1회 호출, 영향 무시 가능

**Task 3 (BaseStrategy 정리):**
- 성능 영향: `__init__`에서 불필요한 `PriceDeterminerConfig` 생성 제거
- Cold path (초기화 시 1회)이므로 실질적 영향 없음

### 개발 편의성 vs 기존 코드 호환성

- Task 1, 2: SL/TP determiner 구현체 (4개 파일) 수정 필요하지만, 변경량 소규모
- Task 3: 테스트 코드 의존성 확인 필요
- 전체적으로 **하위 호환성을 유지하면서** 점진적 개선 가능

---

## 6. Hot Path 성능 영향 분석

CLAUDE.md의 실시간 트레이딩 가이드라인 준수 확인:

| 가이드라인 | 현재 준수 | 변경 후 준수 | 비고 |
|-----------|-----------|-------------|------|
| Hot Path에서 Pydantic 금지 | Yes (frozen dataclass) | Yes | 변경 없음 |
| datetime 파싱 지연 평가 | Yes (int timestamp) | Yes | 변경 없음 |
| Lock-free 자료구조 | Yes (deque, asyncio.Queue) | Yes | 변경 없음 |
| 비동기 로깅 | Yes | Yes | 변경 없음 |
| 틱 처리 지연 < 1ms (p99) | 영향 없음 | 영향 없음 | dict lookup O(1) 유지 |

**결론:** 제안된 3개 Task 모두 Hot Path 성능에 영향 없음.

---

## Work Objectives

### Core Objective
PriceContext와 metadata transport의 ICT 커플링을 제거하여, 향후 새로운 전략 추가 시 기존 generic base 코드 수정 없이 확장 가능하게 만든다.

### Deliverables
1. PriceContext에서 ICT 특화 필드 제거 + extras dict 도입
2. EntryDecision에 price_extras 필드 추가하여 metadata transport 명시적 분리
3. (Optional) BaseStrategy에서 미사용 price delegation 코드 정리

### Definition of Done
- 모든 기존 테스트 통과
- PriceContext에 전략 특화 필드 없음
- `_`-prefixed metadata 패턴 제거
- Hot path 성능 가이드라인 준수 (frozen dataclass, int timestamp 유지)

---

## Must Have / Must NOT Have

### Must Have
- PriceContext.extras: Dict[str, Any] 필드 (전략 특화 데이터 전달)
- EntryDecision.price_extras: Dict[str, Any] 필드 (metadata transport 분리)
- 기존 모든 테스트 통과
- frozen dataclass 패턴 유지 (Hot path compliance)

### Must NOT Have
- "SubStrategy" 또는 "HighLevelStrategy" 같은 새로운 추상 클래스
- 런타임 isinstance 검증 추가 (Hot path에서 금지)
- Pydantic 모델 도입 (Hot path에서 금지)
- PriceContext에 ICT 외 전략의 필드 추가 (extras로 해결)

---

## Task Flow and Dependencies

```
Task 1: PriceContext extras 전환
    ↓ (Task 2가 Task 1에 의존: price_extras → PriceContext.extras passthrough)
Task 2: EntryDecision price_extras 도입
    ↓ (독립)
Task 3: BaseStrategy price delegation 정리 (optional, 독립)
```

---

## Detailed TODOs

### Task 1: PriceContext extras 전환
**Priority: HIGH**
**Files:**
- `src/pricing/base.py` - PriceContext 수정
- `src/pricing/stop_loss/zone_based.py` - extras에서 zone 접근
- `src/pricing/take_profit/displacement.py` - extras에서 displacement 접근
- `src/strategies/composable.py` - PriceContext.from_strategy() 호출 수정
- `src/strategies/base.py` - _create_price_context() 수정
- `tests/pricing/test_zone_based_sl.py` - PriceContext.from_strategy() 키워드 인자를 extras로 변경 (Critic 지적)

**Acceptance Criteria:**
- [ ] PriceContext에서 fvg_zone, ob_zone, displacement_size 필드 제거
- [ ] PriceContext에 extras: Dict[str, Any] 필드 추가 (default_factory=dict)
- [ ] PriceContext.from_strategy()에 extras 파라미터 추가
- [ ] ZoneBasedStopLoss가 context.extras.get("fvg_zone") / context.extras.get("ob_zone") 사용
- [ ] DisplacementTakeProfit가 context.extras.get("displacement_size") 사용
- [ ] ComposableStrategy.analyze()에서 extras dict 구성하여 PriceContext에 전달
- [ ] 모든 기존 테스트 통과

### Task 2: EntryDecision price_extras 도입
**Priority: HIGH** (Task 1 완료 후)
**Files:**
- `src/entry/base.py` - EntryDecision에 price_extras 필드 추가
- `src/entry/ict_entry.py` - _-prefixed keys를 price_extras로 이동
- `src/entry/sma_entry.py` - 변경 불필요 (price_extras 비어있음)
- `src/entry/always_entry.py` - 변경 불필요
- `src/strategies/composable.py` - metadata에서 key 추출 대신 decision.price_extras passthrough

**Acceptance Criteria:**
- [ ] EntryDecision에 price_extras: Dict[str, Any] 필드 추가
- [ ] ICTEntryDeterminer에서 _fvg_zone, _ob_zone, _displacement_size를 price_extras로 이동
- [ ] ICTEntryDeterminer의 metadata에서 _-prefixed keys 제거 (public metadata만 남김)
- [ ] ComposableStrategy.analyze()에서 decision.price_extras를 PriceContext.extras로 직접 전달
- [ ] ComposableStrategy.analyze()에서 하드코딩된 "_fvg_zone", "_ob_zone", "_displacement_size" key 추출 코드 제거
- [ ] public metadata stripping 로직 (`k.startswith("_")` 필터) 제거 (더 이상 필요 없음)
- [ ] 모든 기존 테스트 통과

### Task 3: BaseStrategy price delegation 정리
**Priority: LOW** (독립 실행 가능)
**Files:**
- `src/strategies/base.py` - price delegation 코드 제거/정리
- 관련 테스트 파일 확인 및 수정

**Acceptance Criteria:**
- [ ] BaseStrategy.__init__에서 _price_config 초기화 제거
- [ ] _create_price_config(), _create_price_context() 메서드 제거
- [ ] calculate_take_profit(), calculate_stop_loss() concrete 메서드 제거 (주의: abstract가 아닌 concrete 메서드임)
- [ ] ComposableStrategy._create_price_config() 오버라이드 제거 (base에서 제거되므로)
- [ ] PriceDeterminerConfig 참조 정리 (StrategyModuleConfig로 대체 완료 확인)
- [ ] 테스트에서 BaseStrategy 직접 서브클래싱하는 mock 확인 및 수정
- [ ] 모든 기존 테스트 통과

---

## Commit Strategy

```
commit 1: "refactor: replace ICT-specific PriceContext fields with generic extras dict"
  - Task 1 완료

commit 2: "refactor: introduce EntryDecision.price_extras to replace _-prefixed metadata transport"
  - Task 2 완료

commit 3 (optional): "refactor: remove orphaned price delegation from BaseStrategy"
  - Task 3 완료
```

---

## Success Criteria

1. **확장성**: 새로운 전략 추가 시 PriceContext, EntryDecision, ComposableStrategy 수정 불필요
2. **타입 안전성**: `_`-prefixed 암묵적 metadata 패턴 제거, 의미 명확한 필드 분리
3. **성능 유지**: Hot path 가이드라인 100% 준수 (frozen dataclass, int timestamp, no Pydantic)
4. **하위 호환성**: 모든 기존 테스트 통과, 외부 인터페이스 (EventDispatcher, TradingEngine) 변경 없음
5. **코드 간결성**: ComposableStrategy.analyze()에서 하드코딩된 metadata key 추출 로직 제거

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| 테스트에서 _-prefixed metadata에 의존 | MEDIUM | LOW | 테스트 수정 (단순 key 변경) |
| BaseStrategy 직접 서브클래싱 mock 존재 | LOW | MEDIUM | Task 3 전 테스트 그레핑으로 확인 |
| extras dict의 key 오타 | MEDIUM | LOW | 상수 정의 또는 docstring convention |
| PriceContext.extras 타입 안전성 부재 | LOW | LOW | 현재 _-prefixed보다는 개선. 향후 TypedDict 가능 |

---

## Appendix: "하지 않기로 한 것"과 그 이유

### A. SubStrategy ABC 도입
**이유:** 4개 Determiner의 인터페이스가 의도적으로 다르다 (analyze→EntryDecision, calculate_stop_loss→float, should_exit→Signal). 통합 ABC는 `Any` 타입 남발로 이어지며, 현재 Determiner ABC가 이미 충분한 추상화를 제공.

### B. HighLevelStrategy 클래스 도입
**이유:** ComposableStrategy가 이미 "고수준 전략" 역할을 하고 있다. 새 클래스를 도입하면 ComposableStrategy와 역할이 중복되며, TradingEngine/EventDispatcher의 consumer 코드도 변경 필요.

### C. Strategy Validation Layer
**이유:** StrategyModuleConfig가 frozen dataclass이므로 4개 필드 모두 필수. Python의 dataclass 생성자가 이미 validation을 제공. Hot path에 런타임 isinstance 검증을 추가하는 것은 가이드라인 위반.

### D. BaseStrategy 분할 (BufferManager + PriceCalculator)
**이유:** 현재 ComposableStrategy가 유일한 서브클래스이며, price delegation은 사실상 사용되지 않음. 분할 대신 미사용 코드 제거(Task 3)가 더 실용적.
