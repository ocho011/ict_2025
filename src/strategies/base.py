"""
Abstract base class for trading strategies.

This module defines the strategy interface contract that all trading strategies
must implement. It provides common functionality for candle buffer management
and defines abstract methods for signal generation and risk calculations.

Issue #27: Unified buffer structure using Dict[str, deque] for both single
and multi-timeframe strategies. Supports pre-computed detectors (Issue #19).
"""

import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal

# Imports for type hinting only; prevents circular dependency at runtime
# Only imported during static analysis (e.g., mypy, IDE)
if TYPE_CHECKING:
    from src.strategies.indicator_cache import IndicatorStateCache


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Provides:
    - Unified buffer management via buffers Dict[str, deque] (Issue #27)
    - Standard interface for signal generation
    - Configuration management
    - Type safety through full type hints

    Subclasses must implement:
    - analyze(): Main strategy logic for signal generation
    - calculate_take_profit(): TP price calculation
    - calculate_stop_loss(): SL price calculation

    Buffer Structure (Issue #27):
        All strategies use self.buffers: Dict[str, deque] where:
        - Key = interval string (e.g., '5m', '1h', '4h')
        - Value = deque of Candle objects with maxlen=buffer_size

        Single-timeframe strategies: buffers contains one interval
        Multi-timeframe strategies: buffers contains multiple intervals

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

                # Access buffer via interval key
                buffer = self.buffers.get(candle.interval)
                if not buffer or len(buffer) < self.my_param:
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

    def __init__(
        self, symbol: str, config: dict, intervals: Optional[List[str]] = None
    ) -> None:
        """
        Initialize strategy with symbol and configuration.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT', 'ETHUSDT')
            config: Strategy configuration dictionary with:
                - buffer_size (int, optional): Max candles to store (default: 100)
                - default_interval (str, optional): Default interval for single-TF (default: '1m')
                - Additional strategy-specific parameters
            intervals: List of intervals to track (e.g., ['5m', '1h', '4h']).
                       If None, uses config['default_interval'] or '1m'.

        Attributes:
            symbol: Trading pair this strategy analyzes
            config: Configuration dictionary for strategy parameters
            intervals: List of intervals this strategy tracks
            buffers: Dict[str, deque] - one buffer per interval (Issue #27)
            buffer_size: Maximum number of candles to keep per buffer

        Buffer Management (Issue #27):
            - Unified buffers Dict replaces old candle_buffer
            - Each interval has its own deque with maxlen=buffer_size
            - Buffers store candles in chronological order (oldest → newest)
            - When buffer exceeds buffer_size, oldest candle is auto-removed (FIFO)
            - Uses collections.deque with maxlen for O(1) append/evict operations

        Example:
            ```python
            # Single-timeframe strategy (intervals auto-detected from config)
            config = {'buffer_size': 200, 'default_interval': '5m'}
            strategy = MyStrategy('BTCUSDT', config)
            # strategy.intervals = ['5m']
            # strategy.buffers = {'5m': deque(maxlen=200)}

            # Multi-timeframe strategy (intervals explicitly provided)
            config = {'buffer_size': 200}
            strategy = MTFStrategy('BTCUSDT', config, intervals=['5m', '1h', '4h'])
            # strategy.intervals = ['5m', '1h', '4h']
            # strategy.buffers = {'5m': deque(), '1h': deque(), '4h': deque()}
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

        # Initialize price determiner configuration
        self._price_config = self._create_price_config(config)

        # Issue #27: Unified buffer structure
        # Determine intervals from parameter or config
        if intervals is not None:
            self.intervals: List[str] = intervals
        else:
            # Single-timeframe: use default_interval from config
            default_interval = config.get("default_interval", "1m")
            self.intervals = [default_interval]

        # Create buffers dict with one deque per interval
        self.buffers: Dict[str, deque] = {
            interval: deque(maxlen=self.buffer_size) for interval in self.intervals
        }

        # Track initialization status per interval
        self._initialized: Dict[str, bool] = {
            interval: False for interval in self.intervals
        }

        # Indicator cache for pre-computed indicators (Issue #19)
        # Subclasses can initialize this for indicator-aware analysis
        self._indicator_cache: Optional["IndicatorStateCache"] = None

        self.logger = logging.getLogger(self.__class__.__name__)

    def _create_price_config(self, config: Dict[str, Any]) -> "PriceDeterminerConfig":
        """
        Factory method for price determiner configuration.

        Subclasses can override to provide custom determiners.
        Default implementation: percentage-based SL + risk-reward TP.
        """
        from src.pricing.stop_loss.percentage import PercentageStopLoss
        from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
        from src.pricing.base import PriceDeterminerConfig

        return PriceDeterminerConfig(
            stop_loss_determiner=PercentageStopLoss(
                stop_loss_percent=config.get("stop_loss_percent", 0.01)
            ),
            take_profit_determiner=RiskRewardTakeProfit(
                risk_reward_ratio=config.get("risk_reward_ratio", 2.0)
            ),
        )

    def _create_price_context(
        self,
        entry_price: float,
        side: str,
        fvg_zone: Optional[Tuple[float, float]] = None,
        ob_zone: Optional[Tuple[float, float]] = None,
        displacement_size: Optional[float] = None,
    ) -> "PriceContext":
        """
        Create PriceContext for determiner calls.

        Provides all required fields (symbol, timestamp) from strategy state.
        """
        from src.pricing.base import PriceContext
        return PriceContext.from_strategy(
            entry_price=entry_price,
            side=side,
            symbol=self.symbol,
            fvg_zone=fvg_zone,
            ob_zone=ob_zone,
            displacement_size=displacement_size,
        )

    def initialize_with_historical_data(
        self, candles: List[Candle], interval: Optional[str] = None
    ) -> None:
        """
        Initialize strategy buffer with historical candle data.

        Called once during system startup after backfilling completes.
        Does NOT trigger signal generation - used only for warmup phase.

        This method pre-populates the candle buffer with historical data
        so strategies can analyze immediately when real-time trading begins,
        rather than waiting for enough real-time candles to accumulate.

        Args:
            candles: List of historical candles in chronological order (oldest first)
            interval: Target interval to initialize. If None, auto-detects from
                     candles[0].interval or uses first registered interval.

        Behavior:
            1. Determines target interval (from parameter, candles, or default)
            2. Clears existing buffer for that interval
            3. Adds most recent buffer_size candles (if more provided)
            4. Initializes indicator cache (FeatureCache) for the interval
            5. Marks interval as initialized
            6. Logs initialization progress

        Buffer Management:
            - If len(candles) <= buffer_size: All candles added
            - If len(candles) > buffer_size: Only most recent buffer_size candles kept
            - Maintains chronological order (oldest → newest)
            - Deque maxlen automatically enforces size limit

        Example:
            >>> # After backfill, TradingEngine calls this for each strategy
            >>> historical_candles = data_collector.get_candle_buffer('BTCUSDT', '5m')
            >>> strategy.initialize_with_historical_data(historical_candles, '5m')
            >>> # strategy.buffers['5m'] now contains up to buffer_size candles
            >>> # strategy._initialized['5m'] = True
            >>> # Strategy ready for real-time analysis

        Usage Pattern:
            ```python
            # Single-timeframe strategy
            strategy.initialize_with_historical_data(candles)  # Uses first interval

            # Multi-timeframe strategy
            strategy.initialize_with_historical_data(candles_5m, '5m')
            strategy.initialize_with_historical_data(candles_1h, '1h')
            ```

        Notes:
            - Called ONCE during startup, before real-time streaming begins
            - Does NOT call analyze() or generate signals - warmup only
            - Subsequent real-time candles handled normally via analyze()
            - If buffer already has data, it will be replaced (not appended)
            - Thread-safe: Called from main thread before async event loop starts
        """
        # Determine target interval
        if interval is not None:
            target_interval = interval
        elif candles and hasattr(candles[0], "interval"):
            target_interval = candles[0].interval
        else:
            target_interval = self.intervals[0] if self.intervals else "1m"

        # Validate interval is registered
        if target_interval not in self.buffers:
            self.logger.warning(
                f"Interval '{target_interval}' not registered "
                f"for {self.symbol}. Registered: {self.intervals}. "
                f"Creating new buffer for this interval."
            )
            # Auto-register the interval
            self.intervals.append(target_interval)
            self.buffers[target_interval] = deque(maxlen=self.buffer_size)
            self._initialized[target_interval] = False

        if not candles:
            self.logger.warning(
                f"No historical candles provided "
                f"for {self.symbol} {target_interval}. Strategy will start with empty buffer."
            )
            self._initialized[target_interval] = True
            return

        self.logger.info(
            f"Initializing {self.symbol} {target_interval} buffer "
            f"with {len(candles)} historical candles"
        )

        # Clear existing buffer (in case of re-initialization)
        self.buffers[target_interval].clear()

        # Add candles respecting maxlen (keeps most recent)
        # Slice to most recent buffer_size candles if more provided
        for candle in candles[-self.buffer_size :]:
            self.buffers[target_interval].append(candle)

        # Mark interval as initialized
        self._initialized[target_interval] = True

        self.logger.info(
            f"{self.symbol} {target_interval} initialization complete: "
            f"{len(self.buffers[target_interval])} candles in buffer"
        )

        # Initialize indicator cache for this interval if available (Issue #19)
        if (
            self._indicator_cache is not None
            and target_interval in self.buffers
            and self.buffers[target_interval]
        ):
            indicator_counts = self._indicator_cache.initialize_from_history(
                target_interval, list(self.buffers[target_interval])
            )
            self.logger.info(
                f"{self.symbol} {target_interval} indicators initialized: "
                f"OBs={indicator_counts.get('order_blocks', 0)}, "
                f"FVGs={indicator_counts.get('fvgs', 0)}"
            )

    def update_buffer(self, candle: Candle) -> None:
        """
        Add candle to appropriate buffer based on candle.interval.

        This method manages the historical candle buffers by routing
        candles to the correct interval buffer. When a buffer reaches
        maxlen (buffer_size), the deque automatically removes the oldest candle.

        Issue #27: Unified buffer routing using candle.interval attribute.

        Buffer Order:
            buffer[0]  = oldest candle
            buffer[-1] = newest candle (just added)

        FIFO Behavior:
            When buffer is full (len == buffer_size):
            - Append new candle to end: O(1)
            - Oldest candle automatically removed: O(1)
            - Maintains chronological order

        Args:
            candle: New candle to add to historical buffer.
                   Routes to self.buffers[candle.interval].

        Example:
            ```python
            # Multi-timeframe strategy with buffers = {'5m': deque(), '1h': deque()}
            strategy.update_buffer(candle_5m)  # Routes to buffers['5m']
            strategy.update_buffer(candle_1h)  # Routes to buffers['1h']

            # Single-timeframe strategy with buffers = {'1m': deque()}
            strategy.update_buffer(candle_1m)  # Routes to buffers['1m']
            ```

        Performance:
            - Time Complexity: O(1) for both append and auto-evict
            - Space Complexity: O(buffer_size) per interval
            - Improvement: Previous List.pop(0) was O(n)

        Usage Pattern:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                self.update_buffer(candle)  # Auto-routes by candle.interval

                buffer = self.buffers.get(candle.interval)
                if not buffer or len(buffer) < self.min_periods:
                    return None  # Not enough data yet

                # Now use buffer for calculations
                closes = [c.close for c in buffer]
                sma = np.mean(closes[-20:])  # Last 20 candles
                # ...
            ```

        Notes:
            - Automatically routes candle to correct interval buffer
            - Buffer persists across analyze() calls (not cleared)
            - No validation - assumes candles added in chronological order
            - Deque maxlen handles FIFO automatically (no manual pop needed)
            - Logs warning if interval not registered
        """
        interval = candle.interval

        if interval not in self.buffers:
            # Auto-register unknown interval (for flexibility)
            self.logger.debug(
                f"Auto-registering interval '{interval}' "
                f"for {self.symbol}"
            )
            self.intervals.append(interval)
            self.buffers[interval] = deque(maxlen=self.buffer_size)
            self._initialized[interval] = True  # Mark as ready (live data)

        self.buffers[interval].append(candle)  # O(1) - maxlen handles FIFO

    def get_latest_candles(
        self, count: int, interval: Optional[str] = None
    ) -> List[Candle]:
        """
        Get the most recent N candles from buffer.

        Retrieves the last `count` candles from the specified interval buffer
        in chronological order. Useful for indicator calculations or pattern detection.

        Args:
            count: Number of candles to retrieve
            interval: Target interval buffer. If None, uses first registered interval.

        Returns:
            List of candles (newest last), empty if insufficient data

        Example:
            ```python
            # Single-timeframe: Get last 20 candles
            recent = strategy.get_latest_candles(20)

            # Multi-timeframe: Get last 20 candles from specific interval
            recent_1h = strategy.get_latest_candles(20, '1h')

            if recent:
                closes = [c.close for c in recent]
                sma = sum(closes) / len(closes)
            ```

        Notes:
            - Returns empty list if buffer has fewer than `count` candles
            - Returned list maintains chronological order (oldest → newest)
            - Does not modify buffer, read-only operation
        """
        target_interval = interval or (self.intervals[0] if self.intervals else None)
        if not target_interval or target_interval not in self.buffers:
            return []

        buffer = self.buffers[target_interval]
        if len(buffer) < count:
            return []
        return list(buffer)[-count:]

    def get_buffer_size_current(self, interval: Optional[str] = None) -> int:
        """
        Get current number of candles in buffer.

        Returns the actual number of candles currently stored, which may
        be less than buffer_size during initial warmup phase.

        Args:
            interval: Target interval buffer. If None, uses first registered interval.

        Returns:
            Current buffer length (0 to buffer_size)

        Example:
            ```python
            # Single-timeframe
            current = strategy.get_buffer_size_current()

            # Multi-timeframe
            current_1h = strategy.get_buffer_size_current('1h')

            max_size = strategy.buffer_size
            progress = (current / max_size) * 100
            print(f"Buffer: {current}/{max_size} ({progress:.1f}%)")
            ```

        Notes:
            - Returns 0 when buffer is empty
            - Returns buffer_size when buffer is full
            - Useful for monitoring warmup progress
        """
        target_interval = interval or (self.intervals[0] if self.intervals else None)
        if not target_interval or target_interval not in self.buffers:
            return 0
        return len(self.buffers[target_interval])

    def is_buffer_ready(self, min_candles: int, interval: Optional[str] = None) -> bool:
        """
        Check if buffer has minimum required candles for analysis.

        Validates that buffer contains at least `min_candles` for indicator
        calculations. Common use in analyze() to ensure sufficient data.

        Args:
            min_candles: Minimum candles needed for analysis
            interval: Target interval buffer. If None, uses first registered interval.

        Returns:
            True if buffer has enough data, False otherwise

        Example:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                self.update_buffer(candle)

                # Check buffer readiness before analysis
                if not self.is_buffer_ready(self.slow_period, candle.interval):
                    return None  # Not enough data yet

                # Proceed with calculations
                closes = self.get_latest_candles(self.slow_period, candle.interval)
                sma = calculate_sma(closes)
                # ...
            ```

        Notes:
            - Cleaner than `if len(self.buffers[interval]) < min_candles`
            - Consistent API across strategy implementations
            - Supports both single and multi-timeframe strategies
        """
        target_interval = interval or (self.intervals[0] if self.intervals else None)
        if not target_interval or target_interval not in self.buffers:
            return False
        return len(self.buffers[target_interval]) >= min_candles

    def is_ready(self) -> bool:
        """
        Check if all intervals have been initialized.

        For single-timeframe strategies, this checks if the single buffer is ready.
        For multi-timeframe strategies, this checks if ALL interval buffers are ready.

        Returns:
            True if all intervals initialized, False otherwise

        Example:
            ```python
            if strategy.is_ready():
                # All intervals have data
                signal = await strategy.analyze(candle)
            else:
                # Still warming up
                return None
            ```

        Notes:
            - Called automatically by analyze() in MTF strategies
            - Returns False until ALL intervals initialized
            - Prevents analysis with incomplete data
        """
        return all(self._initialized.values())

    @property
    def indicator_cache(self) -> Optional["IndicatorStateCache"]:
        """
        Get the indicator cache instance.

        Returns:
            IndicatorStateCache if initialized, None otherwise
        """
        return self._indicator_cache

    def set_indicator_cache(self, cache: "IndicatorStateCache") -> None:
        """
        Set the indicator cache for pre-computed indicator management.

        Args:
            cache: IndicatorStateCache instance

        Example:
            ```python
            from src.strategies.indicator_cache import IndicatorStateCache

            cache = IndicatorStateCache(config={'max_order_blocks': 20})
            strategy.set_indicator_cache(cache)
            ```
        """
        self._indicator_cache = cache
        self.logger.info(
            f"Indicator cache configured for {self.symbol}"
        )

    def _update_feature_cache(self, candle: Candle) -> None:
        """
        Update indicator cache with new candle data.

        Internal helper method for updating pre-computed indicators.

        Args:
            candle: New candle to update cache with
        """
        if self._indicator_cache is not None and candle.interval in self.intervals:
            self._indicator_cache.update_on_new_candle(
                candle.interval, candle, self.buffers[candle.interval]
            )

    @abstractmethod
    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle and generate trading signal if conditions met.

        This is the main strategy method called by TradingEngine for each new
        candle. It must be implemented by all subclasses.

        Template Method Pattern (Issue #47):
            Subclasses should implement their strategy logic here.
            Common operations (buffer update, cache update, ready check)
            should be handled by calling helper methods.

        Implementation Pattern:
            ```python
            async def analyze(self, candle: Candle) -> Optional[Signal]:
                # 1. Validate candle is closed
                if not candle.is_closed:
                    return None

                # 2. Update buffer with new candle
                self.update_buffer(candle)

                # 3. Update indicator cache if available
                self._update_feature_cache(candle)

                # 4. Check if ready
                if not self.is_ready():
                    return None

                # 5. Implement strategy logic
                buffer = self.buffers.get(candle.interval)
                if not buffer or len(buffer) < self.min_periods:
                    return None

                # ... strategy logic ...
                return signal if conditions_met else None
            ```

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

                # 3. Check sufficient data (access buffer via interval key)
                buffer = self.buffers.get(candle.interval)
                if not buffer or len(buffer) < self.min_periods:
                    return None

                # 4. Calculate indicators
                closes = np.array([c.close for c in buffer])
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

    @abstractmethod
    async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
        """
        Evaluate whether an open position should be exited based on current market conditions.

        This is the main exit evaluation method called by TradingEngine when a position
        exists for the strategy's symbol. It provides dynamic exit logic that complements
        static TP/SL orders, enabling sophisticated exit strategies like trailing stops,
        time-based exits, momentum reversals, etc.

        Parallel Entry/Exit Design:
            - analyze() handles entry signal generation
            - should_exit() handles exit signal generation
            - Both methods are called by TradingEngine but with different triggers
            - Entry signals require TP/SL, exit signals have optional TP/SL

        Method Call Sequence:
            1. TradingEngine detects new candle for symbol
            2. If position exists: calls should_exit(position, candle)
            3. If should_exit() returns signal: executes exit and skips analyze()
            4. If no position or should_exit() returns None: calls analyze(candle)

        Implementation Pattern:
            ```python
            async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
                # 1. Validate inputs
                if not candle.is_closed:
                    return None

                # 2. Update buffer with new candle
                self.update_buffer(candle)

                # 3. Check if ready for analysis
                if not self.is_ready():
                    return None

                # 4. Apply exit logic
                buffer = self.buffers.get(candle.interval)
                if not buffer or len(buffer) < self.exit_periods:
                    return None

                # ... exit condition evaluation ...
                if exit_condition_met:
                    signal_type = SignalType.CLOSE_LONG if position.side == 'LONG' else SignalType.CLOSE_SHORT
                    return Signal(
                        signal_type=signal_type,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="dynamic_exit_description"
                    )

                return None
            ```

        Contract:
            - Called by TradingEngine when position exists for self.symbol
            - Must be async (supports I/O operations if needed)
            - Returns Signal with CLOSE_LONG/CLOSE_SHORT if exit conditions met
            - Returns None if position should remain open

        Args:
            position: Current open position for this symbol
            candle: Latest candle to analyze for exit conditions

        Returns:
            Signal with CLOSE_LONG or CLOSE_SHORT if exit triggered, None otherwise

        Exit Signal Requirements:
            - signal_type must be CLOSE_LONG (for LONG positions) or CLOSE_SHORT (for SHORT positions)
            - take_profit and stop_loss are optional for exit signals
            - exit_reason should describe why exit was triggered
            - Entry price typically set to current candle close price

        Implementation Guidelines:
            1. Verify position side matches signal type (CLOSE_LONG for LONG, CLOSE_SHORT for SHORT)
            2. Use candle.is_closed to ensure analyzing complete candles
            3. Call self.update_buffer(candle) to maintain buffer consistency
            4. Check buffer readiness before performing calculations
            5. Apply specific exit strategy logic
            6. Include descriptive exit_reason for tracking and analysis

        Common Exit Strategies:
            ```python
            # Trailing Stop Exit
            async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
                self.update_buffer(candle)

                # Calculate trailing stop level
                highest_close = max([c.close for c in self.buffers[candle.interval][-20:]])
                trailing_stop = highest_close * 0.95  # 5% below recent high

                if position.side == 'LONG' and candle.close <= trailing_stop:
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop_5pct"
                    )
                return None

            # Time-Based Exit
            async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
                from datetime import timedelta

                if position.entry_time and (candle.close_time - position.entry_time) > timedelta(hours=4):
                    signal_type = SignalType.CLOSE_LONG if position.side == 'LONG' else SignalType.CLOSE_SHORT
                    return Signal(
                        signal_type=signal_type,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="time_exit_4h"
                    )
                return None

            # Momentum Reversal Exit
            async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
                self.update_buffer(candle)

                buffer = self.buffers.get(candle.interval)
                if not buffer or len(buffer) < 14:
                    return None

                # RSI calculation for momentum reversal
                closes = [c.close for c in buffer[-14:]]
                rsi = calculate_rsi(closes)  # Your RSI implementation

                # Exit LONG if RSI becomes overbought
                if position.side == 'LONG' and rsi > 70:
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="rsi_overbought_70"
                    )

                # Exit SHORT if RSI becomes oversold
                if position.side == 'SHORT' and rsi < 30:
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="rsi_oversold_30"
                    )
                return None
            ```

        Error Handling:
            - Return None for invalid inputs or insufficient data
            - Don't raise exceptions - TradingEngine handles error logging
            - Strategy errors should not affect position management

        Performance:
            - Should be fast (<5ms typical) - called on every candle when position exists
            - Avoid heavy calculations in hot path
            - Cache expensive calculations if possible

        Integration with TradingEngine:
            ```python
            # In TradingEngine event handler
            async def _on_candle_closed(self, candle: Candle):
                position = self.position_manager.get_position(candle.symbol)

                if position:
                    # Check for dynamic exit first
                    exit_signal = await self.strategy.should_exit(position, candle)
                    if exit_signal:
                        await self._execute_exit_signal(exit_signal)
                        return

                # No exit signal or no position - check for entry
                entry_signal = await self.strategy.analyze(candle)
                if entry_signal:
                    await self._execute_entry_signal(entry_signal)
            ```

        Notes:
            - Abstract method - must be implemented by subclass
            - Complements static TP/SL orders with dynamic exit logic
            - Called before analyze() when position exists (exit priority)
            - Exit signals bypass entry analysis for immediate execution
            - Should use same buffer management as analyze() for consistency
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

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price via injected determiner.

        Subclasses can override _create_price_config() to customize.

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
            - Logic varies by strategy (percentage, RR, fixed, dynamic)
            - Signal.__post_init__() validates TP > entry (LONG) or TP < entry (SHORT)
        """
        context = self._create_price_context(entry_price, side)
        stop_loss = self.calculate_stop_loss(entry_price, side)
        return self._price_config.take_profit_determiner.calculate_take_profit(context, stop_loss)

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price via injected determiner.

        Subclasses can override _create_price_config() to customize.

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
            - Logic varies by strategy (percentage, ATR, S/R, volatility)
            - Signal.__post_init__() validates SL < entry (LONG) or SL > entry (SHORT)
            - Critical for risk management - should be conservative
        """
        context = self._create_price_context(entry_price, side)
        return self._price_config.stop_loss_determiner.calculate_stop_loss(context)
