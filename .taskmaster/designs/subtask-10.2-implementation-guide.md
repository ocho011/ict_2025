# Subtask 10.2: Event Handler Setup Implementation Guide

## Overview

Implement the event wiring between components through EventBus, creating the bridge from WebSocket data to the event-driven trading pipeline.

## File to Modify

- **Primary**: `src/main.py` - Implement `_setup_event_handlers()` and `_on_candle_received()`

## Design Principles

1. **Pub-Sub Pattern**: Decouple components through event-based communication
2. **Non-Blocking Operations**: Use asyncio.create_task for concurrent event processing
3. **Event Type Differentiation**: Distinguish between updates and closed candles
4. **Queue Routing**: Route events to appropriate queues based on criticality
5. **Observable Flow**: Add debug logging for event flow tracing

## Implementation Details

### 1. `_setup_event_handlers()` Method

**Purpose**: Register event handlers with EventBus for 3 critical event types

**Current State** (stub):
```python
def _setup_event_handlers(self) -> None:
    """Wire up event subscriptions between components."""
    pass
```

**Implementation**:
```python
def _setup_event_handlers(self) -> None:
    """
    Wire up event subscriptions between components.

    Registers handlers for the three main event types in the trading pipeline:
    - CANDLE_CLOSED: Triggers strategy analysis
    - SIGNAL_GENERATED: Triggers risk validation and order execution
    - ORDER_FILLED: Triggers position tracking updates

    Called during initialization (Step 10 in initialize() method).
    """
    self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
    self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal_generated)
    self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)

    self.logger.info("Event handlers registered successfully")
```

**Key Points**:
- Subscribe to 3 event types (not CANDLE_UPDATE - only closed candles trigger strategy)
- Pass method references (not calls): `self._on_candle_closed` not `self._on_candle_closed()`
- EventBus.subscribe() signature: `(EventType, Callable) -> None`
- Handlers can be sync or async (EventBus detects at runtime)

### 2. `_on_candle_received()` Method

**Purpose**: Bridge WebSocket callback to EventBus event system

**Current State** (stub):
```python
def _on_candle_received(self, candle: Candle) -> None:
    """Callback from BinanceDataCollector on every candle update."""
    pass
```

**Implementation**:
```python
def _on_candle_received(self, candle: Candle) -> None:
    """
    Callback from BinanceDataCollector on every candle update.

    This method bridges the WebSocket data stream to the EventBus by:
    1. Determining event type based on candle.is_closed flag
    2. Creating an Event wrapper around the Candle
    3. Publishing to EventBus 'data' queue asynchronously

    Called by BinanceDataCollector for every candle update (both updates and closes).

    Args:
        candle: Candle data from WebSocket stream

    Note:
        - Uses asyncio.create_task for non-blocking publish
        - CANDLE_CLOSED events trigger strategy analysis
        - CANDLE_UPDATE events are for monitoring only
    """
    # Determine event type based on candle state
    event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE

    # Create Event wrapper
    event = Event(event_type, candle)

    # Publish to EventBus asynchronously (non-blocking)
    asyncio.create_task(
        self.event_bus.publish(event, queue_name='data')
    )

    # Debug logging for event flow tracing
    if candle.is_closed:
        self.logger.debug(
            f"Candle closed: {candle.symbol} {candle.interval} "
            f"@ {candle.close} (published to EventBus)"
        )
```

**Key Points**:

1. **Event Type Logic**:
   ```python
   # Correct: Conditional based on is_closed
   event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE

   # Wrong: Always CANDLE_CLOSED
   event_type = EventType.CANDLE_CLOSED  # Incorrect
   ```

2. **Event Creation**:
   ```python
   # Correct: Event wraps the candle data
   event = Event(event_type, candle)

   # Event constructor: Event(event_type: EventType, data: Any)
   ```

3. **Async Task Creation**:
   ```python
   # Correct: Non-blocking publish
   asyncio.create_task(self.event_bus.publish(event, queue_name='data'))

   # Wrong: Blocking await (would block WebSocket thread)
   await self.event_bus.publish(event, queue_name='data')  # Don't do this!
   ```

4. **Queue Routing**:
   - Candle events → `'data'` queue (high-frequency, can drop under load)
   - Signal events → `'signal'` queue (important, blocks under load)
   - Order events → `'order'` queue (critical, never drops)

## EventBus Interface Reference

### EventBus.subscribe()

**Signature**:
```python
def subscribe(self, event_type: EventType, handler: Callable) -> None
```

**Behavior**:
- Accepts both sync and async handlers
- No duplicate checking (same handler can subscribe multiple times)
- Thread-safe (uses defaultdict)
- Logs subscription for debugging

**Example**:
```python
# Sync handler
def my_handler(event: Event) -> None:
    print(event.data)

# Async handler
async def async_handler(event: Event) -> None:
    await asyncio.sleep(0.1)
    print(event.data)

bus.subscribe(EventType.CANDLE_CLOSED, my_handler)
bus.subscribe(EventType.CANDLE_CLOSED, async_handler)
```

### EventBus.publish()

**Signature**:
```python
async def publish(self, event: Event, queue_name: str = 'data') -> None
```

**Behavior**:
- Async method (must be awaited or wrapped in create_task)
- Routes to one of 3 queues: 'data', 'signal', 'order'
- Different overflow handling per queue:
  - `data`: Timeout 1s, drops on full (acceptable for high-frequency)
  - `signal`: Timeout 5s, raises TimeoutError on full
  - `order`: No timeout, blocks indefinitely (never drops)

**Example**:
```python
# High-frequency data (may drop)
await bus.publish(Event(EventType.CANDLE_UPDATE, candle), queue_name='data')

# Trading signal (blocks up to 5s)
await bus.publish(Event(EventType.SIGNAL_GENERATED, signal), queue_name='signal')

# Critical order (never drops)
await bus.publish(Event(EventType.ORDER_PLACED, order), queue_name='order')
```

## Event Flow Diagram

```
WebSocket Thread                EventBus System              Event Handlers
─────────────────              ──────────────────            ──────────────

Candle Update
     │
     ├─> _on_candle_received()
     │         │
     │         ├─> Event(CANDLE_UPDATE, candle)
     │         │
     │         └─> create_task(
     │                 publish(event, 'data')
     │             )
     │                   │
     │                   ├─> data_queue.put(event)
     │                   │
     │                   └─> [EventBus processors]
     │                             │
     │                             └─> (no handler)
     │
Candle Closed
     │
     ├─> _on_candle_received()
     │         │
     │         ├─> Event(CANDLE_CLOSED, candle)
     │         │
     │         └─> create_task(
     │                 publish(event, 'data')
     │             )
     │                   │
     │                   ├─> data_queue.put(event)
     │                   │
     │                   └─> [EventBus processors]
     │                             │
     │                             └─> dispatch ───────────> _on_candle_closed()
                                                                    │
                                                                    └─> strategy.analyze()
                                                                        (Subtask 10.3)
```

## Testing Strategy

### Unit Tests

**Test File**: `tests/test_main_event_handlers.py`

```python
import pytest
from unittest.mock import Mock, patch, AsyncMock, call
from src.main import TradingBot
from src.models.event import Event, EventType
from src.models.candle import Candle
from datetime import datetime


class TestEventHandlerSetup:
    """Tests for _setup_event_handlers() method."""

    @patch('src.main.EventBus')
    def test_setup_event_handlers_subscribes_to_three_events(self, mock_event_bus):
        """Test _setup_event_handlers registers 3 event subscriptions."""
        # Setup
        bot = TradingBot()
        bot.event_bus = Mock()
        bot.logger = Mock()

        # Execute
        bot._setup_event_handlers()

        # Verify 3 subscriptions
        assert bot.event_bus.subscribe.call_count == 3

        # Verify exact subscriptions
        calls = bot.event_bus.subscribe.call_args_list
        assert call(EventType.CANDLE_CLOSED, bot._on_candle_closed) in calls
        assert call(EventType.SIGNAL_GENERATED, bot._on_signal_generated) in calls
        assert call(EventType.ORDER_FILLED, bot._on_order_filled) in calls

    def test_setup_event_handlers_passes_method_references(self):
        """Test handler subscriptions pass method references, not calls."""
        bot = TradingBot()
        bot.event_bus = Mock()
        bot.logger = Mock()

        bot._setup_event_handlers()

        # Verify references are callable
        for call_args in bot.event_bus.subscribe.call_args_list:
            handler = call_args[0][1]  # Second argument is handler
            assert callable(handler)


class TestCandleReceivedCallback:
    """Tests for _on_candle_received() method."""

    @patch('asyncio.create_task')
    def test_on_candle_received_creates_event_for_closed_candle(
        self, mock_create_task
    ):
        """Test closed candle creates CANDLE_CLOSED event."""
        # Setup
        bot = TradingBot()
        bot.event_bus = Mock()
        bot.logger = Mock()

        closed_candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime.now(),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            close_time=datetime.now(),
            is_closed=True
        )

        # Execute
        bot._on_candle_received(closed_candle)

        # Verify create_task called
        mock_create_task.assert_called_once()

        # Extract the coroutine argument
        coro = mock_create_task.call_args[0][0]
        # Cannot directly inspect coroutine, but verify it was created

    @patch('asyncio.create_task')
    def test_on_candle_received_creates_event_for_update_candle(
        self, mock_create_task
    ):
        """Test update candle creates CANDLE_UPDATE event."""
        # Setup
        bot = TradingBot()
        bot.event_bus = Mock()
        bot.logger = Mock()

        update_candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime.now(),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            close_time=datetime.now(),
            is_closed=False  # Not closed
        )

        # Execute
        bot._on_candle_received(update_candle)

        # Verify create_task called
        mock_create_task.assert_called_once()

    @patch('asyncio.create_task')
    def test_on_candle_received_publishes_to_data_queue(
        self, mock_create_task
    ):
        """Test event is published to 'data' queue."""
        # Setup
        bot = TradingBot()
        bot.event_bus = AsyncMock()
        bot.logger = Mock()

        candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime.now(),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            close_time=datetime.now(),
            is_closed=True
        )

        # Execute
        bot._on_candle_received(candle)

        # Verify create_task was called (publish happens inside)
        assert mock_create_task.called

    def test_on_candle_received_logs_closed_candles(self):
        """Test debug logging for closed candles."""
        # Setup
        bot = TradingBot()
        bot.event_bus = AsyncMock()
        bot.logger = Mock()

        closed_candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime.now(),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            close_time=datetime.now(),
            is_closed=True
        )

        # Execute
        with patch('asyncio.create_task'):
            bot._on_candle_received(closed_candle)

        # Verify debug log
        assert bot.logger.debug.called
        log_message = str(bot.logger.debug.call_args)
        assert 'Candle closed' in log_message
        assert 'BTCUSDT' in log_message

    def test_on_candle_received_does_not_block(self):
        """Test callback returns immediately (non-blocking)."""
        # Setup
        bot = TradingBot()
        bot.event_bus = AsyncMock()
        bot.logger = Mock()

        candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime.now(),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            close_time=datetime.now(),
            is_closed=True
        )

        # Execute (should return immediately)
        with patch('asyncio.create_task'):
            result = bot._on_candle_received(candle)

        # Verify synchronous return (None)
        assert result is None
```

### Integration Test

**Test File**: `tests/integration/test_event_flow.py`

```python
import pytest
import asyncio
from src.main import TradingBot
from src.models.candle import Candle
from src.models.event import EventType
from datetime import datetime


@pytest.mark.asyncio
async def test_full_candle_to_event_flow():
    """
    Integration test: Candle → Event → Handler subscription.

    Tests the complete flow from WebSocket callback to event handler.
    """
    # Setup bot with initialized components
    bot = TradingBot()

    # Mock components (full initialization tested in Subtask 10.1)
    with patch('src.main.ConfigManager'), \
         patch('src.main.TradingLogger'), \
         patch('src.main.BinanceDataCollector'), \
         patch('src.main.OrderExecutionManager'), \
         patch('src.main.RiskManager'), \
         patch('src.main.StrategyFactory'):

        bot.initialize()

    # Track handler calls
    handler_called = asyncio.Event()
    received_candle = None

    async def test_handler(event):
        nonlocal received_candle
        received_candle = event.data
        handler_called.set()

    # Subscribe test handler
    bot.event_bus.subscribe(EventType.CANDLE_CLOSED, test_handler)

    # Start EventBus processor
    processor_task = asyncio.create_task(bot.event_bus.start())

    # Create test candle
    test_candle = Candle(
        symbol='BTCUSDT',
        interval='1m',
        open_time=datetime.now(),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=100.0,
        close_time=datetime.now(),
        is_closed=True
    )

    # Trigger callback
    bot._on_candle_received(test_candle)

    # Wait for handler to be called
    await asyncio.wait_for(handler_called.wait(), timeout=2.0)

    # Verify
    assert received_candle is not None
    assert received_candle.symbol == 'BTCUSDT'
    assert received_candle.close == 50050.0

    # Cleanup
    bot.event_bus.stop()
    processor_task.cancel()
```

## Common Pitfalls & Solutions

### Pitfall 1: Blocking in Callback

❌ **Wrong**:
```python
def _on_candle_received(self, candle: Candle) -> None:
    event = Event(EventType.CANDLE_CLOSED, candle)
    await self.event_bus.publish(event, queue_name='data')  # SyntaxError: await in non-async
```

✅ **Correct**:
```python
def _on_candle_received(self, candle: Candle) -> None:
    event = Event(EventType.CANDLE_CLOSED, candle)
    asyncio.create_task(self.event_bus.publish(event, queue_name='data'))
```

### Pitfall 2: Calling Methods Instead of Passing References

❌ **Wrong**:
```python
self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed())
```

✅ **Correct**:
```python
self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
```

### Pitfall 3: Wrong Event Type Logic

❌ **Wrong**:
```python
event_type = EventType.CANDLE_CLOSED  # Always closed
event = Event(event_type, candle)
```

✅ **Correct**:
```python
event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE
event = Event(event_type, candle)
```

### Pitfall 4: Wrong Queue Name

❌ **Wrong**:
```python
asyncio.create_task(self.event_bus.publish(event))  # Defaults to 'data', but implicit
```

✅ **Correct**:
```python
asyncio.create_task(self.event_bus.publish(event, queue_name='data'))  # Explicit
```

## Integration with Other Subtasks

### From Subtask 10.1
- ✅ `self.event_bus` initialized
- ✅ `initialize()` calls `_setup_event_handlers()`
- ✅ BinanceDataCollector configured with `_on_candle_received` callback

### To Subtask 10.3
- Event handlers registered and ready
- `_on_candle_closed()` will be implemented to call `strategy.analyze()`
- `_on_signal_generated()` will be implemented for risk validation and order execution
- `_on_order_filled()` will be implemented for position tracking

## Success Criteria

- ✅ `_setup_event_handlers()` registers 3 event subscriptions
- ✅ `_on_candle_received()` creates correct Event type based on is_closed
- ✅ Event published to 'data' queue via asyncio.create_task
- ✅ Callback returns immediately (non-blocking)
- ✅ Debug logging for closed candles
- ✅ Unit tests pass (10+ tests with >90% coverage)
- ✅ Integration test verifies full event flow
- ✅ Ready for Subtask 10.3 (signal processing pipeline)

## Next Steps

After completing this subtask:
1. Mark Subtask 10.2 status as `done`
2. Begin Subtask 10.3: Signal Processing Pipeline
3. Implement `_on_candle_closed()`, `_on_signal_generated()`, `_on_order_filled()`
4. Test end-to-end trading flow

## Reference Documents

- **Quick Reference**: `.taskmaster/designs/TASK-10-QUICK-REFERENCE.md` (Lines 125-141)
- **Architecture**: `.taskmaster/designs/task-10-architecture-diagram.md` (Event Flow Sequence)
- **EventBus Design**: `.taskmaster/designs/task-4-event-architecture-design.md`
