# Task 7.3: Risk/Reward Ratio & Position Size Limiting Design

## Overview

Design specification for implementing risk/reward ratio access and maximum position size limiting in RiskManager.

## Design Discovery

### Existing Implementation in Signal Model

**Good News:** Signal model already implements risk/reward calculation!

```python
# src/models/signal.py:65-80
@property
def risk_amount(self) -> float:
    """Risk per unit (entry - stop_loss)."""
    return abs(self.entry_price - self.stop_loss)

@property
def reward_amount(self) -> float:
    """Reward per unit (take_profit - entry)."""
    return abs(self.take_profit - self.entry_price)

@property
def risk_reward_ratio(self) -> float:
    """Risk-to-reward ratio (reward / risk)."""
    if self.risk_amount == 0:
        return 0.0
    return self.reward_amount / self.risk_amount
```

**Implication:** RiskManager doesn't need to duplicate this logic. Can simply access `signal.risk_reward_ratio` when needed.

## Architecture

### Component Design

```
┌─────────────────────────────────────────────────────────────┐
│                      RiskManager                             │
├─────────────────────────────────────────────────────────────┤
│ - max_risk_per_trade: float                                 │
│ - max_leverage: int                                          │
│ - max_position_size_percent: float  [NEW USAGE]             │
├─────────────────────────────────────────────────────────────┤
│ + calculate_position_size(...) -> float      [MODIFY 7.3]  │
│   └─> Add position size limiting logic                      │
│ + validate_risk(signal, position) -> bool    [✅ Task 7.2]  │
└─────────────────────────────────────────────────────────────┘
                        │
                        │ uses
                        ▼
        ┌───────────────────────────────┐
        │         Signal                │
        ├───────────────────────────────┤
        │ @property risk_reward_ratio   │  [Already exists!]
        │ @property risk_amount         │
        │ @property reward_amount       │
        └───────────────────────────────┘
```

## Implementation Specification

### Part 1: Risk/Reward Ratio Access (Simplified)

**Decision:** No new method needed in RiskManager

**Rationale:**
- Signal already provides `risk_reward_ratio` property
- RiskManager can access it via `signal.risk_reward_ratio`
- Follows DRY principle (Don't Repeat Yourself)
- Task requirement satisfied by existing implementation

**Usage Example:**
```python
# In RiskManager or TradingEngine:
ratio = signal.risk_reward_ratio
if ratio < 1.5:
    logger.warning(f"Low R:R ratio: {ratio:.2f}")
```

**Task 7.3 Scope Adjustment:**
- ~~Create calculate_risk_reward_ratio() method~~ (Not needed)
- ✅ Document that Signal provides this functionality
- ✅ Add tests to verify Signal.risk_reward_ratio works correctly

### Part 2: Position Size Limiting (Primary Focus)

**Objective:** Limit calculated position size to maximum allowed percentage of account

**Location:** Modify `calculate_position_size()` in `src/risk/manager.py`

**Current Flow:**
```
Step 1-3: Input validation and SL distance calculation
Step 4-5: Calculate risk-based position size
Step 6: Log calculation details
Step 7: Return quantity
```

**New Flow:**
```
Step 1-3: Input validation and SL distance calculation
Step 4-5: Calculate risk-based position size
Step 6: Calculate maximum allowed position size      [NEW]
Step 7: Apply limit if needed (with warning log)     [NEW]
Step 8: Log final calculation details                [MODIFIED]
Step 9: Return limited quantity                      [MODIFIED]
```

### Position Size Limiting Logic

**Formula:**
```python
# Maximum position value based on account percentage and leverage
max_position_value = account_balance * max_position_size_percent * leverage

# Convert to quantity
max_quantity = max_position_value / entry_price

# Apply limit
if quantity > max_quantity:
    quantity = max_quantity  # Cap to maximum
```

**Example Calculation:**
```python
# Given:
account_balance = 10,000 USDT
max_position_size_percent = 0.1  # 10%
leverage = 10
entry_price = 50,000

# Calculate max:
max_position_value = 10,000 * 0.1 * 10 = 10,000 USDT
max_quantity = 10,000 / 50,000 = 0.2 BTC

# If risk-based calculation gave 0.5 BTC:
# Final quantity = min(0.5, 0.2) = 0.2 BTC (limited)
```

### Code Implementation

**Insert after Step 5 (line ~103 in current code):**

```python
# Step 6: Calculate maximum position size
max_position_value = account_balance * self.max_position_size_percent * leverage
max_quantity = max_position_value / entry_price

# Step 7: Apply position size limit
if quantity > max_quantity:
    self.logger.warning(
        f"Position size {quantity:.4f} exceeds maximum {max_quantity:.4f} "
        f"({self.max_position_size_percent:.1%} of account with {leverage}x leverage), "
        f"capping to {max_quantity:.4f}"
    )
    quantity = max_quantity

# Step 8: Log final calculation details
self.logger.info(
    f"Position size calculated: {quantity:.4f} "
    f"(risk={risk_amount:.2f} USDT, "
    f"SL distance={sl_distance_percent:.2%}, "
    f"max_allowed={max_quantity:.4f})"
)

# Step 9: Return limited quantity
# Note: Rounding will be added in subtask 7.4
return quantity
```

## Validation Rules

### Rule 1: Maximum Position Size Constraint

**Formula:**
```
Max Position = Account Balance × max_position_size_percent × Leverage
```

**Default:** 10% of account balance per position

**Rationale:**
- Prevents over-concentration in single position
- Limits exposure to single trade
- Allows portfolio diversification
- Protects against catastrophic losses

**Examples:**

| Account | Max % | Leverage | Entry | Max Position | Max Quantity |
|---------|-------|----------|-------|--------------|--------------|
| 10,000  | 10%   | 10x      | 50,000| 10,000 USDT  | 0.2 BTC      |
| 10,000  | 10%   | 20x      | 50,000| 20,000 USDT  | 0.4 BTC      |
| 20,000  | 10%   | 10x      | 50,000| 20,000 USDT  | 0.4 BTC      |
| 10,000  | 5%    | 10x      | 50,000| 5,000 USDT   | 0.1 BTC      |

### Rule 2: Limiting Behavior

**Condition:** `calculated_quantity > max_quantity`

**Action:**
1. Cap quantity to max_quantity
2. Log warning with both values
3. Return capped quantity

**Log Message Format:**
```
"Position size {original:.4f} exceeds maximum {max:.4f}
({percent:.1%} of account with {leverage}x leverage),
capping to {max:.4f}"
```

**Example:**
```
"Position size 0.5000 exceeds maximum 0.2000
(10.0% of account with 10x leverage),
capping to 0.2000"
```

## Test Strategy

### Test Coverage Matrix

| Test Case | Account | Risk % | SL Dist | Leverage | Expected | Limit? |
|-----------|---------|--------|---------|----------|----------|--------|
| 1. Within limit | 10,000 | 1% | 2% | 10x | 0.1 BTC | No |
| 2. Tight SL exceeds | 10,000 | 1% | 0.1% | 10x | 0.2 BTC (capped) | Yes |
| 3. High leverage | 10,000 | 1% | 1% | 20x | 0.4 BTC (capped) | Yes |
| 4. Low max percent | 10,000 | 1% | 1% | 10x (5% max) | 0.05 BTC (capped) | Yes |
| 5. Warning logged | Any | - | - | - | Check log | - |
| 6. Max respects leverage | 10,000 | - | - | Various | Scale with leverage | - |

### Test Implementation

```python
class TestPositionSizeLimiting:
    """Test suite for subtask 7.3 - Position size limiting"""

    @pytest.fixture
    def risk_manager(self):
        """Setup RiskManager with standard config"""
        config = {
            'max_risk_per_trade': 0.01,
            'max_leverage': 20,
            'default_leverage': 10,
            'max_position_size_percent': 0.1  # 10%
        }
        return RiskManager(config)

    def test_position_within_limit_not_capped(self, risk_manager):
        """
        Normal case: Position size within limit is not capped

        Risk-based: 0.1 BTC
        Max (10% × 10x): 0.2 BTC
        Result: 0.1 BTC (not limited)
        """
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49000,  # 2% SL
            leverage=10
        )

        # Should not be limited
        assert quantity == pytest.approx(0.1, rel=0.01)

    def test_tight_sl_exceeds_limit_capped(self, risk_manager, caplog):
        """
        Edge case: Tight SL creates large position that exceeds limit

        Risk-based: 2.0 BTC (from 0.1% tight SL)
        Max (10% × 10x): 0.2 BTC
        Result: 0.2 BTC (capped)
        """
        with caplog.at_level(logging.WARNING):
            quantity = risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49950,  # 0.1% tight SL
                leverage=10
            )

        # Should be capped to max
        max_quantity = 10000 * 0.1 * 10 / 50000  # 0.2 BTC
        assert quantity == pytest.approx(max_quantity, rel=0.01)

        # Check warning logged
        assert "exceeds maximum" in caplog.text
        assert "capping to" in caplog.text

    def test_high_leverage_increases_max_limit(self, risk_manager):
        """
        Max position size scales with leverage

        Leverage 10x: Max = 0.2 BTC
        Leverage 20x: Max = 0.4 BTC
        """
        # With 10x leverage
        max_10x = 10000 * 0.1 * 10 / 50000  # 0.2 BTC

        # With 20x leverage
        max_20x = 10000 * 0.1 * 20 / 50000  # 0.4 BTC

        assert max_20x == 2 * max_10x

    def test_custom_max_position_percent(self):
        """
        Custom max_position_size_percent is respected

        5% max instead of 10%
        """
        manager = RiskManager({
            'max_risk_per_trade': 0.01,
            'max_position_size_percent': 0.05  # 5%
        })

        quantity = manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49500,  # Tight SL to trigger limit
            leverage=10
        )

        # Max with 5%: 10000 * 0.05 * 10 / 50000 = 0.1 BTC
        assert quantity <= 0.1

    def test_warning_contains_specific_values(self, risk_manager, caplog):
        """
        Warning log contains actual calculated and max values
        """
        with caplog.at_level(logging.WARNING):
            risk_manager.calculate_position_size(
                account_balance=10000,
                entry_price=50000,
                stop_loss_price=49950,  # Tight SL
                leverage=10
            )

        # Check log contains specific values
        assert "0.2" in caplog.text  # Max quantity
        assert "10.0%" in caplog.text or "10%" in caplog.text  # Percentage

    def test_integration_full_calculation_with_limiting(self, risk_manager):
        """
        Integration test: Full position calculation with limiting

        Verifies entire flow from input to limited output
        """
        # Scenario: Very tight SL (0.05%) should trigger limit
        quantity = risk_manager.calculate_position_size(
            account_balance=10000,
            entry_price=50000,
            stop_loss_price=49975,  # 0.05% SL
            leverage=10
        )

        # Max allowed: 0.2 BTC
        max_quantity = 0.2

        # Should be capped
        assert quantity == pytest.approx(max_quantity, rel=0.01)

        # Should be less than uncapped calculation
        # Risk-based would give: 100 / 0.0005 / 50000 = 4.0 BTC
        assert quantity < 4.0
```

### Signal Risk/Reward Ratio Tests

```python
class TestSignalRiskRewardRatio:
    """Test suite for Signal.risk_reward_ratio property (verification)"""

    def test_risk_reward_ratio_1_to_2(self):
        """
        R:R ratio 1:2 correctly calculated

        Entry: 50,000
        SL: 49,000 (1,000 risk)
        TP: 52,000 (2,000 reward)
        R:R: 2,000 / 1,000 = 2.0
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=49000,  # 1,000 risk
            take_profit=52000,  # 2,000 reward
            strategy_name="test",
            timestamp=datetime.now()
        )

        assert signal.risk_reward_ratio == pytest.approx(2.0, rel=0.01)

    def test_risk_reward_ratio_zero_risk_returns_zero(self):
        """
        Zero risk returns 0.0 (division by zero handling)
        """
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            stop_loss=50000,  # Zero risk (same as entry)
            take_profit=51000,
            strategy_name="test",
            timestamp=datetime.now()
        )

        # Note: Signal.__post_init__ will raise ValueError
        # This test verifies the property logic handles zero risk
        # May need to use object.__setattr__ for testing
```

## Integration Points

### Upstream Dependencies
- Task 7.1: calculate_position_size() base implementation ✅
- Signal.risk_reward_ratio property (already exists)

### Downstream Impact
- Task 7.4: Quantity rounding will apply AFTER limiting
- TradingEngine: Can use signal.risk_reward_ratio for signal filtering

### Configuration
```python
config = {
    'max_risk_per_trade': 0.01,          # 1% risk per trade
    'max_leverage': 20,                  # Maximum leverage allowed
    'default_leverage': 10,              # Default leverage
    'max_position_size_percent': 0.1     # 10% max position size [USED HERE]
}
```

## Edge Cases & Considerations

### 1. Leverage Impact on Max Position

**Observation:** Max position scales linearly with leverage

```python
# 10x leverage: Max = 10,000 * 0.1 * 10 = 10,000 USDT (0.2 BTC @ 50k)
# 20x leverage: Max = 10,000 * 0.1 * 20 = 20,000 USDT (0.4 BTC @ 50k)
```

**Rationale:** Higher leverage → more capital efficiency → larger positions allowed

### 2. Relationship Between Risk-Based and Max-Based Sizing

**Scenarios:**

| Risk % | SL Distance | Risk-Based Size | Max Size | Final Size | Constraint |
|--------|-------------|-----------------|----------|------------|------------|
| 1%     | 2%          | 0.1 BTC         | 0.2 BTC  | 0.1 BTC    | Risk-based |
| 1%     | 0.1%        | 2.0 BTC         | 0.2 BTC  | 0.2 BTC    | Max-based  |
| 2%     | 2%          | 0.2 BTC         | 0.2 BTC  | 0.2 BTC    | Equal      |
| 0.5%   | 2%          | 0.05 BTC        | 0.2 BTC  | 0.05 BTC   | Risk-based |

**Insight:**
- Normal SL distances (1-5%) → Risk-based constraint dominates
- Tight SL distances (<0.5%) → Max-based constraint dominates

### 3. Signal.risk_reward_ratio Already Handles Zero Risk

**Code Review:**
```python
@property
def risk_reward_ratio(self) -> float:
    if self.risk_amount == 0:
        return 0.0  # Safe handling
    return self.reward_amount / self.risk_amount
```

**No Additional Work Needed:** Signal model already handles edge case correctly

### 4. Order of Operations

**Correct Flow:**
```
1. Calculate risk-based position size
2. Apply max position size limit
3. Apply lot size rounding (Task 7.4)
4. Return final quantity
```

**Rationale:** Limiting before rounding ensures we don't exceed max after rounding up

## Success Criteria

✅ **Implementation Complete When:**
1. Position size limiting added to calculate_position_size()
2. Warning logged when position is capped
3. Max position respects leverage parameter
4. All 6+ test cases pass
5. Documentation updated

✅ **Code Quality:**
- Clear step numbers in implementation
- Informative warning log with actual values
- No duplicate R:R ratio logic (use Signal property)

✅ **Integration:**
- Works seamlessly with Task 7.1 base calculation
- Prepares for Task 7.4 rounding

## References

- Task 7.3 specification: `.taskmaster/tasks/task-7.3.md`
- Signal model: `src/models/signal.py:20-81`
- RiskManager: `src/risk/manager.py:10-165`
- Existing calculate_position_size: `src/risk/manager.py:35-114`
