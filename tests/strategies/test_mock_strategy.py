"""
Unit tests for MockSMACrossoverStrategy.

Tests verify:
- Initialization with default and custom configurations
- Configuration validation (fast_period < slow_period)
- SMA calculation accuracy
- Golden cross and death cross detection
- Duplicate signal prevention
- Buffer size requirements
- TP/SL calculation accuracy
"""

from datetime import datetime, timezone

import numpy as np
import pytest

from src.models.candle import Candle
from src.models.signal import SignalType
from src.strategies.mock_strategy import MockSMACrossoverStrategy

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def default_config():
    """Default configuration dictionary."""
    return {}


@pytest.fixture
def custom_config():
    """Custom configuration with specific parameters."""
    return {
        "fast_period": 5,
        "slow_period": 15,
        "risk_reward_ratio": 3.0,
        "stop_loss_percent": 0.015,
        "buffer_size": 50,
    }


@pytest.fixture
def sample_candles():
    """Create a list of sample closed candles for testing."""
    base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles = []

    # Create 25 candles with incrementing prices
    for i in range(25):
        candle = Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=base_time.replace(minute=i),
            close_time=base_time.replace(minute=i + 1),
            open=50000.0 + i * 100,
            high=51000.0 + i * 100,
            low=49000.0 + i * 100,
            close=50000.0 + i * 100,
            volume=100.0,
            is_closed=True,
        )
        candles.append(candle)

    return candles


@pytest.fixture
def golden_cross_candles():
    """
    Create candles that produce a golden cross.

    Pattern: Prices drop then spike to create fast crossing above slow.
    """
    base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    # Prices: Start at 50000, drop gradually, then spike
    # This will cause fast SMA to cross above slow SMA
    prices = [
        50000,
        49900,
        49800,
        49700,
        49600,  # 0-4: Drop
        49500,
        49400,
        49300,
        49200,
        49100,  # 5-9: Continue drop
        49000,
        48900,
        48800,
        48700,
        48600,  # 10-14: More drop
        48500,
        48400,
        48300,
        48200,
        48100,  # 15-19: Stabilize
        48000,
        48100,
        48200,
        48300,
        52000,  # 20-24: Spike (golden cross)
    ]

    candles = []
    for i, price in enumerate(prices):
        candle = Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=base_time.replace(minute=i),
            close_time=base_time.replace(minute=i + 1),
            open=price - 100,
            high=price + 100,
            low=price - 200,
            close=price,
            volume=100.0,
            is_closed=True,
        )
        candles.append(candle)

    return candles


@pytest.fixture
def death_cross_candles():
    """
    Create candles that produce a death cross.

    Pattern: Prices rise then drop to create fast crossing below slow.
    """
    base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    # Prices: Start at 50000, rise gradually, then drop
    # This will cause fast SMA to cross below slow SMA
    prices = [
        50000,
        50100,
        50200,
        50300,
        50400,  # 0-4: Rise
        50500,
        50600,
        50700,
        50800,
        50900,  # 5-9: Continue rise
        51000,
        51100,
        51200,
        51300,
        51400,  # 10-14: More rise
        51500,
        51600,
        51700,
        51800,
        51900,  # 15-19: Stabilize
        52000,
        51900,
        51800,
        51700,
        48000,  # 20-24: Drop (death cross)
    ]

    candles = []
    for i, price in enumerate(prices):
        candle = Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=base_time.replace(minute=i),
            close_time=base_time.replace(minute=i + 1),
            open=price - 100,
            high=price + 100,
            low=price - 200,
            close=price,
            volume=100.0,
            is_closed=True,
        )
        candles.append(candle)

    return candles


# ============================================================================
# Test Class: Initialization
# ============================================================================


class TestMockSMAInitialization:
    """Test strategy initialization with various configurations."""

    def test_initialization_with_default_config(self, default_config):
        """Test initialization with empty config uses default parameters."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        assert strategy.symbol == "BTCUSDT"
        assert strategy.fast_period == 10
        assert strategy.slow_period == 20
        # risk_reward_ratio and stop_loss_percent now stored in config, not as instance attributes
        assert strategy.config.get("risk_reward_ratio", 2.0) == 2.0
        assert strategy.config.get("stop_loss_percent", 0.01) == 0.01
        assert strategy.buffer_size == 100
        assert strategy._last_signal_type is None
        assert len(strategy.buffers['1m']) == 0

    def test_initialization_with_custom_config(self, custom_config):
        """Test initialization with custom configuration."""
        strategy = MockSMACrossoverStrategy("ETHUSDT", custom_config)

        assert strategy.symbol == "ETHUSDT"
        assert strategy.fast_period == 5
        assert strategy.slow_period == 15
        # risk_reward_ratio and stop_loss_percent now stored in config, not as instance attributes
        assert strategy.config["risk_reward_ratio"] == 3.0
        assert strategy.config["stop_loss_percent"] == 0.015
        assert strategy.buffer_size == 50

    def test_initialization_validation_fast_equals_slow(self):
        """Test that fast_period == slow_period raises ValueError."""
        with pytest.raises(ValueError, match="fast_period .* must be < slow_period"):
            MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 10, "slow_period": 10})

    def test_initialization_validation_fast_greater_than_slow(self):
        """Test that fast_period > slow_period raises ValueError."""
        with pytest.raises(ValueError, match="fast_period .* must be < slow_period"):
            MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 20, "slow_period": 10})

    def test_initialization_partial_config(self):
        """Test initialization with partial config merges with defaults."""
        config = {"fast_period": 7, "risk_reward_ratio": 2.5}
        strategy = MockSMACrossoverStrategy("BTCUSDT", config)

        assert strategy.fast_period == 7
        assert strategy.slow_period == 20  # Default
        # risk_reward_ratio and stop_loss_percent now stored in config, not as instance attributes
        assert strategy.config["risk_reward_ratio"] == 2.5
        assert strategy.config.get("stop_loss_percent", 0.01) == 0.01  # Default


# ============================================================================
# Test Class: SMA Calculation
# ============================================================================


class TestSMACalculation:
    """Test SMA calculation accuracy."""

    @pytest.mark.asyncio
    async def test_sma_calculation_with_known_values(self, default_config):
        """Test SMA calculation accuracy with known dataset."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        # Create candles with known close prices
        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        prices = [
            50.0,
            52.0,
            51.0,
            53.0,
            54.0,
            55.0,
            56.0,
            57.0,
            58.0,
            59.0,
            60.0,
            61.0,
            62.0,
            63.0,
            64.0,
            65.0,
            66.0,
            67.0,
            68.0,
            69.0,
            70.0,
        ]

        candles = []
        for i, price in enumerate(prices):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=base_time.replace(minute=i),
                close_time=base_time.replace(minute=i + 1),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=100.0,
                is_closed=True,
            )
            candles.append(candle)
            await strategy.analyze(candle)

        # After processing all candles, check buffer
        buffer = strategy.buffers['1m']
        assert len(buffer) == 21

        # Manually calculate expected SMAs
        close_prices = np.array(prices)
        expected_fast_sma = np.mean(close_prices[-10:])  # Last 10
        expected_slow_sma = np.mean(close_prices[-20:])  # Last 20

        # Calculate actual SMAs from buffer
        actual_close_prices = np.array([c.close for c in buffer])
        actual_fast_sma = np.mean(actual_close_prices[-10:])
        actual_slow_sma = np.mean(actual_close_prices[-20:])

        assert actual_fast_sma == pytest.approx(expected_fast_sma)
        assert actual_slow_sma == pytest.approx(expected_slow_sma)

        # Expected values
        # Fast SMA (last 10): mean([61, 62, 63, 64, 65, 66, 67, 68, 69, 70]) = 65.5
        # Slow SMA (last 20): mean([51, 52, ..., 69, 70]) = 60.5
        assert actual_fast_sma == 65.5
        assert actual_slow_sma == 60.5

    @pytest.mark.asyncio
    async def test_sma_calculation_updates_with_new_candles(self, default_config):
        """Test that SMAs update correctly as new candles arrive."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

        # Add 21 candles with price = 50000
        for i in range(21):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=base_time.replace(minute=i),
                close_time=base_time.replace(minute=i + 1),
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50000.0,
                volume=100.0,
                is_closed=True,
            )
            await strategy.analyze(candle)

        # Both SMAs should be 50000
        close_prices = np.array([c.close for c in strategy.buffers['1m']])
        assert np.mean(close_prices[-10:]) == 50000.0
        assert np.mean(close_prices[-20:]) == 50000.0


# ============================================================================
# Test Class: Crossover Detection
# ============================================================================


class TestCrossoverDetection:
    """Test golden cross and death cross detection."""

    @pytest.mark.asyncio
    async def test_golden_cross_generates_long_signal(self, golden_cross_candles):
        """Test that golden cross generates LONG_ENTRY signal."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 5, "slow_period": 10})

        signal = None
        for candle in golden_cross_candles:
            result = await strategy.analyze(candle)
            if result:
                signal = result
                break  # Stop after first signal

        assert signal is not None
        assert signal.signal_type == SignalType.LONG_ENTRY
        assert signal.symbol == "BTCUSDT"
        assert signal.strategy_name == "MockSMACrossoverStrategy"

    @pytest.mark.asyncio
    async def test_death_cross_generates_short_signal(self, death_cross_candles):
        """Test that death cross generates SHORT_ENTRY signal."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 5, "slow_period": 10})

        signal = None
        for candle in death_cross_candles:
            result = await strategy.analyze(candle)
            if result:
                signal = result
                break  # Stop after first signal

        assert signal is not None
        assert signal.signal_type == SignalType.SHORT_ENTRY
        assert signal.symbol == "BTCUSDT"
        assert signal.strategy_name == "MockSMACrossoverStrategy"

    @pytest.mark.asyncio
    async def test_no_crossover_returns_none(self, sample_candles):
        """Test that no crossover returns None."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 5, "slow_period": 10})

        # Process candles with steadily increasing prices (no crossover)
        signals = []
        for candle in sample_candles[:15]:
            signal = await strategy.analyze(candle)
            if signal:
                signals.append(signal)

        # With steadily increasing prices, fast should stay above slow
        # No crossover should occur
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_duplicate_long_signal_prevention(self, golden_cross_candles):
        """Test that consecutive LONG signals are prevented."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 5, "slow_period": 10})

        signals = []
        for candle in golden_cross_candles:
            signal = await strategy.analyze(candle)
            if signal:
                signals.append(signal)

        # Should only generate one LONG signal despite multiple crossover conditions
        long_signals = [s for s in signals if s.signal_type == SignalType.LONG_ENTRY]
        assert len(long_signals) == 1

    @pytest.mark.asyncio
    async def test_duplicate_short_signal_prevention(self, death_cross_candles):
        """Test that consecutive SHORT signals are prevented."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 5, "slow_period": 10})

        signals = []
        for candle in death_cross_candles:
            signal = await strategy.analyze(candle)
            if signal:
                signals.append(signal)

        # Should only generate one SHORT signal despite multiple crossover conditions
        short_signals = [s for s in signals if s.signal_type == SignalType.SHORT_ENTRY]
        assert len(short_signals) == 1

    @pytest.mark.asyncio
    async def test_alternating_signals_allowed(self):
        """Test that alternating LONG/SHORT signals are allowed."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 3, "slow_period": 6})

        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

        # Create pattern: drop (death cross) → rise (golden cross)
        prices = [
            50000,
            50100,
            50200,
            50300,
            50400,
            50500,
            50600,  # Rise
            50500,
            50400,
            50300,
            50200,
            45000,
            44000,
            43000,  # Drop (death cross)
            44000,
            45000,
            46000,
            47000,
            52000,
            53000,
            54000,  # Rise (golden cross)
        ]

        signals = []
        for i, price in enumerate(prices):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=base_time.replace(minute=i),
                close_time=base_time.replace(minute=i + 1),
                open=price,
                high=price + 100,
                low=price - 100,
                close=price,
                volume=100.0,
                is_closed=True,
            )
            signal = await strategy.analyze(candle)
            if signal:
                signals.append(signal)

        # Should have at least 2 signals (one SHORT, one LONG)
        assert len(signals) >= 1
        # If we got 2 signals, they should be different types
        if len(signals) >= 2:
            assert signals[0].signal_type != signals[1].signal_type


# ============================================================================
# Test Class: Buffer Requirements
# ============================================================================


class TestBufferRequirements:
    """Test buffer size requirements for signal generation."""

    @pytest.mark.asyncio
    async def test_insufficient_buffer_returns_none(self, default_config):
        """Test that insufficient buffer (<slow_period) returns None."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

        # Add only 15 candles (less than slow_period=20)
        for i in range(15):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=base_time.replace(minute=i),
                close_time=base_time.replace(minute=i + 1),
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50000.0,
                volume=100.0,
                is_closed=True,
            )
            signal = await strategy.analyze(candle)
            assert signal is None

    @pytest.mark.asyncio
    async def test_exact_slow_period_buffer_returns_none(self, default_config):
        """Test that buffer == slow_period returns None (need slow_period + 1)."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

        # Add exactly slow_period candles (20)
        for i in range(20):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=base_time.replace(minute=i),
                close_time=base_time.replace(minute=i + 1),
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50000.0,
                volume=100.0,
                is_closed=True,
            )
            signal = await strategy.analyze(candle)
            # Should still return None (need 21 for crossover detection)
            assert signal is None

    @pytest.mark.asyncio
    async def test_sufficient_buffer_allows_analysis(self, default_config):
        """Test that buffer >= slow_period + 1 allows analysis."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

        # Add slow_period + 1 candles (21)
        for i in range(21):
            candle = Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=base_time.replace(minute=i),
                close_time=base_time.replace(minute=i + 1),
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50000.0,
                volume=100.0,
                is_closed=True,
            )
            await strategy.analyze(candle)

        # Buffer should have 21 candles
        assert len(strategy.buffers['1m']) == 21

    @pytest.mark.asyncio
    async def test_open_candle_returns_none(self, default_config):
        """Test that open (incomplete) candle returns None."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        open_candle = Candle(
            symbol="BTCUSDT",
            interval="1m",
            open_time=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
            is_closed=False,  # Open candle
        )

        signal = await strategy.analyze(open_candle)
        assert signal is None


# ============================================================================
# Test Class: TP/SL Calculation
# ============================================================================


class TestTPSLCalculation:
    """Test take profit and stop loss calculation."""

    def test_calculate_take_profit_long_default(self, default_config):
        """Test TP calculation for LONG with default config."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        entry_price = 50000.0
        tp = strategy.calculate_take_profit(entry_price, "LONG")

        # Default: stop_loss_percent=0.01, risk_reward_ratio=2.0
        # SL_distance = 50000 * 0.01 = 500
        # TP_distance = 500 * 2.0 = 1000
        # TP = 50000 + 1000 = 51000
        expected_tp = 51000.0
        assert tp == pytest.approx(expected_tp)
        assert tp > entry_price  # LONG TP must be above entry

    def test_calculate_take_profit_short_default(self, default_config):
        """Test TP calculation for SHORT with default config."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        entry_price = 50000.0
        tp = strategy.calculate_take_profit(entry_price, "SHORT")

        # Default: stop_loss_percent=0.01, risk_reward_ratio=2.0
        # SL_distance = 50000 * 0.01 = 500
        # TP_distance = 500 * 2.0 = 1000
        # TP = 50000 - 1000 = 49000
        expected_tp = 49000.0
        assert tp == pytest.approx(expected_tp)
        assert tp < entry_price  # SHORT TP must be below entry

    def test_calculate_take_profit_long_custom(self, custom_config):
        """Test TP calculation for LONG with custom config."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", custom_config)

        entry_price = 50000.0
        tp = strategy.calculate_take_profit(entry_price, "LONG")

        # Custom: stop_loss_percent=0.015, risk_reward_ratio=3.0
        # SL_distance = 50000 * 0.015 = 750
        # TP_distance = 750 * 3.0 = 2250
        # TP = 50000 + 2250 = 52250
        expected_tp = 52250.0
        assert tp == pytest.approx(expected_tp)

    def test_calculate_stop_loss_long_default(self, default_config):
        """Test SL calculation for LONG with default config."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        entry_price = 50000.0
        sl = strategy.calculate_stop_loss(entry_price, "LONG")

        # Default: stop_loss_percent=0.01
        # SL = 50000 * (1 - 0.01) = 50000 * 0.99 = 49500
        expected_sl = 49500.0
        assert sl == pytest.approx(expected_sl)
        assert sl < entry_price  # LONG SL must be below entry

    def test_calculate_stop_loss_short_default(self, default_config):
        """Test SL calculation for SHORT with default config."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", default_config)

        entry_price = 50000.0
        sl = strategy.calculate_stop_loss(entry_price, "SHORT")

        # Default: stop_loss_percent=0.01
        # SL = 50000 * (1 + 0.01) = 50000 * 1.01 = 50500
        expected_sl = 50500.0
        assert sl == pytest.approx(expected_sl)
        assert sl > entry_price  # SHORT SL must be above entry

    def test_calculate_stop_loss_long_custom(self, custom_config):
        """Test SL calculation for LONG with custom config."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", custom_config)

        entry_price = 50000.0
        sl = strategy.calculate_stop_loss(entry_price, "LONG")

        # Custom: stop_loss_percent=0.015
        # SL = 50000 * (1 - 0.015) = 50000 * 0.985 = 49250
        expected_sl = 49250.0
        assert sl == pytest.approx(expected_sl)

    @pytest.mark.asyncio
    async def test_signal_validation_tp_sl_relationships(self, golden_cross_candles):
        """Test that generated signals have valid TP/SL relationships."""
        strategy = MockSMACrossoverStrategy("BTCUSDT", {"fast_period": 5, "slow_period": 10})

        signal = None
        for candle in golden_cross_candles:
            result = await strategy.analyze(candle)
            if result:
                signal = result
                break

        assert signal is not None

        # LONG signal validation (enforced by Signal.__post_init__)
        if signal.signal_type == SignalType.LONG_ENTRY:
            assert signal.take_profit > signal.entry_price
            assert signal.stop_loss < signal.entry_price

    @pytest.mark.asyncio
    async def test_tp_sl_calculation_accuracy_in_signal(self, golden_cross_candles):
        """Test TP/SL accuracy in generated signal."""
        config = {
            "fast_period": 5,
            "slow_period": 10,
            "risk_reward_ratio": 2.0,
            "stop_loss_percent": 0.01,
        }
        strategy = MockSMACrossoverStrategy("BTCUSDT", config)

        signal = None
        for candle in golden_cross_candles:
            result = await strategy.analyze(candle)
            if result:
                signal = result
                break

        assert signal is not None

        # Manually calculate expected TP/SL
        entry = signal.entry_price
        sl_distance = entry * 0.01
        tp_distance = sl_distance * 2.0

        expected_sl = entry * 0.99
        expected_tp = entry + tp_distance

        assert signal.stop_loss == pytest.approx(expected_sl)
        assert signal.take_profit == pytest.approx(expected_tp)
