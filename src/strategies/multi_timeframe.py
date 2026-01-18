"""
Multi-timeframe strategy base class for HTF→MTF→LTF analysis.

This module provides the MultiTimeframeStrategy base class that extends
BaseStrategy to support analysis across multiple timeframes simultaneously.
Enables strategies like ICT that require Higher Timeframe (HTF) trend analysis,
Medium Timeframe (MTF) structure detection, and Lower Timeframe (LTF) entry timing.

Issue #27: Simplified to leverage unified buffer structure from BaseStrategy.
MultiTimeframeStrategy now primarily adds:
- analyze_mtf() abstract method for multi-timeframe analysis
- check_exit_mtf() for multi-timeframe exit logic
- Feature cache support for pre-computed features
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

    Extends BaseStrategy to support analysis across multiple timeframes.
    Issue #27: Now uses unified buffer structure from BaseStrategy.

    Key Features (inherited from BaseStrategy Issue #27):
    - Separate candle buffers for each timeframe via self.buffers Dict
    - Per-interval historical data initialization
    - Automatic buffer updates routed by candle.interval
    - is_ready() validation ensures all intervals initialized

    Additional MTF Features:
    - analyze_mtf() method receives all interval buffers
    - check_exit_mtf() for multi-timeframe exit logic
    - Feature cache support for pre-computed features (Issue #19)

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
        # TradingEngine routes candles by interval (unified interface)
        engine = TradingEngine(config)
        strategy = ICTStrategy('BTCUSDT', {
            'htf_interval': '4h',
            'mtf_interval': '1h',
            'ltf_interval': '5m',
            'buffer_size': 200
        })
        engine.set_strategy(strategy)

        # Historical data initialized per-interval
        # Real-time candles routed to correct buffers via update_buffer(candle)
        # analyze_mtf() called on candle close
        ```
    """

    def __init__(self, symbol: str, intervals: List[str], config: dict) -> None:
        """
        Initialize multi-timeframe strategy.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            intervals: List of intervals to analyze (e.g., ['5m', '1h', '4h'])
            config: Strategy configuration with buffer_size and strategy params

        Attributes (inherited from BaseStrategy):
            intervals: List of intervals this strategy monitors
            buffers: Dict[interval, deque] - one buffer per interval
            _initialized: Dict[interval, bool] - initialization status per interval

        Additional Attributes:
            _feature_cache: Optional FeatureStateCache for pre-computed features

        Buffer Structure (inherited from BaseStrategy Issue #27):
            ```python
            {
                '5m': deque([Candle, ...], maxlen=200),
                '1h': deque([Candle, ...], maxlen=200),
                '4h': deque([Candle, ...], maxlen=200)
            }
            ```

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
            - Uses unified buffer structure from BaseStrategy (Issue #27)
            - Each interval has independent FIFO management
            - Buffer size applies to ALL intervals
        """
        # Initialize BaseStrategy with intervals (Issue #27 unified structure)
        super().__init__(symbol, config, intervals=intervals)

        # Feature cache for pre-computed features (Issue #19)
        # Subclasses can initialize this for feature-aware analysis
        self._feature_cache: Optional["FeatureStateCache"] = None

    def initialize_with_historical_data(
        self, candles: List[Candle], interval: Optional[str] = None
    ) -> None:
        """
        Initialize specific interval buffer with historical data.

        Issue #27: Unified signature with BaseStrategy (candles, interval=None).
        The interval parameter is required for MTF strategies.

        Args:
            candles: Historical candles for this interval (chronological order)
            interval: Interval to initialize (e.g., '1h'). Required for MTF.

        Example:
            ```python
            # Called by TradingEngine for each interval
            strategy.initialize_with_historical_data(historical_1h, interval='1h')
            strategy.initialize_with_historical_data(historical_5m, interval='5m')
            ```

        Notes:
            - Delegates to BaseStrategy.initialize_with_historical_data()
            - Adds feature cache initialization (Issue #19)
        """
        # Determine interval from parameter or first candle
        target_interval = interval
        if target_interval is None and candles:
            target_interval = candles[0].interval if hasattr(candles[0], 'interval') else None

        if target_interval is None:
            self.logger.warning(
                f"[{self.__class__.__name__}] No interval specified for {self.symbol}. "
                f"Using first registered interval: {self.intervals[0] if self.intervals else 'unknown'}"
            )
            target_interval = self.intervals[0] if self.intervals else "1m"

        # Call parent implementation with explicit interval
        super().initialize_with_historical_data(candles, interval=target_interval)

        # Initialize feature cache for this interval if available (Issue #19)
        if (
            self._feature_cache is not None
            and target_interval in self.buffers
            and self.buffers[target_interval]
        ):
            feature_counts = self._feature_cache.initialize_from_history(
                target_interval, list(self.buffers[target_interval])
            )
            self.logger.info(
                f"[{self.__class__.__name__}] {self.symbol} {target_interval} features initialized: "
                f"OBs={feature_counts.get('order_blocks', 0)}, "
                f"FVGs={feature_counts.get('fvgs', 0)}"
            )

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
            2. Update correct interval buffer (via BaseStrategy.update_buffer)
            3. Update feature cache if available
            4. Check if all intervals ready
            5. Call analyze_mtf() with all buffers
            6. Return signal or None

        Example:
            ```python
            # Called by TradingEngine
            signal = await strategy.analyze(candle_5m)

            # Internally:
            # 1. Updates buffers['5m'] via update_buffer(candle)
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

        # Update the buffer for this interval (uses BaseStrategy.update_buffer)
        self.update_buffer(candle)

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

        # Update the buffer for this interval (uses BaseStrategy.update_buffer)
        self.update_buffer(candle)

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
