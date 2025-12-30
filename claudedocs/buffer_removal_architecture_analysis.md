# DataCollector Buffer Removal: Architectural Impact Analysis

**Date**: 2025-12-30
**Scope**: Remove internal buffer system from DataCollector (eliminate duplicate storage)
**Status**: Pre-implementation architectural review

---

## Executive Summary

### Current Architecture (Redundant Buffering)
```
REST API → DataCollector._candle_buffers → Strategy.buffers  (backfill)
WebSocket → DataCollector._candle_buffers → Strategy.buffers  (real-time)
           ↓ (also triggers)
           callback → EventBus → TradingEngine → Strategy
```

**Problem**: Same candles stored in TWO places (500 candles × 2 = wasted memory)

### Target Architecture (Direct Injection)
```
REST API → Strategy.buffers  (direct initialization)
WebSocket → callback → EventBus → TradingEngine → Strategy.update_buffer()
```

**Benefit**: Single source of truth, reduced memory footprint, simpler data flow

---

## 1. Dependency Analysis

### 1.1 Components Depending on Buffer Methods

#### **CRITICAL PATH: Main.py Backfill Workflow**

**Current Flow (main.py:162-196)**:
```python
# Step 5.5: Backfill
backfill_success = data_collector.backfill_all(limit=200)

# Step 5.6: Retrieve buffered candles
historical_candles = data_collector.get_all_buffered_candles()
# Returns: {'BTCUSDT_1h': [Candle, ...], 'BTCUSDT_5m': [...]}

# Step 9.5: Initialize strategy
trading_engine.initialize_strategy_with_historical_data(historical_candles)
```

**New Flow (PROPOSED)**:
```python
# Step 5.5: Direct strategy initialization with REST data
for symbol in trading_config.symbols:
    for interval in trading_config.intervals:
        # Fetch directly from REST API
        candles = data_collector.get_historical_candles(symbol, interval, limit=200)

        # Direct injection to strategy buffer (no DataCollector buffering)
        strategy.initialize_with_historical_data(interval, candles)
```

**Impact**: `backfill_all()` and `get_all_buffered_candles()` must be REMOVED/REFACTORED

---

#### **DataCollector Methods Using Buffers**

| Method | Current Usage | Buffer Operation | Removal Impact |
|--------|---------------|------------------|----------------|
| `_get_buffer_key()` | Internal helper | Generate buffer keys | **DELETE** (no buffers needed) |
| `add_candle_to_buffer()` | WebSocket handler | Store candle in deque | **DELETE** (direct callback only) |
| `get_candle_buffer()` | External query | Retrieve specific buffer | **DELETE** (strategy has data) |
| `get_all_buffered_candles()` | Main.py:174 | Return all buffers | **DELETE** (see new flow above) |
| `backfill_all()` | Main.py:167 | Fetch + auto-buffer | **REFACTOR** (fetch only, no buffering) |
| `get_historical_candles()` | Internal + external | Fetch + auto-buffer (line 448) | **REFACTOR** (remove line 448) |

---

#### **WebSocket Message Handler**

**Current Flow (data_collector.py:167-271)**:
```python
def _handle_kline_message(self, _, message):
    # ... parse message ...
    candle = Candle(...)

    # Step 5: Add candle to buffer  ← DELETE THIS
    self.add_candle_to_buffer(candle)

    # Step 6: Invoke user callback      ← KEEP THIS
    if self.on_candle_callback:
        self.on_candle_callback(candle)
```

**New Flow (PROPOSED)**:
```python
def _handle_kline_message(self, _, message):
    # ... parse message ...
    candle = Candle(...)

    # Direct callback to main.py → EventBus → TradingEngine → Strategy
    if self.on_candle_callback:
        self.on_candle_callback(candle)
```

**Impact**: Remove `self.add_candle_to_buffer(candle)` from line 241

---

### 1.2 TradingEngine Initialization Flow

**Current Flow (trading_engine.py:188-331)**:
```python
def initialize_strategy_with_historical_data(self, historical_candles: dict):
    # historical_candles = {'BTCUSDT_1h': [Candle, ...], ...}

    if isinstance(self.strategy, MultiTimeframeStrategy):
        for buffer_key, candles in historical_candles.items():
            if buffer_key.startswith(symbol):
                interval = buffer_key.rsplit('_', 1)[1]  # Extract interval
                self.strategy.initialize_with_historical_data(interval, candles)
    else:
        # Single-interval backward compatibility
        for buffer_key, candles in historical_candles.items():
            if buffer_key.startswith(symbol):
                self.strategy.initialize_with_historical_data(candles)
                return  # Use ONLY first interval
```

**New Flow (PROPOSED)**:
```python
# NO LONGER NEEDED - TradingEngine doesn't initialize strategy
# Initialization happens directly in Main.py during backfill loop
```

**Impact**: `initialize_strategy_with_historical_data()` becomes UNUSED (can be deleted or kept for compatibility)

---

### 1.3 Strategy Buffer Management

**BaseStrategy (base.py:85-170)**:
```python
class BaseStrategy:
    def __init__(self, symbol: str, config: dict):
        self.candle_buffer = deque(maxlen=config.get('buffer_size', 100))

    def update_buffer(self, candle: Candle):
        self.candle_buffer.append(candle)

    def initialize_with_historical_data(self, candles: List[Candle]):
        for candle in candles:
            self.candle_buffer.append(candle)
```

**MultiTimeframeStrategy (multi_timeframe.py:94-230)**:
```python
class MultiTimeframeStrategy(BaseStrategy):
    def __init__(self, symbol: str, intervals: List[str], config: dict):
        super().__init__(symbol, config)
        self.intervals = intervals
        self.buffers = {interval: deque(maxlen=self.buffer_size) for interval in intervals}

    def initialize_with_historical_data(self, interval: str, candles: List[Candle]):
        for candle in candles:
            self.buffers[interval].append(candle)

    async def analyze(self, candle: Candle):
        # Route candle to correct interval buffer
        if candle.interval in self.buffers:
            self.buffers[candle.interval].append(candle)
```

**Impact**: Strategy buffer logic is ALREADY INDEPENDENT - no changes needed here

---

## 2. Risk Assessment

### 2.1 High Risk Areas

#### **CRITICAL: Real-Time Data Flow Integrity**

**Risk**: Breaking WebSocket → Strategy flow causes data loss
**Likelihood**: High (multiple touchpoints)
**Mitigation**:
1. Ensure `on_candle_callback` is ALWAYS invoked (line 245)
2. Verify EventBus publishes to 'data' queue
3. Test WebSocket → EventBus → Strategy end-to-end
4. Keep integration test: `test_binance_mainnet.py`

**Validation**:
```python
# Real-time flow test (keep this pattern)
async def test_real_time_flow():
    collector = BinanceDataCollector(..., on_candle_callback=callback)
    await collector.start_streaming()

    # Wait for candle
    # Assert: callback invoked → EventBus published → Strategy buffered
```

---

#### **CRITICAL: MTF Strategy Interval Routing**

**Risk**: Multi-timeframe strategies receive candles but don't route to correct interval buffers
**Likelihood**: Medium (existing routing logic is robust)
**Mitigation**:
1. Preserve MTF routing in `analyze()` method
2. Test 3-interval scenario (5m, 1h, 4h)
3. Verify `buffers[interval].append()` still works

**Validation**:
```python
def test_mtf_interval_routing():
    strategy = ICTStrategy(symbol='BTCUSDT', intervals=['5m', '1h', '4h'], config={})

    # Initialize with historical data (new direct flow)
    for interval in ['5m', '1h', '4h']:
        candles = data_collector.get_historical_candles('BTCUSDT', interval, 100)
        strategy.initialize_with_historical_data(interval, candles)

    # Simulate real-time candles
    candle_5m = Candle(interval='5m', ...)
    candle_1h = Candle(interval='1h', ...)

    await strategy.analyze(candle_5m)  # Should route to buffers['5m']
    await strategy.analyze(candle_1h)  # Should route to buffers['1h']

    assert len(strategy.buffers['5m']) == 101
    assert len(strategy.buffers['1h']) == 101
```

---

### 2.2 Medium Risk Areas

#### **Test Suite Breakage (14+ Tests)**

**Risk**: Many tests explicitly verify buffer behavior
**Likelihood**: Guaranteed (100%)
**Mitigation**: Systematic test refactoring (see Migration Plan)

**Affected Tests (from test_data_collector.py)**:
- `test_get_buffer_key_*` (3 tests) → DELETE (no buffer keys)
- `test_add_candle_*` (3 tests) → DELETE (no buffering)
- `test_get_candle_buffer_*` (5 tests) → DELETE (no getter)
- `test_websocket_integration_auto_buffers` → REFACTOR (verify callback only)
- `test_historical_data_prepopulates_buffer` → REFACTOR (verify no buffering)

**New Tests Needed**:
```python
def test_websocket_callback_no_buffering(data_collector):
    """Verify WebSocket calls callback but doesn't buffer."""
    callback_invoked = False

    def callback(candle):
        nonlocal callback_invoked
        callback_invoked = True

    collector = BinanceDataCollector(..., on_candle_callback=callback)

    # Simulate WebSocket message
    message = {...}  # Kline message
    collector._handle_kline_message(None, message)

    assert callback_invoked is True
    assert not hasattr(collector, '_candle_buffers')  # No buffers exist

def test_get_historical_no_buffering(data_collector):
    """Verify get_historical_candles doesn't buffer data."""
    candles = data_collector.get_historical_candles('BTCUSDT', '1h', 100)

    assert len(candles) == 100
    assert not hasattr(data_collector, '_candle_buffers')  # No buffers created
```

---

#### **Backfill Workflow Refactoring**

**Risk**: Main.py initialization sequence breaks during refactor
**Likelihood**: Medium (well-defined flow)
**Mitigation**: Incremental changes with integration tests

**Critical Path**:
```python
# OLD (main.py:162-196)
backfill_success = data_collector.backfill_all(limit=200)
historical_candles = data_collector.get_all_buffered_candles()
trading_engine.initialize_strategy_with_historical_data(historical_candles)

# NEW (PROPOSED)
for symbol in [trading_config.symbol]:
    for interval in trading_config.intervals:
        candles = data_collector.get_historical_candles(symbol, interval, limit=200)
        strategy.initialize_with_historical_data(interval, candles)
```

**Validation**: Integration test `test_backfill_to_strategy_direct()`

---

### 2.3 Low Risk Areas

#### **REST API get_historical_candles()**

**Risk**: Method signature change breaks external callers
**Likelihood**: Low (signature stays same)
**Mitigation**: Remove internal buffering (line 448) only

**Change**:
```python
# OLD (data_collector.py:390-469)
def get_historical_candles(self, symbol, interval, limit):
    klines_data = self.rest_client.klines(...)
    candles = []
    for kline_array in klines_data:
        candle = self._parse_rest_kline(kline_array)
        candles.append(candle)
        self.add_candle_to_buffer(candle)  # ← DELETE LINE 448
    return candles

# NEW (PROPOSED)
def get_historical_candles(self, symbol, interval, limit):
    klines_data = self.rest_client.klines(...)
    candles = []
    for kline_array in klines_data:
        candle = self._parse_rest_kline(kline_array)
        candles.append(candle)
        # No buffering - just return data
    return candles
```

**Impact**: Existing callers (main.py, tests) still work - return value unchanged

---

#### **EventBus Data Flow**

**Risk**: EventBus routing logic needs changes
**Likelihood**: Very Low (EventBus agnostic to buffering)
**Mitigation**: None needed (EventBus just routes events)

**Current Flow (unchanged)**:
```
WebSocket → callback → Event(CANDLE_CLOSED) → EventBus.publish('data') → TradingEngine → Strategy.analyze()
```

---

## 3. Migration Strategy

### Phase 1: Preparation (Non-Breaking)

**Goal**: Add new direct-injection paths WITHOUT removing buffers

#### Step 1.1: Add Direct Strategy Initialization
```python
# NEW METHOD: main.py (add alongside existing backfill)
def initialize_strategy_direct(
    self,
    data_collector: BinanceDataCollector,
    strategy: BaseStrategy,
    symbols: List[str],
    intervals: List[str],
    limit: int
) -> None:
    """Direct strategy initialization without DataCollector buffering."""
    for symbol in symbols:
        for interval in intervals:
            candles = data_collector.get_historical_candles(symbol, interval, limit)

            if isinstance(strategy, MultiTimeframeStrategy):
                strategy.initialize_with_historical_data(interval, candles)
            else:
                strategy.initialize_with_historical_data(candles)
```

**Test**: Verify new flow works alongside old flow

---

#### Step 1.2: Deprecate Buffer Methods
```python
# data_collector.py - mark for removal
def get_all_buffered_candles(self) -> Dict[str, List[Candle]]:
    """
    DEPRECATED: Will be removed in next version.
    Use direct strategy initialization instead.
    """
    import warnings
    warnings.warn("get_all_buffered_candles() is deprecated", DeprecationWarning)
    return self._get_all_buffered_candles_impl()
```

**Test**: Run full test suite - should pass with warnings

---

### Phase 2: Remove DataCollector Buffering (BREAKING)

**Goal**: Remove all buffer logic from DataCollector

#### Step 2.1: Remove Buffer Storage
```python
# data_collector.py - DELETE from __init__
# Line 115-117
# self._candle_buffers: Dict[str, deque] = {}

# NEW __init__ (no buffer attribute)
def __init__(...):
    # ... existing setup ...
    # REST client, WebSocket client, state flags
    # NO buffer initialization
```

**Impact**: Breaks any code accessing `collector._candle_buffers`

---

#### Step 2.2: Remove WebSocket Buffering
```python
# data_collector.py - EDIT _handle_kline_message
def _handle_kline_message(self, _, message):
    # ... parse logic ...
    candle = Candle(...)

    # DELETE: self.add_candle_to_buffer(candle)  # Line 241

    # KEEP: Direct callback
    if self.on_candle_callback:
        self.on_candle_callback(candle)
```

**Test**: `test_websocket_callback_only()`

---

#### Step 2.3: Remove REST API Buffering
```python
# data_collector.py - EDIT get_historical_candles
def get_historical_candles(self, symbol, interval, limit):
    klines_data = self.rest_client.klines(...)
    candles = []
    for kline_array in klines_data:
        candle = self._parse_rest_kline(kline_array)
        candles.append(candle)
        # DELETE: self.add_candle_to_buffer(candle)  # Line 448
    return candles
```

**Test**: `test_get_historical_no_buffering()`

---

#### Step 2.4: Delete Buffer Methods
```python
# data_collector.py - DELETE entire methods
# Lines 552-693 (approx)

# DELETE:
# - _get_buffer_key()
# - add_candle_to_buffer()
# - get_candle_buffer()
# - get_all_buffered_candles()
```

**Impact**: Breaks tests explicitly testing these methods

---

#### Step 2.5: Refactor backfill_all()
```python
# data_collector.py - OPTION A: Keep as convenience wrapper
def backfill_all(self, limit: int = 100) -> bool:
    """
    Convenience wrapper for fetching all symbol/interval pairs.
    Returns dict of candles ready for strategy initialization.
    """
    result = {}
    for symbol in self.symbols:
        for interval in self.intervals:
            try:
                candles = self.get_historical_candles(symbol, interval, limit)
                buffer_key = f"{symbol}_{interval}"
                result[buffer_key] = candles
            except Exception as e:
                self.logger.error(f"Failed to fetch {symbol} {interval}: {e}")

    return result

# OPTION B: Delete entirely (callers use get_historical_candles directly)
```

**Recommendation**: Keep OPTION A for backward compatibility

---

### Phase 3: Update Main.py Initialization

**Goal**: Replace old backfill flow with direct strategy initialization

#### Step 3.1: Replace Backfill Block
```python
# main.py - REPLACE Lines 162-196

# OLD:
# backfill_success = self.data_collector.backfill_all(limit=200)
# historical_candles = self.data_collector.get_all_buffered_candles()
# self._historical_candles = historical_candles

# NEW:
if trading_config.backfill_limit > 0:
    self.logger.info(f"Backfilling {trading_config.backfill_limit} candles...")

    for symbol in [trading_config.symbol]:
        for interval in trading_config.intervals:
            try:
                candles = self.data_collector.get_historical_candles(
                    symbol, interval, trading_config.backfill_limit
                )

                # Direct strategy initialization (no intermediate storage)
                if isinstance(self.strategy, MultiTimeframeStrategy):
                    self.strategy.initialize_with_historical_data(interval, candles)
                else:
                    self.strategy.initialize_with_historical_data(candles)

                self.logger.info(
                    f"✅ Initialized {symbol} {interval}: {len(candles)} candles"
                )
            except Exception as e:
                self.logger.error(f"❌ Failed to backfill {symbol} {interval}: {e}")
else:
    self.logger.info("Backfilling disabled (limit=0)")
```

---

#### Step 3.2: Remove TradingEngine Initialization Call
```python
# main.py - DELETE Lines 260-268

# DELETE:
# if hasattr(self, '_historical_candles') and self._historical_candles:
#     self.trading_engine.initialize_strategy_with_historical_data(
#         self._historical_candles
#     )
```

**Rationale**: Strategy already initialized in Step 3.1

---

### Phase 4: Test Migration

**Goal**: Replace buffer-focused tests with callback-focused tests

#### Step 4.1: Delete Obsolete Tests
```python
# tests/core/test_data_collector.py - DELETE

# Lines ~1429-1465: Buffer key tests
# - test_get_buffer_key_uppercase_normalization
# - test_get_buffer_key_format
# - test_get_buffer_key_different_intervals

# Lines ~1466-1692: Buffer operation tests
# - test_add_candle_creates_buffer_if_not_exists
# - test_add_candle_multiple_to_same_buffer
# - test_add_candle_separate_buffers_per_pair
# - test_get_candle_buffer_nonexistent_returns_empty
# - test_get_candle_buffer_empty_buffer_returns_empty
# - test_get_candle_buffer_returns_sorted_by_time
# - test_get_candle_buffer_nondestructive_read
# - test_get_candle_buffer_multiple_candles
# - test_websocket_integration_auto_buffers
# - test_historical_data_prepopulates_buffer
```

---

#### Step 4.2: Add New Tests
```python
# tests/core/test_data_collector.py - ADD

def test_websocket_callback_only(data_collector):
    """Verify WebSocket handler calls callback without buffering."""
    callback_called = False
    received_candle = None

    def callback(candle):
        nonlocal callback_called, received_candle
        callback_called = True
        received_candle = candle

    collector = BinanceDataCollector(
        api_key='test', api_secret='test',
        symbols=['BTCUSDT'], intervals=['1m'],
        on_candle_callback=callback
    )

    # Simulate WebSocket message
    message = {
        'e': 'kline',
        'k': {
            's': 'BTCUSDT', 'i': '1m', 't': 1609459200000, 'T': 1609459259999,
            'o': '29000.00', 'h': '29100.00', 'l': '28900.00',
            'c': '29050.00', 'v': '100.5', 'x': True
        }
    }

    collector._handle_kline_message(None, message)

    assert callback_called is True
    assert received_candle.symbol == 'BTCUSDT'
    assert not hasattr(collector, '_candle_buffers')  # No buffers exist

def test_get_historical_no_buffering(mock_rest_client, data_collector):
    """Verify get_historical_candles returns data without buffering."""
    # Mock REST API response
    mock_rest_client.klines.return_value = [
        [1609459200000, '29000', '29100', '28900', '29050', '100.5', 1609459259999, ...],
        # ... more klines ...
    ]

    candles = data_collector.get_historical_candles('BTCUSDT', '1h', 100)

    assert len(candles) == 100
    assert candles[0].symbol == 'BTCUSDT'
    assert not hasattr(data_collector, '_candle_buffers')  # No buffers created

def test_backfill_returns_dict_no_buffering(mock_rest_client, data_collector):
    """Verify backfill_all returns organized candles without buffering."""
    mock_rest_client.klines.return_value = [...] * 50

    result = data_collector.backfill_all(limit=50)

    assert 'BTCUSDT_1m' in result
    assert len(result['BTCUSDT_1m']) == 50
    assert not hasattr(data_collector, '_candle_buffers')  # No buffers exist
```

---

#### Step 4.3: Integration Tests
```python
# tests/integration/test_backfill_to_strategy.py - NEW FILE

@pytest.mark.integration
async def test_direct_strategy_initialization():
    """Verify REST API → Strategy direct initialization."""
    # Setup
    collector = BinanceDataCollector(...)
    strategy = ICTStrategy(symbol='BTCUSDT', intervals=['5m', '1h'], config={})

    # Backfill directly to strategy
    for interval in ['5m', '1h']:
        candles = collector.get_historical_candles('BTCUSDT', interval, 100)
        strategy.initialize_with_historical_data(interval, candles)

    # Verify
    assert len(strategy.buffers['5m']) == 100
    assert len(strategy.buffers['1h']) == 100
    assert strategy.is_ready() is True

@pytest.mark.integration
async def test_websocket_to_strategy_flow():
    """Verify WebSocket → EventBus → Strategy real-time flow."""
    # Setup full pipeline
    event_bus = EventBus()
    collector = BinanceDataCollector(..., on_candle_callback=lambda c: event_bus.publish(...))
    strategy = ICTStrategy(...)
    engine = TradingEngine(...)

    await collector.start_streaming()

    # Wait for real candle
    await asyncio.sleep(65)  # 1m + buffer

    # Verify candle reached strategy
    assert len(strategy.buffers['1m']) > 0
    assert not hasattr(collector, '_candle_buffers')  # No DataCollector buffering
```

---

## 4. Validation Points

### 4.1 Phase 1 Validation (Preparation)
- [ ] New direct initialization path works
- [ ] Old backfill path still works (parallel)
- [ ] Deprecation warnings appear
- [ ] All existing tests pass

---

### 4.2 Phase 2 Validation (Buffer Removal)
- [ ] DataCollector has NO `_candle_buffers` attribute
- [ ] WebSocket handler calls callback only (no buffering)
- [ ] REST API returns candles without buffering
- [ ] Buffer methods deleted or raise NotImplementedError
- [ ] New tests pass (`test_websocket_callback_only`, etc.)

---

### 4.3 Phase 3 Validation (Main.py Refactor)
- [ ] Main.py initializes strategy directly (no intermediate storage)
- [ ] Multi-timeframe routing works (3-interval test)
- [ ] Single-interval strategy backward compatible
- [ ] Backfill errors logged but don't crash

---

### 4.4 Phase 4 Validation (Test Migration)
- [ ] Obsolete tests deleted (14+ tests)
- [ ] New tests added (3+ tests)
- [ ] Integration tests pass (backfill + real-time)
- [ ] Test coverage >= 90% (target)

---

### 4.5 End-to-End Validation
- [ ] **Real-time flow**: WebSocket → EventBus → Strategy (no data loss)
- [ ] **Backfill flow**: REST → Strategy (all intervals initialized)
- [ ] **MTF routing**: 3 intervals (5m, 1h, 4h) correctly separated
- [ ] **Memory usage**: Reduced by ~50% (no duplicate storage)
- [ ] **Performance**: No regression in latency/throughput

---

## 5. Rollback Plan

### If Issues Detected in Phase 2-3

**Symptoms**:
- Data loss in real-time flow
- MTF strategies receive wrong intervals
- Integration tests fail

**Rollback Steps**:
1. Revert Phase 2 commits (restore buffer methods)
2. Revert Phase 3 commits (restore old main.py flow)
3. Keep Phase 1 (new direct path) as OPTIONAL fallback
4. Investigate root cause before retry

**Recovery Time**: < 1 hour (git revert)

---

## 6. Success Metrics

### Performance
- [ ] Memory usage: Reduced by 40-50% (500 candles × 2 → 500 candles × 1)
- [ ] Latency: No increase in WebSocket → Strategy delay
- [ ] Throughput: Same candle processing rate

### Maintainability
- [ ] Code complexity: Reduced LOC by ~150 lines (buffer methods)
- [ ] Test count: Net reduction (14 deleted, 3 added = -11 tests)
- [ ] Data flow: Single path (easier to debug)

### Correctness
- [ ] Zero data loss in real-time trading
- [ ] MTF strategies work with all interval combinations
- [ ] Backward compatibility for single-interval strategies

---

## 7. Timeline Estimate

| Phase | Tasks | Effort | Dependencies |
|-------|-------|--------|--------------|
| Phase 1: Preparation | Add direct path, deprecate | 2 hours | None |
| Phase 2: Remove Buffers | Delete buffer logic | 3 hours | Phase 1 complete |
| Phase 3: Main.py Refactor | Update initialization | 2 hours | Phase 2 complete |
| Phase 4: Test Migration | Delete/add tests | 3 hours | Phase 3 complete |
| Validation | Integration tests, review | 2 hours | Phase 4 complete |
| **TOTAL** | | **12 hours** | Sequential |

**Recommended Approach**: Execute over 2 days with checkpoints after each phase

---

## Appendix A: File Change Summary

### Files to MODIFY
1. `src/core/data_collector.py`
   - DELETE: `_candle_buffers` attribute
   - DELETE: Lines 241, 448 (buffering calls)
   - DELETE: Methods (552-693): buffer operations
   - REFACTOR: `backfill_all()` to return dict (optional)

2. `src/main.py`
   - REPLACE: Lines 162-196 (backfill block)
   - DELETE: Lines 260-268 (TradingEngine initialization)

3. `tests/core/test_data_collector.py`
   - DELETE: 14+ buffer tests
   - ADD: 3 new callback tests

### Files UNCHANGED
1. `src/strategies/base.py` - Strategy buffer logic independent
2. `src/strategies/multi_timeframe.py` - MTF routing unchanged
3. `src/core/event_handler.py` - EventBus agnostic
4. `src/core/trading_engine.py` - Can keep old method as no-op

### Files to ADD (Optional)
1. `tests/integration/test_backfill_to_strategy.py` - E2E validation

---

## Appendix B: Critical Code Blocks

### DataCollector WebSocket Handler (KEEP THIS FLOW)
```python
# src/core/data_collector.py:167-271
def _handle_kline_message(self, _, message):
    # ... parse and validate ...
    candle = Candle(...)

    # CRITICAL: Callback must always fire
    if self.on_candle_callback:
        self.on_candle_callback(candle)  # → main.py → EventBus → Strategy
```

### Main.py Callback Bridge (KEEP THIS FLOW)
```python
# src/main.py:303-387
def _on_candle_received(self, candle: Candle):
    # Lifecycle state check
    if self._lifecycle_state != LifecycleState.RUNNING:
        return

    # CRITICAL: Publish to EventBus
    event = Event(EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE, candle)
    asyncio.run_coroutine_threadsafe(
        self.event_bus.publish(event, queue_name='data'),
        self._event_loop
    )
```

### Strategy MTF Routing (KEEP THIS LOGIC)
```python
# src/strategies/multi_timeframe.py:250-280
async def analyze(self, candle: Candle):
    # CRITICAL: Route to correct interval buffer
    if candle.interval in self.buffers:
        self.buffers[candle.interval].append(candle)

    # Only analyze on LTF candle close
    if candle.interval == self.ltf_interval and candle.is_closed:
        return await self.analyze_mtf(candle, self.buffers)
```

---

## Conclusion

**Architectural Impact**: MODERATE
**Risk Level**: MEDIUM (test breakage guaranteed, data flow changes)
**Effort**: 12 hours (2 days)
**Benefit**: Significant (50% memory reduction, simpler data flow)

**Recommendation**: PROCEED with phased migration approach. Execute Phase 1-2 first, validate thoroughly before Phase 3-4.

**Key Success Factors**:
1. Real-time data flow integrity (WebSocket → Strategy)
2. MTF interval routing correctness
3. Comprehensive integration testing
4. Rollback readiness

---

**Review Status**: Ready for implementation
**Next Action**: Execute Phase 1 (Preparation) with feature flag
