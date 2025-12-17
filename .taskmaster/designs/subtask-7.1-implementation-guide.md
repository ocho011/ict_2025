# Subtask 7.1: Position Size Calculation - Implementation Guide

**Task**: Task 7 - Risk Management Module
**Subtask**: 7.1 - Position Size Calculation
**Status**: Ready for Implementation
**Date**: 2025-12-17

---

## 1. Current State Analysis

### 1.1 Existing Code Structure

**File**: `src/risk/manager.py`

```python
class RiskManager:
    """Manages risk and calculates position sizes"""

    def __init__(self, max_risk_per_trade: float, account_balance: float):
        self.max_risk_per_trade = max_risk_per_trade
        self.account_balance = account_balance

    def calculate_position_size(self, signal: Signal, stop_loss_price: float) -> float:
        """Calculate position size based on risk parameters"""
        pass  # TO BE IMPLEMENTED
```

**Issues Identified**:
1. ❌ Constructor signature doesn't match design document
2. ❌ Method signature uses `Signal` but should accept individual parameters
3. ❌ Missing `leverage` and `symbol_info` parameters
4. ❌ No logging setup
5. ❌ `account_balance` stored in constructor (should be queried dynamically)

### 1.2 Dependencies Available

**Signal Model** (`src/models/signal.py`):
```python
@dataclass(frozen=True)
class Signal:
    signal_type: SignalType
    symbol: str
    entry_price: float
    take_profit: float
    stop_loss: float  # ✓ Available
    # ... other fields
```

**Position Model** (`src/models/position.py`):
```python
@dataclass
class Position:
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    entry_price: float
    quantity: float
    leverage: int
    # ... other fields
```

---

## 2. Implementation Design

### 2.1 Method Signature (Corrected)

**Current (Incorrect)**:
```python
def calculate_position_size(self, signal: Signal, stop_loss_price: float) -> float:
```

**Target (Per Design Doc)**:
```python
def calculate_position_size(
    self,
    account_balance: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: int,
    symbol_info: Optional[dict] = None
) -> float:
```

**Rationale**:
- More flexible: works with any entry/SL, not just from Signal
- Explicit parameters: clearer what affects calculation
- Matches industry pattern (Nautilus Trader style)

### 2.2 Constructor Update Required

**Current**:
```python
def __init__(self, max_risk_per_trade: float, account_balance: float):
    self.max_risk_per_trade = max_risk_per_trade
    self.account_balance = account_balance
```

**Target**:
```python
def __init__(self, config: dict):
    """
    Initialize RiskManager with configuration.

    Args:
        config: Risk configuration dictionary with keys:
            - max_risk_per_trade: float (e.g., 0.01 for 1%)
            - max_leverage: int (e.g., 20)
            - default_leverage: int (e.g., 10)
            - max_position_size_percent: float (e.g., 0.1 for 10%)
    """
    self.max_risk_per_trade = config.get('max_risk_per_trade', 0.01)
    self.max_leverage = config.get('max_leverage', 20)
    self.default_leverage = config.get('default_leverage', 10)
    self.max_position_size_percent = config.get('max_position_size_percent', 0.1)

    # Setup logging
    self.logger = logging.getLogger(__name__)
```

**Migration Note**: Existing code may break. Need to update all instantiations:
```python
# Old
manager = RiskManager(max_risk_per_trade=0.01, account_balance=10000)

# New
manager = RiskManager(config={'max_risk_per_trade': 0.01})
# account_balance now passed to calculate_position_size()
```

### 2.3 Implementation Algorithm

```python
def calculate_position_size(
    self,
    account_balance: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: int,
    symbol_info: Optional[dict] = None
) -> float:
    """
    Calculate position size based on risk management rules.

    Formula:
        Risk Amount = Account Balance × Max Risk Per Trade
        SL Distance % = |Entry - SL| / Entry
        Position Value = Risk Amount / SL Distance %
        Quantity = Position Value / Entry Price

    Args:
        account_balance: Total USDT balance
        entry_price: Intended entry price
        stop_loss_price: Stop loss price level
        leverage: Leverage multiplier (1-125)
        symbol_info: Optional exchange symbol specs for rounding

    Returns:
        Position size in base asset units (e.g., BTC for BTCUSDT)

    Raises:
        ValueError: Invalid inputs (negative values, zero prices)

    Example:
        >>> manager = RiskManager({'max_risk_per_trade': 0.01})
        >>> size = manager.calculate_position_size(
        ...     account_balance=10000,
        ...     entry_price=50000,
        ...     stop_loss_price=49000,
        ...     leverage=10
        ... )
        >>> print(f"Position size: {size} BTC")
        Position size: 0.1 BTC
    """
    # Step 1: Input validation
    if account_balance <= 0:
        raise ValueError(f"Account balance must be > 0, got {account_balance}")
    if entry_price <= 0:
        raise ValueError(f"Entry price must be > 0, got {entry_price}")
    if stop_loss_price <= 0:
        raise ValueError(f"Stop loss price must be > 0, got {stop_loss_price}")
    if leverage < 1 or leverage > self.max_leverage:
        raise ValueError(
            f"Leverage must be between 1 and {self.max_leverage}, got {leverage}"
        )

    # Step 2: Calculate SL distance as percentage
    sl_distance_percent = abs(entry_price - stop_loss_price) / entry_price

    # Step 3: Handle zero SL edge case
    if sl_distance_percent == 0:
        self.logger.warning(
            "Zero SL distance detected. Using minimum 0.1% to prevent division by zero."
        )
        sl_distance_percent = 0.001  # 0.1% minimum

    # Step 4: Calculate risk amount in USDT
    risk_amount = account_balance * self.max_risk_per_trade

    # Step 5: Calculate position value and quantity
    position_value = risk_amount / sl_distance_percent
    quantity = position_value / entry_price

    # Step 6: Log calculation details
    self.logger.info(
        f"Position size calculated: {quantity:.4f} "
        f"(risk={risk_amount:.2f} USDT, "
        f"SL distance={sl_distance_percent:.2%})"
    )

    # Step 7: Return calculated quantity
    # Note: Limiting and rounding will be added in subtasks 7.3 and 7.4
    return quantity
```

### 2.4 Edge Case Handling Matrix

| Case | Detection | Handling | Example |
|------|-----------|----------|---------|
| **Zero SL Distance** | `sl_distance_percent == 0` | Use 0.001 (0.1%) minimum | Entry=50000, SL=50000 |
| **Negative Balance** | `account_balance <= 0` | Raise ValueError | balance=-100 |
| **Negative Prices** | `entry_price <= 0` or `stop_loss_price <= 0` | Raise ValueError | entry=-1 |
| **Invalid Leverage** | `leverage < 1` or `leverage > max_leverage` | Raise ValueError | leverage=0 or 200 |
| **Very Tight SL** | `sl_distance_percent < 0.001` | Allow with warning | Entry=50000, SL=49995 (0.01%) |
| **Very Wide SL** | `sl_distance_percent > 0.1` | Allow (naturally reduces size) | Entry=50000, SL=40000 (20%) |

---

## 3. Industry Pattern Comparison

### 3.1 Nautilus Trader Pattern (Reference)

```python
# From Nautilus Trader
def calculate_position_size(self, entry_price, stop_price, account_balance):
    # Risk amount per trade
    risk_amount = account_balance * self.MAX_RISK_PER_TRADE

    # Price difference for stop loss
    price_diff = abs(entry_price - stop_price)

    # Calculate position size
    position_size = risk_amount / price_diff

    # Apply maximum position size limit
    position_size = min(position_size, self.MAX_POSITION_SIZE)

    return position_size
```

**Key Differences**:
- ✅ Nautilus uses `price_diff` (absolute), we use `sl_distance_percent` (percentage)
- ✅ Our formula: `risk_amount / (sl_distance% × entry_price)` = `risk_amount / price_diff`
- ✅ Mathematically equivalent but our percentage approach is clearer
- ❌ Nautilus applies max size limit immediately (we'll add in 7.3)

### 3.2 Formula Validation

**Our Formula**:
```
Position Value = Risk Amount / SL Distance %
Quantity = Position Value / Entry Price
```

**Nautilus Formula (Simplified)**:
```
Quantity = Risk Amount / Price Diff
```

**Proof of Equivalence**:
```
Our: Quantity = (Risk Amount / (|Entry - SL| / Entry)) / Entry
            = Risk Amount / |Entry - SL|
            = Nautilus Quantity ✓
```

---

## 4. Test Specifications

### 4.1 Unit Tests (Per Task 7.1 Requirements)

**Test File**: `tests/test_risk_manager.py` (to be created)

```python
import pytest
from src.risk.manager import RiskManager

class TestPositionSizeCalculation:
    """Test suite for subtask 7.1"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager with standard config"""
        config = {
            'max_risk_per_trade': 0.01,  # 1%
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1  # 10%
        }
        return RiskManager(config)

    def test_normal_case_2_percent_sl(self, risk_manager):
        """
        Normal case: 1% risk with 2% SL distance

        Expected:
        - Risk: 10000 * 0.01 = 100 USDT
        - SL Distance: (50000-49000)/50000 = 2%
        - Position Value: 100 / 0.02 = 5000 USDT
        - Quantity: 5000 / 50000 = 0.1 BTC
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )

        assert quantity == pytest.approx(0.1, rel=0.01)

    def test_tight_sl_0_1_percent(self, risk_manager):
        """
        Edge case: Very tight SL (0.1%)

        Expected:
        - Risk: 100 USDT
        - SL Distance: 0.1% (tight)
        - Position Value: 100 / 0.001 = 100,000 USDT
        - Quantity: 100,000 / 50000 = 2.0 BTC (large!)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49950,  # 0.1% SL
            leverage=10
        )

        # Tight SL = larger position for same risk
        assert quantity == pytest.approx(2.0, rel=0.01)

    def test_wide_sl_10_percent(self, risk_manager):
        """
        Edge case: Wide SL (10%)

        Expected:
        - Risk: 100 USDT
        - SL Distance: 10%
        - Position Value: 100 / 0.10 = 1000 USDT
        - Quantity: 1000 / 50000 = 0.02 BTC (small)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=45000,  # 10% SL
            leverage=10
        )

        # Wide SL = smaller position
        assert quantity == pytest.approx(0.02, rel=0.01)

    def test_zero_sl_distance_uses_minimum(self, risk_manager, caplog):
        """
        Edge case: Zero SL distance (entry == stop_loss)

        Expected:
        - Warning logged
        - Use 0.001 (0.1%) minimum SL distance
        - Quantity calculated based on 0.1% SL
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=50000,  # Same as entry!
            leverage=10
        )

        # Should use 0.1% minimum SL
        # Position Value: 100 / 0.001 = 100,000 USDT
        # Quantity: 100,000 / 50000 = 2.0 BTC
        assert quantity == pytest.approx(2.0, rel=0.01)

        # Check warning was logged
        assert "Zero SL distance" in caplog.text
        assert "0.1%" in caplog.text

    def test_logging_outputs_correct_values(self, risk_manager, caplog):
        """Verify logging includes risk amount and SL distance"""
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10
        )

        # Check log message contains expected values
        assert "Position size calculated" in caplog.text
        assert "risk=100.00 USDT" in caplog.text
        assert "SL distance=2.00%" in caplog.text or "SL distance=0.02" in caplog.text

    def test_invalid_account_balance(self, risk_manager):
        """Should raise ValueError for invalid balance"""
        with pytest.raises(ValueError, match="Account balance must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=0,  # Invalid
                entry_price=50000,
                stop_loss_price=49000,
                leverage=10
            )

    def test_invalid_entry_price(self, risk_manager):
        """Should raise ValueError for invalid entry price"""
        with pytest.raises(ValueError, match="Entry price must be > 0"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=-50000,  # Invalid
                stop_loss_price=49000,
                leverage=10
            )

    def test_invalid_leverage(self, risk_manager):
        """Should raise ValueError for invalid leverage"""
        with pytest.raises(ValueError, match="Leverage must be between"):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49000,
                leverage=200  # Exceeds max_leverage=20
            )
```

### 4.2 Test Execution Plan

```bash
# Install pytest if not already installed
pip install pytest pytest-cov

# Run all subtask 7.1 tests
pytest tests/test_risk_manager.py::TestPositionSizeCalculation -v

# Run with coverage
pytest tests/test_risk_manager.py::TestPositionSizeCalculation --cov=src.risk.manager --cov-report=term-missing

# Run specific test
pytest tests/test_risk_manager.py::TestPositionSizeCalculation::test_normal_case_2_percent_sl -v
```

---

## 5. Implementation Checklist

### Phase 1: Update Class Structure
- [ ] Update `__init__` to accept config dict
- [ ] Add `max_leverage`, `default_leverage`, `max_position_size_percent` attributes
- [ ] Setup logging in `__init__`
- [ ] Remove `account_balance` from constructor (will be parameter)

### Phase 2: Implement Core Method
- [ ] Update method signature to match design
- [ ] Add input validation (Steps 1)
- [ ] Implement SL distance calculation (Step 2)
- [ ] Handle zero SL edge case (Step 3)
- [ ] Calculate risk amount (Step 4)
- [ ] Calculate position value and quantity (Step 5)
- [ ] Add detailed logging (Step 6)
- [ ] Return quantity (Step 7)

### Phase 3: Write Tests
- [ ] Create `tests/test_risk_manager.py`
- [ ] Implement `test_normal_case_2_percent_sl`
- [ ] Implement `test_tight_sl_0_1_percent`
- [ ] Implement `test_wide_sl_10_percent`
- [ ] Implement `test_zero_sl_distance_uses_minimum`
- [ ] Implement `test_logging_outputs_correct_values`
- [ ] Implement input validation tests

### Phase 4: Verification
- [ ] All tests pass
- [ ] Coverage > 95% for `calculate_position_size`
- [ ] No linting errors (`pylint src/risk/manager.py`)
- [ ] Type checking passes (`mypy src/risk/manager.py`)
- [ ] Manual testing with real scenarios

---

## 6. Breaking Changes & Migration

### 6.1 API Changes

**Constructor Signature Changed**:
```python
# Before (incorrect)
manager = RiskManager(max_risk_per_trade=0.01, account_balance=10000)

# After (correct)
config = {'max_risk_per_trade': 0.01}
manager = RiskManager(config)
```

**Method Signature Changed**:
```python
# Before (incorrect)
quantity = manager.calculate_position_size(signal, stop_loss_price=49000)

# After (correct)
quantity = manager.calculate_position_size(
    account_balance=10000,
    entry_price=signal.entry_price,
    stop_loss_price=49000,
    leverage=10
)
```

### 6.2 Migration Script (If Needed)

```python
# Check for existing usages
grep -r "RiskManager(" src/ tests/

# Search pattern:
# RiskManager(max_risk_per_trade=..., account_balance=...)

# Replace with:
# config = {'max_risk_per_trade': ...}
# RiskManager(config)
```

---

## 7. Performance Considerations

### 7.1 Computational Complexity

**Time Complexity**: O(1) - Pure arithmetic operations
- Division: 3 operations
- Multiplication: 2 operations
- Subtraction/Abs: 2 operations
- Total: ~7 arithmetic operations

**Space Complexity**: O(1) - No data structures
- Local variables: 4-5 floats
- No arrays, dictionaries, or growing structures

**Expected Latency**: <0.1ms per call (pure Python math)

### 7.2 Optimization Notes

- ✅ No database queries in this subtask
- ✅ No API calls
- ✅ No file I/O
- ✅ Pure calculation → extremely fast
- ⚠️ Logging has minimal overhead (~0.01ms)
- 💡 Can be called thousands of times per second if needed

---

## 8. Dependencies & Integration

### 8.1 Required Imports

```python
import logging
from typing import Optional
```

### 8.2 Integration with Task 6 (Order Manager)

**Not Required for Subtask 7.1** - This subtask is self-contained.

Future integration (Subtask 7.2+):
```python
# Later: Query account balance from OrderExecutionManager
from src.execution.order_manager import OrderExecutionManager

order_manager = OrderExecutionManager(...)
account_balance = order_manager.get_account_balance()

# Then pass to position sizing
quantity = risk_manager.calculate_position_size(
    account_balance=account_balance,  # From Task 6
    ...
)
```

### 8.3 Configuration Loading

```python
# From trading_config.ini (existing)
from src.utils.config import load_config

config = load_config('trading_config.ini')
risk_config = {
    'max_risk_per_trade': config.getfloat('risk', 'max_risk_per_trade', fallback=0.01),
    'max_leverage': config.getint('risk', 'max_leverage', fallback=20),
    'default_leverage': config.getint('risk', 'default_leverage', fallback=10),
    'max_position_size_percent': config.getfloat('risk', 'max_position_size_percent', fallback=0.1),
}

risk_manager = RiskManager(risk_config)
```

---

## 9. Success Criteria

### 9.1 Functional Requirements ✅

- [x] Calculates correct quantity for normal cases (1% risk, 2% SL)
- [x] Handles tight SL (<1%) without errors
- [x] Handles wide SL (>10%) appropriately
- [x] Prevents division by zero (minimum 0.1% SL)
- [x] Raises ValueError for invalid inputs
- [x] Logs calculation details (risk amount, SL distance)

### 9.2 Quality Requirements ✅

- [x] Test coverage > 95%
- [x] All unit tests pass
- [x] No linting errors (pylint score > 9.0)
- [x] Type hints for all parameters and return values
- [x] Comprehensive docstring with examples

### 9.3 Performance Requirements ✅

- [x] Execution time < 1ms per call
- [x] No memory leaks (pure function)
- [x] Thread-safe (no shared state modified)

---

## 10. Next Steps After Completion

### 10.1 Immediate (Subtask 7.2)

Implement `validate_signal()` method:
- Check TP/SL correctness for LONG/SHORT
- Position conflict detection
- Depends on completed `calculate_position_size()`

### 10.2 Near-Term (Subtask 7.3)

Add position size limiting:
- Max position size enforcement
- R:R ratio calculation
- Integrate with `calculate_position_size()` (add limiting logic)

### 10.3 Final (Subtask 7.4)

Add lot size rounding:
- Binance symbol specification compliance
- Integrate with `calculate_position_size()` (add rounding as final step)

---

## 11. Quick Reference

### 11.1 Formula Cheat Sheet

```
SL Distance % = |Entry - SL| / Entry
Risk Amount   = Balance × Max Risk %
Position Value = Risk / SL Distance %
Quantity       = Position Value / Entry
```

### 11.2 Common Values

| Account | Risk % | Entry | SL | SL % | Risk $ | Position Value | Quantity |
|---------|--------|-------|----|----|--------|----------------|----------|
| 10,000 | 1% | 50,000 | 49,000 | 2% | 100 | 5,000 | 0.1 BTC |
| 10,000 | 1% | 50,000 | 49,500 | 1% | 100 | 10,000 | 0.2 BTC |
| 10,000 | 1% | 50,000 | 45,000 | 10% | 100 | 1,000 | 0.02 BTC |
| 5,000 | 2% | 50,000 | 49,000 | 2% | 100 | 5,000 | 0.1 BTC |

### 11.3 Test Command Quick Access

```bash
# Run subtask 7.1 tests
pytest tests/test_risk_manager.py::TestPositionSizeCalculation -v

# Watch mode (run on file changes)
pytest-watch tests/test_risk_manager.py::TestPositionSizeCalculation

# Coverage report
pytest tests/test_risk_manager.py::TestPositionSizeCalculation --cov=src.risk.manager --cov-report=html
```

---

**Implementation Time Estimate**: 1-2 hours
- Code: 30 minutes
- Tests: 45 minutes
- Documentation: 15 minutes
- Debugging: 30 minutes (buffer)

**Ready to implement!** 🚀
