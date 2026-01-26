"""Tests for ZoneBasedStopLoss determiner."""

import pytest
from src.pricing.base import PriceContext
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss


class TestZoneBasedStopLoss:
    """Test cases for ZoneBasedStopLoss."""

    def test_long_with_fvg_zone(self):
        """Test LONG SL using FVG zone."""
        sl = ZoneBasedStopLoss()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(49000.0, 49500.0),  # Zone below entry
        )
        result = sl.calculate_stop_loss(context)
        expected = 49000.0 - (50000.0 * 0.001)  # zone_low - buffer
        assert result == expected

    def test_short_with_fvg_zone(self):
        """Test SHORT SL using FVG zone."""
        sl = ZoneBasedStopLoss()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
            fvg_zone=(50500.0, 51000.0),  # Zone above entry
        )
        result = sl.calculate_stop_loss(context)
        expected = 51000.0 + (50000.0 * 0.001)  # zone_high + buffer
        assert result == expected

    def test_long_with_ob_zone_fallback(self):
        """Test LONG SL using OB zone when no FVG."""
        sl = ZoneBasedStopLoss()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            ob_zone=(48500.0, 49000.0),  # OB zone below entry
        )
        result = sl.calculate_stop_loss(context)
        expected = 48500.0 - (50000.0 * 0.001)  # zone_low - buffer
        assert result == expected

    def test_fvg_takes_priority_over_ob(self):
        """Test FVG zone takes priority over OB zone."""
        sl = ZoneBasedStopLoss()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(49000.0, 49500.0),  # FVG
            ob_zone=(48000.0, 48500.0),   # OB (should be ignored)
        )
        result = sl.calculate_stop_loss(context)
        expected = 49000.0 - (50000.0 * 0.001)  # Uses FVG zone_low
        assert result == expected

    def test_percentage_fallback_when_no_zones(self):
        """Test fallback to percentage when no zones provided."""
        sl = ZoneBasedStopLoss(fallback_percent=0.01)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        result = sl.calculate_stop_loss(context)
        assert result == 49500.0  # 50000 * 0.99 (1% fallback)

    def test_long_fallback_when_zone_above_entry(self):
        """Test LONG SL fallback when zone would result in SL above entry."""
        sl = ZoneBasedStopLoss(fallback_percent=0.01)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(51000.0, 52000.0),  # Zone above entry (invalid for LONG)
        )
        result = sl.calculate_stop_loss(context)
        assert result == 49500.0  # Fallback: 50000 * 0.99

    def test_short_fallback_when_zone_below_entry(self):
        """Test SHORT SL fallback when zone would result in SL below entry."""
        sl = ZoneBasedStopLoss(fallback_percent=0.01)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
            fvg_zone=(48000.0, 49000.0),  # Zone below entry (invalid for SHORT)
        )
        result = sl.calculate_stop_loss(context)
        assert result == 50500.0  # Fallback: 50000 * 1.01

    def test_custom_buffer_percent(self):
        """Test custom buffer percentage."""
        sl = ZoneBasedStopLoss(buffer_percent=0.002)  # 0.2%
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(49000.0, 49500.0),
        )
        result = sl.calculate_stop_loss(context)
        expected = 49000.0 - (50000.0 * 0.002)  # 0.2% buffer
        assert result == expected

    def test_immutability(self):
        """Test that ZoneBasedStopLoss is immutable."""
        sl = ZoneBasedStopLoss()
        with pytest.raises(AttributeError):
            sl.buffer_percent = 0.005
