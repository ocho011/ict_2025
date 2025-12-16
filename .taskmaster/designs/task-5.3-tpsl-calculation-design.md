# TP/SL Calculation Logic Design Document

**Task**: Subtask 5.3 - Implement TP/SL Calculation Logic
**Date**: 2025-12-16
**Status**: Completed

---

## 1. Overview

### 1.1 Purpose
Implement take profit (TP) and stop loss (SL) calculation methods for the MockSMACrossoverStrategy with:
- **Configurable risk/reward ratios** for flexible position management
- **Support for both LONG and SHORT positions** with correct price calculations
- **Consistent risk management** across all signal types
- **Integration with Signal creation** for automated order placement

### 1.2 Core Requirements
From Task 5.3 specification:
- Calculate stop loss as percentage of entry price
- Calculate take profit based on risk/reward ratio
- Support LONG positions (buy): SL below entry, TP above entry
- Support SHORT positions (sell): SL above entry, TP below entry
- Create Signal objects with calculated TP/SL values

### 1.3 Key Concepts

**Risk**: The amount at risk per trade (distance from entry to stop loss)
```
Risk = Entry Price × Stop Loss Percentage
```

**Reward**: The potential profit per trade (distance from entry to take profit)
```
Reward = Risk × Risk/Reward Ratio
```

**Risk/Reward Ratio**: The ratio of potential profit to potential loss
```
Risk/Reward Ratio = Reward / Risk
Example: 2:1 ratio means profit potential is 2x the risk
```

---

## 2. Mathematical Formulas

### 2.1 Stop Loss Calculation

**LONG Position (Buy)**
```
SL Price = Entry Price × (1 - Stop Loss %)
Example: Entry = $50,000, SL% = 1% (0.01)
         SL = $50,000 × (1 - 0.01) = $49,500
```

**SHORT Position (Sell)**
```
SL Price = Entry Price × (1 + Stop Loss %)
Example: Entry = $50,000, SL% = 1% (0.01)
         SL = $50,000 × (1 + 0.01) = $50,500
```

**Logic**:
- LONG: Price must go down to hit SL (below entry)
- SHORT: Price must go up to hit SL (above entry)

### 2.2 Take Profit Calculation

**Step 1: Calculate Risk Distance**
```
Risk Distance = Entry Price × Stop Loss %
```

**Step 2: Calculate Reward Distance**
```
Reward Distance = Risk Distance × Risk/Reward Ratio
```

**Step 3: Calculate TP Price**

**LONG Position:**
```
TP Price = Entry Price + Reward Distance

Example: Entry = $50,000, SL% = 1%, RR = 2.0
         Risk = $50,000 × 0.01 = $500
         Reward = $500 × 2.0 = $1,000
         TP = $50,000 + $1,000 = $51,000
```

**SHORT Position:**
```
TP Price = Entry Price - Reward Distance

Example: Entry = $50,000, SL% = 1%, RR = 2.0
         Risk = $50,000 × 0.01 = $500
         Reward = $500 × 2.0 = $1,000
         TP = $50,000 - $1,000 = $49,000
```

**Logic**:
- LONG: Price must go up to hit TP (above entry)
- SHORT: Price must go down to hit TP (below entry)

---

## 3. Implementation Design

### 3.1 Method Signatures

```python
def calculate_stop_loss(self, entry_price: float, side: str) -> float:
    """
    Calculate stop loss price as percentage of entry price.

    Args:
        entry_price: Position entry price
        side: 'LONG' or 'SHORT'

    Returns:
        Stop loss price (float)

    Formula:
        LONG:  SL = entry × (1 - stop_loss_percent)
        SHORT: SL = entry × (1 + stop_loss_percent)
    """
```

```python
def calculate_take_profit(self, entry_price: float, side: str) -> float:
    """
    Calculate take profit price based on risk-reward ratio.

    Args:
        entry_price: Position entry price
        side: 'LONG' or 'SHORT'

    Returns:
        Take profit price (float)

    Formula:
        SL_distance = entry_price × stop_loss_percent
        TP_distance = SL_distance × risk_reward_ratio

        LONG:  TP = entry + TP_distance
        SHORT: TP = entry - TP_distance
    """
```

```python
def _create_signal(self, signal_type: SignalType, candle: Candle) -> Signal:
    """
    Helper to construct Signal object with calculated TP/SL.

    Args:
        signal_type: LONG_ENTRY or SHORT_ENTRY
        candle: Current candle with entry price

    Returns:
        Signal object with TP/SL automatically calculated
    """
```

### 3.2 Configuration Parameters

**Class-level Configuration:**
```python
class MockSMACrossoverStrategy(BaseStrategy):
    def __init__(self, symbol: str, config: dict):
        super().__init__(symbol, config)
        # Risk management parameters
        self.risk_reward_ratio = config.get('risk_reward_ratio', 2.0)
        self.stop_loss_percent = config.get('stop_loss_percent', 0.01)
```

**Default Values:**
- `risk_reward_ratio`: 2.0 (2:1 risk/reward)
- `stop_loss_percent`: 0.01 (1% of entry price)

**Typical Ranges:**
- Risk/Reward Ratio: 1.5 - 3.0
- Stop Loss %: 0.005 (0.5%) - 0.02 (2%)

### 3.3 Side Determination Logic

```python
def _create_signal(self, signal_type: SignalType, candle: Candle) -> Signal:
    # Determine position side from signal type
    if signal_type == SignalType.LONG_ENTRY:
        side = 'LONG'
    elif signal_type == SignalType.SHORT_ENTRY:
        side = 'SHORT'
    else:
        raise ValueError(f"Invalid signal type for entry: {signal_type}")

    entry_price = candle.close

    # Calculate TP/SL using helper methods
    tp = self.calculate_take_profit(entry_price, side)
    sl = self.calculate_stop_loss(entry_price, side)

    return Signal(
        signal_type=signal_type,
        symbol=self.symbol,
        entry_price=entry_price,
        take_profit=tp,
        stop_loss=sl,
        strategy_name=self.__class__.__name__,
        timestamp=datetime.now(timezone.utc)
    )
```

---

## 4. Validation & Edge Cases

### 4.1 Price Relationship Validation

**LONG Position Requirements:**
```
SL < Entry < TP

Example: Entry = $50,000
         SL = $49,500 ✓ (below entry)
         TP = $51,000 ✓ (above entry)
```

**SHORT Position Requirements:**
```
TP < Entry < SL

Example: Entry = $50,000
         TP = $49,000 ✓ (below entry)
         SL = $50,500 ✓ (above entry)
```

**Validation Location:** Signal model's `__post_init__()` method enforces these relationships.

### 4.2 Edge Cases

**Case 1: Very Small Entry Prices**
```python
entry = 0.0001  # Small altcoin price
sl_percent = 0.01
risk = 0.0001 × 0.01 = 0.000001

# Ensure precision is maintained
assert sl != entry  # Must be different
```

**Case 2: Very Large Entry Prices**
```python
entry = 1_000_000  # High-value asset
sl_percent = 0.01
risk = 1_000_000 × 0.01 = 10_000

# Calculation should not overflow
assert isinstance(tp, float)
assert isinstance(sl, float)
```

**Case 3: Zero Risk/Reward Ratio**
```python
risk_reward_ratio = 0  # Invalid
# Should use default or raise error
# Current implementation: uses config value, no validation
```

**Case 4: Negative Percentages**
```python
stop_loss_percent = -0.01  # Invalid
# Should be prevented by validation
# Current implementation: no explicit validation
```

### 4.3 Floating Point Precision

**Issue**: Floating point arithmetic can introduce small errors
```python
# Example of potential precision issue
entry = 49999.999999999
sl = entry * (1 - 0.01)
# Result: 49499.99999999901 (small precision error)
```

**Current Approach**: Use Python's native float (64-bit)
- Sufficient precision for cryptocurrency prices
- Exchange APIs typically round to specific decimal places
- Signal model can add rounding if needed

---

## 5. Integration with MockSMACrossoverStrategy

### 5.1 Signal Generation Flow

```
1. SMA Crossover Detection
   ↓
2. Determine Signal Type
   - Golden Cross → LONG_ENTRY
   - Death Cross → SHORT_ENTRY
   ↓
3. Call _create_signal(signal_type, candle)
   ↓
4. Determine Side from Signal Type
   - LONG_ENTRY → 'LONG'
   - SHORT_ENTRY → 'SHORT'
   ↓
5. Calculate SL and TP
   - call calculate_stop_loss(entry, side)
   - call calculate_take_profit(entry, side)
   ↓
6. Create Signal Object
   - Set entry_price = candle.close
   - Set calculated TP and SL
   - Set timestamp, symbol, strategy_name
   ↓
7. Return Signal
```

### 5.2 Usage in analyze() Method

```python
async def analyze(self, candle: Candle) -> Optional[Signal]:
    # ... SMA calculation and crossover detection ...

    # Golden cross detected
    if prev_fast <= prev_slow and fast_sma > slow_sma:
        if self._last_signal_type != SignalType.LONG_ENTRY:
            self._last_signal_type = SignalType.LONG_ENTRY
            # TP/SL automatically calculated in _create_signal
            return self._create_signal(SignalType.LONG_ENTRY, candle)

    # Death cross detected
    if prev_fast >= prev_slow and fast_sma < slow_sma:
        if self._last_signal_type != SignalType.SHORT_ENTRY:
            self._last_signal_type = SignalType.SHORT_ENTRY
            # TP/SL automatically calculated in _create_signal
            return self._create_signal(SignalType.SHORT_ENTRY, candle)

    return None
```

---

## 6. Test Strategy

### 6.1 Unit Test Cases

**Test Class: TestTPSLCalculation** (8 tests in test_mock_strategy.py)

#### TC1: Stop Loss Calculation - LONG
```python
def test_calculate_stop_loss_long_default():
    # Entry: $100, SL%: 1% → Expected: $99
    strategy = MockSMACrossoverStrategy('BTCUSDT', {})
    sl = strategy.calculate_stop_loss(100.0, 'LONG')
    assert sl == 99.0
```

#### TC2: Stop Loss Calculation - SHORT
```python
def test_calculate_stop_loss_short_default():
    # Entry: $100, SL%: 1% → Expected: $101
    strategy = MockSMACrossoverStrategy('BTCUSDT', {})
    sl = strategy.calculate_stop_loss(100.0, 'SHORT')
    assert sl == 101.0
```

#### TC3: Take Profit Calculation - LONG (Default 2:1)
```python
def test_calculate_take_profit_long_default():
    # Entry: $100, SL%: 1%, RR: 2.0
    # Risk: $1, Reward: $2 → TP: $102
    strategy = MockSMACrossoverStrategy('BTCUSDT', {})
    tp = strategy.calculate_take_profit(100.0, 'LONG')
    assert tp == 102.0
```

#### TC4: Take Profit Calculation - SHORT (Default 2:1)
```python
def test_calculate_take_profit_short_default():
    # Entry: $100, SL%: 1%, RR: 2.0
    # Risk: $1, Reward: $2 → TP: $98
    strategy = MockSMACrossoverStrategy('BTCUSDT', {})
    tp = strategy.calculate_take_profit(100.0, 'SHORT')
    assert tp == 98.0
```

#### TC5: Custom Risk/Reward Ratio - LONG
```python
def test_calculate_take_profit_long_custom_rr():
    # Entry: $100, SL%: 1%, RR: 3.0
    # Risk: $1, Reward: $3 → TP: $103
    config = {'risk_reward_ratio': 3.0}
    strategy = MockSMACrossoverStrategy('BTCUSDT', config)
    tp = strategy.calculate_take_profit(100.0, 'LONG')
    assert tp == 103.0
```

#### TC6: Custom Stop Loss Percentage
```python
def test_calculate_stop_loss_custom_percent():
    # Entry: $100, SL%: 2%
    # LONG: $98, SHORT: $102
    config = {'stop_loss_percent': 0.02}
    strategy = MockSMACrossoverStrategy('BTCUSDT', config)

    sl_long = strategy.calculate_stop_loss(100.0, 'LONG')
    assert sl_long == 98.0

    sl_short = strategy.calculate_stop_loss(100.0, 'SHORT')
    assert sl_short == 102.0
```

#### TC7: Signal TP/SL Validation
```python
def test_signal_tpsl_relationship_long():
    # Verify SL < Entry < TP for LONG
    strategy = MockSMACrossoverStrategy('BTCUSDT', {})
    signal = strategy._create_signal(SignalType.LONG_ENTRY, test_candle)

    assert signal.stop_loss < signal.entry_price
    assert signal.entry_price < signal.take_profit
```

#### TC8: Signal TP/SL Validation - SHORT
```python
def test_signal_tpsl_relationship_short():
    # Verify TP < Entry < SL for SHORT
    strategy = MockSMACrossoverStrategy('BTCUSDT', {})
    signal = strategy._create_signal(SignalType.SHORT_ENTRY, test_candle)

    assert signal.take_profit < signal.entry_price
    assert signal.entry_price < signal.stop_loss
```

### 6.2 Test Coverage Results

From test_mock_strategy.py (test commit 5f50d5d):
- **8 tests** specifically for TP/SL calculation
- **All tests passing** ✅
- **Code coverage**: 96% for MockSMACrossoverStrategy
- Missing coverage: Lines 212, 223 (duplicate signal prevention returns)

---

## 7. Implementation Details

### 7.1 Actual Implementation Location

**File**: `src/strategies/mock_strategy.py`
**Lines**: 274-375

**calculate_take_profit()** (lines 274-327):
```python
def calculate_take_profit(self, entry_price: float, side: str) -> float:
    """
    Calculate take profit price based on risk-reward ratio.

    TP is calculated as a multiple of the stop loss distance:
    - LONG: TP = entry + (SL_distance * risk_reward_ratio)
    - SHORT: TP = entry - (SL_distance * risk_reward_ratio)
    """
    sl_distance = entry_price * self.stop_loss_percent
    tp_distance = sl_distance * self.risk_reward_ratio

    if side == 'LONG':
        return entry_price + tp_distance
    else:  # SHORT
        return entry_price - tp_distance
```

**calculate_stop_loss()** (lines 329-375):
```python
def calculate_stop_loss(self, entry_price: float, side: str) -> float:
    """
    Calculate stop loss price as percentage of entry price.

    SL is set at a fixed percentage below (LONG) or above (SHORT) entry:
    - LONG: SL = entry - (entry * stop_loss_percent)
    - SHORT: SL = entry + (entry * stop_loss_percent)
    """
    if side == 'LONG':
        return entry_price * (1 - self.stop_loss_percent)
    else:  # SHORT
        return entry_price * (1 + self.stop_loss_percent)
```

**_create_signal()** (lines 232-272):
```python
def _create_signal(self, signal_type: SignalType, candle: Candle) -> Signal:
    """
    Create a Signal object with calculated TP/SL.

    Automatically determines side from signal_type and calculates
    appropriate take profit and stop loss levels.
    """
    side = 'LONG' if signal_type == SignalType.LONG_ENTRY else 'SHORT'
    entry_price = candle.close

    return Signal(
        signal_type=signal_type,
        symbol=self.symbol,
        entry_price=entry_price,
        take_profit=self.calculate_take_profit(entry_price, side),
        stop_loss=self.calculate_stop_loss(entry_price, side),
        strategy_name=self.__class__.__name__,
        timestamp=datetime.now(timezone.utc)
    )
```

### 7.2 Implementation Notes

**Key Design Decisions:**
1. **Percentage-based SL**: Simple, predictable, works across price ranges
2. **Risk-based TP**: Ensures consistent risk/reward across all trades
3. **Side parameter**: Explicit 'LONG'/'SHORT' string for clarity
4. **Helper method**: `_create_signal()` encapsulates signal creation logic
5. **No validation**: Trusts Signal model's `__post_init__` for validation

**Why This Approach:**
- **Simplicity**: Easy to understand and maintain
- **Flexibility**: Config-based parameters allow tuning
- **Consistency**: Same logic for all signals
- **Testability**: Pure functions, easy to unit test

---

## 8. Configuration Examples

### 8.1 Conservative Settings (Lower Risk)
```python
config = {
    'fast_period': 10,
    'slow_period': 20,
    'risk_reward_ratio': 3.0,      # 3:1 RR (higher reward target)
    'stop_loss_percent': 0.005     # 0.5% SL (tighter stop)
}
```

**Characteristics:**
- Tighter stop loss (less risk per trade)
- Higher reward target (but harder to achieve)
- Suitable for low volatility markets

### 8.2 Aggressive Settings (Higher Risk)
```python
config = {
    'fast_period': 10,
    'slow_period': 20,
    'risk_reward_ratio': 1.5,      # 1.5:1 RR (lower reward target)
    'stop_loss_percent': 0.02      # 2% SL (wider stop)
}
```

**Characteristics:**
- Wider stop loss (more risk per trade)
- Lower reward target (easier to achieve)
- Suitable for high volatility markets

### 8.3 Balanced Settings (Default)
```python
config = {
    'fast_period': 10,
    'slow_period': 20,
    'risk_reward_ratio': 2.0,      # 2:1 RR
    'stop_loss_percent': 0.01      # 1% SL
}
```

**Characteristics:**
- Moderate risk per trade
- Reasonable reward target
- Suitable for most market conditions

---

## 9. Future Enhancements

### 9.1 ATR-Based Stop Loss
**Current**: Fixed percentage SL
**Enhancement**: Use Average True Range (ATR) for dynamic SL based on volatility

```python
def calculate_stop_loss_atr(self, entry_price: float, side: str, atr: float) -> float:
    """
    Calculate SL based on ATR (volatility-adjusted).

    SL Distance = ATR × ATR_Multiplier
    """
    atr_multiplier = self.config.get('atr_multiplier', 2.0)
    sl_distance = atr * atr_multiplier

    if side == 'LONG':
        return entry_price - sl_distance
    else:
        return entry_price + sl_distance
```

**Benefits**:
- Adapts to market volatility
- More sophisticated risk management
- Industry standard approach

### 9.2 Trailing Stop Loss
**Current**: Fixed SL price
**Enhancement**: SL moves with favorable price action

```python
def update_trailing_stop(self, current_price: float, current_sl: float, side: str) -> float:
    """
    Update trailing stop loss based on price movement.

    LONG: If price moves up, move SL up (but never down)
    SHORT: If price moves down, move SL down (but never up)
    """
    trailing_percent = self.config.get('trailing_stop_percent', 0.005)

    if side == 'LONG':
        new_sl = current_price * (1 - trailing_percent)
        return max(new_sl, current_sl)  # Never lower SL for LONG
    else:
        new_sl = current_price * (1 + trailing_percent)
        return min(new_sl, current_sl)  # Never raise SL for SHORT
```

### 9.3 Multiple TP Levels
**Current**: Single TP target
**Enhancement**: Scale out at multiple TP levels

```python
def calculate_take_profits(self, entry_price: float, side: str) -> List[float]:
    """
    Calculate multiple TP levels for partial position closing.

    Example: Close 50% at TP1, 30% at TP2, 20% at TP3
    """
    tp_levels = self.config.get('tp_levels', [1.5, 2.0, 3.0])  # RR multiples

    tps = []
    for rr_ratio in tp_levels:
        sl_distance = entry_price * self.stop_loss_percent
        tp_distance = sl_distance * rr_ratio

        if side == 'LONG':
            tps.append(entry_price + tp_distance)
        else:
            tps.append(entry_price - tp_distance)

    return tps
```

### 9.4 Break-Even Stop
**Current**: Fixed SL at entry time
**Enhancement**: Move SL to break-even after partial TP hit

```python
def should_move_to_breakeven(self, entry_price: float, current_price: float,
                             tp_price: float, side: str) -> bool:
    """
    Check if price has moved enough to warrant break-even SL.

    Typical rule: Move to BE when 50% of TP distance achieved
    """
    breakeven_percent = self.config.get('breakeven_trigger', 0.5)

    if side == 'LONG':
        tp_distance = tp_price - entry_price
        current_distance = current_price - entry_price
        return current_distance >= (tp_distance * breakeven_percent)
    else:
        tp_distance = entry_price - tp_price
        current_distance = entry_price - current_price
        return current_distance >= (tp_distance * breakeven_percent)
```

---

## 10. References

### 10.1 Implementation Files
- **Main Implementation**: `src/strategies/mock_strategy.py` (lines 232-375)
- **Base Interface**: `src/strategies/base.py` (abstract methods)
- **Signal Model**: `src/models/signal.py` (validation logic)
- **Tests**: `tests/strategies/test_mock_strategy.py` (TestTPSLCalculation class)

### 10.2 Related Tasks
- **Task 5.1**: BaseStrategy abstract class (defines interface)
- **Task 5.2**: MockSMACrossoverStrategy (uses TP/SL calculation)
- **Task 5.4**: StrategyFactory (instantiates strategies with config)

### 10.3 Git History
- **Implementation**: Commit `1559773` (Subtask 5.2)
- **Tests**: Commit `5f50d5d` (comprehensive unit tests)
- **Status Update**: Commit `c7b6001` (marked as done)

### 10.4 Trading Concepts
- **Risk Management**: Position sizing and stop loss principles
- **Risk/Reward Ratio**: Common trading metric (2:1, 3:1)
- **Position Types**: LONG (buy) vs SHORT (sell) mechanics

---

## 11. Approval & Sign-off

**Design Status:** ✅ Implemented and Tested

**Implementation Date:** 2025-12-12 (with Subtask 5.2)
**Test Date:** 2025-12-16
**Documentation Date:** 2025-12-16

**Key Achievements:**
1. ✅ Mathematical formulas correctly implemented
2. ✅ LONG and SHORT positions both supported
3. ✅ Configurable risk/reward parameters
4. ✅ 8 comprehensive unit tests, all passing
5. ✅ Integration with Signal model validation

**Quality Metrics:**
- **Code Coverage**: 96% (MockSMACrossoverStrategy)
- **Test Success Rate**: 100% (8/8 tests passing)
- **Formula Accuracy**: Verified with known test cases

**Next Steps:**
- ✅ Task 5.3 complete
- ✅ Task 5.4 complete
- ✅ Task 5 fully complete

---

**Document Version:** 1.0
**Last Updated:** 2025-12-16 23:45 KST
