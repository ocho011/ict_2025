"""
ICT Fair Value Gap (FVG) Detection
Identifies imbalances in price action using 3-candle patterns
"""

from collections import deque
from typing import List, Union

from src.models.candle import Candle

from src.models.indicators import FairValueGap


def detect_bullish_fvg(
    candles: Union[List[Candle], deque[Candle]],
    interval: str = "1h",
    min_gap_percent: float = 0.001,
) -> List["FairValueGap"]:
    """
    Detect bullish Fair Value Gaps (FVG).

    A bullish FVG occurs when there's a gap between candle[0].high and candle[2].low,
    indicating an imbalance where price moved up too quickly.

    Args:
        candles: List or deque of Candle objects
        interval: Timeframe (e.g., '1h', '4h')
        min_gap_percent: Minimum gap size as percentage of price (default 0.1%)

    Returns:
        List of FairValueGap objects for bullish gaps
    """
    bullish_fvgs: List[FairValueGap] = []
    candles_list = list(candles)

    # Need at least 3 candles for FVG pattern
    if len(candles_list) < 3:
        return bullish_fvgs

    # Iterate through candles looking for 3-candle bullish FVG pattern
    for i in range(len(candles_list) - 2):
        candle_0 = candles_list[i]  # First candle
        _candle_1 = candles_list[i + 1]  # Middle candle (creates the gap)
        candle_2 = candles_list[i + 2]  # Third candle

        # Bullish FVG: gap between candle[0].high and candle[2].low
        if candle_0.high < candle_2.low:
            gap_low = candle_0.high
            gap_high = candle_2.low
            gap_size = gap_high - gap_low

            # Check minimum gap size
            avg_price = (candle_0.high + candle_2.low) / 2.0
            gap_percent = gap_size / avg_price

            if gap_percent >= min_gap_percent:
                fvg_id = f"{interval}_{_candle_1.open_time.timestamp()}_bullish"

                bullish_fvgs.append(
                    FairValueGap(
                        id=fvg_id,
                        interval=interval,
                        direction="bullish",
                        gap_high=gap_high,
                        gap_low=gap_low,
                        timestamp=_candle_1.open_time,
                        candle_index=i + 1,
                        gap_size=gap_size,
                    )
                )

    return bullish_fvgs


def detect_bearish_fvg(
    candles: Union[List[Candle], deque[Candle]],
    interval: str = "1h",
    min_gap_percent: float = 0.001,
) -> List["FairValueGap"]:
    """
    Detect bearish Fair Value Gaps (FVG).

    A bearish FVG occurs when there's a gap between candle[0].low and candle[2].high,
    indicating an imbalance where price moved down too quickly.

    Args:
        candles: List or deque of Candle objects
        interval: Timeframe (e.g., '1h', '4h')
        min_gap_percent: Minimum gap size as percentage of price (default 0.1%)

    Returns:
        List of FairValueGap objects for bearish gaps
    """
    bearish_fvgs: List[FairValueGap] = []
    candles_list = list(candles)

    # Need at least 3 candles for FVG pattern
    if len(candles_list) < 3:
        return bearish_fvgs

    # Iterate through candles looking for 3-candle bearish FVG pattern
    for i in range(len(candles_list) - 2):
        candle_0 = candles_list[i]  # First candle
        _candle_1 = candles_list[i + 1]  # Middle candle (creates the gap)
        candle_2 = candles_list[i + 2]  # Third candle

        # Bearish FVG: gap between candle[2].high and candle[0].low
        if candle_2.high < candle_0.low:
            gap_high = candle_0.low
            gap_low = candle_2.high
            gap_size = gap_high - gap_low

            # Check minimum gap size
            avg_price = (candle_0.low + candle_2.high) / 2.0
            gap_percent = gap_size / avg_price

            if gap_percent >= min_gap_percent:
                fvg_id = f"{interval}_{_candle_1.open_time.timestamp()}_bearish"

                bearish_fvgs.append(
                    FairValueGap(
                        id=fvg_id,
                        interval=interval,
                        direction="bearish",
                        gap_high=gap_high,
                        gap_low=gap_low,
                        timestamp=_candle_1.open_time,
                        candle_index=i + 1,
                        gap_size=gap_size,
                    )
                )

    return bearish_fvgs


def is_fvg_filled(fvg: "FairValueGap", current_price: float) -> bool:
    """
    Check if a Fair Value Gap has been filled/mitigated.

    A FVG is considered filled when price returns to trade within the gap zone.

    Args:
        fvg: FairValueGap object to check
        current_price: Current market price

    Returns:
        True if the FVG has been filled
    """
    # Check if price enters the gap zone
    if fvg.gap_low <= current_price <= fvg.gap_high:
        return True
    # Or use the filled property from indicators.FairValueGap
    return fvg.filled


def get_fvg_levels(fvg: FairValueGap) -> tuple[float, float, float]:
    """
    Get key price levels from a Fair Value Gap.

    Args:
        fvg: FairValueGap object

    Returns:
        Tuple of (gap_low, gap_midpoint, gap_high)
    """
    return (fvg.gap_low, fvg.midpoint, fvg.gap_high)


def update_fvg_status(
    fvgs: List["FairValueGap"],
    candles: Union[List[Candle], deque[Candle]],
    start_index: int = 0,
) -> List["FairValueGap"]:
    """
    Update filled status for all FVGs based on subsequent price action.

    This function returns new FVG objects with updated status (immutable pattern).

    Args:
        fvgs: List of FairValueGap objects to update
        candles: List or deque of Candle objects
        start_index: Index in candles to start checking from

    Returns:
        List of FairValueGap objects with updated status
    """
    from src.models.indicators import IndicatorStatus

    candles_list = list(candles)
    updated_fvgs: List["FairValueGap"] = []

    for fvg in fvgs:
        if fvg.status in (
            IndicatorStatus.MITIGATED,
            IndicatorStatus.FILLED,
            IndicatorStatus.INVALIDATED,
        ):
            updated_fvgs.append(fvg)
            continue  # Already filled/mitigated

        filled = False
        # Check all candles after the FVG formation
        for i in range(max(start_index, fvg.index + 2), len(candles_list)):
            candle = candles_list[i]

            # Check if candle trades within the FVG zone
            # FVG is filled if candle high is above gap_low AND candle low is below gap_high
            if candle.low <= fvg.gap_high and candle.high >= fvg.gap_low:
                filled = True
                break

        if filled:
            updated_fvgs.append(fvg.with_status(IndicatorStatus.FILLED, fill_percent=1.0))
        else:
            updated_fvgs.append(fvg)

    return updated_fvgs


def find_nearest_fvg(
    fvgs: List["FairValueGap"],
    current_price: float,
    direction: str = "bullish",
    only_unfilled: bool = True,
) -> Union["FairValueGap", None]:
    """
    Find the nearest FVG to current price.

    Args:
        fvgs: List of FairValueGap objects
        current_price: Current market price
        direction: 'bullish' or 'bearish' FVGs to search
        only_unfilled: If True, only consider unfilled FVGs

    Returns:
        Nearest FairValueGap or None if not found
    """
    from src.models.indicators import IndicatorStatus

    filtered_fvgs = [
        fvg
        for fvg in fvgs
        if fvg.direction == direction
        and (
            not only_unfilled
            or fvg.status in (IndicatorStatus.ACTIVE, IndicatorStatus.TOUCHED)
        )
    ]

    if not filtered_fvgs:
        return None

    # Find FVG with midpoint closest to current price
    nearest_fvg = min(filtered_fvgs, key=lambda fvg: abs(fvg.midpoint - current_price))

    return nearest_fvg


def get_entry_zone(fvg: FairValueGap, zone_percent: float = 0.5) -> tuple[float, float]:
    """
    Get optimal entry zone within a FVG.

    For bullish FVG, entry zone is lower portion (more optimal).
    For bearish FVG, entry zone is upper portion (more optimal).

    Args:
        fvg: FairValueGap object
        zone_percent: Percentage of gap to use as entry zone (0.0-1.0)

    Returns:
        Tuple of (entry_low, entry_high)
    """
    gap_size = fvg.gap_size
    zone_size = gap_size * zone_percent

    if fvg.direction == "bullish":
        # Entry zone in lower portion of bullish FVG
        entry_low = fvg.gap_low
        entry_high = fvg.gap_low + zone_size
    else:  # bearish
        # Entry zone in upper portion of bearish FVG
        entry_high = fvg.gap_high
        entry_low = fvg.gap_high - zone_size

    return (entry_low, entry_high)


def detect_all_fvg(
    candles: Union[List[Candle], deque[Candle]],
    interval: str = "1h",
    min_gap_percent: float = 0.001,
    auto_update_status: bool = True,
) -> tuple[List["FairValueGap"], List["FairValueGap"]]:
    """
    Detect both bullish and bearish FVGs in one call.

    Args:
        candles: List or deque of Candle objects
        interval: Timeframe (e.g., '1h', '4h')
        min_gap_percent: Minimum gap size as percentage of price
        auto_update_status: Automatically update filled status

    Returns:
        Tuple of (bullish_fvgs, bearish_fvgs)
    """
    bullish_fvgs = detect_bullish_fvg(candles, interval, min_gap_percent)
    bearish_fvgs = detect_bearish_fvg(candles, interval, min_gap_percent)

    if auto_update_status:
        bullish_fvgs = update_fvg_status(bullish_fvgs, candles)
        bearish_fvgs = update_fvg_status(bearish_fvgs, candles)

    return (bullish_fvgs, bearish_fvgs)
