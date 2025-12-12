# Subtask 4.4: EventBus Lifecycle Management Design

**Parent Task**: Task #4 - Event-Driven Architecture & Async Queue System
**Dependencies**: Subtask 4.1 (EventBus Core) ✅ | Subtask 4.2 (Multi-queue) ✅ | Subtask 4.3 (Queue Processors) ✅
**Complexity**: 7/10 (Medium-High)
**Status**: Design Phase

## 1. Objective

Implement lifecycle management methods (`start()`, `stop()`, `shutdown()`) that control the EventBus processor tasks with proper initialization, graceful shutdown, and pending event handling.

**Scope**:
- Implement `start()` async method to spawn 3 processor tasks
- Implement `stop()` method to signal processors to exit
- Implement `shutdown()` async method for graceful cleanup with timeout
- Add `_processor_tasks` attribute for task management
- Proper logging for lifecycle events

**Out of Scope** (deferred to Subtask 4.5):
- TradingEngine integration
- Component handler registration
- Application-level orchestration

## 2. Current State Analysis

**Existing EventBus Components** (from 4.1, 4.2, 4.3):

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
        self._running: bool = False  # ✅ Ready for lifecycle control
        self._drop_count: Dict[str, int] = {'data': 0, 'signal': 0, 'order': 0}

    async def _process_queue(self, queue_name: str) -> None:
        """Process events continuously while _running=True"""
        # Implemented in Subtask 4.3
        # Checks self._running flag
        # Calls queue.task_done() after processing
        pass
```

**What's Missing**:
1. `_processor_tasks` attribute to store task references
2. `start()` method to spawn processor tasks
3. `stop()` method to signal shutdown
4. `shutdown()` method for graceful cleanup

## 3. Lifecycle Management Design

### 3.1 Task Storage Attribute

Add to `__init__()`:
```python
def __init__(self):
    # ... existing attributes ...
    self._processor_tasks: List[asyncio.Task] = []  # Store for cancellation
```

**Rationale**:
- Need references to cancel tasks during shutdown
- Empty list initially, populated by start()
- Type hint for clarity

### 3.2 start() Method

```python
async def start(self) -> None:
    """
    Start all queue processors and run until stop() is called.

    Creates three processor tasks (data, signal, order) and runs them
    concurrently using asyncio.gather with return_exceptions=True to
    prevent single task failure from crashing the entire EventBus.

    Process Flow:
        1. Set _running flag to True
        2. Create 3 processor tasks with descriptive names
        3. Store task references in _processor_tasks
        4. Wait for all tasks with gather (blocks until stop())

    Error Handling:
        - return_exceptions=True logs task errors without propagating
        - Individual processor errors don't crash EventBus
        - Task names enable debugging (data_processor, signal_processor, order_processor)

    Lifecycle:
        - Blocks until stop() sets _running=False
        - Processors exit their loops on _running=False
        - gather completes when all processors exit

    Example:
        ```python
        bus = EventBus()
        # Register handlers first
        bus.subscribe(EventType.CANDLE_CLOSED, handler)

        # Start processors (blocks until stop())
        asyncio.create_task(bus.start())

        # Later, to stop:
        bus.stop()  # Processors exit within 0.5s
        ```

    Notes:
        - Must call stop() to exit (or KeyboardInterrupt)
        - Use shutdown() for graceful cleanup with pending events
        - Task names aid debugging in asyncio task list
    """
    self._running = True
    self.logger.info("Starting EventBus processors")

    # Create processor tasks with descriptive names
    self._processor_tasks = [
        asyncio.create_task(
            self._process_queue('data'),
            name='data_processor'
        ),
        asyncio.create_task(
            self._process_queue('signal'),
            name='signal_processor'
        ),
        asyncio.create_task(
            self._process_queue('order'),
            name='order_processor'
        )
    ]

    # Wait for all processors (runs until stop() called)
    # return_exceptions=True prevents single task error from crashing EventBus
    await asyncio.gather(*self._processor_tasks, return_exceptions=True)

    self.logger.info("EventBus processors stopped")
```

### 3.3 stop() Method

```python
def stop(self) -> None:
    """
    Signal all processors to stop by setting _running flag.

    This is a non-blocking operation that signals processors to exit
    their loops. Processors will finish their current event and exit
    within approximately 0.1s (the queue polling timeout).

    Process Flow:
        1. Log stop request
        2. Set _running=False
        3. Return immediately

    Timing:
        - Non-blocking call (returns immediately)
        - Processors check _running every 0.1s (timeout period)
        - Expect processors to exit within 0.5s

    Usage:
        ```python
        # In main application or signal handler
        event_bus.stop()  # Signal shutdown

        # Optionally wait for graceful cleanup
        await event_bus.shutdown(timeout=10.0)
        ```

    Notes:
        - Does NOT wait for processors to exit
        - Does NOT cancel tasks (use shutdown() for that)
        - Safe to call multiple times (idempotent)
        - Typically followed by shutdown() for cleanup
    """
    self.logger.info("Stopping EventBus processors")
    self._running = False
```

### 3.4 shutdown() Method

```python
async def shutdown(self, timeout: float = 5.0) -> None:
    """
    Gracefully shutdown EventBus with pending event processing.

    Performs graceful shutdown sequence:
    1. Stop processors (set _running=False)
    2. Wait for queues to drain (all events processed)
    3. Cancel processor tasks if timeout exceeded

    Args:
        timeout: Max seconds to wait per queue for pending events (default: 5.0)

    Process Flow:
        1. Call stop() to signal processors
        2. For each queue, wait for queue.join() with timeout
        3. If timeout: log warning, continue to next queue
        4. Cancel all processor tasks

    Error Handling:
        - TimeoutError per queue: logged as warning, continues
        - Task cancellation: always attempted (defensive)
        - Pending events logged if timeout exceeded

    Example:
        ```python
        try:
            await event_bus.start()
        except KeyboardInterrupt:
            await event_bus.shutdown(timeout=10.0)
            # All pending events processed or timeout logged
        ```

    Critical for Trading:
        - Order queue events MUST be processed or logged
        - Timeout prevents indefinite hanging
        - Cancellation as last resort

    Notes:
        - Calls stop() internally (safe to call shutdown() directly)
        - Timeout applies PER QUEUE (total time = 3 * timeout)
        - Defensive hasattr check for _processor_tasks
        - Task cancellation doesn't wait (fire and forget)
    """
    # Signal processors to stop
    self.stop()

    self.logger.info("Shutting down EventBus gracefully")

    # Wait for queues to drain (all events processed)
    for queue_name, queue in self._queues.items():
        try:
            self.logger.debug(
                f"Waiting for {queue_name} queue to drain "
                f"(pending: {queue.qsize()})"
            )
            await asyncio.wait_for(queue.join(), timeout=timeout)
            self.logger.debug(f"Queue {queue_name} drained successfully")

        except asyncio.TimeoutError:
            pending = queue.qsize()
            self.logger.warning(
                f"Queue {queue_name} didn't drain in {timeout}s "
                f"({pending} events remaining). Proceeding with shutdown."
            )
            # Continue to next queue (don't block shutdown)

    # Cancel processor tasks (defensive check)
    if hasattr(self, '_processor_tasks') and self._processor_tasks:
        self.logger.debug(
            f"Cancelling {len(self._processor_tasks)} processor tasks"
        )
        for task in self._processor_tasks:
            if not task.done():
                task.cancel()

    self.logger.info("EventBus shutdown complete")
```

## 4. Design Decisions

**1. asyncio.gather with return_exceptions=True**:
- **Choice**: `await asyncio.gather(*tasks, return_exceptions=True)`
- **Rationale**:
  - Single processor crash doesn't kill entire EventBus
  - Errors logged but not propagated
  - All processors continue even if one fails
- **Alternative Rejected**: `gather()` without return_exceptions would crash EventBus on first task error

**2. Task Names for Debugging**:
- **Choice**: `asyncio.create_task(..., name='data_processor')`
- **Rationale**:
  - Visible in asyncio.all_tasks() for debugging
  - Easier to identify tasks in error logs
  - Helps with performance profiling
- **Note**: Requires Python 3.8+ (available in our environment)

**3. stop() is Non-Blocking**:
- **Choice**: Synchronous method, just sets flag
- **Rationale**:
  - Can be called from signal handlers (sync context)
  - Immediate return enables fast shutdown signaling
  - Processors check flag every 0.1s (responsive)
- **Alternative Rejected**: Async stop() would complicate signal handling

**4. shutdown() Timeout Per Queue**:
- **Choice**: timeout parameter applies to each queue individually
- **Rationale**:
  - Fair timeout for each queue priority
  - Total time = 3 * timeout (predictable)
  - One slow queue doesn't consume entire timeout
- **Trade-off**: Total shutdown could take 3x timeout, but more balanced

**5. Defensive Task Cancellation**:
- **Choice**: `hasattr()` check before cancelling tasks
- **Rationale**:
  - shutdown() might be called before start()
  - Prevents AttributeError in edge cases
  - Safe to call shutdown() multiple times
- **Note**: Defensive programming for robustness

**6. Task Storage in _processor_tasks**:
- **Choice**: Store task references in list attribute
- **Rationale**:
  - Enables cancellation during shutdown
  - Allows inspection of task status
  - Supports potential future restart logic
- **Alternative Rejected**: Local variable would prevent shutdown() access

## 5. Error Handling Strategy

### 5.1 Error Categories

| Error Type | Handling | Impact | Example |
|------------|----------|--------|---------|
| **Processor Exception** | Logged by gather | Isolated | _process_queue() raises unexpected error |
| **Queue Timeout** | Log warning + Continue | Graceful | Queue doesn't drain in timeout |
| **Task Cancellation** | Fire and forget | Clean | Cancel tasks after timeout |
| **Shutdown During Start** | Defensive check | Robust | shutdown() called before start() |

### 5.2 Graceful Degradation

**Scenario 1**: Processor Task Crashes
```python
# In start():
await asyncio.gather(*tasks, return_exceptions=True)
# Result: Crashed task logged, others continue
```

**Scenario 2**: Queue Doesn't Drain
```python
# In shutdown():
try:
    await asyncio.wait_for(queue.join(), timeout=5.0)
except asyncio.TimeoutError:
    # Log warning with pending count
    # Continue to next queue (don't block shutdown)
```

**Scenario 3**: Multiple shutdown() Calls
```python
# First call: Sets _running=False, drains queues, cancels tasks
# Second call: Sets _running=False (no-op), queue.join() immediate (empty), cancel no-op
# Result: Safe, idempotent
```

## 6. Test Strategy

### Test Suite: `tests/core/test_event_handler.py::TestEventBusLifecycle`

**Test 1: start() Creates Processor Tasks**
```python
@pytest.mark.asyncio
async def test_start_creates_processor_tasks():
    """Verify start() spawns 3 processor tasks with names."""
    bus = EventBus()

    # Start in background
    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.1)  # Let processors start

    # Verify 3 tasks created
    assert len(bus._processor_tasks) == 3

    # Verify task names
    task_names = {task.get_name() for task in bus._processor_tasks}
    assert task_names == {'data_processor', 'signal_processor', 'order_processor'}

    # Verify tasks running
    for task in bus._processor_tasks:
        assert not task.done()

    # Cleanup
    bus.stop()
    await start_task
```

**Test 2: Processors Run Until Stopped**
```python
@pytest.mark.asyncio
async def test_processors_run_until_stopped():
    """Verify processors run continuously until stop() called."""
    bus = EventBus()

    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.3)  # Let run for 3x timeout period

    # Processors should still be running
    for task in bus._processor_tasks:
        assert not task.done()

    # Stop and verify exit
    bus.stop()
    await asyncio.wait_for(start_task, timeout=1.0)

    # All tasks should be done
    for task in bus._processor_tasks:
        assert task.done()
```

**Test 3: stop() Sets _running Flag**
```python
@pytest.mark.asyncio
async def test_stop_sets_running_flag():
    """Verify stop() sets _running=False immediately."""
    bus = EventBus()

    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.1)

    # Verify _running is True
    assert bus._running is True

    # Stop and verify flag
    bus.stop()
    assert bus._running is False

    await start_task
```

**Test 4: Processors Exit After stop()**
```python
@pytest.mark.asyncio
async def test_processors_exit_after_stop():
    """Verify processors exit within 0.5s after stop()."""
    bus = EventBus()

    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.1)

    # Stop and measure exit time
    import time
    start_time = time.time()
    bus.stop()
    await asyncio.wait_for(start_task, timeout=1.0)
    elapsed = time.time() - start_time

    # Should exit within 0.5s (0.1s timeout * 5 iterations max)
    assert elapsed < 0.5
```

**Test 5: shutdown() Waits for Pending Events**
```python
@pytest.mark.asyncio
async def test_shutdown_waits_for_pending_events():
    """Verify shutdown() waits for queue.join()."""
    bus = EventBus()

    executed = []

    def handler(event):
        executed.append(event.data)

    bus.subscribe(EventType.CANDLE_CLOSED, handler)

    # Start processors
    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.1)

    # Publish events
    for i in range(3):
        event = Event(EventType.CANDLE_CLOSED, {'id': i}, source='test')
        await bus.publish(event, queue_name='data')

    # Shutdown gracefully
    await bus.shutdown(timeout=2.0)
    await start_task

    # Verify all events processed
    assert len(executed) == 3
    assert executed == [{'id': 0}, {'id': 1}, {'id': 2}]
```

**Test 6: shutdown() Timeout Prevents Hanging**
```python
@pytest.mark.asyncio
async def test_shutdown_timeout_prevents_hanging(caplog):
    """Verify shutdown() times out gracefully with warning."""
    bus = EventBus()

    # Handler that blocks indefinitely
    async def blocking_handler(event):
        await asyncio.sleep(100)  # Simulates slow processing

    bus.subscribe(EventType.CANDLE_CLOSED, blocking_handler)

    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.1)

    # Publish event
    event = Event(EventType.CANDLE_CLOSED, {}, source='test')
    await bus.publish(event, queue_name='data')

    # Shutdown with short timeout
    with caplog.at_level(logging.WARNING):
        await bus.shutdown(timeout=0.5)

    await asyncio.wait_for(start_task, timeout=1.0)

    # Verify warning logged
    assert "didn't drain" in caplog.text
    assert "data" in caplog.text
```

**Test 7: Integration Test - Full Lifecycle**
```python
@pytest.mark.asyncio
async def test_integration_start_publish_stop():
    """Full lifecycle: start → publish → stop → verify."""
    bus = EventBus()

    executed = []

    async def async_handler(event):
        await asyncio.sleep(0.01)
        executed.append(event.data)

    bus.subscribe(EventType.CANDLE_CLOSED, async_handler)
    bus.subscribe(EventType.SIGNAL_GENERATED, async_handler)

    # Start processors
    start_task = asyncio.create_task(bus.start())
    await asyncio.sleep(0.1)

    # Publish to multiple queues
    for i in range(5):
        await bus.publish(
            Event(EventType.CANDLE_CLOSED, {'candle': i}, source='test'),
            queue_name='data'
        )

    for i in range(3):
        await bus.publish(
            Event(EventType.SIGNAL_GENERATED, {'signal': i}, source='test'),
            queue_name='signal'
        )

    # Graceful shutdown
    await bus.shutdown(timeout=2.0)
    await start_task

    # Verify all events processed
    assert len(executed) == 8

    # Verify queue stats
    stats = bus.get_queue_stats()
    assert stats['data']['size'] == 0
    assert stats['signal']['size'] == 0
```

### Test Execution Command
```bash
pytest tests/core/test_event_handler.py::TestEventBusLifecycle -v \
    --cov=src.core.event_handler --cov-report=term-missing
```

**Expected Coverage**: 100% for new lifecycle methods (start, stop, shutdown)

## 7. Integration Points

### 7.1 Dependencies (from 4.1, 4.2, 4.3)

**From Subtask 4.3** (_process_queue):
- Checks `self._running` flag (controlled by stop())
- Calls `queue.task_done()` (enables queue.join() in shutdown())
- Exits loop when `_running=False`

**From Subtask 4.2** (Multi-queue):
- Three queues available for draining in shutdown()
- queue.qsize() used for pending event logging

**From Subtask 4.1** (EventBus Core):
- Logger for lifecycle events
- Subscribers must be registered before start()

### 7.2 Dependents (Subtask 4.5)

**TradingEngine Integration**:
```python
class TradingEngine:
    async def run(self):
        """Main application entry point"""
        try:
            # Start EventBus (blocks until stopped)
            await self.event_bus.start()
        except KeyboardInterrupt:
            self.logger.info("Shutdown requested")
            await self.event_bus.shutdown(timeout=10.0)
```

**Key Points**:
- TradingEngine.run() will call `await event_bus.start()`
- KeyboardInterrupt triggers graceful shutdown
- Timeout ensures order events processed or logged

## 8. Quality Assurance

### Code Review Checklist

**Correctness**:
- [ ] start() spawns 3 tasks with correct names
- [ ] stop() sets _running=False immediately
- [ ] shutdown() calls stop() internally
- [ ] shutdown() waits for queue.join() per queue
- [ ] Timeout handled gracefully (warning log)
- [ ] Task cancellation defensive (hasattr check)

**Error Handling**:
- [ ] gather with return_exceptions=True
- [ ] TimeoutError caught per queue, continues
- [ ] Task cancellation doesn't crash
- [ ] Safe to call shutdown() before start()

**Performance**:
- [ ] stop() is non-blocking (immediate return)
- [ ] Processors exit within 0.5s of stop()
- [ ] shutdown() timeout per queue (fair distribution)

**Testing**:
- [ ] All 7 unit tests implemented
- [ ] 100% coverage on lifecycle methods
- [ ] Integration test covers full lifecycle
- [ ] Async tests use @pytest.mark.asyncio

**Documentation**:
- [ ] Full docstrings with process flow
- [ ] Error handling documented
- [ ] Lifecycle timing documented
- [ ] Integration examples provided

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

1. ✅ `start()` spawns 3 processor tasks with descriptive names
2. ✅ Processors run continuously until `stop()` called
3. ✅ `stop()` sets `_running=False` immediately (non-blocking)
4. ✅ Processors exit within 0.5s after `stop()`
5. ✅ `shutdown()` waits for pending events (queue.join())
6. ✅ Timeout handled gracefully (warning log, continues)
7. ✅ Task cancellation defensive (hasattr check)
8. ✅ Integration test demonstrates full lifecycle

### Test Requirements

1. ✅ 7 comprehensive unit tests implemented
2. ✅ 100% code coverage on lifecycle methods
3. ✅ All tests pass with pytest
4. ✅ Integration test covers start → publish → shutdown flow

### Non-Functional Requirements

1. ✅ stop() returns immediately (non-blocking)
2. ✅ Processors responsive to shutdown (<0.5s)
3. ✅ Graceful shutdown doesn't hang (timeout enforced)
4. ✅ Safe to call methods in any order

### Documentation Requirements

1. ✅ Full docstrings with process flow
2. ✅ Error handling strategy documented
3. ✅ Timing characteristics explained
4. ✅ Integration points with 4.5 documented

## 10. Implementation Sequence

**Step 1**: Add _processor_tasks attribute to __init__() (2 min)
- Add list attribute with type hint
- Document purpose in docstring

**Step 2**: Implement start() method (10 min)
- Set _running=True
- Create 3 tasks with names
- Store in _processor_tasks
- await gather with return_exceptions
- Add logging

**Step 3**: Implement stop() method (5 min)
- Log stop request
- Set _running=False
- Return immediately

**Step 4**: Implement shutdown() method (15 min)
- Call stop()
- Loop over queues with queue.join()
- Handle TimeoutError per queue
- Cancel tasks defensively
- Add logging

**Step 5**: Create unit tests (25 min)
- Implement 7 tests in TestEventBusLifecycle class
- Ensure proper async test decoration
- Verify all tests pass

**Step 6**: Verify coverage and quality (3 min)
- Run pytest with coverage report
- Verify 100% coverage on new methods
- Run static analysis

**Total Estimated Time**: 60 minutes

## 11. Next Steps

**After Subtask 4.4 Complete**:

→ **Subtask 4.5**: TradingEngine Orchestrator
- Create TradingEngine class with component injection
- Implement run() method that starts EventBus
- Register handlers via subscribe()
- Handle KeyboardInterrupt → shutdown()

## 12. References

**Parent Design**:
- `.taskmaster/designs/task-4-event-architecture-design.md` (Section 7: Lifecycle Management)

**Related Files**:
- `src/core/event_handler.py` - EventBus implementation
- `tests/core/test_event_handler.py` - Test suite

**Design Patterns**:
- Task Group Pattern (asyncio.gather for concurrent tasks)
- Graceful Shutdown Pattern (stop → drain → cancel)
- Defensive Programming (hasattr checks)

**External References**:
- AnyIO task cancellation patterns
- asyncio.gather with return_exceptions
- asyncio.wait_for for timeout handling
- Task naming for debugging (Python 3.8+)
