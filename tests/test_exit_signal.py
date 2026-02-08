"""
Unit tests for Exit Signal Separation - Issue #25

Tests for:
1. Signal model with optional TP/SL for exit signals
2. RiskGuard exit signal validation
3. BaseStrategy check_exit() method
4. MultiTimeframeStrategy check_exit_mtf() method
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.risk.risk_guard import RiskGuard


class TestSignalModelExitSupport:
    """Test suite for Signal model with exit signal support"""

    def test_entry_signal_requires_tp_sl(self):
        """LONG_ENTRY signal requires take_profit and stop_loss"""
        with pytest.raises(ValueError, match="take_profit is required"):
            Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                strategy_name="test",
                timestamp=datetime.now(timezone.utc),
                # Missing take_profit and stop_loss
            )

    def test_entry_signal_requires_sl(self):
        """LONG_ENTRY signal requires stop_loss"""
        with pytest.raises(ValueError, match="stop_loss is required"):
            Signal(
                signal_type=SignalType.LONG_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                take_profit=51000,
                # Missing stop_loss
                strategy_name="test",
                timestamp=datetime.now(timezone.utc),
            )

    def test_short_entry_requires_tp_sl(self):
        """SHORT_ENTRY signal requires take_profit and stop_loss"""
        with pytest.raises(ValueError, match="take_profit is required"):
            Signal(
                signal_type=SignalType.SHORT_ENTRY,
                symbol="BTCUSDT",
                entry_price=50000,
                strategy_name="test",
                timestamp=datetime.now(timezone.utc),
            )

    def test_exit_signal_tp_sl_optional(self):
        """CLOSE_LONG signal does NOT require take_profit or stop_loss"""
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
            exit_reason="trailing_stop",
        )

        assert signal.signal_type == SignalType.CLOSE_LONG
        assert signal.take_profit is None
        assert signal.stop_loss is None
        assert signal.exit_reason == "trailing_stop"

    def test_close_short_signal_tp_sl_optional(self):
        """CLOSE_SHORT signal does NOT require take_profit or stop_loss"""
        signal = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
            exit_reason="htf_trend_reversal",
        )

        assert signal.signal_type == SignalType.CLOSE_SHORT
        assert signal.take_profit is None
        assert signal.stop_loss is None
        assert signal.exit_reason == "htf_trend_reversal"

    def test_is_entry_signal_property(self):
        """is_entry_signal returns True for entry signals"""
        long_entry = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=51000,
            stop_loss=49000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        assert long_entry.is_entry_signal is True
        assert long_entry.is_exit_signal is False

        short_entry = Signal(
            signal_type=SignalType.SHORT_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=49000,
            stop_loss=51000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        assert short_entry.is_entry_signal is True
        assert short_entry.is_exit_signal is False

    def test_is_exit_signal_property(self):
        """is_exit_signal returns True for exit signals"""
        close_long = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        assert close_long.is_exit_signal is True
        assert close_long.is_entry_signal is False

        close_short = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        assert close_short.is_exit_signal is True
        assert close_short.is_entry_signal is False

    def test_exit_signal_risk_amount_zero(self):
        """Exit signal risk_amount returns 0.0 (no stop_loss)"""
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        assert signal.risk_amount == 0.0
        assert signal.reward_amount == 0.0
        assert signal.risk_reward_ratio == 0.0

    def test_valid_long_entry_with_tp_sl(self):
        """Valid LONG entry signal with proper TP/SL"""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000,
            take_profit=52000,  # Above entry
            stop_loss=49000,  # Below entry
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )

        assert signal.take_profit == 52000
        assert signal.stop_loss == 49000
        assert signal.risk_amount == pytest.approx(1000, rel=0.01)
        assert signal.reward_amount == pytest.approx(2000, rel=0.01)
        assert signal.risk_reward_ratio == pytest.approx(2.0, rel=0.01)


class TestRiskGuardExitValidation:
    """Test suite for RiskGuard exit signal validation"""

    @pytest.fixture
    def mock_audit_logger(self):
        """Mock AuditLogger"""
        return MagicMock()

    @pytest.fixture
    def risk_manager(self, mock_audit_logger):
        """Setup RiskGuard with standard config"""
        config = {
            "max_risk_per_trade": 0.01,
            "max_leverage": 20,
            "default_leverage": 10,
            "max_position_size_percent": 0.1,
        }
        return RiskGuard(config, audit_logger=mock_audit_logger)

    def test_close_long_with_long_position_valid(self, risk_manager):
        """CLOSE_LONG signal with LONG position is valid"""
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
            exit_reason="trailing_stop",
        )
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=48000,
            quantity=0.1,
            leverage=10,
        )

        result = risk_manager.validate_risk(signal, position)
        assert result is True

    def test_close_short_with_short_position_valid(self, risk_manager):
        """CLOSE_SHORT signal with SHORT position is valid"""
        signal = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
            exit_reason="time_exit",
        )
        position = Position(
            symbol="BTCUSDT",
            side="SHORT",
            entry_price=52000,
            quantity=0.1,
            leverage=10,
        )

        result = risk_manager.validate_risk(signal, position)
        assert result is True

    def test_close_long_no_position_rejected(self, risk_manager, caplog):
        """CLOSE_LONG signal without position is rejected"""
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, None)

        assert result is False
        assert "no position exists" in caplog.text

    def test_close_short_no_position_rejected(self, risk_manager, caplog):
        """CLOSE_SHORT signal without position is rejected"""
        signal = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, None)

        assert result is False
        assert "no position exists" in caplog.text

    def test_close_long_with_short_position_rejected(self, risk_manager, caplog):
        """CLOSE_LONG signal with SHORT position is rejected (side mismatch)"""
        signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        position = Position(
            symbol="BTCUSDT",
            side="SHORT",  # Wrong side for CLOSE_LONG
            entry_price=52000,
            quantity=0.1,
            leverage=10,
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position)

        assert result is False
        assert (
            "position_side_mismatch" in caplog.text
            or "requires LONG position" in caplog.text
        )

    def test_close_short_with_long_position_rejected(self, risk_manager, caplog):
        """CLOSE_SHORT signal with LONG position is rejected (side mismatch)"""
        signal = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol="BTCUSDT",
            entry_price=50000,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        position = Position(
            symbol="BTCUSDT",
            side="LONG",  # Wrong side for CLOSE_SHORT
            entry_price=48000,
            quantity=0.1,
            leverage=10,
        )

        with caplog.at_level(logging.WARNING):
            result = risk_manager.validate_risk(signal, position)

        assert result is False
        assert (
            "position_side_mismatch" in caplog.text
            or "requires SHORT position" in caplog.text
        )


class TestBaseStrategyCheckExit:
    """Test suite for BaseStrategy check_exit() method"""

    @pytest.fixture
    def mock_candle(self):
        """Create mock candle for testing"""
        now = datetime.now(timezone.utc)
        return Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=now,
            open=50000,
            high=50500,
            low=49500,
            close=50200,
            volume=100.0,
            close_time=now,
            is_closed=True,
        )

    @pytest.fixture
    def mock_position(self):
        """Create mock position for testing"""
        return Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=49000,
            quantity=0.1,
            leverage=10,
        )

    @pytest.mark.asyncio
    async def test_base_strategy_check_exit_returns_none(
        self, mock_candle, mock_position
    ):
        """BaseStrategy.check_exit() default returns None"""
        from src.strategies.base import BaseStrategy

        # Create a concrete implementation for testing
        class TestStrategy(BaseStrategy):
            async def analyze(self, candle):
                return None

            async def should_exit(self, position, candle):
                return None

            def calculate_take_profit(self, entry_price, side):
                return entry_price * 1.02

            def calculate_stop_loss(self, entry_price, side):
                return entry_price * 0.99

        strategy = TestStrategy(symbol="BTCUSDT", config={"buffer_size": 100})
        result = await strategy.check_exit(mock_candle, mock_position)
        assert result is None


class TestMultiTimeframeStrategyCheckExit:
    """Test suite for MultiTimeframeStrategy check_exit_mtf() method"""

    @pytest.fixture
    def mock_candle(self):
        """Create mock candle for testing"""
        now = datetime.now(timezone.utc)
        return Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=now,
            open=50000,
            high=50500,
            low=49500,
            close=50200,
            volume=100.0,
            close_time=now,
            is_closed=True,
        )

    @pytest.fixture
    def mock_position(self):
        """Create mock position for testing"""
        return Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=49000,
            quantity=0.1,
            leverage=10,
        )

    @pytest.mark.asyncio
    async def test_base_strategy_check_exit_returns_none(
        self, mock_candle, mock_position
    ):
        """BaseStrategy.check_exit() default returns None"""
        from collections import deque

        from src.strategies.base import BaseStrategy

        # Create a concrete implementation for testing
        class TestMTFStrategy(BaseStrategy):
            async def analyze(self, candle):
                return None

            async def should_exit(self, position, candle):
                return None

            def calculate_take_profit(self, entry_price, side):
                return entry_price * 1.02

            def calculate_stop_loss(self, entry_price, side):
                return entry_price * 0.99

        strategy = TestMTFStrategy(
            symbol="BTCUSDT",
            config={"buffer_size": 100},
            intervals=["5m", "1h", "4h"],
        )

        # Initialize buffers
        for interval in strategy.intervals:
            strategy._initialized[interval] = True

        result = await strategy.check_exit(mock_candle, mock_position)
        assert result is None

    @pytest.mark.asyncio
    async def test_base_strategy_check_exit_override(self, mock_candle, mock_position):
        """BaseStrategy.check_exit() can be overridden for custom exit logic"""
        from collections import deque

        from src.strategies.base import BaseStrategy

        # Create a strategy that returns an exit signal
        class ExitingMTFStrategy(BaseStrategy):
            async def analyze(self, candle):
                return None

            async def check_exit(self, candle, position):
                # Return exit signal when position exists
                return Signal(
                    signal_type=SignalType.CLOSE_LONG,
                    symbol=self.symbol,
                    entry_price=candle.close,
                    strategy_name=self.__class__.__name__,
                    timestamp=datetime.now(timezone.utc),
                    exit_reason="test_exit",
                )

            async def should_exit(self, position, candle):
                return None  # Implementation to satisfy new abstract method

            def calculate_take_profit(self, entry_price, side):
                return entry_price * 1.02

            def calculate_stop_loss(self, entry_price, side):
                return entry_price * 0.99

        strategy = ExitingMTFStrategy(
            symbol="BTCUSDT",
            config={"buffer_size": 100},
            intervals=["5m", "1h", "4h"],
        )

        # Initialize buffers
        for interval in strategy.intervals:
            strategy._initialized[interval] = True
            strategy.buffers[interval].append(mock_candle)

        result = await strategy.check_exit(mock_candle, mock_position)
        assert result is not None
        assert result.signal_type == SignalType.CLOSE_LONG
        assert result.exit_reason == "test_exit"
