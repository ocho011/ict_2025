# Task #4: Event-Driven Architecture Design Specification

**Version**: 1.0
**Date**: 2025-12-11
**Complexity**: 7/10 (Medium)
**Status**: Design Phase

---

## 1. Executive Summary

### 1.1 Overview
Event-driven architecture using asyncio with multi-queue system to implement non-blocking data → signal → order pipeline for cryptocurrency trading system.

### 1.2 Key Components
- **EventBus**: Central pub-sub coordinator with 3 priority queues
- **TradingEngine**: Main application orchestrator and component coordinator
- **Queue System**: data (1000), signal (100), order (50) with priority-based overflow handling

### 1.3 Design Goals
✅ **Non-blocking operation**: asyncio-based async/await patterns
✅ **Event jamming prevention**: Separate queues with priority handling
✅ **Reliability**: Handler error isolation, graceful shutdown
✅ **Scalability**: 1000+ events/sec throughput capacity

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      TradingEngine                          │
│  (Component Orchestrator & Event Handler Registration)     │
└────────────┬────────────────────────────────┬───────────────┘
             │                                │
             │ Injects Components             │ Registers Handlers
             │                                │
             ▼                                ▼
┌─────────────────────┐            ┌──────────────────────────┐
│  BinanceCollector   │            │       EventBus           │
│  (Task #3)          │──publish──▶│  ┌─────────────────┐    │
└─────────────────────┘            │  │ Subscriber      │    │
                                   │  │ Registry        │    │
┌─────────────────────┐            │  └────────┬────────┘    │
│  Strategy           │            │           │              │
│  (Task #5)          │◀──notify───┤           │              │
└──────┬──────────────┘            │           ▼              │
       │                           │  ┌─────────────────┐    │
       │publish                    │  │  Queue System   │    │
       ▼                           │  │                 │    │
┌─────────────────────┐            │  │ Data Queue     │    │
│  OrderExecution     │            │  │ (1000 events)  │    │
│  (Task #6)          │◀──notify───┤  │ DROP on full   │    │
└─────────────────────┘            │  │                │    │
                                   │  │ Signal Queue   │    │
                                   │  │ (100 events)   │    │
                                   │  │ BLOCK on full  │    │
                                   │  │                │    │
                                   │  │ Order Queue    │    │
                                   │  │ (50 events)    │    │
                                   │  │ NEVER drop     │    │
                                   │  └────────┬────────┘    │
                                   │           │              │
                                   │           ▼              │
                                   │  ┌─────────────────┐    │
                                   │  │ 3 Async Queue   │    │
                                   │  │ Processors      │    │
                                   │  │ (data/sig/ord)  │    │
                                   │  └─────────────────┘    │
                                   └──────────────────────────┘
```

### 2.2 Event Flow Pipeline

```
1. CANDLE_CLOSED Event (Data Queue)
   BinanceCollector.on_candle_close()
      → EventBus.publish(CANDLE_CLOSED, candle, queue='data')
      → Data Queue Processor
      → Strategy._on_candle_closed(event)

2. SIGNAL_GENERATED Event (Signal Queue)
   Strategy.analyze(candle)
      → EventBus.publish(SIGNAL_GENERATED, signal, queue='signal')
      → Signal Queue Processor
      → OrderExecution._on_signal(event)

3. ORDER_CREATED Event (Order Queue)
   OrderExecution.create_order(signal)
      → EventBus.publish(ORDER_CREATED, order, queue='order')
      → Order Queue Processor
      → Exchange.execute_order(event)
```

### 2.3 Component Interaction Matrix

| Component | Publishes | Subscribes | Queue Used |
|-----------|-----------|------------|------------|
| BinanceCollector | CANDLE_CLOSED | - | data |
| Strategy | SIGNAL_GENERATED | CANDLE_CLOSED | signal |
| OrderExecution | ORDER_CREATED | SIGNAL_GENERATED | order |
| TradingEngine | - | All (coordinator) | - |

---

## 3. EventBus Design

### 3.1 Core Responsibilities
1. **Subscriber Management**: Register handlers for EventType
2. **Event Publishing**: Route events to appropriate queues
3. **Queue Processing**: Async processors for each queue
4. **Lifecycle Management**: Start/stop/shutdown coordination

### 3.2 EventBus Class Structure

```python
class EventBus:
    """
    Central event coordination with multi-queue priority system.

    Architecture:
        - Pub-Sub pattern for loose coupling
        - 3 async queue processors running concurrently
        - Priority-based overflow handling
        - Graceful shutdown with pending event processing
    """

    def __init__(self):
        # Subscriber registry: EventType → List[Callable]
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)

        # Multi-queue system with priority handling
        self._queues: Dict[str, asyncio.Queue] = {
            'data': asyncio.Queue(maxsize=1000),    # High throughput, can drop
            'signal': asyncio.Queue(maxsize=100),   # Medium priority, must process
            'order': asyncio.Queue(maxsize=50)      # Critical, never drop
        }

        # Lifecycle state
        self._running: bool = False
        self._processor_tasks: List[asyncio.Task] = []
        self.logger = logging.getLogger(__name__)

    # === Subscription API ===
    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Register handler for event type. Supports sync/async handlers."""

    # === Publishing API ===
    async def publish(self, event: Event, queue_name: str = 'data') -> None:
        """Publish event to specified queue with priority-based overflow."""

    # === Queue Processing ===
    async def _process_queue(self, queue_name: str) -> None:
        """Async processor: polls queue, dispatches to handlers, error isolation."""

    # === Lifecycle Management ===
    async def start(self) -> None:
        """Start all queue processors concurrently."""

    def stop(self) -> None:
        """Signal processors to stop gracefully."""

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Graceful shutdown with pending event processing."""
```

### 3.3 Queue Priority System

#### 3.3.1 Data Queue (High Throughput)
```python
# Configuration
maxsize = 1000
overflow_policy = "DROP"
timeout = 1.0 second

# Use Case
- Binance candle updates (1 event/sec per symbol)
- Latest data is most valuable
- Missing one candle update is acceptable

# Implementation
try:
    await asyncio.wait_for(
        self._queues['data'].put(event),
        timeout=1.0
    )
except asyncio.TimeoutError:
    self.logger.warning(f"Data queue full, dropping event: {event.event_type}")
    # Metrics: increment drop counter
```

#### 3.3.2 Signal Queue (Medium Priority)
```python
# Configuration
maxsize = 100
overflow_policy = "BLOCK"
timeout = 5.0 seconds

# Use Case
- Strategy-generated trading signals
- Must not lose signals (opportunity cost)
- Backpressure to strategy if queue full

# Implementation
try:
    await asyncio.wait_for(
        self._queues['signal'].put(event),
        timeout=5.0
    )
except asyncio.TimeoutError:
    self.logger.error(f"Signal queue blocked for 5s: {event}")
    raise QueueFullError("Signal queue saturated")
```

#### 3.3.3 Order Queue (Critical)
```python
# Configuration
maxsize = 50
overflow_policy = "NEVER_DROP"
timeout = None (unlimited)

# Use Case
- Order execution instructions
- Financial risk if dropped
- Must guarantee delivery

# Implementation
await self._queues['order'].put(event)  # No timeout, will block
# Alternative: Persistent queue with disk backup
```

### 3.4 Queue Processor Implementation

```python
async def _process_queue(self, queue_name: str) -> None:
    """
    Async queue processor with error isolation.

    Guarantees:
        - Handler errors don't crash processor
        - Events processed in FIFO order
        - Both sync/async handlers supported
        - Metrics logged for monitoring
    """
    queue = self._queues[queue_name]

    while self._running:
        try:
            # Non-blocking get with timeout (allows clean shutdown)
            event = await asyncio.wait_for(queue.get(), timeout=0.1)

            # Get registered handlers for this event type
            handlers = self._subscribers.get(event.event_type, [])

            # Execute each handler sequentially
            for handler in handlers:
                try:
                    start_time = time.time()

                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)  # Sync handler

                    # Metrics: handler execution time
                    execution_time = time.time() - start_time
                    self.logger.debug(
                        f"Handler {handler.__name__} executed in {execution_time:.3f}s"
                    )

                except Exception as e:
                    # CRITICAL: Handler errors must not crash processor
                    self.logger.error(
                        f"Handler error in {queue_name} queue: {handler.__name__}",
                        exc_info=True
                    )
                    # Continue processing other handlers

            # Mark task done (for queue.join())
            queue.task_done()

        except asyncio.TimeoutError:
            # No event available, loop continues (allows shutdown check)
            continue

        except Exception as e:
            self.logger.error(f"Queue processor error: {e}", exc_info=True)
            # Processor continues running despite errors
```

### 3.5 Lifecycle Management

#### 3.5.1 Startup Sequence
```python
async def start(self) -> None:
    """
    Start all queue processors concurrently.

    Pattern: asyncio.gather() with return_exceptions=True
    - All 3 processors run in parallel
    - Exceptions don't cancel other processors
    - Blocks until stop() is called
    """
    self._running = True
    self.logger.info("Starting EventBus processors")

    # Create processor tasks
    tasks = [
        asyncio.create_task(self._process_queue('data'), name='data_processor'),
        asyncio.create_task(self._process_queue('signal'), name='signal_processor'),
        asyncio.create_task(self._process_queue('order'), name='order_processor')
    ]
    self._processor_tasks = tasks

    # Wait for all processors (runs until _running = False)
    await asyncio.gather(*tasks, return_exceptions=True)
```

#### 3.5.2 Graceful Shutdown
```python
async def shutdown(self, timeout: float = 5.0) -> None:
    """
    Graceful shutdown with pending event processing.

    Sequence:
        1. Signal stop (self._running = False)
        2. Wait for queues to drain (queue.join())
        3. Cancel processor tasks if timeout exceeded
        4. Log any pending events for manual review

    Critical: Order queue must be fully processed
    """
    self.logger.info("Initiating EventBus shutdown")
    self.stop()  # Set _running = False

    # Wait for each queue to empty
    for name, queue in self._queues.items():
        try:
            self.logger.info(f"Draining {name} queue ({queue.qsize()} events)")
            await asyncio.wait_for(queue.join(), timeout=timeout)
            self.logger.info(f"{name} queue drained")
        except asyncio.TimeoutError:
            remaining = queue.qsize()
            self.logger.warning(
                f"{name} queue didn't empty in {timeout}s "
                f"({remaining} events remaining)"
            )
            # CRITICAL: Log pending order events for manual review
            if name == 'order':
                self._log_pending_orders(queue)

    # Cancel processor tasks
    for task in self._processor_tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    self.logger.info("EventBus shutdown complete")
```

---

## 4. TradingEngine Design

### 4.1 Orchestrator Responsibilities
1. **Component Lifecycle**: Initialize, start, stop all components
2. **Dependency Injection**: Wire up data_collector, strategy, order_manager
3. **Event Handler Registration**: Connect pipeline (data → signal → order)
4. **Error Coordination**: Handle system-wide errors and logging

### 4.2 TradingEngine Class Structure

```python
class TradingEngine:
    """
    Main application orchestrator for trading system.

    Design Pattern: Composition Root with Dependency Injection
    - Components are injected (loose coupling)
    - TradingEngine wires them via EventBus
    - Handlers are thin wrappers (delegate to components)
    """

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Core event system
        self.event_bus = EventBus()

        # Components (injected externally)
        self.data_collector = None  # BinanceDataCollector
        self.strategy = None         # TradingStrategy
        self.order_manager = None    # OrderExecutionManager

        # Setup event handlers
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Register event handlers for trading pipeline."""
        self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal)
        self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)
        self.event_bus.subscribe(EventType.ERROR, self._on_error)

    # === Thin Wrapper Handlers ===
    async def _on_candle_closed(self, event: Event) -> None:
        """Data → Signal: Delegate to strategy."""

    async def _on_signal(self, event: Event) -> None:
        """Signal → Order: Delegate to order manager."""

    async def _on_order_filled(self, event: Event) -> None:
        """Order → Position: Position management logic."""

    async def _on_error(self, event: Event) -> None:
        """System error handling and recovery."""

    # === Lifecycle Management ===
    async def run(self) -> None:
        """Start all components and event bus."""

    async def shutdown(self) -> None:
        """Gracefully stop all components."""

    # === Component Injection ===
    def set_data_collector(self, collector) -> None:
    def set_strategy(self, strategy) -> None:
    def set_order_manager(self, manager) -> None:
```

### 4.3 Handler Implementation Patterns

#### 4.3.1 Data → Signal Handler
```python
async def _on_candle_closed(self, event: Event) -> None:
    """
    Handle new candle data → generate trading signal.

    Flow:
        1. Extract candle from event
        2. Call strategy.analyze() (async)
        3. If signal generated, publish to signal queue

    Error Handling:
        - Strategy.analyze() errors are caught here
        - Logged but don't crash system
        - Event processing continues
    """
    candle = event.data
    self.logger.debug(f"Candle closed: {candle.symbol} @ {candle.close_time}")

    if not self.strategy:
        self.logger.warning("No strategy configured, skipping analysis")
        return

    try:
        # Strategy analyzes candle (may return None)
        signal = await self.strategy.analyze(candle)

        if signal:
            self.logger.info(
                f"Signal generated: {signal.direction} {signal.symbol} @ {signal.price}"
            )
            await self.event_bus.publish(
                Event(EventType.SIGNAL_GENERATED, signal, source='strategy'),
                queue_name='signal'
            )
    except Exception as e:
        self.logger.error(f"Strategy analysis error: {e}", exc_info=True)
        # Publish error event for monitoring
        await self.event_bus.publish(
            Event(EventType.ERROR, {'component': 'strategy', 'error': str(e)}),
            queue_name='signal'
        )
```

#### 4.3.2 Signal → Order Handler
```python
async def _on_signal(self, event: Event) -> None:
    """
    Handle trading signal → create order.

    Flow:
        1. Extract signal from event
        2. Call order_manager.create_order() (async)
        3. Publish ORDER_CREATED to order queue

    Critical: Order creation errors must be logged extensively
    """
    signal = event.data
    self.logger.info(f"Processing signal: {signal.direction} {signal.symbol}")

    if not self.order_manager:
        self.logger.error("No order manager configured")
        return

    try:
        # Create order from signal
        order = await self.order_manager.create_order(signal)

        if order:
            self.logger.info(f"Order created: {order.order_id} ({order.order_type})")
            await self.event_bus.publish(
                Event(EventType.ORDER_CREATED, order, source='order_manager'),
                queue_name='order'
            )
    except Exception as e:
        self.logger.error(
            f"Order creation error for {signal.symbol}: {e}",
            exc_info=True
        )
        # Critical: Persist failed order attempt for review
        await self._persist_failed_order(signal, e)
```

### 4.4 Component Run Pattern

```python
async def run(self) -> None:
    """
    Start trading engine and all components.

    Startup Order:
        1. Start EventBus processors
        2. Start data collector WebSocket
        3. Wait for shutdown signal

    Shutdown Triggers:
        - KeyboardInterrupt (Ctrl+C)
        - SIGTERM signal
        - Unrecoverable error
    """
    self.logger.info("Starting TradingEngine")

    try:
        # Start all components concurrently
        await asyncio.gather(
            self.event_bus.start(),
            self.data_collector.start_streaming() if self.data_collector else asyncio.sleep(0),
            return_exceptions=True
        )
    except KeyboardInterrupt:
        self.logger.info("Shutdown requested (KeyboardInterrupt)")
    except Exception as e:
        self.logger.error(f"TradingEngine error: {e}", exc_info=True)
    finally:
        await self.shutdown()


async def shutdown(self) -> None:
    """
    Gracefully shutdown all components.

    Shutdown Order:
        1. Stop data collector (no new events)
        2. Shutdown EventBus (process pending events)
        3. Close all connections
    """
    self.logger.info("Shutting down TradingEngine")

    # Stop data source first (prevent new events)
    if self.data_collector:
        self.logger.info("Stopping data collector")
        await self.data_collector.stop()

    # Shutdown event bus (process pending events)
    self.logger.info("Shutting down event bus")
    await self.event_bus.shutdown(timeout=10.0)

    self.logger.info("TradingEngine shutdown complete")
```

---

## 5. Error Handling & Resilience

### 5.1 Error Categories

| Error Type | Handling Strategy | Recovery Action |
|------------|-------------------|-----------------|
| Handler Exception | Catch, log, continue processing | Publish ERROR event |
| Queue Overflow | Data: drop, Signal/Order: block | Log + alert |
| WebSocket Disconnect | Reconnect with exponential backoff | Maintain event queue |
| Exchange API Error | Retry with backoff (order queue) | Persist for manual review |
| Shutdown Timeout | Force cancel tasks | Log pending events |

### 5.2 Handler Error Isolation

```python
# In _process_queue()
for handler in handlers:
    try:
        if asyncio.iscoroutinefunction(handler):
            await handler(event)
        else:
            handler(event)
    except Exception as e:
        # CRITICAL: Errors must not crash processor
        self.logger.error(
            f"Handler {handler.__name__} failed in {queue_name} queue",
            exc_info=True,
            extra={'event_type': event.event_type, 'event_data': event.data}
        )
        # Metrics: increment handler error counter
        # Continue to next handler
```

### 5.3 System Error Event Pattern

```python
# Add ERROR event type
class EventType(Enum):
    # ... existing types ...
    ERROR = "error"

# Publish errors to signal queue (medium priority)
await self.event_bus.publish(
    Event(
        EventType.ERROR,
        {
            'component': 'strategy',
            'error_type': type(e).__name__,
            'error_message': str(e),
            'context': {'candle': candle.to_dict()}
        },
        source='trading_engine'
    ),
    queue_name='signal'
)

# TradingEngine._on_error() handles recovery
async def _on_error(self, event: Event) -> None:
    error_data = event.data
    component = error_data['component']

    if component == 'strategy':
        # Strategy errors are non-critical (skip this candle)
        self.logger.warning(f"Strategy error: {error_data['error_message']}")
    elif component == 'order_manager':
        # Order errors are critical (alert + persist)
        self.logger.critical(f"Order manager error: {error_data}")
        await self._alert_critical_error(error_data)
```

---

## 6. Performance & Capacity Analysis

### 6.1 Throughput Requirements

| Component | Expected Load | Capacity | Margin |
|-----------|--------------|----------|--------|
| Data Queue | 10 events/sec (10 symbols × 1s candle) | 1000 events | 100x |
| Signal Queue | 1 event/10 sec (1 signal per 10 candles) | 100 events | 1000x |
| Order Queue | 1 order/min | 50 events | 50x |

### 6.2 Handler Performance Budget

```python
# Target: <10ms per handler to avoid queue buildup
async def _on_candle_closed(self, event: Event) -> None:
    # Light computation only
    candle = event.data  # <0.1ms
    signal = await self.strategy.analyze(candle)  # <5ms target
    if signal:
        await self.event_bus.publish(...)  # <1ms
    # Total: <10ms
```

### 6.3 Memory Footprint

```python
# Event object: ~1KB (Candle with OHLCV + metadata)
# Queue capacity:
#   - Data: 1000 events × 1KB = 1MB
#   - Signal: 100 events × 1KB = 100KB
#   - Order: 50 events × 1KB = 50KB
# Total: ~1.5MB for all queues (negligible)
```

### 6.4 Bottleneck Analysis

**Potential Bottlenecks:**
1. Strategy.analyze() taking >100ms → Blocks signal generation
2. Order API calls taking >5s → Backs up order queue
3. WebSocket receiving >100 events/sec → Data queue overflow

**Mitigation Strategies:**
1. Strategy: Offload heavy computation to separate tasks
2. Order API: Use async HTTP client with connection pooling
3. Data queue: Increase size or implement sampling

---

## 7. Testing Strategy

### 7.1 Unit Tests (Per Subtask)

#### EventBus Core (Subtask 4.1)
```python
def test_subscribe_adds_handler():
    bus = EventBus()
    handler = lambda e: None
    bus.subscribe(EventType.CANDLE_CLOSED, handler)
    assert handler in bus._subscribers[EventType.CANDLE_CLOSED]

def test_multiple_handlers_same_event():
    bus = EventBus()
    h1, h2 = lambda e: None, lambda e: None
    bus.subscribe(EventType.CANDLE_CLOSED, h1)
    bus.subscribe(EventType.CANDLE_CLOSED, h2)
    assert len(bus._subscribers[EventType.CANDLE_CLOSED]) == 2
```

#### Multi-Queue System (Subtask 4.2)
```python
async def test_data_queue_drops_on_overflow():
    bus = EventBus()
    # Fill queue beyond maxsize
    for i in range(1001):
        await bus.publish(Event(EventType.CANDLE_CLOSED, f"event_{i}"))
    # Verify drop behavior
    assert bus._queues['data'].qsize() <= 1000

async def test_order_queue_blocks_on_overflow():
    bus = EventBus()
    # Fill order queue to maxsize
    for i in range(50):
        await bus.publish(Event(EventType.ORDER_CREATED, f"order_{i}"), queue_name='order')
    # Next publish should block (use asyncio.wait_for to test)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            bus.publish(Event(EventType.ORDER_CREATED, "order_51"), queue_name='order'),
            timeout=0.1
        )
```

#### Queue Processor (Subtask 4.3)
```python
async def test_handler_exception_doesnt_crash_processor():
    bus = EventBus()

    def failing_handler(event):
        raise ValueError("Test error")

    def working_handler(event):
        working_handler.called = True
    working_handler.called = False

    bus.subscribe(EventType.CANDLE_CLOSED, failing_handler)
    bus.subscribe(EventType.CANDLE_CLOSED, working_handler)

    # Start processor and publish event
    task = asyncio.create_task(bus.start())
    await bus.publish(Event(EventType.CANDLE_CLOSED, "data"))
    await asyncio.sleep(0.1)

    # Verify working handler was still called
    assert working_handler.called

    bus.stop()
    await task
```

### 7.2 Integration Tests

```python
async def test_end_to_end_pipeline():
    """Test data → signal → order pipeline."""
    engine = TradingEngine(config={})

    # Setup components
    collector = MockDataCollector()
    strategy = MockStrategy()
    order_mgr = MockOrderManager()

    engine.set_data_collector(collector)
    engine.set_strategy(strategy)
    engine.set_order_manager(order_mgr)

    # Start engine
    engine_task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.1)  # Let processors start

    # Simulate candle event
    candle = Candle(symbol='BTCUSDT', close=50000, ...)
    await engine.event_bus.publish(
        Event(EventType.CANDLE_CLOSED, candle),
        queue_name='data'
    )

    # Wait for pipeline to process
    await asyncio.sleep(0.5)

    # Verify:
    assert strategy.analyze_called
    assert order_mgr.create_order_called

    # Cleanup
    await engine.shutdown()
    await engine_task
```

### 7.3 Stress Tests

```python
async def test_high_throughput():
    """Verify system handles 1000+ events/sec."""
    bus = EventBus()

    handler_call_count = 0
    def counter_handler(event):
        nonlocal handler_call_count
        handler_call_count += 1

    bus.subscribe(EventType.CANDLE_CLOSED, counter_handler)

    # Start processor
    task = asyncio.create_task(bus.start())

    # Publish 10,000 events rapidly
    start = time.time()
    for i in range(10000):
        await bus.publish(Event(EventType.CANDLE_CLOSED, f"event_{i}"))

    # Wait for processing
    await asyncio.sleep(5)
    elapsed = time.time() - start

    # Verify throughput
    throughput = handler_call_count / elapsed
    assert throughput > 1000, f"Only {throughput:.1f} events/sec"

    bus.stop()
    await task
```

---

## 8. Implementation Plan (5 Subtasks)

### Subtask 4.1: EventBus Core (15-20 min)
**Scope**: Subscriber registry and event routing
**Files**: `src/core/event_handler.py`
**Key Methods**: `__init__`, `subscribe`, `_get_handlers`
**Tests**: Subscription, multiple handlers, empty handlers

### Subtask 4.2: Multi-Queue System (15-20 min)
**Scope**: 3 async queues with overflow handling
**Files**: `src/core/event_handler.py` (extend EventBus)
**Key Methods**: `publish`, `get_queue_stats`
**Tests**: Queue overflow (drop/block), timeout behavior

### Subtask 4.3: Queue Processors (20-25 min)
**Scope**: Async event processing with error isolation
**Files**: `src/core/event_handler.py` (extend EventBus)
**Key Methods**: `_process_queue`
**Tests**: Handler execution (sync/async), error isolation, timeout

### Subtask 4.4: Lifecycle Management (15-20 min)
**Scope**: Start/stop/shutdown with graceful cleanup
**Files**: `src/core/event_handler.py` (extend EventBus)
**Key Methods**: `start`, `stop`, `shutdown`
**Tests**: Task creation, queue draining, timeout behavior

### Subtask 4.5: TradingEngine Orchestrator (20-25 min)
**Scope**: Component coordination and handler registration
**Files**: `src/core/trading_engine.py` (new file)
**Key Methods**: `__init__`, `_setup_handlers`, `_on_*`, `run`, `shutdown`
**Tests**: Handler registration, pipeline flow, component injection

**Total Estimated Time**: 85-110 minutes (~1.5-2 hours)

---

## 9. Success Criteria

### 9.1 Functional Requirements
✅ EventBus supports subscribe/publish for all EventType
✅ 3 queues (data/signal/order) with correct overflow behavior
✅ Queue processors handle sync/async handlers
✅ Handler errors don't crash processors
✅ Graceful shutdown processes pending events
✅ TradingEngine wires data → signal → order pipeline

### 9.2 Non-Functional Requirements
✅ Throughput: >1000 events/sec
✅ Handler latency: <10ms average
✅ Memory footprint: <10MB
✅ Shutdown time: <10s with pending events
✅ Test coverage: >90%

### 9.3 Integration Requirements
✅ BinanceDataCollector (Task #3) publishes CANDLE_CLOSED
✅ Strategy (Task #5) subscribes to CANDLE_CLOSED, publishes SIGNAL_GENERATED
✅ OrderExecution (Task #6) subscribes to SIGNAL_GENERATED
✅ All components use Event model from `src/models/event.py`

---

## 10. Risk Analysis

### 10.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Handler deadlock | Low | High | Use asyncio.wait_for with timeouts |
| Queue overflow | Medium | Medium | Priority-based drop/block strategy |
| Memory leak | Low | High | Limit queue sizes, test with stress tests |
| Shutdown hang | Medium | Medium | Timeout-based force cancel |

### 10.2 Business Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Lost order events | Low | Critical | Order queue never drops + persist |
| Missed trading signals | Medium | High | Signal queue blocks (backpressure) |
| Stale data | High | Low | Data queue drops old events |

---

## 11. Future Enhancements

### 11.1 Phase 2 Features (Post-Task #4)
- Event persistence (order queue → database)
- Metrics dashboard (queue depth, handler latency)
- Dead letter queue for failed events
- Event replay capability for testing
- Multiple strategy support (fan-out pattern)

### 11.2 Scalability Improvements
- Distributed event bus (Redis Pub/Sub)
- Event partitioning by symbol
- Load balancing across multiple processors
- Event compression for high-frequency data

---

## 12. References

### 12.1 Design Patterns
- **Pub-Sub Pattern**: EventBus as message broker
- **Observer Pattern**: Handler subscription model
- **Queue Pattern**: Priority-based message queuing
- **Dependency Injection**: TradingEngine composition root

### 12.2 Asyncio Resources
- Context7: `/agronholm/anyio` (task groups, cancellation)
- Python asyncio documentation (Queue, Task, gather)
- Backpressure patterns in async systems

### 12.3 Related Tasks
- Task #2: Data Models (Event, EventType)
- Task #3: BinanceDataCollector (event publisher)
- Task #5: Strategy (event subscriber + publisher)
- Task #6: OrderExecution (event subscriber)

---

**Document End**
