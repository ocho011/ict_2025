# Task #5 Design: Mock Strategy & Signal Generation Pipeline

**Task ID:** 5
**Design Date:** 2025-12-12
**Status:** Design Complete - Ready for Implementation
**Dependencies:** Task 2 (Models), Task 3 (Data Collector), Task 4 (Event Architecture)

---

## 1. Design Overview

### 1.1 Purpose

Implement a complete strategy framework with a simple mock SMA crossover strategy to:
1. Validate the end-to-end data-to-signal pipeline (Candle → Strategy → Signal)
2. Provide abstract base class for future ICT strategy implementations
3. Enable integration testing of TradingEngine event flow
4. Establish strategy instantiation patterns (Factory pattern)

**Critical Insight:** This is NOT a production trading strategy - it's a testing framework that validates the trading pipeline works correctly before implementing complex ICT indicators.

### 1.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Strategy Architecture                         │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  src/strategies/                                                  │
├──────────────────────────────────────────────────────────────────┤
│  __init__.py                                                      │
│    ├─ from .base import BaseStrategy                             │
│    ├─ from .mock_strategy import MockSMACrossoverStrategy        │
│    └─ from .factory import StrategyFactory                       │
│                                                                   │
│  base.py         (Abstract Strategy Interface)                   │
│    └─ BaseStrategy(ABC)                                          │
│         ├─ __init__(symbol, config)                              │
│         ├─ update_buffer(candle) → None                          │
│         ├─ analyze(candle) → Optional[Signal]  [abstract]        │
│         ├─ calculate_take_profit() → float  [abstract]           │
│         └─ calculate_stop_loss() → float  [abstract]             │
│                                                                   │
│  mock_strategy.py    (Test Strategy Implementation)              │
│    └─ MockSMACrossoverStrategy(BaseStrategy)                     │
│         ├─ __init__(symbol, config)                              │
│         ├─ analyze(candle) → Optional[Signal]                    │
│         ├─ _create_signal(type, price) → Signal                  │
│         ├─ calculate_take_profit(price, side) → float            │
│         └─ calculate_stop_loss(price, side) → float              │
│                                                                   │
│  factory.py     (Strategy Instantiation)                         │
│    └─ StrategyFactory                                            │
│         ├─ _strategies: Dict[str, Type[BaseStrategy]]            │
│         └─ create(name, symbol, config) → BaseStrategy           │
└──────────────────────────────────────────────────────────────────┘

Integration Points:
┌────────────────┐    set_strategy()    ┌────────────────┐
│ TradingEngine  │ ──────────────────> │  BaseStrategy  │
└────────┬───────┘                      └────────┬───────┘
         │                                       │
         │ _on_candle_closed(event)              │
         │ ───> strategy.analyze(candle)         │
         │                                       │
         │ <─── Optional[Signal]                 │
         │                                       │
         │ event_bus.publish(Signal, 'signal')   │
         └───────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 BaseStrategy (Abstract Base Class)

**File:** `src/strategies/base.py`

**Purpose:** Define the strategy interface contract that all strategies must implement.

**Class Definition:**

```python
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from src.models.candle import Candle
from src.models.signal import Signal


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Provides:
    - Candle buffer management for historical data access
    - Standard interface for signal generation
    - Configuration management

    Subclasses must implement:
    - analyze(): Main strategy logic
    - calculate_take_profit(): TP calculation
    - calculate_stop_loss(): SL calculation

    Example:
        ```python
        class MyStrategy(BaseStrategy):
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                if not candle.is_closed:
                    return None
                self.update_buffer(candle)
                # ... strategy logic ...
                return Signal(...) if conditions_met else None
        ```
    """

    def __init__(self, symbol: str, config: dict) -> None:
        """
        Initialize strategy with symbol and configuration.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            config: Strategy configuration dict with:
                - buffer_size: Max candles to store (default: 100)
                - Additional strategy-specific parameters

        Attributes:
            symbol: Trading pair this strategy analyzes
            config: Configuration dictionary
            candle_buffer: List of historical candles (FIFO)
            buffer_size: Maximum buffer capacity
        """
        self.symbol = symbol
        self.config = config
        self.candle_buffer: List[Candle] = []
        self.buffer_size: int = config.get('buffer_size', 100)

    def update_buffer(self, candle: Candle) -> None:
        """
        Add candle to buffer, maintaining max size via FIFO.

        Buffer Management:
        - Appends new candle to end of list
        - If buffer exceeds buffer_size, removes oldest (index 0)
        - Maintains chronological order (oldest first, newest last)

        Args:
            candle: New candle to add to history

        Example:
            ```python
            # buffer_size = 3, buffer = [c1, c2, c3]
            strategy.update_buffer(c4)
            # Result: buffer = [c2, c3, c4]  (c1 removed)
            ```

        Notes:
            - Called automatically by analyze() in most strategies
            - Buffer persists across analyze() calls
            - No validation - assumes candle chronological order
        """
        self.candle_buffer.append(candle)
        if len(self.candle_buffer) > self.buffer_size:
            self.candle_buffer.pop(0)  # Remove oldest

    @abstractmethod
    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle and generate trading signal if conditions met.

        Contract:
        - Called by TradingEngine._on_candle_closed() for each new candle
        - Must be async (supports I/O operations if needed)
        - Returns Signal object if trading opportunity detected
        - Returns None if no signal conditions met

        Args:
            candle: Latest candle to analyze

        Returns:
            Signal object with entry/TP/SL prices, or None

        Implementation Guidelines:
        1. Check candle.is_closed (only analyze complete candles)
        2. Call update_buffer(candle) to add to history
        3. Verify buffer has enough data for calculations
        4. Apply strategy logic (indicators, patterns, etc.)
        5. If conditions met, create Signal via calculate_take_profit/stop_loss
        6. Return Signal or None

        Error Handling:
        - Exceptions logged by TradingEngine, don't re-raise
        - Invalid calculations should return None, not raise

        Example:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                if not candle.is_closed:
                    return None

                self.update_buffer(candle)

                if len(self.candle_buffer) < self.min_periods:
                    return None

                if self._detect_buy_signal():
                    return Signal(
                        signal_type=SignalType.LONG_ENTRY,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        take_profit=self.calculate_take_profit(candle.close, 'LONG'),
                        stop_loss=self.calculate_stop_loss(candle.close, 'LONG'),
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.utcnow()
                    )

                return None
            ```
        """
        pass

    @abstractmethod
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price for a position.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Take profit price (float)

        Validation:
        - LONG: TP must be > entry_price
        - SHORT: TP must be < entry_price
        - Signal model validates this in __post_init__

        Example:
            ```python
            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                risk = entry_price * self.stop_loss_percent
                reward = risk * self.risk_reward_ratio
                return entry_price + reward if side == 'LONG' else entry_price - reward
            ```
        """
        pass

    @abstractmethod
    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price for a position.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Stop loss price (float)

        Validation:
        - LONG: SL must be < entry_price
        - SHORT: SL must be > entry_price
        - Signal model validates this in __post_init__

        Example:
            ```python
            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                risk = entry_price * self.stop_loss_percent
                return entry_price - risk if side == 'LONG' else entry_price + risk
            ```
        """
        pass
```

**Design Rationale:**
- **ABC (Abstract Base Class)**: Enforces interface contract for all strategies
- **Buffer Management**: Centralized in base class (common to all strategies)
- **Configuration Dict**: Flexible, supports any strategy-specific params
- **Async analyze()**: Supports future strategies that need I/O (API calls, etc.)

---

### 2.2 MockSMACrossoverStrategy (Test Implementation)

**File:** `src/strategies/mock_strategy.py`

**Purpose:** Simple Moving Average crossover strategy for pipeline validation.

**Algorithm:** Golden/Death Cross Detection
- **Golden Cross** (Bullish): Fast SMA crosses above Slow SMA → LONG_ENTRY
- **Death Cross** (Bearish): Fast SMA crosses below Slow SMA → SHORT_ENTRY

**Class Definition:**

```python
import numpy as np
from datetime import datetime, timezone
from typing import Optional
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


class MockSMACrossoverStrategy(BaseStrategy):
    """
    Simple Moving Average crossover strategy for testing.

    **WARNING:** This is a mock strategy for pipeline validation only.
    NOT suitable for production trading - lacks risk management, filtering, etc.

    Algorithm:
    - Calculate fast SMA (default: 10 periods)
    - Calculate slow SMA (default: 20 periods)
    - Detect crossover:
        * Golden Cross: fast crosses above slow → LONG_ENTRY
        * Death Cross: fast crosses below slow → SHORT_ENTRY

    Signal Generation:
    - Entry: Current candle close price
    - Stop Loss: Percentage-based (default: 1%)
    - Take Profit: Risk-reward ratio (default: 2:1)

    Configuration:
        ```python
        config = {
            'buffer_size': 100,        # Max candles in history
            'fast_period': 10,         # Fast SMA periods
            'slow_period': 20,         # Slow SMA periods
            'risk_reward_ratio': 2.0,  # TP:SL ratio
            'stop_loss_percent': 0.01  # 1% stop loss
        }
        ```

    Example Usage:
        ```python
        strategy = MockSMACrossoverStrategy('BTCUSDT', config)
        signal = await strategy.analyze(candle)
        if signal:
            print(f"Signal: {signal.signal_type.value} at {signal.entry_price}")
        ```
    """

    def __init__(self, symbol: str, config: dict) -> None:
        """
        Initialize SMA crossover strategy.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            config: Configuration dict with optional keys:
                - fast_period (int): Fast SMA periods (default: 10)
                - slow_period (int): Slow SMA periods (default: 20)
                - risk_reward_ratio (float): TP:SL ratio (default: 2.0)
                - stop_loss_percent (float): SL % (default: 0.01)
                - buffer_size (int): Max candles (default: 100)

        Attributes:
            fast_period: Fast SMA calculation periods
            slow_period: Slow SMA calculation periods
            risk_reward_ratio: Take profit to stop loss ratio
            stop_loss_percent: Stop loss as decimal (0.01 = 1%)
            _last_signal_type: Prevents duplicate consecutive signals
        """
        super().__init__(symbol, config)

        # SMA configuration
        self.fast_period: int = config.get('fast_period', 10)
        self.slow_period: int = config.get('slow_period', 20)

        # Risk management configuration
        self.risk_reward_ratio: float = config.get('risk_reward_ratio', 2.0)
        self.stop_loss_percent: float = config.get('stop_loss_percent', 0.01)

        # State tracking
        self._last_signal_type: Optional[SignalType] = None

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle for SMA crossover signals.

        Process:
        1. Validate candle is closed
        2. Update buffer with new candle
        3. Verify buffer has enough data (>= slow_period)
        4. Calculate current and previous SMAs
        5. Detect crossover (golden/death cross)
        6. Generate signal if conditions met

        Args:
            candle: Latest candle from data collector

        Returns:
            Signal object if crossover detected, None otherwise

        Crossover Detection:
            Golden Cross (Bullish):
                prev_fast <= prev_slow AND fast_sma > slow_sma
                → Generate LONG_ENTRY signal

            Death Cross (Bearish):
                prev_fast >= prev_slow AND fast_sma < slow_sma
                → Generate SHORT_ENTRY signal

        Signal Deduplication:
            _last_signal_type prevents consecutive duplicate signals.
            If already in LONG, don't generate another LONG until SHORT.

        Example:
            ```python
            # Candle closes, fast SMA crosses above slow SMA
            signal = await strategy.analyze(candle)
            # Returns: Signal(LONG_ENTRY, entry=50000, tp=51000, sl=49500)

            # Next candle, still bullish (no crossover)
            signal = await strategy.analyze(next_candle)
            # Returns: None (already in LONG position)
            ```

        Notes:
            - Only analyzes closed candles (candle.is_closed == True)
            - Returns None if insufficient data for SMA calculation
            - Uses numpy for efficient SMA calculation
        """
        # Only analyze complete candles
        if not candle.is_closed:
            return None

        # Add to historical buffer
        self.update_buffer(candle)

        # Need enough data for slow SMA calculation
        if len(self.candle_buffer) < self.slow_period:
            return None

        # Extract close prices as numpy array
        closes = np.array([c.close for c in self.candle_buffer])

        # Calculate current SMAs
        fast_sma = np.mean(closes[-self.fast_period:])
        slow_sma = np.mean(closes[-self.slow_period:])

        # Calculate previous period SMAs (for crossover detection)
        prev_fast = np.mean(closes[-self.fast_period-1:-1])
        prev_slow = np.mean(closes[-self.slow_period-1:-1])

        # Golden cross detection (bullish)
        if prev_fast <= prev_slow and fast_sma > slow_sma:
            # Prevent duplicate signals
            if self._last_signal_type != SignalType.LONG_ENTRY:
                self._last_signal_type = SignalType.LONG_ENTRY
                return self._create_signal(SignalType.LONG_ENTRY, candle.close)

        # Death cross detection (bearish)
        if prev_fast >= prev_slow and fast_sma < slow_sma:
            # Prevent duplicate signals
            if self._last_signal_type != SignalType.SHORT_ENTRY:
                self._last_signal_type = SignalType.SHORT_ENTRY
                return self._create_signal(SignalType.SHORT_ENTRY, candle.close)

        # No crossover detected
        return None

    def _create_signal(self, signal_type: SignalType, price: float) -> Signal:
        """
        Create Signal object with calculated TP/SL prices.

        Args:
            signal_type: LONG_ENTRY or SHORT_ENTRY
            price: Entry price (current candle close)

        Returns:
            Fully configured Signal object

        Signal Construction:
            - Entry: Current candle close price
            - Side: Derived from signal_type
            - TP: calculate_take_profit(price, side)
            - SL: calculate_stop_loss(price, side)
            - Strategy Name: 'MockSMACrossover'
            - Timestamp: UTC now

        Example:
            Entry: $50,000, SL: 1%, RR: 2:1
            → SL: $49,500, TP: $51,000
        """
        side = 'LONG' if signal_type == SignalType.LONG_ENTRY else 'SHORT'

        return Signal(
            signal_type=signal_type,
            symbol=self.symbol,
            entry_price=price,
            take_profit=self.calculate_take_profit(price, side),
            stop_loss=self.calculate_stop_loss(price, side),
            strategy_name='MockSMACrossover',
            timestamp=datetime.now(timezone.utc)
        )

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price based on risk-reward ratio.

        Formula:
            risk = entry_price * stop_loss_percent
            reward = risk * risk_reward_ratio
            TP = entry_price + reward (LONG) or entry_price - reward (SHORT)

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Take profit price

        Example:
            Entry: $50,000
            SL %: 1% (0.01)
            RR: 2:1

            LONG:
                risk = 50000 * 0.01 = $500
                reward = 500 * 2 = $1,000
                TP = 50000 + 1000 = $51,000

            SHORT:
                risk = 50000 * 0.01 = $500
                reward = 500 * 2 = $1,000
                TP = 50000 - 1000 = $49,000

        Validation:
            Signal model validates:
            - LONG: TP > entry_price
            - SHORT: TP < entry_price
        """
        risk = entry_price * self.stop_loss_percent
        reward = risk * self.risk_reward_ratio

        if side == 'LONG':
            return entry_price + reward
        else:  # SHORT
            return entry_price - reward

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price based on percentage.

        Formula:
            risk = entry_price * stop_loss_percent
            SL = entry_price - risk (LONG) or entry_price + risk (SHORT)

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Stop loss price

        Example:
            Entry: $50,000
            SL %: 1% (0.01)

            LONG:
                risk = 50000 * 0.01 = $500
                SL = 50000 - 500 = $49,500

            SHORT:
                risk = 50000 * 0.01 = $500
                SL = 50000 + 500 = $50,500

        Validation:
            Signal model validates:
            - LONG: SL < entry_price
            - SHORT: SL > entry_price
        """
        risk = entry_price * self.stop_loss_percent

        if side == 'LONG':
            return entry_price - risk
        else:  # SHORT
            return entry_price + risk
```

**Design Rationale:**
- **Simplicity**: Easy to understand and test (validates pipeline, not trading performance)
- **Numpy**: Efficient array operations for SMA calculation
- **Signal Deduplication**: `_last_signal_type` prevents spam signals
- **Configurable Risk**: Supports different RR ratios and SL percentages for testing

---

### 2.3 StrategyFactory (Instantiation Pattern)

**File:** `src/strategies/factory.py` or `src/strategies/__init__.py`

**Purpose:** Centralized strategy registration and instantiation.

**Class Definition:**

```python
from typing import Dict, Type
from src.strategies.base import BaseStrategy
from src.strategies.mock_strategy import MockSMACrossoverStrategy


class StrategyFactory:
    """
    Factory for creating strategy instances.

    Pattern: Registry Pattern + Factory Pattern
    - Maintains registry of available strategies
    - Provides clean instantiation interface
    - Validates strategy existence before creation

    Usage:
        ```python
        # Register strategy (done automatically)
        StrategyFactory._strategies = {'mock_sma': MockSMACrossoverStrategy}

        # Create strategy instance
        strategy = StrategyFactory.create(
            name='mock_sma',
            symbol='BTCUSDT',
            config={'fast_period': 10, 'slow_period': 20}
        )
        ```

    Extension:
        ```python
        # Future: Add ICT strategy
        from src.strategies.ict_fvg import ICTFVGStrategy

        StrategyFactory._strategies['ict_fvg'] = ICTFVGStrategy
        strategy = StrategyFactory.create('ict_fvg', 'ETHUSDT', config)
        ```
    """

    # Strategy registry (class-level dictionary)
    _strategies: Dict[str, Type[BaseStrategy]] = {
        'mock_sma': MockSMACrossoverStrategy,
        # Future strategies will be added here:
        # 'ict_fvg': ICTFVGStrategy,
        # 'ict_breaker': ICTBreakerStrategy,
    }

    @classmethod
    def create(cls, name: str, symbol: str, config: dict) -> BaseStrategy:
        """
        Create and return a strategy instance.

        Args:
            name: Strategy identifier (e.g., 'mock_sma', 'ict_fvg')
            symbol: Trading pair for strategy (e.g., 'BTCUSDT')
            config: Strategy configuration dict

        Returns:
            Configured strategy instance

        Raises:
            ValueError: If strategy name not found in registry

        Example:
            ```python
            # Create mock SMA strategy
            strategy = StrategyFactory.create(
                name='mock_sma',
                symbol='BTCUSDT',
                config={
                    'fast_period': 10,
                    'slow_period': 20,
                    'risk_reward_ratio': 2.0,
                    'stop_loss_percent': 0.01
                }
            )

            # Use with TradingEngine
            engine = TradingEngine(config)
            engine.set_strategy(strategy)
            ```

        Validation:
            - Strategy name must exist in _strategies registry
            - Descriptive error message if not found
            - Lists available strategies in error
        """
        if name not in cls._strategies:
            available = ', '.join(cls._strategies.keys())
            raise ValueError(
                f"Unknown strategy: '{name}'. "
                f"Available strategies: {available}"
            )

        # Instantiate and return strategy
        strategy_class = cls._strategies[name]
        return strategy_class(symbol, config)

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseStrategy]) -> None:
        """
        Register a new strategy (optional helper method).

        Args:
            name: Strategy identifier
            strategy_class: Strategy class (must inherit BaseStrategy)

        Example:
            ```python
            # Dynamic registration (for plugins, etc.)
            StrategyFactory.register('custom_rsi', CustomRSIStrategy)
            strategy = StrategyFactory.create('custom_rsi', 'BTCUSDT', config)
            ```
        """
        cls._strategies[name] = strategy_class

    @classmethod
    def list_strategies(cls) -> list[str]:
        """
        List all available strategy names.

        Returns:
            List of registered strategy identifiers

        Example:
            ```python
            strategies = StrategyFactory.list_strategies()
            print(f"Available: {', '.join(strategies)}")
            # Output: "Available: mock_sma"
            ```
        """
        return list(cls._strategies.keys())
```

**Design Rationale:**
- **Registry Pattern**: Centralized strategy registration
- **Class Methods**: No need to instantiate factory
- **Extensibility**: Easy to add new strategies (just add to `_strategies`)
- **Validation**: Clear error messages for invalid strategy names

---

## 3. Integration with Existing System

### 3.1 TradingEngine Integration

**Current Interface** (from Task #4):
```python
class TradingEngine:
    def set_strategy(self, strategy: Any) -> None:
        """Inject Strategy component for signal generation."""
        self.strategy = strategy
        self.logger.info(f"Strategy injected: {type(strategy).__name__}")

    async def _on_candle_closed(self, event: Event) -> None:
        """Handle CANDLE_CLOSED event: Analyze candle and generate signal."""
        candle: Candle = event.data

        if not self.strategy:
            self.logger.warning("No strategy configured, skipping analysis")
            return

        # Call strategy.analyze() - returns Optional[Signal]
        signal: Optional[Signal] = await self.strategy.analyze(candle)

        if signal:
            self.logger.info(f"Signal generated: {signal.signal_type.value}")
            await self.event_bus.publish(
                Event(EventType.SIGNAL_GENERATED, signal, source='TradingEngine'),
                queue_name='signal'
            )
```

**Integration Example:**
```python
# main.py or integration test
from src.core.trading_engine import TradingEngine
from src.strategies.factory import StrategyFactory

# Configuration
config = {
    'environment': 'testnet',
    'log_level': 'DEBUG'
}

strategy_config = {
    'fast_period': 10,
    'slow_period': 20,
    'risk_reward_ratio': 2.0,
    'stop_loss_percent': 0.01
}

# Create strategy via factory
strategy = StrategyFactory.create('mock_sma', 'BTCUSDT', strategy_config)

# Inject into TradingEngine
engine = TradingEngine(config)
engine.set_strategy(strategy)

# Engine will call strategy.analyze() for each candle
await engine.run()
```

### 3.2 Event Flow Validation

```
1. BinanceDataCollector receives WebSocket candle
   ↓
2. Publishes CANDLE_CLOSED event to 'data' queue
   ↓
3. EventBus routes to TradingEngine._on_candle_closed()
   ↓
4. TradingEngine calls strategy.analyze(candle)
   ↓
5. MockSMACrossoverStrategy:
   a. Updates buffer with candle
   b. Calculates fast/slow SMAs
   c. Detects crossover (if any)
   d. Returns Signal object (or None)
   ↓
6. TradingEngine publishes Signal to 'signal' queue
   ↓
7. Future: OrderManager receives Signal event
```

---

## 4. Test Strategy

### 4.1 Unit Tests

**File:** `tests/strategies/test_base_strategy.py`

```python
class TestBaseStrategy:
    """Test BaseStrategy abstract class."""

    def test_init_creates_buffer():
        """Verify __init__ initializes buffer with default size."""
        # Test default buffer_size = 100
        # Test custom buffer_size from config

    def test_update_buffer_fifo():
        """Verify buffer FIFO behavior when exceeding max size."""
        # Add buffer_size + 1 candles
        # Verify oldest candle removed
        # Verify newest candle at end

    def test_abstract_methods_raise():
        """Verify abstract methods raise NotImplementedError."""
        # Try to instantiate BaseStrategy directly
        # Should raise TypeError (cannot instantiate ABC)

    def test_buffer_maintains_order():
        """Verify candles stored in chronological order."""
        # Add multiple candles
        # Verify buffer[0] is oldest, buffer[-1] is newest
```

**File:** `tests/strategies/test_mock_strategy.py`

```python
class TestMockSMACrossover:
    """Test MockSMACrossoverStrategy implementation."""

    @pytest.mark.asyncio
    async def test_sma_calculation_accuracy():
        """Verify SMA calculation with known dataset."""
        # Create strategy with known fast/slow periods
        # Feed known candle data
        # Compare calculated SMAs with expected values
        # Use numpy.testing.assert_almost_equal()

    @pytest.mark.asyncio
    async def test_golden_cross_generates_long():
        """Verify golden cross generates LONG_ENTRY signal."""
        # Feed candles: fast SMA < slow SMA
        # Then feed candles: fast SMA > slow SMA (crossover)
        # Verify LONG_ENTRY signal returned
        # Verify signal has correct TP/SL

    @pytest.mark.asyncio
    async def test_death_cross_generates_short():
        """Verify death cross generates SHORT_ENTRY signal."""
        # Feed candles: fast SMA > slow SMA
        # Then feed candles: fast SMA < slow SMA (crossover)
        # Verify SHORT_ENTRY signal returned

    @pytest.mark.asyncio
    async def test_no_duplicate_signals():
        """Verify no consecutive duplicate signals."""
        # Generate LONG signal
        # Continue with bullish trend (no crossover)
        # Verify subsequent analyze() returns None
        # Verify _last_signal_type prevents duplicates

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none():
        """Verify returns None with insufficient buffer data."""
        # Create strategy with slow_period = 20
        # Feed only 10 candles
        # Verify analyze() returns None

    @pytest.mark.asyncio
    async def test_unclosed_candle_returns_none():
        """Verify unclosed candles are ignored."""
        # Create candle with is_closed = False
        # Call analyze()
        # Verify returns None

    def test_calculate_stop_loss_long():
        """Verify SL calculation for LONG positions."""
        # Entry: $50,000, SL %: 1%
        # Expected SL: $49,500
        # Verify calculation correct

    def test_calculate_stop_loss_short():
        """Verify SL calculation for SHORT positions."""
        # Entry: $50,000, SL %: 1%
        # Expected SL: $50,500

    def test_calculate_take_profit_long():
        """Verify TP calculation for LONG with 2:1 RR."""
        # Entry: $50,000, SL: 1%, RR: 2:1
        # Risk: $500, Reward: $1,000
        # Expected TP: $51,000

    def test_calculate_take_profit_short():
        """Verify TP calculation for SHORT with 2:1 RR."""
        # Entry: $50,000, SL: 1%, RR: 2:1
        # Expected TP: $49,000

    def test_signal_validation():
        """Verify Signal object passes model validation."""
        # Create signal via _create_signal()
        # Verify Signal.__post_init__() doesn't raise
        # Verify LONG: TP > entry, SL < entry
        # Verify SHORT: TP < entry, SL > entry
```

**File:** `tests/strategies/test_factory.py`

```python
class TestStrategyFactory:
    """Test StrategyFactory pattern."""

    def test_create_mock_sma_strategy():
        """Verify successful creation of mock_sma strategy."""
        # Create strategy via factory
        # Verify instance is MockSMACrossoverStrategy
        # Verify symbol and config passed correctly

    def test_create_unknown_strategy_raises():
        """Verify ValueError for unknown strategy name."""
        # Try to create non-existent strategy
        # Verify ValueError raised
        # Verify error message lists available strategies

    def test_list_strategies():
        """Verify list_strategies() returns registered names."""
        # Call StrategyFactory.list_strategies()
        # Verify 'mock_sma' in list

    def test_register_custom_strategy():
        """Verify custom strategy registration."""
        # Create dummy strategy class
        # Register via StrategyFactory.register()
        # Verify can create instance via create()
```

### 4.2 Integration Tests

**File:** `tests/integration/test_strategy_pipeline.py`

```python
class TestStrategyPipeline:
    """End-to-end strategy pipeline tests."""

    @pytest.mark.asyncio
    async def test_full_pipeline_candle_to_signal():
        """Integration: Candle → Strategy → Signal → EventBus."""
        # Create TradingEngine with MockSMACrossover
        # Mock EventBus.publish to capture signals
        # Feed candles that trigger crossover
        # Verify Signal published to 'signal' queue
        # Verify Signal has correct data

    @pytest.mark.asyncio
    async def test_historical_data_golden_cross():
        """Test with real historical data (golden cross)."""
        # Load historical candle CSV/JSON
        # Feed to strategy sequentially
        # Verify expected signals generated
        # Compare with manual SMA calculation

    @pytest.mark.asyncio
    async def test_strategy_error_isolation():
        """Verify strategy errors don't crash TradingEngine."""
        # Mock strategy.analyze() to raise exception
        # Call TradingEngine._on_candle_closed()
        # Verify exception caught and logged
        # Verify TradingEngine continues running
```

### 4.3 Coverage Goals

```
Target Coverage: >90% for all strategy modules

src/strategies/base.py:          100% (simple ABC, all paths testable)
src/strategies/mock_strategy.py:  95% (edge cases, error handling)
src/strategies/factory.py:       100% (simple factory, full coverage)
```

---

## 5. Performance Considerations

### 5.1 Buffer Management

**Current Approach:** Python list with `pop(0)` for FIFO
- **Complexity:** O(n) for `pop(0)` (shifts all elements)
- **Impact:** Negligible for buffer_size=100 (< 1ms)
- **Alternative:** `collections.deque` with `maxlen` (O(1) append/pop)

**Recommendation:** Start with list, optimize to deque if profiling shows bottleneck.

### 5.2 SMA Calculation

**Current Approach:** Numpy array operations
- **Complexity:** O(n) for `np.mean(array[-period:])`
- **Impact:** Fast for small periods (10-20 candles)
- **Optimization:** Could use rolling window with cached sums (O(1) update)

**Recommendation:** Numpy sufficient for mock strategy, optimize for production ICT indicators.

### 5.3 Memory Footprint

```
Per Strategy Instance:
- Buffer: 100 candles × ~200 bytes ≈ 20 KB
- Config: < 1 KB
- Instance variables: < 1 KB
Total: ~22 KB per strategy

For 10 strategies: ~220 KB (negligible)
```

---

## 6. Security & Error Handling

### 6.1 Input Validation

**Candle Validation:**
- TradingEngine checks `candle.is_closed` before calling strategy
- Strategy double-checks in `analyze()` (defensive)
- Signal model validates TP/SL relationship in `__post_init__()`

**Configuration Validation:**
```python
# Add to MockSMACrossoverStrategy.__init__()
if self.fast_period >= self.slow_period:
    raise ValueError(f"fast_period ({self.fast_period}) must be < slow_period ({self.slow_period})")

if self.risk_reward_ratio <= 0:
    raise ValueError(f"risk_reward_ratio must be > 0, got {self.risk_reward_ratio}")

if self.stop_loss_percent <= 0 or self.stop_loss_percent >= 1:
    raise ValueError(f"stop_loss_percent must be 0 < x < 1, got {self.stop_loss_percent}")
```

### 6.2 Error Isolation

**Exception Handling:**
- Strategy exceptions caught by TradingEngine (`try-except` in `_on_candle_closed`)
- Logged but don't crash engine
- Strategy returns `None` for invalid conditions (don't raise)

**Example:**
```python
# In MockSMACrossoverStrategy.analyze()
try:
    fast_sma = np.mean(closes[-self.fast_period:])
    slow_sma = np.mean(closes[-self.slow_period:])
except Exception as e:
    self.logger.error(f"SMA calculation error: {e}")
    return None  # Don't crash, just skip this candle
```

---

## 7. Future Extensions

### 7.1 ICT Strategy Integration

```python
# src/strategies/ict_fvg.py (future)
class ICTFVGStrategy(BaseStrategy):
    """Fair Value Gap detection strategy."""

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        # Detect bullish/bearish FVG
        # Validate with higher timeframe structure
        # Return signal if valid setup
        pass
```

**Factory Registration:**
```python
StrategyFactory._strategies['ict_fvg'] = ICTFVGStrategy
```

### 7.2 Strategy Composition

```python
# Future: Combine multiple strategies
class CompositeStrategy(BaseStrategy):
    """Run multiple strategies, aggregate signals."""

    def __init__(self, symbol: str, config: dict):
        super().__init__(symbol, config)
        self.strategies = [
            StrategyFactory.create('mock_sma', symbol, config),
            StrategyFactory.create('ict_fvg', symbol, config)
        ]

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        # Analyze with all strategies
        # Aggregate signals (consensus, voting, etc.)
        pass
```

### 7.3 Strategy Metrics

```python
# Future: Track strategy performance
class StrategyMetrics:
    """Track signal accuracy, win rate, etc."""

    def record_signal(self, signal: Signal):
        # Store signal for later analysis
        pass

    def record_outcome(self, signal: Signal, pnl: float):
        # Track if TP/SL hit, calculate win rate
        pass
```

---

## 8. Implementation Checklist

### Phase 1: BaseStrategy (Subtask 5.1)
- [ ] Create `src/strategies/__init__.py` with exports
- [ ] Create `src/strategies/base.py`
- [ ] Implement `BaseStrategy` class with all methods and docstrings
- [ ] Write unit tests for buffer management
- [ ] Verify abstract methods enforce implementation
- [ ] Run tests, achieve 100% coverage

### Phase 2: MockSMACrossover (Subtask 5.2)
- [ ] Create `src/strategies/mock_strategy.py`
- [ ] Implement `MockSMACrossoverStrategy.__init__()`
- [ ] Implement `analyze()` with SMA calculation and crossover detection
- [ ] Implement `_create_signal()` helper
- [ ] Write unit tests for SMA calculation accuracy
- [ ] Write tests for golden/death cross detection
- [ ] Test signal deduplication logic
- [ ] Run tests, achieve >95% coverage

### Phase 3: TP/SL Calculations (Subtask 5.3)
- [ ] Implement `calculate_take_profit()` for LONG/SHORT
- [ ] Implement `calculate_stop_loss()` for LONG/SHORT
- [ ] Write unit tests for LONG calculations
- [ ] Write unit tests for SHORT calculations
- [ ] Test edge cases (various entry prices, percentages)
- [ ] Verify Signal model validation passes
- [ ] Run tests, achieve 100% coverage

### Phase 4: StrategyFactory (Subtask 5.4)
- [ ] Create `src/strategies/factory.py`
- [ ] Implement `StrategyFactory` with registry
- [ ] Implement `create()` classmethod
- [ ] Implement `register()` and `list_strategies()` helpers
- [ ] Write unit tests for successful creation
- [ ] Test error handling for unknown strategies
- [ ] Run tests, achieve 100% coverage

### Phase 5: Integration Testing
- [ ] Write integration test: Candle → Strategy → Signal
- [ ] Test with historical candle data
- [ ] Test with TradingEngine (end-to-end)
- [ ] Verify EventBus receives signals correctly
- [ ] Test error isolation (strategy exception handling)
- [ ] Run all tests, verify >90% total coverage

### Phase 6: Documentation & Review
- [ ] Add docstrings to all classes and methods
- [ ] Create usage examples in docstrings
- [ ] Update `src/strategies/__init__.py` exports
- [ ] Write integration example in `scripts/` or `examples/`
- [ ] Code review checklist
- [ ] Mark Task 5 as complete

---

## 9. Design Validation

### 9.1 Requirements Coverage

| Requirement | Implementation | Validation |
|-------------|----------------|------------|
| Abstract strategy interface | BaseStrategy ABC | Abstract methods enforced |
| Candle buffer management | update_buffer() in base class | Unit tests verify FIFO |
| SMA crossover logic | MockSMACrossoverStrategy | Golden/death cross tests |
| TP/SL calculations | calculate_take_profit/stop_loss | Math unit tests |
| Configurable parameters | Config dict pattern | Tests with various configs |
| Strategy factory | StrategyFactory.create() | Registration tests |
| TradingEngine integration | set_strategy() injection | Integration tests |

### 9.2 Design Principles

✅ **SOLID Principles:**
- **S**ingle Responsibility: Each class has one clear purpose
- **O**pen/Closed: Extensible via BaseStrategy inheritance
- **L**iskov Substitution: Any BaseStrategy can replace another
- **I**nterface Segregation: Clean, minimal interface (analyze, TP, SL)
- **D**ependency Inversion: TradingEngine depends on BaseStrategy interface

✅ **Design Patterns:**
- **Abstract Factory**: BaseStrategy defines interface
- **Factory Pattern**: StrategyFactory for instantiation
- **Template Method**: BaseStrategy defines skeleton, subclasses fill in
- **Strategy Pattern**: Encapsulates algorithms (SMA, future ICT)

✅ **Best Practices:**
- Type hints for all methods and properties
- Comprehensive docstrings with examples
- Unit tests for all logic paths
- Integration tests for system validation

---

## 10. Risk Assessment

### 10.1 Implementation Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| SMA calculation bugs | Medium | High | Unit tests with known datasets |
| Signal validation failures | Low | High | Signal model enforces TP/SL logic |
| Buffer overflow issues | Low | Medium | FIFO logic tested, deque alternative |
| Duplicate signals | Medium | Medium | _last_signal_type tracking |
| Integration errors | Low | High | End-to-end integration tests |

### 10.2 Performance Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Buffer pop(0) slow | Low | Low | Deque optimization if needed |
| SMA calculation overhead | Low | Low | Numpy optimized, caching possible |
| Memory leaks | Very Low | Medium | Buffer size limited, GC handles |

---

## 11. Conclusion

This design provides a complete, production-ready strategy framework with:

✅ **Clear Interface**: BaseStrategy ABC enforces contract
✅ **Simple Test Strategy**: MockSMACrossover validates pipeline
✅ **Extensibility**: Easy to add ICT strategies via same interface
✅ **Testability**: Comprehensive unit and integration tests
✅ **Integration**: Seamless TradingEngine injection
✅ **Documentation**: Full docstrings with examples

**Ready for Implementation:** All subtasks have clear specifications, test strategies, and validation criteria.

**Estimated Implementation Time:** 4-6 hours total
- Clear requirements reduce implementation uncertainty
- Existing models and TradingEngine simplify integration
- Comprehensive tests ensure quality

---

**Design Status:** ✅ **APPROVED - Ready for Implementation**
**Next Step:** Begin Phase 1 (BaseStrategy implementation)
