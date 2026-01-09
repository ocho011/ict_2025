"""
ICT Liquidity Analysis
Identifies equal highs/lows, premium/discount zones, and liquidity sweeps
"""

from collections import deque
from typing import List, Optional, Tuple, Union

from src.models.candle import Candle
from src.models.ict_signals import LiquidityLevel, LiquiditySweep


def find_equal_highs(
    candles: Union[List[Candle], deque[Candle]],
    tolerance_percent: float = 0.001,
    min_touches: int = 2,
    lookback: int = 20,
) -> List[LiquidityLevel]:
    """
    Find equal highs (Buy Side Liquidity - BSL).

    Equal highs are price levels where multiple swing highs form at similar prices,
    indicating accumulation of buy stop orders above.

    Args:
        candles: List or deque of Candle objects
        tolerance_percent: Price tolerance for "equal" (default 0.1%)
        min_touches: Minimum number of touches required (default 2)
        lookback: Number of candles to look back for patterns

    Returns:
        List of LiquidityLevel objects for equal highs (BSL)
    """
    equal_highs: List[LiquidityLevel] = []
    candles_list = list(candles)

    # Need at least 3 candles for local peak detection (1 in middle, 1 on each side)
    if len(candles_list) < 3:
        return equal_highs

    # Collect significant highs (local peaks) - look 1 bar on each side
    swing_highs = []

    for i in range(1, len(candles_list) - 1):
        candle = candles_list[i]
        prev_candle = candles_list[i - 1]
        next_candle = candles_list[i + 1]

        # Check if this is a local high (higher than immediate neighbors)
        if candle.high > prev_candle.high and candle.high > next_candle.high:
            swing_highs.append((i, candle.high, candle.open_time))

    # Group equal highs within tolerance
    processed = set()

    for i, (current_idx, current_high, current_time) in enumerate(swing_highs):
        if i in processed:
            continue

        # Find all highs within tolerance of current high
        touches = [(i, current_idx, current_high, current_time)]

        for j in range(i + 1, len(swing_highs)):
            if j in processed:
                continue

            other_idx, other_high, other_time = swing_highs[j]

            # Check if within tolerance and within lookback window
            price_diff = abs(other_high - current_high)
            tolerance = current_high * tolerance_percent

            if price_diff <= tolerance and (other_idx - current_idx) <= lookback:
                touches.append((j, other_idx, other_high, other_time))
                processed.add(j)

        # If we have enough touches, create liquidity level
        if len(touches) >= min_touches:
            avg_price = sum(h for _, _, h, _ in touches) / len(touches)

            equal_highs.append(
                LiquidityLevel(
                    index=current_idx,
                    type="BSL",
                    price=avg_price,
                    timestamp=current_time,
                    swept=False,
                    num_touches=len(touches),
                )
            )

            processed.add(i)

    return equal_highs


def find_equal_lows(
    candles: Union[List[Candle], deque[Candle]],
    tolerance_percent: float = 0.001,
    min_touches: int = 2,
    lookback: int = 20,
) -> List[LiquidityLevel]:
    """
    Find equal lows (Sell Side Liquidity - SSL).

    Equal lows are price levels where multiple swing lows form at similar prices,
    indicating accumulation of sell stop orders below.

    Args:
        candles: List or deque of Candle objects
        tolerance_percent: Price tolerance for "equal" (default 0.1%)
        min_touches: Minimum number of touches required (default 2)
        lookback: Number of candles to look back for patterns

    Returns:
        List of LiquidityLevel objects for equal lows (SSL)
    """
    equal_lows: List[LiquidityLevel] = []
    candles_list = list(candles)

    # Need at least 3 candles for local valley detection (1 in middle, 1 on each side)
    if len(candles_list) < 3:
        return equal_lows

    # Collect significant lows (local valleys) - look 1 bar on each side
    swing_lows = []

    for i in range(1, len(candles_list) - 1):
        candle = candles_list[i]
        prev_candle = candles_list[i - 1]
        next_candle = candles_list[i + 1]

        # Check if this is a local low (lower than immediate neighbors)
        if candle.low < prev_candle.low and candle.low < next_candle.low:
            swing_lows.append((i, candle.low, candle.open_time))

    # Group equal lows within tolerance
    processed = set()

    for i, (current_idx, current_low, current_time) in enumerate(swing_lows):
        if i in processed:
            continue

        # Find all lows within tolerance of current low
        touches = [(i, current_idx, current_low, current_time)]

        for j in range(i + 1, len(swing_lows)):
            if j in processed:
                continue

            other_idx, other_low, other_time = swing_lows[j]

            # Check if within tolerance and within lookback window
            price_diff = abs(other_low - current_low)
            tolerance = current_low * tolerance_percent

            if price_diff <= tolerance and (other_idx - current_idx) <= lookback:
                touches.append((j, other_idx, other_low, other_time))
                processed.add(j)

        # If we have enough touches, create liquidity level
        if len(touches) >= min_touches:
            avg_price = sum(l for _, _, l, _ in touches) / len(touches)

            equal_lows.append(
                LiquidityLevel(
                    index=current_idx,
                    type="SSL",
                    price=avg_price,
                    timestamp=current_time,
                    swept=False,
                    num_touches=len(touches),
                )
            )

            processed.add(i)

    return equal_lows


def calculate_premium_discount(
    candles: Union[List[Candle], deque[Candle]], lookback: int = 50
) -> Tuple[float, float, float]:
    """
    Calculate premium and discount zones based on recent range.

    Premium zone: Upper 50% of range (expensive, good for selling)
    Discount zone: Lower 50% of range (cheap, good for buying)

    Args:
        candles: List or deque of Candle objects
        lookback: Number of candles to calculate range

    Returns:
        Tuple of (range_low, range_mid, range_high)
    """
    candles_list = list(candles)

    if len(candles_list) < lookback:
        lookback = len(candles_list)

    if lookback == 0:
        return (0.0, 0.0, 0.0)

    recent_candles = candles_list[-lookback:]

    range_high = max(candle.high for candle in recent_candles)
    range_low = min(candle.low for candle in recent_candles)
    range_mid = (range_high + range_low) / 2.0

    return (range_low, range_mid, range_high)


def is_in_premium(current_price: float, range_low: float, range_high: float) -> bool:
    """
    Check if current price is in premium zone (upper 50%).

    Args:
        current_price: Current market price
        range_low: Low of the range
        range_high: High of the range

    Returns:
        True if price is in premium zone
    """
    range_mid = (range_high + range_low) / 2.0
    return current_price > range_mid


def is_in_discount(current_price: float, range_low: float, range_high: float) -> bool:
    """
    Check if current price is in discount zone (lower 50%).

    Args:
        current_price: Current market price
        range_low: Low of the range
        range_high: High of the range

    Returns:
        True if price is in discount zone
    """
    range_mid = (range_high + range_low) / 2.0
    return current_price < range_mid


def detect_liquidity_sweep(
    candles: Union[List[Candle], deque[Candle]],
    liquidity_levels: List[LiquidityLevel],
    reversal_threshold: float = 0.5,
) -> List[LiquiditySweep]:
    """
    Detect liquidity sweep events (stop hunts before reversal).

    A liquidity sweep occurs when price breaks through a liquidity level
    (taking stops) and then reverses direction.

    Args:
        candles: List or deque of Candle objects
        liquidity_levels: List of LiquidityLevel objects to check
        reversal_threshold: Minimum reversal as % of sweep distance

    Returns:
        List of LiquiditySweep objects
    """
    sweeps: List[LiquiditySweep] = []
    candles_list = list(candles)

    for level in liquidity_levels:
        if level.swept:
            continue  # Already swept

        # Check each candle after the liquidity level
        for i in range(level.index + 1, len(candles_list)):
            candle = candles_list[i]

            swept = False
            reversal_started = False
            direction = None

            # Check for BSL sweep (price goes above, then reverses down)
            if level.type == "BSL" and candle.high > level.price:
                swept = True
                direction = "bearish"

                # Check if price reversed back through the level
                # A true reversal means price comes back below the swept level
                for j in range(i + 1, min(i + 5, len(candles_list))):
                    future_candle = candles_list[j]

                    # True ICT reversal: price must come back below the level
                    if future_candle.low < level.price:
                        reversal_started = True
                        break

            # Check for SSL sweep (price goes below, then reverses up)
            elif level.type == "SSL" and candle.low < level.price:
                swept = True
                direction = "bullish"

                # Check if price reversed back through the level
                # A true reversal means price comes back above the swept level
                for j in range(i + 1, min(i + 5, len(candles_list))):
                    future_candle = candles_list[j]

                    # True ICT reversal: price must come back above the level
                    if future_candle.high > level.price:
                        reversal_started = True
                        break

            if swept:
                level.swept = True

                sweeps.append(
                    LiquiditySweep(
                        index=i,
                        direction=direction,
                        swept_level=level.price,
                        reversal_started=reversal_started,
                        timestamp=candle.open_time,
                    )
                )
                break  # Found the sweep for this level

    return sweeps


def find_liquidity_voids(
    candles: Union[List[Candle], deque[Candle]], min_gap_percent: float = 0.005
) -> List[Tuple[int, float, float]]:
    """
    Find liquidity voids (areas with no trading activity).

    Liquidity voids are gaps where price moved quickly with little trading,
    similar to FVGs but focusing on volume gaps.

    Args:
        candles: List or deque of Candle objects
        min_gap_percent: Minimum gap size as percentage

    Returns:
        List of tuples (index, void_low, void_high)
    """
    voids: List[Tuple[int, float, float]] = []
    candles_list = list(candles)

    if len(candles_list) < 3:
        return voids

    for i in range(len(candles_list) - 2):
        candle_0 = candles_list[i]
        candles_list[i + 1]
        candle_2 = candles_list[i + 2]

        # Look for gaps in price (similar to FVG)
        # Bullish void: candle_0.high < candle_2.low
        if candle_0.high < candle_2.low:
            void_size = candle_2.low - candle_0.high
            avg_price = (candle_0.high + candle_2.low) / 2.0

            if void_size / avg_price >= min_gap_percent:
                voids.append((i, candle_0.high, candle_2.low))

        # Bearish void: candle_2.high < candle_0.low
        elif candle_2.high < candle_0.low:
            void_size = candle_0.low - candle_2.high
            avg_price = (candle_2.high + candle_0.low) / 2.0

            if void_size / avg_price >= min_gap_percent:
                voids.append((i, candle_2.high, candle_0.low))

    return voids


def get_liquidity_draw(
    current_price: float, liquidity_levels: List[LiquidityLevel], direction: str = "both"
) -> Optional[LiquidityLevel]:
    """
    Get the nearest liquidity draw (magnet) for price.

    Price tends to be drawn toward nearby liquidity pools.

    Args:
        current_price: Current market price
        liquidity_levels: List of LiquidityLevel objects
        direction: 'above', 'below', or 'both'

    Returns:
        Nearest unswept LiquidityLevel or None
    """
    # Filter unswept levels
    unswept_levels = [level for level in liquidity_levels if not level.swept]

    if not unswept_levels:
        return None

    # Filter by direction
    if direction == "above":
        filtered = [level for level in unswept_levels if level.price > current_price]
    elif direction == "below":
        filtered = [level for level in unswept_levels if level.price < current_price]
    else:  # both
        filtered = unswept_levels

    if not filtered:
        return None

    # Find nearest level
    nearest = min(filtered, key=lambda level: abs(level.price - current_price))

    return nearest
