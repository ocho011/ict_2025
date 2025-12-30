"""
Mock SMA Crossover Strategy for testing and validation.

This module implements a Simple Moving Average (SMA) crossover strategy
for testing the trading system pipeline. It serves as a reference implementation
demonstrating how to extend BaseStrategy with concrete trading logic.

The strategy generates signals based on the crossover of fast and slow SMAs:
- Golden Cross (fast SMA crosses above slow SMA) → LONG entry
- Death Cross (fast SMA crosses below slow SMA) → SHORT entry
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


class MockSMACrossoverStrategy(BaseStrategy):
    """
    SMA Crossover Strategy using fast and slow moving averages.

    This strategy:
    - Calculates fast SMA (default 10 periods) and slow SMA (default 20 periods)
    - Detects crossovers between fast and slow SMAs
    - Generates LONG signals on golden cross (fast crosses above slow)
    - Generates SHORT signals on death cross (fast crosses below slow)
    - Prevents duplicate signals on consecutive crossovers

    Configuration Parameters:
        fast_period (int): Period for fast SMA calculation (default: 10)
        slow_period (int): Period for slow SMA calculation (default: 20)
        risk_reward_ratio (float): TP/SL ratio for position sizing (default: 2.0)
        stop_loss_percent (float): Stop loss as percentage of entry (default: 0.01)
        buffer_size (int): Candle buffer size (default: 100)

    Example:
        ```python
        config = {
            'fast_period': 10,
            'slow_period': 20,
            'risk_reward_ratio': 2.0,
            'stop_loss_percent': 0.01,
            'buffer_size': 100
        }
        strategy = MockSMACrossoverStrategy('BTCUSDT', config)

        # TradingEngine calls analyze() for each candle
        signal = await strategy.analyze(candle)
        if signal:
            # Signal generated - golden/death cross detected
            print(f"Signal: {signal.signal_type} at {signal.entry_price}")
        ```

    Performance Characteristics:
        - Time Complexity: O(n) where n = slow_period (numpy array slicing)
        - Space Complexity: O(buffer_size) for candle buffer
        - Typical execution: <5ms for buffer_size=100

    Notes:
        - Requires buffer_size >= slow_period for accurate SMA calculation
        - Uses numpy for efficient SMA calculation
        - Tracks last signal to prevent duplicate consecutive signals
        - Suitable for testing and demonstration, not production trading
    """

    def __init__(self, symbol: str, config: dict) -> None:
        """
        Initialize MockSMACrossoverStrategy with configuration.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
            config: Strategy configuration dictionary with optional parameters:
                - fast_period (int): Fast SMA period (default: 10)
                - slow_period (int): Slow SMA period (default: 20)
                - risk_reward_ratio (float): TP/SL ratio (default: 2.0)
                - stop_loss_percent (float): SL percentage (default: 0.01)
                - buffer_size (int): Buffer size (default: 100)

        Raises:
            ValueError: If fast_period >= slow_period (fast must be faster)

        Example:
            ```python
            # Default configuration
            strategy = MockSMACrossoverStrategy('BTCUSDT', {})

            # Custom configuration
            config = {'fast_period': 5, 'slow_period': 15, 'risk_reward_ratio': 3.0}
            strategy = MockSMACrossoverStrategy('ETHUSDT', config)
            ```

        Notes:
            - fast_period must be < slow_period for valid crossover detection
            - Larger slow_period requires larger buffer_size for accuracy
            - Risk-reward ratio affects TP calculation relative to SL
        """
        super().__init__(symbol, config)

        # Logger for strategy status
        self.logger = logging.getLogger(__name__)

        # SMA periods
        self.fast_period: int = config.get("fast_period", 10)
        self.slow_period: int = config.get("slow_period", 20)

        # Risk management parameters
        self.risk_reward_ratio: float = config.get("risk_reward_ratio", 2.0)
        self.stop_loss_percent: float = config.get("stop_loss_percent", 0.01)

        # Internal state
        self._last_signal_type: Optional[SignalType] = None

        # Validate configuration
        if self.fast_period >= self.slow_period:
            raise ValueError(
                f"fast_period ({self.fast_period}) must be < slow_period ({self.slow_period})"
            )

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle for SMA crossover signals.

        This method:
        1. Validates candle is closed (only analyze complete candles)
        2. Updates buffer with new candle
        3. Checks buffer has sufficient data (>= slow_period)
        4. Calculates current fast/slow SMAs
        5. Calculates previous fast/slow SMAs (for crossover detection)
        6. Detects golden cross → LONG signal
        7. Detects death cross → SHORT signal
        8. Prevents duplicate signals of same type

        Args:
            candle: Latest candle to analyze

        Returns:
            Signal object if crossover detected and different from last signal,
            None otherwise

        Crossover Detection Logic:
            Golden Cross (LONG):
                - Previous: fast_sma <= slow_sma
                - Current: fast_sma > slow_sma
                - Condition: fast crosses ABOVE slow

            Death Cross (SHORT):
                - Previous: fast_sma >= slow_sma
                - Current: fast_sma < slow_sma
                - Condition: fast crosses BELOW slow

        Example:
            ```python
            # Buffer warm-up (need slow_period candles)
            for candle in historical_candles[:20]:
                signal = await strategy.analyze(candle)
                # signal will be None until buffer >= slow_period

            # After warm-up, analyze new candles
            candle = new_candle_from_exchange()
            signal = await strategy.analyze(candle)
            if signal:
                if signal.signal_type == SignalType.LONG_ENTRY:
                    print("Golden cross detected - buy signal")
                elif signal.signal_type == SignalType.SHORT_ENTRY:
                    print("Death cross detected - sell signal")
            ```

        Performance:
            - Returns None immediately if candle not closed (O(1))
            - SMA calculation: O(slow_period) via numpy array operations
            - Typical execution: <5ms for default parameters

        Notes:
            - Only analyzes closed candles (is_closed=True)
            - Requires buffer_size >= slow_period for valid signals
            - Prevents duplicate consecutive signals via _last_signal_type tracking
            - Uses _create_signal() helper to construct Signal objects
        """
        # Step 1: Only analyze closed candles
        if not candle.is_closed:
            return None

        # Step 2: Update buffer with new candle
        self.update_buffer(candle)

        # Step 3: Check buffer has enough data
        if len(self.candle_buffer) < self.slow_period:
            # Log buffer warm-up progress
            self.logger.info(
                f"📊 Buffer warming up: {len(self.candle_buffer)}/{self.slow_period} "
                f"candles collected for {candle.symbol} {candle.interval}"
            )
            return None

        # Step 4: Extract close prices for SMA calculation
        close_prices = np.array([c.close for c in self.candle_buffer])

        # Step 5: Calculate current SMAs
        current_fast_sma = np.mean(close_prices[-self.fast_period :])
        current_slow_sma = np.mean(close_prices[-self.slow_period :])

        # Step 6: Calculate previous SMAs (for crossover detection)
        # Need at least slow_period + 1 candles for previous calculation
        if len(self.candle_buffer) < self.slow_period + 1:
            self.logger.info(
                f"📈 SMA ready, waiting for crossover detection data: "
                f"{len(self.candle_buffer)}/{self.slow_period + 1} candles "
                f"for {candle.symbol} {candle.interval}"
            )
            return None

        previous_fast_sma = np.mean(close_prices[-(self.fast_period + 1) : -1])
        previous_slow_sma = np.mean(close_prices[-(self.slow_period + 1) : -1])

        # Step 7: Detect golden cross (fast crosses above slow)
        if previous_fast_sma <= previous_slow_sma and current_fast_sma > current_slow_sma:
            # Golden cross detected
            if self._last_signal_type == SignalType.LONG_ENTRY:
                # Prevent duplicate LONG signals
                return None

            signal = self._create_signal(candle, SignalType.LONG_ENTRY)
            self._last_signal_type = SignalType.LONG_ENTRY
            return signal

        # Step 8: Detect death cross (fast crosses below slow)
        if previous_fast_sma >= previous_slow_sma and current_fast_sma < current_slow_sma:
            # Death cross detected
            if self._last_signal_type == SignalType.SHORT_ENTRY:
                # Prevent duplicate SHORT signals
                return None

            signal = self._create_signal(candle, SignalType.SHORT_ENTRY)
            self._last_signal_type = SignalType.SHORT_ENTRY
            return signal

        # No crossover detected
        return None

    def _create_signal(self, candle: Candle, signal_type: SignalType) -> Signal:
        """
        Create Signal object with calculated TP/SL prices.

        Helper method to construct Signal objects with proper entry/TP/SL prices
        based on the signal type (LONG/SHORT).

        Args:
            candle: Candle that triggered the signal
            signal_type: Type of signal (LONG_ENTRY or SHORT_ENTRY)

        Returns:
            Signal object with entry, TP, SL, and metadata

        Example:
            ```python
            # Internal usage in analyze()
            signal = self._create_signal(candle, SignalType.LONG_ENTRY)
            # signal.entry_price = candle.close
            # signal.take_profit = calculated TP above entry
            # signal.stop_loss = calculated SL below entry
            ```

        Notes:
            - Entry price = candle close price
            - TP/SL calculated via calculate_take_profit() and calculate_stop_loss()
            - Signal validates TP/SL relationships in __post_init__()
            - Strategy name automatically set to class name
        """
        side = "LONG" if signal_type == SignalType.LONG_ENTRY else "SHORT"
        entry_price = candle.close

        return Signal(
            signal_type=signal_type,
            symbol=self.symbol,
            entry_price=entry_price,
            take_profit=self.calculate_take_profit(entry_price, side),
            stop_loss=self.calculate_stop_loss(entry_price, side),
            strategy_name=self.__class__.__name__,
            timestamp=datetime.now(timezone.utc),
        )

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price based on risk-reward ratio.

        TP is calculated as a multiple of the stop loss distance:
        - LONG: TP = entry + (SL_distance * risk_reward_ratio)
        - SHORT: TP = entry - (SL_distance * risk_reward_ratio)

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Take profit price (float)

        Formula:
            SL_distance = entry_price * stop_loss_percent
            TP_distance = SL_distance * risk_reward_ratio

            LONG:  TP = entry + TP_distance
            SHORT: TP = entry - TP_distance

        Example:
            ```python
            # Default: risk_reward_ratio=2.0, stop_loss_percent=0.01
            entry = 50000.0

            # LONG position
            tp_long = strategy.calculate_take_profit(50000.0, 'LONG')
            # SL_distance = 50000 * 0.01 = 500
            # TP_distance = 500 * 2.0 = 1000
            # TP = 50000 + 1000 = 51000.0

            # SHORT position
            tp_short = strategy.calculate_take_profit(50000.0, 'SHORT')
            # TP = 50000 - 1000 = 49000.0
            ```

        Validation:
            - LONG: TP > entry (enforced by Signal.__post_init__)
            - SHORT: TP < entry (enforced by Signal.__post_init__)

        Notes:
            - Risk-reward ratio configurable via config dict
            - Higher ratio = larger TP relative to SL
            - Typical values: 1.5 (conservative) to 3.0 (aggressive)
        """
        sl_distance = entry_price * self.stop_loss_percent
        tp_distance = sl_distance * self.risk_reward_ratio

        if side == "LONG":
            return entry_price + tp_distance
        else:  # SHORT
            return entry_price - tp_distance

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price as percentage of entry price.

        SL is set at a fixed percentage below (LONG) or above (SHORT) entry:
        - LONG: SL = entry - (entry * stop_loss_percent)
        - SHORT: SL = entry + (entry * stop_loss_percent)

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Stop loss price (float)

        Formula:
            LONG:  SL = entry * (1 - stop_loss_percent)
            SHORT: SL = entry * (1 + stop_loss_percent)

        Example:
            ```python
            # Default: stop_loss_percent=0.01 (1%)
            entry = 50000.0

            # LONG position
            sl_long = strategy.calculate_stop_loss(50000.0, 'LONG')
            # SL = 50000 * (1 - 0.01) = 50000 * 0.99 = 49500.0

            # SHORT position
            sl_short = strategy.calculate_stop_loss(50000.0, 'SHORT')
            # SL = 50000 * (1 + 0.01) = 50000 * 1.01 = 50500.0
            ```

        Validation:
            - LONG: SL < entry (enforced by Signal.__post_init__)
            - SHORT: SL > entry (enforced by Signal.__post_init__)

        Notes:
            - Fixed percentage SL (simple but effective for testing)
            - Configurable via config dict
            - Typical values: 0.005 (0.5%) to 0.02 (2%)
            - Production strategies might use ATR or volatility-based SL
        """
        if side == "LONG":
            return entry_price * (1 - self.stop_loss_percent)
        else:  # SHORT
            return entry_price * (1 + self.stop_loss_percent)
