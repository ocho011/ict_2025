# Task 10: Main Application Entry Point & Integration
## Comprehensive System Design Document

**Date**: 2025-12-21
**Status**: Design Phase
**Dependencies**: Tasks 3, 4, 5, 6, 7, 8, 9 (ALL COMPLETE ✅)

---

## 1. Executive Summary

This document provides the complete architectural design for the main.py entry point that orchestrates all system components into a fully functional ICT-based cryptocurrency trading bot. This is the capstone integration task that brings together 9 previously completed components.

### 1.1 Design Objectives

1. **Clean Integration**: Seamlessly connect all system components with proper initialization sequence
2. **Lifecycle Management**: Handle startup, runtime, and graceful shutdown phases
3. **Event-Driven Flow**: Implement end-to-end trading pipeline from candle → signal → order
4. **Production-Ready**: Include proper error handling, logging, and resource cleanup
5. **Signal Handling**: Support SIGINT/SIGTERM for graceful termination

---

## 2. System Architecture Overview

### 2.1 Component Dependency Graph

```
┌─────────────────────────────────────────────────────────────┐
│                       TradingBot (main.py)                   │
│  Orchestrates all components with event-driven architecture  │
└──────────┬──────────────────────────────────────────────────┘
           │
           │ Initializes & Coordinates
           │
    ┌──────┴──────────────────────────────────────────────┐
    │                                                      │
    ▼                                                      ▼
┌───────────────────┐                            ┌──────────────────┐
│  ConfigManager    │                            │   TradingLogger  │
│  (Task 9)         │                            │   (Task 8)       │
│                   │                            │                  │
│ - API credentials │                            │ - Multi-handler  │
│ - Trading params  │                            │ - Rotation       │
│ - Validation      │                            │ - Trade logs     │
└──────┬────────────┘                            └─────────┬────────┘
       │                                                   │
       │ Provides Config                                  │ Provides Logging
       │                                                   │
       ▼                                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                     Component Layer                           │
├───────────────────┬──────────────────┬──────────────────────┤
│                   │                  │                      │
│ BinanceDataCollector  EventBus      │  OrderExecutionMgr  │
│ (Task 3)          │  (Task 4)       │  (Task 6)           │
│                   │                  │                      │
│ - WebSocket       │ - Pub/Sub       │  - Market orders    │
│ - Candle buffer   │ - 3 Queues      │  - TP/SL placement  │
│ - REST API        │ - Event routing │  - Position mgmt    │
└────────┬──────────┴─────┬────────────┴──────────┬──────────┘
         │                │                       │
         │                │                       │
         ▼                ▼                       ▼
┌──────────────┐  ┌──────────────┐      ┌──────────────┐
│ StrategyFactory│  │ RiskManager  │      │ AuditLogger  │
│ (Task 5)      │  │ (Task 7)     │      │ (Task 6.6)   │
│               │  │              │      │              │
│ - Strategy    │  │ - Position   │      │ - Audit trail│
│   creation    │  │   sizing     │      │ - Compliance │
│ - BaseStrategy│  │ - Validation │      │              │
└───────────────┘  └──────────────┘      └──────────────┘
```

### 2.2 Data Flow Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   EVENT-DRIVEN PIPELINE                       │
└──────────────────────────────────────────────────────────────┘

1️⃣ DATA INGESTION
   WebSocket → Candle → on_candle_callback()
                            │
                            ▼
2️⃣ EVENT PUBLISHING
   Event(CANDLE_CLOSED, candle) → EventBus.publish(queue='data')
                                        │
                                        ▼
3️⃣ STRATEGY ANALYSIS
   _on_candle_closed() → strategy.analyze(candle) → Signal?
                                                      │
                                                      ▼
4️⃣ SIGNAL VALIDATION
   Event(SIGNAL_GENERATED, signal) → EventBus.publish(queue='signal')
                                           │
                                           ▼
5️⃣ RISK VALIDATION
   _on_signal_generated() → RiskManager.validate_signal()
                                   │
                                   ▼ (if valid)
6️⃣ POSITION SIZING
   RiskManager.calculate_position_size() → quantity
                                              │
                                              ▼
7️⃣ ORDER EXECUTION
   OrderManager.execute_signal(signal, quantity) → (entry, [tp, sl])
                                                      │
                                                      ▼
8️⃣ ORDER CONFIRMATION
   Event(ORDER_FILLED, order) → _on_order_filled()
```

---

## 3. Component Interface Analysis

### 3.1 BinanceDataCollector (Task 3)

**Interface**:
```python
class BinanceDataCollector:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        symbols: List[str],
        intervals: List[str],
        is_testnet: bool = True,
        on_candle_callback: Optional[Callable[[Candle], None]] = None,
        buffer_size: int = 500
    ) -> None

    async def start_streaming(self) -> None
    async def stop(self, timeout: float = 5.0) -> None
    def get_candle_buffer(self, symbol: str, interval: str) -> List[Candle]
```

**Integration Requirements**:
- Provide `on_candle_callback` that bridges to EventBus
- Call `start_streaming()` in async startup
- Call `stop()` during graceful shutdown
- Callback signature: `def _on_candle_received(self, candle: Candle) -> None`

### 3.2 EventBus (Task 4)

**Interface**:
```python
class EventBus:
    def subscribe(self, event_type: EventType, handler: Callable) -> None
    async def publish(self, event: Event, queue_name: str = 'data') -> None
    async def start(self) -> None  # Runs until stop()
    def stop(self) -> None
    async def shutdown(self, timeout: float = 5.0) -> None
```

**Integration Requirements**:
- Subscribe handlers BEFORE calling start()
- Use proper queue routing: `data` → `signal` → `order`
- Call `start()` concurrently with data collector
- Use `shutdown()` for graceful cleanup with queue draining

### 3.3 OrderExecutionManager (Task 6)

**Interface**:
```python
class OrderExecutionManager:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        is_testnet: bool = True
    ) -> None

    def set_leverage(self, symbol: str, leverage: int) -> bool
    def set_margin_type(self, symbol: str, margin_type: str = 'ISOLATED') -> bool
    def execute_signal(
        self, signal: Signal, quantity: float, reduce_only: bool = False
    ) -> tuple[Order, list[Order]]
    def get_position(self, symbol: str) -> Optional[Position]
    def get_account_balance(self) -> float
```

**Integration Requirements**:
- Initialize with API credentials from ConfigManager
- Set leverage during initialization
- Call `execute_signal()` after risk validation
- Query position before signal validation

### 3.4 RiskManager (Task 7)

**Interface**:
```python
class RiskManager:
    def __init__(self, config: dict) -> None

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        leverage: int,
        symbol_info: Optional[dict] = None
    ) -> float

    def validate_signal(
        self, signal: Signal, position: Optional[Position]
    ) -> bool
```

**Integration Requirements**:
- Initialize with risk config dict
- Call `validate_signal()` before execution
- Call `calculate_position_size()` for quantity calculation

### 3.5 StrategyFactory (Task 5)

**Interface**:
```python
class StrategyFactory:
    @classmethod
    def create(cls, name: str, symbol: str, config: dict) -> BaseStrategy

    @classmethod
    def list_strategies(cls) -> List[str]
```

**Strategy Interface**:
```python
class BaseStrategy(ABC):
    async def analyze(self, candle: Candle) -> Optional[Signal]
    def calculate_take_profit(self, entry_price: float, side: str) -> float
    def calculate_stop_loss(self, entry_price: float, side: str) -> float
```

**Integration Requirements**:
- Create strategy instance during initialization
- Call `strategy.analyze()` in candle closed handler
- Strategy returns Signal or None

### 3.6 ConfigManager (Task 9)

**Interface**:
```python
class ConfigManager:
    def __init__(self, config_dir: str = "configs") -> None
    def validate(self) -> bool

    @property
    def api_config(self) -> APIConfig  # api_key, api_secret, is_testnet

    @property
    def trading_config(self) -> TradingConfig  # symbol, intervals, strategy, leverage, etc.

    @property
    def logging_config(self) -> LoggingConfig  # log_level, log_dir
```

**Integration Requirements**:
- Load configs at startup
- Call `validate()` before component initialization
- Use `api_config` for API components
- Use `trading_config` for strategy and risk params

### 3.7 TradingLogger (Task 8)

**Interface**:
```python
class TradingLogger:
    def __init__(self, config: dict) -> None

    @staticmethod
    def log_trade(action: str, data: dict) -> None
```

**Integration Requirements**:
- Initialize early in startup sequence
- Use `TradingLogger.log_trade()` for structured trade events
- Use standard `logging.getLogger(__name__)` for component logging

---

## 4. TradingBot Class Design

### 4.1 Class Structure

```python
class TradingBot:
    """
    Main orchestrator for the ICT trading system.

    Lifecycle:
        1. __init__() - Store references, no initialization
        2. initialize() - Load configs, create components, wire events
        3. run() - Start EventBus and DataCollector concurrently
        4. shutdown() - Graceful cleanup with timeout

    Attributes:
        config_manager: Configuration provider
        event_bus: Event coordination system
        data_collector: WebSocket data source
        order_manager: Order execution interface
        risk_manager: Risk validation & sizing
        strategy: Trading strategy implementation
        logger: Logging interface
        _running: Lifecycle state flag
    """

    def __init__(self) -> None:
        """Lightweight constructor - no initialization logic"""

    def initialize(self) -> None:
        """Heavy initialization - load configs, create components"""

    async def run(self) -> None:
        """Main event loop - runs until shutdown requested"""

    async def shutdown(self) -> None:
        """Graceful cleanup - stop components, close connections"""

    # Event Handlers
    def _setup_event_handlers(self) -> None
    def _on_candle_received(self, candle: Candle) -> None
    async def _on_candle_closed(self, event: Event) -> None
    async def _on_signal_generated(self, event: Event) -> None
    async def _on_order_filled(self, event: Event) -> None
```

### 4.2 Initialization Sequence

```python
def initialize(self) -> None:
    """
    Initialize all system components in correct dependency order.

    Sequence:
        1. ConfigManager - Load and validate configurations
        2. TradingLogger - Setup logging infrastructure
        3. Log startup banner with environment info
        4. BinanceDataCollector - WebSocket and REST client
        5. OrderExecutionManager - Order execution interface
        6. RiskManager - Risk validation and sizing
        7. StrategyFactory - Create strategy instance
        8. EventBus (no init needed, created inline)
        9. Setup event subscriptions
        10. Set account leverage

    Raises:
        ValueError: Invalid configuration
        ConfigurationError: Missing required config
    """

    # Step 1: Load configurations
    self.config_manager = ConfigManager()
    api_config = self.config_manager.api_config
    trading_config = self.config_manager.trading_config

    if not self.config_manager.validate():
        raise ValueError("Invalid configuration")

    # Step 2: Setup logging
    TradingLogger(self.config_manager.logging_config.__dict__)
    self.logger = logging.getLogger(__name__)

    # Step 3: Startup banner
    self.logger.info("=" * 50)
    self.logger.info("ICT Trading Bot Starting...")
    self.logger.info(f"Environment: {'TESTNET' if api_config.is_testnet else 'MAINNET'}")
    self.logger.info(f"Symbol: {trading_config.symbol}")
    self.logger.info(f"Strategy: {trading_config.strategy}")
    self.logger.info(f"Leverage: {trading_config.leverage}x")
    self.logger.info("=" * 50)

    # Step 4: Data Collector
    self.data_collector = BinanceDataCollector(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        symbols=[trading_config.symbol],
        intervals=trading_config.intervals,
        is_testnet=api_config.is_testnet,
        on_candle_callback=self._on_candle_received
    )

    # Step 5: Order Manager
    self.order_manager = OrderExecutionManager(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        is_testnet=api_config.is_testnet
    )

    # Step 6: Risk Manager
    self.risk_manager = RiskManager({
        'max_risk_per_trade': trading_config.max_risk_per_trade,
        'default_leverage': trading_config.leverage
    })

    # Step 7: Strategy
    self.strategy = StrategyFactory.create(
        name=trading_config.strategy,
        symbol=trading_config.symbol,
        config={
            'buffer_size': 100,
            'risk_reward_ratio': trading_config.take_profit_ratio,
            'stop_loss_percent': trading_config.stop_loss_percent
        }
    )

    # Step 8: Event Bus (initialized inline in __init__)
    self.event_bus = EventBus()

    # Step 9: Wire event handlers
    self._setup_event_handlers()

    # Step 10: Set leverage
    success = self.order_manager.set_leverage(
        trading_config.symbol,
        trading_config.leverage
    )
    if not success:
        self.logger.warning("Failed to set leverage (may already be set)")
```

### 4.3 Event Handler Wiring

```python
def _setup_event_handlers(self) -> None:
    """
    Subscribe event handlers to EventBus.

    Event Flow:
        CANDLE_CLOSED → _on_candle_closed → strategy.analyze()
        SIGNAL_GENERATED → _on_signal_generated → risk validation → execute
        ORDER_FILLED → _on_order_filled → log confirmation
    """
    self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
    self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal_generated)
    self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)

    self.logger.debug("Event handlers registered")
```

### 4.4 Candle Callback Bridge

```python
def _on_candle_received(self, candle: Candle) -> None:
    """
    Bridge WebSocket candles to EventBus.

    Called by BinanceDataCollector for every candle update.
    Publishes to 'data' queue with appropriate event type.

    Args:
        candle: Candle from WebSocket (may be closed or updating)
    """
    # Determine event type based on candle state
    event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE

    # Create event and publish (non-blocking)
    event = Event(event_type, candle)
    asyncio.create_task(self.event_bus.publish(event, queue_name='data'))
```

### 4.5 Trading Pipeline Handlers

```python
async def _on_candle_closed(self, event: Event) -> None:
    """
    Handle closed candle - run strategy analysis.

    Flow:
        1. Extract candle from event
        2. Log candle info (DEBUG level)
        3. Call strategy.analyze(candle)
        4. If signal generated, publish SIGNAL_GENERATED event to 'signal' queue

    Args:
        event: Event with EventType.CANDLE_CLOSED
    """
    candle: Candle = event.data
    self.logger.debug(
        f"Candle closed: {candle.symbol} {candle.interval} @ "
        f"{candle.close_time.isoformat()} (close={candle.close})"
    )

    # Run strategy analysis
    signal = await self.strategy.analyze(candle)

    if signal:
        # Publish signal event to signal queue
        await self.event_bus.publish(
            Event(EventType.SIGNAL_GENERATED, signal),
            queue_name='signal'
        )


async def _on_signal_generated(self, event: Event) -> None:
    """
    Handle generated signal - validate and execute.

    Flow:
        1. Extract signal from event
        2. Log signal details (INFO level)
        3. Get current position
        4. Validate signal with RiskManager
        5. If invalid, return early (logged by RiskManager)
        6. Get account balance
        7. Calculate position size
        8. Execute signal via OrderManager
        9. Log execution result
        10. On error, log but don't crash

    Args:
        event: Event with EventType.SIGNAL_GENERATED
    """
    signal: Signal = event.data

    self.logger.info(
        f"Signal: {signal.signal_type.value} at {signal.entry_price} "
        f"(TP: {signal.take_profit}, SL: {signal.stop_loss})"
    )

    # Get current position
    current_position = self.order_manager.get_position(signal.symbol)

    # Validate with risk manager
    if not self.risk_manager.validate_signal(signal, current_position):
        # Validation failure already logged by RiskManager
        return

    # Calculate position size
    balance = self.order_manager.get_account_balance()
    quantity = self.risk_manager.calculate_position_size(
        account_balance=balance,
        entry_price=signal.entry_price,
        stop_loss_price=signal.stop_loss,
        leverage=self.config_manager.trading_config.leverage
    )

    # Execute signal
    try:
        entry_order, tpsl_orders = self.order_manager.execute_signal(signal, quantity)

        # Log success
        TradingLogger.log_trade('ORDER_EXECUTED', {
            'signal': signal.signal_type.value,
            'symbol': signal.symbol,
            'entry_order_id': entry_order.order_id,
            'quantity': quantity,
            'entry_price': entry_order.price,
            'tpsl_count': len(tpsl_orders)
        })

        self.logger.info(
            f"Order executed: ID={entry_order.order_id}, "
            f"quantity={quantity}, TP/SL={len(tpsl_orders)}/2"
        )

    except Exception as e:
        self.logger.error(f"Order execution failed: {e}", exc_info=True)


async def _on_order_filled(self, event: Event) -> None:
    """
    Handle order fill notification.

    Flow:
        1. Extract order from event
        2. Log fill confirmation
        3. (Optional) Update internal tracking

    Args:
        event: Event with EventType.ORDER_FILLED
    """
    order: Order = event.data
    self.logger.info(
        f"Order filled: {order.order_id} "
        f"({order.symbol} {order.side.value} {order.quantity})"
    )
```

### 4.6 Runtime Loop

```python
async def run(self) -> None:
    """
    Main runtime loop - runs until shutdown requested.

    Flow:
        1. Set _running flag
        2. Start EventBus and DataCollector concurrently
        3. Handle CancelledError on shutdown
        4. Ensure shutdown() called in finally

    Concurrent Operations:
        - event_bus.start() - Processes event queues
        - data_collector.start_streaming() - WebSocket connection

    Raises:
        asyncio.CancelledError: On graceful shutdown (caught internally)
    """
    self._running = True

    try:
        # Run both concurrently until shutdown
        await asyncio.gather(
            self.event_bus.start(),
            self.data_collector.start_streaming()
        )
    except asyncio.CancelledError:
        self.logger.info("Shutdown requested...")
    finally:
        await self.shutdown()
```

### 4.7 Graceful Shutdown

```python
async def shutdown(self) -> None:
    """
    Graceful shutdown with resource cleanup.

    Sequence:
        1. Check if already stopped (idempotency)
        2. Set _running flag to False
        3. Stop data collector (closes WebSocket)
        4. Shutdown EventBus (drains queues)
        5. Log completion

    Timeout Handling:
        - DataCollector: 5s timeout (configurable)
        - EventBus: 5s per queue (15s total max)

    Idempotent: Safe to call multiple times
    """
    if not self._running:
        self.logger.debug("Already stopped")
        return

    self._running = False
    self.logger.info("Shutting down...")

    # Stop data collector (WebSocket)
    try:
        await self.data_collector.stop(timeout=5.0)
    except Exception as e:
        self.logger.error(f"Error stopping data collector: {e}")

    # Shutdown EventBus (drain queues)
    try:
        await self.event_bus.shutdown(timeout=5.0)
    except Exception as e:
        self.logger.error(f"Error shutting down EventBus: {e}")

    self.logger.info("Shutdown complete")
```

---

## 5. Main Entry Point

```python
def main() -> None:
    """
    Application entry point with signal handling.

    Flow:
        1. Create event loop
        2. Create TradingBot instance
        3. Register signal handlers (SIGINT, SIGTERM)
        4. Initialize bot
        5. Run bot (blocks until shutdown)
        6. Handle keyboard interrupt gracefully
        7. Close event loop

    Exit Codes:
        0: Clean shutdown
        1: Fatal error during initialization or runtime
    """
    bot = TradingBot()

    # Create and configure event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(bot.shutdown())
        )

    try:
        # Initialize system
        bot.initialize()

        # Run until shutdown
        loop.run_until_complete(bot.run())

    except KeyboardInterrupt:
        # Graceful exit on Ctrl+C (no traceback)
        pass

    except Exception as e:
        # Fatal error - log and exit with error code
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        # Clean up event loop
        loop.close()


if __name__ == '__main__':
    main()
```

---

## 6. Error Handling Strategy

### 6.1 Initialization Errors

| Error Type | Handler | Behavior |
|------------|---------|----------|
| ConfigurationError | main() | Log error, exit code 1 |
| ValueError (invalid config) | main() | Log error, exit code 1 |
| ConnectionError (API) | main() | Log error, exit code 1 |
| Missing credentials | ConfigManager | Raise ConfigurationError with helpful message |

### 6.2 Runtime Errors

| Error Type | Handler | Behavior |
|------------|---------|----------|
| Strategy exception | _on_candle_closed | Log error, continue (EventBus isolation) |
| Order execution error | _on_signal_generated | Log error, skip trade, continue |
| WebSocket disconnect | BinanceDataCollector | Auto-reconnect (built-in) |
| Event handler exception | EventBus | Log error, continue to next handler |

### 6.3 Shutdown Errors

| Error Type | Handler | Behavior |
|------------|---------|----------|
| DataCollector timeout | shutdown() | Log warning, force stop |
| EventBus timeout | shutdown() | Log warning, continue cleanup |
| Resource cleanup | shutdown() | Log error, continue (best effort) |

---

## 7. Testing Strategy

### 7.1 Unit Tests

```python
# test_trading_bot.py

class TestTradingBot:
    def test_initialization_with_valid_config(self):
        """Test bot initializes successfully with valid configs"""

    def test_initialization_fails_with_missing_config(self):
        """Test initialization raises ConfigurationError"""

    def test_shutdown_is_idempotent(self):
        """Test shutdown can be called multiple times safely"""

    def test_candle_callback_publishes_event(self):
        """Test _on_candle_received publishes to EventBus"""
```

### 7.2 Integration Tests

```python
# test_integration.py

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_candle_to_signal_flow(self):
        """Test candle → strategy → signal → risk → order flow"""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_on_sigint(self):
        """Test SIGINT triggers graceful shutdown"""

    @pytest.mark.asyncio
    async def test_event_bus_drains_queues_on_shutdown(self):
        """Test pending events are processed during shutdown"""
```

### 7.3 Manual Testing Checklist

- [ ] Start bot with testnet credentials
- [ ] Verify startup banner shows correct environment
- [ ] Confirm WebSocket connection established
- [ ] Observe candle updates in logs
- [ ] Trigger Ctrl+C and verify graceful shutdown
- [ ] Check all log files created (trading.log, trades.log)
- [ ] Verify no resource leaks (check connections closed)
- [ ] Test with invalid config (should exit cleanly)

---

## 8. Implementation Plan

### Subtask 10.1: TradingBot Class & Initialization ✅
**Files**: `src/main.py`
- Create TradingBot class structure
- Implement `__init__()` method (lightweight)
- Implement `initialize()` method (7-step sequence)
- Import all required components
- Add comprehensive logging at each step

### Subtask 10.2: Event Handler Wiring ✅
**Files**: `src/main.py`
- Implement `_setup_event_handlers()`
- Implement `_on_candle_received()` callback
- Subscribe all handlers to EventBus
- Test event subscription

### Subtask 10.3: Signal Processing Pipeline ✅
**Files**: `src/main.py`
- Implement `_on_candle_closed()` async handler
- Implement `_on_signal_generated()` async handler
- Implement `_on_order_filled()` async handler
- Add error handling for each handler
- Add structured trade logging

### Subtask 10.4: Graceful Shutdown ✅
**Files**: `src/main.py`
- Implement `shutdown()` async method
- Add SIGINT/SIGTERM signal handlers
- Ensure idempotent cleanup
- Add timeout handling for components

### Subtask 10.5: Main Entry Point ✅
**Files**: `src/main.py`
- Implement `run()` method with asyncio.gather
- Implement `main()` function with event loop
- Add signal handler registration
- Add KeyboardInterrupt handling
- Add top-level exception handling

---

## 9. Configuration Requirements

### 9.1 API Keys Config (`configs/api_keys.ini`)

```ini
[binance]
use_testnet = true

[binance.testnet]
api_key = your_testnet_api_key
api_secret = your_testnet_api_secret

[binance.mainnet]
api_key = your_mainnet_api_key
api_secret = your_mainnet_api_secret
```

### 9.2 Trading Config (`configs/trading_config.ini`)

```ini
[trading]
symbol = BTCUSDT
intervals = 1m,5m,15m
strategy = mock_sma
leverage = 10
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02

[logging]
log_level = INFO
log_dir = logs
```

---

## 10. Performance Considerations

### 10.1 Resource Usage

| Component | CPU | Memory | Network |
|-----------|-----|--------|---------|
| WebSocket | Low | ~10MB | Continuous |
| EventBus | Low | ~5MB | Internal |
| Strategy | Medium | Varies | None |
| OrderManager | Low | ~5MB | Sporadic |

### 10.2 Optimization Opportunities

1. **Candle Buffer**: Use `collections.deque` for O(1) append/pop
2. **Strategy Analysis**: Vectorize calculations with numpy
3. **Event Processing**: Keep handlers fast (<10ms typical)
4. **Logging**: Use async logging handlers for I/O operations

---

## 11. Security Considerations

### 11.1 API Key Protection

- ✅ Never log API keys (enforced by ConfigManager)
- ✅ Load from environment variables or INI files (not in code)
- ✅ Validate credentials before component initialization
- ✅ Use testnet by default for safety

### 11.2 Error Message Sanitization

- ✅ Don't include sensitive data in error messages
- ✅ Log to files, not console for production
- ✅ Rotate logs to prevent disk filling

---

## 12. Deployment Checklist

- [ ] API credentials configured (testnet first!)
- [ ] Trading config validated
- [ ] Log directory created and writable
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Testnet connection verified
- [ ] Strategy configured correctly
- [ ] Risk parameters set conservatively
- [ ] Monitoring/alerting set up
- [ ] Backup/recovery plan documented

---

## 13. Success Criteria

### Functional Requirements ✅
- [ ] Bot starts without errors with valid config
- [ ] WebSocket connection established successfully
- [ ] Candles flow through EventBus to strategy
- [ ] Signals trigger order execution
- [ ] TP/SL orders placed automatically
- [ ] Graceful shutdown on SIGINT
- [ ] All logs created and rotated

### Non-Functional Requirements ✅
- [ ] Startup time < 10 seconds
- [ ] Event processing latency < 100ms
- [ ] Zero memory leaks (verified with valgrind)
- [ ] Clean shutdown in < 5 seconds
- [ ] Comprehensive logging coverage
- [ ] Error recovery without restart

---

## 14. Related Documentation

- [Task 3: Data Collection](./task-3-data-collection.md)
- [Task 4: Event-Driven Architecture](./task-4-event-architecture.md)
- [Task 5: Strategy Framework](./task-5-strategy-framework.md)
- [Task 6: Order Execution](./task-6-order-execution.md)
- [Task 7: Risk Management](./task-7-risk-management.md)
- [Task 8: Logging System](./task-8-logging-system.md)
- [Task 9: Configuration Management](./task-9-config-management.md)

---

**End of Design Document**

This design provides a complete blueprint for implementing the main.py entry point that integrates all system components into a production-ready trading bot. The architecture emphasizes clean separation of concerns, robust error handling, and graceful lifecycle management.
