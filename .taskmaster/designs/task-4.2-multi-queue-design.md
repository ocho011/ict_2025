# Subtask 4.2: Multi-Queue System Design

**Parent Task**: Task #4 - Event-Driven Architecture & Async Queue System
**Dependency**: Subtask 4.1 (EventBus Core) ✅ COMPLETE
**Complexity**: 6/10 (Medium)
**Status**: Design Phase

## 1. Objective

Implement three priority-based asyncio queues (data, signal, order) with different overflow strategies to prevent event jamming and enable natural backpressure in the trading system.

**Scope**:
- Add `_queues` dict initialization to EventBus
- Implement async `publish()` method with timeout handling
- Add `get_queue_stats()` monitoring helper
- Create 6 comprehensive unit tests

**Out of Scope** (deferred to later subtasks):
- Queue processors (`_process_queue()` in 4.3)
- Lifecycle management (`start()`/`stop()` in 4.4)
- Handler execution logic (4.3)

## 2. Current State Analysis

**Existing EventBus Structure** (from 4.1):
```python
class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self.logger = logging.getLogger(__name__)
        self._running: bool = False
        self.logger.debug("EventBus initialized")

    def subscribe(event_type: EventType, handler: Callable) -> None:
        # Adds handler to _subscribers[event_type]
        pass

    def _get_handlers(event_type: EventType) -> List[Callable]:
        # Returns list of handlers for event_type
        pass
```

**What's Missing**:
1. No queue storage mechanism
2. No event publishing capability
3. No overflow handling strategy
4. No queue monitoring utilities

## 3. Three-Queue Architecture Design

### Queue Specifications

| Queue Name | Max Size | Purpose | Overflow Strategy | Timeout |
|------------|----------|---------|-------------------|---------|
| **data** | 1000 | Candle updates, market data | **Drop** (latest matters) | 1.0s |
| **signal** | 100 | Strategy signals | **Block** (backpressure) | 5.0s |
| **order** | 50 | Exchange orders | **Never drop** (critical) | None |

### Design Rationale

**Data Queue (1000 events, droppable)**:
- **Purpose**: High-frequency candle stream (10 symbols × 1 event/sec = 10/sec)
- **Overflow**: Drop oldest events when timeout exceeded
- **Rationale**: Latest candle matters most, missing one won't break strategy (next arrives soon)
- **Capacity**: 1000 events = 16 min backlog buffer at 10 events/sec

**Signal Queue (100 events, must process)**:
- **Purpose**: Strategy-generated trading signals (1 signal per 10 candles = 1/sec)
- **Overflow**: Block on full (creates backpressure to strategy)
- **Rationale**: Every signal must be evaluated, dropping = missed trading opportunity
- **Capacity**: 100 events = 10 min backlog assuming 1 signal per 10 candles

**Order Queue (50 events, critical)**:
- **Purpose**: Orders to exchange (0.1 orders/sec = rare)
- **Overflow**: Block indefinitely, never timeout
- **Rationale**: Dropping order = potential financial loss, system must handle all orders
- **Capacity**: 50 events = 10 sec processing buffer at 0.2s per order

### Natural Backpressure Flow

```
Exchange slow → Order queue fills → Blocks order creation
                ↓
           Signal processing slows → Signal queue fills
                ↓
           Strategy slows → Fewer signals generated
                ↓
           Data queue has capacity → Continues processing
```

**Benefits**:
- System self-regulates under load
- Critical operations (orders) protected
- Non-critical operations (data) gracefully degrade
- No cascading failures

## 4. EventBus Class Extensions

### 4.1 Queue Initialization (in `__init__`)

**Location**: `src/core/event_handler.py`, EventBus.__init__() method

**Implementation**:
```python
def __init__(self):
    """
    Initialize EventBus with subscriber registry and multi-queue system.

    Attributes:
        _subscribers: Maps EventType to list of handler functions
        _queues: Three priority queues (data, signal, order)
        logger: Logger instance for debug/error tracking
        _running: Lifecycle flag (used in Subtask 4.4)
        _drop_count: Counter for dropped events (monitoring)
    """
    # Subscriber registry (from Subtask 4.1)
    self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)

    # Three priority queues with different capacities
    self._queues: Dict[str, asyncio.Queue] = {
        'data': asyncio.Queue(maxsize=1000),    # High throughput, can drop
        'signal': asyncio.Queue(maxsize=100),   # Medium priority, must process
        'order': asyncio.Queue(maxsize=50)      # Critical, never drop
    }

    # Logger for debugging
    self.logger = logging.getLogger(__name__)

    # Lifecycle flag (will be used in Subtask 4.4)
    self._running: bool = False

    # Monitoring: track dropped events per queue
    self._drop_count: Dict[str, int] = {
        'data': 0,
        'signal': 0,
        'order': 0
    }

    self.logger.debug(
        "EventBus initialized with queues: "
        f"data({1000}), signal({100}), order({50})"
    )
```

**Design Decisions**:
1. **Dict[str, asyncio.Queue]**: String keys for simplicity, easy to extend with new queues
2. **maxsize parameter**: Explicit capacity limits prevent unbounded memory growth
3. **_drop_count tracking**: Essential for monitoring and alerting on event loss
4. **DEBUG logging**: Include queue capacities for operational visibility

### 4.2 Publish Method Design

**Signature**:
```python
async def publish(
    self,
    event: Event,
    queue_name: str = 'data'
) -> None:
    """
    Publish event to specified queue with overflow handling.

    This method implements the "publish" side of the pub-sub pattern.
    Events are routed to one of three priority queues based on criticality.

    Args:
        event: Event to publish (from src.models.event.Event)
        queue_name: Target queue ('data', 'signal', 'order'). Defaults to 'data'.

    Raises:
        ValueError: If queue_name is not in ['data', 'signal', 'order']
        asyncio.TimeoutError: For signal/order queues if timeout exceeded

    Overflow Handling:
        - data queue: Drop event on timeout, log warning, increment drop_count
        - signal queue: Block for up to 5s, raise TimeoutError if full
        - order queue: Block indefinitely (no timeout), never drop

    Example:
        ```python
        bus = EventBus()

        # High-frequency data (may drop under load)
        await bus.publish(
            Event(EventType.CANDLE_UPDATE, candle),
            queue_name='data'
        )

        # Trading signal (must process, creates backpressure)
        await bus.publish(
            Event(EventType.SIGNAL_GENERATED, signal),
            queue_name='signal'
        )

        # Critical order (never drops, blocks indefinitely)
        await bus.publish(
            Event(EventType.ORDER_PLACED, order),
            queue_name='order'
        )
        ```

    Notes:
        - Data queue drops are expected under high load (design feature)
        - Signal/order timeouts indicate system overload (needs investigation)
        - Monitor drop_count via get_queue_stats() for operational alerts
    """
```

**Implementation Logic**:
```python
async def publish(self, event: Event, queue_name: str = 'data') -> None:
    # 1. Validate queue name
    if queue_name not in self._queues:
        raise ValueError(
            f"Invalid queue_name '{queue_name}'. "
            f"Must be one of: {list(self._queues.keys())}"
        )

    queue = self._queues[queue_name]

    # 2. Define timeout strategy per queue type
    timeout_map = {
        'data': 1.0,    # Drop quickly for high-frequency data
        'signal': 5.0,  # Wait longer for important signals
        'order': None   # Never timeout for critical orders
    }
    timeout = timeout_map[queue_name]

    # 3. Attempt to publish with timeout
    try:
        if timeout is None:
            # Order queue: block indefinitely, never drop
            await queue.put(event)
            self.logger.debug(
                f"Published {event.event_type.value} to {queue_name} queue "
                f"(qsize={queue.qsize()})"
            )
        else:
            # Data/Signal queues: timeout-based overflow handling
            await asyncio.wait_for(
                queue.put(event),
                timeout=timeout
            )
            self.logger.debug(
                f"Published {event.event_type.value} to {queue_name} queue "
                f"(qsize={queue.qsize()})"
            )

    except asyncio.TimeoutError:
        # 4. Handle timeout based on queue criticality
        if queue_name == 'data':
            # Data queue: drop is acceptable, log and continue
            self._drop_count[queue_name] += 1
            self.logger.warning(
                f"Dropped {event.event_type.value} from {queue_name} queue "
                f"(full, timeout={timeout}s). "
                f"Total drops: {self._drop_count[queue_name]}"
            )
        else:
            # Signal/Order queues: timeout is serious, re-raise
            self.logger.error(
                f"Failed to publish {event.event_type.value} to "
                f"{queue_name} queue (timeout={timeout}s, "
                f"qsize={queue.qsize()}). System overload!"
            )
            raise
```

**Timeout Strategy Rationale**:

| Queue | Timeout | On Timeout | Rationale |
|-------|---------|-----------|-----------|
| data | 1.0s | Drop + log | Latest candle matters, missing one acceptable |
| signal | 5.0s | Raise | Every signal critical, timeout = overload |
| order | None | Block forever | Financial risk if dropped, must process all |

**Error Handling Strategy**:
1. **ValueError**: Invalid queue_name → fail fast, programming error
2. **TimeoutError (data)**: Drop event, log warning, increment counter → expected behavior
3. **TimeoutError (signal/order)**: Re-raise, log error → system overload, needs intervention

### 4.3 Queue Stats Helper Design

**Signature**:
```python
def get_queue_stats(self) -> Dict[str, Dict[str, int]]:
    """
    Get current queue statistics for monitoring.

    Returns dict with queue sizes, capacities, and drop counts:
    {
        'data': {'size': 42, 'maxsize': 1000, 'drops': 5},
        'signal': {'size': 3, 'maxsize': 100, 'drops': 0},
        'order': {'size': 0, 'maxsize': 50, 'drops': 0}
    }

    Useful for:
    - Operational monitoring and alerting
    - Performance tuning (queue sizing)
    - Capacity planning
    - Debugging event flow bottlenecks

    Example:
        ```python
        stats = bus.get_queue_stats()

        # Alert if data queue is consistently full
        if stats['data']['size'] > 900:
            logger.warning("Data queue near capacity!")

        # Alert on any signal drops (should never happen)
        if stats['signal']['drops'] > 0:
            logger.critical("Signal queue dropped events!")
        ```
    """
    return {
        queue_name: {
            'size': queue.qsize(),
            'maxsize': queue.maxsize,
            'drops': self._drop_count[queue_name]
        }
        for queue_name, queue in self._queues.items()
    }
```

**Design Decisions**:
1. **Synchronous method**: Stats collection is fast, no need for async
2. **Comprehensive data**: Include size, capacity, and drops for full picture
3. **Dict structure**: Easy to serialize to JSON for monitoring systems
4. **Per-queue drops**: Track separately for granular alerting

## 5. Test Strategy

### Test Suite: `tests/core/test_event_handler.py::TestEventBusQueues`

**Test 1: Queue Initialization**
```python
def test_queues_initialized_with_correct_sizes():
    """Verify all three queues created with correct maxsize."""
    bus = EventBus()

    stats = bus.get_queue_stats()

    assert 'data' in stats
    assert 'signal' in stats
    assert 'order' in stats

    assert stats['data']['maxsize'] == 1000
    assert stats['signal']['maxsize'] == 100
    assert stats['order']['maxsize'] == 50

    # All queues start empty
    assert stats['data']['size'] == 0
    assert stats['signal']['size'] == 0
    assert stats['order']['size'] == 0

    # No drops initially
    assert stats['data']['drops'] == 0
    assert stats['signal']['drops'] == 0
    assert stats['order']['drops'] == 0
```

**Test 2: Data Queue Drop Behavior**
```python
@pytest.mark.asyncio
async def test_data_queue_drops_events_when_full():
    """Verify data queue drops events after timeout when full."""
    bus = EventBus()

    # Fill data queue to capacity (1000 events)
    for i in range(1000):
        event = Event(EventType.CANDLE_UPDATE, {'id': i})
        await bus.publish(event, queue_name='data')

    # Verify queue is full
    stats = bus.get_queue_stats()
    assert stats['data']['size'] == 1000

    # Attempt to publish one more (should drop due to timeout)
    overflow_event = Event(EventType.CANDLE_UPDATE, {'id': 1000})

    # Should not raise exception (drops gracefully)
    await bus.publish(overflow_event, queue_name='data')

    # Verify drop was counted
    stats_after = bus.get_queue_stats()
    assert stats_after['data']['drops'] == 1

    # Queue still at capacity (event was dropped, not added)
    assert stats_after['data']['size'] == 1000
```

**Test 3: Signal Queue Timeout Behavior**
```python
@pytest.mark.asyncio
async def test_signal_queue_raises_timeout_when_full():
    """Verify signal queue raises TimeoutError when full (no drops)."""
    bus = EventBus()

    # Fill signal queue to capacity (100 events)
    for i in range(100):
        event = Event(EventType.SIGNAL_GENERATED, {'id': i})
        await bus.publish(event, queue_name='signal')

    # Verify queue is full
    stats = bus.get_queue_stats()
    assert stats['signal']['size'] == 100

    # Attempt to publish one more (should raise TimeoutError)
    overflow_event = Event(EventType.SIGNAL_GENERATED, {'id': 100})

    with pytest.raises(asyncio.TimeoutError):
        await bus.publish(overflow_event, queue_name='signal')

    # Verify no drops (signal queue never drops)
    stats_after = bus.get_queue_stats()
    assert stats_after['signal']['drops'] == 0
```

**Test 4: Order Queue Never Drops**
```python
@pytest.mark.asyncio
async def test_order_queue_blocks_indefinitely_when_full():
    """Verify order queue blocks without timeout (never drops)."""
    bus = EventBus()

    # Fill order queue to capacity (50 events)
    for i in range(50):
        event = Event(EventType.ORDER_PLACED, {'id': i})
        await bus.publish(event, queue_name='order')

    # Verify queue is full
    stats = bus.get_queue_stats()
    assert stats['order']['size'] == 50

    # Attempt to publish with short timeout to verify blocking behavior
    overflow_event = Event(EventType.ORDER_PLACED, {'id': 50})

    # Use wait_for to simulate timeout (order queue itself has no timeout)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            bus.publish(overflow_event, queue_name='order'),
            timeout=0.5  # Short timeout to verify blocking
        )

    # Verify no drops (order queue NEVER drops)
    stats_after = bus.get_queue_stats()
    assert stats_after['order']['drops'] == 0
```

**Test 5: Invalid Queue Name Validation**
```python
@pytest.mark.asyncio
async def test_publish_raises_valueerror_for_invalid_queue():
    """Verify publish() validates queue_name parameter."""
    bus = EventBus()
    event = Event(EventType.CANDLE_UPDATE, {})

    with pytest.raises(ValueError) as exc_info:
        await bus.publish(event, queue_name='invalid_queue')

    assert "Invalid queue_name 'invalid_queue'" in str(exc_info.value)
    assert "data" in str(exc_info.value)
    assert "signal" in str(exc_info.value)
    assert "order" in str(exc_info.value)
```

**Test 6: Queue Stats Accuracy**
```python
@pytest.mark.asyncio
async def test_get_queue_stats_reflects_current_state():
    """Verify get_queue_stats() returns accurate real-time data."""
    bus = EventBus()

    # Initial state
    stats = bus.get_queue_stats()
    assert stats['data']['size'] == 0

    # Publish 10 events to data queue
    for i in range(10):
        event = Event(EventType.CANDLE_UPDATE, {'id': i})
        await bus.publish(event, queue_name='data')

    # Verify stats updated
    stats_after = bus.get_queue_stats()
    assert stats_after['data']['size'] == 10
    assert stats_after['data']['drops'] == 0

    # Publish 5 to signal, 2 to order
    for i in range(5):
        await bus.publish(
            Event(EventType.SIGNAL_GENERATED, {'id': i}),
            queue_name='signal'
        )
    for i in range(2):
        await bus.publish(
            Event(EventType.ORDER_PLACED, {'id': i}),
            queue_name='order'
        )

    # Verify all queues tracked independently
    final_stats = bus.get_queue_stats()
    assert final_stats['data']['size'] == 10
    assert final_stats['signal']['size'] == 5
    assert final_stats['order']['size'] == 2
```

### Test Execution Command
```bash
pytest tests/core/test_event_handler.py::TestEventBusQueues -v \
    --cov=src.core.event_handler --cov-report=term-missing
```

**Expected Coverage**: 100% for new queue-related code (lines added in 4.2)

## 6. Integration Points

### 6.1 Dependencies (from 4.1)

**EventBus class structure**:
- `__init__()`: Extend with `_queues` and `_drop_count` initialization
- `_subscribers`: Already exists, no changes needed
- `logger`: Already exists, will log queue events
- `_running`: Already exists, no changes in this subtask

**Imports needed** (no new imports):
- `asyncio`: Already imported for future use
- `Event`, `EventType`: Already imported from src.models.event

### 6.2 Dependents (Subtasks 4.3, 4.4)

**Subtask 4.3** (Queue Processors):
- Will use `self._queues` to spawn processors
- Will call `_get_handlers()` to dispatch events
- Will monitor queue via `get_queue_stats()`

**Subtask 4.4** (Lifecycle Management):
- `start()` will verify queues initialized
- `stop()` will set `_running=False` to stop processors
- `shutdown()` will drain all three queues using `queue.join()`

**TradingEngine** (Subtask 4.5):
- Will call `publish()` to route events:
  - `CANDLE_CLOSED` → data queue
  - `SIGNAL_GENERATED` → signal queue
  - `ORDER_PLACED` → order queue

## 7. Quality Assurance

### Code Review Checklist

**Correctness**:
- [ ] All three queues initialized with correct maxsize
- [ ] publish() validates queue_name parameter
- [ ] Timeout strategy matches specification (1.0s, 5.0s, None)
- [ ] Data queue drops gracefully, signal/order raise on timeout
- [ ] Drop counts incremented correctly
- [ ] get_queue_stats() returns all required fields

**Error Handling**:
- [ ] ValueError for invalid queue_name
- [ ] TimeoutError handling per queue type
- [ ] Logging at appropriate levels (debug, warning, error)
- [ ] No silent failures

**Testing**:
- [ ] All 6 unit tests implemented
- [ ] 100% coverage for new code
- [ ] Tests cover happy path and error cases
- [ ] Async tests use @pytest.mark.asyncio

**Documentation**:
- [ ] Full docstrings with examples
- [ ] Timeout strategy rationale documented
- [ ] Overflow behavior clearly explained
- [ ] Integration notes for future subtasks

### Static Analysis Commands

```bash
# Type checking
mypy src/core/event_handler.py --strict

# Linting
flake8 src/core/event_handler.py --max-line-length=88
pylint src/core/event_handler.py --max-line-length=88

# Code formatting
black src/core/event_handler.py --check
```

### Performance Validation

**Expected Performance**:
- publish() latency: <1ms for non-full queues
- Throughput: 1000+ events/sec per queue
- Memory: ~1.5MB for all queues at capacity (Event objects ~1KB each)

**Load Test** (in Test 6):
```python
# Publish 1000 events rapidly
start = time.time()
for i in range(1000):
    await bus.publish(Event(EventType.CANDLE_UPDATE, {'id': i}))
elapsed = time.time() - start

assert elapsed < 1.0  # Should complete in <1 second
```

## 8. Success Criteria

### Functional Requirements

1. ✅ Three queues initialized with correct capacities (1000, 100, 50)
2. ✅ publish() routes events to specified queue
3. ✅ Data queue drops events after 1.0s timeout
4. ✅ Signal queue raises TimeoutError after 5.0s timeout
5. ✅ Order queue blocks indefinitely (no timeout)
6. ✅ Drop counts tracked per queue
7. ✅ get_queue_stats() returns accurate real-time data
8. ✅ Invalid queue_name raises ValueError

### Test Requirements

1. ✅ 6 comprehensive unit tests implemented
2. ✅ 100% code coverage for new queue functionality
3. ✅ All tests pass with pytest
4. ✅ Async tests properly decorated with @pytest.mark.asyncio

### Non-Functional Requirements

1. ✅ publish() completes in <1ms for non-full queues
2. ✅ No memory leaks (queues bounded by maxsize)
3. ✅ Thread-safe queue operations (asyncio.Queue guarantees)
4. ✅ Clear error messages for all failure modes

### Documentation Requirements

1. ✅ Full docstrings with examples for all methods
2. ✅ Overflow strategy rationale documented
3. ✅ Integration points with future subtasks documented
4. ✅ Monitoring guidance (get_queue_stats() usage)

## 9. Implementation Sequence

**Step 1**: Extend EventBus.__init__() (5 min)
- Add `_queues` dict with three asyncio.Queue instances
- Add `_drop_count` dict for monitoring
- Update initialization logging

**Step 2**: Implement publish() method (15 min)
- Add method signature with docstring
- Implement queue_name validation
- Implement timeout strategy per queue
- Add TimeoutError handling (drop for data, raise for signal/order)
- Add debug/warning/error logging

**Step 3**: Implement get_queue_stats() helper (5 min)
- Add method signature with docstring
- Return dict with size, maxsize, drops per queue
- Add usage examples in docstring

**Step 4**: Create unit tests (20 min)
- Implement 6 tests in TestEventBusQueues class
- Ensure proper async test decoration
- Verify all tests pass

**Step 5**: Verify coverage and quality (5 min)
- Run pytest with coverage report
- Verify 100% coverage on new code
- Run static analysis (mypy, flake8)

**Total Estimated Time**: 50 minutes

## 10. Next Steps

**After Subtask 4.2 Complete**:

→ **Subtask 4.3**: Async Queue Processors
- Implement `_process_queue(queue_name)` async loop
- Poll queue with timeout (0.1s)
- Call `_get_handlers()` to get registered handlers
- Execute handlers with error isolation
- Handle TimeoutError gracefully (no events = continue loop)

→ **Subtask 4.4**: Lifecycle Management
- Implement `start()` to spawn 3 processor tasks
- Implement `stop()` to set `_running=False`
- Implement `shutdown()` to drain queues with timeout

→ **Subtask 4.5**: TradingEngine Integration
- Register handlers via `subscribe()`
- Call `publish()` to route events to correct queues
- Implement thin wrapper handlers that delegate to components

## 11. References

**Parent Design**:
- `.taskmaster/designs/task-4-event-architecture-design.md` (Section 3: Queue System Design)

**Related Files**:
- `src/core/event_handler.py` - EventBus implementation
- `src/models/event.py` - Event and EventType definitions
- `tests/core/test_event_handler.py` - Test suite

**Design Patterns**:
- Priority Queue Pattern (different queue capacities for different event types)
- Backpressure Pattern (blocking on critical queues creates natural rate limiting)
- Drop-tail Queue Pattern (drop oldest when data queue full)

**External References**:
- AnyIO library timeout patterns: `asyncio.wait_for()` with timeout parameter
- asyncio.Queue documentation: maxsize parameter and put() behavior
- Timeout propagation in nested cancel scopes (AnyIO best practices)
