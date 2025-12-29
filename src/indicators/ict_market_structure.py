"""
ICT Market Structure Analysis
Identifies swing points, Break of Structure (BOS), and Change of Character (CHoCH)
"""

from typing import List, Optional, Union
from collections import deque

from src.models.candle import Candle
from src.models.ict_signals import SwingPoint, StructureBreak


def identify_swing_highs(
    candles: Union[List[Candle], deque[Candle]],
    left_bars: int = 5,
    right_bars: int = 5
) -> List[SwingPoint]:
    """
    Identify swing high points in price action.

    A swing high is a high that is higher than N bars to the left and N bars to the right.

    Args:
        candles: List or deque of Candle objects
        left_bars: Number of bars to look left for comparison
        right_bars: Number of bars to look right for comparison

    Returns:
        List of SwingPoint objects representing swing highs
    """
    swing_highs: List[SwingPoint] = []
    candles_list = list(candles)  # Convert deque to list if needed

    # Need at least left_bars + 1 + right_bars candles
    min_length = left_bars + 1 + right_bars
    if len(candles_list) < min_length:
        return swing_highs

    # Start from left_bars, end at len - right_bars (exclusive)
    for i in range(left_bars, len(candles_list) - right_bars):
        current_high = candles_list[i].high

        # Check if current high is higher than all left bars
        is_higher_than_left = all(
            current_high > candles_list[j].high
            for j in range(i - left_bars, i)
        )

        # Check if current high is higher than all right bars
        is_higher_than_right = all(
            current_high > candles_list[j].high
            for j in range(i + 1, i + 1 + right_bars)
        )

        if is_higher_than_left and is_higher_than_right:
            swing_highs.append(SwingPoint(
                index=i,
                price=current_high,
                type='high',
                timestamp=candles_list[i].open_time,
                strength=min(left_bars, right_bars)
            ))

    return swing_highs


def identify_swing_lows(
    candles: Union[List[Candle], deque[Candle]],
    left_bars: int = 5,
    right_bars: int = 5
) -> List[SwingPoint]:
    """
    Identify swing low points in price action.

    A swing low is a low that is lower than N bars to the left and N bars to the right.

    Args:
        candles: List or deque of Candle objects
        left_bars: Number of bars to look left for comparison
        right_bars: Number of bars to look right for comparison

    Returns:
        List of SwingPoint objects representing swing lows
    """
    swing_lows: List[SwingPoint] = []
    candles_list = list(candles)

    # Need at least left_bars + 1 + right_bars candles
    min_length = left_bars + 1 + right_bars
    if len(candles_list) < min_length:
        return swing_lows

    # Start from left_bars, end at len - right_bars (exclusive)
    for i in range(left_bars, len(candles_list) - right_bars):
        current_low = candles_list[i].low

        # Check if current low is lower than all left bars
        is_lower_than_left = all(
            current_low < candles_list[j].low
            for j in range(i - left_bars, i)
        )

        # Check if current low is lower than all right bars
        is_lower_than_right = all(
            current_low < candles_list[j].low
            for j in range(i + 1, i + 1 + right_bars)
        )

        if is_lower_than_left and is_lower_than_right:
            swing_lows.append(SwingPoint(
                index=i,
                price=current_low,
                type='low',
                timestamp=candles_list[i].open_time,
                strength=min(left_bars, right_bars)
            ))

    return swing_lows


def detect_bos(
    candles: Union[List[Candle], deque[Candle]],
    swing_lookback: int = 5
) -> List[StructureBreak]:
    """
    Detect Break of Structure (BOS) events.

    BOS occurs when price breaks the previous swing high (bullish) or swing low (bearish)
    in the direction of the current trend, confirming trend continuation.

    Args:
        candles: List or deque of Candle objects
        swing_lookback: Number of bars for swing point identification

    Returns:
        List of StructureBreak objects for BOS events
    """
    bos_events: List[StructureBreak] = []
    candles_list = list(candles)

    if len(candles_list) < swing_lookback * 2 + 2:
        return bos_events

    # Identify swing points
    swing_highs = identify_swing_highs(candles_list, swing_lookback, swing_lookback)
    swing_lows = identify_swing_lows(candles_list, swing_lookback, swing_lookback)

    if not swing_highs and not swing_lows:
        return bos_events

    # Track current trend based on swing structure
    # Bullish trend: higher highs and higher lows
    # Bearish trend: lower highs and lower lows

    # Detect bullish BOS: price breaks above previous swing high (uptrend continuation)
    for i in range(1, len(swing_highs)):
        prev_swing_high = swing_highs[i - 1]
        current_swing_high = swing_highs[i]

        # Higher high = bullish BOS
        if current_swing_high.price > prev_swing_high.price:
            # Find the candle that actually broke the level
            break_index = current_swing_high.index
            for j in range(prev_swing_high.index + 1, current_swing_high.index + 1):
                if candles_list[j].high > prev_swing_high.price:
                    break_index = j
                    break

            bos_events.append(StructureBreak(
                index=break_index,
                type='BOS',
                direction='bullish',
                broken_level=prev_swing_high.price,
                timestamp=candles_list[break_index].open_time
            ))

    # Detect bearish BOS: price breaks below previous swing low (downtrend continuation)
    for i in range(1, len(swing_lows)):
        prev_swing_low = swing_lows[i - 1]
        current_swing_low = swing_lows[i]

        # Lower low = bearish BOS
        if current_swing_low.price < prev_swing_low.price:
            # Find the candle that actually broke the level
            break_index = current_swing_low.index
            for j in range(prev_swing_low.index + 1, current_swing_low.index + 1):
                if candles_list[j].low < prev_swing_low.price:
                    break_index = j
                    break

            bos_events.append(StructureBreak(
                index=break_index,
                type='BOS',
                direction='bearish',
                broken_level=prev_swing_low.price,
                timestamp=candles_list[break_index].open_time
            ))

    # Sort by index to maintain chronological order
    bos_events.sort(key=lambda x: x.index)
    return bos_events


def detect_choch(
    candles: Union[List[Candle], deque[Candle]],
    swing_lookback: int = 5
) -> List[StructureBreak]:
    """
    Detect Change of Character (CHoCH) events.

    CHoCH occurs when price breaks structure in the OPPOSITE direction of the trend,
    signaling a potential trend reversal.

    Args:
        candles: List or deque of Candle objects
        swing_lookback: Number of bars for swing point identification

    Returns:
        List of StructureBreak objects for CHoCH events
    """
    choch_events: List[StructureBreak] = []
    candles_list = list(candles)

    if len(candles_list) < swing_lookback * 2 + 2:
        return choch_events

    # Identify swing points
    swing_highs = identify_swing_highs(candles_list, swing_lookback, swing_lookback)
    swing_lows = identify_swing_lows(candles_list, swing_lookback, swing_lookback)

    if not swing_highs or not swing_lows:
        return choch_events

    # Detect bullish CHoCH: in downtrend, price breaks above recent swing high (reversal)
    # First identify if we're in downtrend by checking lower highs
    for i in range(1, len(swing_highs)):
        prev_swing_high = swing_highs[i - 1]

        # Check if there are subsequent lows that are lower (downtrend)
        lows_after_high = [sl for sl in swing_lows if sl.index > prev_swing_high.index]
        if not lows_after_high:
            continue

        # In downtrend, breaking above previous swing high = bullish CHoCH
        for j in range(prev_swing_high.index + 1, len(candles_list)):
            if candles_list[j].high > prev_swing_high.price:
                # Verify we had lower lows before this break (confirming downtrend)
                recent_lows = [sl for sl in swing_lows if prev_swing_high.index < sl.index < j]
                if recent_lows and any(sl.price < prev_swing_high.price for sl in recent_lows):
                    choch_events.append(StructureBreak(
                        index=j,
                        type='CHoCH',
                        direction='bullish',
                        broken_level=prev_swing_high.price,
                        timestamp=candles_list[j].open_time
                    ))
                    break

    # Detect bearish CHoCH: in uptrend, price breaks below recent swing low (reversal)
    for i in range(1, len(swing_lows)):
        prev_swing_low = swing_lows[i - 1]

        # Check if there are subsequent highs that are higher (uptrend)
        highs_after_low = [sh for sh in swing_highs if sh.index > prev_swing_low.index]
        if not highs_after_low:
            continue

        # In uptrend, breaking below previous swing low = bearish CHoCH
        for j in range(prev_swing_low.index + 1, len(candles_list)):
            if candles_list[j].low < prev_swing_low.price:
                # Verify we had higher highs before this break (confirming uptrend)
                recent_highs = [sh for sh in swing_highs if prev_swing_low.index < sh.index < j]
                if recent_highs and any(sh.price > prev_swing_low.price for sh in recent_highs):
                    choch_events.append(StructureBreak(
                        index=j,
                        type='CHoCH',
                        direction='bearish',
                        broken_level=prev_swing_low.price,
                        timestamp=candles_list[j].open_time
                    ))
                    break

    # Sort by index to maintain chronological order
    choch_events.sort(key=lambda x: x.index)
    return choch_events


def get_current_trend(
    candles: Union[List[Candle], deque[Candle]],
    swing_lookback: int = 5,
    min_swings: int = 2
) -> Optional[str]:
    """
    Determine current market trend based on swing structure.

    Args:
        candles: List or deque of Candle objects
        swing_lookback: Number of bars for swing point identification
        min_swings: Minimum number of swing points needed for trend determination

    Returns:
        'bullish', 'bearish', or None if trend is unclear
    """
    candles_list = list(candles)

    if len(candles_list) < swing_lookback * 2 + 2:
        return None

    swing_highs = identify_swing_highs(candles_list, swing_lookback, swing_lookback)
    swing_lows = identify_swing_lows(candles_list, swing_lookback, swing_lookback)

    if len(swing_highs) < min_swings or len(swing_lows) < min_swings:
        return None

    # Check for higher highs and higher lows (bullish trend)
    recent_highs = swing_highs[-min_swings:]
    recent_lows = swing_lows[-min_swings:]

    higher_highs = all(
        recent_highs[i].price > recent_highs[i-1].price
        for i in range(1, len(recent_highs))
    )
    higher_lows = all(
        recent_lows[i].price > recent_lows[i-1].price
        for i in range(1, len(recent_lows))
    )

    if higher_highs and higher_lows:
        return 'bullish'

    # Check for lower highs and lower lows (bearish trend)
    lower_highs = all(
        recent_highs[i].price < recent_highs[i-1].price
        for i in range(1, len(recent_highs))
    )
    lower_lows = all(
        recent_lows[i].price < recent_lows[i-1].price
        for i in range(1, len(recent_lows))
    )

    if lower_highs and lower_lows:
        return 'bearish'

    return None  # Consolidation or unclear trend
