# Task 7: Risk Management Module - Architectural Design

**Design Date**: 2025-12-17
**Author**: Claude (Sonnet 4.5)
**Status**: Design Phase
**Dependencies**: Task 2 (Signal Processing), Task 6 (Order Manager)

---

## 1. Executive Summary

The Risk Management Module is a **safety-critical component** responsible for protecting capital through intelligent position sizing and validation. It translates trading signals into exchange-compliant order quantities while enforcing risk limits.

**Key Responsibilities**:
- Calculate position sizes based on account balance and risk percentage
- Validate signal correctness (TP/SL placement logic)
- Enforce maximum position size and leverage limits
- Round quantities to Binance exchange specifications

**Design Philosophy**: **Fail-safe by default** - Invalid signals are rejected early, position sizes are capped conservatively, and all decisions are logged for auditability.

---

## 2. System Context

### 2.1 Integration Points

```
┌─────────────────┐
│ Signal Pipeline │
│   (Task 2)      │
└────────┬────────┘
         │ Signal
         ↓
┌─────────────────┐     ┌──────────────────┐
│  RiskManager    │────→│ OrderExecution   │
│   (Task 7)      │     │   Manager        │
│                 │     │   (Task 6)       │
└────────┬────────┘     └──────────────────┘
         │
         ↓
┌─────────────────┐
│ Binance API     │
│ (Position/      │
│  Account Info)  │
└─────────────────┘
```

**Input**: `Signal` objects with entry price, TP, SL, symbol
**Output**: Validated position quantity (float) or rejection (ValidationError)
**Dependencies**:
- `OrderExecutionManager` for account balance and position queries
- `Signal` and `Position` models from Task 6
- Binance exchange info (tick sizes, precision)

### 2.2 Data Flow

```
1. Signal Generated → RiskManager.validate_signal()
   ├─ Check TP/SL correctness
   ├─ Check position conflicts
   └─ Return True/False

2. If valid → RiskManager.calculate_position_size()
   ├─ Query account balance
   ├─ Calculate risk amount (balance × risk%)
   ├─ Calculate SL distance percentage
   ├─ Derive quantity: risk_amount / (sl_distance% × entry_price)
   ├─ Apply max position size limit
   ├─ Round to exchange lot size
   └─ Return quantity

3. If invalid → Log rejection reason, skip execution
```

---

## 3. Architecture Design

### 3.1 Class Structure

```python
class RiskManager:
    """
    Capital protection through position sizing and signal validation.

    Design Principles:
    - Immutable configuration (set once at initialization)
    - Pure calculation functions (no side effects)
    - Explicit error handling with typed exceptions
    - Defensive programming (validate all inputs)
    - Comprehensive logging for auditability
    """

    # Configuration (immutable after __init__)
    max_risk_per_trade: float      # 0.01 = 1% of account
    max_leverage: int               # 20x maximum
    default_leverage: int           # 10x standard
    max_position_size_percent: float # 0.1 = 10% of account

    # Runtime state
    logger: logging.Logger
    _order_manager: OrderExecutionManager  # For balance/position queries

    # Core Methods (pure functions)
    def calculate_position_size(...) -> float
    def validate_signal(...) -> bool
    def calculate_risk_reward_ratio(...) -> float

    # Helper Methods (private)
    def _round_to_lot_size(...) -> float
    def _get_account_balance() -> float
    def _get_current_position(...) -> Optional[Position]
```

### 3.2 Configuration Design

**Rationale**: Risk parameters should be **conservative by default** and configurable via INI file for flexibility without code changes.

```ini
# trading_config.ini
[risk]
# Core Risk Parameters
max_risk_per_trade = 0.01        # 1% of account per trade
max_leverage = 20                 # Maximum allowed leverage
default_leverage = 10             # Standard leverage for most trades
max_position_size_percent = 0.1   # 10% of account max position value

# Validation Settings
allow_concurrent_positions = false  # Reject signals if position exists
min_risk_reward_ratio = 1.0        # Minimum 1:1 R:R required
min_sl_distance_percent = 0.001    # Minimum 0.1% SL distance
```

**Loading Pattern** (from Task 6):
```python
from src.utils.config import load_config

config = load_config('trading_config.ini')
risk_manager = RiskManager(config['risk'])
```

---

## 4. Position Sizing Algorithm

### 4.1 Mathematical Foundation

**Kelly Criterion Influence**: The position sizing formula is inspired by the Kelly Criterion but uses a **fixed fractional approach** for consistency and simplicity.

**Core Formula**:
```
Risk Amount (USDT) = Account Balance × Max Risk Per Trade (%)
SL Distance (%)     = |Entry Price - Stop Loss Price| / Entry Price
Position Value      = Risk Amount / SL Distance (%)
Quantity (units)    = Position Value / Entry Price
```

**Example Calculation**:
```
Account Balance: 10,000 USDT
Max Risk: 1% = 100 USDT
Entry Price: 50,000 USDT (BTCUSDT)
Stop Loss: 49,000 USDT
SL Distance: (50,000 - 49,000) / 50,000 = 2%

Position Value: 100 / 0.02 = 5,000 USDT
Quantity: 5,000 / 50,000 = 0.1 BTC
```

### 4.2 Position Size Limiting

**Multiple Layers of Protection**:

1. **Risk-Based Limit**: Calculated from SL distance (primary)
2. **Max Position Value Limit**: `account_balance × max_position_size_percent × leverage`
3. **Lot Size Compliance**: Round down to Binance's lot size specification

**Implementation**:
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
    Calculate position size with multiple safety limits.

    Layers of protection:
    1. Risk-based calculation (primary)
    2. Maximum position value enforcement
    3. Lot size rounding (exchange compliance)

    Returns:
        Position size in base asset units (e.g., BTC for BTCUSDT)

    Raises:
        ValueError: Invalid inputs (zero SL distance, negative values)
    """
    # Layer 1: Risk-based calculation
    sl_distance_percent = abs(entry_price - stop_loss_price) / entry_price

    if sl_distance_percent == 0:
        self.logger.warning("Zero SL distance, using minimum 0.1%")
        sl_distance_percent = 0.001  # Minimum threshold

    risk_amount = account_balance * self.max_risk_per_trade
    position_value = risk_amount / sl_distance_percent
    quantity = position_value / entry_price

    # Layer 2: Maximum position size enforcement
    max_position_value = account_balance * self.max_position_size_percent * leverage
    max_quantity = max_position_value / entry_price

    if quantity > max_quantity:
        self.logger.warning(
            f"Position size capped: {quantity:.4f} → {max_quantity:.4f} "
            f"(max {self.max_position_size_percent*100}% of account)"
        )
        quantity = max_quantity

    # Layer 3: Lot size rounding
    if symbol_info:
        quantity = self._round_to_lot_size(quantity, symbol_info)
    else:
        quantity = round(quantity, 3)  # Default precision

    self.logger.info(
        f"Position size: {quantity} (risk={risk_amount:.2f} USDT, "
        f"SL distance={sl_distance_percent:.2%})"
    )

    return quantity
```

### 4.3 Edge Cases & Handling

| Edge Case | Detection | Handling | Rationale |
|-----------|-----------|----------|-----------|
| Zero SL distance | `sl_distance == 0` | Use 0.1% minimum | Prevent division by zero, force minimum risk buffer |
| Tight SL (<0.1%) | `sl_distance < 0.001` | Allow but log warning | May indicate scalping strategy, allow with caution |
| Wide SL (>10%) | `sl_distance > 0.1` | Allow but cap position size | Large SL naturally reduces position size via formula |
| Negative prices | `entry_price <= 0` or `stop_loss_price <= 0` | Raise ValueError | Invalid input data |
| Position size too small | `quantity < min_lot_size` | Log warning, return 0 | Avoid dust orders rejected by exchange |

---

## 5. Signal Validation Design

### 5.1 Validation Rules

**Critical Principle**: **Validate once, validate thoroughly**. All checks happen before any calculations to fail fast.

```python
def validate_signal(
    self,
    signal: Signal,
    current_position: Optional[Position] = None
) -> bool:
    """
    Validate signal for risk rule compliance.

    Validation Rules:
    1. No concurrent positions (if configured)
    2. TP/SL correctness for signal type
    3. Minimum R:R ratio (if configured)
    4. Reasonable SL distance

    Returns:
        True if signal passes all checks, False otherwise

    Note:
        Logs specific rejection reasons at WARNING level
    """
    # Rule 1: Position conflict check
    if current_position is not None and not self.allow_concurrent_positions:
        self.logger.warning(
            f"Signal rejected: {signal.signal_type.value} for {signal.symbol} "
            f"blocked by existing {current_position.side} position"
        )
        return False

    # Rule 2: TP/SL correctness (already validated in Signal.__post_init__)
    # Additional validation for extreme cases
    if signal.signal_type == SignalType.LONG_ENTRY:
        if signal.take_profit <= signal.entry_price:
            self.logger.warning(f"Invalid LONG: TP ({signal.take_profit}) <= entry ({signal.entry_price})")
            return False
        if signal.stop_loss >= signal.entry_price:
            self.logger.warning(f"Invalid LONG: SL ({signal.stop_loss}) >= entry ({signal.entry_price})")
            return False
    elif signal.signal_type == SignalType.SHORT_ENTRY:
        if signal.take_profit >= signal.entry_price:
            self.logger.warning(f"Invalid SHORT: TP ({signal.take_profit}) >= entry ({signal.entry_price})")
            return False
        if signal.stop_loss <= signal.entry_price:
            self.logger.warning(f"Invalid SHORT: SL ({signal.stop_loss}) <= entry ({signal.entry_price})")
            return False

    # Rule 3: Minimum R:R ratio check
    rr_ratio = self.calculate_risk_reward_ratio(signal)
    if rr_ratio < self.min_risk_reward_ratio:
        self.logger.warning(
            f"Signal rejected: R:R ratio {rr_ratio:.2f} < minimum {self.min_risk_reward_ratio:.2f}"
        )
        return False

    # Rule 4: Reasonable SL distance check
    sl_distance = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
    if sl_distance < self.min_sl_distance_percent:
        self.logger.warning(
            f"Signal rejected: SL distance {sl_distance:.2%} < minimum {self.min_sl_distance_percent:.2%}"
        )
        return False

    return True
```

### 5.2 Validation State Machine

```
Signal Received
    │
    ├─→ Check Position Conflict
    │   ├─ FAIL → Reject (log: "existing position")
    │   └─ PASS → Continue
    │
    ├─→ Check TP/SL Logic
    │   ├─ FAIL → Reject (log: "invalid TP/SL placement")
    │   └─ PASS → Continue
    │
    ├─→ Check R:R Ratio
    │   ├─ FAIL → Reject (log: "R:R too low")
    │   └─ PASS → Continue
    │
    └─→ Check SL Distance
        ├─ FAIL → Reject (log: "SL too tight")
        └─ PASS → **VALIDATED** ✓
```

---

## 6. Error Handling Strategy

### 6.1 Exception Hierarchy

**Principle**: Use **typed exceptions** for programmatic error handling, not strings.

```python
# From src/core/exceptions.py
class RiskManagementError(TradingSystemError):
    """Base exception for risk management errors"""
    pass

class PositionSizingError(RiskManagementError):
    """Position size calculation failed"""
    pass

class SignalValidationError(RiskManagementError):
    """Signal validation failed"""
    pass

class AccountQueryError(RiskManagementError):
    """Failed to query account information"""
    pass
```

### 6.2 Error Handling Patterns

```python
# Pattern 1: Validation Errors (return False, don't raise)
def validate_signal(self, signal: Signal) -> bool:
    try:
        # Validation logic
        if invalid_condition:
            self.logger.warning("Specific rejection reason")
            return False  # Fail gracefully
        return True
    except Exception as e:
        self.logger.error(f"Validation error: {e}", exc_info=True)
        return False  # Default to rejection on unexpected errors

# Pattern 2: Calculation Errors (raise typed exceptions)
def calculate_position_size(self, ...) -> float:
    try:
        # Calculation logic
        if invalid_input:
            raise ValueError("Specific error message")

        account_balance = self._get_account_balance()
        # ... calculation

    except OrderExecutionError as e:
        # Wrap and re-raise with context
        raise AccountQueryError(f"Failed to get account balance: {e}") from e
    except ValueError as e:
        # Wrap input validation errors
        raise PositionSizingError(f"Invalid input: {e}") from e

# Pattern 3: External API Errors (wrap with retry from Task 6)
@retry_with_backoff(max_retries=3, initial_delay=1.0)
def _get_account_balance(self) -> float:
    try:
        return self._order_manager.get_account_balance()
    except OrderExecutionError as e:
        self.logger.error(f"Balance query failed: {e}")
        raise AccountQueryError(f"Balance query failed: {e}") from e
```

### 6.3 Logging Strategy

**Log Levels**:
- `DEBUG`: Detailed calculation steps, lot size rounding
- `INFO`: Position size results, validation outcomes
- `WARNING`: Signal rejections, position size limiting, edge case handling
- `ERROR`: Calculation failures, API errors, unexpected exceptions

**Log Format** (consistent with Task 6):
```python
self.logger.info(
    f"Position size calculated: {quantity} "
    f"(risk={risk_amount:.2f} USDT, SL dist={sl_distance:.2%})"
)

self.logger.warning(
    f"Position size limited from {original_qty:.4f} to {capped_qty:.4f} "
    f"(max {self.max_position_size_percent*100}% of account)"
)

self.logger.error(
    f"Position sizing failed: {type(e).__name__}: {e}",
    exc_info=True  # Include stack trace
)
```

---

## 7. Industry Best Practices Integration

### 7.1 Lessons from Production Systems

Based on analysis of Nautilus Trader (production-grade trading platform):

1. **Risk Engine Separation**: Keep risk logic separate from execution logic
   - ✓ **Applied**: RiskManager is isolated from OrderExecutionManager

2. **Configuration-Driven Limits**: Risk parameters in config files, not hardcoded
   - ✓ **Applied**: All limits configurable via trading_config.ini

3. **Position Aggregation**: Track net exposure, not just individual positions
   - → **Future Enhancement**: Currently simple "no concurrent positions" rule

4. **Order Rate Limiting**: Prevent spam and rate limit violations
   - ✓ **Already handled**: Task 6 implements RequestWeightTracker

5. **ReduceOnly Orders**: Support for position reduction without adding exposure
   - → **Future Enhancement**: Add reduce_only parameter to position sizing

### 7.2 Quantitative Risk Model Patterns

From Toraniko (quantitative risk modeling library):

1. **Cross-Sectional Normalization**: Standardize risk across multiple positions
   - → **Future Enhancement**: Portfolio-level risk aggregation

2. **Exponential Weighting**: Recent risk metrics matter more than old ones
   - → **Future Enhancement**: Adaptive risk limits based on recent PnL

3. **Factor Decomposition**: Break down risk into components (market, sector, idiosyncratic)
   - → **Not applicable**: Single-asset futures trading (no portfolio diversification yet)

---

## 8. Testing Strategy

### 8.1 Unit Test Coverage

**Subtask 7.1**: Position Size Calculation
```python
def test_position_size_normal_case():
    """1% risk with 2% SL distance"""
    manager = RiskManager(config)
    quantity = manager.calculate_position_size(
        account_balance=10000,
        entry_price=50000,
        stop_loss_price=49000,  # 2% SL
        leverage=10
    )
    expected = (10000 * 0.01) / 0.02 / 50000  # 100 / 0.02 / 50000 = 0.1 BTC
    assert quantity == pytest.approx(expected, rel=0.01)

def test_position_size_tight_sl():
    """Very tight SL (0.1%) should still calculate correctly"""
    quantity = manager.calculate_position_size(
        account_balance=10000,
        entry_price=50000,
        stop_loss_price=49950,  # 0.1% SL
        leverage=10
    )
    # Tighter SL = larger position for same risk
    assert quantity > 0.5  # Should be ~1.0 BTC

def test_position_size_zero_sl():
    """Zero SL distance should use minimum threshold"""
    quantity = manager.calculate_position_size(
        account_balance=10000,
        entry_price=50000,
        stop_loss_price=50000,  # Same as entry!
        leverage=10
    )
    # Should use 0.1% minimum SL distance
    assert quantity > 0
```

**Subtask 7.2**: Signal Validation
```python
def test_validate_signal_valid_long():
    """Valid LONG signal should pass"""
    signal = Signal(
        signal_type=SignalType.LONG_ENTRY,
        symbol="BTCUSDT",
        entry_price=50000,
        take_profit=52000,  # Above entry ✓
        stop_loss=49000,    # Below entry ✓
        strategy_name="Test",
        timestamp=datetime.now(timezone.utc)
    )
    assert manager.validate_signal(signal) is True

def test_validate_signal_invalid_long_tp():
    """LONG with TP <= entry should fail"""
    signal = Signal(..., take_profit=49000)  # TP below entry!
    assert manager.validate_signal(signal) is False

def test_validate_signal_existing_position():
    """Signal should be rejected if position exists"""
    position = Position(symbol="BTCUSDT", side="LONG", ...)
    signal = Signal(signal_type=SignalType.LONG_ENTRY, ...)
    assert manager.validate_signal(signal, position) is False
```

**Subtask 7.3**: R:R and Limiting
```python
def test_calculate_rr_ratio():
    """R:R ratio calculation"""
    signal = Signal(
        entry_price=50000,
        take_profit=52000,  # +2000
        stop_loss=49000     # -1000
    )
    rr = manager.calculate_risk_reward_ratio(signal)
    assert rr == pytest.approx(2.0)  # 2:1 R:R

def test_position_size_limiting():
    """Position size should be capped at max%"""
    # Setup: Very tight SL that would result in huge position
    quantity = manager.calculate_position_size(
        account_balance=10000,
        entry_price=50000,
        stop_loss_price=49999,  # 0.002% SL = huge position
        leverage=10
    )
    # Max position value: 10000 * 0.1 * 10 = 10,000 USDT = 0.2 BTC
    assert quantity <= 0.2
```

**Subtask 7.4**: Lot Size Rounding
```python
def test_lot_size_rounding_btc():
    """BTCUSDT lot size rounding (0.001 precision)"""
    symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
    quantity = manager._round_to_lot_size(1.2345, symbol_info)
    assert quantity == 1.234  # Rounded to 3 decimals

def test_lot_size_rounding_floor():
    """Should floor down, not round up"""
    symbol_info = {'lot_size': 0.01, 'quantity_precision': 2}
    quantity = manager._round_to_lot_size(0.567, symbol_info)
    assert quantity == 0.56  # Floored to 0.01 lot size
```

### 8.2 Integration Tests

```python
def test_full_position_sizing_flow():
    """End-to-end: Signal → Validation → Position Size"""
    # Setup mocks
    order_manager.get_account_balance = Mock(return_value=10000)
    order_manager.get_position = Mock(return_value=None)

    # Create signal
    signal = Signal(
        signal_type=SignalType.LONG_ENTRY,
        symbol="BTCUSDT",
        entry_price=50000,
        take_profit=52000,
        stop_loss=49000,
        strategy_name="Test",
        timestamp=datetime.now(timezone.utc)
    )

    # Validate
    assert risk_manager.validate_signal(signal) is True

    # Calculate size
    symbol_info = {'lot_size': 0.001, 'quantity_precision': 3}
    quantity = risk_manager.calculate_position_size(
        account_balance=10000,
        entry_price=signal.entry_price,
        stop_loss_price=signal.stop_loss,
        leverage=10,
        symbol_info=symbol_info
    )

    # Verify result
    assert 0 < quantity <= 0.2  # Within reasonable bounds
    assert quantity % 0.001 == 0  # Lot size compliant
```

### 8.3 Property-Based Testing

Using Hypothesis for fuzz testing:
```python
from hypothesis import given, strategies as st

@given(
    balance=st.floats(min_value=100, max_value=100000),
    entry=st.floats(min_value=1000, max_value=100000),
    sl_distance_pct=st.floats(min_value=0.001, max_value=0.1)
)
def test_position_size_always_positive(balance, entry, sl_distance_pct):
    """Position size should always be positive"""
    stop_loss = entry * (1 - sl_distance_pct)
    quantity = risk_manager.calculate_position_size(
        account_balance=balance,
        entry_price=entry,
        stop_loss_price=stop_loss,
        leverage=10
    )
    assert quantity > 0
    assert quantity < balance  # Never larger than account balance in base asset value
```

---

## 9. Performance Considerations

### 9.1 Calculation Complexity

**Time Complexity**: O(1) for all operations
- Position sizing: Simple arithmetic operations
- Validation: Sequential checks (no loops)
- Lot size rounding: Single string operation

**Space Complexity**: O(1)
- No data structures that grow with input size
- Minimal state (just config parameters)

**Estimated Latency**: <1ms per call (pure Python calculations)

### 9.2 Optimization Opportunities

1. **Symbol Info Caching**: Cache Binance symbol specs (already done in Task 6)
   ```python
   # Leverage OrderExecutionManager's exchange_info_cache
   symbol_info = self._order_manager._exchange_info_cache.get(symbol)
   ```

2. **Lazy Account Balance Query**: Only query when needed
   ```python
   # Don't query balance during validation (no calculation yet)
   def validate_signal(self, signal) -> bool:
       # No balance query here

   # Only query during position sizing
   def calculate_position_size(self, ...) -> float:
       balance = self._get_account_balance()  # Query here
   ```

3. **Batch Validation**: If processing multiple signals, validate all before querying balance once
   ```python
   # Future enhancement for multi-signal strategies
   def validate_signals(self, signals: list[Signal]) -> list[bool]:
       return [self.validate_signal(s) for s in signals]  # No balance queries
   ```

---

## 10. Security & Safety Considerations

### 10.1 Input Validation

**Defense in Depth**:
```python
def calculate_position_size(self, ...) -> float:
    # Layer 1: Type checking (Python type hints + runtime checks)
    if not isinstance(account_balance, (int, float)) or account_balance <= 0:
        raise ValueError(f"Invalid account balance: {account_balance}")

    if not isinstance(entry_price, (int, float)) or entry_price <= 0:
        raise ValueError(f"Invalid entry price: {entry_price}")

    # Layer 2: Range validation
    if leverage < 1 or leverage > self.max_leverage:
        raise ValueError(f"Leverage {leverage} outside valid range [1, {self.max_leverage}]")

    # Layer 3: Business logic validation
    sl_distance = abs(entry_price - stop_loss_price) / entry_price
    if sl_distance > 0.5:  # 50% SL is unreasonable
        self.logger.warning(f"Unusually large SL distance: {sl_distance:.2%}")
        # Allow but log warning (may be intentional for very volatile markets)
```

### 10.2 State Management

**Principle**: RiskManager should be **stateless** for calculations (pure functions).

```python
class RiskManager:
    # Configuration state (immutable after __init__)
    max_risk_per_trade: float
    max_leverage: int

    # NO mutable calculation state!
    # Each calculation is independent

    def calculate_position_size(self, ...) -> float:
        # Pure function: same inputs always produce same output
        # No side effects except logging
        pass
```

**Rationale**: Stateless design prevents bugs from stale state and makes testing easier.

### 10.3 Fail-Safe Defaults

**Conservative Configuration**:
```python
DEFAULT_CONFIG = {
    'max_risk_per_trade': 0.01,         # 1% (conservative)
    'max_leverage': 20,                 # Binance max but high
    'default_leverage': 5,              # Lower default (safer)
    'max_position_size_percent': 0.05,  # 5% (more conservative than 10%)
    'allow_concurrent_positions': False, # Single position only (simpler)
    'min_risk_reward_ratio': 1.5,      # Require favorable R:R
    'min_sl_distance_percent': 0.001,  # 0.1% minimum SL
}
```

**On Error Behavior**:
- Validation errors → Reject signal (don't trade)
- Calculation errors → Raise exception (don't guess)
- API errors → Retry with backoff (transient failures)

---

## 11. Future Enhancements

### 11.1 Phase 2 Features (Post-MVP)

1. **Adaptive Risk Management**
   - Reduce risk after consecutive losses
   - Increase risk after winning streaks (with limits)
   - Volatility-adjusted position sizing

2. **Portfolio Risk Management**
   - Track aggregate exposure across multiple positions
   - Correlation-based position limits
   - Maximum portfolio heat (total capital at risk)

3. **Advanced Validation**
   - Historical volatility checks
   - Minimum R:R ratio per strategy
   - Time-of-day risk limits (avoid news events)

4. **Risk Analytics**
   - Real-time drawdown tracking
   - Sharpe ratio monitoring
   - Risk-adjusted return calculation

### 11.2 Integration with Task 8 (Backtesting)

**Backtesting Support**:
```python
# RiskManager should work seamlessly in backtesting
class BacktestRiskManager(RiskManager):
    def _get_account_balance(self) -> float:
        # Override to use backtesting account state
        return self._backtest_account.balance

    def _get_current_position(self, symbol: str) -> Optional[Position]:
        # Override to use backtesting position tracker
        return self._backtest_positions.get(symbol)
```

---

## 12. Implementation Checklist

### Phase 1: Core Implementation (Subtasks 7.1-7.4)

- [ ] **Subtask 7.1**: Position size calculation
  - [ ] Implement risk-based formula
  - [ ] Handle zero SL edge case
  - [ ] Add detailed logging
  - [ ] Unit tests (normal, tight SL, wide SL, zero SL)

- [ ] **Subtask 7.2**: Signal validation
  - [ ] Position conflict detection
  - [ ] TP/SL correctness validation
  - [ ] Warning logs for rejections
  - [ ] Unit tests (LONG/SHORT valid/invalid, position conflict)

- [ ] **Subtask 7.3**: R:R and position limiting
  - [ ] R:R ratio calculation
  - [ ] Max position size enforcement
  - [ ] Limiting log with both values
  - [ ] Unit tests (R:R calculation, position capping)

- [ ] **Subtask 7.4**: Lot size rounding
  - [ ] Binance-compliant rounding logic
  - [ ] Symbol info integration
  - [ ] Graceful fallback for missing info
  - [ ] Unit tests (BTCUSDT, ETHUSDT, missing info)

### Phase 2: Integration & Testing

- [ ] Integration with OrderExecutionManager (Task 6)
- [ ] Integration with Signal models (Task 2)
- [ ] End-to-end tests (signal → validation → sizing → execution)
- [ ] Property-based testing (Hypothesis)
- [ ] Performance benchmarking (<1ms per call)

### Phase 3: Documentation & Review

- [ ] API documentation (docstrings)
- [ ] Configuration examples
- [ ] Error handling guide
- [ ] Code review with focus on safety

---

## 13. Success Criteria

### Functional Requirements

✅ **Position Sizing**:
- Calculates correct quantity for 1% risk scenarios
- Handles tight SL (<0.1%) without errors
- Handles wide SL (>10%) with appropriate limits
- Prevents division by zero (minimum SL threshold)

✅ **Validation**:
- Rejects invalid TP/SL placement (100% accuracy)
- Blocks concurrent positions when configured
- Validates R:R ratio meets minimum threshold
- Provides actionable log messages for rejections

✅ **Exchange Compliance**:
- Rounds quantities to Binance lot sizes
- Respects quantity precision requirements
- Works with real BTCUSDT/ETHUSDT specifications

### Non-Functional Requirements

✅ **Performance**: <1ms per calculation (pure Python)
✅ **Reliability**: 100% test coverage for core logic
✅ **Safety**: Conservative defaults, fail-safe on errors
✅ **Maintainability**: Clear code structure, comprehensive logging
✅ **Auditability**: Every decision logged with rationale

---

## 14. Appendix: Code Examples

### 14.1 Usage Example

```python
from src.risk.manager import RiskManager
from src.execution.order_manager import OrderExecutionManager
from src.models.signal import Signal, SignalType
from datetime import datetime, timezone

# Initialize components
order_manager = OrderExecutionManager(is_testnet=True)
risk_manager = RiskManager(
    config={
        'max_risk_per_trade': 0.01,
        'max_leverage': 20,
        'default_leverage': 10,
        'max_position_size_percent': 0.1
    },
    order_manager=order_manager
)

# Receive trading signal
signal = Signal(
    signal_type=SignalType.LONG_ENTRY,
    symbol="BTCUSDT",
    entry_price=50000.0,
    take_profit=52000.0,
    stop_loss=49000.0,
    strategy_name="ICT_Strategy",
    timestamp=datetime.now(timezone.utc)
)

# Validate signal
current_position = order_manager.get_position(signal.symbol)
if not risk_manager.validate_signal(signal, current_position):
    print("Signal rejected by risk management")
    exit()

# Calculate position size
account_balance = order_manager.get_account_balance()
symbol_info = order_manager._exchange_info_cache.get(signal.symbol)

quantity = risk_manager.calculate_position_size(
    account_balance=account_balance,
    entry_price=signal.entry_price,
    stop_loss_price=signal.stop_loss,
    leverage=risk_manager.default_leverage,
    symbol_info=symbol_info
)

print(f"Calculated position size: {quantity} BTC")

# Execute order (Task 6)
entry_order, tpsl_orders = order_manager.execute_signal(signal, quantity)
print(f"Entry order ID: {entry_order.order_id}")
print(f"TP/SL orders placed: {len(tpsl_orders)}/2")
```

### 14.2 Configuration Loading

```python
from src.utils.config import load_config

# Load trading configuration
config = load_config('trading_config.ini')

# Extract risk section
risk_config = {
    'max_risk_per_trade': config.getfloat('risk', 'max_risk_per_trade', fallback=0.01),
    'max_leverage': config.getint('risk', 'max_leverage', fallback=20),
    'default_leverage': config.getint('risk', 'default_leverage', fallback=10),
    'max_position_size_percent': config.getfloat('risk', 'max_position_size_percent', fallback=0.1),
    'allow_concurrent_positions': config.getboolean('risk', 'allow_concurrent_positions', fallback=False),
    'min_risk_reward_ratio': config.getfloat('risk', 'min_risk_reward_ratio', fallback=1.0),
    'min_sl_distance_percent': config.getfloat('risk', 'min_sl_distance_percent', fallback=0.001),
}

# Initialize RiskManager
risk_manager = RiskManager(risk_config, order_manager)
```

---

**End of Design Document**

**Next Steps**:
1. Review design with team/stakeholders
2. Begin implementation with Subtask 7.1 (position sizing)
3. Iterate on design based on implementation learnings
4. Integrate with Task 6 (Order Manager) for testing
