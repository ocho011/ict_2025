# Status: Project Storage & Buffer Architecture Analysis

Analysis Date: 2025-12-28
Scope: Data Collector, Event Bus, Strategy Layer

## 1. Component Storage Analysis

### A. Data Collector (`BinanceDataCollector`)
- **Status:** ✅ **Optimized for Multi-Interval**
- **Storage Structure:** `Dict[str, deque]`
- **Key Format:** `"{SYMBOL}_{INTERVAL}"` (e.g., `BTCUSDT_1m`, `ETHUSDT_1h`)
- **Mechanism:** 
  - Uses `deque` with `maxlen` for automatic FIFO management.
  - Distinct buffers for every ticker and timeframe combination.
  - Successfully isolates data streams.

### B. Event Bus (`EventBus`)
- **Status:** ⚠️ **Transient Mixing (By Design)**
- **Storage Structure:** `Dict[str, asyncio.Queue]`
- **Queues:** `'data'`, `'signal'`, `'order'`
- **Mechanism:**
  - Acts as a pipe, not storage.
  - No separation by symbol or interval within the queue.
  - All candle data flows through the single `'data'` queue.
  - Consumers must filter/dispatch events based on `Event.data` attributes.

### C. Strategy Layer (`BaseStrategy`)
- **Status:** ❌ **Critical Limitation (Needs Refactoring)**
- **Storage Structure:** `List[Candle]` (Single List)
- **Variable:** `self.candle_buffer`
- **Mechanism:**
  - A single list stores all incoming candles.
  - **Issue:** If multiple intervals (e.g., 1m, 1h) are fed to one strategy instance, they are mixed into this single list.
  - **Consequence:** Indicator calculations (SMA, RSI) will be incorrect due to mixed timeframe data.
  - **Action Item:** Refactor to `Dict[str, deque]` similar to Data Collector.

---

## 2. Strategy Buffer Design Analysis

### Buffer Scope & Ownership
- **Type:** **Instance-Specific**
- **Implementation:** 
  - `self.candle_buffer` is initialized in `BaseStrategy.__init__`.
  - Each strategy instance maintains its own completely isolated copy of historical data.
- **Shared Memory:** **None**. There is no "global buffer" shared across strategies. Does not reference Data Collector's memory.

### Multi-Strategy Implications
- **Safety:** High. Strategy A cannot corrupt Strategy B's data.
- **Efficiency:** Low. If multiple strategies use the same data (e.g., BTC 1m), data is duplicated in memory for each instance.
- **Engine Limitation:** 
  - Current `TradingEngine` holds a single reference: `self.strategy: Optional[BaseStrategy]`.
  - **Blocker:** Cannot currently run multiple strategies simultaneously without refactoring the engine to hold a list or dict of strategies.

## 3. Summary & Roadmap
1. **Immediate Fix:** Refactor `BaseStrategy` to support multi-interval buffers (Dict structure).
2. **Future Improvement:** Refactor `TradingEngine` to support multiple strategy instances (Strategy Manager pattern).
