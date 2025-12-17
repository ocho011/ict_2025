# Review: Data Flow Architecture (Historical vs. Real-time)

**Date:** 2025-12-16
**Context:** Clarification of data flow mechanisms for Data Collector, Event Bus, and Strategy.

## 1. Executive Summary

This document clarifies the architectural distinction between **Historical Data (Initialization)** and **Real-time Data (Streaming)**. The key design principle is that historical data is used for **state initialization** and does not pass through the event bus system to avoid processing overhead and false signals.

| Feature | Historical Data | Real-time Data |
| :--- | :--- | :--- |
| **Purpose** | State Initialization (Pre-load) | Event Processing (Trading) |
| **Source** | REST API | WebSocket Stream |
| **Transport** | Direct Injection (Method Call) | Event Bus (Queue) |
| **Target** | `Strategy.candle_buffer` | `Strategy.analyze()` |
| **Latency** | N/A (Batch) | Critical (Low Latency) |

---

## 2. Detailed Data Flow

### 2.1 Phase 1: System Initialization (Startup)

During the startup phase, the system builds the necessary context for the strategy to function immediately upon receiving the first real-time candle.

**Flow:**
1.  **Fetch**: `DataCollector` requests the last $N$ candles (e.g., 500) via Binance REST API.
2.  **Inject**: The system (via `TradingEngine`) calls `strategy.update_buffer()` directly for each historical candle.
3.  **State Ready**: The strategy's internal buffer is populated, and indicators are pre-calculated (if applicable).
4.  **No Events**: No `CANDLE_CLOSED` events are emitted to the EventBus.

```mermaid
sequenceDiagram
    participant Main as System Entry
    participant Coll as DataCollector
    participant Eng as TradingEngine
    participant Strat as Strategy
    participant Bus as EventBus

    Note over Main, Bus: Phase 1: Initialization
    Main->>Coll: Initialize
    Main->>Coll: get_historical_candles()
    Coll->>Binance API: REST Request (limit=500)
    Binance API-->>Coll: Historical Candles []
    
    loop For each candle
        Coll->>Strat: Direct Buffer Update (Pre-load)
        Note right of Strat: Buffer grows: [c1, c2, ... c500]
    end
    
    Note over Bus: EventBus is IDLE (No traffic)
    Main->>Eng: Ready to Start
```

### 2.2 Phase 2: Real-time Operation (Runtime)

Once initialized, the system switches to event-driven mode.

**Flow:**
1.  **Stream**: `DataCollector` receives a closed candle via WebSocket.
2.  **Publish**: `DataCollector` creates a `CANDLE_CLOSED` event and pushes it to the EventBus `data` queue.
3.  **Dispatch**: `TradingEngine` consumes the event.
4.  **Analyze**: `TradingEngine` calls `strategy.analyze(candle)`.
5.  **Process**:
    *   Strategy adds the new candle to the buffer (FIFO: removing the oldest).
    *   Strategy calculates logic/indicators.
    *   Strategy returns a `Signal` if conditions are met.

```mermaid
sequenceDiagram
    participant Coll as DataCollector
    participant Bus as EventBus
    participant Eng as TradingEngine
    participant Strat as Strategy

    Note over Coll, Strat: Phase 2: Real-time Operation
    Binance WS-->>Coll: Kline Update (Closed)
    Coll->>Bus: Publish CANDLE_CLOSED Event
    Bus->>Eng: Dispatch Event (queue='data')
    
    rect rgb(240, 248, 255)
        Note right of Eng: Critical Path
        Eng->>Strat: analyze(new_candle)
        Strat->>Strat: update_buffer(new_candle)
        Note right of Strat: Buffer: [c2...c500, new]
        Strat->>Strat: Check Logic / Signals
        Strat-->>Eng: Return Signal (or None)
    end
    
    opt Signal Generated
        Eng->>Bus: Publish SIGNAL_GENERATED Event
    end
```

## 3. Implementation Notes

-   **Performance**: Bypassing the EventBus for historical data prevents "thundering herd" issues where the message queue is flooded with 1000s of events at startup.
-   **Safety**: Prevents the strategy from generating "stale" signals based on old market conditions during startup.
-   **Consistency**: The `Strategy` class treats the buffer simply as a state container, agnostic of whether the data came from REST or WebSocket, ensuring logic consistency.
