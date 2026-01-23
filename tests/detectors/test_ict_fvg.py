"""
Unit tests for ICT Fair Value Gap (FVG) Detection
"""

from collections import deque
from datetime import datetime, timedelta

from src.detectors.ict_fvg import (
    detect_all_fvg,
    detect_bearish_fvg,
    detect_bullish_fvg,
    find_nearest_fvg,
    get_entry_zone,
    get_fvg_levels,
    is_fvg_filled,
    update_fvg_status,
)
from src.models.candle import Candle
from src.models.indicators import FairValueGap, IndicatorStatus


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


class TestDetectBullishFVG:
    """Test bullish FVG detection"""

    def test_bullish_fvg_detected(self):
        """Test detection of a clear bullish FVG."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),  # Candle 0: high=102
            create_test_candle(1, 101, 110, 101, 109),  # Candle 1: gap creator
            create_test_candle(2, 109, 112, 108, 111),  # Candle 2: low=108 > 102 = FVG
            create_test_candle(3, 111, 113, 110, 112),
        ]

        fvgs = detect_bullish_fvg(candles, min_gap_percent=0.001)

        assert len(fvgs) > 0
        fvg = fvgs[0]
        assert fvg.direction == "bullish"
        assert fvg.gap_low == 102  # candle[0].high
        assert fvg.gap_high == 108  # candle[2].low
        assert fvg.index == 1
        assert not fvg.filled

    def test_multiple_bullish_fvgs(self):
        """Test detection of multiple bullish FVGs."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),  # FVG 1
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),
            create_test_candle(3, 111, 113, 110, 112),
            create_test_candle(4, 112, 115, 111, 114),  # FVG 2
            create_test_candle(5, 114, 123, 114, 122),
            create_test_candle(6, 122, 125, 120, 124),
        ]

        fvgs = detect_bullish_fvg(candles, min_gap_percent=0.001)

        # Should detect at least 2 FVGs
        assert len(fvgs) >= 2
        assert all(fvg.direction == "bullish" for fvg in fvgs)

    def test_no_fvg_insufficient_gap(self):
        """Test that tiny gaps below threshold are ignored."""
        candles = [
            create_test_candle(0, 100.00, 100.02, 99.98, 100.01),
            create_test_candle(1, 100.01, 100.03, 100.01, 100.02),
            create_test_candle(2, 100.02, 100.05, 100.01, 100.04),  # Tiny gap
        ]

        fvgs = detect_bullish_fvg(candles, min_gap_percent=0.001)

        # Gap too small to be significant
        assert len(fvgs) == 0

    def test_insufficient_candles(self):
        """Test behavior with insufficient candles."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 110, 101, 109),
        ]

        fvgs = detect_bullish_fvg(candles)

        # Need at least 3 candles
        assert len(fvgs) == 0

    def test_works_with_deque(self):
        """Test that function works with deque input."""
        candles_list = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),
        ]
        candles_deque = deque(candles_list, maxlen=100)

        fvgs = detect_bullish_fvg(candles_deque)

        assert isinstance(fvgs, list)
        assert len(fvgs) > 0


class TestDetectBearishFVG:
    """Test bearish FVG detection"""

    def test_bearish_fvg_detected(self):
        """Test detection of a clear bearish FVG."""
        candles = [
            create_test_candle(0, 100, 102, 98, 99),  # Candle 0: low=98
            create_test_candle(1, 99, 99, 89, 90),  # Candle 1: gap creator
            create_test_candle(2, 90, 92, 88, 89),  # Candle 2: high=92 < 98 = FVG
            create_test_candle(3, 89, 90, 87, 88),
        ]

        fvgs = detect_bearish_fvg(candles, min_gap_percent=0.001)

        assert len(fvgs) > 0
        fvg = fvgs[0]
        assert fvg.direction == "bearish"
        assert fvg.gap_high == 98  # candle[0].low
        assert fvg.gap_low == 92  # candle[2].high
        assert fvg.index == 1
        assert not fvg.filled

    def test_multiple_bearish_fvgs(self):
        """Test detection of multiple bearish FVGs."""
        candles = [
            create_test_candle(0, 100, 102, 98, 99),  # FVG 1
            create_test_candle(1, 99, 99, 89, 90),
            create_test_candle(2, 90, 92, 88, 89),
            create_test_candle(3, 89, 90, 87, 88),
            create_test_candle(4, 88, 90, 86, 87),  # FVG 2
            create_test_candle(5, 87, 87, 77, 78),
            create_test_candle(6, 78, 80, 76, 77),
        ]

        fvgs = detect_bearish_fvg(candles, min_gap_percent=0.001)

        # Should detect at least 2 FVGs
        assert len(fvgs) >= 2
        assert all(fvg.direction == "bearish" for fvg in fvgs)


class TestIsFVGFilled:
    """Test FVG filled status checking"""

    def test_fvg_not_filled(self):
        """Test FVG that hasn't been filled yet."""
        fvg = FairValueGap(
            id="fvg_1",
            interval="1m",
            direction="bullish",
            gap_high=110,
            gap_low=100,
            timestamp=datetime(2025, 1, 1),
            candle_index=0,
            gap_size=10.0,
        )

        # Price outside gap
        assert not is_fvg_filled(fvg, 95)
        assert not is_fvg_filled(fvg, 115)

    def test_fvg_filled(self):
        """Test FVG that has been filled."""
        fvg = FairValueGap(
            id="fvg_2",
            interval="1m",
            direction="bullish",
            gap_high=110,
            gap_low=100,
            timestamp=datetime(2025, 1, 1),
            candle_index=0,
            gap_size=10.0,
        )

        # Price within gap
        assert is_fvg_filled(fvg, 105)
        assert is_fvg_filled(fvg, 100)  # At boundary
        assert is_fvg_filled(fvg, 110)  # At boundary

    def test_bearish_fvg_filled(self):
        """Test bearish FVG filled check."""
        fvg = FairValueGap(
            id="fvg_3",
            interval="1m",
            direction="bearish",
            gap_high=100,
            gap_low=90,
            timestamp=datetime(2025, 1, 1),
            candle_index=0,
            gap_size=10.0,
        )

        assert not is_fvg_filled(fvg, 85)
        assert not is_fvg_filled(fvg, 105)
        assert is_fvg_filled(fvg, 95)


class TestGetFVGLevels:
    """Test FVG level extraction"""

    def test_get_fvg_levels(self):
        """Test extraction of key FVG levels."""
        fvg = FairValueGap(
            id="fvg_4",
            interval="1m",
            direction="bullish",
            gap_high=110,
            gap_low=100,
            timestamp=datetime(2025, 1, 1),
            candle_index=0,
            gap_size=10.0,
        )

        low, mid, high = get_fvg_levels(fvg)

        assert low == 100
        assert mid == 105  # Midpoint
        assert high == 110


class TestUpdateFVGStatus:
    """Test FVG status updates"""

    def test_update_unfilled_fvg(self):
        """Test updating unfilled FVG with subsequent candles."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),  # FVG formed: 102-108
            create_test_candle(3, 111, 113, 110, 112),  # Not filled
            create_test_candle(4, 112, 114, 111, 113),  # Not filled
        ]

        fvgs = detect_bullish_fvg(candles, min_gap_percent=0.001)
        assert len(fvgs) > 0

        # FVG should not be filled yet
        fvgs = update_fvg_status(fvgs, candles)
        assert not fvgs[0].filled

    def test_update_filled_fvg(self):
        """Test updating FVG that gets filled."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),  # FVG: 102-108
            create_test_candle(3, 111, 113, 110, 112),
            create_test_candle(4, 112, 113, 105, 106),  # Fills FVG (touches 105)
        ]

        fvgs = detect_bullish_fvg(candles, min_gap_percent=0.001)
        assert len(fvgs) > 0

        # FVG should be filled
        fvgs = update_fvg_status(fvgs, candles)
        assert fvgs[0].filled


class TestFindNearestFVG:
    """Test finding nearest FVG"""

    def test_find_nearest_bullish_fvg(self):
        """Test finding nearest bullish FVG to current price."""
        fvgs = [
            FairValueGap("id1", "1m", "bullish", 110, 100, datetime(2025, 1, 1), 0, 10.0),
            FairValueGap("id2", "1m", "bullish", 130, 120, datetime(2025, 1, 1), 1, 10.0),
            FairValueGap("id3", "1m", "bullish", 90, 80, datetime(2025, 1, 1), 2, 10.0),
        ]

        # Current price 115 - nearest is 100-110 FVG
        nearest = find_nearest_fvg(fvgs, 115, "bullish")
        assert nearest is not None
        assert nearest.index == 0
        assert nearest.gap_low == 100

    def test_find_nearest_only_unfilled(self):
        """Test finding only unfilled FVGs."""
        fvgs = [
            FairValueGap("id1", "1m", "bullish", 110, 100, datetime(2025, 1, 1), 0, 10.0, IndicatorStatus.FILLED),  # Filled
            FairValueGap("id2", "1m", "bullish", 130, 120, datetime(2025, 1, 1), 1, 10.0),  # Unfilled
        ]

        # Should only return unfilled FVG
        nearest = find_nearest_fvg(fvgs, 115, "bullish", only_unfilled=True)
        assert nearest is not None
        assert nearest.index == 1
        assert not nearest.filled


class TestGetEntryZone:
    """Test entry zone calculation"""

    def test_bullish_entry_zone(self):
        """Test entry zone for bullish FVG (lower portion)."""
        fvg = FairValueGap("id1", "1m", "bullish", 110, 100, datetime(2025, 1, 1), 0, 10.0)

        low, high = get_entry_zone(fvg, zone_percent=0.5)

        # Entry zone is lower 50% of gap
        assert low == 100
        assert high == 105

    def test_bearish_entry_zone(self):
        """Test entry zone for bearish FVG (upper portion)."""
        fvg = FairValueGap("id1", "1m", "bearish", 100, 90, datetime(2025, 1, 1), 0, 10.0)

        low, high = get_entry_zone(fvg, zone_percent=0.5)

        # Entry zone is upper 50% of gap
        assert low == 95
        assert high == 100


class TestDetectAllFVG:
    """Test combined FVG detection"""

    def test_detect_all_fvg(self):
        """Test detecting both bullish and bearish FVGs."""
        candles = [
            # Bullish FVG
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),
            create_test_candle(3, 111, 113, 110, 112),
            # Bearish FVG
            create_test_candle(4, 112, 114, 110, 111),
            create_test_candle(5, 111, 111, 101, 102),
            create_test_candle(6, 102, 104, 100, 101),
        ]

        bullish_fvgs, bearish_fvgs = detect_all_fvg(candles)

        # Should detect both types
        assert len(bullish_fvgs) > 0
        assert len(bearish_fvgs) > 0
        assert all(fvg.direction == "bullish" for fvg in bullish_fvgs)
        assert all(fvg.direction == "bearish" for fvg in bearish_fvgs)

    def test_auto_update_status(self):
        """Test auto-update of filled status."""
        candles = [
            create_test_candle(0, 100, 102, 99, 101),
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),  # FVG: 102-108
            create_test_candle(3, 111, 112, 105, 106),  # Fills FVG
        ]

        bullish_fvgs, bearish_fvgs = detect_all_fvg(candles, auto_update_status=True)

        # FVG should be auto-filled
        if bullish_fvgs:
            assert bullish_fvgs[0].filled
