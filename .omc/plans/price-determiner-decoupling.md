# Plan: Strategy and Price Determination Decoupling (Revised)

**Issue:** GitHub #46 - 전략과 가격 결정 로직의 디커플링 및 추상화
**Created:** 2026-01-26
**Status:** APPROVED (Ralplan Iteration 2 - Critic Approved)
**Previous Issues Addressed:** Type safety, import dependencies, method signatures, ICT integration

---

## 1. Requirements Summary

### Background
The current codebase has tight coupling between strategy logic and price determination (entry price, stop loss, take profit calculations). Price calculations are embedded within strategy implementations as abstract methods in `BaseStrategy`.

### Goals
1. **Decouple** price determination logic from strategy classes
2. **Create reusable** `PriceDeterminer` interface and concrete implementations
3. **Enable dependency injection** of price calculators into strategies
4. **Maintain backward compatibility** with existing strategy configurations
5. **Improve testability** - price logic independently testable

### Scope
- Stop loss calculation (percentage-based and zone-based)
- Take profit calculation (risk-reward and displacement-based)
- **Out of scope (Phase 1):** Entry price determination - remains `candle.close`
- **Out of scope:** `should_exit()` logic - uses existing SL/TP or custom exit conditions

### Scope Clarification: Why `should_exit()` Is Out of Scope
The `should_exit()` method in `BaseStrategy` (lines 692-942) handles **dynamic exit logic** such as:
- Trailing stops
- Time-based exits
- Momentum reversal exits

This is **different from** TP/SL price calculation:
- `calculate_take_profit()` / `calculate_stop_loss()` → Static prices set at signal creation
- `should_exit()` → Dynamic evaluation during position lifetime

The `PriceDeterminer` abstraction targets static price calculations. Dynamic exit logic remains strategy-specific.

---

## 2. Current State Analysis

### Files Involved
| File | Current Responsibility | Changes Required |
|------|----------------------|------------------|
| `src/strategies/base.py` | Abstract `calculate_take_profit()`, `calculate_stop_loss()` methods | Add `_price_config`, delegate to determiners |
| `src/strategies/ict_strategy.py` | ICT-specific price logic with detector dependencies | Override `_create_price_config()` |
| `src/strategies/mock_strategy.py` | Percentage-based price calculations | Remove duplicated logic, use inherited |
| `src/strategies/always_signal.py` | Duplicate of mock_strategy price logic | Remove duplicated logic, use inherited |
| `src/strategies/__init__.py` | Strategy exports | Add pricing module exports |

### Current Price Calculation Patterns

**Pattern 1: Percentage-Based (Simple)** - MockSMACrossoverStrategy, AlwaysSignalStrategy
```python
stop_loss = entry_price * (1 - stop_loss_percent)  # LONG
take_profit = entry_price + (sl_distance * risk_reward_ratio)
```

**Pattern 2: Zone-Based + Displacement (ICT)** - ICTStrategy
```python
# SL: _calculate_stop_loss_with_indicators() at lines 684-726
stop_loss = zone_edge + buffer  # From FVG or OB, fallback to 1%

# TP: _calculate_take_profit_with_buffer() at lines 614-652
take_profit = entry + (displacement_size * rr_ratio)
```

### Critical Insight: ICTStrategy Has Two SL Calculation Paths
1. `calculate_stop_loss()` (lines 728-745) → Simple 1% fallback for BaseStrategy compliance
2. `_calculate_stop_loss_with_indicators()` (lines 684-726) → Full ICT logic with FVG/OB

The refactoring must preserve this dual behavior by having ICTStrategy inject a `ZoneBasedStopLoss` that mimics `_calculate_stop_loss_with_indicators()`.

---

## 3. Proposed Architecture

### 3.1 New Module Structure

```
src/
├── pricing/
│   ├── __init__.py                    # Module exports
│   ├── base.py                        # PriceDeterminer ABC + typed context
│   ├── stop_loss/
│   │   ├── __init__.py
│   │   ├── percentage.py              # PercentageStopLoss
│   │   └── zone_based.py              # ZoneBasedStopLoss (ICT)
│   └── take_profit/
│       ├── __init__.py
│       ├── risk_reward.py             # RiskRewardTakeProfit
│       └── displacement.py            # DisplacementTakeProfit (ICT)
```

### 3.2 Interface Design (Type-Safe)

```python
# src/pricing/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Protocol, Callable, Tuple
import time


@dataclass(frozen=True, slots=True)
class PriceContext:
    """
    Immutable context for price calculations.

    Type-safe design: Indicator data passed as typed fields, not Dict[str, Any].
    Real-time compliance: Uses int timestamp, no datetime parsing.
    """
    entry_price: float
    side: str  # "LONG" | "SHORT"
    symbol: str
    timestamp: int  # Unix timestamp in milliseconds

    # ICT-specific typed fields (optional)
    fvg_zone: Optional[Tuple[float, float]] = None  # (zone_low, zone_high)
    ob_zone: Optional[Tuple[float, float]] = None   # (zone_low, zone_high)
    displacement_size: Optional[float] = None       # For displacement-based TP

    @classmethod
    def from_strategy(
        cls,
        entry_price: float,
        side: str,
        symbol: str,
        fvg_zone: Optional[Tuple[float, float]] = None,
        ob_zone: Optional[Tuple[float, float]] = None,
        displacement_size: Optional[float] = None,
    ) -> "PriceContext":
        """Factory method for strategy use."""
        return cls(
            entry_price=entry_price,
            side=side,
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            fvg_zone=fvg_zone,
            ob_zone=ob_zone,
            displacement_size=displacement_size,
        )


class StopLossDeterminer(ABC):
    """Abstract base for stop loss determination."""

    @abstractmethod
    def calculate_stop_loss(self, context: PriceContext) -> float:
        """Calculate stop loss price."""
        pass


class TakeProfitDeterminer(ABC):
    """Abstract base for take profit determination."""

    @abstractmethod
    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        """Calculate take profit price. May use SL distance for risk-reward."""
        pass


@dataclass(frozen=True, slots=True)
class PriceDeterminerConfig:
    """Configuration bundle for strategy injection."""
    stop_loss_determiner: StopLossDeterminer
    take_profit_determiner: TakeProfitDeterminer
```

### 3.3 Concrete Implementations

#### PercentageStopLoss
```python
# src/pricing/stop_loss/percentage.py
from dataclasses import dataclass
from src.pricing.base import StopLossDeterminer, PriceContext


@dataclass(frozen=True, slots=True)
class PercentageStopLoss(StopLossDeterminer):
    """Fixed percentage stop loss from entry price."""
    stop_loss_percent: float = 0.01  # 1% default

    def calculate_stop_loss(self, context: PriceContext) -> float:
        if context.side == "LONG":
            return context.entry_price * (1.0 - self.stop_loss_percent)
        else:  # SHORT
            return context.entry_price * (1.0 + self.stop_loss_percent)
```

#### ZoneBasedStopLoss (ICT)
```python
# src/pricing/stop_loss/zone_based.py
from dataclasses import dataclass
from typing import Optional, Tuple
from src.pricing.base import StopLossDeterminer, PriceContext
from src.pricing.stop_loss.percentage import PercentageStopLoss


@dataclass(frozen=True, slots=True)
class ZoneBasedStopLoss(StopLossDeterminer):
    """
    ICT zone-based stop loss using pre-calculated FVG/OB zones.

    Design Decision: Zone extraction happens BEFORE calling the determiner.
    This avoids circular imports: strategy calls get_entry_zone() -> passes tuple to context.
    """
    buffer_percent: float = 0.001  # 0.1%
    fallback_percent: float = 0.01  # 1% fallback

    def calculate_stop_loss(self, context: PriceContext) -> float:
        # Priority: FVG zone > OB zone > fallback percentage
        zone = context.fvg_zone or context.ob_zone

        if zone:
            return self._apply_buffer(context, zone)

        # Fallback to percentage-based SL
        return PercentageStopLoss(self.fallback_percent).calculate_stop_loss(context)

    def _apply_buffer(self, context: PriceContext, zone: Tuple[float, float]) -> float:
        zone_low, zone_high = zone
        buffer = context.entry_price * self.buffer_percent

        if context.side == "LONG":
            sl = zone_low - buffer
            return sl if sl < context.entry_price else context.entry_price * (1 - self.fallback_percent)
        else:  # SHORT
            sl = zone_high + buffer
            return sl if sl > context.entry_price else context.entry_price * (1 + self.fallback_percent)
```

#### RiskRewardTakeProfit
```python
# src/pricing/take_profit/risk_reward.py
from dataclasses import dataclass
from src.pricing.base import TakeProfitDeterminer, PriceContext


@dataclass(frozen=True, slots=True)
class RiskRewardTakeProfit(TakeProfitDeterminer):
    """Take profit based on risk-reward ratio from stop loss distance."""
    risk_reward_ratio: float = 2.0

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        sl_distance = abs(context.entry_price - stop_loss)
        tp_distance = sl_distance * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + tp_distance
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - tp_distance
            return tp if tp < context.entry_price else context.entry_price * 0.98
```

#### DisplacementTakeProfit (ICT)
```python
# src/pricing/take_profit/displacement.py
from dataclasses import dataclass
from src.pricing.base import TakeProfitDeterminer, PriceContext


@dataclass(frozen=True, slots=True)
class DisplacementTakeProfit(TakeProfitDeterminer):
    """
    ICT displacement-based take profit.

    Uses displacement size as the risk measure instead of SL distance.
    Falls back to SL-based calculation if no displacement provided.
    """
    risk_reward_ratio: float = 2.0
    fallback_risk_percent: float = 0.02  # 2% fallback

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        # Use displacement size if available, else fallback to entry percentage
        if context.displacement_size and context.displacement_size > 0:
            risk_amount = context.displacement_size
        else:
            risk_amount = context.entry_price * self.fallback_risk_percent

        reward_amount = risk_amount * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + reward_amount
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - reward_amount
            return tp if tp < context.entry_price else context.entry_price * 0.98
```

### 3.4 Strategy Integration Pattern

#### BaseStrategy Modification
```python
# src/strategies/base.py - Add these methods

def _create_price_config(self, config: Dict[str, Any]) -> PriceDeterminerConfig:
    """
    Factory method for price determiner configuration.

    Subclasses can override to provide custom determiners.
    Default implementation: percentage-based SL + risk-reward TP.
    """
    from src.pricing.stop_loss.percentage import PercentageStopLoss
    from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
    from src.pricing.base import PriceDeterminerConfig

    return PriceDeterminerConfig(
        stop_loss_determiner=PercentageStopLoss(
            stop_loss_percent=config.get("stop_loss_percent", 0.01)
        ),
        take_profit_determiner=RiskRewardTakeProfit(
            risk_reward_ratio=config.get("risk_reward_ratio", 2.0)
        ),
    )


def _create_price_context(
    self,
    entry_price: float,
    side: str,
    fvg_zone: Optional[Tuple[float, float]] = None,
    ob_zone: Optional[Tuple[float, float]] = None,
    displacement_size: Optional[float] = None,
) -> "PriceContext":
    """
    Create PriceContext for determiner calls.

    Addresses Critic issue #4: Provides all required fields (symbol, timestamp).
    """
    from src.pricing.base import PriceContext
    return PriceContext.from_strategy(
        entry_price=entry_price,
        side=side,
        symbol=self.symbol,
        fvg_zone=fvg_zone,
        ob_zone=ob_zone,
        displacement_size=displacement_size,
    )
```

#### Backward-Compatible Method Delegation
```python
# In BaseStrategy.__init__():
self._price_config = self._create_price_config(config)

# Default implementations (keep @abstractmethod removed for these):
def calculate_stop_loss(self, entry_price: float, side: str) -> float:
    """Default SL calculation via injected determiner."""
    context = self._create_price_context(entry_price, side)
    return self._price_config.stop_loss_determiner.calculate_stop_loss(context)

def calculate_take_profit(self, entry_price: float, side: str) -> float:
    """Default TP calculation via injected determiner."""
    context = self._create_price_context(entry_price, side)
    stop_loss = self.calculate_stop_loss(entry_price, side)
    return self._price_config.take_profit_determiner.calculate_take_profit(context, stop_loss)
```

#### ICTStrategy Override
```python
# src/strategies/ict_strategy.py

def _create_price_config(self, config: Dict[str, Any]) -> PriceDeterminerConfig:
    """ICT uses zone-based SL and displacement-based TP."""
    from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
    from src.pricing.take_profit.displacement import DisplacementTakeProfit
    from src.pricing.base import PriceDeterminerConfig

    return PriceDeterminerConfig(
        stop_loss_determiner=ZoneBasedStopLoss(
            buffer_percent=config.get("sl_buffer_percent", 0.001),
            fallback_percent=config.get("stop_loss_percent", 0.01),
        ),
        take_profit_determiner=DisplacementTakeProfit(
            risk_reward_ratio=config.get("rr_ratio", self.rr_ratio),
            fallback_risk_percent=config.get("fallback_risk_percent", 0.02),
        ),
    )


# ICT-specific method that passes zone/displacement context
def calculate_stop_loss_with_context(
    self,
    entry_price: float,
    side: str,
    nearest_fvg=None,
    nearest_ob=None,
) -> float:
    """
    ICT-specific SL with zone context.

    Replaces _calculate_stop_loss_with_indicators().
    Zone extraction happens here (strategy side), not in determiner.
    """
    from src.detectors.ict_fvg import get_entry_zone
    from src.detectors.ict_order_block import get_ob_zone

    fvg_zone = get_entry_zone(nearest_fvg) if nearest_fvg else None
    ob_zone_tuple = get_ob_zone(nearest_ob) if nearest_ob else None

    context = self._create_price_context(
        entry_price=entry_price,
        side=side,
        fvg_zone=fvg_zone,
        ob_zone=ob_zone_tuple,
    )
    return self._price_config.stop_loss_determiner.calculate_stop_loss(context)


def calculate_take_profit_with_context(
    self,
    entry_price: float,
    side: str,
    displacement_size: Optional[float] = None,
) -> float:
    """
    ICT-specific TP with displacement context.

    Replaces _calculate_take_profit_with_buffer().
    """
    context = self._create_price_context(
        entry_price=entry_price,
        side=side,
        displacement_size=displacement_size,
    )
    stop_loss = self.calculate_stop_loss(entry_price, side)
    return self._price_config.take_profit_determiner.calculate_take_profit(context, stop_loss)
```

---

## 4. Import Dependency Analysis

### Dependency Diagram (Addresses Critic Issue #2)
```
┌─────────────────────────────────────────────────────────────────┐
│                     IMPORT FLOW (No Cycles)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  src/pricing/base.py          (No imports from strategies)      │
│       │                                                         │
│       ├── src/pricing/stop_loss/percentage.py                   │
│       │       (imports base.py)                                 │
│       │                                                         │
│       ├── src/pricing/stop_loss/zone_based.py                   │
│       │       (imports base.py, percentage.py)                  │
│       │       (NO imports from detectors - zones passed in)     │
│       │                                                         │
│       ├── src/pricing/take_profit/risk_reward.py                │
│       │       (imports base.py)                                 │
│       │                                                         │
│       └── src/pricing/take_profit/displacement.py               │
│               (imports base.py)                                 │
│                                                                 │
│  src/strategies/base.py                                         │
│       │  (imports from src/pricing/*)                           │
│       │                                                         │
│       └── src/strategies/ict_strategy.py                        │
│               (imports base.py, pricing/*, detectors/*)         │
│               (Zone extraction: detector → tuple → context)     │
│                                                                 │
│  src/detectors/ict_fvg.py, ict_order_block.py                   │
│       (NO imports from pricing or strategies)                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

KEY DESIGN: ZoneBasedStopLoss receives pre-extracted zone tuples,
            NOT FVG/OB objects. This prevents detector imports in pricing module.
```

---

## 5. Implementation Plan

### Phase 1: Create Pricing Module Foundation (No Strategy Changes Yet)
**Files to create:**
- `src/pricing/__init__.py`
- `src/pricing/base.py`
- `src/pricing/stop_loss/__init__.py`
- `src/pricing/stop_loss/percentage.py`
- `src/pricing/take_profit/__init__.py`
- `src/pricing/take_profit/risk_reward.py`

**Tests to create:**
- `tests/pricing/__init__.py`
- `tests/pricing/test_percentage_stop_loss.py`
- `tests/pricing/test_risk_reward_tp.py`

**Validation:** All new tests pass, no existing tests break.

### Phase 2: ICT-Specific Implementations
**Files to create:**
- `src/pricing/stop_loss/zone_based.py`
- `src/pricing/take_profit/displacement.py`

**Tests to create:**
- `tests/pricing/test_zone_based_sl.py`
- `tests/pricing/test_displacement_tp.py`

**Validation:** All new tests pass, import checks pass (no cycles).

### Phase 3: BaseStrategy Integration
**Files to modify:**
- `src/strategies/base.py`:
  - Add `_price_config` attribute in `__init__()`
  - Add `_create_price_config()` factory method
  - Add `_create_price_context()` helper method
  - Change `@abstractmethod` on `calculate_stop_loss()` to concrete default
  - Change `@abstractmethod` on `calculate_take_profit()` to concrete default

**Tests:** Run full `pytest tests/strategies/` - all must pass.

### Phase 4: Concrete Strategy Migration
**Files to modify:**
- `src/strategies/mock_strategy.py`:
  - Remove `calculate_stop_loss()` implementation (use inherited)
  - Remove `calculate_take_profit()` implementation (use inherited)
- `src/strategies/always_signal.py`:
  - Remove `calculate_stop_loss()` implementation (use inherited)
  - Remove `calculate_take_profit()` implementation (use inherited)
- `src/strategies/ict_strategy.py`:
  - Override `_create_price_config()` for ICT determiners
  - Add `calculate_stop_loss_with_context()` and `calculate_take_profit_with_context()`
  - Modify `analyze()` to call new context-aware methods
  - Keep `_calculate_stop_loss_with_indicators()` as deprecated (calls new method)

**Tests:** Run full `pytest tests/` - all must pass.

### Phase 5: Cleanup and Documentation
- Remove deprecated `_calculate_stop_loss_with_indicators()` in next release
- Update `src/strategies/__init__.py` exports
- Add docstrings and type hints

---

## 6. Acceptance Criteria

### Functional Requirements
- [ ] All existing tests pass without modification (backward compatibility)
- [ ] Price determiners are independently instantiable and testable
- [ ] `BaseStrategy.calculate_stop_loss()` delegates to injected determiner
- [ ] `BaseStrategy.calculate_take_profit()` delegates to injected determiner
- [ ] ICTStrategy correctly uses `ZoneBasedStopLoss` and `DisplacementTakeProfit`
- [ ] MockSMACrossoverStrategy and AlwaysSignalStrategy use inherited defaults
- [ ] Signal model validation still works (TP > entry for LONG, etc.)

### Non-Functional Requirements
- [ ] No performance regression: price calculation <1ms p99 (benchmark with `time.perf_counter_ns()`)
- [ ] Type hints on all new code (`mypy src/pricing/` passes)
- [ ] `@dataclass(frozen=True, slots=True)` for immutable value objects
- [ ] No circular imports (`python -c "from src.pricing import *"` succeeds)
- [ ] No circular imports (`python -c "from src.strategies import *"` succeeds)

### Test Coverage
- [ ] Unit tests for each concrete price determiner (>90% coverage)
- [ ] Integration tests for strategy + determiner combinations
- [ ] Edge case tests: zero price, negative values, side validation

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Backward compatibility break | Medium | High | Keep existing method signatures, delegate internally, deprecate gradually |
| Performance regression | Low | Medium | Use dataclasses with slots, avoid object creation in hot path |
| Detector coupling in zone-based | **Mitigated** | - | Zone extraction in strategy, pass tuples to determiner |
| ICT behavior regression | Medium | High | Comprehensive comparison tests between old and new implementations |
| Type safety loss | **Mitigated** | - | Typed fields in PriceContext instead of Dict[str, Any] |

---

## 8. Benchmark Methodology (Addresses Critic Issue #8)

### Baseline Measurement (Before Refactoring)
```python
# tests/pricing/test_performance.py
import time

def test_baseline_sl_performance():
    """Measure current SL calculation performance."""
    from src.strategies.mock_strategy import MockSMACrossoverStrategy

    strategy = MockSMACrossoverStrategy({"symbol": "BTCUSDT", ...})

    iterations = 10000
    start = time.perf_counter_ns()
    for _ in range(iterations):
        strategy.calculate_stop_loss(50000.0, "LONG")
    elapsed_ns = time.perf_counter_ns() - start

    p99_ns = elapsed_ns / iterations
    assert p99_ns < 1_000_000, f"SL calculation exceeded 1ms: {p99_ns/1e6:.3f}ms"
```

### Post-Refactoring Comparison
- Run same benchmark with new implementation
- Compare p99 latency before/after
- Target: <10% regression, ideally no regression

---

## 9. File-by-File Implementation Details

### 9.1 `src/pricing/base.py`
(See section 3.2 above - complete implementation)

### 9.2 `src/pricing/stop_loss/percentage.py`
(See section 3.3 above - complete implementation)

### 9.3 `src/pricing/stop_loss/zone_based.py`
(See section 3.3 above - complete implementation)

### 9.4 `src/pricing/take_profit/risk_reward.py`
(See section 3.3 above - complete implementation)

### 9.5 `src/pricing/take_profit/displacement.py`
(See section 3.3 above - complete implementation)

### 9.6 `src/strategies/base.py` Modifications
(See section 3.4 above - complete implementation)

### 9.7 `src/strategies/ict_strategy.py` Modifications
(See section 3.4 above - complete implementation)

---

## 10. Verification Steps

1. **Unit Tests:** `pytest tests/pricing/ -v` - all new tests pass
2. **Integration Tests:** `pytest tests/strategies/ -v` - all existing tests pass
3. **Type Check:** `mypy src/pricing/` - no type errors
4. **Import Check:** `python -c "from src.pricing import *; from src.strategies import *"` - no errors
5. **Performance:** Run benchmark tests - <1ms p99
6. **Manual Verification:** Create strategy with custom determiners, verify signals

---

## 11. Questions for Architect (From Critic Review)

### Q1: Per-init vs Per-signal determiners
**Question:** Should `PriceDeterminerConfig` be created once in `__init__()` or per-signal?

**Decision:** Created once in `__init__()`. Context data (zones, displacement) is passed via `PriceContext` per-call, not by recreating determiners. This maintains immutability and avoids allocation overhead.

### Q2: Abstract method removal
**Question:** Can `calculate_take_profit()` and `calculate_stop_loss()` be made non-abstract?

**Decision:** Yes. After migration, `BaseStrategy` provides default implementations that delegate to determiners. Subclasses override `_create_price_config()` for customization.

### Q3: Detector coupling decision
**Question:** Should `ZoneBasedStopLoss` import from `detectors` directly?

**Decision:** No. Zone extraction (`get_entry_zone()`, `get_ob_zone()`) happens in strategy code. The determiner receives pre-extracted `Tuple[float, float]` zones via `PriceContext`. This prevents circular imports.

### Q4: Entry price flexibility
**Question:** Is there a concrete use case for `EntryPriceDeterminer`?

**Decision:** Deferred to Phase 2. Current scope focuses on SL/TP decoupling. Entry price abstraction can be added later if limit order entry zones are needed.

---

PLAN_READY: .omc/plans/price-determiner-decoupling.md
