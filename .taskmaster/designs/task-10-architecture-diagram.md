# Task 10: System Architecture Diagrams

## 1. Component Integration Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TradingBot (main.py)                         │
│                   Main Orchestrator & Lifecycle Manager              │
├──────────────────┬──────────────────────┬───────────────────────────┤
│  Initialization  │   Event Handlers     │   Shutdown Management    │
│  • Load configs  │   • _on_candle_*     │   • Stop DataCollector   │
│  • Create comps  │   • _on_signal_*     │   • Drain EventBus       │
│  • Wire events   │   • _on_order_*      │   • Resource cleanup     │
└──────────────────┴──────────────────────┴───────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ ConfigManager│    │ TradingLogger│    │   EventBus   │
│  (Task 9)    │    │  (Task 8)    │    │  (Task 4)    │
│              │    │              │    │              │
│ ┌──────────┐ │    │ ┌──────────┐ │    │ ┌──────────┐ │
│ │API Config│ │    │ │Console   │ │    │ │data queue│ │
│ │Trading   │ │    │ │File logs │ │    │ │signal q  │ │
│ │Logging   │ │    │ │Trade logs│ │    │ │order q   │ │
│ └──────────┘ │    │ └──────────┘ │    │ └──────────┘ │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       │ Provides Config   │ Logging Services  │ Event Routing
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    Component Layer                           │
├───────────────────┬──────────────────┬──────────────────────┤
│                   │                  │                      │
│ BinanceData       │  StrategyFactory │  OrderExecution      │
│ Collector         │  & Strategy      │  Manager             │
│ (Task 3)          │  (Task 5)        │  (Task 6)            │
│                   │                  │                      │
│ ┌──────────────┐  │ ┌──────────────┐ │ ┌──────────────┐    │
│ │WebSocket     │  │ │BaseStrategy  │ │ │Market Orders │    │
│ │REST API      │  │ │MockSMA       │ │ │TP/SL Placement│   │
│ │Candle Buffer │  │ │analyze()     │ │ │Position Query│    │
│ │on_callback   │  │ │calc TP/SL    │ │ │Leverage Set  │    │
│ └──────────────┘  │ └──────────────┘ │ └──────────────┘    │
└───────────────────┴──────────────────┴──────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
    ┌──────────────┐                ┌──────────────┐
    │ RiskManager  │                │ AuditLogger  │
    │  (Task 7)    │                │  (Task 6.6)  │
    │              │                │              │
    │ ┌──────────┐ │                │ ┌──────────┐ │
    │ │Position  │ │                │ │JSON audit│ │
    │ │  Sizing  │ │                │ │Compliance│ │
    │ │Validation│ │                │ │           │ │
    │ └──────────┘ │                │ └──────────┘ │
    └──────────────┘                └──────────────┘
```

## 2. Event Flow Sequence Diagram

```
┌──────────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐
│  WebSocket   │   │  main.py │   │EventBus │   │Strategy │   │RiskMgr  │   │OrderMgr │
└──────┬───────┘   └────┬─────┘   └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘
       │                │               │             │             │             │
       │  Candle Data   │               │             │             │             │
       │───────────────>│               │             │             │             │
       │                │               │             │             │             │
       │         _on_candle_received()  │             │             │             │
       │                │               │             │             │             │
       │                │ publish(      │             │             │             │
       │                │  CANDLE_CLOSED│             │             │             │
       │                │  queue='data')│             │             │             │
       │                │──────────────>│             │             │             │
       │                │               │             │             │             │
       │                │               │ dispatch to │             │             │
       │                │               │ _on_candle_ │             │             │
       │                │               │  closed()   │             │             │
       │                │<──────────────│             │             │             │
       │                │               │             │             │             │
       │                │ strategy.analyze(candle)    │             │             │
       │                │──────────────────────────>│             │             │
       │                │               │             │             │             │
       │                │               │  Signal?    │             │             │
       │                │<──────────────────────────│             │             │
       │                │               │             │             │             │
       │                │ publish(      │             │             │             │
       │                │  SIGNAL_GEN   │             │             │             │
       │                │  queue='signal')            │             │             │
       │                │──────────────>│             │             │             │
       │                │               │             │             │             │
       │                │               │ dispatch to │             │             │
       │                │               │ _on_signal_ │             │             │
       │                │               │ generated() │             │             │
       │                │<──────────────│             │             │             │
       │                │               │             │             │             │
       │                │ get_position()│             │             │             │
       │                │───────────────────────────────────────────────────────>│
       │                │               │             │             │  Position?  │
       │                │<───────────────────────────────────────────────────────│
       │                │               │             │             │             │
       │                │ validate_signal(signal, position)         │             │
       │                │───────────────────────────────────────>│             │
       │                │               │             │  valid?     │             │
       │                │<───────────────────────────────────────│             │
       │                │               │             │             │             │
       │                │ calculate_position_size()   │             │             │
       │                │───────────────────────────────────────>│             │
       │                │               │             │  quantity   │             │
       │                │<───────────────────────────────────────│             │
       │                │               │             │             │             │
       │                │ execute_signal(signal, quantity)        │             │
       │                │───────────────────────────────────────────────────────>│
       │                │               │             │             │  Entry Order│
       │                │               │             │             │  TP Order   │
       │                │               │             │             │  SL Order   │
       │                │<───────────────────────────────────────────────────────│
       │                │               │             │             │             │
       │                │ publish(      │             │             │             │
       │                │  ORDER_FILLED │             │             │             │
       │                │  queue='order')             │             │             │
       │                │──────────────>│             │             │             │
       │                │               │             │             │             │
```

## 3. Initialization Sequence

```
┌─────────┐
│  main() │
└────┬────┘
     │
     │  1. Create event loop
     │  2. Create TradingBot instance
     │  3. Register signal handlers (SIGINT, SIGTERM)
     │
     ▼
┌──────────────────────┐
│ TradingBot.          │
│ initialize()         │
└──────┬───────────────┘
       │
       ├─ Step 1: ConfigManager() ──────────────────────┐
       │          Load API, Trading, Logging configs      │
       │                                                  │
       ├─ Step 2: TradingLogger() ──────────────────────┤
       │          Setup console, file, trade handlers    │
       │                                                  │
       ├─ Step 3: Log Startup Banner ───────────────────┤
       │          Environment, Symbol, Strategy info     │
       │                                                  │
       ├─ Step 4: BinanceDataCollector() ───────────────┤
       │          WebSocket client with on_candle_callback
       │                                                  │
       ├─ Step 5: OrderExecutionManager() ──────────────┤
       │          REST client for order execution        │
       │                                                  │
       ├─ Step 6: RiskManager() ────────────────────────┤
       │          Position sizing & validation logic     │
       │                                                  │
       ├─ Step 7: StrategyFactory.create() ─────────────┤
       │          Instantiate strategy (MockSMA/ICT)     │
       │                                                  │
       ├─ Step 8: EventBus() ───────────────────────────┤
       │          Create pub-sub coordinator             │
       │                                                  │
       ├─ Step 9: _setup_event_handlers() ──────────────┤
       │          Subscribe to CANDLE_CLOSED, SIGNAL_*   │
       │                                                  │
       └─ Step 10: set_leverage() ──────────────────────┘
                 Configure account leverage


     ▼
┌──────────────────────┐
│ TradingBot.run()     │
└──────┬───────────────┘
       │
       ├─ asyncio.gather(
       │    event_bus.start(),
       │    data_collector.start_streaming()
       │  )
       │
       └─ [Runs until shutdown requested]
```

## 4. Shutdown Sequence

```
┌──────────────────┐
│  SIGINT/SIGTERM  │
│  (Ctrl+C)        │
└────────┬─────────┘
         │
         ▼
┌──────────────────────┐
│ Signal Handler       │
│ asyncio.create_task( │
│   bot.shutdown()     │
│ )                    │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│ TradingBot.shutdown()                     │
└────┬─────────────────────────────────────┘
     │
     ├─ 1. Set _running = False
     │
     ├─ 2. data_collector.stop(timeout=5.0)
     │      • Close WebSocket connection
     │      • Stop REST client
     │      • Log buffer states
     │
     ├─ 3. event_bus.shutdown(timeout=5.0)
     │      • Drain data queue (timeout: 5s)
     │      • Drain signal queue (timeout: 5s)
     │      • Drain order queue (timeout: 5s)
     │      • Stop processors
     │      • Cancel tasks
     │
     └─ 4. Log "Shutdown complete"


     ▼
┌──────────────────┐
│ Event Loop Close │
│ Exit Code: 0     │
└──────────────────┘
```

## 5. Error Handling Hierarchy

```
┌──────────────────────────────────────────────────────┐
│               Error Classification                    │
└──────┬───────────────────────────────────────────────┘
       │
       ├─── FATAL ERRORS (Exit Code 1) ─────────────┐
       │    • ConfigurationError                     │
       │    • Missing API credentials                │
       │    • Invalid trading config                 │
       │    → Log error, exit immediately            │
       │                                             │
       ├─── RECOVERABLE ERRORS (Continue) ──────────┤
       │    • Strategy analysis exception            │
       │    • Order execution failure                │
       │    • WebSocket temporary disconnect         │
       │    → Log error, skip current operation      │
       │                                             │
       ├─── WARNINGS (Continue) ────────────────────┤
       │    • Risk validation failed                 │
       │    • Position already exists                │
       │    • TP/SL partial placement                │
       │    → Log warning, continue monitoring       │
       │                                             │
       └─── SHUTDOWN ERRORS (Best Effort) ──────────┘
            • Component timeout during cleanup
            • Resource cleanup failure
            → Log error, continue shutdown sequence
```

## 6. Thread & Concurrency Model

```
┌─────────────────────────────────────────────────┐
│           Main Event Loop (asyncio)              │
└────┬─────────────────────────────────────────┬──┘
     │                                         │
     ├─ EventBus Processors (3 tasks) ────────┤
     │  • data_processor (async)               │
     │  • signal_processor (async)             │
     │  • order_processor (async)              │
     │                                         │
     ├─ WebSocket Client (1 thread) ──────────┤
     │  • binance-futures-connector library    │
     │  • Callbacks dispatched to event loop   │
     │                                         │
     └─ Signal Handlers (event loop) ─────────┘
        • SIGINT handler
        • SIGTERM handler


Thread Safety Notes:
• All async operations run on single event loop
• WebSocket library uses internal threading
• Event queue operations are thread-safe (asyncio.Queue)
• ConfigManager is read-only after initialization
• No shared mutable state between components
```

## 7. Data Flow Map

```
Input Sources            Processing Layers           Output Destinations
─────────────            ─────────────────           ───────────────────

┌──────────┐
│ WebSocket│─┐
│ Stream   │ │
└──────────┘ │           ┌─────────────┐            ┌──────────┐
             ├─────────> │  EventBus   │──────────> │Console   │
┌──────────┐ │           │  (3 queues) │            │Logs      │
│ REST API │─┤           └─────┬───────┘            └──────────┘
│ Queries  │ │                 │
└──────────┘ │                 │                    ┌──────────┐
             │                 ├──────────────────> │File Logs │
┌──────────┐ │                 │                    │(rotating)│
│ Strategy │─┘                 │                    └──────────┘
│ Signals  │                   │
└──────────┘                   │                    ┌──────────┐
                               └──────────────────> │Trade Logs│
                                                    │(JSON)    │
                                                    └──────────┘

                                                    ┌──────────┐
                                                    │Binance   │
                                                    │Orders    │
                                                    │(WebAPI)  │
                                                    └──────────┘
```

---

**Architecture Notes**:

1. **Single Event Loop**: All async operations run on one asyncio event loop
2. **Queue-Based Decoupling**: Components communicate through EventBus queues
3. **Graceful Degradation**: Component failures don't crash the entire system
4. **Resource Cleanup**: Proper shutdown sequence prevents resource leaks
5. **Configuration Driven**: All behavior controlled via INI files
6. **Production Ready**: Comprehensive logging, error handling, signal management
