# Subtask 4.1: EventBus Core Class Design Specification

**Parent Task**: Task #4 - Event-Driven Architecture & Async Queue System
**Version**: 1.0
**Date**: 2025-12-11
**Estimated Time**: 15-20 minutes

---

## 1. Overview

### 1.1 Objective
Implement the foundational EventBus class with subscriber registry and event routing capabilities. This establishes the pub-sub pattern infrastructure before queue implementation.

### 1.2 Scope
- EventBus class initialization with subscriber storage
- Handler subscription mechanism (sync/async support)
- Event type-based routing foundation
- Debug logging for subscriptions

### 1.3 Out of Scope (Future Subtasks)
- Queue system implementation (Subtask 4.2)
- Event publishing mechanism (Subtask 4.2)
- Async queue processors (Subtask 4.3)
- Lifecycle management (Subtask 4.4)

---

## 2. Current State Analysis

### 2.1 Existing Implementation
**File**: `src/core/event_handler.py`

```python
class EventHandler:
    """Coordinates system events and data flow"""

    def __init__(self):
        self._handlers: Dict[str, list[Callable]] = {}

    def subscribe(self, event: str, handler: Callable):
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    async def emit(self, event: str, data: Any):
        if event in self._handlers:
            for handler in self._handlers[event]:
                await handler(data)
```

**Issues with Current Implementation:**
1. ❌ Uses string-based event types (not type-safe)
2. ❌ Named `EventHandler` (conflicts with handler concept)
3. ❌ Has `emit()` method (premature, belongs in Subtask 4.2)
4. ❌ No logging for debugging
5. ❌ Manual dict initialization (not using defaultdict)
6. ❌ No `_running` flag for lifecycle management

### 2.2 Available Models
**File**: `src/models/event.py`

```python
from enum import Enum

class EventType(Enum):
    """Event types for event-driven architecture."""
    CANDLE_UPDATE = "candle_update"
    CANDLE_CLOSED = "candle_closed"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"

@dataclass
class Event:
    event_type: EventType
    data: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: Optional[str] = None
```

✅ **Good**: Type-safe EventType enum already exists
✅ **Good**: Event dataclass already defined

---

## 3. Design Specification

### 3.1 Class Structure

```python
"""
Event-driven system coordinator with multi-queue support
"""

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Dict, List

from src.models.event import Event, EventType


class EventBus:
    """
    Central event coordination with subscriber registry.

    This class implements the pub-sub pattern foundation for event-driven
    architecture. In Subtask 4.1, we focus on subscriber management only.
    Queue system and publishing will be added in subsequent subtasks.

    Architecture:
        - Type-safe event routing via EventType enum
        - Multiple handlers per event type
        - Support for both sync and async handlers
        - Thread-safe subscriber storage with defaultdict

    Lifecycle:
        - Subtask 4.1: Subscriber registry and routing
        - Subtask 4.2: Queue system and publishing
        - Subtask 4.3: Async queue processors
        - Subtask 4.4: Lifecycle management (start/stop/shutdown)
    """

    def __init__(self):
        """
        Initialize EventBus with empty subscriber registry.

        Attributes:
            _subscribers: Maps EventType to list of handler functions
            logger: Logger instance for debug/error tracking
            _running: Lifecycle flag (used in Subtask 4.4)
        """
        # Subscriber registry: EventType → List[Callable]
        # defaultdict automatically creates empty list for new EventTypes
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)

        # Logger for debugging subscription events
        self.logger = logging.getLogger(__name__)

        # Lifecycle flag (will be used in Subtask 4.4)
        self._running: bool = False

        self.logger.debug("EventBus initialized")

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Register a handler function for a specific event type.

        This method implements the "subscribe" side of the pub-sub pattern.
        Multiple handlers can subscribe to the same event type, and all will
        be called when that event is published.

        Args:
            event_type: The type of event to subscribe to (EventType enum)
            handler: Callable to invoke when event occurs. Can be sync or async.
                     Signature: (Event) -> None or (Event) -> Awaitable[None]

        Notes:
            - No duplicate checking: Same handler can subscribe multiple times
            - Both sync and async handlers supported (checked at execution time)
            - Thread-safe: defaultdict handles concurrent subscriptions

        Example:
            ```python
            bus = EventBus()

            def my_handler(event: Event):
                print(f"Received: {event.data}")

            async def async_handler(event: Event):
                await asyncio.sleep(0.1)
                print(f"Async received: {event.data}")

            bus.subscribe(EventType.CANDLE_CLOSED, my_handler)
            bus.subscribe(EventType.CANDLE_CLOSED, async_handler)
            ```
        """
        # Add handler to the list for this event type
        self._subscribers[event_type].append(handler)

        # Log subscription for debugging
        handler_name = getattr(handler, '__name__', repr(handler))
        self.logger.debug(
            f"Handler '{handler_name}' subscribed to {event_type.value}"
        )

    def _get_handlers(self, event_type: EventType) -> List[Callable]:
        """
        Retrieve all handlers registered for a specific event type.

        This is a helper method used internally by event processors
        (to be implemented in Subtask 4.3).

        Args:
            event_type: The event type to get handlers for

        Returns:
            List of handler callables. Empty list if no handlers registered.

        Notes:
            - Returns a reference to the internal list (not a copy)
            - Safe to iterate: defaultdict ensures list exists
            - Empty list is safe to iterate (no special handling needed)

        Example:
            ```python
            handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
            for handler in handlers:
                handler(event)  # Will execute 0+ times
            ```
        """
        return self._subscribers[event_type]
```

### 3.2 Key Design Decisions

#### Decision 1: Rename EventHandler → EventBus
**Rationale**:
- "EventHandler" is ambiguous (is it the bus or a handler function?)
- "EventBus" clearly indicates its role as message broker
- Aligns with industry standard terminology (e.g., Vert.x EventBus, Spring EventBus)

#### Decision 2: Use EventType Enum (not strings)
**Rationale**:
- Type safety: Typos caught at compile time
- IDE autocomplete for event types
- Enum already exists in `src/models/event.py`
- Prevents magic strings scattered in codebase

**Migration from existing code:**
```python
# Before (string-based)
bus.subscribe("candle_closed", handler)

# After (enum-based)
bus.subscribe(EventType.CANDLE_CLOSED, handler)
```

#### Decision 3: Use defaultdict for Subscriber Storage
**Rationale**:
- Eliminates `if event not in self._handlers` boilerplate
- Thread-safe for concurrent subscriptions
- Automatically creates empty list for new event types
- Cleaner code: `self._subscribers[event_type].append(handler)`

**Comparison:**
```python
# Manual dict (old approach)
if event not in self._handlers:
    self._handlers[event] = []
self._handlers[event].append(handler)

# defaultdict (new approach)
self._subscribers[event_type].append(handler)  # One line!
```

#### Decision 4: Support Both Sync and Async Handlers
**Rationale**:
- Flexibility: Some handlers are simple (sync), others need I/O (async)
- Checked at execution time using `asyncio.iscoroutinefunction()`
- Registration is identical for both types
- Execution logic in Subtask 4.3 (queue processors)

#### Decision 5: No Duplicate Handler Checking
**Rationale**:
- Use case: Same handler may need to subscribe multiple times (e.g., retry logic)
- Simplicity: No need to compare function identity
- Performance: No O(n) search on every subscribe()
- If deduplication needed, caller can implement it

#### Decision 6: Add _running Flag (Unused in 4.1)
**Rationale**:
- Prepares for Subtask 4.4 (lifecycle management)
- No logic overhead (just a boolean attribute)
- Clearer initialization sequence

---

## 4. Implementation Details

### 4.1 File Structure

**Path**: `src/core/event_handler.py`

**Modifications Required:**
1. Rename `EventHandler` class → `EventBus`
2. Remove `emit()` method (premature, belongs in Subtask 4.2)
3. Change `_handlers` → `_subscribers` (clearer naming)
4. Change `Dict[str, list[Callable]]` → `Dict[EventType, List[Callable]]`
5. Add `defaultdict(list)` initialization
6. Add `logger` initialization
7. Add `_running` flag initialization
8. Add logging to `subscribe()` method
9. Add `_get_handlers()` helper method

### 4.2 Import Dependencies

```python
import asyncio  # For future async support
import logging
from collections import defaultdict
from typing import Callable, Dict, List

from src.models.event import Event, EventType
```

**New Dependencies:**
- `logging`: For debug logging
- `defaultdict`: For automatic list creation
- `EventType`: Type-safe event enum

### 4.3 Method Signatures

```python
class EventBus:
    def __init__(self) -> None:
        """Initialize EventBus with empty subscriber registry."""

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Register handler for event type."""

    def _get_handlers(self, event_type: EventType) -> List[Callable]:
        """Get all handlers for event type. Internal use only."""
```

### 4.4 Logging Strategy

```python
# Initialization logging
self.logger.debug("EventBus initialized")

# Subscription logging
handler_name = getattr(handler, '__name__', repr(handler))
self.logger.debug(
    f"Handler '{handler_name}' subscribed to {event_type.value}"
)
```

**Log Levels:**
- `DEBUG`: Subscription events (verbose, for development)
- `INFO`: Not used in Subtask 4.1
- `WARNING`: Not used in Subtask 4.1
- `ERROR`: Not used in Subtask 4.1

**Rationale for DEBUG Level:**
- Subscriptions are frequent during initialization
- Not critical for production monitoring
- Useful for debugging subscription issues

---

## 5. Test Strategy

### 5.1 Test File Structure

**Path**: `tests/test_event_handler.py` (create if doesn't exist)

```python
"""
Unit tests for EventBus core functionality (Subtask 4.1)
"""

import pytest
from src.core.event_handler import EventBus
from src.models.event import EventType, Event


class TestEventBusCore:
    """Test EventBus subscriber registry and routing."""
```

### 5.2 Test Cases

#### Test 1: Subscribe Adds Handler Correctly
```python
def test_subscribe_adds_handler():
    """Verify subscribe() adds handler to subscriber registry."""
    bus = EventBus()

    def my_handler(event):
        pass

    # Subscribe handler to event type
    bus.subscribe(EventType.CANDLE_CLOSED, my_handler)

    # Verify handler was added
    handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
    assert my_handler in handlers
    assert len(handlers) == 1
```

**Success Criteria:**
- ✅ Handler appears in `_subscribers[EventType.CANDLE_CLOSED]`
- ✅ Handler count is 1

#### Test 2: Multiple Handlers for Same Event
```python
def test_multiple_handlers_same_event():
    """Verify multiple handlers can subscribe to same event type."""
    bus = EventBus()

    def handler_1(event):
        pass

    def handler_2(event):
        pass

    # Subscribe both handlers
    bus.subscribe(EventType.CANDLE_CLOSED, handler_1)
    bus.subscribe(EventType.CANDLE_CLOSED, handler_2)

    # Verify both handlers registered
    handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
    assert handler_1 in handlers
    assert handler_2 in handlers
    assert len(handlers) == 2
```

**Success Criteria:**
- ✅ Both handlers appear in list
- ✅ Handler count is 2
- ✅ Order is preserved (handler_1 first, handler_2 second)

#### Test 3: Empty Handler List for Unsubscribed Events
```python
def test_empty_handler_list_for_unsubscribed_events():
    """Verify _get_handlers() returns empty list for unregistered events."""
    bus = EventBus()

    # Don't subscribe any handlers

    # Get handlers for event with no subscriptions
    handlers = bus._get_handlers(EventType.SIGNAL_GENERATED)

    # Verify empty list returned (not None or error)
    assert handlers == []
    assert len(handlers) == 0
    assert isinstance(handlers, list)
```

**Success Criteria:**
- ✅ Returns empty list (not None)
- ✅ No exception raised
- ✅ Safe to iterate over result

#### Test 4: Sync and Async Handlers Registered
```python
def test_sync_and_async_callables_registered():
    """Verify both sync and async handlers can be registered."""
    bus = EventBus()

    def sync_handler(event):
        pass

    async def async_handler(event):
        pass

    # Subscribe both types
    bus.subscribe(EventType.CANDLE_CLOSED, sync_handler)
    bus.subscribe(EventType.CANDLE_CLOSED, async_handler)

    # Verify both registered
    handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
    assert sync_handler in handlers
    assert async_handler in handlers

    # Verify they're callable
    assert callable(sync_handler)
    assert callable(async_handler)
```

**Success Criteria:**
- ✅ Sync function registered
- ✅ Async function registered
- ✅ Both are callable

#### Test 5: Thread-Safe Concurrent Subscriptions
```python
import threading

def test_thread_safety_concurrent_subscriptions():
    """Verify concurrent subscriptions from multiple threads are safe."""
    bus = EventBus()

    def handler(event):
        pass

    # Subscribe from multiple threads simultaneously
    threads = []
    for i in range(10):
        t = threading.Thread(
            target=lambda: bus.subscribe(EventType.CANDLE_CLOSED, handler)
        )
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify all subscriptions succeeded
    handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
    assert len(handlers) == 10  # All 10 subscriptions succeeded
    assert all(h is handler for h in handlers)
```

**Success Criteria:**
- ✅ No race conditions or exceptions
- ✅ All 10 subscriptions succeed
- ✅ Handler count is correct

**Note**: This test verifies that `defaultdict` is thread-safe for our use case. While Python's GIL provides some protection, this test ensures no corruption occurs.

### 5.3 Test Execution

```bash
# Run all Subtask 4.1 tests
pytest tests/test_event_handler.py::TestEventBusCore -v

# Run specific test
pytest tests/test_event_handler.py::TestEventBusCore::test_subscribe_adds_handler -v

# Run with coverage
pytest tests/test_event_handler.py::TestEventBusCore --cov=src.core.event_handler -v
```

**Expected Output:**
```
tests/test_event_handler.py::TestEventBusCore::test_subscribe_adds_handler PASSED
tests/test_event_handler.py::TestEventBusCore::test_multiple_handlers_same_event PASSED
tests/test_event_handler.py::TestEventBusCore::test_empty_handler_list_for_unsubscribed_events PASSED
tests/test_event_handler.py::TestEventBusCore::test_sync_and_async_callables_registered PASSED
tests/test_event_handler.py::TestEventBusCore::test_thread_safety_concurrent_subscriptions PASSED

5 passed in 0.05s
```

---

## 6. Migration Plan

### 6.1 Backwards Compatibility Considerations

**Breaking Changes:**
1. Class name: `EventHandler` → `EventBus`
2. Event type: `str` → `EventType` enum
3. Method removed: `emit()` (premature, will be replaced with `publish()` in 4.2)

**Impact Analysis:**
- **No existing usage found**: This is Subtask 4.1, first implementation
- **If usage exists**: Will be caught by type checker and unit tests
- **Migration is simple**: Change import and event type references

### 6.2 Rollback Strategy

If issues arise:
1. Revert `src/core/event_handler.py` to previous version
2. Tests will fail (expected)
3. Fix issues and re-attempt
4. No data loss risk (in-memory only)

---

## 7. Integration Points

### 7.1 Dependencies (What We Need)

From `src/models/event.py`:
- ✅ `EventType` enum (already exists)
- ✅ `Event` dataclass (already exists, used in future subtasks)

Python stdlib:
- ✅ `logging` (standard library)
- ✅ `collections.defaultdict` (standard library)
- ✅ `typing` (standard library)
- ✅ `asyncio` (standard library, used in future subtasks)

### 7.2 Dependents (What Needs Us)

**Subtask 4.2** (Multi-Queue System):
- Will add `_queues: Dict[str, asyncio.Queue]` attribute
- Will add `publish(event: Event, queue_name: str)` method
- Uses `_subscribers` to route events to handlers

**Subtask 4.3** (Queue Processors):
- Will add `_process_queue(queue_name: str)` method
- Uses `_get_handlers()` to retrieve handler list
- Uses `_running` flag to control processor loop

**Subtask 4.4** (Lifecycle Management):
- Will add `start()`, `stop()`, `shutdown()` methods
- Uses `_running` flag to signal processors
- Manages processor tasks

**Subtask 4.5** (TradingEngine):
- Will instantiate `EventBus()`
- Will call `subscribe()` to register handlers
- Will call `publish()` (from 4.2) to emit events

---

## 8. Quality Assurance

### 8.1 Code Review Checklist

- [ ] Class renamed to `EventBus`
- [ ] Uses `EventType` enum (not strings)
- [ ] Uses `defaultdict(list)` for subscribers
- [ ] Logger initialized in `__init__`
- [ ] `_running` flag initialized to False
- [ ] `subscribe()` adds handler to list
- [ ] `subscribe()` logs at DEBUG level
- [ ] `_get_handlers()` returns List[Callable]
- [ ] No premature `emit()` or `publish()` method
- [ ] Type hints are correct
- [ ] Docstrings are comprehensive

### 8.2 Static Analysis

```bash
# Type checking
mypy src/core/event_handler.py

# Linting
flake8 src/core/event_handler.py
pylint src/core/event_handler.py

# Formatting
black src/core/event_handler.py --check
```

**Expected Results:**
- ✅ No mypy errors
- ✅ No flake8 warnings
- ✅ Pylint score ≥ 9.0/10
- ✅ Black formatting compliant

### 8.3 Coverage Target

**Minimum Coverage**: 100% (simple class, all code should be tested)

**Coverage Report:**
```bash
pytest tests/test_event_handler.py::TestEventBusCore --cov=src.core.event_handler --cov-report=term-missing
```

**Expected:**
- ✅ `__init__`: 100% (tested via all tests)
- ✅ `subscribe`: 100% (tests 1, 2, 4, 5)
- ✅ `_get_handlers`: 100% (all tests)

---

## 9. Success Criteria

### 9.1 Functional Requirements
✅ `EventBus` class created in `src/core/event_handler.py`
✅ `__init__`, `subscribe`, `_get_handlers` methods implemented
✅ Uses `EventType` enum for type-safe routing
✅ Uses `defaultdict(list)` for subscriber storage
✅ Logger initialized and used for debug logging
✅ `_running` flag initialized (for future use)

### 9.2 Test Requirements
✅ All 5 unit tests pass
✅ 100% code coverage
✅ No type checker errors (mypy)
✅ No linting warnings

### 9.3 Non-Functional Requirements
✅ Code follows project style conventions
✅ Docstrings are comprehensive
✅ Type hints are complete
✅ No premature optimization

---

## 10. Next Steps

After Subtask 4.1 completion:

**Subtask 4.2** - Multi-Queue System (15-20 min)
- Add `_queues: Dict[str, asyncio.Queue]` attribute
- Implement `publish(event: Event, queue_name: str)` method
- Implement overflow handling (drop/block based on queue)
- Test queue overflow behavior

**Subtask 4.3** - Queue Processors (20-25 min)
- Implement `_process_queue(queue_name: str)` method
- Add async/sync handler execution logic
- Implement error isolation
- Test handler exceptions don't crash processor

**Subtask 4.4** - Lifecycle Management (15-20 min)
- Implement `start()`, `stop()`, `shutdown()` methods
- Add task management for processors
- Implement graceful shutdown with queue draining
- Test shutdown with pending events

**Subtask 4.5** - TradingEngine Orchestrator (20-25 min)
- Create `src/core/trading_engine.py`
- Implement component injection
- Register event handlers
- Test end-to-end pipeline

---

## 11. References

### 11.1 Design Documents
- **Parent Design**: `.taskmaster/designs/task-4-event-architecture-design.md`
- **Section 3.2**: EventBus Class Structure
- **Section 7.1**: Unit Tests (Subtask 4.1)

### 11.2 Related Files
- `src/models/event.py`: EventType enum, Event dataclass
- `src/core/event_handler.py`: Current implementation (to be modified)

### 11.3 Design Patterns
- **Pub-Sub Pattern**: Subscriber registry and event routing
- **Registry Pattern**: `_subscribers` dict as handler registry
- **Template Method**: `_get_handlers()` for extensibility

### 11.4 Python Best Practices
- `defaultdict` for automatic list creation
- Type hints for static analysis
- Docstrings following Google style guide
- Logging at appropriate levels

---

**Document Status**: ✅ Ready for Implementation
**Next Action**: `/sc:implement --serena` to begin coding

---

**Document End**
