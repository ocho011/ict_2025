# GitHub Issues Integration Roadmap

## Executive Summary

7개의 오픈 이슈를 3개의 논리적 Phase로 구조화한 구현 로드맵입니다.

**핵심 인사이트:**
- **Phase 1 (Critical Fixes)**: 즉시 해결 가능한 안정성 이슈 (2일)
- **Phase 2 (Architecture)**: 핵심 구조 개선 - 순차적 의존성 (10일)
- **Phase 3 (Features)**: 기능 확장 및 성능 최적화 (8일)

**총 예상 기간**: 20일 (버퍼 포함 26일)

---

## Phase 1: Critical Fixes & Stability (2 days)

### Goal
시스템 안정성 확보 및 명백한 버그 수정

### Issues

#### Issue #22: SIGINT Fix (P0 - Critical)
**Problem**: Ctrl+C가 initialize() 단계에서 무시됨

**Solution**:
```python
# src/main.py
def signal_handler(_sig, _frame):
    if bot._stop_event:
        bot._stop_event.set()
    else:
        raise KeyboardInterrupt  # NEW: 초기화 중 즉시 종료
```

**Tasks**:
- [ ] Modify `signal_handler` in `main.py`
- [ ] Add `else` branch with `raise KeyboardInterrupt`
- [ ] Test: Ctrl+C during `initialize()` exits immediately
- [ ] Test: Ctrl+C during `run()` triggers graceful shutdown

**Impact**: 🔴 High | **Complexity**: 🟢 Low | **Risk**: 🟢 Low
**Estimate**: 1-2 hours

---

#### Issue #23: Task Management (P1 - High)
**Problem**: asyncio 태스크가 명시적으로 취소되지 않아 zombie task 경고 발생

**Solution**:
```python
# src/main.py - TradingBot.run()
stop_signal_task = asyncio.create_task(self._stop_event.wait())
try:
    done, pending = await asyncio.wait([engine_task, stop_signal_task], ...)
finally:
    if not stop_signal_task.done():
        stop_signal_task.cancel()
```

**Tasks**:
- [ ] Extract `stop_signal_task` variable in `TradingBot.run()`
- [ ] Implement `finally` block with explicit task cancellation
- [ ] Test: No "Task was destroyed but it is pending" warnings
- [ ] Test: Clean shutdown with multiple concurrent tasks

**Impact**: 🟡 Medium | **Complexity**: 🟢 Low | **Risk**: 🟢 Low
**Estimate**: 2-3 hours

---

#### Issue #26: Backfill Logic Fix (P0 - Critical)
**Problem**: `initialize_strategy_with_backfill`이 `DataCollector.intervals` 대신 `Strategy.intervals`를 사용해야 함

**Solution**:
```python
# AS-IS (Wrong)
for interval in self.data_collector.intervals:  # 시스템 전체 interval
    # API Call

# TO-BE (Correct)
for interval in strategy.intervals:  # 해당 전략의 interval만
    # API Call
```

**Tasks**:
- [ ] Change loop in `initialize_strategy_with_backfill` from `self.data_collector.intervals` to `strategy.intervals`
- [ ] Add compatibility check for single-interval strategies
- [ ] Test: MTF strategy receives only configured intervals
- [ ] Test: Single-interval strategies still work correctly

**Impact**: 🔴 High | **Complexity**: 🟢 Low | **Risk**: 🟡 Medium
**Estimate**: 3-4 hours

---

### Phase 1 Exit Criteria
- ✅ All unit tests pass
- ✅ Manual Ctrl+C test successful during both phases
- ✅ No asyncio warnings in logs
- ✅ MTF strategies initialize with correct intervals only

---

## Phase 2: Architectural Foundation (10 days)

### Goal
핵심 데이터 구조 및 시그널 아키텍처 현대화

**Dependencies**: Sequential execution required (#27 → #25)

---

### Issue #27: Buffer Structure Unification (P0 - Foundational)
**Problem**: `BaseStrategy`와 `MultiTimeframeStrategy`가 버퍼 관리를 이원화하여 중복 및 혼선 발생

**Solution**: 모든 전략이 `Dict[str, deque]` 구조 사용
```python
class BaseStrategy(ABC):
    def __init__(self, symbol: str, config: dict, intervals: List[str] = None):
        self.intervals = intervals or [config.get('interval', '1m')]
        self.buffers: Dict[str, deque] = {
            interval: deque(maxlen=self.buffer_size)
            for interval in self.intervals
        }

    def update_buffer(self, candle: Candle) -> None:
        if candle.interval in self.buffers:
            self.buffers[candle.interval].append(candle)
```

**Tasks**:
- [ ] **`src/strategies/base.py`**: Remove `self.candle_buffer`, add `self.buffers: Dict[str, deque]`
- [ ] Update `update_buffer()`, `get_latest_candles()`, `is_buffer_ready()` methods
- [ ] **`src/strategies/multi_timeframe.py`**: Remove duplicate buffer creation, use `super().__init__()`
- [ ] **`src/core/trading_engine.py`**: Update `_on_candle_closed()` to use single interface
- [ ] Add backward compatibility property: `@property candle_buffer → self.buffers[self.intervals[0]]`
- [ ] Update all unit tests to use `Dict[str, deque]` structure
- [ ] Test: Single-interval strategies work with `buffers['1m']`
- [ ] Test: MTF strategies have isolated buffers per interval
- [ ] Test: TradingEngine routes candles correctly

**Impact**: 🔴 High (Foundational) | **Complexity**: 🟡 Medium | **Risk**: 🔴 High
**Estimate**: 2-3 days

**Risk Mitigation**:
- Phased migration with compatibility layer
- Extensive regression testing
- Deprecation warnings for old interface

---

### Issue #25: Entry/Exit Signal Separation (P1 - Foundational)
**Problem**: 현재 진입 시그널에 청산가가 포함되어 동적 청산 로직 구현 어려움

**Solution**: 진입(Entry)과 청산(Exit)을 독립적인 시그널로 분리
```python
class SignalType(Enum):
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"

@dataclass
class Signal:
    signal_type: SignalType
    symbol: str
    timestamp: int
    entry_price: Optional[float] = None  # ENTRY signals only
    initial_sl: Optional[float] = None   # Optional
    initial_tp: Optional[float] = None   # Optional
    exit_reason: Optional[str] = None    # EXIT signals only
```

**Tasks**:
- [ ] **`src/models/signal.py`**: Add `SignalType` enum, restructure `Signal` dataclass
- [ ] Add validation logic for signal type field consistency
- [ ] **`src/strategies/base.py`**: Split `analyze()` into `check_entry()` and `check_exit()`
- [ ] Add abstract methods for both entry/exit checks
- [ ] Implement position state tracking (`self.position: Optional[Position]`)
- [ ] **`src/execution/order_manager.py`**: Add signal type branching logic
- [ ] Implement separate handlers for ENTRY/EXIT signals
- [ ] Maintain OCO order compatibility for initial SL/TP
- [ ] **All Strategy Implementations**: Migrate to new interface
- [ ] Separate entry/exit logic explicitly in all strategies
- [ ] Add compatibility wrapper: default `analyze()` → calls `check_entry()`
- [ ] Test: Signal validation for each type
- [ ] Test: BaseStrategy state transitions (no position → entry → position held → exit)
- [ ] Test: OrderManager handles all signal types correctly

**Impact**: 🔴 High (Foundational) | **Complexity**: 🔴 High | **Risk**: 🔴 High
**Estimate**: 3-4 days

**Risk Mitigation**:
- Phased rollout: Add new methods first, deprecate later
- 100% test coverage on new signal types
- Canary deployment with conservative strategies

---

### Phase 2 Exit Criteria
- ✅ All strategies use `Dict[str, deque]` buffers
- ✅ Signal generation/processing uses Entry/Exit separation
- ✅ 100% test coverage on new signal types
- ✅ Zero breaking changes for production strategies
- ✅ Integration tests pass for full pipeline

---

## Phase 3: Feature Enhancement & Performance (8 days)

### Goal
고급 기능 구현 및 실시간 성능 최적화

**Dependencies**: #27 (buffer structure), #25 (signal separation) must be complete

---

### Issue #19: Precompute Historical Features (P2 - Performance)
**Problem**: 실시간 MTF 전략에서 HTF 캔들 미확정 시 지표 재계산 지연 발생

**Solution**: 백필 단계에서 모든 지표 및 구조적 특성 사전 계산
```python
class MultiTimeframeStrategy(BaseStrategy):
    def initialize_with_historical_data(self, historical_data: Dict[str, List[Candle]]):
        # Step 1: Fill buffers (existing)
        for interval, candles in historical_data.items():
            self.buffers[interval].extend(candles)

        # Step 2: NEW - Pre-calculate all features
        self.active_order_blocks: List[OrderBlock] = []
        self.active_fvgs: List[FairValueGap] = []

        for candle in self._chronological_order(historical_data):
            self._update_feature_states(candle)
            self._detect_new_features(candle)

    def analyze_mtf(self, current_candles: Dict[str, Candle]) -> Optional[Signal]:
        # Only update states, not recalculate
        self._update_feature_states(current_candles)
        self._detect_new_features(current_candles)
        return self._generate_signal_from_features()
```

**Tasks**:
- [ ] **Feature State Objects**: Create `src/models/order_block.py` and `src/models/fair_value_gap.py`
- [ ] Add creation time, price level, mitigation/fill status fields
- [ ] **Strategy Enhancement**: Add `_update_feature_states()` method (O(n) scan)
- [ ] Add `_detect_new_features()` method (check for new OB/FVG formation)
- [ ] Add `_chronological_order()` helper (merge multi-interval historical data)
- [ ] Implement feature expiration logic (remove after N candles)
- [ ] Add circular buffer for feature history
- [ ] Test: Feature state lifecycle (creation → active → expired)
- [ ] Benchmark: Backfill time < 60s for 1000 candles × 3 intervals
- [ ] Benchmark: analyze_mtf() < 1ms (p99)
- [ ] Memory profiling: Feature count stays < 100 per strategy

**Impact**: 🟡 Medium (Performance) | **Complexity**: 🔴 High | **Risk**: 🟡 Medium
**Estimate**: 5-7 days

**Trade-offs**:
- ⬆️ Backfill time: +30-60 seconds
- ⬆️ Memory: +5-10MB per strategy
- ⬇️ Real-time latency: -80% (5ms → 1ms)

---

### Issue #18: Per-Symbol Strategy Configuration (P2 - Feature)
**Problem**: 현재 모든 심볼이 동일한 전략 타입 및 설정 사용

**Solution**: Strategy Profile Mapping 방식으로 심볼별 독립 설정
```ini
[strategy_profile.aggressive]
name = ICTMultiTimeframe
buffer_size = 200
risk_reward_ratio = 2.0

[strategy_profile.conservative]
name = ICTMultiTimeframe
buffer_size = 100
risk_reward_ratio = 3.0

[trading]
symbols = BTCUSDT:aggressive, ETHUSDT:conservative
```

**Tasks**:
- [ ] **`src/utils/config.py`**: Add `StrategyProfile` dataclass
- [ ] Parse `[strategy_profile.*]` sections from INI
- [ ] Update `TradingConfig.symbols` to `List[Tuple[str, str]]` (symbol, profile)
- [ ] **`src/core/trading_engine.py`**: Update `initialize_components()` to map symbols to profiles
- [ ] Pass per-symbol config to `StrategyFactory.create()`
- [ ] Add backward compatibility: Single profile for all symbols if no mapping
- [ ] Test: ConfigManager parses multi-profile INI correctly
- [ ] Test: TradingEngine creates different strategy instances per symbol
- [ ] Test: Single-profile config still works (regression)

**Impact**: 🟡 Medium | **Complexity**: 🟡 Medium | **Risk**: 🟢 Low
**Estimate**: 2-3 days

---

### Phase 3 Exit Criteria
- ✅ Historical feature precomputation reduces real-time latency by 70%+
- ✅ Per-symbol strategy configuration working in production
- ✅ Memory usage stays within 50MB per strategy instance
- ✅ All performance benchmarks met:
  - Tick processing < 1ms (p99)
  - Backfill time < 60s
  - Memory growth < 10MB/hour

---

## Implementation Timeline

### Gantt Chart
```
Week 1: Phase 1 - Critical Fixes (2 days)
─────────────────────────────────────────────
Day 1-2    │ #22 SIGINT │ #23 Task │ #26 Backfill │ Testing │
           └────────────┴──────────┴──────────────┴─────────┘

Week 2-3: Phase 2 - Architecture (10 days)
─────────────────────────────────────────────
Day 3-5    │        #27 Buffer Unification         │ Testing │
           └───────────────────────────────────────┴─────────┘
Day 6-9    │        #25 Signal Separation          │ Testing │
           └───────────────────────────────────────┴─────────┘
Day 10     │           Integration Testing                    │
           └──────────────────────────────────────────────────┘

Week 4-5: Phase 3 - Features (8 days)
─────────────────────────────────────────────
Day 11-17  │        #19 Precompute Features        │ Testing │
Day 11-13  │     #18 Per-Symbol Config (Parallel)  │ Testing │
           └───────────────────────────────────────┴─────────┘
Day 18-19  │           Integration Testing                    │
Day 20     │          Production Readiness Review             │
           └──────────────────────────────────────────────────┘

Total: 20 business days (realistic: 26 days with 30% buffer)
```

---

## Risk Management

### High-Risk Items
- **#27 Buffer Structure**: Breaking all existing strategies
  - **Mitigation**: Compatibility layer, extensive testing
- **#25 Signal Separation**: Pipeline bugs causing missed trades
  - **Mitigation**: Canary deployment, conservative strategies first

### Testing Requirements
- **Phase 1**: 2-3 hours per issue, CI/CD on every commit
- **Phase 2**: 1-2 days per major change, full regression suite
- **Phase 3**: Performance + load testing, nightly benchmarks

---

## Success Metrics

| Metric | Baseline | Target | Phase |
|--------|----------|--------|-------|
| System Uptime | 95% | 99.5% | Phase 1 |
| Tick Processing | 5ms (p99) | < 1ms (p99) | Phase 3 |
| Memory Efficiency | 50MB/strategy | < 30MB/strategy | Phase 3 |
| Configuration Flexibility | 1 strategy type | N strategy types | Phase 3 |

---

## Recommended Next Steps

1. **Immediate Action**: Start Phase 1 (#22, #23, #26) in parallel
2. **Design Finalization**: Finalize detailed design for #27 and #25
3. **Test Infrastructure**: Ensure performance benchmarking tools are ready
4. **Deployment Plan**: Prepare canary deployment for Phase 2

**Critical Path**: Phase 2 (Buffer Unification → Signal Separation) - 10 days
**Parallel Opportunities**: Phase 1 (all 3 issues), Phase 3 (#18 and #19)
**Total Duration**: 20 days optimistic, 26 days realistic
