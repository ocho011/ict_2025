# Design Document: Subtask 5.2 - MockSMACrossoverStrategy

**Task**: #5.2 - Implement MockSMACrossoverStrategy with SMA calculation using numpy
**Status**: Design Phase
**Created**: 2025-12-12
**Designer**: Claude Sonnet 4.5

---

## 1. Overview

### Purpose
Implement a concrete SMA (Simple Moving Average) crossover strategy that extends `BaseStrategy` for testing and validation of the trading system pipeline. This strategy demonstrates golden cross (LONG) and death cross (SHORT) signal generation.

### Scope
- **In Scope**:
  - `MockSMACrossoverStrategy` class extending `BaseStrategy`
  - Fast/slow SMA calculation using `numpy.mean()`
  - Golden cross detection (fast SMA crosses above slow SMA)
  - Death cross detection (fast SMA crosses below slow SMA)
  - Risk-reward based TP/SL calculation
  - Duplicate signal prevention

- **Out of Scope**:
  - Advanced technical indicators (RSI, MACD, Bollinger Bands)
  - Machine learning or adaptive strategies
  - Multi-timeframe analysis
  - Production-grade backtesting

### Key Requirements
1. Extend `BaseStrategy` abstract class
2. Use `numpy.mean()` for SMA calculation
3. Detect crossover events (golden/death cross)
4. Generate LONG_ENTRY signals on golden cross
5. Generate SHORT_ENTRY signals on death cross
6. Prevent duplicate consecutive signals
7. Calculate TP based on risk-reward ratio
8. Calculate SL based on percentage

---

## 2. Architecture

### Class Hierarchy
```
BaseStrategy (ABC)
    ↓ (extends)
MockSMACrossoverStrategy
```

### Dependencies
```python
# Standard library
from datetime import datetime, timezone
from typing import Optional

# Third-party
import numpy as np

# Project imports
from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy
```

### File Location
```
src/strategies/mock_strategy.py
```

---

## 3. Class Specification

### MockSMACrossoverStrategy

```python
class MockSMACrossoverStrategy(BaseStrategy):
    """
    SMA Crossover Strategy using fast and slow moving averages.

    Generates LONG signals on golden cross (fast crosses above slow).
    Generates SHORT signals on death cross (fast crosses below slow).
    """
```

#### Constructor

```python
def __init__(self, symbol: str, config: dict) -> None:
    """
    Initialize MockSMACrossoverStrategy with configuration.

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT', 'ETHUSDT')
        config: Configuration dictionary with optional parameters:
            - fast_period (int): Fast SMA period (default: 10)
            - slow_period (int): Slow SMA period (default: 20)
            - risk_reward_ratio (float): TP/SL ratio (default: 2.0)
            - stop_loss_percent (float): SL percentage (default: 0.01)
            - buffer_size (int): Buffer size (default: 100)

    Raises:
        ValueError: If fast_period >= slow_period
    """
```

**Attributes**:
- `fast_period: int` - Fast SMA period (default: 10)
- `slow_period: int` - Slow SMA period (default: 20)
- `risk_reward_ratio: float` - TP/SL ratio (default: 2.0)
- `stop_loss_percent: float` - SL percentage (default: 0.01)
- `_last_signal_type: Optional[SignalType]` - Tracks last signal to prevent duplicates

**Validation**:
- Ensure `fast_period < slow_period`
- Raise `ValueError` if invalid

#### Core Methods

##### 1. analyze()

```python
async def analyze(self, candle: Candle) -> Optional[Signal]:
    """
    Analyze candle for SMA crossover signals.

    Workflow:
    1. Validate candle is closed
    2. Update buffer with new candle
    3. Check buffer has sufficient data (>= slow_period + 1)
    4. Calculate current fast/slow SMAs
    5. Calculate previous fast/slow SMAs (for crossover detection)
    6. Detect golden cross → LONG signal
    7. Detect death cross → SHORT signal
    8. Prevent duplicate signals

    Args:
        candle: Latest candle to analyze

    Returns:
        Signal object if crossover detected, None otherwise
    """
```

**Logic Flow**:
```
1. if not candle.is_closed:
       return None

2. self.update_buffer(candle)

3. if len(self.candle_buffer) < self.slow_period + 1:
       return None  # Need at least slow_period + 1 for crossover

4. close_prices = np.array([c.close for c in self.candle_buffer])

5. current_fast_sma = np.mean(close_prices[-self.fast_period:])
   current_slow_sma = np.mean(close_prices[-self.slow_period:])

6. previous_fast_sma = np.mean(close_prices[-(self.fast_period + 1):-1])
   previous_slow_sma = np.mean(close_prices[-(self.slow_period + 1):-1])

7. # Golden cross detection
   if previous_fast_sma <= previous_slow_sma and current_fast_sma > current_slow_sma:
       if self._last_signal_type == SignalType.LONG_ENTRY:
           return None  # Prevent duplicate LONG
       signal = self._create_signal(candle, SignalType.LONG_ENTRY)
       self._last_signal_type = SignalType.LONG_ENTRY
       return signal

8. # Death cross detection
   if previous_fast_sma >= previous_slow_sma and current_fast_sma < current_slow_sma:
       if self._last_signal_type == SignalType.SHORT_ENTRY:
           return None  # Prevent duplicate SHORT
       signal = self._create_signal(candle, SignalType.SHORT_ENTRY)
       self._last_signal_type = SignalType.SHORT_ENTRY
       return signal

9. return None  # No crossover detected
```

##### 2. _create_signal()

```python
def _create_signal(self, candle: Candle, signal_type: SignalType) -> Signal:
    """
    Create Signal object with calculated TP/SL prices.

    Helper method to construct Signal objects.

    Args:
        candle: Candle that triggered the signal
        signal_type: Type of signal (LONG_ENTRY or SHORT_ENTRY)

    Returns:
        Signal object with entry, TP, SL, and metadata
    """
```

**Logic**:
```python
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

##### 3. calculate_take_profit()

```python
def calculate_take_profit(self, entry_price: float, side: str) -> float:
    """
    Calculate take profit price based on risk-reward ratio.

    Formula:
        SL_distance = entry_price * stop_loss_percent
        TP_distance = SL_distance * risk_reward_ratio

        LONG:  TP = entry + TP_distance
        SHORT: TP = entry - TP_distance

    Args:
        entry_price: Position entry price
        side: 'LONG' or 'SHORT'

    Returns:
        Take profit price (float)
    """
```

**Logic**:
```python
sl_distance = entry_price * self.stop_loss_percent
tp_distance = sl_distance * self.risk_reward_ratio

if side == 'LONG':
    return entry_price + tp_distance
else:  # SHORT
    return entry_price - tp_distance
```

##### 4. calculate_stop_loss()

```python
def calculate_stop_loss(self, entry_price: float, side: str) -> float:
    """
    Calculate stop loss price as percentage of entry price.

    Formula:
        LONG:  SL = entry * (1 - stop_loss_percent)
        SHORT: SL = entry * (1 + stop_loss_percent)

    Args:
        entry_price: Position entry price
        side: 'LONG' or 'SHORT'

    Returns:
        Stop loss price (float)
    """
```

**Logic**:
```python
if side == 'LONG':
    return entry_price * (1 - self.stop_loss_percent)
else:  # SHORT
    return entry_price * (1 + self.stop_loss_percent)
```

---

## 4. Configuration

### Default Configuration
```python
{
    'fast_period': 10,           # Fast SMA period
    'slow_period': 20,           # Slow SMA period
    'risk_reward_ratio': 2.0,    # TP = 2x SL distance
    'stop_loss_percent': 0.01,   # 1% SL
    'buffer_size': 100           # Buffer size (inherited from BaseStrategy)
}
```

### Example Configurations

#### Conservative (Slower signals, tighter risk)
```python
{
    'fast_period': 15,
    'slow_period': 30,
    'risk_reward_ratio': 1.5,
    'stop_loss_percent': 0.005  # 0.5%
}
```

#### Aggressive (Faster signals, wider risk)
```python
{
    'fast_period': 5,
    'slow_period': 10,
    'risk_reward_ratio': 3.0,
    'stop_loss_percent': 0.02  # 2%
}
```

---

## 5. SMA Crossover Detection

### Golden Cross (LONG Entry)
```
Condition:
    previous_fast_sma <= previous_slow_sma  AND
    current_fast_sma > current_slow_sma

Visual:
    t-1:  fast ≤ slow   (below or equal)
    t:    fast > slow   (crossed above)

Signal: LONG_ENTRY
```

### Death Cross (SHORT Entry)
```
Condition:
    previous_fast_sma >= previous_slow_sma  AND
    current_fast_sma < current_slow_sma

Visual:
    t-1:  fast ≥ slow   (above or equal)
    t:    fast < slow   (crossed below)

Signal: SHORT_ENTRY
```

### Duplicate Prevention
```python
# Prevent consecutive LONG signals
if crossover_detected and self._last_signal_type == SignalType.LONG_ENTRY:
    return None

# Prevent consecutive SHORT signals
if crossover_detected and self._last_signal_type == SignalType.SHORT_ENTRY:
    return None

# Update last signal type after generating new signal
self._last_signal_type = signal_type
```

---

## 6. Numpy Integration

### Why numpy.mean()?
- **Performance**: Optimized C implementation (~10x faster than Python loop)
- **Simplicity**: Clean, readable code (`np.mean(prices)` vs manual sum/division)
- **Reliability**: Battle-tested library with proper edge case handling
- **Standards**: Industry standard for numerical computing in Python

### SMA Calculation Pattern
```python
import numpy as np

# Extract close prices from candle buffer
close_prices = np.array([c.close for c in self.candle_buffer])

# Current fast SMA (last 10 candles)
current_fast_sma = np.mean(close_prices[-10:])

# Current slow SMA (last 20 candles)
current_slow_sma = np.mean(close_prices[-20:])

# Previous fast SMA (candles -11 to -1, excluding latest)
previous_fast_sma = np.mean(close_prices[-11:-1])

# Previous slow SMA (candles -21 to -1, excluding latest)
previous_slow_sma = np.mean(close_prices[-21:-1])
```

### Array Slicing Reference
```python
# close_prices = [p0, p1, p2, ..., p18, p19, p20]  # 21 candles

# Last 10 candles (current fast SMA)
close_prices[-10:]     # [p11, p12, ..., p19, p20]

# Last 20 candles (current slow SMA)
close_prices[-20:]     # [p1, p2, ..., p19, p20]

# Previous 10 candles (previous fast SMA, excluding latest p20)
close_prices[-11:-1]   # [p10, p11, ..., p18, p19]

# Previous 20 candles (previous slow SMA, excluding latest p20)
close_prices[-21:-1]   # [p0, p1, ..., p18, p19]
```

---

## 7. Test Strategy

### Unit Tests (`tests/strategies/test_mock_strategy.py`)

#### Test Classes

1. **TestMockSMAInitialization**
   - Test default configuration
   - Test custom configuration
   - Test validation (fast_period >= slow_period raises ValueError)

2. **TestSMACalculation**
   - Test fast SMA calculation accuracy with known dataset
   - Test slow SMA calculation accuracy with known dataset
   - Test SMA calculation with different buffer sizes

3. **TestCrossoverDetection**
   - Test golden cross generates LONG_ENTRY signal
   - Test death cross generates SHORT_ENTRY signal
   - Test no crossover returns None
   - Test duplicate signal prevention (consecutive LONG)
   - Test duplicate signal prevention (consecutive SHORT)

4. **TestBufferRequirements**
   - Test insufficient buffer (< slow_period + 1) returns None
   - Test exact buffer size (== slow_period + 1) works
   - Test buffer with open candle returns None

5. **TestTPSLCalculation**
   - Test TP calculation for LONG (risk-reward ratio)
   - Test TP calculation for SHORT (risk-reward ratio)
   - Test SL calculation for LONG (percentage)
   - Test SL calculation for SHORT (percentage)
   - Test Signal validation passes (TP/SL relationships correct)

### Test Data Patterns

#### Known SMA Dataset
```python
# Prices: [50, 52, 51, 53, 54, 55, 56, 57, 58, 59, 60]
# Fast SMA (period=5): mean([56, 57, 58, 59, 60]) = 58.0
# Slow SMA (period=10): mean([51, 52, ..., 59, 60]) = 55.5

# Expected: Fast (58.0) > Slow (55.5)
```

#### Golden Cross Scenario
```python
# Setup prices to create golden cross
# Previous: fast ≤ slow
# Current: fast > slow

# Prices array creating crossover:
# [..., 48, 49, 50, 51, 52, 53, 54, 55, 56, 62]
#                                          ↑ spike causes crossover
```

#### Death Cross Scenario
```python
# Setup prices to create death cross
# Previous: fast ≥ slow
# Current: fast < slow

# Prices array creating crossover:
# [..., 62, 61, 60, 59, 58, 57, 56, 55, 54, 48]
#                                          ↑ drop causes crossover
```

### Coverage Goals
- **Target**: 100% coverage for MockSMACrossoverStrategy
- **Critical paths**:
  - SMA calculation logic
  - Crossover detection conditions
  - Duplicate prevention logic
  - TP/SL calculation formulas

---

## 8. Integration Points

### TradingEngine Integration
```python
# TradingEngine._on_candle_closed()
async def _on_candle_closed(self, event: Event):
    candle = event.data

    # Calls MockSMACrossoverStrategy.analyze()
    signal = await self.strategy.analyze(candle)

    if signal:
        # Signal generated - emit for order execution
        await self.event_handler.emit(
            Event(EventType.SIGNAL_GENERATED, signal)
        )
```

### Signal Validation
```python
# Signal.__post_init__() validates:
# LONG: take_profit > entry_price AND stop_loss < entry_price
# SHORT: take_profit < entry_price AND stop_loss > entry_price

# MockSMACrossoverStrategy ensures these relationships via:
# - calculate_take_profit(): TP calculated correctly per side
# - calculate_stop_loss(): SL calculated correctly per side
```

---

## 9. Performance Characteristics

### Time Complexity
- `analyze()`: **O(n)** where n = slow_period
  - Array slicing: O(n)
  - numpy.mean(): O(n)
  - Total: 4x O(n) = O(n)

### Space Complexity
- Buffer: **O(buffer_size)** - inherited from BaseStrategy
- Temp arrays: **O(slow_period)** - for numpy operations

### Typical Execution Time
- Buffer size: 100 candles
- Slow period: 20
- Execution: **<5ms** (numpy optimized C code)

---

## 10. Implementation Checklist

### Phase 1: Class Structure
- [ ] Create `MockSMACrossoverStrategy` class extending `BaseStrategy`
- [ ] Implement `__init__()` with configuration parameters
- [ ] Add parameter validation (fast_period < slow_period)
- [ ] Initialize `_last_signal_type` tracking

### Phase 2: Core Logic
- [ ] Implement `analyze()` method
  - [ ] Validate candle is closed
  - [ ] Update buffer
  - [ ] Check buffer size >= slow_period + 1
  - [ ] Calculate current fast/slow SMAs using numpy
  - [ ] Calculate previous fast/slow SMAs
  - [ ] Detect golden cross
  - [ ] Detect death cross
  - [ ] Prevent duplicate signals
- [ ] Implement `_create_signal()` helper method

### Phase 3: TP/SL Calculation
- [ ] Implement `calculate_take_profit()` (risk-reward based)
- [ ] Implement `calculate_stop_loss()` (percentage based)

### Phase 4: Testing
- [ ] Write initialization tests
- [ ] Write SMA calculation accuracy tests
- [ ] Write crossover detection tests
- [ ] Write duplicate prevention tests
- [ ] Write TP/SL calculation tests
- [ ] Verify 100% code coverage

### Phase 5: Documentation
- [ ] Add comprehensive docstrings
- [ ] Add inline comments for complex logic
- [ ] Add usage examples in docstrings

---

## 11. Example Usage

### Basic Usage
```python
from src.strategies.mock_strategy import MockSMACrossoverStrategy
from src.models.candle import Candle

# Create strategy instance
config = {
    'fast_period': 10,
    'slow_period': 20,
    'risk_reward_ratio': 2.0,
    'stop_loss_percent': 0.01
}
strategy = MockSMACrossoverStrategy('BTCUSDT', config)

# Warm up buffer (need slow_period + 1 candles)
for historical_candle in historical_candles[:21]:
    signal = await strategy.analyze(historical_candle)
    # signal will be None during warm-up

# Analyze new candles
candle = new_candle_from_exchange()
signal = await strategy.analyze(candle)

if signal:
    if signal.signal_type == SignalType.LONG_ENTRY:
        print(f"Golden cross detected: BUY at {signal.entry_price}")
        print(f"TP: {signal.take_profit}, SL: {signal.stop_loss}")
    elif signal.signal_type == SignalType.SHORT_ENTRY:
        print(f"Death cross detected: SELL at {signal.entry_price}")
        print(f"TP: {signal.take_profit}, SL: {signal.stop_loss}")
```

### TradingEngine Integration
```python
from src.core.trading_engine import TradingEngine
from src.strategies.mock_strategy import MockSMACrossoverStrategy

# Create engine
engine = TradingEngine(config)

# Create and inject strategy
strategy_config = {'fast_period': 10, 'slow_period': 20}
strategy = MockSMACrossoverStrategy('BTCUSDT', strategy_config)
engine.set_strategy(strategy)

# Run engine (auto-calls strategy.analyze() for each candle)
await engine.run()
```

---

## 12. Risk Assessment

### Low Risk
- ✅ Simple, well-tested SMA calculation
- ✅ Clear crossover detection logic
- ✅ Numpy library reliability
- ✅ Comprehensive test coverage

### Medium Risk
- ⚠️ Whipsaw in ranging markets (false signals)
- ⚠️ Lagging indicator (delayed entry/exit)
- ⚠️ Parameter sensitivity (fast/slow periods)

### Mitigation
- Unit tests cover edge cases
- Integration tests with various market conditions
- Clear documentation of limitations
- This is a **mock strategy for testing**, not production

---

## 13. Future Enhancements (Out of Scope)

- Exponential Moving Average (EMA) support
- Volume-weighted moving averages
- Multi-timeframe confirmation
- Trend strength indicators
- Dynamic parameter optimization
- Advanced risk management (ATR-based SL)

---

**Design Complete**: Ready for implementation phase
**Next Step**: `/sc:implement --serena`
