# Task 10: Main Integration Design Summary

## Overview
Complete architectural design for main.py entry point that orchestrates all 9 completed system components into a fully functional ICT trading bot.

## Key Design Elements

### TradingBot Class
- **Lifecycle**: __init__() → initialize() → run() → shutdown()
- **Components**: ConfigManager, TradingLogger, BinanceDataCollector, EventBus, OrderExecutionManager, RiskManager, StrategyFactory
- **State Management**: _running flag for lifecycle control

### Event-Driven Pipeline
1. WebSocket → Candle → `_on_candle_received()`
2. Event(CANDLE_CLOSED) → EventBus.publish('data')
3. `_on_candle_closed()` → strategy.analyze()
4. Event(SIGNAL_GENERATED) → EventBus.publish('signal')
5. `_on_signal_generated()` → risk validation → position sizing → execute
6. Event(ORDER_FILLED) → `_on_order_filled()`

### Initialization Sequence (10 Steps)
1. ConfigManager - load configs
2. TradingLogger - setup logging
3. Log startup banner
4. BinanceDataCollector - WebSocket client
5. OrderExecutionManager - order interface
6. RiskManager - risk validation
7. StrategyFactory - create strategy
8. EventBus - create instance
9. Wire event handlers
10. Set account leverage

### Signal Handlers
- SIGINT/SIGTERM → graceful shutdown
- Cleanup: stop DataCollector → shutdown EventBus (drain queues)
- Timeout handling: 5s per component

## Critical Integration Points

### Callback Bridge
```python
def _on_candle_received(self, candle: Candle) -> None:
    event = Event(
        EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE,
        candle
    )
    asyncio.create_task(self.event_bus.publish(event, queue_name='data'))
```

### Concurrent Runtime
```python
await asyncio.gather(
    self.event_bus.start(),         # Process event queues
    self.data_collector.start_streaming()  # WebSocket connection
)
```

## Error Handling Strategy
- Initialization errors: fatal, exit code 1
- Runtime errors: log and continue (EventBus isolation)
- Shutdown errors: best-effort cleanup, log warnings

## Configuration Requirements
- `configs/api_keys.ini`: API credentials (testnet/mainnet sections)
- `configs/trading_config.ini`: symbol, strategy, leverage, risk params
- Environment: use TESTNET by default for safety

## Testing Strategy
1. Unit tests: initialization, shutdown, event publishing
2. Integration tests: full pipeline, signal handling, graceful shutdown
3. Manual tests: testnet connection, WebSocket stream, Ctrl+C handling

## Implementation Files
- Primary: `src/main.py` (complete rewrite)
- Dependencies: All Task 3-9 components (already implemented)
- Documentation: 
- Design: `.taskmaster/designs/task-10-main-entry-point-design.md`
- Architecture: `.taskmaster/designs/task-10-architecture-diagram.md`
- Quick Reference: `.taskmaster/designs/TASK-10-QUICK-REFERENCE.md`

## Success Criteria
- Clean startup with valid config
- WebSocket streaming active
- Events flow through pipeline
- Orders execute with TP/SL
- Graceful shutdown in <5s
- Zero resource leaks
- Comprehensive logging

## Design Document Locations
- **Comprehensive Design**: `.taskmaster/designs/task-10-main-entry-point-design.md` (14 sections)
- **Architecture Diagrams**: `.taskmaster/designs/task-10-architecture-diagram.md` (7 visual diagrams)
- **Quick Reference**: `.taskmaster/designs/TASK-10-QUICK-REFERENCE.md` (complete code snippets)
