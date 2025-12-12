"""
Unit tests for BaseStrategy abstract class.

Tests verify:
- Abstract method enforcement (cannot instantiate directly)
- Initialization with default and custom configurations
- FIFO buffer management behavior
- Concrete implementation compliance with interface
"""

from datetime import datetime, timezone
from typing import Optional

import pytest

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


# ============================================================================
# Test Helper: Concrete Strategy Implementation
# ============================================================================

class ConcreteTestStrategy(BaseStrategy):
    """
    Concrete strategy implementation for testing.

    Implements all abstract methods with simple logic for testing purposes.
    """

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Simple analysis: return LONG signal if close > 50000, else None.

        This is for testing purposes only - real strategies have complex logic.
        """
        if not candle.is_closed:
            return None

        self.update_buffer(candle)

        if len(self.candle_buffer) < 2:
            return None

        # Simple condition: price above threshold
        if candle.close > 50000:
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
        """
        Calculate TP at 2% profit.
        """
        tp_percent = self.config.get('tp_percent', 0.02)
        if side == 'LONG':
            return entry_price * (1 + tp_percent)
        else:  # SHORT
            return entry_price * (1 - tp_percent)

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate SL at 1% loss.
        """
        sl_percent = self.config.get('sl_percent', 0.01)
        if side == 'LONG':
            return entry_price * (1 - sl_percent)
        else:  # SHORT
            return entry_price * (1 + sl_percent)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_candle():
    """Create a sample closed candle for testing."""
    return Candle(
        symbol='BTCUSDT',
        interval='1m',
        open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        open=50000.0,
        high=51000.0,
        low=49000.0,
        close=50500.0,
        volume=100.0,
        is_closed=True
    )


@pytest.fixture
def open_candle():
    """Create an open (incomplete) candle for testing."""
    return Candle(
        symbol='BTCUSDT',
        interval='1m',
        open_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc),
        open=50500.0,
        high=51000.0,
        low=50000.0,
        close=50800.0,
        volume=50.0,
        is_closed=False
    )


@pytest.fixture
def default_config():
    """Default configuration dictionary."""
    return {}


@pytest.fixture
def custom_config():
    """Custom configuration with specific buffer size and strategy params."""
    return {
        'buffer_size': 200,
        'tp_percent': 0.03,
        'sl_percent': 0.015
    }


# ============================================================================
# Test Class: Abstract Method Enforcement
# ============================================================================

class TestAbstractMethodEnforcement:
    """Test that BaseStrategy cannot be instantiated directly."""

    def test_cannot_instantiate_base_strategy_directly(self):
        """BaseStrategy is abstract and should raise TypeError if instantiated."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseStrategy('BTCUSDT', {})

    def test_concrete_implementation_can_be_instantiated(self, default_config):
        """Concrete implementation with all abstract methods should work."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)
        assert strategy is not None
        assert isinstance(strategy, BaseStrategy)


# ============================================================================
# Test Class: Initialization
# ============================================================================

class TestBaseStrategyInitialization:
    """Test strategy initialization with various configurations."""

    def test_initialization_with_default_config(self, default_config):
        """Test initialization with empty config uses default buffer_size."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        assert strategy.symbol == 'BTCUSDT'
        assert strategy.config == default_config
        assert strategy.buffer_size == 100  # Default value
        assert strategy.candle_buffer == []
        assert len(strategy.candle_buffer) == 0

    def test_initialization_with_custom_buffer_size(self, custom_config):
        """Test initialization with custom buffer_size in config."""
        strategy = ConcreteTestStrategy('ETHUSDT', custom_config)

        assert strategy.symbol == 'ETHUSDT'
        assert strategy.config == custom_config
        assert strategy.buffer_size == 200  # Custom value
        assert strategy.candle_buffer == []

    def test_config_stores_strategy_specific_parameters(self, custom_config):
        """Test that config dict stores strategy-specific parameters."""
        strategy = ConcreteTestStrategy('BTCUSDT', custom_config)

        assert strategy.config.get('tp_percent') == 0.03
        assert strategy.config.get('sl_percent') == 0.015

    def test_different_symbols_create_separate_strategies(self, default_config):
        """Test that strategies for different symbols are independent."""
        btc_strategy = ConcreteTestStrategy('BTCUSDT', default_config)
        eth_strategy = ConcreteTestStrategy('ETHUSDT', default_config)

        assert btc_strategy.symbol == 'BTCUSDT'
        assert eth_strategy.symbol == 'ETHUSDT'
        assert btc_strategy is not eth_strategy


# ============================================================================
# Test Class: Buffer Management
# ============================================================================

class TestBufferManagement:
    """Test FIFO buffer management functionality."""

    def test_update_buffer_appends_candle(self, default_config, sample_candle):
        """Test that update_buffer appends candle to buffer."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        assert len(strategy.candle_buffer) == 0

        strategy.update_buffer(sample_candle)

        assert len(strategy.candle_buffer) == 1
        assert strategy.candle_buffer[0] == sample_candle

    def test_buffer_maintains_chronological_order(self, default_config):
        """Test that buffer maintains candles in chronological order."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        # Create 3 candles with sequential timestamps
        candles = [
            Candle(
                symbol='BTCUSDT',
                interval='1m',
                open_time=datetime(2024, 1, 1, 0, i, tzinfo=timezone.utc),
                close_time=datetime(2024, 1, 1, 0, i+1, tzinfo=timezone.utc),
                open=50000.0 + i * 100,
                high=51000.0 + i * 100,
                low=49000.0 + i * 100,
                close=50500.0 + i * 100,
                volume=100.0,
                is_closed=True
            )
            for i in range(3)
        ]

        for candle in candles:
            strategy.update_buffer(candle)

        assert len(strategy.candle_buffer) == 3
        assert strategy.candle_buffer[0] == candles[0]  # Oldest
        assert strategy.candle_buffer[1] == candles[1]  # Middle
        assert strategy.candle_buffer[2] == candles[2]  # Newest

    def test_buffer_fifo_behavior_when_full(self, default_config):
        """Test that oldest candle is removed when buffer exceeds buffer_size."""
        # Use small buffer size for testing
        config = {'buffer_size': 3}
        strategy = ConcreteTestStrategy('BTCUSDT', config)

        # Add 4 candles (buffer_size = 3)
        candles = [
            Candle(
                symbol='BTCUSDT',
                interval='1m',
                open_time=datetime(2024, 1, 1, 0, i, tzinfo=timezone.utc),
                close_time=datetime(2024, 1, 1, 0, i+1, tzinfo=timezone.utc),
                open=50000.0 + i * 100,
                high=51000.0,
                low=49000.0,
                close=50500.0,
                volume=100.0,
                is_closed=True
            )
            for i in range(4)
        ]

        for candle in candles:
            strategy.update_buffer(candle)

        # Buffer should contain last 3 candles (FIFO removed first)
        assert len(strategy.candle_buffer) == 3
        assert strategy.candle_buffer[0] == candles[1]  # candles[0] removed
        assert strategy.candle_buffer[1] == candles[2]
        assert strategy.candle_buffer[2] == candles[3]

    def test_buffer_size_limit_enforcement(self, default_config):
        """Test that buffer never exceeds buffer_size."""
        config = {'buffer_size': 5}
        strategy = ConcreteTestStrategy('BTCUSDT', config)

        # Add 10 candles (buffer_size = 5)
        for i in range(10):
            candle = Candle(
                symbol='BTCUSDT',
                interval='1m',
                open_time=datetime(2024, 1, 1, 0, i, tzinfo=timezone.utc),
                close_time=datetime(2024, 1, 1, 0, i+1, tzinfo=timezone.utc),
                open=50000.0,
                high=51000.0,
                low=49000.0,
                close=50500.0,
                volume=100.0,
                is_closed=True
            )
            strategy.update_buffer(candle)

            # Buffer should never exceed buffer_size
            assert len(strategy.candle_buffer) <= 5

        # Final buffer size should be exactly buffer_size
        assert len(strategy.candle_buffer) == 5


# ============================================================================
# Test Class: Concrete Implementation Behavior
# ============================================================================

class TestConcreteImplementation:
    """Test concrete strategy implementation behavior."""

    @pytest.mark.asyncio
    async def test_analyze_returns_none_for_open_candle(self, default_config, open_candle):
        """Test that analyze returns None for incomplete candles."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        signal = await strategy.analyze(open_candle)

        assert signal is None

    @pytest.mark.asyncio
    async def test_analyze_returns_none_with_insufficient_buffer(self, default_config, sample_candle):
        """Test that analyze returns None when buffer is insufficient."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        # ConcreteTestStrategy requires 2+ candles
        signal = await strategy.analyze(sample_candle)

        assert signal is None
        assert len(strategy.candle_buffer) == 1

    @pytest.mark.asyncio
    async def test_analyze_generates_signal_when_conditions_met(self, default_config):
        """Test that analyze generates signal when strategy conditions are met."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        # Add first candle (buffer warm-up)
        candle1 = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            is_closed=True
        )
        await strategy.analyze(candle1)

        # Add second candle above threshold (close > 50000)
        candle2 = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc),
            open=50500.0,
            high=51000.0,
            low=50000.0,
            close=50800.0,  # Above 50000 threshold
            volume=100.0,
            is_closed=True
        )

        signal = await strategy.analyze(candle2)

        assert signal is not None
        assert signal.signal_type == SignalType.LONG_ENTRY
        assert signal.symbol == 'BTCUSDT'
        assert signal.entry_price == 50800.0
        assert signal.strategy_name == 'ConcreteTestStrategy'

    @pytest.mark.asyncio
    async def test_analyze_updates_buffer(self, default_config, sample_candle):
        """Test that analyze calls update_buffer internally."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        assert len(strategy.candle_buffer) == 0

        await strategy.analyze(sample_candle)

        assert len(strategy.candle_buffer) == 1
        assert strategy.candle_buffer[0] == sample_candle

    def test_calculate_take_profit_long_default(self, default_config):
        """Test TP calculation for LONG position with default config."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        entry_price = 50000.0
        tp = strategy.calculate_take_profit(entry_price, 'LONG')

        # Default tp_percent = 0.02 (2%)
        expected_tp = entry_price * 1.02
        assert tp == pytest.approx(expected_tp)
        assert tp > entry_price  # LONG TP must be above entry

    def test_calculate_take_profit_short_default(self, default_config):
        """Test TP calculation for SHORT position with default config."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        entry_price = 50000.0
        tp = strategy.calculate_take_profit(entry_price, 'SHORT')

        # Default tp_percent = 0.02 (2%)
        expected_tp = entry_price * 0.98
        assert tp == pytest.approx(expected_tp)
        assert tp < entry_price  # SHORT TP must be below entry

    def test_calculate_take_profit_long_custom(self, custom_config):
        """Test TP calculation for LONG with custom tp_percent."""
        strategy = ConcreteTestStrategy('BTCUSDT', custom_config)

        entry_price = 50000.0
        tp = strategy.calculate_take_profit(entry_price, 'LONG')

        # Custom tp_percent = 0.03 (3%)
        expected_tp = entry_price * 1.03
        assert tp == pytest.approx(expected_tp)

    def test_calculate_stop_loss_long_default(self, default_config):
        """Test SL calculation for LONG position with default config."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        entry_price = 50000.0
        sl = strategy.calculate_stop_loss(entry_price, 'LONG')

        # Default sl_percent = 0.01 (1%)
        expected_sl = entry_price * 0.99
        assert sl == pytest.approx(expected_sl)
        assert sl < entry_price  # LONG SL must be below entry

    def test_calculate_stop_loss_short_default(self, default_config):
        """Test SL calculation for SHORT position with default config."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        entry_price = 50000.0
        sl = strategy.calculate_stop_loss(entry_price, 'SHORT')

        # Default sl_percent = 0.01 (1%)
        expected_sl = entry_price * 1.01
        assert sl == pytest.approx(expected_sl)
        assert sl > entry_price  # SHORT SL must be above entry

    def test_calculate_stop_loss_long_custom(self, custom_config):
        """Test SL calculation for LONG with custom sl_percent."""
        strategy = ConcreteTestStrategy('BTCUSDT', custom_config)

        entry_price = 50000.0
        sl = strategy.calculate_stop_loss(entry_price, 'LONG')

        # Custom sl_percent = 0.015 (1.5%)
        expected_sl = entry_price * 0.985
        assert sl == pytest.approx(expected_sl)

    @pytest.mark.asyncio
    async def test_signal_validation_passes_for_valid_tp_sl(self, default_config):
        """Test that Signal validation passes for correctly calculated TP/SL."""
        strategy = ConcreteTestStrategy('BTCUSDT', default_config)

        # Warm up buffer
        candle1 = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            is_closed=True
        )
        await strategy.analyze(candle1)

        # Generate signal
        candle2 = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, 0, 2, tzinfo=timezone.utc),
            open=50500.0,
            high=51000.0,
            low=50000.0,
            close=50800.0,
            volume=100.0,
            is_closed=True
        )

        signal = await strategy.analyze(candle2)

        # Signal should be created successfully (no validation errors)
        assert signal is not None
        assert signal.entry_price == 50800.0
        assert signal.take_profit > signal.entry_price  # LONG validation
        assert signal.stop_loss < signal.entry_price    # LONG validation
