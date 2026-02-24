"""
ICT Kill Zones
Identifies optimal trading times based on ICT methodology
"""

from datetime import datetime, time
from typing import Literal, Optional

import pytz

# Kill Zone time ranges in UTC
LONDON_KILLZONE_START = time(8, 0)  # 8:00 UTC (3:00 AM EST)
LONDON_KILLZONE_END = time(9, 0)  # 9:00 UTC (4:00 AM EST)

NY_AM_KILLZONE_START = time(15, 0)  # 15:00 UTC (10:00 AM EST)
NY_AM_KILLZONE_END = time(16, 0)  # 16:00 UTC (11:00 AM EST)

NY_PM_KILLZONE_START = time(19, 0)  # 19:00 UTC (2:00 PM EST)
NY_PM_KILLZONE_END = time(20, 0)  # 20:00 UTC (3:00 PM EST)


def is_london_killzone(timestamp: datetime) -> bool:
    """
    Check if timestamp is within London kill zone (3:00-4:00 AM EST / 8:00-9:00 UTC).

    The London kill zone represents the London session open, a period of high
    liquidity and volatility.

    Args:
        timestamp: Datetime to check (should be timezone-aware)

    Returns:
        True if timestamp is in London kill zone
    """
    # Convert to UTC if timezone-aware, otherwise assume UTC
    if timestamp.tzinfo is not None:
        utc_time = timestamp.astimezone(pytz.UTC)
    else:
        utc_time = timestamp

    current_time = utc_time.time()

    return LONDON_KILLZONE_START <= current_time < LONDON_KILLZONE_END


def is_newyork_killzone(timestamp: datetime) -> bool:
    """
    Check if timestamp is within New York kill zones.

    NY has two kill zones:
    - NY AM: 10:00-11:00 AM EST (15:00-16:00 UTC)
    - NY PM: 2:00-3:00 PM EST (19:00-20:00 UTC)

    These periods represent the New York session's most active trading times.

    Args:
        timestamp: Datetime to check (should be timezone-aware)

    Returns:
        True if timestamp is in either NY kill zone
    """
    # Convert to UTC if timezone-aware, otherwise assume UTC
    if timestamp.tzinfo is not None:
        utc_time = timestamp.astimezone(pytz.UTC)
    else:
        utc_time = timestamp

    current_time = utc_time.time()

    # Check NY AM kill zone
    ny_am = NY_AM_KILLZONE_START <= current_time < NY_AM_KILLZONE_END

    # Check NY PM kill zone
    ny_pm = NY_PM_KILLZONE_START <= current_time < NY_PM_KILLZONE_END

    return ny_am or ny_pm


def get_active_killzone(timestamp: datetime) -> Optional[Literal["london", "ny_am", "ny_pm"]]:
    """
    Get the currently active kill zone, if any.

    Args:
        timestamp: Datetime to check (should be timezone-aware)

    Returns:
        'london', 'ny_am', 'ny_pm', or None if no kill zone is active
    """
    # Convert to UTC if timezone-aware, otherwise assume UTC
    if timestamp.tzinfo is not None:
        utc_time = timestamp.astimezone(pytz.UTC)
    else:
        utc_time = timestamp

    current_time = utc_time.time()

    # Check London kill zone
    if LONDON_KILLZONE_START <= current_time < LONDON_KILLZONE_END:
        return "london"

    # Check NY AM kill zone
    if NY_AM_KILLZONE_START <= current_time < NY_AM_KILLZONE_END:
        return "ny_am"

    # Check NY PM kill zone
    if NY_PM_KILLZONE_START <= current_time < NY_PM_KILLZONE_END:
        return "ny_pm"

    return None


def is_killzone_active(timestamp: datetime) -> bool:
    """
    Check if any kill zone is currently active.

    Args:
        timestamp: Datetime to check (should be timezone-aware)

    Returns:
        True if any kill zone is active
    """
    return get_active_killzone(timestamp) is not None


def get_next_killzone(
    timestamp: datetime,
) -> tuple[Optional[Literal["london", "ny_am", "ny_pm"]], Optional[datetime]]:
    """
    Get the next upcoming kill zone and its start time.

    Args:
        timestamp: Current datetime (should be timezone-aware)

    Returns:
        Tuple of (kill_zone_name, start_datetime) or (None, None) if none today
    """
    # Convert to UTC if timezone-aware, otherwise assume UTC
    if timestamp.tzinfo is not None:
        utc_time = timestamp.astimezone(pytz.UTC)
    else:
        utc_time = pytz.UTC.localize(timestamp)

    current_time = utc_time.time()
    current_date = utc_time.date()

    # Check if London kill zone is upcoming
    if current_time < LONDON_KILLZONE_START:
        london_start = datetime.combine(current_date, LONDON_KILLZONE_START)
        london_start = pytz.UTC.localize(london_start)
        return ("london", london_start)

    # Check if NY AM kill zone is upcoming
    if current_time < NY_AM_KILLZONE_START:
        ny_am_start = datetime.combine(current_date, NY_AM_KILLZONE_START)
        ny_am_start = pytz.UTC.localize(ny_am_start)
        return ("ny_am", ny_am_start)

    # Check if NY PM kill zone is upcoming
    if current_time < NY_PM_KILLZONE_START:
        ny_pm_start = datetime.combine(current_date, NY_PM_KILLZONE_START)
        ny_pm_start = pytz.UTC.localize(ny_pm_start)
        return ("ny_pm", ny_pm_start)

    # All kill zones have passed for today
    return (None, None)
