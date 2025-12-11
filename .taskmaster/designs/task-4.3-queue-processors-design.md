# Subtask 4.3: Async Queue Processors Design

**Parent Task**: Task #4 - Event-Driven Architecture & Async Queue System
**Dependencies**: Subtask 4.1 (EventBus Core) ✅ | Subtask 4.2 (Multi-queue) ✅
**Complexity**: 7/10 (Medium-High)
**Status**: Design Phase

## 1. Objective

Implement continuous async event processing loops that poll queues, dispatch events to registered handlers, and provide robust error isolation to prevent processor crashes.

**Scope**:
- Implement `_process_queue(queue_name)` async method
- Handler execution with sync/async detection
- Error isolation per handler (one fails → others continue)
- Timeout handling for empty queues
- Lifecycle integration with `_running` flag

**Out of Scope** (deferred to Subtask 4.4):
- Starting processor tasks (`start()` method)
- Stopping processors (`stop()` method)
- Graceful shutdown with queue draining (`shutdown()` method)

## 2. Current State Analysis

**Existing EventBus Components** (from 4.1 and 4.2):

```python
class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._queues: Dict[str, asyncio.Queue] = {
            'data': asyncio.Queue(maxsize=1000),
            'signal': asyncio.Queue(maxsize=100),
            'order': asyncio.Queue(maxsize=50)
        }
        self.logger = logging.getLogger(__name__)
        self._running: bool = False
        self._drop_count: Dict[str, int] = {'data': 0, 'signal': 0, 'order': 0}

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        # Adds handler to _subscribers[event_type]
        pass

    def _get_handlers(self, event_type: EventType) -> List[Callable]:
        # Returns list of handlers for event_type
        return self._subscribers[event_type]

    async def publish(self, event: Event, queue_name: str = 'data') -> None:
        # Puts event into specified queue with timeout handling
        pass

    def get_queue_stats(self) -> Dict[str, Dict[str, int]]:
        # Returns queue sizes, maxsizes, drop counts
        pass
```

**What's Missing**:
1. Event processing loop (`_process_queue()`)
2. Handler execution logic (sync/async detection)
3. Error isolation per handler
4. Empty queue timeout handling

## 3. Queue Processor Design

### 3.1 Method Signature

```python
async def _process_queue(self, queue_name: str) -> None:
    """
    Continuously process events from the specified queue.

    This is the core event processing loop. It runs continuously while
    _running=True, polling the queue for events and dispatching them to
    registered handlers with comprehensive error isolation.

    Args:
        queue_name: Name of queue to process ('data', 'signal', or 'order')

    Process Flow:
        1. Poll queue with 0.1s timeout (non-blocking)
        2. Get handlers registered for event type
        3. Execute each handler sequentially (sync or async)
        4. Isolate handler errors (one fails → others continue)
        5. Mark queue task as done
        6. Repeat until _running=False

    Error Handling:
        - Handler exceptions: Logged with exc_info=True, continue processing
        - Queue TimeoutError: Expected when empty, continue loop
        - Other exceptions: Logged as critical, continue loop

    Performance:
        - Handler execution is sequential (guarantees ordering)
        - Empty queue polling: 10 iterations/sec (0.1s timeout)
        - Handlers should be fast (<10ms); heavy work → spawn tasks

    Example:
        ```python
        # In Subtask 4.4, start() will spawn processor tasks:
        async def start(self):
            self._running = True
            tasks = [
                asyncio.create_task(self._process_queue('data')),
                asyncio.create_task(self._process_queue('signal')),
                asyncio.create_task(self._process_queue('order'))
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
        ```

    Notes:
        - Sequential handler execution prevents race conditions
        - Handler isolation prevents cascade failures
        - 0.1s timeout allows responsive shutdown (checks _running flag)
        - Method is private (internal to EventBus lifecycle)
    """
```

### 3.2 Implementation Logic

```python
async def _process_queue(self, queue_name: str) -> None:
    """Process events from queue continuously."""
    queue = self._queues[queue_name]

    self.logger.info(f"Starting {queue_name} queue processor")

    while self._running:
        try:
            # 1. Poll queue with timeout (non-blocking)
            event = await asyncio.wait_for(
                queue.get(),
                timeout=0.1  # Check _running flag 10x per second
            )

            # 2. Get handlers for this event type
            handlers = self._get_handlers(event.event_type)

            if not handlers:
                self.logger.debug(
                    f"No handlers for {event.event_type.value} in {queue_name} queue"
                )

            # 3. Execute each handler sequentially with error isolation
            for handler in handlers:
                handler_name = getattr(handler, '__name__', repr(handler))

                try:
                    # Detect async vs sync handler
                    if asyncio.iscoroutinefunction(handler):
                        self.logger.debug(
                            f"Executing async handler '{handler_name}' "
                            f"for {event.event_type.value}"
                        )
                        await handler(event)
                    else:
                        self.logger.debug(
                            f"Executing sync handler '{handler_name}' "
                            f"for {event.event_type.value}"
                        )
                        handler(event)  # Direct call for sync handlers

                except Exception as e:
                    # Handler error: log but continue processing other handlers
                    self.logger.error(
                        f"Handler '{handler_name}' failed for "
                        f"{event.event_type.value} in {queue_name} queue: {e}",
                        exc_info=True  # Include full traceback
                    )
                    # Don't raise - continue to next handler

            # 4. Mark task as done (for queue.join() in shutdown)
            queue.task_done()

        except asyncio.TimeoutError:
            # No event available - not an error, continue loop
            continue

        except Exception as e:
            # Unexpected processor error (shouldn't happen, but be defensive)
            self.logger.critical(
                f"Processor error in {queue_name} queue: {e}",
                exc_info=True
            )
            # Don't crash processor - continue loop

    self.logger.info(f"Stopped {queue_name} queue processor")
```

### 3.3 Design Decisions

**1. Sequential vs Parallel Handler Execution**:
- **Choice**: Sequential (for loop, not asyncio.gather)
- **Rationale**:
  - Guarantees event ordering (handler 1 → handler 2 → handler 3)
  - Simpler error handling (one fails → log → continue)
  - No race conditions between handlers
  - Trading systems need predictable ordering
  - Lighter weight (no task spawning overhead)
- **Trade-off**: Slow handler blocks others, but handlers should be fast (<10ms)

**2. 0.1s Timeout for Queue Polling**:
- **Choice**: `asyncio.wait_for(queue.get(), timeout=0.1)`
- **Rationale**:
  - Allows checking `_running` flag 10x per second (responsive shutdown)
  - Non-blocking: doesn't hold up system when queue empty
  - TimeoutError is expected, not an error condition
- **Alternative Rejected**: Blocking `queue.get()` would make shutdown slow

**3. Handler Error Isolation**:
- **Choice**: try-except per handler, log but continue
- **Rationale**:
  - One bad handler shouldn't crash entire processor
  - One bad handler shouldn't block other handlers
  - Full traceback (`exc_info=True`) aids debugging
  - System continues with partial functionality
- **Critical**: Never raise from handler error block

**4. Sync vs Async Handler Detection**:
- **Choice**: `asyncio.iscoroutinefunction(handler)`
- **Rationale**:
  - Detects async def functions at runtime
  - Allows mixed sync/async handlers in same event type
  - await async, call sync directly
- **Note**: Lambdas and partials need special handling (covered in tests)

**5. Logging Strategy**:
- **INFO**: Processor start/stop (lifecycle events)
- **DEBUG**: Handler execution per event (verbose, for development)
- **ERROR**: Handler failures with exc_info=True (operational alerts)
- **CRITICAL**: Processor-level failures (should never happen)

## 4. Handler Execution Model

### 4.1 Sync Handler Execution

```python
def sync_handler(event: Event) -> None:
    print(f"Sync handling: {event.data}")
    # Direct call, no await

# In processor:
handler(event)  # Executed immediately
```

**Characteristics**:
- Blocks processor until complete
- Should be fast (<1ms)
- Good for: logging, metrics, simple state updates

### 4.2 Async Handler Execution

```python
async def async_handler(event: Event) -> None:
    await asyncio.sleep(0.01)  # Simulating I/O
    print(f"Async handling: {event.data}")

# In processor:
await handler(event)  # Yields control to event loop
```

**Characteristics**:
- Yields control during I/O operations
- Can await other coroutines
- Good for: API calls, database queries, external services

### 4.3 Handler Best Practices

**DO**:
- Keep handlers fast (<10ms total execution)
- Use async for I/O-bound work
- Spawn separate tasks for heavy computation
- Log errors within handler (defensive)

**DON'T**:
- Perform blocking I/O in sync handlers
- Raise exceptions (will be caught and logged)
- Mutate event object (handlers should be read-only)
- Assume handler execution order (depends on subscription order)

## 5. Error Handling Strategy

### 5.1 Error Categories

| Error Type | Handling | Impact | Example |
|------------|----------|--------|---------|
| **Handler Exception** | Log + Continue | Isolated | Strategy.analyze() raises ValueError |
| **Queue Timeout** | Continue | None | Empty queue, no events available |
| **Processor Exception** | Log + Continue | Critical | Unexpected processor bug |
| **System Shutdown** | Exit Loop | Clean | _running=False, processor stops |

### 5.2 Handler Error Isolation

```python
# Scenario: 3 handlers, middle one fails
handlers = [handler_1, handler_2_fails, handler_3]

for handler in handlers:
    try:
        # handler_1: executes successfully ✅
        # handler_2_fails: raises exception ❌ → logged, continue
        # handler_3: still executes ✅
    except Exception:
        # Caught, logged, loop continues
```

**Result**: handler_1 and handler_3 execute, handler_2_fails logged as error

### 5.3 Processor Resilience

**Principle**: Processors should never crash from handler errors

**Implementation**:
1. Outer try-except catches processor-level errors (defensive)
2. Inner try-except per handler catches handler errors (expected)
3. TimeoutError handling for empty queue (expected, not error)
4. All exceptions logged with full context
5. Loop continues in all cases

## 6. Test Strategy

### Test Suite: `tests/core/test_event_handler.py::TestEventBusProcessors`

**Test 1: Async Handler Execution**
```python
@pytest.mark.asyncio
async def test_processor_executes_async_handler():
    """Verify processor correctly awaits async handlers."""
    bus = EventBus()
    bus._running = True

    executed = []

    async def async_handler(event):
        await asyncio.sleep(0.01)  # Simulating async work
        executed.append(event.data)

    # Subscribe handler
    bus.subscribe(EventType.CANDLE_CLOSED, async_handler)

    # Publish event to data queue
    event = Event(EventType.CANDLE_CLOSED, {'test': 'data'}, source='test')
    await bus.publish(event, queue_name='data')

    # Start processor (will process 1 event then we stop it)
    processor_task = asyncio.create_task(bus._process_queue('data'))
    await asyncio.sleep(0.05)  # Let it process
    bus._running = False
    await processor_task

    # Verify handler was executed
    assert len(executed) == 1
    assert executed[0] == {'test': 'data'}
```

**Test 2: Sync Handler Execution**
```python
@pytest.mark.asyncio
async def test_processor_executes_sync_handler():
    """Verify processor correctly calls sync handlers."""
    bus = EventBus()
    bus._running = True

    executed = []

    def sync_handler(event):
        executed.append(event.data)

    bus.subscribe(EventType.CANDLE_CLOSED, sync_handler)

    event = Event(EventType.CANDLE_CLOSED, {'test': 'sync'}, source='test')
    await bus.publish(event, queue_name='data')

    processor_task = asyncio.create_task(bus._process_queue('data'))
    await asyncio.sleep(0.05)
    bus._running = False
    await processor_task

    assert len(executed) == 1
    assert executed[0] == {'test': 'sync'}
```

**Test 3: Handler Error Isolation**
```python
@pytest.mark.asyncio
async def test_processor_isolates_handler_errors():
    """Verify one handler error doesn't affect others."""
    bus = EventBus()
    bus._running = True

    executed = []

    def handler_1(event):
        executed.append('handler_1')

    def handler_2_fails(event):
        executed.append('handler_2_called')
        raise ValueError("Handler 2 intentional failure")

    def handler_3(event):
        executed.append('handler_3')

    # Subscribe all three handlers
    bus.subscribe(EventType.CANDLE_CLOSED, handler_1)
    bus.subscribe(EventType.CANDLE_CLOSED, handler_2_fails)
    bus.subscribe(EventType.CANDLE_CLOSED, handler_3)

    event = Event(EventType.CANDLE_CLOSED, {}, source='test')
    await bus.publish(event, queue_name='data')

    processor_task = asyncio.create_task(bus._process_queue('data'))
    await asyncio.sleep(0.05)
    bus._running = False
    await processor_task

    # Verify all handlers executed (2 succeeded, 1 failed but logged)
    assert 'handler_1' in executed
    assert 'handler_2_called' in executed
    assert 'handler_3' in executed
```

**Test 4: Processor Continues After Errors**
```python
@pytest.mark.asyncio
async def test_processor_continues_after_handler_error():
    """Verify processor processes multiple events despite errors."""
    bus = EventBus()
    bus._running = True

    executed_count = [0]

    def failing_handler(event):
        executed_count[0] += 1
        raise RuntimeError("Always fails")

    bus.subscribe(EventType.CANDLE_CLOSED, failing_handler)

    # Publish 3 events
    for i in range(3):
        event = Event(EventType.CANDLE_CLOSED, {'id': i}, source='test')
        await bus.publish(event, queue_name='data')

    processor_task = asyncio.create_task(bus._process_queue('data'))
    await asyncio.sleep(0.1)  # Let it process all 3
    bus._running = False
    await processor_task

    # Verify all 3 events were attempted (all failed but processor continued)
    assert executed_count[0] == 3
```

**Test 5: Empty Queue Timeout Handling**
```python
@pytest.mark.asyncio
async def test_processor_handles_empty_queue_timeout():
    """Verify processor continues when queue is empty (TimeoutError)."""
    bus = EventBus()
    bus._running = True

    # Start processor on empty queue
    processor_task = asyncio.create_task(bus._process_queue('data'))

    # Let it run for a bit (will hit TimeoutError multiple times)
    await asyncio.sleep(0.3)  # 3x the 0.1s timeout

    # Should still be running, not crashed
    assert not processor_task.done()

    # Stop gracefully
    bus._running = False
    await processor_task
```

**Test 6: Processor Stops on _running=False**
```python
@pytest.mark.asyncio
async def test_processor_stops_when_running_false():
    """Verify processor exits loop when _running flag set to False."""
    bus = EventBus()
    bus._running = True

    processor_task = asyncio.create_task(bus._process_queue('data'))
    await asyncio.sleep(0.05)  # Let it start

    # Stop processor
    bus._running = False

    # Should exit within ~0.1s (timeout period)
    await asyncio.wait_for(processor_task, timeout=0.5)

    # Verify task completed (not cancelled or error)
    assert processor_task.done()
    assert not processor_task.cancelled()
```

**Test 7: Sequential Handler Execution**
```python
@pytest.mark.asyncio
async def test_handlers_execute_sequentially():
    """Verify handlers execute in order, not parallel."""
    bus = EventBus()
    bus._running = True

    execution_order = []

    async def handler_1(event):
        execution_order.append('start_1')
        await asyncio.sleep(0.01)
        execution_order.append('end_1')

    async def handler_2(event):
        execution_order.append('start_2')
        await asyncio.sleep(0.01)
        execution_order.append('end_2')

    bus.subscribe(EventType.CANDLE_CLOSED, handler_1)
    bus.subscribe(EventType.CANDLE_CLOSED, handler_2)

    event = Event(EventType.CANDLE_CLOSED, {}, source='test')
    await bus.publish(event, queue_name='data')

    processor_task = asyncio.create_task(bus._process_queue('data'))
    await asyncio.sleep(0.05)
    bus._running = False
    await processor_task

    # Verify sequential execution (1 completes before 2 starts)
    assert execution_order == ['start_1', 'end_1', 'start_2', 'end_2']
```

### Test Execution Command
```bash
pytest tests/core/test_event_handler.py::TestEventBusProcessors -v \
    --cov=src.core.event_handler --cov-report=term-missing
```

**Expected Coverage**: 100% for new `_process_queue()` method

## 7. Integration Points

### 7.1 Dependencies (from 4.1, 4.2)

**From Subtask 4.1**:
- `_subscribers` dict: Maps EventType to List[Callable]
- `_get_handlers()` method: Returns handlers for event type
- `logger`: For logging handler execution and errors

**From Subtask 4.2**:
- `_queues` dict: Three asyncio.Queue instances
- `_running` flag: Controls processor loop lifecycle
- Queue polling: `await queue.get()` retrieves events

### 7.2 Dependents (Subtask 4.4, 4.5)

**Subtask 4.4** (Lifecycle Management):
- `start()` will spawn 3 processor tasks (one per queue)
- `stop()` will set `_running=False` to exit loops
- `shutdown()` will wait for `queue.task_done()` on all events

**Subtask 4.5** (TradingEngine):
- Will register handlers via `subscribe()`
- Handlers will be executed by processors
- Example: `_on_candle_closed()` handler called when CANDLE_CLOSED event processed

## 8. Quality Assurance

### Code Review Checklist

**Correctness**:
- [ ] Handler detection (sync vs async) correct
- [ ] Sequential execution maintained (not parallel)
- [ ] Handler errors caught and logged
- [ ] TimeoutError handled gracefully
- [ ] Loop exits when `_running=False`
- [ ] `queue.task_done()` called after processing

**Error Handling**:
- [ ] Handler exceptions don't crash processor
- [ ] One handler error doesn't affect others
- [ ] All exceptions logged with exc_info=True
- [ ] Processor-level exceptions caught defensively

**Performance**:
- [ ] 0.1s timeout allows responsive shutdown
- [ ] Sequential execution documented/justified
- [ ] No blocking operations in processor loop

**Testing**:
- [ ] All 7 unit tests implemented
- [ ] 100% coverage on _process_queue()
- [ ] Tests cover happy path and error cases
- [ ] Async tests use @pytest.mark.asyncio

**Documentation**:
- [ ] Full docstring with flow explanation
- [ ] Error handling strategy documented
- [ ] Sequential execution rationale explained
- [ ] Integration notes for Subtask 4.4

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

## 9. Success Criteria

### Functional Requirements

1. ✅ `_process_queue()` continuously polls queue while `_running=True`
2. ✅ Async handlers correctly awaited
3. ✅ Sync handlers directly called
4. ✅ Handler errors logged but don't crash processor
5. ✅ One handler error doesn't affect other handlers
6. ✅ Empty queue TimeoutError handled gracefully
7. ✅ Processor exits when `_running=False`
8. ✅ Handlers execute sequentially (not parallel)

### Test Requirements

1. ✅ 7 comprehensive unit tests implemented
2. ✅ 100% code coverage on `_process_queue()` method
3. ✅ All tests pass with pytest
4. ✅ Async tests properly decorated with @pytest.mark.asyncio

### Non-Functional Requirements

1. ✅ Processor responsive to shutdown (exits within 0.5s)
2. ✅ No memory leaks (task cleanup proper)
3. ✅ Full error traceability (exc_info=True logging)
4. ✅ Clear error messages for all failure modes

### Documentation Requirements

1. ✅ Full docstring with process flow explanation
2. ✅ Error handling strategy documented
3. ✅ Sequential execution rationale explained
4. ✅ Integration points with Subtask 4.4 documented

## 10. Implementation Sequence

**Step 1**: Implement `_process_queue()` method skeleton (5 min)
- Method signature with docstring
- While loop with `_running` check
- Basic queue polling

**Step 2**: Add handler execution logic (10 min)
- Get handlers via `_get_handlers()`
- Detect sync vs async with `iscoroutinefunction()`
- Execute with appropriate call/await

**Step 3**: Implement error isolation (10 min)
- Try-except per handler
- Log with exc_info=True
- Continue loop on error

**Step 4**: Add timeout and lifecycle handling (5 min)
- TimeoutError handling for empty queue
- Processor-level exception handling
- Start/stop logging

**Step 5**: Create unit tests (25 min)
- Implement 7 tests in TestEventBusProcessors class
- Ensure proper async test decoration
- Verify all tests pass

**Step 6**: Verify coverage and quality (5 min)
- Run pytest with coverage report
- Verify 100% coverage on new method
- Run static analysis

**Total Estimated Time**: 60 minutes

## 11. Next Steps

**After Subtask 4.3 Complete**:

→ **Subtask 4.4**: Lifecycle Management
- Implement `start()` to spawn 3 processor tasks
- Implement `stop()` to set `_running=False`
- Implement `shutdown()` to drain queues with timeout

→ **Subtask 4.5**: TradingEngine Integration
- Create TradingEngine class with component injection
- Register handlers via `subscribe()`
- Implement handler methods that delegate to components

## 12. References

**Parent Design**:
- `.taskmaster/designs/task-4-event-architecture-design.md` (Section 6: Handler Execution Model)

**Related Files**:
- `src/core/event_handler.py` - EventBus implementation
- `src/models/event.py` - Event and EventType definitions
- `tests/core/test_event_handler.py` - Test suite

**Design Patterns**:
- Event Loop Pattern (continuous queue polling)
- Error Isolation Pattern (try-except per handler)
- Sequential Execution Pattern (for loop, not asyncio.gather)

**External References**:
- AnyIO async iteration for queues
- asyncio.iscoroutinefunction() for coroutine detection
- asyncio.wait_for() with timeout for non-blocking queue polling
