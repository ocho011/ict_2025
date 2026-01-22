"""
ICT Order Block (OB) Identification
Detects last opposing candle before strong displacement moves
"""

from collections import deque
from typing import List, Optional, Union

from src.models.candle import Candle

from src.models.features import OrderBlock


def calculate_average_range(
    candles: Union[List[Candle], deque[Candle]], period: int = 20
) -> float:
    """
    Calculate average candle range over period.

    Args:
        candles: List or deque of Candle objects
        period: Number of candles to calculate average over

    Returns:
        Average candle range (high - low)
    """
    candles_list = list(candles)

    if len(candles_list) < period:
        period = len(candles_list)

    if period == 0:
        return 0.0

    recent_candles = candles_list[-period:]
    total_range = sum(candle.high - candle.low for candle in recent_candles)

    return total_range / period


def identify_bullish_ob(
    candles: Union[List[Candle], deque[Candle]],
    interval: str = "1h",
    displacement_ratio: float = 1.5,
    avg_range_period: int = 20,
) -> List["OrderBlock"]:
    """
    Identify bullish Order Blocks (demand zones).

    A bullish OB is the last bearish/down candle before a strong upward displacement.
    These zones often act as support where smart money accumulated positions.

    Args:
        candles: List or deque of Candle objects
        interval: Timeframe (e.g., '1h', '4h')
        displacement_ratio: Minimum ratio of displacement to average range (default 1.5x)
        avg_range_period: Period for calculating average range

    Returns:
        List of OrderBlock objects for bullish OBs
    """
    bullish_obs: List[OrderBlock] = []
    candles_list = list(candles)

    if len(candles_list) < avg_range_period + 2:
        return bullish_obs

    # Calculate average range
    avg_range = calculate_average_range(candles_list, avg_range_period)

    if avg_range == 0:
        return bullish_obs

    # Look for displacement moves (strong upward candles)
    for i in range(avg_range_period, len(candles_list)):
        current_candle = candles_list[i]
        candle_range = current_candle.high - current_candle.low

        # Check if this is a strong upward displacement
        is_bullish_displacement = (
            current_candle.close > current_candle.open  # Bullish candle
            and candle_range >= displacement_ratio * avg_range  # Strong move
        )

        if is_bullish_displacement:
            # Find the last bearish/down candle before this displacement
            # This is the Order Block (where smart money accumulated)
            for j in range(i - 1, max(0, i - 5), -1):  # Look back up to 5 candles
                prev_candle = candles_list[j]

                # Order Block criteria: bearish candle before displacement
                if prev_candle.close < prev_candle.open:
                    displacement_size = current_candle.high - current_candle.low
                    strength = displacement_size / avg_range

                    ob_id = (
                        f"{interval}_{prev_candle.open_time.timestamp()}_{i}_bullish"
                    )

                    bullish_obs.append(
                        OrderBlock(
                            id=ob_id,
                            interval=interval,
                            direction="bullish",
                            high=prev_candle.high,
                            low=prev_candle.low,
                            timestamp=prev_candle.open_time,
                            candle_index=j,
                            displacement_size=displacement_size,
                            strength=strength,
                        )
                    )
                    break  # Found the OB for this displacement

    return bullish_obs


def identify_bearish_ob(
    candles: Union[List[Candle], deque[Candle]],
    interval: str = "1h",
    displacement_ratio: float = 1.5,
    avg_range_period: int = 20,
) -> List["OrderBlock"]:
    """
    Identify bearish Order Blocks (supply zones).

    A bearish OB is the last bullish/up candle before a strong downward displacement.
    These zones often act as resistance where smart money distributed positions.

    Args:
        candles: List or deque of Candle objects
        interval: Timeframe (e.g., '1h', '4h')
        displacement_ratio: Minimum ratio of displacement to average range (default 1.5x)
        avg_range_period: Period for calculating average range

    Returns:
        List of OrderBlock objects for bearish OBs
    """
    bearish_obs: List[OrderBlock] = []
    candles_list = list(candles)

    if len(candles_list) < avg_range_period + 2:
        return bearish_obs

    # Calculate average range
    avg_range = calculate_average_range(candles_list, avg_range_period)

    if avg_range == 0:
        return bearish_obs

    # Look for displacement moves (strong downward candles)
    for i in range(avg_range_period, len(candles_list)):
        current_candle = candles_list[i]
        candle_range = current_candle.high - current_candle.low

        # Check if this is a strong downward displacement
        is_bearish_displacement = (
            current_candle.close < current_candle.open  # Bearish candle
            and candle_range >= displacement_ratio * avg_range  # Strong move
        )

        if is_bearish_displacement:
            # Find the last bullish/up candle before this displacement
            # This is the Order Block (where smart money distributed)
            for j in range(i - 1, max(0, i - 5), -1):  # Look back up to 5 candles
                prev_candle = candles_list[j]

                # Order Block criteria: bullish candle before displacement
                if prev_candle.close > prev_candle.open:
                    displacement_size = current_candle.high - current_candle.low
                    strength = displacement_size / avg_range

                    ob_id = (
                        f"{interval}_{prev_candle.open_time.timestamp()}_{i}_bearish"
                    )

                    bearish_obs.append(
                        OrderBlock(
                            id=ob_id,
                            interval=interval,
                            direction="bearish",
                            high=prev_candle.high,
                            low=prev_candle.low,
                            timestamp=prev_candle.open_time,
                            candle_index=j,
                            displacement_size=displacement_size,
                            strength=strength,
                        )
                    )
                    break  # Found the OB for this displacement

    return bearish_obs


def validate_ob_strength(ob: OrderBlock, min_strength: float = 1.5) -> bool:
    """
    Validate if Order Block has sufficient strength.

    Strength is measured by displacement_size / avg_range ratio.
    Higher strength means more institutional interest.

    Args:
        ob: OrderBlock object to validate
        min_strength: Minimum strength threshold (default 1.5)

    Returns:
        True if OB meets strength criteria
    """
    return ob.strength >= min_strength


def get_ob_zone(ob: OrderBlock, zone_percent: float = 0.5) -> tuple[float, float]:
    """
    Get optimal trading zone within Order Block.

    For bullish OB, optimal zone is lower portion (better entry).
    For bearish OB, optimal zone is upper portion (better entry).

    Args:
        ob: OrderBlock object
        zone_percent: Percentage of OB to use as zone (0.0-1.0)

    Returns:
        Tuple of (zone_low, zone_high)
    """
    zone_size = ob.zone_size * zone_percent

    if ob.direction == "bullish":
        # Entry zone in lower portion of bullish OB
        zone_low = ob.low
        zone_high = ob.low + zone_size
    else:  # bearish
        # Entry zone in upper portion of bearish OB
        zone_high = ob.high
        zone_low = ob.high - zone_size

    return (zone_low, zone_high)


def filter_obs_by_strength(
    obs: List[OrderBlock], min_strength: float = 1.5
) -> List[OrderBlock]:
    """
    Filter Order Blocks by minimum strength requirement.

    Args:
        obs: List of OrderBlock objects
        min_strength: Minimum strength threshold

    Returns:
        Filtered list of OrderBlock objects meeting strength criteria
    """
    return [ob for ob in obs if validate_ob_strength(ob, min_strength)]


def find_nearest_ob(
    obs: List[OrderBlock], current_price: float, direction: str = "bullish"
) -> Optional[OrderBlock]:
    """
    Find the nearest Order Block to current price.

    Args:
        obs: List of OrderBlock objects
        current_price: Current market price
        direction: 'bullish' or 'bearish' OBs to search

    Returns:
        Nearest OrderBlock or None if not found
    """
    filtered_obs = [ob for ob in obs if ob.direction == direction]

    if not filtered_obs:
        return None

    # Find OB with midpoint closest to current price
    nearest_ob = min(filtered_obs, key=lambda ob: abs(ob.midpoint - current_price))

    return nearest_ob


def detect_all_ob(
    candles: Union[List[Candle], deque[Candle]],
    interval: str = "1h",
    displacement_ratio: float = 1.5,
    avg_range_period: int = 20,
    min_strength: Optional[float] = None,
) -> tuple[List["OrderBlock"], List["OrderBlock"]]:
    """
    Detect both bullish and bearish Order Blocks in one call.

    Args:
        candles: List or deque of Candle objects
        interval: Timeframe (e.g., '1h', '4h')
        displacement_ratio: Minimum ratio of displacement to average range
        avg_range_period: Period for calculating average range
        min_strength: Optional minimum strength filter

    Returns:
        Tuple of (bullish_obs, bearish_obs)
    """
    bullish_obs = identify_bullish_ob(
        candles, interval, displacement_ratio, avg_range_period
    )
    bearish_obs = identify_bearish_ob(
        candles, interval, displacement_ratio, avg_range_period
    )

    # Apply strength filter if specified
    if min_strength is not None:
        bullish_obs = filter_obs_by_strength(bullish_obs, min_strength)
        bearish_obs = filter_obs_by_strength(bearish_obs, min_strength)

    return (bullish_obs, bearish_obs)
