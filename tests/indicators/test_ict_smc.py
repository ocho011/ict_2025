"""
Unit tests for ICT Smart Money Concepts (SMC)
"""

from collections import deque
from datetime import datetime, timedelta

import pytest

from src.indicators.ict_smc import (
    calculate_average_range,
    detect_all_smc,
    detect_displacement,
    detect_inducement,
    find_mitigation_zone,
)
from src.models.candle import Candle
from src.models.features import (
    FairValueGap,
    OrderBlock,
)


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


class TestCalculateAverageRange:
    """Test average range calculation"""

    def test_average_range_calculation(self):
        """Test basic average range calculation."""
        candles = [
            create_test_candle(0, 100, 105, 100, 103),  # Range: 5
            create_test_candle(1, 103, 108, 103, 106),  # Range: 5
            create_test_candle(2, 106, 116, 106, 114),  # Range: 10
        ]

        avg_range = calculate_average_range(candles, period=3)
        expected = (5 + 5 + 10) / 3
        assert avg_range == pytest.approx(expected, rel=0.01)


class TestDetectInducement:
    """Test inducement (fake move) detection"""

    def test_bullish_inducement_detected(self):
        """Test detection of bullish inducement (fake bearish move)."""
        candles = []

        # Create baseline with recent low at 95
        for i in range(10):
            candles.append(create_test_candle(i, 95 + i, 100 + i, 95 + i, 97 + i))

        # Recent low is 95 (from candle 0)
        # Add inducement: price breaks below recent low (95) then reverses up
        candles.append(create_test_candle(10, 104, 105, 94, 95))  # Breaks below 95
        candles.append(create_test_candle(11, 95, 98, 95, 97))  # Reverses above 95

        inducements = detect_inducement(candles, lookback=10)

        assert len(inducements) > 0
        ind = inducements[0]
        assert ind.type == "liquidity_grab"
        assert ind.direction == "bearish"  # Fake bearish move
        assert ind.price_level == 95  # Recent low that was broken

    def test_bearish_inducement_detected(self):
        """Test detection of bearish inducement (fake bullish move)."""
        candles = []

        # Create baseline with recent high at 110
        for i in range(10):
            candles.append(create_test_candle(i, 100, 110, 95, 98))

        # Recent high is 110 (from candle 0)
        # Add inducement: price breaks above recent high then reverses down
        candles.append(create_test_candle(10, 104, 111, 104, 105))  # Breaks above 110
        candles.append(create_test_candle(11, 105, 105, 102, 103))  # Reverses below 110

        inducements = detect_inducement(candles, lookback=10)

        assert len(inducements) > 0
        ind = inducements[0]
        assert ind.type == "liquidity_grab"
        assert ind.direction == "bullish"  # Fake bullish move
        assert ind.price_level == 110  # Recent high that was broken

    def test_no_inducement_without_reversal(self):
        """Test no inducement when break continues in same direction."""
        candles = []

        # Create baseline
        for i in range(10):
            candles.append(create_test_candle(i, 100 + i, 105 + i, 100 + i, 102 + i))

        # Break high but continue up (not inducement)
        candles.append(create_test_candle(10, 109, 116, 109, 115))  # Breaks high
        candles.append(create_test_candle(11, 115, 120, 115, 119))  # Continues up

        inducements = detect_inducement(candles, lookback=10)

        # Should not detect inducement because price didn't reverse
        assert len(inducements) == 0

    def test_works_with_deque(self):
        """Test that function works with deque input."""
        candles_list = []
        for i in range(10):
            candles_list.append(create_test_candle(i, 95 + i, 100 + i, 95 + i, 97 + i))
        candles_list.append(create_test_candle(10, 104, 105, 94, 95))
        candles_list.append(create_test_candle(11, 95, 98, 95, 97))

        candles_deque = deque(candles_list, maxlen=100)

        inducements = detect_inducement(candles_deque, lookback=10)

        assert isinstance(inducements, list)
        assert len(inducements) > 0


class TestDetectDisplacement:
    """Test displacement (strong impulsive move) detection"""

    def test_bullish_displacement_detected(self):
        """Test detection of bullish displacement move."""
        candles = []

        # Create candles with avg range = 2
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Add strong bullish displacement (3x average range)
        candles.append(create_test_candle(20, 120, 126, 120, 125))  # Range: 6 (3x avg of 2)

        displacements = detect_displacement(candles, displacement_ratio=1.5)

        assert len(displacements) > 0
        disp = displacements[0]
        assert disp.direction == "bullish"
        assert disp.displacement_ratio >= 2.5  # Should be ~3.0
        assert disp.size == 5  # Close - open (125 - 120)

    def test_bearish_displacement_detected(self):
        """Test detection of bearish displacement move."""
        candles = []

        # Create candles with avg range = 2
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Add strong bearish displacement (3x average range)
        candles.append(create_test_candle(20, 120, 120, 114, 115))  # Range: 6 (3x avg of 2)

        displacements = detect_displacement(candles, displacement_ratio=1.5)

        assert len(displacements) > 0
        disp = displacements[0]
        assert disp.direction == "bearish"
        assert disp.displacement_ratio >= 2.5
        assert disp.size == 5  # Close - open (abs(115 - 120))

    def test_no_displacement_weak_move(self):
        """Test no displacement with normal-sized candles."""
        candles = []

        # All candles with similar range
        for i in range(25):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        displacements = detect_displacement(candles, displacement_ratio=1.5)

        # No displacement detected (all candles normal size)
        assert len(displacements) == 0

    def test_displacement_ratio_threshold(self):
        """Test displacement ratio threshold filtering."""
        candles = []

        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Add candle with range = 4 (2x average)
        candles.append(create_test_candle(20, 120, 124, 120, 123))

        # Should detect with ratio 1.5
        displacements_low = detect_displacement(candles, displacement_ratio=1.5)
        assert len(displacements_low) > 0

        # Should not detect with ratio 2.5
        displacements_high = detect_displacement(candles, displacement_ratio=2.5)
        assert len(displacements_high) == 0


class TestFindMitigationZone:
    """Test mitigation zone detection"""

    def test_fvg_mitigation_detected(self):
        """Test detection of FVG mitigation."""
        candles = [
            create_test_candle(0, 100, 102, 100, 101),  # FVG forms
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),  # Gap: 102-108
            create_test_candle(3, 111, 113, 110, 112),
            create_test_candle(4, 112, 113, 105, 106),  # Price returns to fill FVG
        ]

        # Create FVG
        fvg = FairValueGap(
            id="fvg1",
            interval="1m",
            direction="bullish",
            gap_high=108,
            gap_low=102,
            timestamp=candles[0].open_time,
            candle_index=0,
            gap_size=6.0,
        )

        mitigation_zones = find_mitigation_zone(candles, fvgs=[fvg])

        assert len(mitigation_zones) > 0
        mz = mitigation_zones[0]
        assert mz.type == "FVG"
        assert mz.mitigated


    def test_ob_mitigation_detected(self):
        """Test detection of Order Block mitigation."""
        candles = [
            create_test_candle(0, 100, 105, 100, 103),  # OB zone: 100-105
            create_test_candle(1, 103, 115, 103, 114),  # Displacement up
            create_test_candle(2, 114, 116, 113, 115),
            create_test_candle(3, 115, 116, 102, 103),  # Price returns to OB
        ]

        # Create OB
        ob = OrderBlock(
            id="ob1",
            interval="1m",
            direction="bullish",
            high=105,
            low=100,
            timestamp=candles[0].open_time,
            candle_index=0,
            displacement_size=12,
            strength=2.0,
        )

        mitigation_zones = find_mitigation_zone(candles, obs=[ob])

        assert len(mitigation_zones) > 0
        mz = mitigation_zones[0]
        assert mz.type == "OB"
        assert mz.mitigated

    def test_no_mitigation_without_price_return(self):
        """Test no mitigation when price doesn't return."""
        candles = [
            create_test_candle(0, 100, 102, 100, 101),
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),  # Gap: 102-108
            create_test_candle(3, 111, 113, 110, 112),
            create_test_candle(4, 112, 114, 111, 113),  # Price stays above gap
        ]

        fvg = FairValueGap(
            id="fvg2",
            interval="1m",
            direction="bullish",
            gap_high=108,
            gap_low=102,
            timestamp=candles[0].open_time,
            candle_index=0,
            gap_size=6.0,
        )

        mitigation_zones = find_mitigation_zone(candles, fvgs=[fvg])

        # No mitigation because price stayed above FVG
        assert len(mitigation_zones) == 0
        assert not fvg.filled

    def test_multiple_mitigations(self):
        """Test detection of multiple mitigation zones."""
        candles = [
            create_test_candle(0, 100, 102, 100, 101),  # FVG 1: 102-108
            create_test_candle(1, 101, 110, 101, 109),
            create_test_candle(2, 109, 112, 108, 111),
            create_test_candle(3, 111, 113, 110, 112),
            create_test_candle(4, 112, 114, 111, 113),  # FVG 2: 114-120
            create_test_candle(5, 113, 123, 113, 122),
            create_test_candle(6, 122, 125, 120, 124),
            create_test_candle(7, 124, 125, 105, 106),  # Fills FVG 1
            create_test_candle(8, 106, 118, 106, 117),  # Fills FVG 2
        ]

        fvg1 = FairValueGap("id1", "1m", "bullish", 108, 102, candles[0].open_time, 0, 6.0)
        fvg2 = FairValueGap("id2", "1m", "bullish", 120, 114, candles[4].open_time, 4, 6.0)

        mitigation_zones = find_mitigation_zone(candles, fvgs=[fvg1, fvg2])

        assert len(mitigation_zones) >= 2
        assert all(mz.type == "FVG" for mz in mitigation_zones)


class TestDetectAllSMC:
    """Test combined SMC detection"""

    def test_detect_all_smc(self):
        """Test detecting all SMC patterns in one call."""
        candles = []

        # Setup for inducement
        for i in range(10):
            candles.append(create_test_candle(i, 95 + i, 100 + i, 95 + i, 97 + i))

        # Add inducement pattern
        candles.append(create_test_candle(10, 104, 105, 94, 95))  # Break low
        candles.append(create_test_candle(11, 95, 98, 95, 97))  # Reverse up

        # Add more normal candles
        for i in range(12, 22):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Add displacement
        candles.append(create_test_candle(22, 122, 128, 122, 127))  # Strong move

        # Create FVG for mitigation test
        fvg = FairValueGap("id1", "1m", "bullish", 108, 102, candles[0].open_time, 0, 6.0)

        inducements, displacements, mitigation_zones = detect_all_smc(candles, fvgs=[fvg])

        # Should detect inducement
        assert len(inducements) > 0
        assert inducements[0].type == "liquidity_grab"

        # Should detect displacement
        assert len(displacements) > 0
        assert displacements[0].displacement_ratio >= 1.5

    def test_works_with_deque(self):
        """Test that combined function works with deque."""
        candles_list = []
        for i in range(25):
            candles_list.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        candles_deque = deque(candles_list, maxlen=100)

        inducements, displacements, mitigation_zones = detect_all_smc(candles_deque)

        assert isinstance(inducements, list)
        assert isinstance(displacements, list)
        assert isinstance(mitigation_zones, list)


class TestSMCWorkflows:
    """Test complete SMC analysis workflows"""

    def test_complete_smc_analysis(self):
        """Test full SMC workflow with inducement → displacement → mitigation."""
        candles = []

        # Phase 1: Normal trading
        for i in range(10):
            candles.append(create_test_candle(i, 95 + i, 100 + i, 95 + i, 97 + i))

        # Phase 2: Inducement (fake breakout below)
        candles.append(create_test_candle(10, 104, 105, 94, 95))  # Break low at 95
        candles.append(create_test_candle(11, 95, 98, 95, 97))  # Reverse up

        # Phase 3: More normal candles
        for i in range(12, 22):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Phase 4: Displacement (strong impulsive move)
        candles.append(create_test_candle(22, 122, 128, 122, 127))  # Displacement

        # Phase 5: Normal continuation
        for i in range(23, 28):
            candles.append(
                create_test_candle(i, 127 + i - 23, 129 + i - 23, 127 + i - 23, 128 + i - 23)
            )

        # Phase 6: Mitigation (return to fill FVG)
        # Create FVG with gap above the early candles to avoid early mitigation
        fvg = FairValueGap("id1", "1m", "bullish", 118, 112, candles[0].open_time, 0, 6.0)
        # Normal pullback to fill FVG (not a huge displacement)
        candles.append(create_test_candle(28, 132, 132, 130, 131))  # Small pullback
        candles.append(create_test_candle(29, 131, 131, 115, 116))  # Fill FVG

        # Analyze all patterns
        inducements, displacements, mitigation_zones = detect_all_smc(candles, fvgs=[fvg])

        # Verify all SMC concepts detected
        assert len(inducements) > 0  # Inducement detected
        assert len(displacements) > 0  # Displacement detected
        assert len(mitigation_zones) > 0  # Mitigation detected

        # Verify SMC concept characteristics
        assert inducements[0].type == "liquidity_grab"
        assert inducements[0].direction in ["bullish", "bearish"]
        assert displacements[0].displacement_ratio >= 1.5
        assert mitigation_zones[0].type == "FVG"
        assert mitigation_zones[0].mitigated
