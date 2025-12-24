"""
Unit tests for AlwaysSignalStrategy.

Tests verify:
- Initialization with default and custom configurations
- Signal generation on every closed candle
- Alternating LONG/SHORT signal mode
- LONG-only and SHORT-only modes
- TP/SL calculation accuracy
- No signal on open candles
"""

from datetime import datetime, timezone

import pytest

from src.models.candle import Candle
from src.models.signal import SignalType
from src.strategies.always_signal import AlwaysSignalStrategy


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def default_config():
    """Default configuration dictionary."""
    return {}


@pytest.fixture
def alternate_config():
    """Configuration for alternating signals."""
    return {'signal_type': 'ALTERNATE'}


@pytest.fixture
def long_only_config():
    """Configuration for LONG signals only."""
    return {'signal_type': 'LONG'}


@pytest.fixture
def short_only_config():
    """Configuration for SHORT signals only."""
    return {'signal_type': 'SHORT'}


@pytest.fixture
def sample_closed_candle():
    """Create a sample closed candle."""
    return Candle(
        symbol='BTCUSDT',
        interval='1m',
        open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        open=50000.0,
        high=51000.0,
        low=49000.0,
        close=50000.0,
        volume=100.0,
        is_closed=True
    )


@pytest.fixture
def sample_open_candle():
    """Create a sample open candle."""
    return Candle(
        symbol='BTCUSDT',
        interval='1m',
        open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        open=50000.0,
        high=51000.0,
        low=49000.0,
        close=50000.0,
        volume=100.0,
        is_closed=False
    )


# ============================================================================
# Initialization Tests
# ============================================================================

class TestAlwaysSignalStrategyInitialization:
    """Test strategy initialization and configuration."""

    def test_default_initialization(self, default_config):
        """Test strategy initializes with default parameters."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)

        assert strategy.symbol == 'BTCUSDT'
        assert strategy.signal_mode == 'ALTERNATE'
        assert strategy.risk_reward_ratio == 2.0
        assert strategy.stop_loss_percent == 0.02

    def test_alternate_mode_initialization(self, alternate_config):
        """Test strategy initializes in ALTERNATE mode."""
        strategy = AlwaysSignalStrategy('ETHUSDT', alternate_config)

        assert strategy.signal_mode == 'ALTERNATE'
        assert strategy._last_signal_type is None

    def test_long_only_mode_initialization(self, long_only_config):
        """Test strategy initializes in LONG mode."""
        strategy = AlwaysSignalStrategy('BTCUSDT', long_only_config)

        assert strategy.signal_mode == 'LONG'

    def test_short_only_mode_initialization(self, short_only_config):
        """Test strategy initializes in SHORT mode."""
        strategy = AlwaysSignalStrategy('BTCUSDT', short_only_config)

        assert strategy.signal_mode == 'SHORT'

    def test_invalid_signal_type_raises_error(self):
        """Test invalid signal_type raises ValueError."""
        config = {'signal_type': 'INVALID'}

        with pytest.raises(ValueError) as exc_info:
            AlwaysSignalStrategy('BTCUSDT', config)

        assert 'LONG' in str(exc_info.value)
        assert 'SHORT' in str(exc_info.value)
        assert 'ALTERNATE' in str(exc_info.value)

    def test_custom_risk_parameters(self):
        """Test custom risk/reward parameters."""
        config = {
            'risk_reward_ratio': 3.0,
            'stop_loss_percent': 0.015
        }
        strategy = AlwaysSignalStrategy('BTCUSDT', config)

        assert strategy.risk_reward_ratio == 3.0
        assert strategy.stop_loss_percent == 0.015


# ============================================================================
# Signal Generation Tests
# ============================================================================

class TestSignalGeneration:
    """Test signal generation behavior."""

    @pytest.mark.asyncio
    async def test_no_signal_on_open_candle(self, default_config, sample_open_candle):
        """Test strategy returns None for open candles."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)

        signal = await strategy.analyze(sample_open_candle)

        assert signal is None

    @pytest.mark.asyncio
    async def test_signal_on_closed_candle(self, default_config, sample_closed_candle):
        """Test strategy generates signal for closed candle."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)

        signal = await strategy.analyze(sample_closed_candle)

        assert signal is not None
        assert signal.symbol == 'BTCUSDT'
        assert signal.entry_price == 50000.0
        assert signal.signal_type in [SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY]

    @pytest.mark.asyncio
    async def test_alternate_mode_switches_signals(self, alternate_config, sample_closed_candle):
        """Test ALTERNATE mode alternates between LONG and SHORT."""
        strategy = AlwaysSignalStrategy('BTCUSDT', alternate_config)

        # First signal (should be LONG since _last_signal_type is None)
        signal1 = await strategy.analyze(sample_closed_candle)
        assert signal1.signal_type == SignalType.LONG_ENTRY

        # Second signal (should be SHORT)
        signal2 = await strategy.analyze(sample_closed_candle)
        assert signal2.signal_type == SignalType.SHORT_ENTRY

        # Third signal (should be LONG again)
        signal3 = await strategy.analyze(sample_closed_candle)
        assert signal3.signal_type == SignalType.LONG_ENTRY

    @pytest.mark.asyncio
    async def test_long_only_mode(self, long_only_config, sample_closed_candle):
        """Test LONG mode always generates LONG signals."""
        strategy = AlwaysSignalStrategy('BTCUSDT', long_only_config)

        signal1 = await strategy.analyze(sample_closed_candle)
        signal2 = await strategy.analyze(sample_closed_candle)
        signal3 = await strategy.analyze(sample_closed_candle)

        assert signal1.signal_type == SignalType.LONG_ENTRY
        assert signal2.signal_type == SignalType.LONG_ENTRY
        assert signal3.signal_type == SignalType.LONG_ENTRY

    @pytest.mark.asyncio
    async def test_short_only_mode(self, short_only_config, sample_closed_candle):
        """Test SHORT mode always generates SHORT signals."""
        strategy = AlwaysSignalStrategy('BTCUSDT', short_only_config)

        signal1 = await strategy.analyze(sample_closed_candle)
        signal2 = await strategy.analyze(sample_closed_candle)
        signal3 = await strategy.analyze(sample_closed_candle)

        assert signal1.signal_type == SignalType.SHORT_ENTRY
        assert signal2.signal_type == SignalType.SHORT_ENTRY
        assert signal3.signal_type == SignalType.SHORT_ENTRY


# ============================================================================
# TP/SL Calculation Tests
# ============================================================================

class TestTPSLCalculation:
    """Test take profit and stop loss calculation accuracy."""

    def test_long_tp_calculation(self, default_config):
        """Test LONG take profit calculation."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)
        entry_price = 50000.0

        tp = strategy.calculate_take_profit(entry_price, 'LONG')

        # SL distance = 50000 * 0.02 = 1000
        # TP distance = 1000 * 2.0 = 2000
        # TP = 50000 + 2000 = 52000
        assert tp == 52000.0

    def test_short_tp_calculation(self, default_config):
        """Test SHORT take profit calculation."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)
        entry_price = 50000.0

        tp = strategy.calculate_take_profit(entry_price, 'SHORT')

        # TP = 50000 - 2000 = 48000
        assert tp == 48000.0

    def test_long_sl_calculation(self, default_config):
        """Test LONG stop loss calculation."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)
        entry_price = 50000.0

        sl = strategy.calculate_stop_loss(entry_price, 'LONG')

        # SL = 50000 - 1000 = 49000
        assert sl == 49000.0

    def test_short_sl_calculation(self, default_config):
        """Test SHORT stop loss calculation."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)
        entry_price = 50000.0

        sl = strategy.calculate_stop_loss(entry_price, 'SHORT')

        # SL = 50000 + 1000 = 51000
        assert sl == 51000.0

    def test_custom_risk_reward_tp_calculation(self):
        """Test TP calculation with custom risk/reward ratio."""
        config = {
            'risk_reward_ratio': 3.0,
            'stop_loss_percent': 0.01
        }
        strategy = AlwaysSignalStrategy('BTCUSDT', config)
        entry_price = 50000.0

        tp = strategy.calculate_take_profit(entry_price, 'LONG')

        # SL distance = 50000 * 0.01 = 500
        # TP distance = 500 * 3.0 = 1500
        # TP = 50000 + 1500 = 51500
        assert tp == 51500.0

    @pytest.mark.asyncio
    async def test_signal_tp_sl_validation(self, default_config, sample_closed_candle):
        """Test signal contains valid TP/SL prices."""
        strategy = AlwaysSignalStrategy('BTCUSDT', default_config)

        signal = await strategy.analyze(sample_closed_candle)

        # For LONG: TP > entry > SL
        # For SHORT: SL > entry > TP
        if signal.signal_type == SignalType.LONG_ENTRY:
            assert signal.take_profit > signal.entry_price > signal.stop_loss
        else:
            assert signal.stop_loss > signal.entry_price > signal.take_profit
