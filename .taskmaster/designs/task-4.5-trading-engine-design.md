# Subtask 4.5: TradingEngine Orchestrator Design

**Parent Task**: Task #4 - Event-Driven Architecture & Async Queue System
**Dependencies**: Subtask 4.4 (EventBus Lifecycle) ✅
**Complexity**: 7/10 (Medium-High)
**Status**: Design Phase

## 1. Objective

Create the **TradingEngine** class that serves as the main application orchestrator, managing component lifecycle, registering event handlers, and coordinating the complete trading pipeline: Data → Strategy → Signal → Order.

**Scope**:
- Implement TradingEngine class with component injection
- Register event handlers for trading pipeline
- Implement event handler methods for data/signal/order flow
- Implement `run()` and `shutdown()` lifecycle methods
- Error handling and logging throughout

**Out of Scope**:
- Strategy implementation (Task #5)
- Risk management implementation (Task #6)
- Order execution logic (later tasks)
- Position tracking implementation (later tasks)

## 2. Architecture Overview

### 2.1 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      TradingEngine                          │
│  (Main Orchestrator - Coordinates All Components)          │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  EventBus    │    │DataCollector │    │  Strategy    │
│  (Task 4.4)  │    │  (Task 3)    │    │ (Placeholder)│
└──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │
        │                   │                   │
        └───────────────────┴───────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │OrderManager  │
                    │(Placeholder) │
                    └──────────────┘
```

### 2.2 Event Flow Pipeline

```
┌──────────────────────────────────────────────────────────────┐
│                    Trading Event Pipeline                     │
└──────────────────────────────────────────────────────────────┘

1. DataCollector → CANDLE_CLOSED event → data queue
                          ↓
2. _on_candle_closed() → Strategy.analyze(candle)
                          ↓
3. Strategy returns Signal → SIGNAL_GENERATED event → signal queue
                          ↓
4. _on_signal() → OrderManager.create_order(signal)
                          ↓
5. OrderManager creates Order → ORDER_PLACED event → order queue
                          ↓
6. Exchange confirms → ORDER_FILLED event → order queue
                          ↓
7. _on_order_filled() → Position update (future implementation)
```

## 3. Design Specifications

### 3.1 TradingEngine Class Definition

**File**: `src/core/trading_engine.py`

```python
"""
TradingEngine: Main orchestrator for automated trading system.

Coordinates:
- Real-time data collection from Binance
- Strategy-based signal generation
- Order execution and position management
- Event-driven async pipeline with graceful shutdown
"""

import asyncio
import logging
from typing import Optional

from src.core.event_handler import EventBus
from src.core.data_collector import BinanceDataCollector
from src.models.event import Event, EventType
from src.models.candle import Candle
from src.models.signal import Signal
from src.execution.order_manager import OrderManager


class TradingEngine:
    """
    Main application orchestrator for event-driven trading system.

    Responsibilities:
    1. Component lifecycle management (EventBus, DataCollector, Strategy, OrderManager)
    2. Event handler registration for trading pipeline
    3. Event routing: CANDLE_CLOSED → SIGNAL_GENERATED → ORDER_PLACED → ORDER_FILLED
    4. Graceful startup and shutdown with pending event processing
    5. Error isolation and logging

    Architecture:
        - Uses dependency injection for all components (testability)
        - Event-driven async pipeline prevents blocking
        - Error handlers prevent cascade failures
        - Graceful shutdown ensures order queue drains

    Lifecycle:
        ```python
        engine = TradingEngine(config)
        engine.set_data_collector(collector)
        engine.set_strategy(strategy)
        engine.set_order_manager(manager)

        await engine.run()  # Blocks until KeyboardInterrupt
        # Automatic shutdown with pending event processing
        ```

    Event Handlers:
        - _on_candle_closed: Candle → Strategy → Signal
        - _on_signal: Signal → OrderManager → Order
        - _on_order_filled: Order → Position update (future)
        - _on_error: System error logging and recovery
    """
```

### 3.2 Constructor & Initialization

```python
def __init__(self, config: dict) -> None:
    """
    Initialize TradingEngine with configuration and components.

    Args:
        config: Configuration dictionary with settings:
            - environment: 'testnet' or 'mainnet'
            - log_level: Logging level (default: 'INFO')
            - Additional strategy/risk parameters

    Attributes:
        config: Configuration dictionary
        logger: Logger instance for engine events
        event_bus: EventBus instance (created immediately)
        data_collector: BinanceDataCollector (injected via setter)
        strategy: Strategy instance (injected via setter)
        order_manager: OrderManager instance (injected via setter)

    Process Flow:
        1. Store config and create logger
        2. Initialize EventBus (core infrastructure)
        3. Set component placeholders to None (inject later)
        4. Call _setup_handlers() to register event handlers

    Notes:
        - EventBus created immediately (always needed)
        - Other components injected via setters (supports testing)
        - Handlers registered even if components None (fail gracefully)
        - Logger uses engine name for component identification

    Example:
        ```python
        config = {
            'environment': 'testnet',
            'log_level': 'DEBUG',
            'strategy_params': {...}
        }
        engine = TradingEngine(config)
        ```
    """
    self.config = config
    self.logger = logging.getLogger(__name__)
    self.logger.setLevel(config.get('log_level', 'INFO'))

    # Core event infrastructure
    self.event_bus = EventBus()

    # Components (inject via setters)
    self.data_collector: Optional[BinanceDataCollector] = None
    self.strategy: Optional[Any] = None  # Strategy interface TBD
    self.order_manager: Optional[OrderManager] = None

    # Register event handlers for trading pipeline
    self._setup_handlers()

    self.logger.info("TradingEngine initialized with config")
```

### 3.3 Event Handler Registration

```python
def _setup_handlers(self) -> None:
    """
    Register event handlers for complete trading pipeline.

    Subscribes handlers to EventBus for:
    - CANDLE_CLOSED: Trigger strategy analysis
    - SIGNAL_GENERATED: Create orders from signals
    - ORDER_FILLED: Update positions (future)
    - ERROR: Log system errors

    Handler Routing:
        - All handlers are async methods
        - Handlers execute sequentially per event type
        - Errors isolated (one fails → others continue)
        - Logging at each pipeline stage

    Notes:
        - Called automatically in __init__()
        - Safe to call even if components None
        - Handlers check component existence before use
        - Private method (internal setup only)

    Example Event Flow:
        CANDLE_CLOSED → _on_candle_closed → Strategy
                     ↓
        SIGNAL_GENERATED → _on_signal → OrderManager
                         ↓
        ORDER_FILLED → _on_order_filled → Position
    """
    self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
    self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal)
    self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)
    # Note: Removed ORDER_PLACED subscription - not needed in pipeline

    self.logger.debug("Event handlers registered for trading pipeline")
```

### 3.4 Event Handler: Candle → Signal

```python
async def _on_candle_closed(self, event: Event) -> None:
    """
    Handle CANDLE_CLOSED event: Analyze candle and generate signal.

    Pipeline Stage: Data → Strategy

    Args:
        event: Event with candle data
            event.data: Candle instance
            event.source: 'BinanceDataCollector'

    Process Flow:
        1. Extract candle from event
        2. Log candle close (DEBUG level)
        3. Check if strategy is configured
        4. Call strategy.analyze(candle)
        5. If signal returned, publish SIGNAL_GENERATED
        6. Handle errors without crashing

    Error Handling:
        - Strategy None: Log warning, skip analysis
        - Strategy.analyze() error: Log error, continue
        - Publish error: Logged by EventBus, not re-raised

    Performance:
        - Should be fast (<10ms) to avoid backlog
        - Heavy analysis → strategy should spawn tasks
        - No blocking I/O in this handler

    Example:
        ```python
        # Incoming event
        event = Event(
            event_type=EventType.CANDLE_CLOSED,
            data=Candle(...),
            source='BinanceDataCollector'
        )

        # Handler processes → strategy.analyze() → signal
        # If signal: publishes SIGNAL_GENERATED to signal queue
        ```

    Notes:
        - Strategy interface: async analyze(candle: Candle) -> Optional[Signal]
        - Signal None is valid (no trade opportunity)
        - Publish to 'signal' queue (medium priority)
    """
    try:
        candle: Candle = event.data
        self.logger.debug(
            f"Candle closed: {candle.symbol} @ {candle.close_time} "
            f"close={candle.close}"
        )

        # Check if strategy is configured
        if not self.strategy:
            self.logger.warning("No strategy configured, skipping analysis")
            return

        # Analyze candle for trading signal
        signal: Optional[Signal] = await self.strategy.analyze(candle)

        if signal:
            self.logger.info(
                f"Signal generated: {signal.signal_type.value} {signal.symbol} "
                f"@ {signal.entry_price}"
            )

            # Publish signal to signal queue
            await self.event_bus.publish(
                Event(
                    event_type=EventType.SIGNAL_GENERATED,
                    data=signal,
                    source='TradingEngine'
                ),
                queue_name='signal'
            )
        else:
            self.logger.debug(f"No signal for {candle.symbol}")

    except Exception as e:
        self.logger.error(
            f"Error in candle handler: {e}",
            exc_info=True
        )
        # Don't re-raise - isolated error handling
```

### 3.5 Event Handler: Signal → Order

```python
async def _on_signal(self, event: Event) -> None:
    """
    Handle SIGNAL_GENERATED event: Convert signal to order.

    Pipeline Stage: Strategy → OrderManager

    Args:
        event: Event with signal data
            event.data: Signal instance
            event.source: 'TradingEngine' or 'Strategy'

    Process Flow:
        1. Extract signal from event
        2. Log signal details (INFO level)
        3. Check if order_manager is configured
        4. Call order_manager.create_order_from_signal(signal)
        5. If order created, publish ORDER_PLACED
        6. Handle errors without crashing

    Error Handling:
        - OrderManager None: Log warning, skip order creation
        - create_order error: Log error, continue
        - Publish error: Logged by EventBus

    Critical for Trading:
        - Signal queue ensures all signals processed
        - Order queue ensures order events never drop
        - Errors logged for post-analysis

    Example:
        ```python
        # Incoming event
        event = Event(
            event_type=EventType.SIGNAL_GENERATED,
            data=Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol='BTCUSDT',
                entry_price=50000,
                ...
            ),
            source='TradingEngine'
        )

        # Handler processes → order_manager.create_order() → order
        # Publishes ORDER_PLACED to order queue
        ```

    Notes:
        - OrderManager interface: async create_order_from_signal(signal) -> Optional[Order]
        - Order None if risk management rejects (future)
        - Publish to 'order' queue (critical priority, never drops)
    """
    try:
        signal: Signal = event.data
        self.logger.info(
            f"Processing signal: {signal.signal_type.value} {signal.symbol} "
            f"entry={signal.entry_price} sl={signal.stop_loss} tp={signal.take_profit}"
        )

        # Check if order manager is configured
        if not self.order_manager:
            self.logger.warning("No order manager configured, skipping order creation")
            return

        # Create order from signal
        # Note: OrderManager method doesn't exist yet - placeholder for future
        # For now, just log the signal processing
        self.logger.info(
            f"Signal processed (order manager integration pending): {signal.symbol}"
        )

        # Future implementation:
        # order = await self.order_manager.create_order_from_signal(signal)
        # if order:
        #     await self.event_bus.publish(
        #         Event(EventType.ORDER_PLACED, order, source='TradingEngine'),
        #         queue_name='order'
        #     )

    except Exception as e:
        self.logger.error(
            f"Error in signal handler: {e}",
            exc_info=True
        )
        # Don't re-raise - isolated error handling
```

### 3.6 Event Handler: Order Filled

```python
async def _on_order_filled(self, event: Event) -> None:
    """
    Handle ORDER_FILLED event: Update position tracking.

    Pipeline Stage: Exchange → Position Management

    Args:
        event: Event with order data
            event.data: Order instance (filled status)
            event.source: 'Exchange' or 'OrderManager'

    Process Flow:
        1. Extract order from event
        2. Log order fill details (INFO level)
        3. Update position tracking (future implementation)
        4. Calculate P&L if position closed
        5. Handle errors without crashing

    Error Handling:
        - Position tracking error: Log error, continue
        - P&L calculation error: Log error, continue
        - All errors isolated (don't crash engine)

    Future Implementation:
        - Position.open() for new positions
        - Position.update() for partial fills
        - Position.close() for exits
        - P&L calculation and tracking

    Example:
        ```python
        # Incoming event
        event = Event(
            event_type=EventType.ORDER_FILLED,
            data=Order(
                order_id='123',
                symbol='BTCUSDT',
                filled_quantity=1.0,
                ...
            ),
            source='Exchange'
        )

        # Handler processes → update position state
        ```

    Notes:
        - Order queue ensures all fills processed
        - Position tracking critical for risk management
        - P&L tracking critical for performance analysis
        - Placeholder implementation for now
    """
    try:
        order = event.data
        self.logger.info(
            f"Order filled: {order.order_id} {order.symbol} "
            f"qty={getattr(order, 'filled_quantity', 'N/A')}"
        )

        # Future implementation:
        # - Update position tracking
        # - Calculate P&L if position closed
        # - Publish POSITION_OPENED or POSITION_CLOSED events
        # - Update risk management state

    except Exception as e:
        self.logger.error(
            f"Error in order filled handler: {e}",
            exc_info=True
        )
        # Don't re-raise - isolated error handling
```

### 3.7 Component Injection Methods

```python
def set_data_collector(self, collector: BinanceDataCollector) -> None:
    """
    Inject DataCollector component for market data streaming.

    Args:
        collector: Configured BinanceDataCollector instance

    Notes:
        - Must be called before run()
        - Collector should have symbols/intervals configured
        - Collector's on_candle_callback will publish CANDLE_CLOSED

    Example:
        ```python
        collector = BinanceDataCollector(
            api_key=key,
            api_secret=secret,
            symbols=['BTCUSDT'],
            intervals=['1h'],
            on_candle_callback=lambda candle: ...
        )
        engine.set_data_collector(collector)
        ```
    """
    self.data_collector = collector
    self.logger.info("DataCollector injected")

def set_strategy(self, strategy) -> None:
    """
    Inject Strategy component for signal generation.

    Args:
        strategy: Strategy instance with analyze() method

    Interface Required:
        async def analyze(self, candle: Candle) -> Optional[Signal]

    Notes:
        - Strategy can be None (dry-run mode)
        - Strategy errors isolated in _on_candle_closed

    Example:
        ```python
        from src.strategies.ict_strategy import ICTStrategy
        strategy = ICTStrategy(config)
        engine.set_strategy(strategy)
        ```
    """
    self.strategy = strategy
    self.logger.info(f"Strategy injected: {type(strategy).__name__}")

def set_order_manager(self, manager: OrderManager) -> None:
    """
    Inject OrderManager component for order execution.

    Args:
        manager: Configured OrderManager instance

    Notes:
        - OrderManager can be None (analysis-only mode)
        - OrderManager errors isolated in _on_signal

    Example:
        ```python
        from src.execution.order_manager import OrderManager
        manager = OrderManager(exchange_client)
        engine.set_order_manager(manager)
        ```
    """
    self.order_manager = manager
    self.logger.info("OrderManager injected")
```

### 3.8 Lifecycle: Run Method

```python
async def run(self) -> None:
    """
    Start the trading engine and run until interrupted.

    Main application entry point that:
    1. Starts EventBus processors (3 queues)
    2. Starts DataCollector streaming (if configured)
    3. Runs until KeyboardInterrupt
    4. Triggers graceful shutdown

    Process Flow:
        1. Log startup message
        2. Validate required components
        3. Start EventBus and DataCollector concurrently
        4. Block until KeyboardInterrupt or component failure
        5. Trigger shutdown() on interrupt
        6. Ensure shutdown() called in finally block

    Error Handling:
        - KeyboardInterrupt: Graceful shutdown
        - Component failure: Log error, trigger shutdown
        - asyncio.gather with return_exceptions=True

    Component Requirements:
        - EventBus: Always required (created in __init__)
        - DataCollector: Optional (None → no data, analysis only)
        - Strategy: Optional (None → no signals)
        - OrderManager: Optional (None → signals only)

    Example:
        ```python
        engine = TradingEngine(config)
        engine.set_data_collector(collector)
        engine.set_strategy(strategy)

        try:
            await engine.run()
        except KeyboardInterrupt:
            print("Shutdown complete")
        ```

    Notes:
        - Blocks until stopped (main loop)
        - Safe to call multiple times (idempotent)
        - Always calls shutdown() (even on errors)
        - EventBus processors run continuously
    """
    self.logger.info("Starting TradingEngine")

    try:
        # Start all components concurrently
        tasks = [
            # EventBus always runs
            asyncio.create_task(
                self.event_bus.start(),
                name='eventbus'
            )
        ]

        # Add DataCollector if configured
        if self.data_collector:
            tasks.append(
                asyncio.create_task(
                    self.data_collector.start_streaming(),
                    name='datacollector'
                )
            )
            self.logger.info("DataCollector streaming enabled")
        else:
            self.logger.warning("No DataCollector configured - analysis only mode")

        # Run until interrupted
        # return_exceptions=True prevents one task error from cancelling others
        await asyncio.gather(*tasks, return_exceptions=True)

    except KeyboardInterrupt:
        self.logger.info("Shutdown requested (KeyboardInterrupt)")

    except Exception as e:
        self.logger.error(f"Unexpected error in run(): {e}", exc_info=True)

    finally:
        # Always shutdown gracefully
        await self.shutdown()
```

### 3.9 Lifecycle: Shutdown Method

```python
async def shutdown(self) -> None:
    """
    Gracefully shutdown all components with pending event processing.

    Shutdown Sequence:
    1. Stop DataCollector (no new candle events)
    2. EventBus.shutdown(timeout=10) drains all queues
    3. All pending events processed or timeout logged

    Args:
        None

    Process Flow:
        1. Log shutdown start
        2. Stop DataCollector if configured
        3. Wait briefly for final events to publish
        4. Shutdown EventBus with 10s timeout per queue
        5. Log shutdown complete

    Error Handling:
        - DataCollector stop error: Log, continue
        - EventBus shutdown error: Log, continue
        - All errors logged, shutdown proceeds

    Timeout Strategy:
        - 10s per queue (30s max total for EventBus)
        - Critical for order queue (ensure orders processed)
        - Data queue can drop (less critical)

    Example:
        ```python
        # Automatic via run()
        await engine.run()  # Calls shutdown() on exit

        # Manual shutdown
        await engine.shutdown()
        ```

    Notes:
        - Safe to call multiple times (idempotent)
        - Always called from run() finally block
        - Blocks until shutdown complete
        - Order events MUST be processed (critical)
    """
    self.logger.info("Shutting down TradingEngine")

    try:
        # Stop data collector first (no new events)
        if self.data_collector:
            self.logger.info("Stopping DataCollector")
            await self.data_collector.stop()

        # Wait briefly for final events to publish
        await asyncio.sleep(0.5)

        # Shutdown EventBus (drains all queues)
        self.logger.info("Shutting down EventBus")
        await self.event_bus.shutdown(timeout=10.0)

    except Exception as e:
        self.logger.error(f"Error during shutdown: {e}", exc_info=True)

    finally:
        self.logger.info("TradingEngine shutdown complete")
```

## 4. Test Strategy

### 4.1 Test File Structure

**File**: `tests/core/test_trading_engine.py`

```python
"""
Unit tests for TradingEngine orchestrator (Subtask 4.5)

Tests component integration, event handlers, and lifecycle management.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.core.trading_engine import TradingEngine
from src.models.event import Event, EventType
from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from datetime import datetime


class TestTradingEngineInit:
    """Test TradingEngine initialization and setup."""

    def test_init_creates_eventbus(self):
        """Verify __init__ creates EventBus instance."""

    def test_init_registers_handlers(self):
        """Verify _setup_handlers() subscribes all event types."""

    def test_component_injection(self):
        """Verify set_*() methods inject components correctly."""


class TestEventHandlers:
    """Test event handler methods."""

    @pytest.mark.asyncio
    async def test_on_candle_closed_calls_strategy(self):
        """Verify _on_candle_closed() calls strategy.analyze()."""

    @pytest.mark.asyncio
    async def test_on_candle_closed_publishes_signal(self):
        """Verify signal published to signal queue when returned."""

    @pytest.mark.asyncio
    async def test_on_candle_closed_handles_no_strategy(self):
        """Verify graceful handling when strategy is None."""

    @pytest.mark.asyncio
    async def test_on_signal_logs_signal(self):
        """Verify _on_signal() logs signal details."""

    @pytest.mark.asyncio
    async def test_on_order_filled_logs_order(self):
        """Verify _on_order_filled() logs order details."""

    @pytest.mark.asyncio
    async def test_handler_errors_isolated(self):
        """Verify handler exceptions don't crash engine."""


class TestLifecycle:
    """Test run() and shutdown() lifecycle methods."""

    @pytest.mark.asyncio
    async def test_run_starts_eventbus(self):
        """Verify run() starts EventBus."""

    @pytest.mark.asyncio
    async def test_run_starts_data_collector(self):
        """Verify run() starts DataCollector if configured."""

    @pytest.mark.asyncio
    async def test_shutdown_stops_components(self):
        """Verify shutdown() stops all components gracefully."""

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_triggers_shutdown(self):
        """Verify KeyboardInterrupt triggers shutdown sequence."""


class TestIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_pipeline_candle_to_signal(self):
        """Integration: Candle → Strategy → Signal → Event."""
```

### 4.2 Test Implementation Details

**Test 1: EventBus Creation**
```python
def test_init_creates_eventbus(self):
    config = {'environment': 'testnet'}
    engine = TradingEngine(config)

    assert engine.event_bus is not None
    assert engine.config == config
    assert engine.data_collector is None
    assert engine.strategy is None
    assert engine.order_manager is None
```

**Test 2: Handler Registration**
```python
def test_init_registers_handlers(self):
    engine = TradingEngine({})

    # Verify handlers subscribed
    candle_handlers = engine.event_bus._get_handlers(EventType.CANDLE_CLOSED)
    signal_handlers = engine.event_bus._get_handlers(EventType.SIGNAL_GENERATED)
    order_handlers = engine.event_bus._get_handlers(EventType.ORDER_FILLED)

    assert len(candle_handlers) == 1
    assert len(signal_handlers) == 1
    assert len(order_handlers) == 1
```

**Test 3: Strategy Integration**
```python
@pytest.mark.asyncio
async def test_on_candle_closed_calls_strategy(self):
    engine = TradingEngine({})

    # Mock strategy
    mock_strategy = AsyncMock()
    mock_signal = Signal(
        signal_type=SignalType.LONG_ENTRY,
        symbol='BTCUSDT',
        entry_price=50000,
        take_profit=55000,
        stop_loss=48000,
        strategy_name='test',
        timestamp=datetime.utcnow()
    )
    mock_strategy.analyze.return_value = mock_signal
    engine.set_strategy(mock_strategy)

    # Create candle event
    candle = Candle(
        symbol='BTCUSDT',
        interval='1h',
        open_time=datetime.utcnow(),
        close_time=datetime.utcnow(),
        open=49000, high=51000, low=48500, close=50000,
        volume=100.0, trades=1000
    )
    event = Event(EventType.CANDLE_CLOSED, candle, source='test')

    # Call handler
    await engine._on_candle_closed(event)

    # Verify strategy called
    mock_strategy.analyze.assert_called_once_with(candle)
```

**Test 4: Lifecycle Integration**
```python
@pytest.mark.asyncio
async def test_run_starts_eventbus(self):
    engine = TradingEngine({})

    # Mock EventBus.start() to not block
    async def mock_start():
        await asyncio.sleep(0.1)

    engine.event_bus.start = AsyncMock(side_effect=mock_start)
    engine.event_bus.shutdown = AsyncMock()

    # Run with short timeout
    run_task = asyncio.create_task(engine.run())
    await asyncio.sleep(0.05)

    # Trigger shutdown
    run_task.cancel()

    try:
        await run_task
    except asyncio.CancelledError:
        pass

    # Verify EventBus.start() was called
    engine.event_bus.start.assert_called_once()
```

## 5. Design Decisions

### 5.1 Dependency Injection Pattern

**Decision**: Use setter methods for component injection
**Rationale**:
- Enables testing with mocks
- Allows partial configuration (analysis-only mode)
- Clear component boundaries
- Supports different strategy implementations

**Alternative Rejected**: Constructor injection (too rigid for testing)

### 5.2 Error Isolation in Handlers

**Decision**: Try-except in all event handlers, don't re-raise
**Rationale**:
- One handler failure shouldn't crash engine
- All errors logged for debugging
- Event processing continues
- Critical for production reliability

**Trade-off**: Silent failures possible, but logged

### 5.3 Graceful Shutdown Sequence

**Decision**: Stop DataCollector → drain queues → shutdown EventBus
**Rationale**:
- Prevents new events during shutdown
- Ensures order queue processed
- 10s timeout prevents hang
- Safe for trading (no lost orders)

### 5.4 Component Optional vs Required

**Decision**: All components except EventBus are optional
**Rationale**:
- Supports different modes (analysis-only, backtest, live)
- Handlers check existence before use
- Clear warnings logged
- Flexible deployment

## 6. Integration Points

### 6.1 Dependencies

**EventBus (Task 4.4)**:
- `event_bus.subscribe()` - Register handlers
- `event_bus.publish()` - Publish events
- `event_bus.start()` - Start processors
- `event_bus.shutdown()` - Graceful cleanup

**DataCollector (Task 3)**:
- `start_streaming()` - Begin candle streaming
- `stop()` - Stop streaming
- Publishes CANDLE_CLOSED events

### 6.2 Future Dependencies

**Strategy (Task #5)**:
- Interface: `async def analyze(candle: Candle) -> Optional[Signal]`
- Returns Signal or None

**OrderManager (Task #7)**:
- Interface: `async def create_order_from_signal(signal: Signal) -> Optional[Order]`
- Handles risk management validation

## 7. Success Criteria

### Functional Requirements
1. ✅ TradingEngine initializes with config and EventBus
2. ✅ `_setup_handlers()` subscribes to 3 event types
3. ✅ `_on_candle_closed()` calls strategy and publishes signals
4. ✅ `_on_signal()` logs signal details
5. ✅ `_on_order_filled()` logs order details
6. ✅ `run()` starts EventBus and DataCollector
7. ✅ `shutdown()` stops all components gracefully
8. ✅ Handler errors logged, don't crash engine

### Test Requirements
1. ✅ All 8 test classes implemented
2. ✅ 100% coverage on TradingEngine methods
3. ✅ Integration test demonstrates pipeline
4. ✅ All tests pass with pytest

### Code Quality
1. ✅ Full docstrings (Google style)
2. ✅ Type hints for all methods
3. ✅ Error handling in all handlers
4. ✅ INFO/DEBUG logging throughout

## 8. Implementation Sequence

**Step 1**: Create file structure (5 min)
- Create `src/core/trading_engine.py`
- Add imports and module docstring

**Step 2**: Implement __init__ and setters (10 min)
- `__init__(config)` with EventBus creation
- `set_data_collector()`, `set_strategy()`, `set_order_manager()`
- `_setup_handlers()` for subscriptions

**Step 3**: Implement event handlers (20 min)
- `_on_candle_closed()` with strategy integration
- `_on_signal()` with logging
- `_on_order_filled()` with logging
- Error handling in all handlers

**Step 4**: Implement lifecycle methods (15 min)
- `run()` with asyncio.gather
- `shutdown()` with component cleanup
- KeyboardInterrupt handling

**Step 5**: Create test file (30 min)
- `tests/core/test_trading_engine.py`
- Implement all 8 test classes
- Mock components and verify behavior

**Step 6**: Integration testing (10 min)
- End-to-end pipeline test
- Verify with real EventBus
- Check logging output

**Total Estimated Time**: 90 minutes

## 9. Next Steps

**After Subtask 4.5 Complete**:

✅ **Task #4 COMPLETE** - Event-Driven Architecture fully implemented!

**Unlocks**:
- **Task #5**: ICT Strategy Implementation (depends on Task #4)
- **Task #6**: Risk Management System (depends on Task #4)
- **Task #7**: Enhanced Order Management (depends on Task #4)

## 10. References

**Design Patterns**:
- Orchestrator Pattern (TradingEngine coordinates all components)
- Dependency Injection (component setters)
- Observer Pattern (EventBus pub-sub)
- Error Isolation Pattern (try-except in handlers)

**Related Files**:
- `src/core/event_handler.py` - EventBus (Task 4.4)
- `src/core/data_collector.py` - BinanceDataCollector (Task 3)
- `src/models/event.py` - Event and EventType definitions
- `src/models/signal.py` - Signal model
- `src/execution/order_manager.py` - OrderManager (placeholder)

**Testing References**:
- pytest-asyncio for async tests
- unittest.mock for component mocking
- asyncio.create_task for concurrent testing
