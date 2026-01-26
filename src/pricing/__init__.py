"""
Price determination module for strategy decoupling.

Provides abstract interfaces and concrete implementations for
stop loss and take profit calculations.
"""

from src.pricing.base import (
    PriceContext,
    StopLossDeterminer,
    TakeProfitDeterminer,
    PriceDeterminerConfig,
)
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.pricing.take_profit.displacement import DisplacementTakeProfit

__all__ = [
    "PriceContext",
    "StopLossDeterminer",
    "TakeProfitDeterminer",
    "PriceDeterminerConfig",
    "PercentageStopLoss",
    "ZoneBasedStopLoss",
    "RiskRewardTakeProfit",
    "DisplacementTakeProfit",
]
