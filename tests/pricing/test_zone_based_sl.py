"""Tests for ZoneBasedStopLoss determiner."""

import pytest
from src.pricing.base import PriceContext
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss


class TestZoneBasedStopLoss:
    """Test cases for ZoneBasedStopLoss."""

    def test_long_with_fvg_zone(self):
        """Test LONG SL using FVG zone (within max_sl_percent)."""
        # Use high max_sl_percent to test pure zone-based logic
        sl = ZoneBasedStopLoss(max_sl_percent=0.10)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(49000.0, 49500.0),  # Zone below entry (~2%)
        )
        result = sl.calculate_stop_loss(context)
        expected = 49000.0 - (50000.0 * 0.001)  # zone_low - buffer
        assert result == expected

    def test_short_with_fvg_zone(self):
        """Test SHORT SL using FVG zone (within max_sl_percent)."""
        # Use high max_sl_percent to test pure zone-based logic
        sl = ZoneBasedStopLoss(max_sl_percent=0.10)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
            fvg_zone=(50500.0, 51000.0),  # Zone above entry (~2%)
        )
        result = sl.calculate_stop_loss(context)
        expected = 51000.0 + (50000.0 * 0.001)  # zone_high + buffer
        assert result == expected

    def test_long_with_ob_zone_fallback(self):
        """Test LONG SL using OB zone when no FVG (within max_sl_percent)."""
        # Use high max_sl_percent to test pure zone-based logic
        sl = ZoneBasedStopLoss(max_sl_percent=0.10)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            ob_zone=(48500.0, 49000.0),  # OB zone below entry (~3%)
        )
        result = sl.calculate_stop_loss(context)
        expected = 48500.0 - (50000.0 * 0.001)  # zone_low - buffer
        assert result == expected

    def test_fvg_takes_priority_over_ob(self):
        """Test FVG zone takes priority over OB zone."""
        # Use high max_sl_percent to test pure zone-based logic
        sl = ZoneBasedStopLoss(max_sl_percent=0.10)
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
        """Test custom buffer percentage (within max_sl_percent)."""
        # Use high max_sl_percent to test pure zone-based logic
        sl = ZoneBasedStopLoss(buffer_percent=0.002, max_sl_percent=0.10)
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


class TestMaxSlPercentCap:
    """Test cases for max_sl_percent capping feature (Issue #64)."""

    def test_long_sl_capped_when_zone_too_far(self):
        """Test LONG SL is capped when zone-based SL exceeds max distance."""
        # Zone at 5% below entry (exceeds default 2% max)
        sl = ZoneBasedStopLoss(max_sl_percent=0.02)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(47000.0, 47500.0),  # 5%+ below entry
        )
        result = sl.calculate_stop_loss(context)
        # Should be capped to 2% below entry
        expected = 50000.0 * (1 - 0.02)  # 49000.0
        assert result == expected

    def test_short_sl_capped_when_zone_too_far(self):
        """Test SHORT SL is capped when zone-based SL exceeds max distance."""
        # Zone at 5% above entry (exceeds default 2% max)
        sl = ZoneBasedStopLoss(max_sl_percent=0.02)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
            fvg_zone=(52500.0, 53000.0),  # 5%+ above entry
        )
        result = sl.calculate_stop_loss(context)
        # Should be capped to 2% above entry
        expected = 50000.0 * (1 + 0.02)  # 51000.0
        assert result == expected

    def test_long_sl_not_capped_when_within_limit(self):
        """Test LONG SL is NOT capped when within max distance."""
        # Zone at 1% below entry (within default 2% max)
        sl = ZoneBasedStopLoss(max_sl_percent=0.02)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(49400.0, 49600.0),  # ~1% below entry
        )
        result = sl.calculate_stop_loss(context)
        # Should NOT be capped, use zone-based SL
        expected = 49400.0 - (50000.0 * 0.001)  # zone_low - buffer
        assert result == expected

    def test_short_sl_not_capped_when_within_limit(self):
        """Test SHORT SL is NOT capped when within max distance."""
        # Zone at 1% above entry (within default 2% max)
        sl = ZoneBasedStopLoss(max_sl_percent=0.02)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
            fvg_zone=(50400.0, 50600.0),  # ~1% above entry
        )
        result = sl.calculate_stop_loss(context)
        # Should NOT be capped, use zone-based SL
        expected = 50600.0 + (50000.0 * 0.001)  # zone_high + buffer
        assert result == expected

    def test_custom_max_sl_percent(self):
        """Test custom max_sl_percent value."""
        # Zone at 3% below entry, with 1.5% max cap
        sl = ZoneBasedStopLoss(max_sl_percent=0.015)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(48000.0, 48500.0),  # 3%+ below entry
        )
        result = sl.calculate_stop_loss(context)
        # Should be capped to 1.5% below entry
        expected = 50000.0 * (1 - 0.015)  # 49250.0
        assert result == expected

    def test_default_max_sl_percent(self):
        """Test default max_sl_percent is 2%."""
        sl = ZoneBasedStopLoss()
        assert sl.max_sl_percent == 0.02

    def test_rr_ratio_improvement_with_capped_sl(self):
        """
        Test that capped SL improves RR ratio.

        Scenario: Zone at 5% below entry, TP at 4% above entry
        Without cap: RR = 4% / 5% = 0.8 (rejected by min_rr_ratio 1.5)
        With 2% cap: RR = 4% / 2% = 2.0 (accepted)
        """
        entry = 50000.0
        tp = 52000.0  # 4% above entry

        # Without cap (or high cap), zone-based SL would be ~5% away
        sl_uncapped = ZoneBasedStopLoss(max_sl_percent=0.10)  # Effectively no cap
        context = PriceContext.from_strategy(
            entry_price=entry,
            side="LONG",
            symbol="BTCUSDT",
            fvg_zone=(47400.0, 47500.0),  # ~5% below entry
        )
        sl_price_uncapped = sl_uncapped.calculate_stop_loss(context)
        rr_uncapped = (tp - entry) / (entry - sl_price_uncapped)

        # With 2% cap
        sl_capped = ZoneBasedStopLoss(max_sl_percent=0.02)
        sl_price_capped = sl_capped.calculate_stop_loss(context)
        rr_capped = (tp - entry) / (entry - sl_price_capped)

        # Verify capping improves RR
        assert rr_capped > rr_uncapped
        assert rr_capped >= 2.0  # Now acceptable with min_rr_ratio 1.5
