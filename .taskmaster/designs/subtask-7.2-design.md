# Task 7.2: Signal Validation Design Document

## Overview

Design and implementation specification for `validate_risk()` method in RiskManager class to validate trading signals for TP/SL correctness and position conflicts.

## Architecture

### Component Design

```
┌─────────────────────────────────────────────────────────────┐
│                      RiskManager                             │
├─────────────────────────────────────────────────────────────┤
│ - max_risk_per_trade: float                                 │
│ - max_leverage: int                                          │
│ - default_leverage: int                                      │
│ - max_position_size_percent: float                          │
│ - logger: Logger                                             │
├─────────────────────────────────────────────────────────────┤
│ + calculate_position_size(...) -> float         [✅ Task 7.1]│
│ + validate_risk(signal, position) -> bool       [🔄 Task 7.2]│
└─────────────────────────────────────────────────────────────┘
                        │
                        │ validates
                        ▼
        ┌───────────────────────────────┐
        │         Signal                │
        ├───────────────────────────────┤
        │ signal_type: SignalType       │
        │ entry_price: float            │
        │ take_profit: float            │
        │ stop_loss: float              │
        │ symbol: str                   │
        └───────────────────────────────┘
                        │
                        │ conflicts with?
                        ▼
        ┌───────────────────────────────┐
        │        Position               │
        ├───────────────────────────────┤
        │ symbol: str                   │
        │ side: str ('LONG'|'SHORT')    │
        │ entry_price: float            │
        │ quantity: float               │
        └───────────────────────────────┘
```

## Method Specification

### validate_risk()

**Signature:**
```python
def validate_risk(self, signal: Signal, position: Optional[Position]) -> bool
```

**Purpose:**
Validate trading signal against risk management rules, checking:
1. Position conflict prevention (no concurrent positions)
2. TP/SL placement correctness for signal direction

**Parameters:**
- `signal`: Signal - Trading signal to validate
- `position`: Optional[Position] - Current position if exists

**Returns:**
- `bool`: True if signal passes all validations, False otherwise

**Side Effects:**
- Logs warning messages for each validation failure

## Validation Logic Flow

```
validate_risk(signal, position)
    │
    ├─► Check 1: Position Conflict
    │   └─► if position is not None:
    │       ├─► Log: "Signal rejected: existing position for {symbol}"
    │       └─► Return False
    │
    ├─► Check 2: LONG_ENTRY Validation
    │   └─► if signal.signal_type == SignalType.LONG_ENTRY:
    │       ├─► Check TP > entry_price
    │       │   └─► if TP <= entry:
    │       │       ├─► Log: "Signal rejected: LONG TP must be > entry"
    │       │       └─► Return False
    │       └─► Check SL < entry_price
    │           └─► if SL >= entry:
    │               ├─► Log: "Signal rejected: LONG SL must be < entry"
    │               └─► Return False
    │
    ├─► Check 3: SHORT_ENTRY Validation
    │   └─► if signal.signal_type == SignalType.SHORT_ENTRY:
    │       ├─► Check TP < entry_price
    │       │   └─► if TP >= entry:
    │       │       ├─► Log: "Signal rejected: SHORT TP must be < entry"
    │       │       └─► Return False
    │       └─► Check SL > entry_price
    │           └─► if SL <= entry:
    │               ├─► Log: "Signal rejected: SHORT SL must be > entry"
    │               └─► Return False
    │
    └─► All validations passed
        └─► Return True
```

## Validation Rules

### Rule 1: Position Conflict Prevention

**Rule:** Only one position per symbol at a time

**Logic:**
```python
if position is not None:
    # Reject signal - position already exists
    return False
```

**Log Message:**
```
"Signal rejected: existing position for {symbol} (side: {side}, entry: {entry_price})"
```

**Rationale:**
- Prevents position stacking and complex risk management
- Ensures clear position tracking and P&L calculation
- Simplifies order management logic

### Rule 2: LONG Position TP/SL Validation

**Requirements:**
- Take Profit **must be above** entry price (TP > entry)
- Stop Loss **must be below** entry price (SL < entry)

**Logic:**
```python
if signal.signal_type == SignalType.LONG_ENTRY:
    if signal.take_profit <= signal.entry_price:
        # Invalid: TP not above entry
        return False
    if signal.stop_loss >= signal.entry_price:
        # Invalid: SL not below entry
        return False
```

**Log Messages:**
```
"Signal rejected: LONG TP ({tp}) must be > entry ({entry})"
"Signal rejected: LONG SL ({sl}) must be < entry ({entry})"
```

**Example:**
```python
# Valid LONG signal
entry = 50000, TP = 51000, SL = 49000  # ✅ TP above, SL below

# Invalid LONG signals
entry = 50000, TP = 49000, SL = 49000  # ❌ TP below entry
entry = 50000, TP = 51000, SL = 51000  # ❌ SL above entry
```

### Rule 3: SHORT Position TP/SL Validation

**Requirements:**
- Take Profit **must be below** entry price (TP < entry)
- Stop Loss **must be above** entry price (SL > entry)

**Logic:**
```python
if signal.signal_type == SignalType.SHORT_ENTRY:
    if signal.take_profit >= signal.entry_price:
        # Invalid: TP not below entry
        return False
    if signal.stop_loss <= signal.entry_price:
        # Invalid: SL not above entry
        return False
```

**Log Messages:**
```
"Signal rejected: SHORT TP ({tp}) must be < entry ({entry})"
"Signal rejected: SHORT SL ({sl}) must be > entry ({entry})"
```

**Example:**
```python
# Valid SHORT signal
entry = 50000, TP = 49000, SL = 51000  # ✅ TP below, SL above

# Invalid SHORT signals
entry = 50000, TP = 51000, SL = 51000  # ❌ TP above entry
entry = 50000, TP = 49000, SL = 49000  # ❌ SL below entry
```

## Implementation Details

### Dependencies

```python
from typing import Optional
from src.models.signal import Signal, SignalType
from src.models.position import Position
import logging
```

### Code Structure

```python
def validate_risk(self, signal: Signal, position: Optional[Position]) -> bool:
    """
    Validate if signal meets risk requirements

    Args:
        signal: Signal to validate
        position: Current position if exists

    Returns:
        True if risk is acceptable
    """
    # Import SignalType enum
    from src.models.signal import SignalType

    # Check 1: Position conflict
    if position is not None:
        self.logger.warning(
            f"Signal rejected: existing position for {signal.symbol} "
            f"(side: {position.side}, entry: {position.entry_price})"
        )
        return False

    # Check 2: LONG_ENTRY validation
    if signal.signal_type == SignalType.LONG_ENTRY:
        if signal.take_profit <= signal.entry_price:
            self.logger.warning(
                f"Signal rejected: LONG TP ({signal.take_profit}) "
                f"must be > entry ({signal.entry_price})"
            )
            return False
        if signal.stop_loss >= signal.entry_price:
            self.logger.warning(
                f"Signal rejected: LONG SL ({signal.stop_loss}) "
                f"must be < entry ({signal.entry_price})"
            )
            return False

    # Check 3: SHORT_ENTRY validation
    elif signal.signal_type == SignalType.SHORT_ENTRY:
        if signal.take_profit >= signal.entry_price:
            self.logger.warning(
                f"Signal rejected: SHORT TP ({signal.take_profit}) "
                f"must be < entry ({signal.entry_price})"
            )
            return False
        if signal.stop_loss <= signal.entry_price:
            self.logger.warning(
                f"Signal rejected: SHORT SL ({signal.stop_loss}) "
                f"must be > entry ({signal.entry_price})"
            )
            return False

    # All validations passed
    return True
```

## Test Strategy

### Test Coverage Matrix

| Test Case | Signal Type | TP/SL | Position | Expected | Log Check |
|-----------|-------------|-------|----------|----------|-----------|
| 1 | LONG_ENTRY | Valid | None | ✅ Pass | No logs |
| 2 | SHORT_ENTRY | Valid | None | ✅ Pass | No logs |
| 3 | LONG_ENTRY | TP ≤ entry | None | ❌ Fail | "LONG TP must be > entry" |
| 4 | LONG_ENTRY | SL ≥ entry | None | ❌ Fail | "LONG SL must be < entry" |
| 5 | SHORT_ENTRY | TP ≥ entry | None | ❌ Fail | "SHORT TP must be < entry" |
| 6 | SHORT_ENTRY | SL ≤ entry | None | ❌ Fail | "SHORT SL must be > entry" |
| 7 | LONG_ENTRY | Valid | Exists | ❌ Fail | "existing position" |

### Test Implementation

```python
class TestSignalValidation:
    """Test suite for subtask 7.2 - Signal validation"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager"""
        config = {
            'max_risk_per_trade': 0.01,
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1
        }
        return RiskManager(config)

    def test_valid_long_signal(self, risk_manager):
        """Valid LONG signal passes validation"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,  # Above entry ✅
            stop_loss=49000,    # Below entry ✅
            strategy_name="test",
            timestamp=datetime.now()
        )
        assert risk_manager.validate_risk(signal, None) is True

    def test_valid_short_signal(self, risk_manager):
        """Valid SHORT signal passes validation"""
        signal = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=49000,  # Below entry ✅
            stop_loss=51000,    # Above entry ✅
            strategy_name="test",
            timestamp=datetime.now()
        )
        assert risk_manager.validate_risk(signal, None) is True

    def test_long_invalid_tp(self, risk_manager, caplog):
        """LONG signal with TP ≤ entry is rejected"""
        with caplog.at_level(logging.WARNING):
            signal = Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                take_profit=49000,  # Below entry ❌
                stop_loss=49000,
                strategy_name="test",
                timestamp=datetime.now()
            )
            # Note: Signal.__post_init__ will raise ValueError
            # Test with mocked Signal or modify test approach

    def test_existing_position_rejection(self, risk_manager, caplog):
        """Signal rejected when position exists"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test",
            timestamp=datetime.now()
        )
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000,
            quantity=0.1,
            leverage=10
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position)

        assert result is False
        assert "Signal rejected: existing position" in caplog.text
```

## Edge Cases & Considerations

### 1. Signal Model Pre-Validation

**Issue:** Signal.__post_init__() already validates TP/SL placement

**Impact:** Invalid signals cannot be created in the first place

**Solution:**
- RiskManager validation acts as a **second validation layer**
- Useful for runtime checks with Position context
- Tests may need to mock Signal or use relaxed validation

### 2. Exit Signals (CLOSE_LONG, CLOSE_SHORT)

**Current Behavior:** Only LONG_ENTRY and SHORT_ENTRY are validated

**Future Consideration:** Exit signals may need different validation rules

### 3. Position Symbol Mismatch

**Assumption:** Position and Signal share same symbol (checked elsewhere)

**Note:** This method assumes symbol matching is handled by caller

### 4. Logging Performance

**Consideration:** Warning logs for every rejection

**Impact:** Minimal - warnings are infrequent in normal operation

## Integration Points

### Upstream Dependencies
- Signal model (Task 6)
- Position model (Task 6)
- SignalType enum

### Downstream Usage
- TradingEngine will call validate_risk() before order placement
- OrderManager may use for pre-execution validation

### Related Subtasks
- Task 7.1: Position size calculation (completed)
- Task 7.3: Position size limiting (depends on 7.2)
- Task 7.4: Quantity rounding (depends on 7.2)

## Success Criteria

✅ **Implementation Complete When:**
1. validate_risk() method implemented with all 3 validation checks
2. All 7 test cases pass
3. Warning logs contain specific rejection reasons
4. Code coverage ≥ 95% for validate_risk() method

✅ **Code Quality:**
- Clear separation of concerns (one check per block)
- Informative log messages with actual values
- Consistent error handling pattern

✅ **Documentation:**
- Method docstring with examples
- Clear parameter descriptions
- Return value semantics documented

## References

- Task 7.2 specification: `.taskmaster/tasks/task-7.2.md`
- Signal model: `src/models/signal.py:20-81`
- Position model: `src/models/position.py:11-53`
- RiskManager: `src/risk/manager.py:10-128`
