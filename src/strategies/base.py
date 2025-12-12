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
