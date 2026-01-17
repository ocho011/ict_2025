"""
Multi-timeframe strategy base class for HTF→MTF→LTF analysis.

This module provides the MultiTimeframeStrategy base class that extends
BaseStrategy to support analysis across multiple timeframes simultaneously.
Enables strategies like ICT that require Higher Timeframe (HTF) trend analysis,
Medium Timeframe (MTF) structure detection, and Lower Timeframe (LTF) entry timing.
"""

from abc import abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Dict, List, Optional

from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal
from src.strategies.base import BaseStrategy

if TYPE_CHECKING:
    from src.strategies.feature_cache import FeatureStateCache


class MultiTimeframeStrategy(BaseStrategy):
    """
    Base class for multi-timeframe trading strategies.

    Extends BaseStrategy to support multiple interval buffers, enabling
    top-down analysis from higher timeframes to lower timeframes.

    Key Features:
    - Separate candle buffers for each timeframe (e.g., 5m, 1h, 4h)
    - Per-interval historical data initialization
    - Automatic buffer updates routed by interval
    - analyze_mtf() method receives all interval buffers
    - is_ready() validation ensures all intervals initialized

    Typical Usage (ICT Strategy):
    - HTF (4h): Identify market trend (bullish/bearish/sideways)
    - MTF (1h): Find structure (Fair Value Gaps, Order Blocks)
    - LTF (5m): Time entry with displacement confirmation

    Example:
        ```python
        class ICTStrategy(MultiTimeframeStrategy):
            def __init__(self, symbol: str, config: dict):
                htf = config.get('htf_interval', '4h')
                mtf = config.get('mtf_interval', '1h')
                ltf = config.get('ltf_interval', '5m')

                intervals = [ltf, mtf, htf]
                super().__init__(symbol, intervals, config)

                self.htf_interval = htf
                self.mtf_interval = mtf
                self.ltf_interval = ltf

            async def analyze_mtf(
                self,
                candle: Candle,
                buffers: Dict[str, deque]
            ) -> Optional[Signal]:
                # HTF trend analysis
                htf_trend = self._analyze_trend(buffers[self.htf_interval])
                if htf_trend == 'sideways':
                    return None

                # MTF structure
                fvg = self._find_fvg(buffers[self.mtf_interval], htf_trend)
                if not fvg:
                    return None

                # LTF entry
                if self._check_displacement(buffers[self.ltf_interval], htf_trend):
                    return self._create_signal(candle, htf_trend, fvg)

                return None
        ```

    Integration with TradingEngine:
        ```python
        # TradingEngine routes candles by interval
        engine = TradingEngine(config)
        strategy = ICTStrategy('BTCUSDT', {
            'htf_interval': '4h',
            'mtf_interval': '1h',
            'ltf_interval': '5m',
            'buffer_size': 200
        })
        engine.set_strategy(strategy)

        # Historical data initialized per-interval
        # Real-time candles routed to correct buffers
        # analyze_mtf() called on LTF interval close
        ```
    """

    def __init__(self, symbol: str, intervals: List[str], config: dict) -> None:
        """
        Initialize multi-timeframe strategy.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            intervals: List of intervals to analyze (e.g., ['5m', '1h', '4h'])
            config: Strategy configuration with buffer_size and strategy params

        Attributes:
            intervals: List of intervals this strategy monitors
            buffers: Dict[interval, deque] - one buffer per interval
            _initialized: Dict[interval, bool] - initialization status per interval

        Buffer Structure:
            ```python
            {
                '5m': deque([Candle, ...], maxlen=200),
                '1h': deque([Candle, ...], maxlen=200),
                '4h': deque([Candle, ...], maxlen=200)
            }
            ```

        Initialization Flow:
            1. Call super().__init__() to set up BaseStrategy
            2. Store intervals list
            3. Create empty deque for each interval
            4. Mark all intervals as uninitialized

        Example:
            ```python
            strategy = ICTStrategy(
                symbol='BTCUSDT',
                intervals=['5m', '1h', '4h'],
                config={
                    'buffer_size': 200,
                    'risk_reward_ratio': 2.0
                }
            )
            # strategy.buffers = {'5m': deque(), '1h': deque(), '4h': deque()}
            # strategy._initialized = {'5m': False, '1h': False, '4h': False}
            ```

        Notes:
            - BaseStrategy's single buffer (self.candle_buffer) is NOT used
            - All candles stored in self.buffers instead
            - Each interval has independent FIFO management
            - Buffer size applies to ALL intervals
        """
        # Initialize BaseStrategy (sets symbol, config, buffer_size, logger)
        super().__init__(symbol, config)

        # Store intervals for this multi-timeframe strategy
        self.intervals: List[str] = intervals

        # Create separate buffer for each interval
        self.buffers: Dict[str, deque] = {
            interval: deque(maxlen=self.buffer_size) for interval in intervals
        }

        # Track initialization status per interval
        self._initialized: Dict[str, bool] = {interval: False for interval in intervals}

        # Feature cache for pre-computed features (Issue #19)
        # Subclasses can initialize this for feature-aware analysis
        self._feature_cache: Optional["FeatureStateCache"] = None

    def initialize_with_historical_data(self, interval: str, candles: List[Candle]) -> None:
        """
        Initialize specific interval buffer with historical data.

        Called once per interval during system startup after backfill.
        Populates the interval's buffer with historical candles.

        Args:
            interval: Interval to initialize (e.g., '1h')
            candles: Historical candles for this interval (chronological order)

        Behavior:
            1. Validates interval is registered
            2. Clears existing buffer for this interval
            3. Adds most recent buffer_size candles
            4. Marks interval as initialized
            5. Logs initialization progress

        Example:
            ```python
            # Called by TradingEngine for each interval
            historical_1h = data_collector.get_candle_buffer('BTCUSDT_1h')
            strategy.initialize_with_historical_data('1h', historical_1h)

            historical_5m = data_collector.get_candle_buffer('BTCUSDT_5m')
            strategy.initialize_with_historical_data('5m', historical_5m)

            # strategy.buffers['1h'] now has up to 200 candles
            # strategy.buffers['5m'] now has up to 200 candles
            # strategy._initialized = {'5m': True, '1h': True, '4h': False}
            ```

        Error Handling:
            - Warns if interval not registered
            - Warns if no candles provided
            - Continues even on warnings

        Notes:
            - Can be called multiple times (re-initialization)
            - Only most recent buffer_size candles kept
            - Does NOT call analyze() or generate signals
            - Thread-safe (called before async event loop)
        """
        if interval not in self.intervals:
            self.logger.warning(
                f"[{self.__class__.__name__}] Interval '{interval}' not registered "
                f"for {self.symbol}. Registered: {self.intervals}"
            )
            return

        if not candles:
            self.logger.warning(
                f"[{self.__class__.__name__}] No historical candles provided "
                f"for {self.symbol} {interval}"
            )
            self._initialized[interval] = True
            return

        self.logger.info(
            f"[{self.__class__.__name__}] Initializing {self.symbol} {interval} "
            f"buffer with {len(candles)} historical candles"
        )

        # Clear existing buffer
        self.buffers[interval].clear()

        # Add candles respecting maxlen (keeps most recent)
        for candle in candles[-self.buffer_size :]:
            self.buffers[interval].append(candle)

        # Mark as initialized
        self._initialized[interval] = True

        # Initialize feature cache for this interval if available (Issue #19)
        if self._feature_cache is not None:
            feature_counts = self._feature_cache.initialize_from_history(
                interval, list(self.buffers[interval])
            )
            self.logger.info(
                f"[{self.__class__.__name__}] {self.symbol} {interval} features initialized: "
                f"OBs={feature_counts.get('order_blocks', 0)}, "
                f"FVGs={feature_counts.get('fvgs', 0)}"
            )

        self.logger.info(
            f"[{self.__class__.__name__}] {self.symbol} {interval} initialization complete: "
            f"{len(self.buffers[interval])} candles in buffer"
        )

    def update_buffer(self, interval: str, candle: Candle) -> None:
        """
        Add candle to specific interval buffer with FIFO management.

        Routes incoming candles to the correct interval buffer.
        Automatic eviction when buffer reaches maxlen.

        Args:
            interval: Interval of the candle (e.g., '5m')
            candle: New candle to add

        Behavior:
            - Validates interval is registered
            - Appends candle to interval's buffer
            - Deque automatically removes oldest if full

        Example:
            ```python
            # In TradingEngine event handler
            async def _on_candle_closed(self, event: Event):
                candle = event.data

                # Route to correct buffer
                if isinstance(strategy, MultiTimeframeStrategy):
                    strategy.update_buffer(candle.interval, candle)
                else:
                    strategy.update_buffer(candle)  # Single-interval
            ```

        Performance:
            - Time Complexity: O(1)
            - Space Complexity: O(buffer_size) per interval

        Notes:
            - No validation of chronological order
            - Assumes candles arrive in order
            - Silent if interval not registered
        """
        if interval not in self.intervals:
            self.logger.warning(
                f"[{self.__class__.__name__}] Attempted to update unknown interval '{interval}' "
                f"for {self.symbol}. Registered: {self.intervals}"
            )
            return

        self.buffers[interval].append(candle)

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Wrapper that routes to analyze_mtf() with all buffers.

        Called by TradingEngine for each candle close. Routes the candle
        to the correct buffer, then calls analyze_mtf() if ready.

        Args:
            candle: Latest candle from event

        Returns:
            Signal if conditions met, None otherwise

        Workflow:
            1. Check candle is closed
            2. Update correct interval buffer
            3. Check if all intervals ready
            4. Call analyze_mtf() with all buffers
            5. Return signal or None

        Example:
            ```python
            # Called by TradingEngine
            signal = await strategy.analyze(candle_5m)

            # Internally:
            # 1. Updates buffers['5m']
            # 2. Checks is_ready()
            # 3. Calls analyze_mtf(candle_5m, all_buffers)
            ```

        Notes:
            - Only analyzes on closed candles
            - Waits until all intervals initialized
            - Subclasses implement analyze_mtf(), not this method
        """
        # Only analyze closed candles
        if not candle.is_closed:
            return None

        # Update the buffer for this interval
        self.update_buffer(candle.interval, candle)

        # Update feature cache for this interval if available (Issue #19)
        if self._feature_cache is not None and candle.interval in self.intervals:
            self._feature_cache.update_on_new_candle(
                candle.interval, candle, self.buffers[candle.interval]
            )

        # Wait until all intervals have been initialized
        if not self.is_ready():
            return None

        # Call subclass implementation with all buffers
        return await self.analyze_mtf(candle, self.buffers)

    @abstractmethod
    async def analyze_mtf(self, candle: Candle, buffers: Dict[str, deque]) -> Optional[Signal]:
        """
        Analyze multiple timeframes and generate signal.

        Subclasses implement multi-timeframe analysis logic here.
        Receives all interval buffers for top-down analysis.

        Args:
            candle: Latest candle that triggered analysis
            buffers: All interval buffers {interval: deque}

        Returns:
            Signal if conditions met, None otherwise

        Implementation Pattern:
            ```python
            async def analyze_mtf(self, candle, buffers):
                # Step 1: HTF trend
                htf_trend = analyze_trend(buffers[self.htf_interval])
                if htf_trend == 'sideways':
                    return None

                # Step 2: MTF structure
                mtf_structure = find_structure(buffers[self.mtf_interval])
                if not mtf_structure:
                    return None

                # Step 3: LTF entry
                ltf_entry = check_entry(buffers[self.ltf_interval], htf_trend)
                if ltf_entry:
                    return Signal(...)

                return None
            ```

        Notes:
            - Called ONLY when all intervals are ready
            - Candle parameter is the latest (usually LTF)
            - Access any interval buffer via buffers[interval]
            - Must call calculate_take_profit() and calculate_stop_loss()
        """

    async def check_exit(self, candle: Candle, position: Position) -> Optional[Signal]:
        """
        Check if position should be exited (MTF version).

        Wrapper that updates buffer and calls check_exit_mtf() with all buffers.
        Called by TradingEngine when a position exists for the symbol.

        Args:
            candle: Latest closed candle
            position: Current open position

        Returns:
            Exit signal if conditions met, None otherwise

        Workflow:
            1. Check candle is closed
            2. Update correct interval buffer
            3. Check if all intervals ready
            4. Call check_exit_mtf() with all buffers and position
            5. Return exit signal or None
        """
        # Only analyze closed candles
        if not candle.is_closed:
            return None

        # Update the buffer for this interval
        self.update_buffer(candle.interval, candle)

        # Wait until all intervals have been initialized
        if not self.is_ready():
            return None

        # Call subclass implementation with all buffers and position
        return await self.check_exit_mtf(candle, self.buffers, position)

    async def check_exit_mtf(
        self, candle: Candle, buffers: Dict[str, deque], position: Position
    ) -> Optional[Signal]:
        """
        Check exit conditions using multiple timeframes.

        Subclasses can override to implement custom MTF exit logic
        (trailing stops based on HTF structure, time-based exits, etc.).

        Args:
            candle: Latest candle that triggered analysis
            buffers: All interval buffers {interval: deque}
            position: Current open position

        Returns:
            Signal with CLOSE_LONG or CLOSE_SHORT if exit conditions met,
            None otherwise

        Default Implementation:
            Returns None (no custom exit logic). Positions exit via TP/SL orders only.

        Override Example:
            ```python
            async def check_exit_mtf(self, candle, buffers, position):
                # Check if HTF trend reversed
                htf_trend = self._analyze_trend(buffers[self.htf_interval])

                # Exit LONG if trend turned bearish
                if position.side == 'LONG' and htf_trend == 'bearish':
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="htf_trend_reversal"
                    )

                # Exit SHORT if trend turned bullish
                if position.side == 'SHORT' and htf_trend == 'bullish':
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="htf_trend_reversal"
                    )

                return None
            ```

        Notes:
            - Called ONLY when all intervals are ready
            - Access any interval buffer via buffers[interval]
            - Position provides entry price, side, quantity for calculations
            - Exit signals bypass entry analysis entirely
        """
        return None  # Default: no custom MTF exit logic

    def get_buffer(self, interval: str) -> Optional[deque]:
        """
        Get buffer for specific interval.

        Args:
            interval: Interval to retrieve (e.g., '1h')

        Returns:
            Deque of candles for interval, None if not found

        Example:
            ```python
            htf_buffer = strategy.get_buffer('4h')
            if htf_buffer:
                recent_highs = [c.high for c in htf_buffer[-20:]]
            ```
        """
        return self.buffers.get(interval)

    @property
    def feature_cache(self) -> Optional["FeatureStateCache"]:
        """
        Get the feature cache instance.

        Returns:
            FeatureStateCache if initialized, None otherwise
        """
        return self._feature_cache

    def set_feature_cache(self, cache: "FeatureStateCache") -> None:
        """
        Set the feature cache for pre-computed feature management.

        Args:
            cache: FeatureStateCache instance

        Example:
            ```python
            from src.strategies.feature_cache import FeatureStateCache

            cache = FeatureStateCache(config={'max_order_blocks': 20})
            strategy.set_feature_cache(cache)
            ```
        """
        self._feature_cache = cache
        self.logger.info(
            f"[{self.__class__.__name__}] Feature cache configured for {self.symbol}"
        )

    def is_ready(self) -> bool:
        """
        Check if all intervals have been initialized.

        Validates that all interval buffers have received historical data
        and are ready for analysis.

        Returns:
            True if all intervals initialized, False otherwise

        Example:
            ```python
            if strategy.is_ready():
                # All intervals have data
                signal = await strategy.analyze_mtf(candle, buffers)
            else:
                # Still warming up
                return None
            ```

        Notes:
            - Called automatically by analyze()
            - Returns False until ALL intervals initialized
            - Prevents analysis with incomplete data
        """
        return all(self._initialized.values())

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price (default implementation).

        Subclasses can override for custom TP logic.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Take profit price

        Example:
            ```python
            # Default: 2% TP
            tp = strategy.calculate_take_profit(50000, 'LONG')
            # Returns: 51000 (50000 * 1.02)
            ```
        """
        tp_percent = self.config.get("tp_percent", 0.02)
        if side == "LONG":
            return entry_price * (1 + tp_percent)
        else:  # SHORT
            return entry_price * (1 - tp_percent)

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price (default implementation).

        Subclasses can override for custom SL logic.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Stop loss price

        Example:
            ```python
            # Default: 1% SL
            sl = strategy.calculate_stop_loss(50000, 'LONG')
            # Returns: 49500 (50000 * 0.99)
            ```
        """
        sl_percent = self.config.get("sl_percent", 0.01)
        if side == "LONG":
            return entry_price * (1 - sl_percent)
        else:  # SHORT
            return entry_price * (1 + sl_percent)
