# Design: Composable Strategy Architecture & Refactoring

> **Status:** Draft / Design Review
> **Target Date:** 2026-03-05
> **Reference Plan:** [composable-strategy-refactoring.plan.md](../../01-plan/features/composable-strategy-refactoring.plan.md)

## 1. Architectural Overview

The goal is to move from a monolithic/hybrid strategy structure to a **Full Composable Architecture**.

### 1.1. Hierarchy & Responsibilities
- **TradingEngine (The Context)**: Manages the lifecycle of multiple strategies, handles real-time data streams, and executes orders.
- **ComposableStrategy (The Orchestrator)**: A lean container that coordinates signals from multiple Determiners. It does not contain business logic.
- **Determiners (The Logic Units)**: Specialized modules for specific decision points.
    - `EntryDeterminer`: Generates entry signals (LONG/SHORT/FLAT).
    - `ExitDeterminer`: Generates exit signals for open positions.
    - `StopLossDeterminer`: Manages risk by determining exit price for protection.
    - `TakeProfitDeterminer`: Manages profit targets.
- **FeatureStore (The Data Hub)**: Centralized store for shared indicators and pre-computed features to avoid redundant calculations.

## 2. 5-Step Instance Creation Process

1.  **Module Definition**: Register classes using `@register_module` and define `ParamSchema`.
2.  **Registry Management**: `ModuleRegistry` stores and provides access to registered module classes.
3.  **Config Merging**: `ConfigManager` merges `base.yaml` and `symbols[*]` overrides.
4.  **Dynamic Assembly**: `DynamicAssembler` creates Determiner instances with injected parameters.
5.  **Strategy Orchestration**: `ComposableStrategy` is initialized with these instances.

## 3. Configuration Schema (YAML)

Refactoring the configuration to support dynamic module selection.

### 3.1. Symbol Configuration Example
```yaml
symbols:
  BTCUSDT:
    entry_config:
      strategy: "ict_optimal_entry"
      parameters:
        active_profile: "RELAXED"
        min_probability: 0.75
    exit_config:
      strategy: "trend_following_exit"
      parameters:
        lookback_period: 20
    stop_loss_config:
      strategy: "atr_trailing_sl"
      parameters:
        multiplier: 2.0
    take_profit_config:
      strategy: "fixed_rr_tp"
      parameters:
        rr_ratio: 1.5
```

## 4. Module Registry & Dynamic Assembler

### 4.1. Module Registry
- A singleton or global registry that maps string names to class types.
- Supports discovery via `src/strategies/modules/`.

### 4.2. Dynamic Assembler
- Logic for parsing the `parameters` block and passing them to the class constructor.
- Uses `Pydantic` or `dataclass` for schema validation at instantiation.

## 5. Infrastructure Refactoring

### 5.1. Non-blocking Async IO
- All Binance API calls must use `aiohttp` or `binance-connector-python` with `asyncio`.
- Hot paths (ticker streams) should minimize latency by using slots in dataclasses.

### 5.2. Dependency Injection
- Use a central `DIContainer` or pass dependencies through constructors.
- Dependencies to inject: `TradingEngine`, `BinanceClient`, `AuditLogger`, `FeatureStore`.

### 5.3. Feature Store
- Determiners request features by key (e.g., `self.feature_store.get('ema_200')`).
- Feature Store manages the cache and updates values upon new tick/candle events.

## 6. Directory Reorganization

Move all logic units to a unified location:
```bash
src/strategies/modules/
├── entry/
│   ├── ict_optimal_entry_determiner.py
│   └── simple_ma_entry_determiner.py
├── exit/
│   └── trend_following_exit_determiner.py
├── sl/
│   └── atr_trailing_sl_determiner.py
└── tp/
    └── fixed_rr_tp_determiner.py
```

## 7. Execution Flow

1.  **Data Received**: `TradingEngine` receives a new tick/candle.
2.  **Feature Update**: `FeatureStore` updates all subscribed indicators.
3.  **Strategy Tick**: `ComposableStrategy.on_tick()` is called.
4.  **Entry Check**: `EntryDeterminer.evaluate()` checks for signals.
5.  **Signal Routing**: If signal generated, `ComposableStrategy` requests `TradingEngine` to execute order.
6.  **Audit Log**: `AuditLogger` records the signal and decision context.

## 8. Resilience Policy

- **Retry Policy**: Exponential backoff for HTTP 5xx or connection errors.
- **Circuit Breaker**: Trip if consecutive failures exceed threshold; enter Half-Open state after cooldown.
- **Graceful Shutdown**: Ensure all orders are cancelled or positions handled if critical failure occurs.

## 9. Verification Plan

- **Unit Tests**: Test each Determiner with mock data for signal accuracy.
- **Mock Integration**: Test `DynamicAssembler` with various YAML configurations.
- **Dry-run**: Run in sandbox with real-time data but mock execution to verify the signal-to-order chain.
- **Performance Benchmark**: Measure latency from `Tick Received` to `Order Sent`.
