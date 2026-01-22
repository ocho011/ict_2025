"""
Unit tests for ICT Liquidity Analysis
"""

from collections import deque
from datetime import datetime, timedelta

import pytest

from src.indicators.ict_liquidity import (
    calculate_premium_discount,
    detect_liquidity_sweep,
    find_equal_highs,
    find_equal_lows,
    find_liquidity_voids,
    get_liquidity_draw,
    is_in_discount,
    is_in_premium,
)
from src.models.candle import Candle
from src.models.features import LiquidityLevel


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


class TestFindEqualHighs:
    """Test equal highs (BSL) detection"""

    def test_equal_highs_detected(self):
        """Test detection of equal highs forming BSL."""
        candles = [
            create_test_candle(0, 100, 105, 100, 103),
            create_test_candle(1, 103, 110, 103, 108),  # High at 110
            create_test_candle(2, 108, 109, 106, 107),
            create_test_candle(3, 107, 110.05, 107, 109),  # High at 110.05 (equal)
            create_test_candle(4, 109, 109, 106, 107),
        ]

        equal_highs = find_equal_highs(candles, tolerance_percent=0.001, min_touches=2)

        assert len(equal_highs) > 0
        bsl = equal_highs[0]
        assert bsl.level_type == "bsl"
        assert bsl.strength == 2
        assert pytest.approx(bsl.price, abs=0.1) == 110

    def test_multiple_equal_highs(self):
        """Test detection of multiple equal high levels."""
        candles = [
            # First equal high group at 110 (need swing highs)
            create_test_candle(0, 100, 105, 100, 103),
            create_test_candle(1, 103, 110, 103, 108),  # Swing high at 110
            create_test_candle(2, 108, 109, 106, 107),
            create_test_candle(3, 107, 110.05, 107, 109),  # Swing high at 110.05 (equal)
            create_test_candle(4, 109, 109, 106, 107),
            # Second equal high group at 120 (need swing highs)
            create_test_candle(5, 107, 115, 107, 113),
            create_test_candle(6, 113, 120, 113, 118),  # Swing high at 120
            create_test_candle(7, 118, 119, 116, 117),
            create_test_candle(8, 117, 120.08, 117, 119),  # Swing high at 120.08 (equal)
            create_test_candle(9, 119, 119, 116, 117),
        ]

        equal_highs = find_equal_highs(candles, tolerance_percent=0.001, min_touches=2)

        assert len(equal_highs) >= 2

    def test_no_equal_highs_insufficient_touches(self):
        """Test no equal highs with only single touch."""
        candles = [
            create_test_candle(0, 100, 105, 100, 103),
            create_test_candle(1, 103, 110, 103, 108),  # Only one high
            create_test_candle(2, 108, 108, 106, 107),
        ]

        equal_highs = find_equal_highs(candles, tolerance_percent=0.001, min_touches=2)

        assert len(equal_highs) == 0


class TestFindEqualLows:
    """Test equal lows (SSL) detection"""

    def test_equal_lows_detected(self):
        """Test detection of equal lows forming SSL."""
        candles = [
            create_test_candle(0, 100, 102, 98, 99),
            create_test_candle(1, 99, 100, 95, 97),  # Swing low at 95
            create_test_candle(2, 97, 99, 97, 98),
            create_test_candle(3, 98, 100, 95.05, 96),  # Swing low at 95.05 (equal)
            create_test_candle(4, 96, 98, 96, 97),
        ]

        equal_lows = find_equal_lows(candles, tolerance_percent=0.001, min_touches=2)

        assert len(equal_lows) > 0
        ssl = equal_lows[0]
        assert ssl.level_type == "ssl"
        assert ssl.strength == 2
        assert pytest.approx(ssl.price, abs=0.1) == 95

    def test_multiple_equal_lows(self):
        """Test detection of multiple equal low levels."""
        candles = [
            # First equal low group at 95 (need swing lows)
            create_test_candle(0, 100, 102, 98, 99),
            create_test_candle(1, 99, 100, 95, 97),  # Swing low at 95
            create_test_candle(2, 97, 99, 97, 98),
            create_test_candle(3, 98, 100, 94.95, 96),  # Swing low at 94.95 (equal)
            create_test_candle(4, 96, 98, 96, 97),
            # Second equal low group at 85 (need swing lows)
            create_test_candle(5, 97, 99, 97, 98),
            create_test_candle(6, 98, 100, 85, 87),  # Swing low at 85
            create_test_candle(7, 87, 89, 87, 88),
            create_test_candle(8, 88, 90, 85.08, 86),  # Swing low at 85.08 (equal)
            create_test_candle(9, 86, 88, 86, 87),
        ]

        equal_lows = find_equal_lows(candles, tolerance_percent=0.001, min_touches=2)

        assert len(equal_lows) >= 2


class TestCalculatePremiumDiscount:
    """Test premium/discount zone calculation"""

    def test_premium_discount_calculation(self):
        """Test calculation of premium and discount zones."""
        candles = [
            create_test_candle(0, 100, 110, 90, 105),  # Range: 90-110
            create_test_candle(1, 105, 108, 92, 100),
            create_test_candle(2, 100, 105, 95, 102),
        ]

        range_low, range_mid, range_high = calculate_premium_discount(candles, lookback=3)

        assert range_low == 90
        assert range_high == 110
        assert range_mid == 100

    def test_premium_zone_check(self):
        """Test if price is in premium zone."""
        assert is_in_premium(105, 90, 110)  # Above midpoint (100)
        assert not is_in_premium(95, 90, 110)  # Below midpoint

    def test_discount_zone_check(self):
        """Test if price is in discount zone."""
        assert is_in_discount(95, 90, 110)  # Below midpoint (100)
        assert not is_in_discount(105, 90, 110)  # Above midpoint


class TestDetectLiquiditySweep:
    """Test liquidity sweep detection"""

    def test_bsl_sweep_with_reversal(self):
        """Test BSL sweep (stop hunt above, then reversal down)."""
        # Create equal highs at 110
        candles = [
            create_test_candle(0, 100, 110, 100, 108),
            create_test_candle(1, 108, 110.05, 106, 107),
        ]

        # Create liquidity level
        bsl = LiquidityLevel(
            id="lvl1",
            interval="1m",
            level_type="bsl",
            price=110,
            strength=2,
            timestamp=candles[0].open_time,
            candle_index=0,
            swept=False,
        )

        # Add sweep candle (goes above BSL)
        candles.append(create_test_candle(2, 107, 112, 107, 111))  # Sweep at index 2

        # Add reversal candle (comes back down)
        candles.append(create_test_candle(3, 111, 111, 106, 107))  # Reversal

        sweeps = detect_liquidity_sweep(candles, [bsl], reversal_threshold=0.5)

        assert len(sweeps) > 0
        sweep = sweeps[0]
        assert sweep.direction == "bearish"
        assert sweep.swept_level == 110
        assert sweep.reversal_started  # Should detect reversal

    def test_ssl_sweep_with_reversal(self):
        """Test SSL sweep (stop hunt below, then reversal up)."""
        # Create equal lows at 90
        candles = [
            create_test_candle(0, 100, 102, 90, 95),
            create_test_candle(1, 95, 97, 89.95, 92),
        ]

        # Create liquidity level
        ssl = LiquidityLevel(
            id="lvl2",
            interval="1m",
            level_type="ssl",
            price=90,
            strength=2,
            timestamp=candles[0].open_time,
            candle_index=0,
            swept=False,
        )

        # Add sweep candle (goes below SSL)
        candles.append(create_test_candle(2, 92, 92, 88, 89))  # Sweep

        # Add reversal candle (comes back up)
        candles.append(create_test_candle(3, 89, 94, 89, 93))  # Reversal

        sweeps = detect_liquidity_sweep(candles, [ssl], reversal_threshold=0.5)

        assert len(sweeps) > 0
        sweep = sweeps[0]
        assert sweep.direction == "bullish"
        assert sweep.reversal_started

    def test_sweep_without_reversal(self):
        """Test sweep that doesn't reverse."""
        candles = [
            create_test_candle(0, 100, 110, 100, 108),
        ]

        bsl = LiquidityLevel(
            id="lvl3",
            interval="1m",
            level_type="bsl",
            price=110,
            strength=2,
            timestamp=candles[0].open_time,
            candle_index=0,
            swept=False,
        )

        # Sweep but no reversal - price stays high
        candles.append(create_test_candle(1, 108, 112, 108, 111))  # Sweep at 112
        candles.append(create_test_candle(2, 111, 113, 110.5, 112))  # Stays above sweep
        candles.append(create_test_candle(3, 112, 114, 111.5, 113))  # Continues up

        sweeps = detect_liquidity_sweep(candles, [bsl], reversal_threshold=0.5)

        assert len(sweeps) > 0
        # Reversal requires going back at least 50% of the sweep distance
        # Sweep was from 110 to 112 (2 points), so reversal needs to go back 1 point to 111
        # But price stayed above 110.5, so no significant reversal
        assert not sweeps[0].reversal_started  # No reversal


class TestFindLiquidityVoids:
    """Test liquidity void detection"""

    def test_bullish_void_detected(self):
        """Test detection of bullish liquidity void."""
        candles = [
            create_test_candle(0, 100, 102, 100, 101),  # High at 102
            create_test_candle(1, 101, 110, 101, 109),  # Gap creator
            create_test_candle(2, 109, 112, 108, 111),  # Low at 108 > 102 = void
        ]

        voids = find_liquidity_voids(candles, min_gap_percent=0.005)

        assert len(voids) > 0
        index, void_low, void_high = voids[0]
        assert void_low == 102
        assert void_high == 108

    def test_bearish_void_detected(self):
        """Test detection of bearish liquidity void."""
        candles = [
            create_test_candle(0, 100, 102, 98, 99),  # Low at 98
            create_test_candle(1, 99, 99, 89, 90),  # Gap creator
            create_test_candle(2, 90, 92, 88, 89),  # High at 92 < 98 = void
        ]

        voids = find_liquidity_voids(candles, min_gap_percent=0.005)

        assert len(voids) > 0


class TestGetLiquidityDraw:
    """Test liquidity draw (magnet) detection"""

    def test_nearest_liquidity_draw_above(self):
        """Test finding nearest liquidity above current price."""
        levels = [
            LiquidityLevel("id1", "1m", "bsl", 110, 2, datetime(2025, 1, 1), 0, False),
            LiquidityLevel("id2", "1m", "bsl", 130, 2, datetime(2025, 1, 1), 1, False),
            LiquidityLevel("id3", "1m", "ssl", 90, 2, datetime(2025, 1, 1), 2, False),
        ]

        # Current price 105 - nearest above is 110
        draw = get_liquidity_draw(105, levels, direction="above")

        assert draw is not None
        assert draw.price == 110

    def test_nearest_liquidity_draw_below(self):
        """Test finding nearest liquidity below current price."""
        levels = [
            LiquidityLevel("id1", "1m", "bsl", 110, 2, datetime(2025, 1, 1), 0, False),
            LiquidityLevel("id2", "1m", "ssl", 90, 2, datetime(2025, 1, 1), 1, False),
            LiquidityLevel("id3", "1m", "ssl", 70, 2, datetime(2025, 1, 1), 2, False),
        ]

        # Current price 105 - nearest below is 90
        draw = get_liquidity_draw(105, levels, direction="below")

        assert draw is not None
        assert draw.price == 90

    def test_nearest_liquidity_draw_both(self):
        """Test finding nearest liquidity in any direction."""
        levels = [
            LiquidityLevel("id1", "1m", "bsl", 110, 2, datetime(2025, 1, 1), 0, False),
            LiquidityLevel("id2", "1m", "ssl", 90, 2, datetime(2025, 1, 1), 1, False),
        ]

        # Current price 105 - nearest is 110 (5 points away vs 15)
        draw = get_liquidity_draw(105, levels, direction="both")

        assert draw is not None
        assert draw.price == 110

    def test_no_unswept_liquidity(self):
        """Test when all liquidity is swept."""
        levels = [
            LiquidityLevel("id1", "1m", "bsl", 110, 2, datetime(2025, 1, 1), 0, True),  # Swept
        ]

        draw = get_liquidity_draw(105, levels, direction="both")

        assert draw is None


class TestLiquidityWorkflows:
    """Test complete liquidity analysis workflows"""

    def test_complete_liquidity_analysis(self):
        """Test full liquidity analysis workflow."""
        # Create candles with equal highs and lows (need swing patterns)
        candles = [
            create_test_candle(0, 100, 105, 95, 98),
            create_test_candle(1, 98, 110, 90, 105),  # Swing high at 110, swing low at 90
            create_test_candle(2, 105, 108, 95, 100),
            create_test_candle(
                3, 100, 110.05, 90.05, 102
            ),  # Swing high at 110.05, swing low at 90.05 (equal)
            create_test_candle(4, 102, 108, 95, 103),
        ]

        # Find liquidity levels
        equal_highs = find_equal_highs(candles, tolerance_percent=0.001)
        equal_lows = find_equal_lows(candles, tolerance_percent=0.001)

        assert len(equal_highs) > 0
        assert len(equal_lows) > 0

        # Calculate premium/discount
        range_low, range_mid, range_high = calculate_premium_discount(candles)

        assert range_low == 90
        assert range_high == 110.05  # Highest high from candle 3

        # Check for liquidity draw
        all_levels = equal_highs + equal_lows
        draw = get_liquidity_draw(105, all_levels)

        assert draw is not None

    def test_works_with_deque(self):
        """Test that functions work with deque input."""
        candles_list = [
            create_test_candle(0, 100, 110, 100, 108),
            create_test_candle(1, 108, 110.05, 106, 107),
        ]
        candles_deque = deque(candles_list, maxlen=100)

        equal_highs = find_equal_highs(candles_deque)

        assert isinstance(equal_highs, list)
