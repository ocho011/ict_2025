"""
Unit tests for ICT Order Block (OB) Detection
"""

import pytest
from datetime import datetime, timedelta
from collections import deque

from src.models.candle import Candle
from src.models.ict_signals import OrderBlock
from src.indicators.ict_order_block import (
    calculate_average_range,
    identify_bullish_ob,
    identify_bearish_ob,
    validate_ob_strength,
    get_ob_zone,
    filter_obs_by_strength,
    find_nearest_ob,
    detect_all_ob
)


def create_test_candle(
    index: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    base_time: datetime = None
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
        is_closed=True
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

    def test_average_range_insufficient_data(self):
        """Test average range with fewer candles than period."""
        candles = [
            create_test_candle(0, 100, 105, 100, 103),  # Range: 5
        ]

        avg_range = calculate_average_range(candles, period=20)
        assert avg_range == 5.0  # Uses available candle

    def test_average_range_empty_list(self):
        """Test average range with empty list."""
        candles = []
        avg_range = calculate_average_range(candles, period=20)
        assert avg_range == 0.0


class TestIdentifyBullishOB:
    """Test bullish Order Block detection"""

    def test_bullish_ob_detected(self):
        """Test detection of bullish OB before strong up move."""
        candles = []

        # Create 20 candles with normal range (~2 points)
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Add bearish candle (this will be the OB)
        candles.append(create_test_candle(20, 120, 121, 118, 119))  # Down candle

        # Add strong bullish displacement (3x average range)
        candles.append(create_test_candle(21, 119, 125, 119, 124))  # Strong up move

        obs = identify_bullish_ob(candles, displacement_ratio=1.5)

        assert len(obs) > 0
        ob = obs[0]
        assert ob.direction == 'bullish'
        assert ob.index == 20  # The bearish candle before displacement
        assert ob.low == 118
        assert ob.high == 121

    def test_bullish_ob_strength_validation(self):
        """Test that OB strength is calculated correctly."""
        candles = []

        # Create candles with avg range = 2
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # OB candle
        candles.append(create_test_candle(20, 120, 121, 118, 119))

        # Displacement with range = 6 (3x average)
        candles.append(create_test_candle(21, 119, 125, 119, 124))

        obs = identify_bullish_ob(candles, displacement_ratio=1.5)

        assert len(obs) > 0
        ob = obs[0]
        # Strength should be displacement_size / avg_range = 6 / 2 = 3.0
        assert ob.strength >= 2.5  # At least 2.5x

    def test_no_ob_without_displacement(self):
        """Test that no OB is detected without strong displacement."""
        candles = []

        # Create candles with similar range, no displacement
        for i in range(25):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        obs = identify_bullish_ob(candles, displacement_ratio=1.5)

        # No strong displacement, so no OB detected
        assert len(obs) == 0

    def test_multiple_bullish_obs(self):
        """Test detection of multiple bullish OBs."""
        candles = []

        # First set with OB
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))
        candles.append(create_test_candle(20, 120, 121, 118, 119))  # OB 1
        candles.append(create_test_candle(21, 119, 125, 119, 124))  # Displacement 1

        # Second set with OB
        for i in range(22, 30):
            candles.append(create_test_candle(i, 125 + i - 22, 127 + i - 22, 125 + i - 22, 126 + i - 22))
        candles.append(create_test_candle(30, 133, 134, 131, 132))  # OB 2
        candles.append(create_test_candle(31, 132, 138, 132, 137))  # Displacement 2

        obs = identify_bullish_ob(candles, displacement_ratio=1.5)

        assert len(obs) >= 2

    def test_works_with_deque(self):
        """Test that function works with deque input."""
        candles_list = []
        for i in range(20):
            candles_list.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))
        candles_list.append(create_test_candle(20, 120, 121, 118, 119))
        candles_list.append(create_test_candle(21, 119, 125, 119, 124))

        candles_deque = deque(candles_list, maxlen=100)

        obs = identify_bullish_ob(candles_deque, displacement_ratio=1.5)

        assert isinstance(obs, list)
        assert len(obs) > 0


class TestIdentifyBearishOB:
    """Test bearish Order Block detection"""

    def test_bearish_ob_detected(self):
        """Test detection of bearish OB before strong down move."""
        candles = []

        # Create 20 candles with normal range (~2 points)
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        # Add bullish candle (this will be the OB)
        candles.append(create_test_candle(20, 120, 122, 120, 121))  # Up candle

        # Add strong bearish displacement
        candles.append(create_test_candle(21, 121, 121, 115, 116))  # Strong down move

        obs = identify_bearish_ob(candles, displacement_ratio=1.5)

        assert len(obs) > 0
        ob = obs[0]
        assert ob.direction == 'bearish'
        assert ob.index == 20  # The bullish candle before displacement
        assert ob.low == 120
        assert ob.high == 122

    def test_bearish_ob_strength_validation(self):
        """Test that bearish OB strength is calculated correctly."""
        candles = []

        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))

        candles.append(create_test_candle(20, 120, 122, 120, 121))
        candles.append(create_test_candle(21, 121, 121, 115, 116))  # Range = 6

        obs = identify_bearish_ob(candles, displacement_ratio=1.5)

        assert len(obs) > 0
        ob = obs[0]
        assert ob.strength >= 2.5


class TestValidateOBStrength:
    """Test OB strength validation"""

    def test_validate_strong_ob(self):
        """Test validation of strong OB."""
        ob = OrderBlock(
            index=10,
            direction='bullish',
            high=110,
            low=100,
            timestamp=datetime(2025, 1, 1),
            displacement_size=15.0,
            strength=2.5  # Strong
        )

        assert validate_ob_strength(ob, min_strength=1.5)
        assert validate_ob_strength(ob, min_strength=2.0)

    def test_validate_weak_ob(self):
        """Test validation of weak OB."""
        ob = OrderBlock(
            index=10,
            direction='bullish',
            high=110,
            low=100,
            timestamp=datetime(2025, 1, 1),
            displacement_size=8.0,
            strength=1.2  # Weak
        )

        assert not validate_ob_strength(ob, min_strength=1.5)
        assert validate_ob_strength(ob, min_strength=1.0)


class TestGetOBZone:
    """Test OB zone extraction"""

    def test_bullish_ob_zone(self):
        """Test zone for bullish OB (lower portion)."""
        ob = OrderBlock(
            index=10,
            direction='bullish',
            high=110,
            low=100,
            timestamp=datetime(2025, 1, 1),
            displacement_size=15.0,
            strength=2.0
        )

        low, high = get_ob_zone(ob, zone_percent=0.5)

        # Entry zone is lower 50% of OB
        assert low == 100
        assert high == 105

    def test_bearish_ob_zone(self):
        """Test zone for bearish OB (upper portion)."""
        ob = OrderBlock(
            index=10,
            direction='bearish',
            high=110,
            low=100,
            timestamp=datetime(2025, 1, 1),
            displacement_size=15.0,
            strength=2.0
        )

        low, high = get_ob_zone(ob, zone_percent=0.5)

        # Entry zone is upper 50% of OB
        assert low == 105
        assert high == 110


class TestFilterOBsByStrength:
    """Test OB filtering by strength"""

    def test_filter_by_strength(self):
        """Test filtering OBs by minimum strength."""
        obs = [
            OrderBlock(0, 'bullish', 110, 100, datetime(2025, 1, 1), 15.0, 2.5),  # Strong
            OrderBlock(1, 'bullish', 120, 110, datetime(2025, 1, 1), 8.0, 1.2),   # Weak
            OrderBlock(2, 'bullish', 130, 120, datetime(2025, 1, 1), 12.0, 1.8),  # Medium
        ]

        filtered = filter_obs_by_strength(obs, min_strength=1.5)

        assert len(filtered) == 2  # Only strong and medium
        assert all(ob.strength >= 1.5 for ob in filtered)


class TestFindNearestOB:
    """Test finding nearest OB"""

    def test_find_nearest_bullish_ob(self):
        """Test finding nearest bullish OB to current price."""
        obs = [
            OrderBlock(0, 'bullish', 110, 100, datetime(2025, 1, 1), 15.0, 2.0),  # Mid: 105
            OrderBlock(1, 'bullish', 130, 120, datetime(2025, 1, 1), 15.0, 2.0),  # Mid: 125
            OrderBlock(2, 'bullish', 90, 80, datetime(2025, 1, 1), 15.0, 2.0),    # Mid: 85
        ]

        # Current price 115 - nearest is 100-110 OB (mid 105)
        nearest = find_nearest_ob(obs, 115, 'bullish')
        assert nearest is not None
        assert nearest.low == 100

    def test_find_nearest_no_match(self):
        """Test when no OB matches direction."""
        obs = [
            OrderBlock(0, 'bearish', 110, 100, datetime(2025, 1, 1), 15.0, 2.0),
        ]

        nearest = find_nearest_ob(obs, 105, 'bullish')
        assert nearest is None


class TestDetectAllOB:
    """Test combined OB detection"""

    def test_detect_all_ob(self):
        """Test detecting both bullish and bearish OBs."""
        candles = []

        # Setup for bullish OB
        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))
        candles.append(create_test_candle(20, 120, 121, 118, 119))  # Bullish OB
        candles.append(create_test_candle(21, 119, 125, 119, 124))  # Up displacement

        # Setup for bearish OB
        for i in range(22, 30):
            candles.append(create_test_candle(i, 125 + i - 22, 127 + i - 22, 125 + i - 22, 126 + i - 22))
        candles.append(create_test_candle(30, 133, 135, 133, 134))  # Bearish OB
        candles.append(create_test_candle(31, 134, 134, 128, 129))  # Down displacement

        bullish_obs, bearish_obs = detect_all_ob(candles, displacement_ratio=1.5)

        # Should detect both types
        assert len(bullish_obs) > 0
        assert len(bearish_obs) > 0
        assert all(ob.direction == 'bullish' for ob in bullish_obs)
        assert all(ob.direction == 'bearish' for ob in bearish_obs)

    def test_detect_with_strength_filter(self):
        """Test detection with minimum strength filter."""
        candles = []

        for i in range(20):
            candles.append(create_test_candle(i, 100 + i, 102 + i, 100 + i, 101 + i))
        candles.append(create_test_candle(20, 120, 121, 118, 119))
        candles.append(create_test_candle(21, 119, 125, 119, 124))

        bullish_obs, bearish_obs = detect_all_ob(
            candles,
            displacement_ratio=1.5,
            min_strength=2.0
        )

        # All returned OBs should meet strength requirement
        for ob in bullish_obs + bearish_obs:
            assert ob.strength >= 2.0
