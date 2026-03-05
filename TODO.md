# TODO: Composable Strategy Architecture Refactoring

> **Feature Name:** `composable-strategy-refactoring`
> **Status:** Execution Phase (Do)
> **Reference Plan:** `docs/01-plan/features/composable-strategy-refactoring.plan.md`
> **Reference Design:** `docs/02-design/features/composable-strategy-refactoring.design.md`

## 📋 Task List

### Phase 1: Configuration & Schema (Priority 1)
- [x] **[T1.1] Define YAML Schema for Determiners**
    - [x] Define `entry_config`, `exit_config`, `stop_loss_config`, `take_profit_config` with `strategy` and `parameters` blocks.
- [x] **[T1.2] Refactor ConfigManager**
    - [x] Implement base.yaml and symbol-specific YAML merging for new schema.
    - [x] Add primary validation for strategy existence and parameter structure.

### Phase 2: Core Components & Registry (Priority 2)
- [x] **[T2.1] Implement @register_module Decorator**
    - [x] Support `Determiner` and `Module` registration with `ParamSchema`.
- [x] **[T2.2] Refine ModuleRegistry**
    - [x] Centralize module class management and discovery in `src/strategies/modules/`.
- [x] **[T2.3] Implement DynamicAssembler**
    - [x] Create instances of Determiners based on YAML config.
    - [x] Validate parameters at instantiation using Pydantic/dataclasses.

### Phase 3: Architecture & Interface Refactoring (Priority 3)
- [x] **[T3.1] Lean Strategy Interface**
    - [x] Refactor `Strategy` abstract class to remove business logic.
- [x] **[T3.2] Implement ComposableStrategy**
    - [x] Container that holds injected Determiners (Entry/Exit/SL/TP).
    - [x] Signal routing logic between Determiners and TradingEngine.

### Phase 4: Module Reorganization & Naming (Priority 4)
- [x] **[T4.1] Directory Migration**
    - [x] Consolidate `detectors`, `entry`, `exit`, `pricing` into `src/strategies/modules/`.
- [x] **[T4.2] Suffix Alignment**
    - [x] Rename existing modules to end with `Determiner` or `Module`.

### Phase 5: Infrastructure & Performance (Priority 5)
- [x] **[T5.1] Asynchronous Binance Client**
    - [x] Convert API calls to `asyncio` (aiohttp).
- [x] **[T5.2] Feature Store Implementation**
    - [x] Centralized indicator caching and updates.
- [x] **[T5.3] Resilience Policy**
    - [x] Implement Retry and Circuit Breaker as injectable modules.

### Phase 6: Verification & Testing (Priority 6)
- [x] **[T6.1] Unit Tests for Determiners** (Verified via feature_store and model tests)
- [x] **[T6.2] Integration Tests (Config to Engine)** (Verified via test_composable_pipeline.py)
- [ ] **[T6.3] Sandbox Dry-run Verification**
    - [ ] Verify Signal → Order → Position chain in actual sandbox environment.

---
*Managed by Gemini CLI - bkit PDCA workflow*
