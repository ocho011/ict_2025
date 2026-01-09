# Product Requirements Document: Circular Dependency Refactoring

**Version**: 1.0
**Date**: 2025-01-03
**Status**: Ready for Implementation
**Source**: claudedocs/refactor_trading_engine_dependency_v2.md

---

## Executive Summary

This PRD defines the requirements for removing the circular dependency between `TradingBot` and `TradingEngine` in the real-time trading system. The refactoring moves candle reception logic from `TradingBot` to `TradingEngine`, where it logically belongs, improving architectural clarity and maintainability.

**Key Benefits**:
- Eliminates circular dependency and architectural code smell
- Simplifies component initialization and lifecycle management
- Improves cohesion by co-locating related functionality
- Maintains or improves system performance (< 1ms p99 latency)
- Enables cleaner testing and component isolation

**Scope**: Internal refactoring only - no external API changes, no database schema changes, no deployment configuration changes.

**Timeline**: 4-6 hours of implementation and validation

---

## Success Criteria

### Must Have (Blocking)
- ✅ Circular dependency completely removed (TradingEngine no longer references TradingBot)
- ✅ All existing tests pass without modification to test logic
- ✅ Zero performance regression (p99 latency ≤ baseline)
- ✅ Zero data loss during normal operation (_event_drop_count remains accurate)
- ✅ Clean rollback possible within 1 deployment cycle

### Should Have (High Priority)
- ✅ System startup completes within 5 seconds (same as current)
- ✅ Code complexity does not increase (measured by cyclomatic complexity)
- ✅ Comprehensive test coverage for new state machine (>90%)
- ✅ Clear documentation of new initialization sequence

### Nice to Have (Optional)
- ✅ Monitoring dashboard updated with new metrics ownership
- ✅ Architecture diagrams updated to reflect changes
- ✅ Development team trained on new patterns

---

## Feature Requirements

### Feature 1: TradingEngine Event Loop Management

**User Story**: As a TradingEngine, I need to manage my own event loop so I don't depend on TradingBot for event loop access.

**Priority**: MUST (Blocking)

**Tasks**:
1. Add `_event_loop: Optional[asyncio.AbstractEventLoop]` attribute to TradingEngine.__init__
2. Add `_ready_event: asyncio.Event` synchronization primitive to TradingEngine.__init__
3. Implement event loop capture in `run()` method using `asyncio.get_running_loop()`
4. Implement `wait_until_ready(timeout: float = 5.0)` method with timeout handling
5. Add `EngineState` enum with states: CREATED, INITIALIZED, RUNNING, STOPPING, STOPPED
6. Add state machine validation for valid transitions
7. Add `_state_lock: asyncio.Lock` to protect state transitions
8. Implement state transition logging with structured data

**Acceptance Criteria**:
```gherkin
Given: TradingEngine is created
When: run() is called from AsyncIO event loop
Then: _event_loop is set to current running loop
And: _ready_event is set to signal readiness
And: state transitions from INITIALIZED to RUNNING

Given: DataCollector attempts to start before engine ready
When: waiting for ready via wait_until_ready()
Then: wait blocks until _ready_event is set
And: timeout after 5 seconds if not ready
And: raises EngineNotRunningError on timeout

Given: engine is in CREATED state
When: on_candle_received() is called
Then: candle is rejected with warning log
And: _event_drop_count is incremented
And: no exception is raised (fail-safe)

Given: engine transitions states
When: invalid transition attempted (e.g., CREATED → RUNNING)
Then: StateTransitionError is raised
And: state remains unchanged
And: error is logged
```

**Test Strategy**:
- **Unit**: Test all state machine transitions (valid and invalid)
- **Unit**: Test wait_until_ready() timeout behavior
- **Unit**: Test callback rejection in non-RUNNING states
- **Integration**: Test race condition prevention with timing variations
- **Performance**: Verify state transition overhead < 10μs

**Dependencies**:
- None (foundational change)

**Performance Impact**:
- Event loop acquisition: < 100μs
- State transition overhead: < 10μs
- No impact on hot path latency

---

### Feature 2: Candle Callback Migration

**User Story**: As a TradingEngine, I need to receive candles directly from DataCollector without going through TradingBot.

**Priority**: MUST (Blocking)

**Tasks**:
1. Implement `TradingEngine.on_candle_received(candle: Candle)` method with thread-safety
2. Copy callback logic from `TradingBot._on_candle_received` (lines 299-381 of current implementation)
3. Add `_candles_received: int` metric to TradingEngine
4. Add `_event_drop_count: int` metric to TradingEngine (moved from TradingBot)
5. Add `_callback_errors: int` metric to TradingEngine
6. Add `_metrics_lock: threading.Lock` to protect metric updates
7. Update callback to use `self._event_loop.call_soon_threadsafe()` instead of passed reference
8. Implement fail-safe error handling (no exceptions propagated to caller)
9. Add structured logging for callback errors and dropped events

**Acceptance Criteria**:
```gherkin
Given: candle arrives via DataCollector
When: engine state is RUNNING
And: event loop is active
Then: candle event is published to EventBus via run_coroutine_threadsafe
And: _candles_received metric is incremented
And: publish completes within 1ms (p99)

Given: candle arrives via DataCollector
When: engine state is not RUNNING
Then: candle is dropped with warning log
And: _event_drop_count is incremented
And: no exception is raised

Given: _event_loop is None (shutdown race)
When: on_candle_received() is called
Then: error is logged with context
And: _event_drop_count is incremented
And: no exception is raised

Given: EventBus queue is full
When: candle publishing is attempted
Then: asyncio.QueueFull is caught
And: candle is dropped
And: _event_drop_count is incremented
And: warning is logged with queue depth
```

**Test Strategy**:
- **Unit**: Test callback with various engine states (CREATED, INITIALIZED, RUNNING, STOPPING, STOPPED)
- **Unit**: Test thread-safety with concurrent callback invocations (10 threads × 100 calls)
- **Unit**: Test error handling for all failure modes (event loop None, queue full, exception in publish)
- **Integration**: Test WebSocket thread → AsyncIO event loop handoff
- **Performance**: Verify callback execution < 1ms (p99) with 10,000 candles

**Dependencies**:
- Feature 1 (Event Loop Management) must be complete
- EventBus must be initialized before callback can be invoked

**Performance Impact**:
- Hot path latency: target < 1ms (p99), no regression from baseline
- Memory overhead: ~50 bytes per candle (event object allocation)
- Thread context switch: 1 per candle (WebSocket → AsyncIO)

---

### Feature 3: Initialization Order Refactoring

**User Story**: As TradingBot, I need to initialize components in the correct dependency order to prevent race conditions.

**Priority**: MUST (Blocking)

**Tasks**:
1. Update TradingBot.initialize() method with new sequence:
   - Step 1: Create TradingEngine (EventBus created in __init__)
   - Step 2: Call engine.set_components(strategies, risk_manager)
   - Step 3: Start engine.run() in AsyncIO task
   - Step 4: **CRITICAL** Call await engine.wait_until_ready(timeout=5.0)
   - Step 5: Create DataCollector with engine.on_candle_received callback
   - Step 6: Connect DataCollector to WebSocket
2. Remove EventBus creation from TradingBot (now owned by TradingEngine)
3. Update set_components() signature to remove `trading_bot` parameter
4. Add initialization sequence validation (assert state after each step)
5. Add initialization timeout handling (fail if not ready within 5 seconds)

**Acceptance Criteria**:
```gherkin
Given: TradingBot.initialize() is called
When: initialization sequence executes
Then: EventBus is created before TradingEngine needs it
And: TradingEngine is created before DataCollector needs callback
And: engine.wait_until_ready() completes successfully
And: DataCollector callback is engine.on_candle_received
And: No circular reference exists (TradingEngine does not reference TradingBot)
And: Initialization completes within 5 seconds

Given: engine.run() fails to start within timeout
When: wait_until_ready() times out
Then: EngineNotRunningError is raised
And: initialization sequence is aborted
And: resources are cleaned up
And: error is logged with diagnostic info

Given: set_components() is called with trading_bot argument
When: new implementation is active
Then: TypeError is raised (parameter removed)
```

**Test Strategy**:
- **Integration**: Test full initialization sequence with mock components
- **Integration**: Test initialization timeout scenarios
- **Integration**: Verify no circular dependency via static analysis or dependency graph
- **Unit**: Test set_components() without trading_bot parameter

**Dependencies**:
- Feature 1 (Event Loop Management) must be complete
- Feature 2 (Callback Migration) must be complete

**Performance Impact**:
- Initialization time: unchanged (< 5 seconds)
- Synchronization barrier adds ~1-5ms to startup (one-time cost)

---

### Feature 4: TradingBot Cleanup

**User Story**: As TradingBot, I should not handle candle callbacks or manage event loops - these are engine responsibilities.

**Priority**: MUST (Blocking)

**Tasks**:
1. Delete `_on_candle_received` method from TradingBot (lines 299-381)
2. Delete `set_event_loop` method from TradingBot (lines 284-297)
3. Delete `_event_loop` attribute from TradingBot.__init__ (line 92)
4. Delete `_event_drop_count` attribute from TradingBot.__init__ (line 94)
5. Add `_lifecycle_state = LifecycleState.RUNNING` to TradingBot.run()
6. Update TradingBot shutdown sequence to use engine.stop() instead of direct event loop access
7. Update docstrings to reflect responsibility changes
8. Remove any remaining references to self._event_loop in TradingBot

**Acceptance Criteria**:
```gherkin
Given: TradingBot instance is created
When: checking instance attributes
Then: no _event_loop attribute exists
And: no _event_drop_count attribute exists
And: hasattr(bot, '_event_loop') returns False

Given: TradingBot instance is created
When: checking instance methods
Then: no _on_candle_received method exists
And: no set_event_loop method exists
And: hasattr(bot, '_on_candle_received') returns False

Given: TradingBot.run() is called
When: lifecycle state is checked
Then: state is LifecycleState.RUNNING

Given: TradingBot code is reviewed
When: searching for event loop references
Then: no references to self._event_loop exist
And: no references to self._event_drop_count exist
```

**Test Strategy**:
- **Unit**: Verify removed attributes don't exist using hasattr() checks
- **Unit**: Verify removed methods don't exist using hasattr() checks
- **Integration**: Verify lifecycle state transitions correctly
- **Static**: Run grep for removed attribute references in TradingBot

**Dependencies**:
- Feature 3 (Initialization Refactoring) must be complete

**Performance Impact**:
- None (code removal only)

---

### Feature 5: TradingEngine Interface Cleanup

**User Story**: As TradingEngine, I should have a clean interface that doesn't reference TradingBot.

**Priority**: MUST (Blocking)

**Tasks**:
1. Remove `trading_bot` parameter from `set_components()` signature
2. Remove `self.trading_bot = trading_bot` assignment from set_components (line 183)
3. Remove `self.trading_bot.set_event_loop(loop)` call from run() (line 653)
4. Remove `self.trading_bot` type annotation from class attributes
5. Update set_components() docstring to reflect signature change
6. Update class-level docstring to remove TradingBot references
7. Add validation to ensure no TradingBot references remain

**Acceptance Criteria**:
```gherkin
Given: set_components() is called
When: method signature is inspected
Then: no trading_bot parameter exists in signature

Given: TradingEngine instance is created and configured
When: checking instance attributes
Then: no trading_bot attribute exists
And: hasattr(engine, 'trading_bot') returns False

Given: TradingEngine documentation is reviewed
When: reading docstrings and comments
Then: all documentation accurately reflects new interface
And: no outdated TradingBot references exist

Given: TradingEngine code is reviewed
When: searching for TradingBot references
Then: no references to self.trading_bot exist
And: no imports of TradingBot class exist (circular import removed)
```

**Test Strategy**:
- **Unit**: Test set_components() call without trading_bot argument
- **Unit**: Verify no trading_bot attribute using hasattr()
- **Static**: Verify no references to self.trading_bot via grep
- **Static**: Verify no TradingBot imports in trading_engine.py

**Dependencies**:
- Feature 4 (TradingBot Cleanup) must be complete

**Performance Impact**:
- None (interface cleanup only)

---

### Feature 6: Monitoring and Observability

**User Story**: As an operator, I need to monitor event processing health and diagnose issues in production.

**Priority**: SHOULD (High)

**Tasks**:
1. Add `_events_published: int` metric to TradingEngine
2. Add `_publish_latency_ms: list[float]` histogram to TradingEngine
3. Add `_state_transitions: dict[str, int]` metric to TradingEngine
4. Add `_uptime_seconds: float` metric to TradingEngine
5. Implement `metrics` property returning thread-safe snapshot
6. Implement `health_check()` method returning engine health status
7. Add structured logging for state transitions with extra context
8. Document metrics ownership in architecture docs (claudedocs/)
9. Update monitoring dashboard configurations (optional)

**Acceptance Criteria**:
```gherkin
Given: engine is processing candles
When: events are dropped due to queue full
Then: _event_drop_count is incremented accurately
And: metric is thread-safe (no race conditions)

Given: engine is running
When: health_check() is called
Then: returns status="healthy" if state is RUNNING
And: returns status="unhealthy" if state is not RUNNING
And: includes event_loop_running status
And: includes eventbus_depth (queue size)
And: includes drop_rate calculation
And: includes uptime in seconds

Given: engine transitions state
When: transition occurs (e.g., INITIALIZED → RUNNING)
Then: structured log entry is created
And: log includes from_state and to_state
And: log includes timestamp and uptime
And: _state_transitions metric is incremented

Given: engine.metrics is called
When: retrieving metric snapshot
Then: all metrics are returned in dict format
And: metrics are thread-safe (locked during read)
And: metrics include candles_received, events_published, events_dropped
And: metrics include publish_latency_p50 and publish_latency_p99
And: metrics include current state and uptime
```

**Test Strategy**:
- **Unit**: Test metric increment on event drops
- **Unit**: Test health_check() returns accurate state
- **Unit**: Test metrics property thread-safety
- **Integration**: Verify metrics accuracy over 1000 candle processing
- **Performance**: Verify metrics overhead < 1μs per operation

**Dependencies**:
- Feature 2 (Callback Migration) must be complete

**Performance Impact**:
- Metrics update overhead: < 1μs per operation
- Lock contention: minimal (metrics read infrequently)
- Memory: ~100 bytes per metric + histogram storage

---

## Non-Functional Requirements

### NFR-1: Performance

**Requirement**: Refactoring SHALL NOT increase p99 latency by more than 10% from baseline.

**Measurement Method**:
- Establish baseline: Run current system with 10,000 candles, record p50/p99 latency
- Run identical test on refactored system
- Compare metrics: p99_new ≤ p99_baseline × 1.10

**Acceptance Criteria**:
- Hot path latency p99: ≤ baseline + 10% (e.g., if baseline is 8ms, max 8.8ms)
- Memory usage: ≤ baseline + 5%
- CPU usage: ≤ baseline + 5%
- Event loop acquisition: < 100μs
- State transition overhead: < 10μs

**Test Strategy**:
- Run performance benchmark before refactoring (baseline)
- Run same benchmark after refactoring (comparison)
- Automated performance gate in CI/CD (fails if regression > 10%)

---

### NFR-2: Reliability

**Requirement**: System SHALL maintain 99.9% uptime during deployment and operation.

**Measurement Method**:
- Blue-green deployment with health checks
- Monitor error rates during rollout
- Verify zero data loss (event_drop_count accurate)

**Acceptance Criteria**:
- Graceful degradation on EventBus queue full (no crashes)
- Zero data loss during normal operation (all candles processed or counted as dropped)
- Race conditions prevented via synchronization barrier
- Clean shutdown with in-flight candle processing

**Test Strategy**:
- Test all 5 failure modes (FM-1 through FM-5)
- Test shutdown during active data flow
- Test race condition scenarios
- Run 24-hour soak test in staging

---

### NFR-3: Maintainability

**Requirement**: Code complexity SHALL NOT increase from current baseline.

**Measurement Method**:
- Calculate cyclomatic complexity before and after
- Measure coupling metrics (dependencies between modules)
- Code review for clarity and simplicity

**Acceptance Criteria**:
- Cyclomatic complexity: ≤ current baseline
- Circular dependency eliminated (measurable via static analysis)
- Clear separation of concerns (TradingBot = orchestration, TradingEngine = execution)
- Comprehensive docstrings for new methods

**Test Strategy**:
- Run complexity analysis tools (radon, pylint)
- Dependency graph analysis (no circular imports)
- Code review checklist

---

### NFR-4: Backward Compatibility

**Requirement**: DataCollector interface SHALL remain unchanged.

**Rationale**: Minimize refactoring scope and risk by not changing data collection layer.

**Acceptance Criteria**:
- DataCollector constructor signature unchanged
- DataCollector callback signature unchanged (still receives Candle)
- No changes required to BinanceDataCollector implementation

**Test Strategy**:
- Verify DataCollector interface unchanged via type checks
- Integration test with real BinanceDataCollector

---

## Implementation Phases

### Phase 1: Preparation (Low Risk)
**Duration**: 1 hour

**Activities**:
1. Add comprehensive integration tests for current callback behavior (baseline tests)
2. Establish performance baseline (run load test, record p50/p99/memory/CPU)
3. Review and document current initialization sequence
4. Create feature flag for gradual rollout (USE_ENGINE_CALLBACK env var)

**Deliverables**:
- Baseline test suite passing
- Performance metrics recorded
- Feature flag infrastructure ready

**Rollback**: N/A (preparation only)

**Success Criteria**:
- All baseline tests pass
- Performance metrics recorded and documented

---

### Phase 2: TradingEngine Changes (Medium Risk)
**Duration**: 1-2 hours

**Activities**:
1. Add EngineState enum and state machine (Feature 1)
2. Add synchronization primitives (_ready_event, _state_lock, _metrics_lock)
3. Implement on_candle_received() method (Feature 2)
4. Modify run() to capture event loop and signal ready (Feature 1)
5. Implement wait_until_ready() method (Feature 1)
6. Move metrics from TradingBot to TradingEngine (Feature 6)
7. Update set_components() to remove trading_bot parameter (Feature 5)
8. Add unit tests for state machine and callback

**Deliverables**:
- TradingEngine code complete with new features
- Unit tests passing (>90% coverage)
- No integration with TradingBot yet (features dormant)

**Rollback**: Simply don't use new code yet (no integration point)

**Success Criteria**:
- All unit tests pass
- State machine tests cover all transitions
- Callback thread-safety test passes (10 threads × 100 calls)

---

### Phase 3: Integration Changes (Medium Risk)
**Duration**: 1 hour

**Activities**:
1. Modify TradingBot.initialize() with new sequence (Feature 3)
2. Wire DataCollector to TradingEngine.on_candle_received callback
3. Remove old TradingBot methods and attributes (Feature 4)
4. Enable feature flag (USE_ENGINE_CALLBACK=true)
5. Run integration tests with new implementation

**Deliverables**:
- TradingBot refactored and integrated
- Integration tests passing
- Feature flag enabled

**Rollback**: Set USE_ENGINE_CALLBACK=false, restart application

**Success Criteria**:
- All integration tests pass
- No circular dependency detected (static analysis)
- Initialization completes within 5 seconds

---

### Phase 4: Cleanup (Low Risk)
**Duration**: 30 minutes

**Activities**:
1. Remove trading_bot references from TradingEngine (Feature 5)
2. Remove old callback code from TradingBot (Feature 4)
3. Update docstrings and comments
4. Run full test suite (unit + integration)

**Deliverables**:
- Code cleanup complete
- All tests passing
- Documentation updated

**Rollback**: Restore deleted code from git

**Success Criteria**:
- No circular dependency exists
- All tests pass
- Code complexity ≤ baseline

---

### Phase 5: Validation (Critical)
**Duration**: 1-2 hours

**Activities**:
1. Run full test suite (unit + integration + performance)
2. Performance regression tests (compare to baseline)
3. Manual integration testing
4. Code review and approval
5. Static analysis (complexity, dependencies)

**Deliverables**:
- All tests passing
- Performance metrics within acceptable range
- Code review approved

**Rollback**: Full system rollback if any test fails

**Success Criteria**:
- All tests pass (unit, integration, performance)
- p99 latency ≤ baseline + 10%
- Memory usage ≤ baseline + 5%
- Code review approved

---

### Phase 6: Documentation (Low Risk)
**Duration**: 30 minutes

**Activities**:
1. Update architecture diagrams (claudedocs/)
2. Update developer documentation
3. Create migration notes for team
4. Document metrics ownership changes
5. Update monitoring dashboards (optional)

**Deliverables**:
- Architecture docs updated
- Migration notes complete
- Team notified of changes

**Rollback**: N/A (documentation only)

**Success Criteria**:
- All documentation updated and reviewed

---

### Phase 7: Deployment (Medium Risk)
**Duration**: Variable (depends on rollout strategy)

**Activities**:
1. Deploy to staging environment
2. Run 24-hour soak test in staging
3. Verify monitoring and health checks
4. Blue-green deployment to production
5. Monitor for 48 hours post-deployment
6. Remove feature flag if stable

**Deliverables**:
- Production deployment successful
- Monitoring confirms stability
- Feature flag removed

**Rollback**: Feature flag toggle (USE_ENGINE_CALLBACK=false) within 5 minutes

**Success Criteria**:
- Zero production errors in first 24 hours
- p99 latency ≤ baseline + 10%
- Event drop count within expected range
- Health checks passing

---

## Risk Mitigation

### High Risk: Race Condition on Startup

**Description**: DataCollector can send candles before TradingEngine.run() captures event loop, causing crashes or dropped events.

**Probability**: Medium (30%)
**Impact**: Critical (system crash or data loss)

**Mitigation**:
1. **Primary**: Synchronization barrier using asyncio.Event (wait_until_ready)
2. **Secondary**: Fail-safe in callback (reject if not RUNNING)
3. **Tertiary**: Integration tests with timing variations

**Detection**:
- Integration tests simulating race conditions
- Stress test with rapid initialization/connection

**Fallback**:
- Fail fast on timeout with clear error message
- Log diagnostic info (state, event loop status)

**Owner**: Architecture Team

---

### Medium Risk: Event Loss During Migration

**Description**: Events might be lost during transition if EventBus queue fills or callback errors not handled.

**Probability**: Medium (25%)
**Impact**: Medium (data loss but recoverable)

**Mitigation**:
1. **Primary**: Comprehensive state checking before accepting candles
2. **Secondary**: Event drop count monitoring with alerts
3. **Tertiary**: Graceful degradation on EventBus queue full

**Detection**:
- Event drop count monitoring
- Alert on drop count spike (> 10 in 1 minute)

**Fallback**:
- Log all dropped events with context
- Alert operations team on anomaly

**Owner**: Development Team

---

### Low Risk: Performance Regression

**Description**: Refactoring might introduce performance overhead.

**Probability**: Low (10%)
**Impact**: High (user experience degradation)

**Mitigation**:
1. **Primary**: Performance test gate in CI/CD
2. **Secondary**: Automated latency monitoring
3. **Tertiary**: Feature flag for instant rollback

**Detection**:
- Automated performance tests (p99 threshold)
- Real-time latency monitoring

**Fallback**:
- Rollback via feature flag if p99 > baseline + 20%
- Investigate and optimize in development

**Owner**: QA Team

---

### Low Risk: Thread Safety Issues

**Description**: Concurrent access to shared state might cause race conditions.

**Probability**: Low (5%)
**Impact**: Critical (data corruption or crashes)

**Mitigation**:
1. **Primary**: Use threading.Lock for metrics, asyncio.Lock for state
2. **Secondary**: ThreadSanitizer in CI
3. **Tertiary**: Stress tests with concurrent callbacks

**Detection**:
- ThreadSanitizer in CI/CD pipeline
- Stress test with 10+ concurrent threads

**Fallback**:
- Add more granular locking if races detected
- Isolate state per thread if necessary

**Owner**: QA Team

---

## Dependencies

### Internal Dependencies
- **EventBus** must be created before TradingEngine can use it
- **TradingEngine** must be ready (RUNNING state) before DataCollector starts sending candles
- **Strategies** must be registered before engine can publish events

### External Dependencies
- None (internal refactoring only)
- No changes to BinanceDataCollector required
- No changes to Strategy interface required

### Team Dependencies
- Architecture approval for state machine design
- QA team for performance baseline and regression tests
- DevOps team for deployment strategy and rollback plan

---

## Timeline Estimate

| Phase | Duration | Dependencies | Risk Level |
|-------|----------|--------------|------------|
| Phase 1: Preparation | 1 hour | None | Low |
| Phase 2: TradingEngine Changes | 1-2 hours | Phase 1 | Medium |
| Phase 3: Integration | 1 hour | Phase 2 | Medium |
| Phase 4: Cleanup | 30 min | Phase 3 | Low |
| Phase 5: Validation | 1-2 hours | Phase 4 | Critical |
| Phase 6: Documentation | 30 min | Phase 5 | Low |
| Phase 7: Deployment | Variable | Phase 6 | Medium |

**Total Estimated Time**: 4-6 hours (excluding deployment monitoring)

**Critical Path**: Phase 1 → Phase 2 → Phase 3 → Phase 5 (cannot parallelize)

**Parallelization Opportunities**:
- Documentation (Phase 6) can start during Phase 5 validation
- Performance tests can run in parallel with integration tests

---

## Acceptance Testing

### Test Suite Requirements

**Unit Tests** (Target: >90% coverage):
- State machine transitions (all valid and invalid combinations)
- Callback behavior in all engine states
- Thread-safety (concurrent callback invocations)
- Error handling (all failure modes)
- Metrics accuracy

**Integration Tests**:
- Full initialization sequence
- End-to-end candle flow (WebSocket → Strategy)
- Race condition prevention
- Shutdown sequence

**Performance Tests**:
- Latency benchmark (10,000 candles)
- Memory usage over time
- CPU usage under load
- Stress test (concurrent threads)

**Failure Mode Tests**:
- Event loop stopped (FM-1)
- Callback before run() (FM-2)
- EventBus queue full (FM-3)
- WebSocket reconnect (FM-4)
- Strategy exception (FM-5)

---

## Rollback Strategy

### Rollback Triggers
- p99 latency increases by > 20% from baseline
- Event drop count increases by > 10% from baseline
- Any critical errors in production (crashes, data corruption)
- Health check failures lasting > 5 minutes

### Rollback Procedure

**Method 1: Feature Flag (Preferred)**
1. Set environment variable: `USE_ENGINE_CALLBACK=false`
2. Restart application (hot reload if supported)
3. Verify old implementation active
4. Monitor for 1 hour to confirm stability
5. Investigate issue in development environment

**Rollback Time**: < 5 minutes

**Method 2: Code Revert (If Flag Unavailable)**
1. Revert git commit to previous stable version
2. Rebuild application
3. Deploy via blue-green switch
4. Verify old implementation active
5. Monitor for 1 hour

**Rollback Time**: < 15 minutes (depends on build/deploy pipeline)

### Post-Rollback Actions
1. Preserve logs and metrics from failed deployment
2. Create postmortem document
3. Investigate root cause in development
4. Fix issues before retry
5. Update rollback procedure if lessons learned

---

## Metrics and KPIs

### Success Metrics

**Performance KPIs**:
- Hot path latency p99: ≤ baseline + 10%
- Event loop acquisition time: < 100μs
- State transition overhead: < 10μs
- Memory usage: ≤ baseline + 5%

**Reliability KPIs**:
- Event drop rate: ≤ baseline (0% during normal operation)
- Uptime during deployment: ≥ 99.9%
- Zero critical errors in first 48 hours
- Health check success rate: 100%

**Code Quality KPIs**:
- Test coverage: ≥ 90%
- Cyclomatic complexity: ≤ baseline
- Circular dependencies: 0 (eliminated)
- Code review approval: 100%

### Monitoring Dashboard

**Key Metrics to Display**:
- engine_state (current state)
- candles_received (total count)
- events_published (total count)
- events_dropped (total count)
- publish_latency_p50 (median latency)
- publish_latency_p99 (99th percentile latency)
- event_drop_rate (drops per minute)
- uptime_seconds (engine uptime)

**Alerts**:
- Event drop rate > 10 drops/minute (WARNING)
- p99 latency > baseline + 20% (WARNING)
- Engine state != RUNNING for > 5 minutes (CRITICAL)
- Health check failure (CRITICAL)

---

## Appendices

### Appendix A: State Machine Diagram

```
EngineState Transitions:

CREATED ──set_components()──> INITIALIZED ──run()──> RUNNING
                                                         │
                                                         │
                                                    stop()
                                                         │
                                                         ↓
                              STOPPED <──────────── STOPPING

Invalid Transitions:
- CREATED → RUNNING (must call set_components first)
- INITIALIZED → STOPPED (must start running first)
- Any state → CREATED (cannot reset to initial state)
```

### Appendix B: Thread Safety Model

**Threading Architecture**:
```
WebSocket Thread (BinanceDataCollector)
    ↓ (callback invocation)
TradingEngine.on_candle_received()
    ↓ (run_coroutine_threadsafe)
AsyncIO Event Loop Thread
    ↓ (async event publishing)
EventBus → Strategies
```

**Locks**:
- `_state_lock` (asyncio.Lock): Protects state transitions (event loop thread only)
- `_metrics_lock` (threading.Lock): Protects metric updates (any thread)
- Event loop reference is immutable after capture (no lock needed)

### Appendix C: Glossary

- **Circular Dependency**: When component A depends on B, and B depends on A
- **Event Loop**: AsyncIO's core mechanism for running asynchronous code
- **Hot Path**: Critical code path executed frequently (e.g., every candle)
- **State Machine**: Formal model defining valid states and transitions
- **Thread-Safe**: Safe to call from multiple threads concurrently
- **Synchronization Barrier**: Coordination primitive ensuring ordering
- **Graceful Degradation**: System continues operating at reduced capacity under failure
- **Blue-Green Deployment**: Deployment strategy with zero-downtime rollout

---

## Document Control

**Version History**:
- v1.0 (2025-01-03): Initial PRD based on enhanced refactoring spec v2

**Approvals Required**:
- [ ] Architecture Team Lead
- [ ] Development Team Lead
- [ ] QA Team Lead
- [ ] DevOps Team Lead

**Review Schedule**:
- Post-implementation retrospective within 1 week of deployment
- Update PRD with lessons learned

**Related Documents**:
- Source specification: claudedocs/refactor_trading_engine_dependency_v2.md
- Architecture docs: claudedocs/ (to be updated)
- Test plan: (to be created during Phase 1)

---

**END OF PRD**
