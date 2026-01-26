"""Tests for DisplacementTakeProfit determiner."""

import pytest
from src.pricing.base import PriceContext
from src.pricing.take_profit.displacement import DisplacementTakeProfit


class TestDisplacementTakeProfit:
    """Test cases for DisplacementTakeProfit."""

    def test_long_with_displacement(self):
        """Test LONG TP using displacement size."""
        tp = DisplacementTakeProfit(risk_reward_ratio=2.0)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            displacement_size=500.0,  # $500 displacement
        )
        result = tp.calculate_take_profit(context, stop_loss=49500.0)
        assert result == 51000.0  # 50000 + (500 * 2)

    def test_short_with_displacement(self):
        """Test SHORT TP using displacement size."""
        tp = DisplacementTakeProfit(risk_reward_ratio=2.0)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
            displacement_size=500.0,  # $500 displacement
        )
        result = tp.calculate_take_profit(context, stop_loss=50500.0)
        assert result == 49000.0  # 50000 - (500 * 2)

    def test_long_with_custom_rr_ratio(self):
        """Test LONG TP with custom 3.0 risk-reward ratio."""
        tp = DisplacementTakeProfit(risk_reward_ratio=3.0)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            displacement_size=500.0,
        )
        result = tp.calculate_take_profit(context, stop_loss=49500.0)
        assert result == 51500.0  # 50000 + (500 * 3)

    def test_fallback_when_no_displacement_long(self):
        """Test LONG TP fallback when no displacement provided."""
        tp = DisplacementTakeProfit(
            risk_reward_ratio=2.0,
            fallback_risk_percent=0.02,  # 2%
        )
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        result = tp.calculate_take_profit(context, stop_loss=49000.0)
        # risk = 50000 * 0.02 = 1000, reward = 1000 * 2 = 2000
        assert result == 52000.0  # 50000 + 2000

    def test_fallback_when_no_displacement_short(self):
        """Test SHORT TP fallback when no displacement provided."""
        tp = DisplacementTakeProfit(
            risk_reward_ratio=2.0,
            fallback_risk_percent=0.02,  # 2%
        )
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        result = tp.calculate_take_profit(context, stop_loss=51000.0)
        # risk = 50000 * 0.02 = 1000, reward = 1000 * 2 = 2000
        assert result == 48000.0  # 50000 - 2000

    def test_fallback_when_displacement_is_zero(self):
        """Test fallback when displacement is zero."""
        tp = DisplacementTakeProfit(
            risk_reward_ratio=2.0,
            fallback_risk_percent=0.01,  # 1%
        )
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
            displacement_size=0.0,  # Zero displacement
        )
        result = tp.calculate_take_profit(context, stop_loss=49500.0)
        # Fallback: risk = 50000 * 0.01 = 500, reward = 500 * 2 = 1000
        assert result == 51000.0  # 50000 + 1000

    def test_long_safety_fallback(self):
        """Test LONG TP safety fallback when calculation fails."""
        tp = DisplacementTakeProfit(
            risk_reward_ratio=0.0,  # Would result in TP = entry
            fallback_risk_percent=0.0,
        )
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        result = tp.calculate_take_profit(context, stop_loss=49500.0)
        assert result == 51000.0  # Fallback: 50000 * 1.02

    def test_short_safety_fallback(self):
        """Test SHORT TP safety fallback when calculation fails."""
        tp = DisplacementTakeProfit(
            risk_reward_ratio=0.0,  # Would result in TP = entry
            fallback_risk_percent=0.0,
        )
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        result = tp.calculate_take_profit(context, stop_loss=50500.0)
        assert result == 49000.0  # Fallback: 50000 * 0.98

    def test_immutability(self):
        """Test that DisplacementTakeProfit is immutable."""
        tp = DisplacementTakeProfit()
        with pytest.raises(AttributeError):
            tp.risk_reward_ratio = 5.0
