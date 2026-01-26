"""Tests for RiskRewardTakeProfit determiner."""

import pytest
from src.pricing.base import PriceContext
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit


class TestRiskRewardTakeProfit:
    """Test cases for RiskRewardTakeProfit."""

    def test_long_take_profit_default_rr(self):
        """Test LONG TP with default 2.0 risk-reward ratio."""
        tp = RiskRewardTakeProfit()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        stop_loss = 49500.0  # 500 USD risk
        result = tp.calculate_take_profit(context, stop_loss)
        assert result == 51000.0  # 50000 + (500 * 2)

    def test_short_take_profit_default_rr(self):
        """Test SHORT TP with default 2.0 risk-reward ratio."""
        tp = RiskRewardTakeProfit()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        stop_loss = 50500.0  # 500 USD risk
        result = tp.calculate_take_profit(context, stop_loss)
        assert result == 49000.0  # 50000 - (500 * 2)

    def test_long_take_profit_custom_rr(self):
        """Test LONG TP with custom 3.0 risk-reward ratio."""
        tp = RiskRewardTakeProfit(risk_reward_ratio=3.0)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        stop_loss = 49500.0  # 500 USD risk
        result = tp.calculate_take_profit(context, stop_loss)
        assert result == 51500.0  # 50000 + (500 * 3)

    def test_short_take_profit_custom_rr(self):
        """Test SHORT TP with custom 3.0 risk-reward ratio."""
        tp = RiskRewardTakeProfit(risk_reward_ratio=3.0)
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        stop_loss = 50500.0  # 500 USD risk
        result = tp.calculate_take_profit(context, stop_loss)
        assert result == 48500.0  # 50000 - (500 * 3)

    def test_long_fallback_when_tp_not_above_entry(self):
        """Test LONG TP fallback when SL distance is zero."""
        tp = RiskRewardTakeProfit()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="LONG",
            symbol="BTCUSDT",
        )
        stop_loss = 50000.0  # Same as entry, zero distance
        result = tp.calculate_take_profit(context, stop_loss)
        assert result == 51000.0  # Fallback: 50000 * 1.02

    def test_short_fallback_when_tp_not_below_entry(self):
        """Test SHORT TP fallback when SL distance is zero."""
        tp = RiskRewardTakeProfit()
        context = PriceContext.from_strategy(
            entry_price=50000.0,
            side="SHORT",
            symbol="BTCUSDT",
        )
        stop_loss = 50000.0  # Same as entry, zero distance
        result = tp.calculate_take_profit(context, stop_loss)
        assert result == 49000.0  # Fallback: 50000 * 0.98

    def test_immutability(self):
        """Test that RiskRewardTakeProfit is immutable."""
        tp = RiskRewardTakeProfit(risk_reward_ratio=2.0)
        with pytest.raises(AttributeError):
            tp.risk_reward_ratio = 3.0
