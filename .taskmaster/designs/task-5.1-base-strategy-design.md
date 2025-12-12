# Subtask 5.1 Design: BaseStrategy Abstract Class

**Subtask ID:** 5.1
**Design Date:** 2025-12-12
**Status:** Design Complete - Ready for Implementation
**Parent Task:** Task #5 - Mock Strategy & Signal Generation Pipeline

---

## 1. Design Overview

### 1.1 Purpose

Implement the abstract base class that defines the **strategy interface contract** for all trading strategies in the system. This provides:

1. **Standard Interface**: Enforces consistent API across all strategy implementations
2. **Buffer Management**: Common candle history storage with FIFO behavior
3. **Configuration Pattern**: Flexible config dict for strategy-specific parameters
4. **Type Safety**: Full type hints for IDE support and static analysis
5. **Documentation**: Comprehensive docstrings with usage examples

**Critical Insight:** This is the foundation for all future strategies (Mock SMA, ICT indicators). Any strategy implementing this interface can be used interchangeably with TradingEngine.

### 1.2 Architecture Context

```
┌─────────────────────────────────────────────────────────────┐
│                    Strategy Framework                        │
└─────────────────────────────────────────────────────────────┘

                        ┌──────────────────┐
                        │  BaseStrategy    │ ← This Design
                        │     (ABC)        │
                        └────────┬─────────┘
                                 │
                    ┌────────────┼────────────┐
                    │                         │
          ┌─────────▼─────────┐    ┌─────────▼─────────┐
          │ MockSMACrossover  │    │  ICTFVGStrategy   │
          │   (Subtask 5.2)   │    │    (Future)       │
          └───────────────────┘    └───────────────────┘

Integration Point:
┌──────────────────┐
│  TradingEngine   │
├──────────────────┤
│ set_strategy()   │ ──> Accepts any BaseStrategy
│ _on_candle()     │ ──> Calls strategy.analyze()
└──────────────────┘
```

---

## 2. File Structure

**Target File:** `src/strategies/base.py`

**Related Files to Create:**
- `src/strategies/__init__.py` - Package exports
- `tests/strategies/test_base_strategy.py` - Unit tests
- `tests/strategies/__init__.py` - Test package

**Directory Structure:**
```
src/strategies/
├── __init__.py          # Export BaseStrategy, future strategies
└── base.py              # This implementation

tests/strategies/
├── __init__.py
└── test_base_strategy.py
```

---

## 3. Detailed Implementation Specification

### 3.1 Class Definition

```python
"""
Abstract base class for trading strategies.

This module defines the strategy interface contract that all trading strategies
must implement. It provides common functionality for candle buffer management
and defines abstract methods for signal generation and risk calculations.
"""

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
    - Type safety through full type hints

    Subclasses must implement:
    - analyze(): Main strategy logic for signal generation
    - calculate_take_profit(): TP price calculation
    - calculate_stop_loss(): SL price calculation

    Example:
        ```python
        class MyStrategy(BaseStrategy):
            def __init__(self, symbol: str, config: dict) -> None:
                super().__init__(symbol, config)
                self.my_param = config.get('my_param', 100)

            async def analyze(self, candle: Candle) -> Optional[Signal]:
                if not candle.is_closed:
                    return None

                self.update_buffer(candle)

                if len(self.candle_buffer) < self.my_param:
                    return None

                # ... strategy logic ...
                if conditions_met:
                    return Signal(
                        signal_type=SignalType.LONG_ENTRY,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        take_profit=self.calculate_take_profit(candle.close, 'LONG'),
                        stop_loss=self.calculate_stop_loss(candle.close, 'LONG'),
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc)
                    )

                return None

            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                # ... TP logic ...
                return tp_price

            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                # ... SL logic ...
                return sl_price
        ```

    Integration with TradingEngine:
        ```python
        # TradingEngine injects strategy via setter
        engine = TradingEngine(config)
        strategy = MyStrategy('BTCUSDT', strategy_config)
        engine.set_strategy(strategy)

        # TradingEngine calls analyze() for each candle
        # await engine.run()  # Calls strategy.analyze() in event handler
        ```
    """

    def __init__(self, symbol: str, config: dict) -> None:
        """
        Initialize strategy with symbol and configuration.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT', 'ETHUSDT')
            config: Strategy configuration dictionary with:
                - buffer_size (int, optional): Max candles to store (default: 100)
                - Additional strategy-specific parameters

        Attributes:
            symbol: Trading pair this strategy analyzes
            config: Configuration dictionary for strategy parameters
            candle_buffer: List of historical candles (FIFO order)
            buffer_size: Maximum number of candles to keep in buffer

        Buffer Management:
            - Buffer stores candles in chronological order (oldest → newest)
            - When buffer exceeds buffer_size, oldest candle is removed (FIFO)
            - Buffer persists across analyze() calls for indicator calculations

        Example:
            ```python
            config = {
                'buffer_size': 200,  # Custom buffer size
                'fast_period': 10,   # Strategy-specific param
                'slow_period': 20    # Strategy-specific param
            }
            strategy = MyStrategy('BTCUSDT', config)
            # strategy.buffer_size = 200
            # strategy.symbol = 'BTCUSDT'
            ```

        Notes:
            - Subclasses should call super().__init__() first
            - Config dict allows flexible parameters per strategy
            - Buffer_size should accommodate longest indicator period
        """
        self.symbol: str = symbol
        self.config: dict = config
        self.candle_buffer: List[Candle] = []
        self.buffer_size: int = config.get('buffer_size', 100)

    def update_buffer(self, candle: Candle) -> None:
        """
        Add candle to buffer, maintaining max size via FIFO.

        This method manages the historical candle buffer by:
        1. Appending new candle to end of list (newest)
        2. Removing oldest candle if buffer exceeds max size

        Buffer Order:
            buffer[0]  = oldest candle
            buffer[-1] = newest candle (just added)

        FIFO Behavior:
            When buffer is full (len == buffer_size):
            - Append new candle to end
            - Remove candle at index 0 (oldest)
            - Maintains chronological order

        Args:
            candle: New candle to add to historical buffer

        Example:
            ```python
            # Initial: buffer_size=3, buffer = [c1, c2, c3]
            strategy.update_buffer(c4)
            # Result: buffer = [c2, c3, c4]  (c1 removed, c4 added)

            # Buffer order after multiple updates:
            # buffer[0]  = oldest (c2)
            # buffer[1]  = middle (c3)
            # buffer[2]  = newest (c4)
            ```

        Performance:
            - Time Complexity: O(n) for pop(0), O(1) for append
            - Space Complexity: O(buffer_size)
            - Note: For large buffers (>1000), consider collections.deque

        Usage Pattern:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                self.update_buffer(candle)  # Always call first

                if len(self.candle_buffer) < self.min_periods:
                    return None  # Not enough data yet

                # Now use buffer for calculations
                closes = [c.close for c in self.candle_buffer]
                sma = np.mean(closes[-20:])  # Last 20 candles
                # ...
            ```

        Notes:
            - Called automatically by most strategy implementations
            - Buffer persists across analyze() calls (not cleared)
            - No validation - assumes candles added in chronological order
            - Oldest candle removed via pop(0) (list shift operation)
        """
        self.candle_buffer.append(candle)
        if len(self.candle_buffer) > self.buffer_size:
            self.candle_buffer.pop(0)  # Remove oldest candle

    @abstractmethod
    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle and generate trading signal if conditions met.

        This is the main strategy method called by TradingEngine for each new
        candle. It must be implemented by all subclasses.

        Contract:
            - Called by TradingEngine._on_candle_closed() for each candle
            - Must be async (supports I/O operations if needed)
            - Returns Signal object if trading opportunity detected
            - Returns None if no signal conditions met or invalid state

        Args:
            candle: Latest candle from data collector to analyze

        Returns:
            Signal object with entry/TP/SL prices if conditions met, None otherwise

        Implementation Guidelines:
            1. Check candle.is_closed (only analyze complete candles)
            2. Call self.update_buffer(candle) to add to history
            3. Verify buffer has enough data for calculations
            4. Apply strategy logic (indicators, patterns, etc.)
            5. If conditions met, create Signal with calculated TP/SL
            6. Return Signal or None

        Error Handling:
            - Exceptions logged by TradingEngine, don't re-raise
            - Invalid calculations should return None, not raise
            - Strategy errors isolated from TradingEngine

        Signal Creation:
            ```python
            if buy_conditions_met:
                return Signal(
                    signal_type=SignalType.LONG_ENTRY,
                    symbol=self.symbol,
                    entry_price=candle.close,
                    take_profit=self.calculate_take_profit(candle.close, 'LONG'),
                    stop_loss=self.calculate_stop_loss(candle.close, 'LONG'),
                    strategy_name=self.__class__.__name__,
                    timestamp=datetime.now(timezone.utc)
                )
            ```

        Example Implementation:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                # 1. Validate candle is closed
                if not candle.is_closed:
                    return None

                # 2. Update buffer with new candle
                self.update_buffer(candle)

                # 3. Check sufficient data
                if len(self.candle_buffer) < self.min_periods:
                    return None

                # 4. Calculate indicators
                closes = np.array([c.close for c in self.candle_buffer])
                sma_fast = np.mean(closes[-self.fast_period:])
                sma_slow = np.mean(closes[-self.slow_period:])

                # 5. Check conditions
                if sma_fast > sma_slow and self._prev_fast <= self._prev_slow:
                    # Golden cross detected
                    return Signal(
                        signal_type=SignalType.LONG_ENTRY,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        take_profit=self.calculate_take_profit(candle.close, 'LONG'),
                        stop_loss=self.calculate_stop_loss(candle.close, 'LONG'),
                        strategy_name='MySMAStrategy',
                        timestamp=datetime.now(timezone.utc)
                    )

                # 6. No signal
                return None
            ```

        Performance:
            - Should be fast (<10ms typical)
            - Heavy calculations should use numpy/vectorization
            - Avoid blocking I/O in analyze() if possible

        Notes:
            - Abstract method - must be implemented by subclass
            - Async allows future strategies to use I/O (API calls, etc.)
            - Called for every candle, so performance matters
            - Signal model validates TP/SL logic in __post_init__()
        """
        pass

    @abstractmethod
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price for a position.

        Must be implemented by all subclasses to define TP logic.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT' to determine TP direction

        Returns:
            Take profit price (float)

        Validation Requirements:
            - LONG: TP must be > entry_price
            - SHORT: TP must be < entry_price
            - Signal model validates this in __post_init__()

        Example Implementations:
            ```python
            # Percentage-based TP
            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                tp_percent = self.config.get('tp_percent', 0.02)  # 2%
                if side == 'LONG':
                    return entry_price * (1 + tp_percent)
                else:  # SHORT
                    return entry_price * (1 - tp_percent)

            # Risk-reward ratio TP
            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                risk = entry_price * self.stop_loss_percent
                reward = risk * self.risk_reward_ratio  # e.g., 2:1
                if side == 'LONG':
                    return entry_price + reward
                else:  # SHORT
                    return entry_price - reward

            # Fixed dollar TP
            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                tp_amount = self.config.get('tp_amount', 1000)  # $1000
                if side == 'LONG':
                    return entry_price + tp_amount
                else:  # SHORT
                    return entry_price - tp_amount
            ```

        Usage:
            ```python
            # Called when creating Signal
            entry = candle.close
            tp = self.calculate_take_profit(entry, 'LONG')
            sl = self.calculate_stop_loss(entry, 'LONG')

            signal = Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol=self.symbol,
                entry_price=entry,
                take_profit=tp,  # Calculated TP
                stop_loss=sl,
                # ...
            )
            ```

        Notes:
            - Abstract method - must be implemented
            - Logic varies by strategy (percentage, RR, fixed, dynamic)
            - Signal.__post_init__() validates TP > entry (LONG) or TP < entry (SHORT)
        """
        pass

    @abstractmethod
    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price for a position.

        Must be implemented by all subclasses to define SL logic.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT' to determine SL direction

        Returns:
            Stop loss price (float)

        Validation Requirements:
            - LONG: SL must be < entry_price
            - SHORT: SL must be > entry_price
            - Signal model validates this in __post_init__()

        Example Implementations:
            ```python
            # Percentage-based SL
            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                sl_percent = self.config.get('sl_percent', 0.01)  # 1%
                if side == 'LONG':
                    return entry_price * (1 - sl_percent)
                else:  # SHORT
                    return entry_price * (1 + sl_percent)

            # ATR-based SL
            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                atr = self._calculate_atr()  # Average True Range
                multiplier = self.config.get('atr_multiplier', 1.5)
                if side == 'LONG':
                    return entry_price - (atr * multiplier)
                else:  # SHORT
                    return entry_price + (atr * multiplier)

            # Support/resistance SL
            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                if side == 'LONG':
                    support = self._find_nearest_support(entry_price)
                    return support - (entry_price * 0.001)  # Below support
                else:  # SHORT
                    resistance = self._find_nearest_resistance(entry_price)
                    return resistance + (entry_price * 0.001)  # Above resistance
            ```

        Usage:
            ```python
            # Called when creating Signal
            entry = candle.close
            tp = self.calculate_take_profit(entry, 'LONG')
            sl = self.calculate_stop_loss(entry, 'LONG')

            signal = Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol=self.symbol,
                entry_price=entry,
                take_profit=tp,
                stop_loss=sl,  # Calculated SL
                # ...
            )
            ```

        Notes:
            - Abstract method - must be implemented
            - Logic varies by strategy (percentage, ATR, S/R, volatility)
            - Signal.__post_init__() validates SL < entry (LONG) or SL > entry (SHORT)
            - Critical for risk management - should be conservative
        """
        pass
```

---

## 4. Integration Points

### 4.1 Model Dependencies

**Candle Model** (from `src/models/candle.py`):
```python
@dataclass
class Candle:
    symbol: str
    interval: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: datetime
    is_closed: bool = False
```

**Signal Model** (from `src/models/signal.py`):
```python
@dataclass(frozen=True)
class Signal:
    signal_type: SignalType  # LONG_ENTRY, SHORT_ENTRY, etc.
    symbol: str
    entry_price: float
    take_profit: float
    stop_loss: float
    strategy_name: str
    timestamp: datetime
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 4.2 TradingEngine Integration

**TradingEngine Expected Interface** (from Task #4):
```python
class TradingEngine:
    async def _on_candle_closed(self, event: Event) -> None:
        """Handle CANDLE_CLOSED event."""
        candle: Candle = event.data

        if not self.strategy:
            self.logger.warning("No strategy configured")
            return

        # Calls strategy.analyze() - BaseStrategy interface
        signal: Optional[Signal] = await self.strategy.analyze(candle)

        if signal:
            await self.event_bus.publish(
                Event(EventType.SIGNAL_GENERATED, signal, source='TradingEngine'),
                queue_name='signal'
            )
```

**Integration Flow:**
```
1. BinanceDataCollector → CANDLE_CLOSED event
2. EventBus routes to TradingEngine._on_candle_closed()
3. TradingEngine calls strategy.analyze(candle)
4. BaseStrategy implementation processes candle
5. Returns Optional[Signal]
6. TradingEngine publishes SIGNAL_GENERATED event
```

---

## 5. Test Strategy

### 5.1 Unit Tests

**File:** `tests/strategies/test_base_strategy.py`

```python
"""
Unit tests for BaseStrategy abstract class.

Tests verify:
- Buffer initialization and configuration
- FIFO buffer management behavior
- Abstract method enforcement
- Type hint correctness
"""

import pytest
from datetime import datetime, timezone
from typing import Optional

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


# Concrete implementation for testing abstract class
class ConcreteTestStrategy(BaseStrategy):
    """Minimal implementation for testing BaseStrategy."""

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """Dummy implementation."""
        return None

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Dummy implementation."""
        return entry_price * 1.02 if side == 'LONG' else entry_price * 0.98

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """Dummy implementation."""
        return entry_price * 0.99 if side == 'LONG' else entry_price * 1.01


class TestBaseStrategyInitialization:
    """Test BaseStrategy initialization and configuration."""

    def test_init_default_buffer_size(self):
        """Verify default buffer_size is 100."""
        config = {}
        strategy = ConcreteTestStrategy('BTCUSDT', config)

        assert strategy.symbol == 'BTCUSDT'
        assert strategy.config == {}
        assert strategy.buffer_size == 100
        assert strategy.candle_buffer == []
        assert isinstance(strategy.candle_buffer, list)

    def test_init_custom_buffer_size(self):
        """Verify custom buffer_size from config."""
        config = {'buffer_size': 200}
        strategy = ConcreteTestStrategy('ETHUSDT', config)

        assert strategy.buffer_size == 200
        assert strategy.symbol == 'ETHUSDT'

    def test_init_preserves_config(self):
        """Verify config dict is stored and accessible."""
        config = {
            'buffer_size': 150,
            'fast_period': 10,
            'slow_period': 20
        }
        strategy = ConcreteTestStrategy('BTCUSDT', config)

        assert strategy.config == config
        assert strategy.config['fast_period'] == 10
        assert strategy.config['slow_period'] == 20


class TestBufferManagement:
    """Test candle buffer FIFO behavior."""

    def test_update_buffer_appends_candle(self):
        """Verify update_buffer adds candle to buffer."""
        strategy = ConcreteTestStrategy('BTCUSDT', {})
        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            is_closed=True
        )

        strategy.update_buffer(candle)

        assert len(strategy.candle_buffer) == 1
        assert strategy.candle_buffer[0] is candle

    def test_update_buffer_maintains_order(self):
        """Verify buffer maintains chronological order (oldest → newest)."""
        strategy = ConcreteTestStrategy('BTCUSDT', {'buffer_size': 10})

        # Add 5 candles
        candles = []
        for i in range(5):
            candle = Candle(
                symbol='BTCUSDT',
                interval='1h',
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i,
                high=51000.0 + i,
                low=49000.0 + i,
                close=50500.0 + i,
                volume=100.0,
                is_closed=True
            )
            candles.append(candle)
            strategy.update_buffer(candle)

        # Verify order
        assert len(strategy.candle_buffer) == 5
        assert strategy.candle_buffer[0] is candles[0]  # Oldest
        assert strategy.candle_buffer[-1] is candles[4]  # Newest

    def test_update_buffer_fifo_behavior(self):
        """Verify FIFO: oldest removed when buffer exceeds max size."""
        strategy = ConcreteTestStrategy('BTCUSDT', {'buffer_size': 3})

        # Add 4 candles (exceeds buffer_size of 3)
        candles = []
        for i in range(4):
            candle = Candle(
                symbol='BTCUSDT',
                interval='1h',
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i,
                high=51000.0 + i,
                low=49000.0 + i,
                close=50500.0 + i,
                volume=100.0,
                is_closed=True
            )
            candles.append(candle)
            strategy.update_buffer(candle)

        # Verify FIFO
        assert len(strategy.candle_buffer) == 3
        assert strategy.candle_buffer[0] is candles[1]  # candles[0] removed
        assert strategy.candle_buffer[1] is candles[2]
        assert strategy.candle_buffer[2] is candles[3]  # Newest

    def test_update_buffer_large_overflow(self):
        """Verify FIFO with large buffer overflow."""
        strategy = ConcreteTestStrategy('BTCUSDT', {'buffer_size': 5})

        # Add 10 candles (5 over buffer_size)
        candles = []
        for i in range(10):
            candle = Candle(
                symbol='BTCUSDT',
                interval='1h',
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i,
                high=51000.0 + i,
                low=49000.0 + i,
                close=50500.0 + i,
                volume=100.0,
                is_closed=True
            )
            candles.append(candle)
            strategy.update_buffer(candle)

        # Verify only last 5 candles remain
        assert len(strategy.candle_buffer) == 5
        assert strategy.candle_buffer[0] is candles[5]  # candles[0-4] removed
        assert strategy.candle_buffer[-1] is candles[9]


class TestAbstractMethods:
    """Test abstract method enforcement."""

    def test_cannot_instantiate_base_strategy(self):
        """Verify BaseStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            strategy = BaseStrategy('BTCUSDT', {})  # Should raise

        assert "Can't instantiate abstract class" in str(exc_info.value)
        assert "abstract method" in str(exc_info.value)

    def test_subclass_must_implement_analyze(self):
        """Verify subclass must implement analyze()."""
        class IncompleteStrategy(BaseStrategy):
            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                return entry_price * 1.02

            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                return entry_price * 0.99

        with pytest.raises(TypeError) as exc_info:
            strategy = IncompleteStrategy('BTCUSDT', {})

        assert "Can't instantiate abstract class" in str(exc_info.value)
        assert "analyze" in str(exc_info.value)

    def test_subclass_must_implement_calculate_take_profit(self):
        """Verify subclass must implement calculate_take_profit()."""
        class IncompleteStrategy(BaseStrategy):
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                return None

            def calculate_stop_loss(self, entry_price: float, side: str) -> float:
                return entry_price * 0.99

        with pytest.raises(TypeError) as exc_info:
            strategy = IncompleteStrategy('BTCUSDT', {})

        assert "Can't instantiate abstract class" in str(exc_info.value)
        assert "calculate_take_profit" in str(exc_info.value)

    def test_subclass_must_implement_calculate_stop_loss(self):
        """Verify subclass must implement calculate_stop_loss()."""
        class IncompleteStrategy(BaseStrategy):
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                return None

            def calculate_take_profit(self, entry_price: float, side: str) -> float:
                return entry_price * 1.02

        with pytest.raises(TypeError) as exc_info:
            strategy = IncompleteStrategy('BTCUSDT', {})

        assert "Can't instantiate abstract class" in str(exc_info.value)
        assert "calculate_stop_loss" in str(exc_info.value)


class TestConcreteImplementation:
    """Test that complete implementations work correctly."""

    def test_complete_implementation_instantiates(self):
        """Verify complete implementation can be instantiated."""
        strategy = ConcreteTestStrategy('BTCUSDT', {})

        assert isinstance(strategy, BaseStrategy)
        assert strategy.symbol == 'BTCUSDT'

    @pytest.mark.asyncio
    async def test_concrete_analyze_callable(self):
        """Verify analyze() can be called on concrete implementation."""
        strategy = ConcreteTestStrategy('BTCUSDT', {})
        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            is_closed=True
        )

        result = await strategy.analyze(candle)

        assert result is None  # ConcreteTestStrategy returns None

    def test_concrete_calculate_take_profit_callable(self):
        """Verify calculate_take_profit() callable."""
        strategy = ConcreteTestStrategy('BTCUSDT', {})

        tp = strategy.calculate_take_profit(50000.0, 'LONG')

        assert tp == 51000.0  # 50000 * 1.02

    def test_concrete_calculate_stop_loss_callable(self):
        """Verify calculate_stop_loss() callable."""
        strategy = ConcreteTestStrategy('BTCUSDT', {})

        sl = strategy.calculate_stop_loss(50000.0, 'LONG')

        assert sl == 49500.0  # 50000 * 0.99
```

### 5.2 Test Coverage Goals

```
Target: 100% coverage for BaseStrategy

src/strategies/base.py:
- __init__():              100% (all branches)
- update_buffer():         100% (FIFO logic)
- analyze():               N/A (abstract method)
- calculate_take_profit(): N/A (abstract method)
- calculate_stop_loss():   N/A (abstract method)

Overall Coverage: 100% (excluding abstract methods)
```

---

## 6. Implementation Checklist

### Phase 1: File Setup
- [ ] Create `src/strategies/` directory
- [ ] Create `src/strategies/__init__.py` with exports
- [ ] Create `src/strategies/base.py` with module docstring
- [ ] Create `tests/strategies/` directory
- [ ] Create `tests/strategies/__init__.py`
- [ ] Create `tests/strategies/test_base_strategy.py`

### Phase 2: BaseStrategy Implementation
- [ ] Add imports (ABC, abstractmethod, typing, models)
- [ ] Define `BaseStrategy` class with class docstring
- [ ] Implement `__init__()` with full docstring
- [ ] Implement `update_buffer()` with full docstring
- [ ] Define `analyze()` abstract method with full docstring
- [ ] Define `calculate_take_profit()` abstract method with full docstring
- [ ] Define `calculate_stop_loss()` abstract method with full docstring

### Phase 3: Testing
- [ ] Implement `ConcreteTestStrategy` test helper
- [ ] Write initialization tests (default/custom buffer_size)
- [ ] Write buffer management tests (append, order, FIFO)
- [ ] Write abstract method enforcement tests
- [ ] Write concrete implementation tests
- [ ] Run tests: `pytest tests/strategies/test_base_strategy.py -v`
- [ ] Verify 100% coverage: `pytest --cov=src/strategies/base tests/strategies/`

### Phase 4: Validation
- [ ] Run type checker: `mypy src/strategies/base.py`
- [ ] Run linter: `pylint src/strategies/base.py`
- [ ] Verify docstring completeness
- [ ] Test manual instantiation attempts (should fail)
- [ ] Verify exports in `__init__.py`

### Phase 5: Documentation
- [ ] Update `src/strategies/__init__.py` exports
- [ ] Add usage examples in docstrings
- [ ] Verify integration with TradingEngine interface
- [ ] Mark Subtask 5.1 as `done`

---

## 7. Design Validation

### 7.1 Requirements Coverage

| Requirement | Implementation | Status |
|-------------|----------------|--------|
| Abstract interface | BaseStrategy(ABC) | ✅ |
| Buffer management | update_buffer() with FIFO | ✅ |
| Abstract methods | analyze, TP, SL | ✅ |
| Type hints | All methods fully typed | ✅ |
| Configuration | Config dict pattern | ✅ |
| Docstrings | Comprehensive with examples | ✅ |

### 7.2 Design Principles

✅ **SOLID Principles:**
- **Single Responsibility**: Buffer management + interface definition
- **Open/Closed**: Open for extension via inheritance, closed for modification
- **Liskov Substitution**: Any BaseStrategy subclass is interchangeable
- **Interface Segregation**: Minimal, focused interface (3 methods)
- **Dependency Inversion**: TradingEngine depends on BaseStrategy abstraction

✅ **Design Patterns:**
- **Template Method**: BaseStrategy defines skeleton, subclasses implement details
- **Abstract Factory**: BaseStrategy serves as factory interface (via StrategyFactory)

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Buffer pop(0) performance | Low | Low | Deque optimization if needed |
| Abstract method not implemented | Low | High | TypeError at instantiation |
| Incorrect buffer order | Very Low | Medium | Unit tests verify FIFO |
| Type hint errors | Very Low | Low | Mypy validation |

---

## 9. Conclusion

**Design Status:** ✅ **APPROVED - Ready for Implementation**

**Next Steps:**
1. Implement `src/strategies/base.py` following this specification
2. Implement comprehensive unit tests
3. Verify 100% coverage and mypy compliance
4. Mark Subtask 5.1 as `done`
5. Proceed to Subtask 5.2: MockSMACrossoverStrategy

**Estimated Implementation Time:** 1-2 hours
- Clear specification reduces implementation uncertainty
- Comprehensive tests ensure quality
- Existing models simplify integration
