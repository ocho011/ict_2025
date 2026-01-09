"""
ICT Smart Money Concepts (SMC)
Detects inducement, displacement, and mitigation zones
"""

from collections import deque
from typing import List, Optional, Union

from src.models.candle import Candle
from src.models.ict_signals import (
    Displacement,
    FairValueGap,
    Inducement,
    MitigationZone,
    OrderBlock,
)


def calculate_average_range(candles: Union[List[Candle], deque[Candle]], period: int = 20) -> float:
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


def detect_inducement(
    candles: Union[List[Candle], deque[Candle]], lookback: int = 10
) -> List[Inducement]:
    """
    Detect inducement patterns - fake moves to trap retail traders.

    Inducement occurs when price makes a small break of a previous high/low
    but quickly reverses, trapping traders who entered on the breakout.

    Args:
        candles: List or deque of Candle objects
        lookback: Number of candles to look back for recent highs/lows

    Returns:
        List of Inducement objects
    """
    inducements: List[Inducement] = []
    candles_list = list(candles)

    # Need at least lookback + 2 candles (lookback to identify level, 2 to confirm trap)
    if len(candles_list) < lookback + 2:
        return inducements

    # Find local highs and lows in lookback window
    for i in range(lookback, len(candles_list) - 1):
        current_candle = candles_list[i]
        next_candle = candles_list[i + 1]

        # Get recent highs and lows from lookback window
        recent_candles = candles_list[i - lookback : i]
        recent_high = max(c.high for c in recent_candles)
        recent_low = min(c.low for c in recent_candles)

        # Bullish inducement: Price breaks below recent low then reverses up
        # (Traps traders who shorted the breakout)
        if current_candle.low < recent_low and next_candle.close > recent_low:
            inducements.append(
                Inducement(
                    index=i,
                    type="liquidity_grab",
                    direction="bearish",  # Fake bearish move
                    price_level=recent_low,
                    timestamp=current_candle.open_time,
                )
            )

        # Bearish inducement: Price breaks above recent high then reverses down
        # (Traps traders who bought the breakout)
        elif current_candle.high > recent_high and next_candle.close < recent_high:
            inducements.append(
                Inducement(
                    index=i,
                    type="liquidity_grab",
                    direction="bullish",  # Fake bullish move
                    price_level=recent_high,
                    timestamp=current_candle.open_time,
                )
            )

    return inducements


def detect_displacement(
    candles: Union[List[Candle], deque[Candle]],
    displacement_ratio: float = 1.5,
    avg_range_period: int = 20,
) -> List[Displacement]:
    """
    Detect displacement moves - strong impulsive price movements.

    Displacement is a strong, fast move (1.5x-2x average range) that indicates
    smart money entering or exiting positions.

    Args:
        candles: List or deque of Candle objects
        displacement_ratio: Minimum ratio vs average range (default 1.5x)
        avg_range_period: Period for calculating average range

    Returns:
        List of Displacement objects
    """
    displacements: List[Displacement] = []
    candles_list = list(candles)

    if len(candles_list) < avg_range_period + 1:
        return displacements

    # Calculate average range
    avg_range = calculate_average_range(candles_list, avg_range_period)

    if avg_range == 0:
        return displacements

    # Look for displacement moves
    for i in range(avg_range_period, len(candles_list)):
        candle = candles_list[i]
        candle_range = candle.high - candle.low

        # Check if this candle is a displacement (strong move)
        if candle_range >= displacement_ratio * avg_range:
            # Determine direction
            is_bullish = candle.close > candle.open
            direction = "bullish" if is_bullish else "bearish"

            displacements.append(
                Displacement(
                    index=i,
                    direction=direction,
                    start_price=candle.open,
                    end_price=candle.close,
                    displacement_ratio=candle_range / avg_range,
                    timestamp=candle.open_time,
                )
            )

    return displacements


def find_mitigation_zone(
    candles: Union[List[Candle], deque[Candle]],
    fvgs: Optional[List[FairValueGap]] = None,
    obs: Optional[List[OrderBlock]] = None,
) -> List[MitigationZone]:
    """
    Find mitigation zones - areas where price fills imbalances or order blocks.

    Mitigation occurs when price returns to fill a FVG or enters an OB zone,
    indicating smart money is taking profits or adding to positions.

    Args:
        candles: List or deque of Candle objects
        fvgs: Optional list of FairValueGap objects to check for mitigation
        obs: Optional list of OrderBlock objects to check for mitigation

    Returns:
        List of MitigationZone objects
    """
    mitigation_zones: List[MitigationZone] = []
    candles_list = list(candles)

    if not fvgs and not obs:
        return mitigation_zones

    # Check FVG mitigation
    if fvgs:
        for fvg in fvgs:
            if fvg.filled:
                continue  # Already mitigated

            # Check if price has entered the FVG zone
            # Skip the 3-candle FVG pattern itself (indices: fvg.index, fvg.index+1, fvg.index+2)
            for i in range(fvg.index + 3, len(candles_list)):
                candle = candles_list[i]

                # Price has entered the FVG zone
                if candle.low <= fvg.gap_high and candle.high >= fvg.gap_low:
                    mitigation_zones.append(
                        MitigationZone(
                            index=i,
                            type="FVG",
                            high=fvg.gap_high,
                            low=fvg.gap_low,
                            timestamp=candle.open_time,
                            mitigated=True,
                        )
                    )
                    fvg.filled = True  # Mark FVG as filled
                    break

    # Check OB mitigation
    if obs:
        for ob in obs:
            # Check if price has entered the OB zone
            for i in range(ob.index + 1, len(candles_list)):
                candle = candles_list[i]

                # Price has entered the OB zone
                if candle.low <= ob.high and candle.high >= ob.low:
                    mitigation_zones.append(
                        MitigationZone(
                            index=i,
                            type="OB",
                            high=ob.high,
                            low=ob.low,
                            timestamp=candle.open_time,
                            mitigated=True,
                        )
                    )
                    break

    return mitigation_zones


def detect_all_smc(
    candles: Union[List[Candle], deque[Candle]],
    displacement_ratio: float = 1.5,
    inducement_lookback: int = 10,
    fvgs: Optional[List[FairValueGap]] = None,
    obs: Optional[List[OrderBlock]] = None,
) -> tuple[List[Inducement], List[Displacement], List[MitigationZone]]:
    """
    Detect all Smart Money Concepts in one call.

    Args:
        candles: List or deque of Candle objects
        displacement_ratio: Minimum ratio vs average range for displacement
        inducement_lookback: Lookback period for inducement detection
        fvgs: Optional list of FairValueGap objects for mitigation detection
        obs: Optional list of OrderBlock objects for mitigation detection

    Returns:
        Tuple of (inducements, displacements, mitigation_zones)
    """
    inducements = detect_inducement(candles, lookback=inducement_lookback)
    displacements = detect_displacement(candles, displacement_ratio=displacement_ratio)
    mitigation_zones = find_mitigation_zone(candles, fvgs=fvgs, obs=obs)

    return (inducements, displacements, mitigation_zones)
