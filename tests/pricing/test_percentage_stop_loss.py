"""Tests for PercentageStopLoss determiner."""

import pytest
from src.pricing.base import PriceContext
from src.pricing.stop_loss.percentage import PercentageStopLoss


class TestPercentageStopLoss:
    """Test cases for PercentageStopLoss."""

    def test_long_stop_loss_default(self):
        """Test LONG SL with default 1% percent."""
        sl = PercentageStopLoss()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        result = sl.calculate_stop_loss(context)
        assert result == 49500.0  # 50000 * 0.99

    def test_short_stop_loss_default(self):
        """Test SHORT SL with default 1% percent."""
        sl = PercentageStopLoss()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        result = sl.calculate_stop_loss(context)
        assert result == 50500.0  # 50000 * 1.01

    def test_long_stop_loss_custom_percent(self):
        """Test LONG SL with custom 2% percent."""
        sl = PercentageStopLoss(stop_loss_percent=0.02)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        result = sl.calculate_stop_loss(context)
        assert result == 49000.0  # 50000 * 0.98

    def test_short_stop_loss_custom_percent(self):
        """Test SHORT SL with custom 2% percent."""
        sl = PercentageStopLoss(stop_loss_percent=0.02)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        result = sl.calculate_stop_loss(context)
        assert result == 51000.0  # 50000 * 1.02

    def test_immutability(self):
        """Test that PercentageStopLoss is immutable."""
        sl = PercentageStopLoss(stop_loss_percent=0.01)
        with pytest.raises(AttributeError):
            sl.stop_loss_percent = 0.02
