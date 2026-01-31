# Refactoring Proposal: Remove Circular Dependency and Improve Cohesion

## Overview
This document proposes a refactoring to move the `_on_candle_received` callback method from `TradingBot` to `TradingEngine`. This change aims to remove the circular dependency between `TradingBot` and `TradingEngine`, simplify the initialization process, and improve the conceptual cohesion of the trading logic.

## Motivation
Currently, `TradingBot` acts as a mediator for candle data, receiving updates from `BinanceDataCollector` and then passing an event loop reference to `TradingEngine` to bridge the thread gap. This creates a circular dependency where `TradingEngine` needs to know about `TradingBot` solely to access the event loop.

### Current Architecture Issues
1.  **Circular Dependency**: `TradingBot` creates `TradingEngine`, but `TradingEngine` holds a reference back to `TradingBot` to set the event loop.
2.  **Scattered Logic**: The "receiving" of data (`_on_candle_received`) is in `TradingBot`, while the "processing" logic is in `TradingEngine`.
3.  **Complex Lifecycle**: The event loop handoff (`set_event_loop`) adds an extra step to the runtime initialization sequence.

## Proposed Changes

### 1. Move `_on_candle_received` to `TradingEngine`
The `_on_candle_received` method should be moved from `TradingBot` to `TradingEngine` (renamed to `on_candle_received` or similar). `TradingEngine` is the natural place for this logic as it manages the `EventBus`.

### 2. Update Initialization Sequence in `TradingBot.initialize`
The initialization order in `src/main.py` needs to be adjusted:
- **Current**: `DataCollector` -> `TradingEngine` -> `engine.set_components(..., bot=self)`
- **Proposed**: `TradingEngine` -> `DataCollector` (with `engine.on_candle_received` callback) -> `engine.set_components(...)`

### 3. Remove `set_event_loop` and `trading_bot` Reference
- `TradingEngine` no longer needs a reference to `TradingBot`.
- `TradingEngine` can capture the running event loop directly in its `run()` method (or `start()` method) and store it as `self._event_loop`.
- The `lock` or `thread-safe` publishing logic remains the same, but it uses the locally stored loop reference.

## Implementation Steps

1.  **Modify `TradingEngine`**:
    - Add `on_candle_received(self, candle: Candle)` method.
    - Add `_event_loop` attribute to `TradingEngine`.
    - Capture `loop = asyncio.get_running_loop()` in `TradingEngine.run()`.
    - Remove `trading_bot` argument from `set_components`.

2.  **Modify `TradingBot`**:
    - Remove `_on_candle_received` method.
    - Remove `set_event_loop` method.
    - Remove `_event_loop` attribute.
    - In `initialize`:
        - Instantiate `TradingEngine` **before** `BinanceDataCollector`.
        - Pass `self.trading_engine.on_candle_received` to `BinanceDataCollector`.
        - Remove `self` from `engine.set_components` call.

## Benefits
- **Decoupling**: `TradingEngine` becomes a self-contained unit that doesn't depend on its container (`TradingBot`).
- **Cohesion**: Data ingestion and processing are co-located in the engine.
- **Simplicity**: Initialization flow is linear (Create Engine -> Create Collector -> Connect), removing the "create then go back and set loop" pattern.

## Verification
- Verify that `on_candle_received` is still called by the WebSocket thread.
- Verify that `run_coroutine_threadsafe` properly schedules events on the main loop using the engine's stored loop reference.
- Run integration tests to ensure data flow remains uninterrupted.
