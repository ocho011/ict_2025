"""
Unit tests for MultiTimeframeStrategy base class.

Tests multi-buffer management, per-interval initialization,
and analyze() routing to analyze_mtf().
"""

from collections import deque
from datetime import datetime, timezone
from typing import Dict, Optional

import pytest

from src.models.candle import Candle
from src.models.signal import Signal
from src.strategies.multi_timeframe import MultiTimeframeStrategy


# Concrete implementation for testing
class ConcreteMTFStrategy(MultiTimeframeStrategy):
    """Test strategy that implements analyze_mtf()."""

    def __init__(self, symbol: str, intervals: list, config: dict):
        super().__init__(symbol, intervals, config)
        self.analyze_mtf_called = False
        self.last_candle = None
        self.last_buffers = None

    async def analyze_mtf(self, candle: Candle, buffers: Dict[str, deque]) -> Optional[Signal]:
        """Store call info and return None."""
        self.analyze_mtf_called = True
        self.last_candle = candle
        self.last_buffers = buffers
        return None


@pytest.fixture
def mtf_config():
    """Standard MTF configuration."""
    return {"buffer_size": 100, "tp_percent": 0.02, "sl_percent": 0.01}


@pytest.fixture
def intervals():
    """Standard interval list."""
    return ["5m", "1h", "4h"]


def create_candle(symbol: str, interval: str, index: int, is_closed: bool = True) -> Candle:
    """Helper to create test candles."""
    return Candle(
        symbol=symbol,
        interval=interval,
        open_time=datetime.now(timezone.utc),
        close_time=datetime.now(timezone.utc),
        open=100.0 + index,
        high=101.0 + index,
        low=99.0 + index,
        close=100.5 + index,
        volume=1000.0,
        is_closed=is_closed,
    )


class TestMultiTimeframeInitialization:
    """Test MultiTimeframeStrategy initialization."""

    def test_init_creates_buffers_for_all_intervals(self, mtf_config, intervals):
        """Verify __init__ creates a buffer for each interval."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        assert len(strategy.buffers) == 3
        assert "5m" in strategy.buffers
        assert "1h" in strategy.buffers
        assert "4h" in strategy.buffers

        # All buffers should be empty deques
        for interval in intervals:
            assert isinstance(strategy.buffers[interval], deque)
            assert len(strategy.buffers[interval]) == 0
            assert strategy.buffers[interval].maxlen == 100

    def test_init_sets_initialization_flags_to_false(self, mtf_config, intervals):
        """Verify all intervals start as uninitialized."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        assert len(strategy._initialized) == 3
        assert strategy._initialized["5m"] is False
        assert strategy._initialized["1h"] is False
        assert strategy._initialized["4h"] is False

    def test_is_ready_returns_false_before_initialization(self, mtf_config, intervals):
        """Verify is_ready() returns False when not all intervals initialized."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        assert strategy.is_ready() is False

        # Initialize only one interval
        # Issue #27: Unified signature - initialize_with_historical_data(candles, interval=...)
        candles_5m = [create_candle("BTCUSDT", "5m", i) for i in range(10)]
        strategy.initialize_with_historical_data(candles_5m, interval="5m")

        assert strategy.is_ready() is False  # Still not all initialized

    def test_is_ready_returns_true_after_all_intervals_initialized(self, mtf_config, intervals):
        """Verify is_ready() returns True after all intervals initialized."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Initialize all intervals
        # Issue #27: Unified signature - initialize_with_historical_data(candles, interval=...)
        for interval in intervals:
            candles = [create_candle("BTCUSDT", interval, i) for i in range(10)]
            strategy.initialize_with_historical_data(candles, interval=interval)

        assert strategy.is_ready() is True


class TestBufferManagement:
    """Test buffer initialization and updates."""

    def test_initialize_with_historical_data_single_interval(self, mtf_config, intervals):
        """Test initializing a single interval buffer."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        candles_1h = [create_candle("BTCUSDT", "1h", i) for i in range(50)]
        strategy.initialize_with_historical_data(candles_1h, interval="1h")

        assert len(strategy.buffers["1h"]) == 50
        assert strategy._initialized["1h"] is True
        assert strategy._initialized["5m"] is False  # Others still False
        assert strategy._initialized["4h"] is False

    def test_initialize_with_historical_data_all_intervals(self, mtf_config, intervals):
        """Test initializing all interval buffers."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Initialize each interval with different number of candles
        candles_5m = [create_candle("BTCUSDT", "5m", i) for i in range(30)]
        candles_1h = [create_candle("BTCUSDT", "1h", i) for i in range(50)]
        candles_4h = [create_candle("BTCUSDT", "4h", i) for i in range(70)]

        # Issue #27: Unified signature
        strategy.initialize_with_historical_data(candles_5m, interval="5m")
        strategy.initialize_with_historical_data(candles_1h, interval="1h")
        strategy.initialize_with_historical_data(candles_4h, interval="4h")

        assert len(strategy.buffers["5m"]) == 30
        assert len(strategy.buffers["1h"]) == 50
        assert len(strategy.buffers["4h"]) == 70

        assert all(strategy._initialized.values())
        assert strategy.is_ready() is True

    def test_initialize_trims_to_buffer_size(self, mtf_config, intervals):
        """Test initialization trims to buffer_size when more candles provided."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Provide 150 candles but buffer_size is 100
        candles_5m = [create_candle("BTCUSDT", "5m", i) for i in range(150)]
        strategy.initialize_with_historical_data(candles_5m, interval="5m")

        assert len(strategy.buffers["5m"]) == 100
        # Should keep most recent 100 candles
        assert strategy.buffers["5m"][0].close == 150.5  # index 50
        assert strategy.buffers["5m"][-1].close == 249.5  # index 149

    def test_update_buffer_appends_to_correct_interval(self, mtf_config, intervals):
        """Test update_buffer() adds candle to correct interval buffer."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Add candles to different intervals
        candle_5m = create_candle("BTCUSDT", "5m", 1)
        candle_1h = create_candle("BTCUSDT", "1h", 2)
        candle_4h = create_candle("BTCUSDT", "4h", 3)

        # Issue #27: update_buffer() now routes by candle.interval automatically
        strategy.update_buffer(candle_5m)
        strategy.update_buffer(candle_1h)
        strategy.update_buffer(candle_4h)

        assert len(strategy.buffers["5m"]) == 1
        assert len(strategy.buffers["1h"]) == 1
        assert len(strategy.buffers["4h"]) == 1

        assert strategy.buffers["5m"][0].close == 101.5
        assert strategy.buffers["1h"][0].close == 102.5
        assert strategy.buffers["4h"][0].close == 103.5

    def test_update_buffer_fifo_behavior_when_full(self, mtf_config, intervals):
        """Test FIFO eviction when buffer reaches maxlen."""
        config = {"buffer_size": 10}
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, config)

        # Add 15 candles to 5m buffer (maxlen=10)
        # Issue #27: update_buffer() now routes by candle.interval automatically
        for i in range(15):
            candle = create_candle("BTCUSDT", "5m", i)
            strategy.update_buffer(candle)

        assert len(strategy.buffers["5m"]) == 10
        # Oldest 5 candles should be evicted
        assert strategy.buffers["5m"][0].close == 105.5  # index 5
        assert strategy.buffers["5m"][-1].close == 114.5  # index 14

    def test_get_buffer_returns_correct_interval_candles(self, mtf_config, intervals):
        """Test get_buffer() retrieves correct interval buffer."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Add candles
        # Issue #27: update_buffer() now routes by candle.interval automatically
        for i in range(5):
            strategy.update_buffer(create_candle("BTCUSDT", "1h", i))

        buffer_1h = strategy.get_buffer("1h")
        assert buffer_1h is not None
        assert len(buffer_1h) == 5
        assert buffer_1h is strategy.buffers["1h"]

        # Non-existent interval
        buffer_15m = strategy.get_buffer("15m")
        assert buffer_15m is None


class TestAnalyzeRouting:
    """Test analyze() wrapper and routing to analyze_mtf()."""

    @pytest.mark.asyncio
    async def test_analyze_returns_none_for_open_candle(self, mtf_config, intervals):
        """Verify analyze() returns None for open candles."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Initialize all intervals
        # Issue #27: Unified signature - initialize_with_historical_data(candles, interval=...)
        for interval in intervals:
            candles = [create_candle("BTCUSDT", interval, i) for i in range(10)]
            strategy.initialize_with_historical_data(candles, interval=interval)

        # Open candle should return None
        open_candle = create_candle("BTCUSDT", "5m", 20, is_closed=False)
        result = await strategy.analyze(open_candle)

        assert result is None
        assert strategy.analyze_mtf_called is False

    @pytest.mark.asyncio
    async def test_analyze_updates_correct_interval_buffer(self, mtf_config, intervals):
        """Verify analyze() updates the correct interval buffer."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Initialize all intervals
        # Issue #27: Unified signature - initialize_with_historical_data(candles, interval=...)
        for interval in intervals:
            candles = [create_candle("BTCUSDT", interval, i) for i in range(10)]
            strategy.initialize_with_historical_data(candles, interval=interval)

        # Analyze 5m candle
        candle_5m = create_candle("BTCUSDT", "5m", 100)
        await strategy.analyze(candle_5m)

        assert len(strategy.buffers["5m"]) == 11  # 10 + 1
        assert strategy.buffers["5m"][-1].close == 200.5  # index 100

        # Other buffers unchanged
        assert len(strategy.buffers["1h"]) == 10
        assert len(strategy.buffers["4h"]) == 10

    @pytest.mark.asyncio
    async def test_analyze_waits_until_all_intervals_ready(self, mtf_config, intervals):
        """Verify analyze() waits for all intervals to be initialized."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Only initialize 5m
        candles_5m = [create_candle("BTCUSDT", "5m", i) for i in range(10)]
        strategy.initialize_with_historical_data(candles_5m, interval="5m")

        # Try to analyze - should return None (not ready)
        candle = create_candle("BTCUSDT", "5m", 20)
        result = await strategy.analyze(candle)

        assert result is None
        assert strategy.analyze_mtf_called is False

        # Initialize remaining intervals
        candles_1h = [create_candle("BTCUSDT", "1h", i) for i in range(10)]
        candles_4h = [create_candle("BTCUSDT", "4h", i) for i in range(10)]
        strategy.initialize_with_historical_data(candles_1h, interval="1h")
        strategy.initialize_with_historical_data(candles_4h, interval="4h")

        # Now analyze should call analyze_mtf
        candle = create_candle("BTCUSDT", "5m", 30)
        await strategy.analyze(candle)

        assert strategy.analyze_mtf_called is True

    @pytest.mark.asyncio
    async def test_analyze_calls_analyze_mtf_when_ready(self, mtf_config, intervals):
        """Verify analyze() calls analyze_mtf() with correct parameters."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        # Initialize all intervals
        # Issue #27: Unified signature - initialize_with_historical_data(candles, interval=...)
        for interval in intervals:
            candles = [create_candle("BTCUSDT", interval, i) for i in range(10)]
            strategy.initialize_with_historical_data(candles, interval=interval)

        # Analyze
        test_candle = create_candle("BTCUSDT", "5m", 99)
        await strategy.analyze(test_candle)

        # Verify analyze_mtf was called
        assert strategy.analyze_mtf_called is True
        assert strategy.last_candle is test_candle
        assert strategy.last_buffers is strategy.buffers

        # Verify all buffers passed
        assert "5m" in strategy.last_buffers
        assert "1h" in strategy.last_buffers
        assert "4h" in strategy.last_buffers


class TestTPSLCalculation:
    """Test default TP/SL calculations."""

    def test_calculate_take_profit_long_default(self, mtf_config, intervals):
        """Test default TP calculation for LONG."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        tp = strategy.calculate_take_profit(50000, "LONG")
        assert tp == 51000  # 50000 * 1.02

    def test_calculate_take_profit_short_default(self, mtf_config, intervals):
        """Test default TP calculation for SHORT."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        tp = strategy.calculate_take_profit(50000, "SHORT")
        assert tp == 49000  # 50000 * 0.98

    def test_calculate_stop_loss_long_default(self, mtf_config, intervals):
        """Test default SL calculation for LONG."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        sl = strategy.calculate_stop_loss(50000, "LONG")
        assert sl == 49500  # 50000 * 0.99

    def test_calculate_stop_loss_short_default(self, mtf_config, intervals):
        """Test default SL calculation for SHORT."""
        strategy = ConcreteMTFStrategy("BTCUSDT", intervals, mtf_config)

        sl = strategy.calculate_stop_loss(50000, "SHORT")
        assert sl == 50500  # 50000 * 1.01
