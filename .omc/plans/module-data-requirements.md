# Plan: Module Data Requirements Interface (v2 — Critic Feedback Applied)

## Goal
각 전략 모듈(Entry/Exit/SL/TP Determiner)이 자신의 데이터 의존성(timeframes, backfill 요구량)을 스스로 선언하는 인터페이스를 설계하여, TradingEngine이 이를 기반으로 데이터를 준비하도록 한다.

## Problem Statement
현재 데이터 요구사항은 `module_config_builder.py`에서 외부적/명시적으로 선언된다:
- ICT: `intervals = [ltf, mtf, htf]` (builder가 하드코딩)
- SMA/AlwaysSignal: `intervals = None` (단일 타임프레임 기본값)
- backfill limit은 전역 설정 1개 (`config.backfill_limit`, 기본 100)
- `ICTEntryDeterminer.min_periods = 50`은 내부에서만 체크, 엔진에 노출 안 됨

**문제점:**
1. Determiner의 실제 데이터 니즈와 builder의 선언이 분리되어 동기화 실패 위험
2. 새 전략 추가 시 builder 함수도 수정해야 하는 이중 작업
3. backfill량이 전역 고정이라 모듈별 최적화 불가능
4. Determiner가 어떤 데이터를 필요로 하는지 런타임에 알 수 없음

## Architecture Analysis

### Current Flow (AS-IS)
```
module_config_builder.py          TradingEngine
  _build_ict_config()  ───────►  intervals = ['5m','1h','4h']
     hardcoded intervals          backfill_limit = 100 (global)
     hardcoded backfill           │
                                  ▼
                            for interval in strategy.intervals:
                              fetch(limit=100)  # same for all
```

### Proposed Flow (TO-BE)
```
ICTEntryDeterminer.requirements ──┐
ICTExitDeterminer.requirements  ──┤
ZoneBasedStopLoss.requirements  ──┼──► StrategyModuleConfig.aggregated_requirements
DisplacementTP.requirements     ──┘        │
                                           ▼
                                    ModuleRequirements(
                                      timeframes={'5m','1h','4h'},
                                      min_candles={'5m':200, '1h':50, '4h':50}
                                    )
                                           │
                                           ▼
                                    BaseStrategy.data_requirements (exposed)
                                           │
                                           ▼
                                    TradingEngine uses per-interval
                                    backfill limits
```

## Acceptance Criteria
1. `ModuleRequirements` dataclass 정의 완료 (truly immutable)
2. 4개 ABC 각각에 `requirements` 프로퍼티 추가 (기본값: 빈 요구사항)
3. `StrategyModuleConfig`에서 4개 모듈의 요구사항을 자동 집계
4. `BaseStrategy`에 `data_requirements` property 추가 (TradingEngine 통합 인터페이스)
5. `TradingEngine.initialize_strategy_with_backfill()`이 집계된 요구사항 사용
6. `module_config_builder.py`의 intervals_override가 집계 결과로 대체 가능
7. 기존 3개 전략(ICT, SMA, AlwaysSignal) 모든 테스트 통과
8. Hot path (`analyze()`, `should_exit()`) 성능 변화 없음
9. `buffer_size >= max(min_candles)` 검증 포함

## Implementation Steps

### Step 1: `ModuleRequirements` dataclass 정의
**File:** `src/models/module_requirements.py` (신규)

> **Critic Fix #3:** `src/strategies/` 대신 `src/models/`에 배치.
> 이유: entry/exit/pricing ABC들은 하위 레이어이고 strategies는 상위 레이어.
> `src/models/`는 공유 타입 레이어로서 모든 레이어가 의존할 수 있음.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import FrozenSet, Mapping


@dataclass(frozen=True)
class ModuleRequirements:
    """
    Immutable declaration of a module's data dependencies.

    Cold-path only: created once at init, never in hot path.
    frozen=True for attribute immutability, MappingProxyType for dict immutability.
    """
    timeframes: FrozenSet[str] = field(default_factory=frozenset)
    min_candles: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    # min_candles: timeframe → minimum candle count needed
    # e.g., {"5m": 200, "1h": 50, "4h": 50}

    def __post_init__(self) -> None:
        """Validate and freeze min_candles dict."""
        # Critic Fix #1: Ensure min_candles is truly immutable via MappingProxyType
        if isinstance(self.min_candles, dict):
            object.__setattr__(self, 'min_candles', MappingProxyType(self.min_candles))

        # Critic Minor Fix #4: Validate min_candles keys ⊆ timeframes
        if self.min_candles and self.timeframes:
            invalid_keys = set(self.min_candles.keys()) - self.timeframes
            if invalid_keys:
                raise ValueError(
                    f"min_candles keys {invalid_keys} not in timeframes {self.timeframes}"
                )

    @staticmethod
    def empty() -> ModuleRequirements:
        """No data requirements (default for simple determiners)."""
        return ModuleRequirements()

    @staticmethod
    def merge(*requirements: ModuleRequirements) -> ModuleRequirements:
        """
        Merge multiple requirements: union timeframes, max min_candles per tf.

        Used by StrategyModuleConfig to aggregate all 4 determiners' needs.
        """
        all_timeframes: set[str] = set()
        all_min_candles: dict[str, int] = {}

        for req in requirements:
            all_timeframes |= req.timeframes
            for tf, count in req.min_candles.items():
                all_min_candles[tf] = max(all_min_candles.get(tf, 0), count)

        return ModuleRequirements(
            timeframes=frozenset(all_timeframes),
            min_candles=all_min_candles,  # __post_init__ wraps in MappingProxyType
        )
```

**Critic Fix #1 해결:** `MappingProxyType`으로 `min_candles` 진정한 불변성 보장.
```python
req = ModuleRequirements(timeframes=frozenset({"5m"}), min_candles={"5m": 200})
req.min_candles["5m"] = 9999  # TypeError: 'mappingproxy' object does not support item assignment
```

**Critic Minor #4 해결:** `__post_init__`에서 `min_candles` 키가 `timeframes`에 포함되는지 검증.

### Step 2: 각 Determiner ABC에 `requirements` 프로퍼티 추가

> **Critic Fix #3 적용:** import 경로가 `src.models.module_requirements`로 변경됨.
> `src/models/`는 `entry/`, `exit/`, `pricing/` 모두에서 이미 import하는 공유 레이어.
> (예: `from src.models.candle import Candle`, `from src.models.signal import Signal`)

**File:** `src/entry/base.py` — `EntryDeterminer`
```python
from src.models.module_requirements import ModuleRequirements

class EntryDeterminer(ABC):
    @abstractmethod
    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def requirements(self) -> ModuleRequirements:
        """Data requirements for this determiner. Override to declare needs."""
        return ModuleRequirements.empty()
```

**File:** `src/exit/base.py` — `ExitDeterminer`
```python
from src.models.module_requirements import ModuleRequirements

class ExitDeterminer(ABC):
    @abstractmethod
    def should_exit(self, context: ExitContext) -> Optional[Signal]:
        pass

    @property
    def requirements(self) -> ModuleRequirements:
        """Data requirements for this determiner. Override to declare needs."""
        return ModuleRequirements.empty()
```

**File:** `src/pricing/base.py` — `StopLossDeterminer`, `TakeProfitDeterminer`
```python
from src.models.module_requirements import ModuleRequirements

class StopLossDeterminer(ABC):
    @abstractmethod
    def calculate_stop_loss(self, context: PriceContext) -> float:
        pass

    @property
    def requirements(self) -> ModuleRequirements:
        """Data requirements for this determiner. Override to declare needs."""
        return ModuleRequirements.empty()

class TakeProfitDeterminer(ABC):
    @abstractmethod
    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        pass

    @property
    def requirements(self) -> ModuleRequirements:
        """Data requirements for this determiner. Override to declare needs."""
        return ModuleRequirements.empty()
```

**Design Decision: 왜 `@property`이고 `abstractmethod`가 아닌가?**
- `abstractmethod`로 하면 기존 모든 구현체가 강제 수정 필요 → 최소 변경 원칙 위반
- concrete property with default (`empty()`)로 하면 기존 구현체 변경 0
- 데이터 요구사항이 있는 모듈만 override하면 됨
- Hot path 영향 없음: `requirements`는 init 시에만 호출

### Step 3: 기존 Determiner에 `requirements` override 추가

**File:** `src/entry/ict_entry.py` — `ICTEntryDeterminer`
```python
from src.models.module_requirements import ModuleRequirements

@property
def requirements(self) -> ModuleRequirements:
    return ModuleRequirements(
        timeframes=frozenset({self.ltf_interval, self.mtf_interval, self.htf_interval}),
        min_candles={
            self.ltf_interval: self.min_periods,  # 50+ (swing_lookback * 4)
            self.mtf_interval: 50,   # market structure analysis
            self.htf_interval: 50,   # trend detection
        },
    )
```

**File:** `src/exit/ict_exit.py` — `ICTExitDeterminer`

> **Critic Minor #1 Fix:** mtf_interval min_candles를 50으로 수정.
> 근거: `ict_exit.py:350`에서 `len(mtf_buffer) < 50` 체크 확인됨.

```python
from src.models.module_requirements import ModuleRequirements

@property
def requirements(self) -> ModuleRequirements:
    return ModuleRequirements(
        timeframes=frozenset({self.mtf_interval, self.htf_interval}),
        min_candles={
            self.mtf_interval: 50,   # _check_indicator_based_exit: len(mtf_buffer) < 50
            self.htf_interval: 50,   # trend confirmation
        },
    )
```

**다른 모듈 (SMAEntryDeterminer, AlwaysEntryDeterminer, PercentageStopLoss, RiskRewardTakeProfit, ZoneBasedStopLoss, DisplacementTakeProfit, NullExitDeterminer):**
- **변경 없음** — 기본 `empty()` 반환이 올바른 동작
- SMA/Always는 단일 타임프레임만 사용하며, 이는 config의 `default_interval`로 결정됨
- ZoneBasedStopLoss/DisplacementTakeProfit은 `PriceContext.extras`에서 데이터를 받으므로 자체 timeframe 요구 없음

### Step 4: `StrategyModuleConfig`에 집계 기능 추가

**File:** `src/pricing/base.py`

```python
from src.models.module_requirements import ModuleRequirements

@dataclass(frozen=True)
class StrategyModuleConfig:
    entry_determiner: EntryDeterminer
    stop_loss_determiner: StopLossDeterminer
    take_profit_determiner: TakeProfitDeterminer
    exit_determiner: ExitDeterminer

    @property
    def aggregated_requirements(self) -> ModuleRequirements:
        """Merge all 4 determiners' data requirements."""
        return ModuleRequirements.merge(
            self.entry_determiner.requirements,
            self.stop_loss_determiner.requirements,
            self.take_profit_determiner.requirements,
            self.exit_determiner.requirements,
        )
```

### Step 5: `BaseStrategy`에 `data_requirements` property 추가

> **Critic Fix #4:** TradingEngine에서 isinstance 체크 대신 BaseStrategy에 통합 인터페이스 제공.

**File:** `src/strategies/base.py`

```python
from src.models.module_requirements import ModuleRequirements

class BaseStrategy(ABC):
    # ... existing code ...

    @property
    def data_requirements(self) -> ModuleRequirements:
        """
        Aggregated data requirements from all modules.

        Default: empty requirements. ComposableStrategy overrides
        to aggregate from StrategyModuleConfig.
        """
        return ModuleRequirements.empty()
```

**File:** `src/strategies/composable.py`

```python
from src.models.module_requirements import ModuleRequirements

class ComposableStrategy(BaseStrategy):
    # ... existing code ...

    @property
    def data_requirements(self) -> ModuleRequirements:
        """Aggregate requirements from all 4 determiner modules."""
        return self.module_config.aggregated_requirements
```

이로써 TradingEngine은 `strategy.data_requirements`만 호출하면 됨 — isinstance 불필요.

### Step 6: `module_config_builder.py` 리팩터

**변경 내용:** intervals_override를 집계된 요구사항에서 도출

> **Critic Fix #2:** `_interval_to_minutes()` 유틸리티 함수를 파일 내에 정의.

```python
# module_config_builder.py 상단에 추가

_INTERVAL_MULTIPLIERS = {"m": 1, "h": 60, "d": 1440, "w": 10080}

def _interval_to_minutes(interval: str) -> int:
    """Convert interval string to minutes for sorting. e.g., '5m'->5, '1h'->60, '4h'->240."""
    unit = interval[-1]
    value = int(interval[:-1])
    return value * _INTERVAL_MULTIPLIERS.get(unit, 1)
```

**각 builder 함수 변경 패턴 (ICT 예시):**

```python
def _build_ict_config(
    strategy_config: dict,
    exit_config: Optional[ExitConfig],
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    # Entry, SL, TP, Exit 생성 (기존과 동일)
    entry = ICTEntryDeterminer.from_config(strategy_config)
    sl = ZoneBasedStopLoss()
    tp = DisplacementTakeProfit()
    exit_det = ICTExitDeterminer(...)

    min_rr_ratio = strategy_config.get("rr_ratio", 2.0)

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    # NEW: Derive intervals from aggregated module requirements
    agg = module_config.aggregated_requirements
    if agg.timeframes:
        intervals = sorted(agg.timeframes, key=_interval_to_minutes)
    else:
        intervals = None

    return module_config, intervals, min_rr_ratio
```

SMA/AlwaysSignal builder도 동일 패턴 적용. `agg.timeframes`가 빈 frozenset이므로 `intervals = None` 반환 — 기존 동작과 동일.

> **Critic Minor #2 해결:** Phase 1/Phase 2 구분을 제거하고, 단일 구현으로 전환.
> ICT의 경우 `agg.timeframes == frozenset({'5m','1h','4h'})`이므로 기존 하드코딩 `['5m','1h','4h']`와 동일 결과.
> 단, 구현 후 기존 테스트 전체 통과를 필수 검증 단계로 포함.

### Step 7: `TradingEngine` backfill 최적화

**File:** `src/core/trading_engine.py` — `initialize_strategy_with_backfill()`

```python
async def initialize_strategy_with_backfill(self, default_limit: int = 100):
    # ... existing setup code ...

    for symbol, strategy in self.strategies.items():
        # Get per-interval requirements via BaseStrategy interface (no isinstance)
        requirements = strategy.data_requirements

        for interval in strategy.intervals:
            # Per-interval backfill: use declared min_candles or default
            limit = requirements.min_candles.get(interval, default_limit)
            candles = self.data_collector.get_historical_candles(
                symbol=symbol, interval=interval, limit=limit
            )
            strategy.initialize_with_historical_data(candles, interval=interval)
```

> **Critic Fix #4 완전 적용:** `isinstance` 체크 없이 `strategy.data_requirements` 호출.
> BaseStrategy.data_requirements가 기본 `empty()` 반환 → `min_candles.get(interval, default_limit)` = `default_limit` → 기존 동작과 동일.

### Step 8: `buffer_size` vs `min_candles` 검증

> **Critic Architect Q#3 해결:** buffer_size < min_candles일 때 backfill 데이터가 deque maxlen에 의해 잘림.

**File:** `src/strategies/composable.py` — `__init__` 내 검증 추가

```python
def __init__(self, symbol, config, module_config, intervals=None, min_rr_ratio=1.5):
    self.module_config = module_config
    self.min_rr_ratio = min_rr_ratio
    super().__init__(symbol, config, intervals)

    # Validate buffer_size accommodates all module requirements
    reqs = self.data_requirements
    if reqs.min_candles:
        max_needed = max(reqs.min_candles.values())
        if self.buffer_size < max_needed:
            self.logger.warning(
                "[%s] buffer_size=%d < max min_candles=%d. "
                "Backfilled data may be truncated. Consider increasing buffer_size.",
                symbol, self.buffer_size, max_needed,
            )
```

경고만 발생 (에러가 아님) — 기존 동작을 깨뜨리지 않으면서 개발자에게 알림.

### Step 9: 테스트

**기존 테스트 통과 확인:**
- `tests/` 디렉토리의 모든 기존 테스트가 수정 없이 통과해야 함
- 기본 `requirements` 반환값(`empty()`)이 기존 동작과 동일하므로 호환성 보장

**새 테스트 추가:**

1. `tests/test_module_requirements.py`:
   - `ModuleRequirements.empty()` — timeframes=frozenset(), min_candles=MappingProxyType({})
   - `ModuleRequirements.merge()` — union timeframes, max min_candles per tf
   - 빈 요구사항 merge 시 빈 결과
   - 단일 요구사항 merge 시 동일 결과
   - **Merge with overlapping timeframes, different min_candles** — max wins
   - **Immutability test:** `req.min_candles["5m"] = 9999` raises TypeError
   - **Validation test:** `min_candles` key not in timeframes raises ValueError

2. `tests/test_requirements_integration.py`:
   - `ICTEntryDeterminer.requirements` — 3 timeframes, correct min_candles
   - `ICTExitDeterminer.requirements` — 2 timeframes, mtf=50, htf=50
   - `StrategyModuleConfig.aggregated_requirements` — ICT 전략 집계 검증
   - SMA/AlwaysSignal의 `aggregated_requirements`가 빈 요구사항인지 검증
   - `ComposableStrategy.data_requirements` == `module_config.aggregated_requirements`
   - `BaseStrategy` 서브클래스의 기본 `data_requirements`가 `empty()`인지 검증
   - **TradingEngine backfill test:** per-interval limit이 실제로 사용되는지 검증 (mock)
   - **buffer_size warning test:** buffer_size < max_needed일 때 warning 로그 발생

## File Changes Summary

| File | Change Type | Lines Changed (est.) | Hot Path Impact |
|------|-------------|---------------------|-----------------|
| `src/models/module_requirements.py` | **NEW** | ~55 | None (cold path only) |
| `src/entry/base.py` | ADD import + property | +6 | None |
| `src/exit/base.py` | ADD import + property | +6 | None |
| `src/pricing/base.py` | ADD import + property x2 + aggregation | +18 | None |
| `src/entry/ict_entry.py` | ADD import + property override | +13 | None |
| `src/exit/ict_exit.py` | ADD import + property override | +12 | None |
| `src/strategies/base.py` | ADD import + property | +8 | None |
| `src/strategies/composable.py` | ADD import + property + validation | +15 | None |
| `src/strategies/module_config_builder.py` | ADD utility + MODIFY interval derivation | ~25 | None (init only) |
| `src/core/trading_engine.py` | MODIFY backfill logic | ~10 | None (init only) |
| `tests/test_module_requirements.py` | **NEW** | ~80 | N/A |
| `tests/test_requirements_integration.py` | **NEW** | ~100 | N/A |

**Total:** 3 new files, 7 modified files, ~348 lines
**기존 모듈 변경 최소화:** SMA, AlwaysSignal, PercentageStopLoss, RiskRewardTakeProfit, ZoneBasedStopLoss, DisplacementTakeProfit, NullExitDeterminer — **변경 0줄**

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Import layer violation | ~~Medium~~ **Eliminated** | High | ModuleRequirements를 `src/models/`에 배치 → 기존 import 방향과 동일 |
| frozen dataclass 가변성 | ~~Medium~~ **Eliminated** | High | MappingProxyType으로 min_candles 진정한 불변성 보장 |
| Hot path regression | Low | Critical | requirements는 init 시에만 호출, analyze/should_exit에서 호출하지 않음 |
| 기존 테스트 실패 | Low | Medium | 모든 ABC 변경은 additive (기본값 제공), breaking change 없음 |
| buffer_size < min_candles | Medium | Medium | ComposableStrategy.__init__에서 warning 발생, 개발자 알림 |
| _interval_to_minutes 파싱 오류 | Low | Low | 단순 문자열 파싱, 테스트 커버리지 포함 |

## Verification Steps
1. `python -m pytest tests/ -v` — 전체 테스트 스위트 통과
2. 새 테스트 파일 통과 확인
3. `ICTEntryDeterminer.requirements.timeframes == frozenset({'5m','1h','4h'})` 확인
4. `StrategyModuleConfig.aggregated_requirements` 집계 결과 검증
5. `req.min_candles["5m"] = 9999` → TypeError 확인 (불변성)
6. Hot path 벤치마크: `analyze()` 호출 시 requirements 접근 없음 확인
7. `ModuleRequirements(timeframes=frozenset({"5m"}), min_candles={"1h": 100})` → ValueError

## Implementation Order
1. `src/models/module_requirements.py` (독립, 의존성 없음)
2. 4개 ABC에 `requirements` property 추가
3. `StrategyModuleConfig.aggregated_requirements` 추가
4. ICT determiner에 override 추가
5. `BaseStrategy.data_requirements` + `ComposableStrategy` override
6. `module_config_builder.py` 리팩터 (intervals from requirements)
7. `TradingEngine` backfill 최적화
8. `ComposableStrategy` buffer_size 검증
9. 테스트 작성 및 실행

## Critic Feedback Tracking (v1 → v2)

| Issue | Status | Resolution |
|-------|--------|------------|
| **Critical #1:** frozen dataclass mutable Dict | ✅ Fixed | MappingProxyType + __post_init__ 래핑 |
| **Critical #2:** _interval_to_minutes 미존재 | ✅ Fixed | module_config_builder.py 내 유틸리티 함수 정의 |
| **Critical #3:** Import layer violation | ✅ Fixed | src/models/module_requirements.py로 이동 |
| **Critical #4:** isinstance check fragile | ✅ Fixed | BaseStrategy.data_requirements 통합 인터페이스 |
| **Minor #1:** ICTExit min_candles=20 → 50 | ✅ Fixed | mtf_interval: 50 (ict_exit.py:350 근거) |
| **Minor #2:** Phase 1/2 미정의 | ✅ Fixed | 단일 구현으로 전환, assert 제거 |
| **Minor #3:** Test coverage gaps | ✅ Fixed | 8개 추가 테스트 케이스 명시 |
| **Minor #4:** No __post_init__ validation | ✅ Fixed | min_candles keys ⊆ timeframes 검증 |
| **Arch Q#1:** ModuleRequirements 위치 | ✅ Resolved | src/models/ (공유 타입 레이어) |
| **Arch Q#2:** interval parsing utility | ✅ Resolved | module_config_builder.py 내 _interval_to_minutes 정의 |
| **Arch Q#3:** buffer_size vs min_candles | ✅ Resolved | ComposableStrategy.__init__ warning + 테스트 |
