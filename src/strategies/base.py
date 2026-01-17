"""
Abstract base class for trading strategies.

This module defines the strategy interface contract that all trading strategies
must implement. It provides common functionality for candle buffer management
and defines abstract methods for signal generation and risk calculations.
"""

import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import List, Optional

from src.models.candle import Candle
from src.models.position import Position
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
            candle_buffer: Deque of historical candles (FIFO order with automatic eviction)
            buffer_size: Maximum number of candles to keep in buffer

        Buffer Management:
            - Buffer stores candles in chronological order (oldest → newest)
            - When buffer exceeds buffer_size, oldest candle is automatically removed (FIFO)
            - Buffer persists across analyze() calls for indicator calculations
            - Uses collections.deque with maxlen for O(1) append/evict operations

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
            - Deque maxlen provides automatic FIFO without manual pop(0)
        """
        self.symbol: str = symbol
        self.config: dict = config
        self.buffer_size: int = config.get("buffer_size", 100)
        self.candle_buffer: deque = deque(maxlen=self.buffer_size)
        self._initialized: bool = False  # Track historical data initialization
        self.logger = logging.getLogger(self.__class__.__name__)

    def initialize_with_historical_data(self, candles: List[Candle]) -> None:
        """
        Initialize strategy buffer with historical candle data.

        Called once during system startup after backfilling completes.
        Does NOT trigger signal generation - used only for warmup phase.

        This method pre-populates the candle buffer with historical data
        so strategies can analyze immediately when real-time trading begins,
        rather than waiting for enough real-time candles to accumulate.

        Args:
            candles: List of historical candles in chronological order (oldest first)

        Behavior:
            1. Clears existing buffer
            2. Adds most recent buffer_size candles (if more provided)
            3. Sets self._initialized = True to mark strategy as warmed up
            4. Logs initialization progress

        Buffer Management:
            - If len(candles) <= buffer_size: All candles added
            - If len(candles) > buffer_size: Only most recent buffer_size candles kept
            - Maintains chronological order (oldest → newest)
            - Deque maxlen automatically enforces size limit

        Example:
            >>> # After backfill, TradingEngine calls this for each strategy
            >>> historical_candles = data_collector.get_candle_buffer('BTCUSDT', '1m')
            >>> strategy.initialize_with_historical_data(historical_candles)
            >>> # strategy.candle_buffer now contains up to buffer_size candles
            >>> # strategy._initialized = True
            >>> # Strategy ready for real-time analysis

        Usage Pattern:
            ```python
            # In TradingBot.initialize() after backfill completes:
            if backfill_success:
                for symbol in symbols:
                    historical_candles = data_collector.get_candle_buffer(symbol, interval)
                    strategy.initialize_with_historical_data(historical_candles)

            # Now when first real-time candle arrives:
            await strategy.analyze(candle)  # Buffer already has historical context
            ```

        Notes:
            - Called ONCE during startup, before real-time streaming begins
            - Does NOT call analyze() or generate signals - warmup only
            - Subsequent real-time candles handled normally via analyze()
            - If buffer already has data, it will be replaced (not appended)
            - Thread-safe: Called from main thread before async event loop starts
        """
        if not candles:
            self.logger.warning(
                f"[{self.__class__.__name__}] No historical candles provided "
                f"for {self.symbol}. Strategy will start with empty buffer."
            )
            self._initialized = True
            return

        self.logger.info(
            f"[{self.__class__.__name__}] Initializing {self.symbol} buffer "
            f"with {len(candles)} historical candles"
        )

        # Clear existing buffer (in case of re-initialization)
        self.candle_buffer.clear()

        # Add candles respecting maxlen (keeps most recent)
        # Slice to most recent buffer_size candles if more provided
        for candle in candles[-self.buffer_size :]:
            self.candle_buffer.append(candle)

        # Mark as initialized
        self._initialized = True

        self.logger.info(
            f"[{self.__class__.__name__}] {self.symbol} initialization complete: "
            f"{len(self.candle_buffer)} candles in buffer"
        )

    def update_buffer(self, candle: Candle) -> None:
        """
        Add candle to buffer with automatic FIFO management.

        This method manages the historical candle buffer by appending
        new candles. When the buffer reaches maxlen (buffer_size),
        the deque automatically removes the oldest candle.

        Buffer Order:
            buffer[0]  = oldest candle
            buffer[-1] = newest candle (just added)

        FIFO Behavior:
            When buffer is full (len == buffer_size):
            - Append new candle to end: O(1)
            - Oldest candle automatically removed: O(1)
            - Maintains chronological order

        Args:
            candle: New candle to add to historical buffer

        Example:
            ```python
            # Initial: buffer_size=3, buffer = deque([c1, c2, c3], maxlen=3)
            strategy.update_buffer(c4)
            # Result: buffer = deque([c2, c3, c4], maxlen=3) - c1 auto-removed

            # Buffer order after multiple updates:
            # buffer[0]  = oldest (c2)
            # buffer[1]  = middle (c3)
            # buffer[2]  = newest (c4)
            ```

        Performance:
            - Time Complexity: O(1) for both append and auto-evict
            - Space Complexity: O(buffer_size)
            - Improvement: Previous List.pop(0) was O(n)

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
            - Deque maxlen handles FIFO automatically (no manual pop needed)
        """
        self.candle_buffer.append(candle)  # O(1) - maxlen handles FIFO  # Remove oldest candle

    def get_latest_candles(self, count: int) -> List[Candle]:
        """
        Get the most recent N candles from buffer.

        Retrieves the last `count` candles from the buffer in chronological
        order. Useful for indicator calculations or pattern detection.

        Args:
            count: Number of candles to retrieve

        Returns:
            List of candles (newest last), empty if insufficient data

        Example:
            ```python
            # Get last 20 candles for SMA calculation
            recent = strategy.get_latest_candles(20)
            if recent:
                closes = [c.close for c in recent]
                sma = sum(closes) / len(closes)
            ```

        Notes:
            - Returns empty list if buffer has fewer than `count` candles
            - Returned list maintains chronological order (oldest → newest)
            - Does not modify buffer, read-only operation
        """
        if len(self.candle_buffer) < count:
            return []
        return list(self.candle_buffer)[-count:]

    def get_buffer_size_current(self) -> int:
        """
        Get current number of candles in buffer.

        Returns the actual number of candles currently stored, which may
        be less than buffer_size during initial warmup phase.

        Returns:
            Current buffer length (0 to buffer_size)

        Example:
            ```python
            current = strategy.get_buffer_size_current()
            max_size = strategy.buffer_size
            progress = (current / max_size) * 100
            print(f"Buffer: {current}/{max_size} ({progress:.1f}%)")
            ```

        Notes:
            - Returns 0 when buffer is empty
            - Returns buffer_size when buffer is full
            - Useful for monitoring warmup progress
        """
        return len(self.candle_buffer)

    def is_buffer_ready(self, min_candles: int) -> bool:
        """
        Check if buffer has minimum required candles for analysis.

        Validates that buffer contains at least `min_candles` for indicator
        calculations. Common use in analyze() to ensure sufficient data.

        Args:
            min_candles: Minimum candles needed for analysis

        Returns:
            True if buffer has enough data, False otherwise

        Example:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                self.update_buffer(candle)

                # Check buffer readiness before analysis
                if not self.is_buffer_ready(self.slow_period):
                    return None  # Not enough data yet

                # Proceed with calculations
                closes = self.get_latest_candles(self.slow_period)
                sma = calculate_sma(closes)
                # ...
            ```

        Notes:
            - Cleaner than `if len(self.candle_buffer) < min_candles`
            - Consistent API across strategy implementations
            - Foundation for MTF buffer ready checks
        """
        return len(self.candle_buffer) >= min_candles

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

    async def check_exit(self, candle: Candle, position: Position) -> Optional[Signal]:
        """
        Check if position should be exited based on strategy conditions.

        This is an optional method that subclasses can override to implement
        custom exit logic (trailing stops, time-based exits, etc.).

        Called by TradingEngine when a position exists for the symbol.
        If this returns an exit Signal, no entry analysis is performed.

        Args:
            candle: Latest closed candle to analyze
            position: Current open position for this symbol

        Returns:
            Signal with CLOSE_LONG or CLOSE_SHORT if exit conditions met,
            None otherwise (position stays open)

        Default Implementation:
            Returns None (no custom exit logic). Positions exit via TP/SL orders only.

        Override Example:
            ```python
            async def check_exit(self, candle: Candle, position: Position) -> Optional[Signal]:
                # Time-based exit: close after 4 hours
                if position.entry_time and (datetime.now() - position.entry_time).hours >= 4:
                    signal_type = SignalType.CLOSE_LONG if position.side == 'LONG' else SignalType.CLOSE_SHORT
                    return Signal(
                        signal_type=signal_type,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="time_exit_4h"
                    )

                # Trailing stop exit
                if self._trailing_stop_hit(candle, position):
                    signal_type = SignalType.CLOSE_LONG if position.side == 'LONG' else SignalType.CLOSE_SHORT
                    return Signal(
                        signal_type=signal_type,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop"
                    )

                return None  # No exit condition met
            ```

        Notes:
            - Called BEFORE analyze() when position exists
            - Exit signals bypass entry analysis entirely
            - TP/SL are optional for exit signals (position is closing)
            - exit_reason field helps track why position was exited
            - TradingEngine uses reduce_only=True for exit orders
        """
        return None  # Default: no custom exit logic

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
