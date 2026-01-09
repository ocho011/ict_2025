"""
Always Signal Strategy for quick testing.

This is a TEST-ONLY strategy that generates a signal on every closed candle
to verify the complete trading pipeline (signal → risk check → order execution).

⚠️ WARNING: DO NOT USE IN PRODUCTION OR WITH REAL MONEY ⚠️
This strategy generates signals continuously without any market analysis.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


class AlwaysSignalStrategy(BaseStrategy):
    """
    Test strategy that generates alternating LONG/SHORT signals every candle.

    This strategy is designed ONLY for testing the complete trading system:
    1. Signal generation works
    2. EventBus routes signals correctly
    3. RiskManager validates signals
    4. OrderManager executes orders (on testnet)
    5. Position tracking works

    Configuration Parameters:
        signal_type (str): 'LONG', 'SHORT', or 'ALTERNATE' (default: 'ALTERNATE')
        risk_reward_ratio (float): TP/SL ratio (default: 2.0)
        stop_loss_percent (float): SL percentage (default: 0.02)

    Example:
        ```python
        # Alternate between LONG and SHORT
        config = {'signal_type': 'ALTERNATE'}
        strategy = AlwaysSignalStrategy('BTCUSDT', config)

        # Always LONG signals
        config = {'signal_type': 'LONG'}
        strategy = AlwaysSignalStrategy('BTCUSDT', config)
        ```

    ⚠️ SAFETY NOTES:
        - Only use on TESTNET with is_testnet=True
        - Will generate orders every minute (if using 1m candles)
        - Uses very small position sizes (1% risk per trade)
        - Designed for pipeline testing, not actual trading
    """

    def __init__(self, symbol: str, config: dict) -> None:
        """
        Initialize AlwaysSignalStrategy with configuration.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            config: Strategy configuration with optional parameters:
                - signal_type (str): 'LONG', 'SHORT', or 'ALTERNATE'
                - risk_reward_ratio (float): TP/SL ratio (default: 2.0)
                - stop_loss_percent (float): SL percentage (default: 0.02)
        """
        super().__init__(symbol, config)

        # Logger for test strategy
        self.logger = logging.getLogger(__name__)

        # Signal generation mode
        self.signal_mode: str = config.get("signal_type", "ALTERNATE").upper()
        if self.signal_mode not in ["LONG", "SHORT", "ALTERNATE"]:
            raise ValueError(
                f"signal_type must be 'LONG', 'SHORT', or 'ALTERNATE', got '{self.signal_mode}'"
            )

        # Risk management parameters
        self.risk_reward_ratio: float = config.get("risk_reward_ratio", 2.0)
        self.stop_loss_percent: float = config.get("stop_loss_percent", 0.02)

        # Internal state for alternating signals
        self._last_signal_type: Optional[SignalType] = None

        # Warn user this is a test strategy
        self.logger.warning("⚠️ AlwaysSignalStrategy loaded - TEST ONLY, DO NOT USE WITH REAL MONEY")  # noqa: E501
        self.logger.info(f"Signal mode: {self.signal_mode}")

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Generate signal on every closed candle for testing.

        Args:
            candle: Current candle data

        Returns:
            Signal on every closed candle, None for open candles

        Note:
            - Only generates signals for closed candles
            - Alternates between LONG/SHORT if mode='ALTERNATE'
            - Always generates same type if mode='LONG' or 'SHORT'
        """
        # Only analyze closed candles
        if not candle.is_closed:
            return None

        # Update buffer (even though we don't use it)
        self.update_buffer(candle)

        # Determine signal type based on mode
        if self.signal_mode == "ALTERNATE":
            # Alternate between LONG and SHORT
            if self._last_signal_type == SignalType.LONG_ENTRY:
                signal_type = SignalType.SHORT_ENTRY
            else:
                signal_type = SignalType.LONG_ENTRY
        elif self.signal_mode == "LONG":
            signal_type = SignalType.LONG_ENTRY
        else:  # SHORT
            signal_type = SignalType.SHORT_ENTRY

        # Create signal
        signal = self._create_signal(candle, signal_type)

        # Track for alternating mode
        self._last_signal_type = signal_type

        # Log signal generation (for testing visibility)
        self.logger.info(
            f"🧪 TEST SIGNAL: {signal_type.value} @ {candle.close} "
            f"(TP: {signal.take_profit}, SL: {signal.stop_loss})"
        )

        return signal

    def _create_signal(self, candle: Candle, signal_type: SignalType) -> Signal:
        """
        Create Signal object with calculated TP/SL prices.

        Args:
            candle: Candle used for entry price
            signal_type: Type of signal (LONG_ENTRY or SHORT_ENTRY)

        Returns:
            Signal object with entry, TP, and SL prices
        """
        entry_price = candle.close

        # Calculate TP and SL based on signal type
        if signal_type == SignalType.LONG_ENTRY:
            tp_price = self.calculate_take_profit(entry_price, "LONG")
            sl_price = self.calculate_stop_loss(entry_price, "LONG")
        else:  # SHORT_ENTRY
            tp_price = self.calculate_take_profit(entry_price, "SHORT")
            sl_price = self.calculate_stop_loss(entry_price, "SHORT")

        return Signal(
            signal_type=signal_type,
            symbol=self.symbol,
            entry_price=entry_price,
            take_profit=tp_price,
            stop_loss=sl_price,
            strategy_name=self.__class__.__name__,
            timestamp=datetime.now(timezone.utc),
        )

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit price.

        Args:
            entry_price: Entry price for the trade
            side: Trade direction ('LONG' or 'SHORT')

        Returns:
            Take profit price
        """
        sl_distance = entry_price * self.stop_loss_percent
        tp_distance = sl_distance * self.risk_reward_ratio

        if side == "LONG":
            return entry_price + tp_distance
        else:  # SHORT
            return entry_price - tp_distance

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss price.

        Args:
            entry_price: Entry price for the trade
            side: Trade direction ('LONG' or 'SHORT')

        Returns:
            Stop loss price
        """
        sl_distance = entry_price * self.stop_loss_percent

        if side == "LONG":
            return entry_price - sl_distance
        else:  # SHORT
            return entry_price + sl_distance
