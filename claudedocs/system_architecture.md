# System Architecture: Symbol-Component Relationships & Data Flow

This document details the architectural design of the trading bot, focusing on how different components handle multi-symbol operations and how data flows through the system.

## 1. Core Architecture Pattern: "Distributed State, Centralized Processing"

The system follows a hybrid architecture where state-heavy components are distributed per symbol (isolated), while processing-heavy and resource-management components are centralized (shared).

### Architecture Diagram

```mermaid
graph TD
    subgraph Distributed [Per-Symbol Components (Isolated)]
        WS_BTC[WebSocket: BTCUSDT]
        WS_ETH[WebSocket: ETHUSDT]
        
        STRAT_BTC[Strategy: BTCUSDT]
        STRAT_ETH[Strategy: ETHUSDT]
        
        BUF_BTC[(Buffer: BTC)]
        BUF_ETH[(Buffer: ETH)]
    end

    subgraph Centralized [Shared Components (Single Instance)]
        DC[DataCollector Body]
        REST[REST Client]
        EB{EventBus}
        TE[TradingEngine]
        OM[OrderExecutionManager]
        RM[RiskManager]
    end

    %% Data Flow
    WS_BTCDesc[Stream] --> WS_BTC
    WS_ETHDesc[Stream] --> WS_ETH
    
    WS_BTC -- "Event(BTC)" --> EB
    WS_ETH -- "Event(ETH)" --> EB
    
    EB -- "Route" --> TE
    TE -- "Dispatch" --> STRAT_BTC
    TE -- "Dispatch" --> STRAT_ETH
    
    STRAT_BTC -- "Read/Write" --> BUF_BTC
    STRAT_ETH -- "Read/Write" --> BUF_ETH
    
    STRAT_BTC -- "Signal(BTC)" --> EB
    STRAT_ETH -- "Signal(ETH)" --> EB
    
    EB -- "Route" --> OM
    OM -- "Validate" --> RM
    RM -- "Check" --> REST
    OM -- "Execute" --> REST
```

---

## 2. Component Analysis

### A. Distributed Components (Symbol-Specific)
These components have separate instances for each subscribed symbol. This isolation failsafes the system: an issue with one symbol's data or logic does not directly corrupt others.

1.  **WebSocket Connections (inside DataCollector)**
    *   **Cardinality:** 1 Connection per Symbol.
    *   **Structure:** `self.ws_clients: Dict[str, Client]`
    *   **Purpose:**
        *   Bypasses Binance Testnet's limitation on streams per connection.
        *   Isolates connection errors (e.g., if BTC stream drops, ETH stream remains active).
    
2.  **Strategy Instances**
    *   **Cardinality:** 1 Strategy Instance per Symbol.
    *   **Structure:** `TradingEngine.strategies: Dict[str, BaseStrategy]`
    *   **Purpose:**
        *   Maintains independent `candle_buffers` (historical data) for each symbol.
        *   Calculates indicators (RSI, MEMS, etc.) independently to prevent cross-contamination of state.

### B. Centralized Components (Shared)
These components exist as **Singletons** (single instance) within the `TradingEngine`, managing resources efficiently across all symbols.

1.  **DataCollector (The Wrapper)**
    *   **Role:** Container for all data ingestion.
    *   **Structure:** Single instance holding multiple WebSocket clients and one REST client.
    *   **Key Distinction:** "The Collector is one, but it has many ears (WebSockets)."

2.  **REST API Client**
    *   **Role:** Historical data fetching and order execution.
    *   **Structure:** `DataCollector.rest_client` & `OrderManager.client`.
    *   **Reason:** REST is stateless (request/response), so a single client can handle requests for any symbol efficiently.

3.  **EventBus**
    *   **Role:** Central nervous system.
    *   **Mechanism:** Single bus sharing queues (`data`, `signal`, `order`) for all symbols.
    *   **Routing:** Events carry `symbol` metadata (e.g., `event.data.symbol`), allowing consumers to identify the source/target.

4.  **OrderExecutionManager**
    *   **Role:** Execution gateway.
    *   **Mechanism:** Manages `_open_orders` dictionary keyed by symbol. Handles API rate limits globally.

5.  **RiskManager**
    *   **Role:** Global risk controller.
    *   **Mechanism:** Enforces account-wide rules (e.g., Max Drawdown, Total Exposure) and per-trade rules (Position Sizing) uniformly.

---

## 3. Data Flow Summary

The data flows through the system in a **Loop**, alternating between distributed and centralized phases:

1.  **Ingestion (Distributed):**
    *   `BTC_WS` receives a kline update.
    *   Wraps it in an `Event` tagged with `symbol="BTCUSDT"`.
    *   Pushes to `EventBus`.

2.  **Routing (Centralized):**
    *   `TradingEngine` consumes the event.
    *   Identifies the symbol tag.
    *   Selects the corresponding `Strategy` instance (`self.strategies["BTCUSDT"]`).

3.  **Analysis (Distributed):**
    *   `BTC_Strategy` updates its private `candle_buffer`.
    *   Runs logic (e.g., "Is RSI > 70?").
    *   If condition met, generates a `Signal` tagged with `symbol="BTCUSDT"`.
    *   Pushes to `EventBus`.

4.  **Execution (Centralized):**
    *   `OrderManager` consumes the signal.
    *   `RiskManager` validates it against global account rules.
    *   `OrderManager` sends the order via the shared `REST Client`.
