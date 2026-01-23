"""
Unit tests for ICT Kill Zones
"""

from datetime import datetime

import pytz

from src.detectors.ict_killzones import (
    LONDON_KILLZONE_START,
    NY_AM_KILLZONE_START,
    NY_PM_KILLZONE_START,
    get_active_killzone,
    get_next_killzone,
    is_killzone_active,
    is_london_killzone,
    is_newyork_killzone,
)


class TestLondonKillzone:
    """Test London kill zone detection"""

    def test_london_killzone_active(self):
        """Test London kill zone is detected during active time."""
        # 8:30 UTC = 3:30 AM EST (middle of London kill zone)
        timestamp = datetime(2025, 1, 15, 8, 30, 0, tzinfo=pytz.UTC)

        assert is_london_killzone(timestamp)
        assert get_active_killzone(timestamp) == "london"

    def test_london_killzone_start_boundary(self):
        """Test London kill zone start time (inclusive)."""
        # Exactly 8:00 UTC = 3:00 AM EST (start)
        timestamp = datetime(2025, 1, 15, 8, 0, 0, tzinfo=pytz.UTC)

        assert is_london_killzone(timestamp)

    def test_london_killzone_end_boundary(self):
        """Test London kill zone end time (exclusive)."""
        # Exactly 9:00 UTC = 4:00 AM EST (end)
        timestamp = datetime(2025, 1, 15, 9, 0, 0, tzinfo=pytz.UTC)

        assert not is_london_killzone(timestamp)

    def test_london_killzone_before(self):
        """Test before London kill zone."""
        # 7:30 UTC = 2:30 AM EST (before London)
        timestamp = datetime(2025, 1, 15, 7, 30, 0, tzinfo=pytz.UTC)

        assert not is_london_killzone(timestamp)

    def test_london_killzone_after(self):
        """Test after London kill zone."""
        # 9:30 UTC = 4:30 AM EST (after London)
        timestamp = datetime(2025, 1, 15, 9, 30, 0, tzinfo=pytz.UTC)

        assert not is_london_killzone(timestamp)


class TestNewYorkKillzone:
    """Test New York kill zone detection"""

    def test_ny_am_killzone_active(self):
        """Test NY AM kill zone is detected."""
        # 15:30 UTC = 10:30 AM EST (middle of NY AM)
        timestamp = datetime(2025, 1, 15, 15, 30, 0, tzinfo=pytz.UTC)

        assert is_newyork_killzone(timestamp)
        assert get_active_killzone(timestamp) == "ny_am"

    def test_ny_pm_killzone_active(self):
        """Test NY PM kill zone is detected."""
        # 19:30 UTC = 2:30 PM EST (middle of NY PM)
        timestamp = datetime(2025, 1, 15, 19, 30, 0, tzinfo=pytz.UTC)

        assert is_newyork_killzone(timestamp)
        assert get_active_killzone(timestamp) == "ny_pm"

    def test_ny_am_start_boundary(self):
        """Test NY AM kill zone start time (inclusive)."""
        # Exactly 15:00 UTC = 10:00 AM EST (start)
        timestamp = datetime(2025, 1, 15, 15, 0, 0, tzinfo=pytz.UTC)

        assert is_newyork_killzone(timestamp)

    def test_ny_am_end_boundary(self):
        """Test NY AM kill zone end time (exclusive)."""
        # Exactly 16:00 UTC = 11:00 AM EST (end)
        timestamp = datetime(2025, 1, 15, 16, 0, 0, tzinfo=pytz.UTC)

        assert not is_newyork_killzone(timestamp)

    def test_ny_pm_start_boundary(self):
        """Test NY PM kill zone start time (inclusive)."""
        # Exactly 19:00 UTC = 2:00 PM EST (start)
        timestamp = datetime(2025, 1, 15, 19, 0, 0, tzinfo=pytz.UTC)

        assert is_newyork_killzone(timestamp)

    def test_ny_pm_end_boundary(self):
        """Test NY PM kill zone end time (exclusive)."""
        # Exactly 20:00 UTC = 3:00 PM EST (end)
        timestamp = datetime(2025, 1, 15, 20, 0, 0, tzinfo=pytz.UTC)

        assert not is_newyork_killzone(timestamp)

    def test_between_ny_killzones(self):
        """Test time between NY AM and NY PM kill zones."""
        # 17:00 UTC = 12:00 PM EST (between NY AM and PM)
        timestamp = datetime(2025, 1, 15, 17, 0, 0, tzinfo=pytz.UTC)

        assert not is_newyork_killzone(timestamp)


class TestGetActiveKillzone:
    """Test get_active_killzone function"""

    def test_london_active(self):
        """Test London kill zone is returned when active."""
        timestamp = datetime(2025, 1, 15, 8, 30, 0, tzinfo=pytz.UTC)

        assert get_active_killzone(timestamp) == "london"

    def test_ny_am_active(self):
        """Test NY AM kill zone is returned when active."""
        timestamp = datetime(2025, 1, 15, 15, 30, 0, tzinfo=pytz.UTC)

        assert get_active_killzone(timestamp) == "ny_am"

    def test_ny_pm_active(self):
        """Test NY PM kill zone is returned when active."""
        timestamp = datetime(2025, 1, 15, 19, 30, 0, tzinfo=pytz.UTC)

        assert get_active_killzone(timestamp) == "ny_pm"

    def test_no_killzone_active(self):
        """Test None is returned when no kill zone is active."""
        # 12:00 UTC = 7:00 AM EST (between London and NY AM)
        timestamp = datetime(2025, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)

        assert get_active_killzone(timestamp) is None


class TestIsKillzoneActive:
    """Test is_killzone_active function"""

    def test_killzone_active(self):
        """Test is_killzone_active returns True during kill zones."""
        # London kill zone
        timestamp_london = datetime(2025, 1, 15, 8, 30, 0, tzinfo=pytz.UTC)
        assert is_killzone_active(timestamp_london)

        # NY AM kill zone
        timestamp_ny_am = datetime(2025, 1, 15, 15, 30, 0, tzinfo=pytz.UTC)
        assert is_killzone_active(timestamp_ny_am)

        # NY PM kill zone
        timestamp_ny_pm = datetime(2025, 1, 15, 19, 30, 0, tzinfo=pytz.UTC)
        assert is_killzone_active(timestamp_ny_pm)

    def test_killzone_inactive(self):
        """Test is_killzone_active returns False outside kill zones."""
        timestamp = datetime(2025, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)

        assert not is_killzone_active(timestamp)


class TestGetNextKillzone:
    """Test get_next_killzone function"""

    def test_next_killzone_is_london(self):
        """Test next kill zone is London when before 8:00 UTC."""
        # 6:00 UTC = 1:00 AM EST (before London)
        timestamp = datetime(2025, 1, 15, 6, 0, 0, tzinfo=pytz.UTC)

        next_kz, next_time = get_next_killzone(timestamp)

        assert next_kz == "london"
        assert next_time.time() == LONDON_KILLZONE_START
        assert next_time.date() == timestamp.date()

    def test_next_killzone_is_ny_am(self):
        """Test next kill zone is NY AM when between London and NY AM."""
        # 12:00 UTC = 7:00 AM EST (after London, before NY AM)
        timestamp = datetime(2025, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)

        next_kz, next_time = get_next_killzone(timestamp)

        assert next_kz == "ny_am"
        assert next_time.time() == NY_AM_KILLZONE_START

    def test_next_killzone_is_ny_pm(self):
        """Test next kill zone is NY PM when between NY AM and NY PM."""
        # 17:00 UTC = 12:00 PM EST (after NY AM, before NY PM)
        timestamp = datetime(2025, 1, 15, 17, 0, 0, tzinfo=pytz.UTC)

        next_kz, next_time = get_next_killzone(timestamp)

        assert next_kz == "ny_pm"
        assert next_time.time() == NY_PM_KILLZONE_START

    def test_no_next_killzone_today(self):
        """Test no next kill zone after NY PM ends."""
        # 21:00 UTC = 4:00 PM EST (after NY PM)
        timestamp = datetime(2025, 1, 15, 21, 0, 0, tzinfo=pytz.UTC)

        next_kz, next_time = get_next_killzone(timestamp)

        assert next_kz is None
        assert next_time is None


class TestTimezoneHandling:
    """Test timezone conversion handling"""

    def test_est_timezone_conversion(self):
        """Test EST timezone is correctly converted to UTC."""
        est = pytz.timezone("US/Eastern")

        # 3:30 AM EST = 8:30 UTC (London kill zone)
        timestamp_est = est.localize(datetime(2025, 1, 15, 3, 30, 0))

        assert is_london_killzone(timestamp_est)
        assert get_active_killzone(timestamp_est) == "london"

    def test_naive_datetime_assumes_utc(self):
        """Test naive datetime is assumed to be UTC."""
        # Naive datetime at 8:30 (assumed UTC)
        timestamp_naive = datetime(2025, 1, 15, 8, 30, 0)

        assert is_london_killzone(timestamp_naive)

    def test_different_timezone_conversion(self):
        """Test non-EST timezone conversion."""
        tokyo = pytz.timezone("Asia/Tokyo")

        # 5:30 PM JST = 8:30 UTC (London kill zone)
        timestamp_jst = tokyo.localize(datetime(2025, 1, 15, 17, 30, 0))

        assert is_london_killzone(timestamp_jst)


class TestKillzoneWorkflow:
    """Test complete kill zone workflow"""

    def test_daily_killzone_sequence(self):
        """Test sequence of kill zones throughout the day."""
        # Test each kill zone in chronological order

        # Before any kill zone (6:00 UTC)
        early = datetime(2025, 1, 15, 6, 0, 0, tzinfo=pytz.UTC)
        assert not is_killzone_active(early)
        assert get_next_killzone(early)[0] == "london"

        # London kill zone (8:30 UTC)
        london = datetime(2025, 1, 15, 8, 30, 0, tzinfo=pytz.UTC)
        assert get_active_killzone(london) == "london"

        # Between London and NY AM (12:00 UTC)
        between1 = datetime(2025, 1, 15, 12, 0, 0, tzinfo=pytz.UTC)
        assert not is_killzone_active(between1)
        assert get_next_killzone(between1)[0] == "ny_am"

        # NY AM kill zone (15:30 UTC)
        ny_am = datetime(2025, 1, 15, 15, 30, 0, tzinfo=pytz.UTC)
        assert get_active_killzone(ny_am) == "ny_am"

        # Between NY AM and NY PM (17:00 UTC)
        between2 = datetime(2025, 1, 15, 17, 0, 0, tzinfo=pytz.UTC)
        assert not is_killzone_active(between2)
        assert get_next_killzone(between2)[0] == "ny_pm"

        # NY PM kill zone (19:30 UTC)
        ny_pm = datetime(2025, 1, 15, 19, 30, 0, tzinfo=pytz.UTC)
        assert get_active_killzone(ny_pm) == "ny_pm"

        # After all kill zones (21:00 UTC)
        late = datetime(2025, 1, 15, 21, 0, 0, tzinfo=pytz.UTC)
        assert not is_killzone_active(late)
        assert get_next_killzone(late)[0] is None

    def test_killzone_filtering(self):
        """Test using kill zones to filter trading times."""
        # Simulate checking multiple timestamps
        timestamps = [datetime(2025, 1, 15, h, 30, 0, tzinfo=pytz.UTC) for h in range(24)]

        # Filter for kill zone times only
        killzone_times = [ts for ts in timestamps if is_killzone_active(ts)]

        # Should have 3 kill zone hours (8, 15, 19)
        assert len(killzone_times) == 3

        # Verify they match expected kill zones
        assert get_active_killzone(killzone_times[0]) == "london"
        assert get_active_killzone(killzone_times[1]) == "ny_am"
        assert get_active_killzone(killzone_times[2]) == "ny_pm"
