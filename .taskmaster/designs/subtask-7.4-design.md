# Task 7.4: Quantity Rounding Design Document

## Overview

Design and implementation specification for lot size rounding logic in RiskManager class to ensure calculated position quantities comply with Binance Futures symbol specifications.

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
│ + validate_risk(signal, position) -> bool       [✅ Task 7.2]│
│ + _round_to_lot_size(qty, info) -> float        [🔄 Task 7.4]│
└─────────────────────────────────────────────────────────────┘
                        │
                        │ uses symbol specs from
                        ▼
        ┌───────────────────────────────┐
        │   Binance Exchange Info       │
        ├───────────────────────────────┤
        │ symbols[].filters[]           │
        │   - LOT_SIZE filter           │
        │     * minQty: "0.001"         │
        │     * maxQty: "1000"          │
        │     * stepSize: "0.001"       │
        │   - quantityPrecision: 3      │
        └───────────────────────────────┘
```

## Method Specification

### _round_to_lot_size()

**Signature:**
```python
def _round_to_lot_size(
    self,
    quantity: float,
    symbol_info: Optional[dict] = None
) -> float
```

**Purpose:**
Round calculated position quantity to comply with Binance symbol specifications for lot size (stepSize) and quantity precision.

**Parameters:**
- `quantity`: float - Raw calculated position size from risk calculation
- `symbol_info`: Optional[dict] - Exchange symbol specifications containing:
  - `lot_size` (float): Minimum quantity increment (stepSize from LOT_SIZE filter)
  - `quantity_precision` (int): Decimal places for rounding (quantityPrecision from symbol)

**Returns:**
- `float`: Rounded quantity compliant with Binance specifications

**Side Effects:**
- Logs rounding operations at DEBUG level

## Rounding Logic

### Two-Stage Rounding Process

```
Input Quantity
    │
    ├─► Stage 1: Lot Size Flooring
    │   └─► quantity - (quantity % lot_size)
    │       └─► Removes fractional lot sizes (floors to nearest valid increment)
    │
    ├─► Stage 2: Precision Rounding
    │   └─► round(floored_quantity, quantity_precision)
    │       └─► Applies decimal precision constraint
    │
    └─► Final Quantity (Binance-compliant)
```

### Formula

```python
# Stage 1: Floor to lot size
floored_quantity = quantity - (quantity % lot_size)

# Stage 2: Round to precision
final_quantity = round(floored_quantity, quantity_precision)
```

### Why Two Stages?

1. **Stage 1 (Lot Size Flooring)**: Ensures quantity is a multiple of `stepSize`
   - Binance rejects orders where `quantity % stepSize != 0`
   - Uses modulo to find remainder and subtracts it (floors)

2. **Stage 2 (Precision Rounding)**: Ensures correct decimal places
   - Binance rejects orders with excess decimal precision
   - Python's `round()` function ensures exact decimal count

## Symbol Info Structure

### Input Format

```python
symbol_info = {
    'lot_size': 0.001,           # From LOT_SIZE filter stepSize
    'quantity_precision': 3       # From symbol quantityPrecision
}
```

### Binance Exchange Info Mapping

**Source: `/fapi/v1/exchangeInfo` Response**

```json
{
  "symbols": [
    {
      "symbol": "BTCUSDT",
      "quantityPrecision": 3,
      "filters": [
        {
          "filterType": "LOT_SIZE",
          "minQty": "0.001",
          "maxQty": "1000",
          "stepSize": "0.001"
        }
      ]
    }
  ]
}
```

**Mapping:**
- `symbol_info['lot_size']` ← `filters[LOT_SIZE].stepSize` (converted to float)
- `symbol_info['quantity_precision']` ← `quantityPrecision` (int)

### Default Values

When `symbol_info` is None or missing keys:
- `lot_size`: 0.001 (BTCUSDT default)
- `quantity_precision`: 3 (BTCUSDT default)

**Rationale:** BTCUSDT is the most common trading pair, providing safe defaults.

## Implementation Details

### Method Location

**File:** `src/risk/manager.py`
**Class:** `RiskManager`
**Visibility:** Private (leading underscore)

### Code Structure

```python
def _round_to_lot_size(
    self,
    quantity: float,
    symbol_info: Optional[dict] = None
) -> float:
    """
    Round quantity to Binance lot size and precision specifications.

    Applies two-stage rounding:
    1. Floor to nearest lot size (stepSize) multiple
    2. Round to required decimal precision

    Args:
        quantity: Raw calculated position size
        symbol_info: Optional dict with 'lot_size' and 'quantity_precision'

    Returns:
        Binance-compliant rounded quantity

    Example:
        >>> manager._round_to_lot_size(1.2345, {'lot_size': 0.001, 'quantity_precision': 3})
        1.234

        >>> manager._round_to_lot_size(0.0567, {'lot_size': 0.01, 'quantity_precision': 2})
        0.05
    """
    # Step 1: Extract specs with defaults
    if symbol_info is None:
        symbol_info = {}

    lot_size = symbol_info.get('lot_size', 0.001)
    quantity_precision = symbol_info.get('quantity_precision', 3)

    # Step 2: Floor to lot size
    floored = quantity - (quantity % lot_size)

    # Step 3: Round to precision
    rounded = round(floored, quantity_precision)

    # Step 4: Log operation (debug)
    self.logger.debug(
        f"Quantity rounding: {quantity:.6f} → {rounded} "
        f"(lot_size={lot_size}, precision={quantity_precision})"
    )

    return rounded
```

### Integration in calculate_position_size()

**Current Code (End of Task 7.3):**
```python
# Step 9: Return limited quantity
# Note: Rounding will be added in subtask 7.4
return quantity
```

**Updated Code (Task 7.4):**
```python
# Step 9: Round to symbol specifications
if symbol_info is not None:
    quantity = self._round_to_lot_size(quantity, symbol_info)
else:
    # Default rounding for backward compatibility
    quantity = round(quantity, 3)

# Step 10: Log final quantity
self.logger.info(
    f"Final position size: {quantity} "
    f"(after rounding with lot_size={symbol_info.get('lot_size', 0.001) if symbol_info else 0.001})"
)

return quantity
```

**Step Renumbering:**
- Previous Step 9 → Split into Step 9 (rounding) and Step 10 (final logging)

## Test Strategy

### Test Coverage Matrix

| Test Case | Input Quantity | lot_size | precision | Expected Output | Validation |
|-----------|---------------|----------|-----------|-----------------|------------|
| 1 | 1.2345 | 0.001 | 3 | 1.234 | Standard rounding |
| 2 | 0.0567 | 0.01 | 2 | 0.05 | Lot size flooring dominates |
| 3 | 0.0567 | 0.001 | 3 | 0.056 | Precision rounding |
| 4 | 1.9999 | 0.001 | 3 | 1.999 | No upward rounding to 2.0 |
| 5 | 0.001 | 0.001 | 3 | 0.001 | Minimum lot size |
| 6 | 1.2345 | None | None | 1.234 | Default values (missing info) |
| 7 | 1.2345 | N/A | N/A | 1.235 | No symbol_info (legacy path) |

### Test Implementation

```python
class TestQuantityRounding:
    """Test suite for subtask 7.4 - Quantity rounding"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager with standard config"""
        config = {
            'max_risk_per_trade': 0.01,
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1
        }
        return RiskManager(config)

    def test_standard_rounding_btcusdt(self, risk_manager):
        """Standard case: 1.2345 BTC with BTCUSDT specs → 1.234"""
        symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
        result = risk_manager._round_to_lot_size(1.2345, symbol_info)
        assert result == pytest.approx(1.234, abs=1e-9)

    def test_lot_size_flooring(self, risk_manager):
        """Lot size flooring: 0.0567 with stepSize=0.01 → 0.05"""
        symbol_info = {'lot_size': 0.01, 'quantity_precision': 2}
        result = risk_manager._round_to_lot_size(0.0567, symbol_info)
        assert result == pytest.approx(0.05, abs=1e-9)

    def test_precision_dominates(self, risk_manager):
        """Precision rounding: 0.0567 with fine lot_size → 0.056"""
        symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
        result = risk_manager._round_to_lot_size(0.0567, symbol_info)
        assert result == pytest.approx(0.056, abs=1e-9)

    def test_no_upward_rounding(self, risk_manager):
        """1.9999 should NOT round up to 2.0, floors to 1.999"""
        symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
        result = risk_manager._round_to_lot_size(1.9999, symbol_info)
        assert result == pytest.approx(1.999, abs=1e-9)

    def test_minimum_lot_size(self, risk_manager):
        """0.001 BTC (minimum) should remain 0.001"""
        symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
        result = risk_manager._round_to_lot_size(0.001, symbol_info)
        assert result == pytest.approx(0.001, abs=1e-9)

    def test_missing_symbol_info_uses_defaults(self, risk_manager):
        """Missing symbol_info uses BTCUSDT defaults (0.001, 3)"""
        result = risk_manager._round_to_lot_size(1.2345, None)
        assert result == pytest.approx(1.234, abs=1e-9)

    def test_partial_symbol_info(self, risk_manager):
        """Partial symbol_info fills missing values with defaults"""
        # Only lot_size provided, precision defaults to 3
        symbol_info = {'lot_size': 0.01}
        result = risk_manager._round_to_lot_size(1.2345, symbol_info)
        assert result == pytest.approx(1.230, abs=1e-9)  # lot_size=0.01 dominates

    def test_integration_with_calculate_position_size(self, risk_manager):
        """Full integration: calculate → limit → round"""
        symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}

        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,  # 2% SL
            leverage=10,
            symbol_info=symbol_info
        )

        # Verify quantity is Binance-compliant
        # 1. Check precision (exactly 3 decimals)
        assert len(str(quantity).split('.')[1]) <= 3

        # 2. Check lot_size compliance (multiple of 0.001)
        assert (quantity % 0.001) < 1e-9

    def test_ethusdt_specs(self, risk_manager):
        """Real-world: ETHUSDT (lot_size=0.001, precision=3)"""
        symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
        result = risk_manager._round_to_lot_size(12.3456, symbol_info)
        assert result == pytest.approx(12.345, abs=1e-9)

    def test_bnbusdt_specs(self, risk_manager):
        """Real-world: BNBUSDT (lot_size=0.01, precision=2)"""
        symbol_info = {'lot_size': 0.01, 'quantity_precision': 2}
        result = risk_manager._round_to_lot_size(49.876, symbol_info)
        assert result == pytest.approx(49.87, abs=1e-9)

    def test_no_symbol_info_legacy_rounding(self, risk_manager):
        """Legacy behavior: No symbol_info → round(qty, 3)"""
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,
            leverage=10,
            symbol_info=None  # No symbol info
        )

        # Should use default round(qty, 3)
        assert len(str(quantity).split('.')[1]) <= 3
```

## Edge Cases & Considerations

### 1. Zero Lot Size

**Issue:** `lot_size = 0` causes division by zero in modulo

**Mitigation:** Set minimum `lot_size = 0.001` in defaults

**Test:**
```python
def test_zero_lot_size_fallback(self, risk_manager):
    symbol_info = {'lot_size': 0, 'quantity_precision': 3}
    result = risk_manager._round_to_lot_size(1.2345, symbol_info)
    # Should fallback to default 0.001
    assert result == pytest.approx(1.234, abs=1e-9)
```

### 2. Negative Quantity

**Issue:** Negative quantities are invalid for position sizing

**Mitigation:** calculate_position_size() already validates positive values (Task 7.1)

**Assumption:** _round_to_lot_size() assumes positive inputs

### 3. Extremely Large Precision

**Issue:** `quantity_precision > 8` may exceed Python float precision

**Mitigation:** Binance typically uses precision ≤ 8 (BTC: 8 decimals)

**Handling:** Trust Python's round() for precision ≤ 8

### 4. Lot Size Larger Than Quantity

**Issue:** `quantity = 0.0005, lot_size = 0.001` → `floored = 0.0`

**Behavior:** Returns 0.0 (below minimum tradeable)

**Resolution:** Caller (TradingEngine) should check minimum quantity requirements

### 5. Backward Compatibility

**Issue:** Existing code calls `calculate_position_size()` without `symbol_info`

**Solution:** Default rounding path: `round(quantity, 3)` when `symbol_info is None`

**Test:** Verify legacy behavior preserved

## Integration Points

### Upstream Dependencies
- Task 7.1: calculate_position_size() provides raw quantity
- Task 7.3: Position size limiting occurs before rounding

### Downstream Usage
- TradingEngine: Passes symbol_info from OrderExecutionManager
- OrderExecutionManager: Provides symbol_info from exchange_info cache

### Related Components
- OrderExecutionManager._format_price(): Similar pattern for price formatting
- OrderExecutionManager._get_tick_size(): Fetches tick size for price rounding

### Data Flow

```
TradingEngine
    │
    ├─► OrderExecutionManager.get_symbol_info(symbol)
    │   └─► Fetch from exchange_info cache
    │       └─► Extract lot_size, quantity_precision
    │
    ├─► RiskManager.calculate_position_size(..., symbol_info)
    │   ├─► Step 1-8: Risk calculation + limiting (Tasks 7.1-7.3)
    │   └─► Step 9: _round_to_lot_size(quantity, symbol_info)
    │       └─► Returns Binance-compliant quantity
    │
    └─► OrderExecutionManager.execute_signal(signal, quantity)
        └─► Quantity accepted by Binance API ✅
```

## Performance Considerations

### Computational Complexity
- **Time:** O(1) - Simple arithmetic operations
- **Space:** O(1) - No additional data structures

### Logging Impact
- DEBUG-level logging only (disabled in production)
- No performance impact with proper log level configuration

## Success Criteria

✅ **Implementation Complete When:**
1. _round_to_lot_size() method implemented with two-stage rounding
2. Integration in calculate_position_size() with symbol_info parameter
3. All 12 test cases pass
4. Code coverage ≥ 95% for _round_to_lot_size() method
5. Legacy behavior preserved (no symbol_info → round(qty, 3))

✅ **Code Quality:**
- Clear docstrings with examples
- DEBUG-level logging for troubleshooting
- Handles missing/partial symbol_info gracefully
- Consistent with OrderExecutionManager._format_price() pattern

✅ **Documentation:**
- Design document complete (this file)
- Method docstring with formula explanation
- Test docstrings describing scenarios
- Integration notes for TradingEngine

## References

### Binance API Documentation
- **Exchange Info Endpoint:** `/fapi/v1/exchangeInfo`
- **LOT_SIZE Filter:** Defines minQty, maxQty, stepSize
- **quantityPrecision:** Maximum decimal places for quantity

### Related Implementation
- Task 7.1: `src/risk/manager.py:35-128` (calculate_position_size)
- Task 7.3: `src/risk/manager.py:105-116` (position size limiting)
- Task 6.5: `src/execution/order_manager.py:424-463` (_format_price pattern)

### Test File
- Location: `tests/test_risk_manager.py`
- New Class: `TestQuantityRounding` (12 tests)
- Coverage Target: 95%+

---

**Design Status:** ✅ Complete - Ready for Implementation
**Dependencies:** Tasks 7.1, 7.3 (completed)
**Next Step:** `/sc:implement --c7 --serena`
