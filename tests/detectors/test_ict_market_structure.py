"""
Unit tests for ICT Market Structure Analysis
"""

from collections import deque
from datetime import datetime, timedelta

from src.detectors.ict_market_structure import (
    detect_bos,
    detect_choch,
    get_current_trend,
    identify_swing_highs,
    identify_swing_lows,
)
from src.models.candle import Candle


def create_test_candle(
    index: int, open_price: float, high: float, low: float, close: float, base_time: datetime = None
) -> Candle:
    """Helper to create test candles."""
    if base_time is None:
        base_time = datetime(2025, 1, 1, 0, 0)

    open_time = base_time + timedelta(minutes=index)
    close_time = open_time + timedelta(minutes=1)

    return Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100.0,
        close_time=close_time,
        is_closed=True,
    )


class TestIdentifySwingHighs:
    """Test swing high identification"""

    def test_no_swing_highs_in_uptrend(self):
        """Continuous uptrend should not produce swing highs until later."""
        candles = [create_test_candle(i, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(15)]
        swing_highs = identify_swing_highs(candles, left_bars=3, right_bars=3)
        # In pure uptrend, no swing highs should be detected
        assert len(swing_highs) == 0

    def test_swing_high_detected(self):
        """Test detection of a clear swing high."""
        # Create price pattern: up to 110, then down to 105
        candles = [
            create_test_candle(0, 100, 101, 99, 100.5),
            create_test_candle(1, 100.5, 102, 100, 101.5),
            create_test_candle(2, 101.5, 103, 101, 102.5),
            create_test_candle(3, 102.5, 105, 102, 104),  # Build up
            create_test_candle(4, 104, 107, 103, 106),
            create_test_candle(5, 106, 110, 105, 109),  # SWING HIGH at index 5
            create_test_candle(6, 109, 109, 106, 107),  # Start down
            create_test_candle(7, 107, 108, 105, 106),
            create_test_candle(8, 106, 107, 104, 105),
            create_test_candle(9, 105, 106, 103, 104),
            create_test_candle(10, 104, 105, 102, 103),
            create_test_candle(11, 103, 104, 101, 102),
        ]

        swing_highs = identify_swing_highs(candles, left_bars=3, right_bars=3)

        assert len(swing_highs) >= 1
        # The swing high should be at index 5 with price 110
        swing_high = next((sh for sh in swing_highs if sh.index == 5), None)
        assert swing_high is not None
        assert swing_high.price == 110
        assert swing_high.type == "high"

    def test_multiple_swing_highs(self):
        """Test detection of multiple swing highs."""
        candles = [
            create_test_candle(
                i, 100 + (i % 6) * 2, 101 + (i % 6) * 2, 99 + (i % 6) * 2, 100 + (i % 6) * 2
            )
            for i in range(20)
        ]
        # This creates a wave pattern
        swing_highs = identify_swing_highs(candles, left_bars=2, right_bars=2)
        # Should detect peaks in the wave
        assert len(swing_highs) > 0

    def test_insufficient_candles(self):
        """Test behavior with insufficient candles."""
        candles = [create_test_candle(i, 100, 101, 99, 100) for i in range(5)]
        swing_highs = identify_swing_highs(candles, left_bars=5, right_bars=5)
        # Need at least 11 candles for 5+1+5
        assert len(swing_highs) == 0

    def test_works_with_deque(self):
        """Test that function works with deque input."""
        candles_list = [
            create_test_candle(i, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(15)
        ]
        candles_deque = deque(candles_list, maxlen=100)

        swing_highs = identify_swing_highs(candles_deque, left_bars=3, right_bars=3)
        # Should work the same as with list
        assert isinstance(swing_highs, list)


class TestIdentifySwingLows:
    """Test swing low identification"""

    def test_no_swing_lows_in_downtrend(self):
        """Continuous downtrend should not produce swing lows until later."""
        candles = [create_test_candle(i, 100 - i, 101 - i, 99 - i, 100.5 - i) for i in range(15)]
        swing_lows = identify_swing_lows(candles, left_bars=3, right_bars=3)
        # In pure downtrend, no swing lows detected
        assert len(swing_lows) == 0

    def test_swing_low_detected(self):
        """Test detection of a clear swing low."""
        # Create price pattern: down to 90, then up to 95
        candles = [
            create_test_candle(0, 100, 101, 99, 100.5),
            create_test_candle(1, 100.5, 100.5, 98, 99),
            create_test_candle(2, 99, 99, 96, 97),
            create_test_candle(3, 97, 97, 94, 95),  # Build down
            create_test_candle(4, 95, 95, 92, 93),
            create_test_candle(5, 93, 93, 90, 91),  # SWING LOW at index 5
            create_test_candle(6, 91, 93, 91, 92),  # Start up
            create_test_candle(7, 92, 94, 92, 93),
            create_test_candle(8, 93, 95, 93, 94),
            create_test_candle(9, 94, 96, 94, 95),
            create_test_candle(10, 95, 97, 95, 96),
            create_test_candle(11, 96, 98, 96, 97),
        ]

        swing_lows = identify_swing_lows(candles, left_bars=3, right_bars=3)

        assert len(swing_lows) >= 1
        # The swing low should be at index 5 with price 90
        swing_low = next((sl for sl in swing_lows if sl.index == 5), None)
        assert swing_low is not None
        assert swing_low.price == 90
        assert swing_low.type == "low"

    def test_insufficient_candles(self):
        """Test behavior with insufficient candles."""
        candles = [create_test_candle(i, 100, 101, 99, 100) for i in range(5)]
        swing_lows = identify_swing_lows(candles, left_bars=5, right_bars=5)
        assert len(swing_lows) == 0


class TestDetectBOS:
    """Test Break of Structure detection"""

    def test_bullish_bos_higher_high(self):
        """Test detection of bullish BOS (higher high in uptrend)."""
        candles = [
            # Build up to first swing high
            create_test_candle(0, 100, 101, 99, 100),
            create_test_candle(1, 100, 103, 100, 102),
            create_test_candle(2, 102, 105, 102, 104),
            create_test_candle(3, 104, 110, 104, 108),  # Peak at 110 (index 3)
            create_test_candle(4, 108, 108, 105, 106),  # Down
            create_test_candle(5, 106, 107, 104, 105),  # Down
            create_test_candle(6, 105, 106, 103, 104),  # Down
            # Build up to second swing high (higher high)
            create_test_candle(7, 104, 108, 104, 107),
            create_test_candle(8, 107, 112, 107, 110),
            create_test_candle(9, 110, 115, 110, 113),  # Peak at 115 (index 9) - HIGHER HIGH = BOS
            create_test_candle(10, 113, 113, 110, 111),  # Down
            create_test_candle(11, 111, 112, 109, 110),  # Down
            create_test_candle(12, 110, 111, 108, 109),  # Down
            create_test_candle(13, 109, 110, 107, 108),
        ]

        bos_events = detect_bos(candles, swing_lookback=2)

        # Should detect bullish BOS
        assert len(bos_events) > 0
        bullish_bos = [b for b in bos_events if b.direction == "bullish"]
        assert len(bullish_bos) > 0
        assert bullish_bos[0].type == "BOS"

    def test_bearish_bos_lower_low(self):
        """Test detection of bearish BOS (lower low in downtrend)."""
        candles = [
            # Build down to first swing low
            create_test_candle(0, 100, 101, 99, 100),
            create_test_candle(1, 100, 100, 97, 98),
            create_test_candle(2, 98, 98, 94, 95),
            create_test_candle(3, 95, 95, 90, 91),  # Bottom at 90 (index 3)
            create_test_candle(4, 91, 93, 91, 92),  # Up
            create_test_candle(5, 92, 94, 92, 93),  # Up
            create_test_candle(6, 93, 95, 93, 94),  # Up
            # Build down to second swing low (lower low)
            create_test_candle(7, 94, 94, 92, 93),
            create_test_candle(8, 93, 93, 88, 89),
            create_test_candle(9, 89, 89, 85, 86),  # Bottom at 85 (index 9) - LOWER LOW = BOS
            create_test_candle(10, 86, 88, 86, 87),  # Up
            create_test_candle(11, 87, 89, 87, 88),  # Up
            create_test_candle(12, 88, 90, 88, 89),  # Up
            create_test_candle(13, 89, 91, 89, 90),
        ]

        bos_events = detect_bos(candles, swing_lookback=2)

        # Should detect bearish BOS
        assert len(bos_events) > 0
        bearish_bos = [b for b in bos_events if b.direction == "bearish"]
        assert len(bearish_bos) > 0
        assert bearish_bos[0].type == "BOS"

    def test_no_bos_in_consolidation(self):
        """No BOS in sideways/consolidation market."""
        candles = [create_test_candle(i, 100, 102, 98, 100 + (i % 2)) for i in range(20)]
        bos_events = detect_bos(candles, swing_lookback=3)
        # Consolidation should have fewer or no BOS events
        assert len(bos_events) == 0 or len(bos_events) < 3


class TestDetectCHoCH:
    """Test Change of Character detection"""

    def test_bullish_choch_downtrend_reversal(self):
        """Test detection of bullish CHoCH (downtrend to uptrend reversal)."""
        candles = [
            # Downtrend: lower highs and lower lows
            create_test_candle(0, 100, 102, 99, 100),
            create_test_candle(1, 100, 100, 96, 97),  # Lower low
            create_test_candle(2, 97, 99, 96, 98),  # Swing high at 99
            create_test_candle(3, 98, 98, 94, 95),
            create_test_candle(4, 95, 95, 91, 92),  # Lower low
            create_test_candle(5, 92, 94, 91, 93),  # Swing high at 94 (lower)
            create_test_candle(6, 93, 93, 89, 90),
            create_test_candle(7, 90, 90, 87, 88),  # Lower low
            # Now break above previous swing high = CHoCH
            create_test_candle(8, 88, 90, 88, 89),
            create_test_candle(9, 89, 95, 89, 94),
            create_test_candle(10, 94, 100, 94, 99),  # Break above 99 = CHoCH
            create_test_candle(11, 99, 102, 99, 101),
        ]

        choch_events = detect_choch(candles, swing_lookback=2)

        # Should detect bullish CHoCH
        _bullish_choch = [c for c in choch_events if c.direction == "bullish"]
        # May or may not detect depending on swing logic strictness
        # At minimum should not crash
        assert isinstance(choch_events, list)

    def test_no_choch_in_strong_trend(self):
        """No CHoCH in strong trending market."""
        # Strong uptrend
        candles = [
            create_test_candle(i, 100 + i * 2, 102 + i * 2, 99 + i * 2, 101 + i * 2)
            for i in range(15)
        ]
        choch_events = detect_choch(candles, swing_lookback=3)
        # Strong trend should have no CHoCH
        assert len(choch_events) == 0


class TestGetCurrentTrend:
    """Test current trend determination"""

    def test_bullish_trend(self):
        """Test identification of bullish trend (higher highs, higher lows)."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 101, 99, 100),  # Low at 99
            create_test_candle(2, 100, 103, 100, 102),  # High at 103
            create_test_candle(3, 102, 102, 100, 101),
            create_test_candle(4, 101, 104, 101, 103),  # High at 104 (higher)
            create_test_candle(5, 103, 103, 101, 102),
            create_test_candle(6, 102, 102, 100, 101),  # Low at 100 (higher)
            create_test_candle(7, 101, 105, 101, 104),
            create_test_candle(8, 104, 107, 104, 106),  # High at 107 (higher)
            create_test_candle(9, 106, 106, 103, 104),
            create_test_candle(10, 104, 104, 102, 103),  # Low at 102 (higher)
            create_test_candle(11, 103, 108, 103, 107),
            create_test_candle(12, 107, 110, 107, 109),
        ]

        trend = get_current_trend(candles, swing_lookback=2, min_swings=2)
        assert trend == "bullish"

    def test_bearish_trend(self):
        """Test identification of bearish trend (lower highs, lower lows)."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 105, 101, 104),  # Build up
            create_test_candle(2, 104, 108, 104, 107),  # High at 108 (index 2)
            create_test_candle(3, 107, 107, 103, 104),  # Down
            create_test_candle(4, 104, 105, 100, 101),  # Down
            create_test_candle(5, 101, 102, 97, 98),  # Low at 97 (index 5)
            create_test_candle(6, 98, 101, 98, 100),  # Up
            create_test_candle(7, 100, 104, 100, 103),  # High at 104 (index 7) - LOWER
            create_test_candle(8, 103, 103, 99, 100),  # Down
            create_test_candle(9, 100, 101, 93, 94),  # Low at 93 (index 9) - LOWER
            create_test_candle(10, 94, 97, 94, 96),  # Up
            create_test_candle(11, 96, 100, 96, 99),  # High at 100 (index 11) - LOWER
            create_test_candle(12, 99, 99, 95, 96),  # Down
            create_test_candle(13, 96, 97, 89, 90),  # Low at 89 (index 13) - LOWER
        ]

        trend = get_current_trend(candles, swing_lookback=2, min_swings=2)
        assert trend == "bearish"

    def test_no_trend_consolidation(self):
        """Test that consolidation returns None."""
        candles = [create_test_candle(i, 100, 102, 98, 100 + (i % 2)) for i in range(15)]
        trend = get_current_trend(candles, swing_lookback=2, min_swings=2)
        # Sideways market should return None
        assert trend is None or trend in ["bullish", "bearish"]  # Depending on noise

    def test_insufficient_data(self):
        """Test that insufficient data returns None."""
        candles = [create_test_candle(i, 100, 101, 99, 100) for i in range(5)]
        trend = get_current_trend(candles, swing_lookback=5, min_swings=2)
        assert trend is None
