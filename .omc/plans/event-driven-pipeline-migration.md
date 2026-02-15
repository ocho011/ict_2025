# Event-Driven Pipeline Migration Plan

## Context

### Original Request
컴포넌트 조립형 전략 설계에 맞게 시그널 생성 -> 주문 생성/전송 -> 포지션 라이프사이클 관리까지 이벤트 드리븐 파이프라인을 구현하고, 기존 모노리식 전략하에서의 매매 플로우를 완전히 대체. 마이그레이션 완료 후 불필요한 파일/클래스/메서드 삭제.

### Current State Summary
- **Composable modules ALREADY EXIST** (commit `a08c130`): `src/entry/`, `src/exit/`, `src/pricing/`, `src/strategies/composable.py`
- **ComposableStrategy is NOT wired** into `TradingEngine.initialize_components()` - it only calls `StrategyFactory.create()` which returns monolithic strategies
- **EventDispatcher** tightly couples to `ICTStrategy._trailing_levels` via `getattr(strategy, "_trailing_levels", None)` in `maybe_update_exchange_sl()`
- **Config** (`trading_config.ini`) has no `strategy_type` field to distinguish composable vs monolithic
- **Tests** extensively reference `StrategyFactory.create()` and monolithic strategies

### Research Findings
- `StrategyFactory.create_composed()` already exists but is never called from production code
- `ICTExitDeterminer` has its own `_trailing_levels` dict (independent from `ICTStrategy._trailing_levels`)
- `NullExitDeterminer` exists for strategies without dynamic exit
- `AlwaysEntryDeterminer` and `SMAEntryDeterminer` can replace `AlwaysSignalStrategy` and `MockSMACrossoverStrategy`
- Signal cooldown is hardcoded at 300s in `EventDispatcher.__init__`
- Import counts: ~11 files reference `ICTStrategy` (2 src + 8 tests + docstrings), 6 files reference `MockSMACrossoverStrategy`, 5 files reference `AlwaysSignalStrategy`
- `StrategyModuleConfig` is `@dataclass(frozen=True)` — instances are immutable after creation
- `ICTEntryDeterminer` uses `from_config(cls, config: dict)` classmethod (not direct `__init__`) with profile loading
- `_load_trading_config()` return statement is at **line 725** (NOT line 669); lines 742-756 are **unreachable dead code** after the return

---

## Work Objectives

### Core Objective
Wire `ComposableStrategy` into the live trading pipeline as the default strategy type, replacing monolithic strategies while maintaining full backward compatibility during transition.

### Deliverables
1. Config-driven composable strategy wiring in `TradingEngine`
2. `EventDispatcher` adapted for composable strategy interface (protocol-based trailing level access)
3. Module config builder that maps config names to composable module assemblies
4. End-to-end pipeline validation (composable produces equivalent signals)
5. Dead code removal of all monolithic strategy files
6. Updated tests for the new pipeline

### Definition of Done
- `TradingEngine.initialize_components()` creates `ComposableStrategy` instances when `strategy_type = composable` in config
- Full event flow works: WebSocket -> Candle -> ComposableStrategy.analyze() -> Signal -> TradeCoordinator -> OrderGateway
- Exit flow works: ComposableStrategy.should_exit() -> Signal -> TradeCoordinator
- Dynamic SL sync works with `ICTExitDeterminer._trailing_levels`
- All existing tests pass (updated for new code paths)
- Monolithic strategy files deleted
- Zero import errors, zero runtime errors

---

## Must Have / Must NOT Have (Guardrails)

### Must Have
- Backward-compatible config: old `strategy = ict_strategy` still works during transition
- `strategy_type` config field (`composable` | `monolithic`) with `composable` as new default
- Module config builder that maps strategy names to determiner assemblies
- Protocol/interface for trailing level access (not `getattr` hack)
- All existing tests green after migration

### Must NOT Have
- Breaking changes to `Signal`, `Event`, `EventType`, or `EventBus` models
- Changes to `TradeCoordinator` or `OrderGateway` (they are strategy-agnostic)
- Changes to `RiskGuard` (receives Signal, doesn't care about strategy type)
- New dependencies or external packages
- Changes to `BaseStrategy` ABC interface (analyze, should_exit signatures)

---

## Task Flow and Dependencies

```
Phase 1: Config & Wiring ─────────────────────┐
  T1.1: Add strategy_type to TradingConfig     │
  T1.2: Create ModuleConfigBuilder             │
  T1.3: Wire create_composed into TradingEngine│
                                               ▼
Phase 2: EventDispatcher Adaptation ───────────┐
  T2.1: Create TrailingLevelProvider protocol  │
  T2.2: Adapt maybe_update_exchange_sl         │
  T2.3: Make signal cooldown configurable      │
                                               ▼
Phase 3: End-to-End Validation ────────────────┐
  T3.1: Integration test: composable pipeline  │
  T3.2: Unit tests for ModuleConfigBuilder     │
  T3.3: Verify signal equivalence              │
                                               ▼
Phase 4: Default Switch ───────────────────────┐
  T4.1: Make composable the default            │
  T4.2: Update trading_config.ini              │
                                               ▼
Phase 5: Dead Code Removal ────────────────────┐
  T5.1: Delete monolithic strategy files       │
  T5.2: Clean StrategyFactory registry         │
  T5.3: Remove backward-compat code            │
  T5.4: Clean imports across codebase          │
                                               ▼
Phase 6: Test Cleanup ─────────────────────────┘
  T6.1: Update tests referencing deleted code
  T6.2: Add regression tests for composable
```

---

## Phase 1: Config-Driven ComposableStrategy Wiring

### T1.1: Add `strategy_type` to TradingConfig

**File:** `src/utils/config_manager.py`

**Changes:**
1. Add `strategy_type: str = "composable"` field to `TradingConfig` dataclass (after `max_symbols` at line 206)
2. Add validation: `strategy_type` must be `"composable"` or `"monolithic"`
3. Load from `[trading]` section in `_load_trading_config()` — add to `return TradingConfig(...)` at **line 725-740**

**NOTE:** Lines 742-756 in `_load_trading_config()` are unreachable dead code (after the return statement). Do NOT add code there.

**Specific edits:**
```python
# In TradingConfig dataclass, add after margin_type:
strategy_type: str = "composable"  # "composable" | "monolithic"

# In __post_init__, add validation:
if self.strategy_type not in ("composable", "monolithic"):
    raise ConfigurationError(
        f"strategy_type must be 'composable' or 'monolithic', got {self.strategy_type}"
    )

# In _load_trading_config(), add to return statement:
strategy_type=trading.get("strategy_type", "composable"),
```

**Acceptance Criteria:**
- `TradingConfig` accepts `strategy_type` field
- Validation rejects invalid values
- Defaults to `"composable"`
- Backward compatible: missing field uses default

---

### T1.2: Create ModuleConfigBuilder

**New File:** `src/strategies/module_config_builder.py`

**Purpose:** Maps strategy name + config dict to `StrategyModuleConfig` with all 4 determiners.

**Content:**
```python
"""
Builder for StrategyModuleConfig from configuration.

Maps strategy names to composable module assemblies:
- "ict_strategy" -> ICTEntryDeterminer + ZoneBasedStopLoss + DisplacementTakeProfit + ICTExitDeterminer
- "mock_sma"     -> SMAEntryDeterminer + PercentageStopLoss + RiskRewardTakeProfit + NullExitDeterminer
- "always_signal"-> AlwaysEntryDeterminer + PercentageStopLoss + RiskRewardTakeProfit + NullExitDeterminer
"""
```

**Registry mapping:**

| Strategy Name | Entry | StopLoss | TakeProfit | Exit | Intervals |
|--------------|-------|----------|------------|------|-----------|
| `ict_strategy` | `ICTEntryDeterminer` | `ZoneBasedStopLoss` | `DisplacementTakeProfit` (fallback: `RiskRewardTakeProfit`) | `ICTExitDeterminer` | `[ltf, mtf, htf]` from ict_config |
| `mock_sma` | `SMAEntryDeterminer` | `PercentageStopLoss` | `RiskRewardTakeProfit` | `NullExitDeterminer` | `[default_interval]` |
| `always_signal` | `AlwaysEntryDeterminer` | `PercentageStopLoss` | `RiskRewardTakeProfit` | `NullExitDeterminer` | `[default_interval]` |

**Key function signature:**
```python
def build_module_config(
    strategy_name: str,
    strategy_config: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """
    Build StrategyModuleConfig from strategy name and config.

    Returns:
        Tuple of (module_config, intervals_override, min_rr_ratio)
    """
```

**ICT-specific wiring logic:**
- Use `ICTEntryDeterminer.from_config(strategy_config)` classmethod (NOT direct constructor) — it handles profile loading automatically
- Pass `exit_config` + shared params to `ICTExitDeterminer` constructor directly
- Extract `ltf_interval`, `mtf_interval`, `htf_interval` for intervals override
- Use `rr_ratio` from config for `min_rr_ratio` (default 2.0)

**NOTE:** `StrategyModuleConfig` is `@dataclass(frozen=True)` — immutable after creation. Each call to `build_module_config()` returns a new instance.

**Exact config key → constructor parameter mapping:**

| Config Key | ICTEntryDeterminer | ICTExitDeterminer |
|---|---|---|
| `swing_lookback` | `swing_lookback` (via `from_config`) | `swing_lookback` |
| `displacement_ratio` | `displacement_ratio` (via `from_config`) | `displacement_ratio` |
| `fvg_min_gap_percent` | `fvg_min_gap_percent` (via `from_config`) | N/A |
| `ob_min_strength` | `ob_min_strength` (via `from_config`) | N/A |
| `liquidity_tolerance` | `liquidity_tolerance` (via `from_config`) | N/A |
| `use_killzones` | `use_killzones` (via `from_config`) | N/A |
| `ltf_interval` | `ltf_interval` (via `from_config`) | N/A |
| `mtf_interval` | `mtf_interval` (via `from_config`) | `mtf_interval` |
| `htf_interval` | `htf_interval` (via `from_config`) | `htf_interval` |
| `active_profile` | Profile loading in `from_config()` | N/A |
| `exit_config` (ExitConfig obj) | N/A | `exit_config` |

**Construction pattern:**
```python
# ICTEntryDeterminer: use classmethod (handles profile + defaults)
entry = ICTEntryDeterminer.from_config(strategy_config)

# ICTExitDeterminer: direct construction
exit_det = ICTExitDeterminer(
    exit_config=exit_config,
    swing_lookback=strategy_config.get("swing_lookback", 5),
    displacement_ratio=strategy_config.get("displacement_ratio", 1.5),
    mtf_interval=strategy_config.get("mtf_interval", "1h"),
    htf_interval=strategy_config.get("htf_interval", "4h"),
)
```

**Acceptance Criteria:**
- `build_module_config("ict_strategy", config, exit_config)` returns valid `StrategyModuleConfig` with all 4 ICT determiners
- `build_module_config("mock_sma", config)` returns SMA determiners
- `build_module_config("always_signal", config)` returns always-signal determiners
- Unknown strategy name raises `ValueError`
- Unit tests in `tests/strategies/test_module_config_builder.py`

---

### T1.3: Wire `create_composed` into TradingEngine

**File:** `src/core/trading_engine.py`

**Changes to `initialize_components()` (lines 204-213):**

Replace the current strategy creation loop:
```python
# CURRENT (lines 208-213):
self.strategies = {}
for symbol in trading_config.symbols:
    self.strategies[symbol] = StrategyFactory.create(
        name=trading_config.strategy, symbol=symbol, config=strategy_config
    )
```

With branching logic (call `build_module_config` **inside** the per-symbol loop to ensure each symbol gets its own determiner instances — prevents shared mutable state like `_trailing_levels`):
```python
# NEW:
self.strategies = {}
if trading_config.strategy_type == "composable":
    from src.strategies.module_config_builder import build_module_config
    for symbol in trading_config.symbols:
        # Each symbol gets its OWN StrategyModuleConfig with fresh determiner instances
        module_config, intervals_override, min_rr_ratio = build_module_config(
            strategy_name=trading_config.strategy,
            strategy_config=strategy_config,
            exit_config=trading_config.exit_config,
        )
        self.strategies[symbol] = StrategyFactory.create_composed(
            symbol=symbol,
            config=strategy_config,
            module_config=module_config,
            intervals=intervals_override,
            min_rr_ratio=min_rr_ratio,
        )
        self.logger.info(f"  Strategy created for {symbol} (composable)")
else:
    # Legacy monolithic path (transition only — removed in Phase 5)
    for symbol in trading_config.symbols:
        self.strategies[symbol] = StrategyFactory.create(
            name=trading_config.strategy, symbol=symbol, config=strategy_config
        )
        self.logger.info(f"  Strategy created for {symbol} (monolithic)")
```

**Acceptance Criteria:**
- `strategy_type = composable` creates `ComposableStrategy` instances
- `strategy_type = monolithic` creates legacy strategy instances (backward compat)
- All existing tests still pass with monolithic path
- New test verifies composable path creates correct strategy type

---

## Phase 2: EventDispatcher Adaptation

### T2.1: Create TrailingLevelProvider Protocol

**New File:** `src/strategies/trailing_level_protocol.py`

**Purpose:** Replace `getattr(strategy, "_trailing_levels", None)` with a proper protocol.

```python
"""Protocol for strategies that provide trailing stop levels."""
from typing import Dict, Optional, Protocol, runtime_checkable

@runtime_checkable
class TrailingLevelProvider(Protocol):
    """Protocol for accessing trailing stop levels.

    Implemented by:
    - ICTStrategy (monolithic) via _trailing_levels dict
    - ICTExitDeterminer (composable) via _trailing_levels dict
    """
    @property
    def trailing_levels(self) -> Dict[str, float]:
        """Return dict of trailing levels keyed by '{symbol}_{side}'."""
        ...
```

**Changes needed in `ICTExitDeterminer`** (`src/exit/ict_exit.py`):
- Add `trailing_levels` property that returns `self._trailing_levels`

**Changes needed in `ComposableStrategy`** (`src/strategies/composable.py`):
- Add `trailing_levels` property that delegates to `self.module_config.exit_determiner.trailing_levels` if the exit determiner implements `TrailingLevelProvider`, else returns empty dict

**Acceptance Criteria:**
- `isinstance(strategy, TrailingLevelProvider)` works for both composable and monolithic ICT strategies
- Protocol is runtime-checkable
- Non-ICT strategies (SMA, AlwaysSignal) do NOT implement the protocol

---

### T2.2: Adapt `maybe_update_exchange_sl`

**File:** `src/core/event_dispatcher.py`

**Changes to `maybe_update_exchange_sl()` (lines 223-269):**

Replace:
```python
trailing_levels = getattr(strategy, "_trailing_levels", None)
```

With (Protocol approach — single implementation, no alternatives):
```python
from src.strategies.trailing_level_protocol import TrailingLevelProvider

if isinstance(strategy, TrailingLevelProvider):
    trailing_levels = strategy.trailing_levels
else:
    return  # Strategy doesn't support trailing levels
```

This works because:
1. `ComposableStrategy.trailing_levels` property delegates to `self.module_config.exit_determiner` if it implements `TrailingLevelProvider`, else returns `{}`
2. `ICTStrategy.trailing_levels` property wraps `self._trailing_levels` (during transition)
3. Non-ICT strategies don't implement the protocol → silently skipped

**Acceptance Criteria:**
- Dynamic SL sync works with `ComposableStrategy` using `ICTExitDeterminer`
- Dynamic SL sync still works with legacy `ICTStrategy` (during transition)
- No `getattr` hack with private attribute names
- Strategies without trailing levels are silently skipped

---

### T2.3: Make Signal Cooldown Configurable *(OPTIONAL — can defer to separate PR)*

> **Note:** This task adds scope beyond the core migration objective. It is a nice-to-have improvement that can be deferred to a follow-up PR to keep the migration focused. Include only if time permits.

**File:** `src/core/event_dispatcher.py`

**Change:** Currently hardcoded at line 67:
```python
self._signal_cooldown: float = 300.0  # 5 minutes cooldown
```

Make it configurable via constructor parameter:
```python
def __init__(
    self,
    ...
    signal_cooldown: float = 300.0,
):
    ...
    self._signal_cooldown = signal_cooldown
```

**File:** `src/core/trading_engine.py`

**Change:** Pass cooldown from config when creating EventDispatcher (line 267-276).

**File:** `src/utils/config_manager.py`

**Change:** Add `signal_cooldown: float = 300.0` to `TradingConfig` with validation (60-3600 seconds).

**Acceptance Criteria:**
- Signal cooldown is configurable via `[trading]` section
- Default remains 300 seconds
- Validation: 60-3600 seconds range

---

## Phase 3: End-to-End Validation

### T3.1: Integration Test for Composable Pipeline

**New File:** `tests/integration/test_composable_pipeline.py`

**Test scenarios:**
1. **Full entry flow:** Candle -> EventDispatcher -> ComposableStrategy.analyze() -> Signal -> EventBus.publish(SIGNAL_GENERATED)
2. **Full exit flow:** Candle + Position -> EventDispatcher -> ComposableStrategy.should_exit() -> Signal -> EventBus.publish(SIGNAL_GENERATED)
3. **Dynamic SL sync:** Candle + Position -> EventDispatcher -> maybe_update_exchange_sl -> OrderGateway.update_stop_loss
4. **Signal cooldown:** Two rapid candles -> only first generates signal
5. **Multi-symbol:** BTCUSDT + ETHUSDT both using composable strategies

**Test setup:**
- Use `AlwaysEntryDeterminer` for deterministic signal generation
- Use `FixedExitDeterminer` (from test_composable.py) for exit testing
- Mock `OrderGateway`, `PositionCacheManager`
- Real `EventBus`, `EventDispatcher`, `ComposableStrategy`

**Acceptance Criteria:**
- All 5 scenarios pass
- Tests run in <5 seconds
- No flaky async behavior

---

### T3.2: Unit Tests for ModuleConfigBuilder

**New File:** `tests/strategies/test_module_config_builder.py`

**Test cases:**
1. `build_module_config("ict_strategy", ict_config, exit_config)` returns correct determiners
2. `build_module_config("mock_sma", config)` returns SMA + Percentage + RiskReward + Null
3. `build_module_config("always_signal", config)` returns Always + Percentage + RiskReward + Null
4. Unknown strategy raises `ValueError`
5. ICT config extracts intervals correctly
6. ICT config extracts min_rr_ratio from `rr_ratio`
7. Missing `exit_config` for ICT uses default `ExitConfig()`

**Acceptance Criteria:**
- All test cases pass
- 100% coverage of `module_config_builder.py`

---

### T3.3: Verify Signal Equivalence (Manual/Optional)

**Purpose:** Confirm composable ICT strategy produces same signals as monolithic on same data.

**Approach:** This is a manual verification step, not an automated test. The composable strategy delegates to `ICTEntryDeterminer` which is extracted from `ICTStrategy.analyze()` steps 1-8. The logic is identical by construction.

**Verification points:**
- Entry decisions: same conditions, same metadata
- TP/SL: may differ slightly if composable uses different pricing determiners (ZoneBasedStopLoss vs ICTStrategy's inline calc)
- Exit signals: same 4 strategies, same trailing logic

**Risk:** TP/SL calculations may differ between monolithic (inline in ICTStrategy) and composable (via pricing determiners). This is EXPECTED and ACCEPTABLE - the composable versions use the cleaner modular implementations.

---

## Phase 4: Full Migration Switch

### T4.1: Make Composable the Default

**File:** `src/utils/config_manager.py`

**Change:** Default `strategy_type` is already `"composable"` (set in T1.1). This task verifies:
1. Production config (`trading_config.ini`) works with composable
2. All test configs work with composable
3. Monolithic path still works when explicitly set

**Acceptance Criteria:**
- System starts successfully with default composable config
- All existing functionality preserved

---

### T4.2: Update trading_config.ini

**File:** `configs/trading_config.ini`

**Changes:**
1. Add `strategy_type = composable` to `[trading]` section (after `strategy = ict_strategy` line 55)
2. Add comment explaining the field

```ini
# Strategy type: composable (modular determiners) or monolithic (single class)
# composable: Uses modular entry/exit/pricing determiners (RECOMMENDED)
# monolithic: Legacy single-class strategies (deprecated)
strategy_type = composable
```

**Acceptance Criteria:**
- Config file updated
- System starts successfully with updated config

---

## Phase 5: Dead Code Removal

### T5.1: Delete Monolithic Strategy Files

**Files to DELETE:**

| File | Reason | Lines |
|------|--------|-------|
| `src/strategies/ict_strategy.py` | Replaced by `ICTEntryDeterminer` + `ICTExitDeterminer` + pricing determiners | 1252 |
| `src/strategies/mock_strategy.py` | Replaced by `SMAEntryDeterminer` + `NullExitDeterminer` | ~100 |
| `src/strategies/always_signal.py` | Replaced by `AlwaysEntryDeterminer` + `NullExitDeterminer` | ~80 |

**Total dead code removed:** ~1432 lines

**Acceptance Criteria:**
- Files deleted
- No import errors anywhere in `src/`
- `python -c "import src"` succeeds

---

### T5.2: Clean StrategyFactory Registry

**File:** `src/strategies/__init__.py`

**Changes:**
1. Remove monolithic imports:
   ```python
   # DELETE these:
   from src.strategies.always_signal import AlwaysSignalStrategy
   from src.strategies.ict_strategy import ICTStrategy
   from src.strategies.mock_strategy import MockSMACrossoverStrategy
   ```

2. Remove from `_strategies` registry:
   ```python
   # DELETE these entries:
   "mock_sma": MockSMACrossoverStrategy,
   "always_signal": AlwaysSignalStrategy,
   "ict_strategy": ICTStrategy,
   ```

3. Remove `StrategyFactory.create()` method entirely (or keep as thin wrapper that raises deprecation)

4. Update `__all__`:
   ```python
   __all__ = [
       "BaseStrategy",
       "ComposableStrategy",
       "StrategyFactory",
   ]
   ```

**Acceptance Criteria:**
- No monolithic strategy classes in registry
- `StrategyFactory.create_composed()` is the only creation method
- All imports clean

---

### T5.3: Remove Backward-Compatibility Code

**File:** `src/core/trading_engine.py`

**Changes:**
1. Remove monolithic branch from `initialize_components()` (the `else` clause added in T1.3)
2. Remove the `strategy_type` check - always use composable path
3. Clean up backward-compatibility properties if no longer needed by tests

**File:** `src/strategies/base.py`

**Review:** `calculate_take_profit()` and `calculate_stop_loss()` methods (lines 993-1135) are used by monolithic strategies. After monolithic deletion:
- `ComposableStrategy` calculates TP/SL inline in `analyze()` via determiners
- These methods are still called by `BaseStrategy._create_price_config()` default path
- **Keep them** - they provide fallback behavior and are part of the ABC contract
- However, they are no longer abstract, just concrete default implementations

**Acceptance Criteria:**
- No `strategy_type == "monolithic"` code paths remain
- TradingEngine always creates composable strategies
- Code compiles and runs without errors

---

### T5.4: Clean Imports Across Codebase

**Files that import deleted modules (must be updated):**

| File | Import to Remove/Update |
|------|------------------------|
| `src/strategies/__init__.py` | Remove `ICTStrategy`, `MockSMACrossoverStrategy`, `AlwaysSignalStrategy` imports |
| `src/entry/ict_entry.py` | **Docstring only** — update docstring references to `ICTStrategy` (no import) |
| `src/exit/ict_exit.py` | **Docstring only** — update docstring references to `ICTStrategy` (no import) |
| `tests/test_dynamic_exit.py` | Remove `ICTStrategy` import, rewrite tests to use `ICTExitDeterminer` |
| `tests/integration/test_mtf_integration.py` | Remove `ICTStrategy` import, rewrite with composable |
| `tests/integration/test_multi_coin.py` | Remove `ICTStrategy` import, rewrite with composable |
| `tests/integration/test_dynamic_exit_integration.py` | Remove `ICTStrategy` import, rewrite with composable |
| `tests/test_feature_cache.py` | Remove `ICTStrategy` import, use composable or mock |
| `tests/strategies/test_ict_strategy.py` | DELETE entirely (tests the deleted monolithic class) |
| `tests/test_ict_strategy_profiles.py` | DELETE or rewrite for composable ICT |
| `tests/strategies/test_mock_strategy.py` | DELETE entirely (tests the deleted monolithic class) |
| `tests/strategies/test_always_signal.py` | DELETE entirely (tests already covered in `test_composable.py`) |
| `tests/strategies/test_factory.py` | Rewrite to test `create_composed()` instead of `create()` |
| `tests/core/test_trading_engine.py` | Update `StrategyFactory.create` mocks to `create_composed` |
| `scripts/verify_tpsl.py` | Update `MockSMACrossoverStrategy` references |

**Acceptance Criteria:**
- Import verification (no false positives from docstrings):
  `grep -rn "from src.strategies.ict_strategy\|from src.strategies.mock_strategy\|from src.strategies.always_signal\|import ICTStrategy\|import MockSMACrossoverStrategy\|import AlwaysSignalStrategy" src/ tests/ scripts/` returns zero matches
- Docstring cleanup verification:
  `grep -rn "ICTStrategy\|MockSMACrossoverStrategy\|AlwaysSignalStrategy" src/` returns zero matches (including docstrings in `ict_entry.py` and `ict_exit.py`)
- All imports resolve without errors

---

## Phase 6: Test Cleanup

### T6.1: Update Tests Referencing Deleted Code

**Tests to DELETE (test deleted monolithic classes):**

| Test File | Reason |
|-----------|--------|
| `tests/strategies/test_ict_strategy.py` | Tests `ICTStrategy` (deleted) |
| `tests/strategies/test_mock_strategy.py` | Tests `MockSMACrossoverStrategy` (deleted) |
| `tests/strategies/test_always_signal.py` | Tests `AlwaysSignalStrategy` (deleted); covered by `test_composable.py::TestAlwaysEntryDeterminer` |
| `tests/test_ict_strategy_profiles.py` | Tests ICT profiles via `ICTStrategy` (deleted) |

**Tests to REWRITE:**

| Test File | What Changes |
|-----------|--------------|
| `tests/strategies/test_factory.py` | Test `create_composed()` with `ModuleConfigBuilder`; remove `create()` tests |
| `tests/core/test_trading_engine.py` | Replace `StrategyFactory.create` mocks with `create_composed` / `build_module_config` mocks |
| `tests/test_dynamic_exit.py` | Test exit strategies via `ICTExitDeterminer` directly (not via `ICTStrategy`) |
| `tests/integration/test_dynamic_exit_integration.py` | Use composable strategy with `ICTExitDeterminer` |
| `tests/integration/test_mtf_integration.py` | Use composable strategy with ICT determiners |
| `tests/integration/test_multi_coin.py` | Use composable strategy |
| `tests/test_feature_cache.py` | Mock strategy or use composable |

**Acceptance Criteria:**
- `pytest tests/` runs with zero failures
- No test references deleted classes
- Test coverage maintained or improved

---

### T6.2: Add Regression Tests for Composable Pipeline

**New tests to add (extend `tests/strategies/test_composable.py`):**

1. **ICT Entry -> SL -> TP -> Signal:** Full composable ICT flow with real `ICTEntryDeterminer`, `ZoneBasedStopLoss`, `DisplacementTakeProfit`
2. **ICT Exit with trailing levels:** Composable ICT with `ICTExitDeterminer`, verify trailing level state
3. **Module config builder integration:** `build_module_config()` -> `create_composed()` -> `analyze()`
4. **Multi-symbol isolation:** Two symbols with separate composable strategies don't share state

**Acceptance Criteria:**
- New regression tests pass
- Tests verify real determiner classes (not just mocks)

---

## Commit Strategy

| Commit | Phase | Description |
|--------|-------|-------------|
| 1 | Phase 1 | `feat: add strategy_type config and ModuleConfigBuilder for composable strategy wiring` |
| 2 | Phase 2 | `refactor: adapt EventDispatcher for composable strategies with TrailingLevelProvider protocol` |
| 3 | Phase 3 | `test: add integration tests for composable pipeline and module config builder` |
| 4 | Phase 4 | `feat: make composable strategy the default and update production config` |
| 5 | Phase 5 | `refactor: remove monolithic strategy files and clean dead code (ICTStrategy, MockSMA, AlwaysSignal)` |
| 6 | Phase 6 | `test: update and clean tests for composable-only strategy pipeline` |

---

## Success Criteria

| Criteria | Verification |
|----------|-------------|
| Composable strategies created by TradingEngine | Unit test: `isinstance(strategy, ComposableStrategy)` |
| Full signal flow works end-to-end | Integration test: candle in -> signal out -> order |
| Dynamic SL sync works | Integration test: trailing level -> exchange SL update |
| All tests pass | `pytest tests/ -q` returns 0 failures |
| No dead code | `grep -r "ICTStrategy" src/` returns 0 |
| No import errors | `python -c "from src.core.trading_engine import TradingEngine"` succeeds |
| Config backward compatible | Old config without `strategy_type` still works |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| ICT signal equivalence differs | ACCEPTED: Composable uses cleaner modular pricing. Document differences. |
| Trailing level state conflicts | Per-symbol `StrategyModuleConfig` instances prevent shared state |
| Test coverage drops | Phase 6 adds regression tests before deleting old tests |
| Production config breaks | Phase 1 adds backward compat; Phase 4 only flips default after validation |
| `_trailing_levels` key format mismatch | Both use `{symbol}_{side}` format - verified in code review |
