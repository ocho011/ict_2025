"""Percentage-based stop loss calculation."""

from dataclasses import dataclass
from pydantic import BaseModel, Field
from src.pricing.base import StopLossDeterminer, PriceContext
from src.strategies.decorators import register_module


@register_module(
    'stop_loss', 'percentage_sl',
    description='고정 비율 손절가 결정자',
)
@dataclass(frozen=True)
class PercentageStopLoss(StopLossDeterminer):
    """Fixed percentage stop loss from entry price."""

    class ParamSchema(BaseModel):
        """Pydantic schema for percentage SL parameters."""
        stop_loss_percent: float = Field(0.01, ge=0.001, le=0.05, description="손절 비율 (0.01 = 1%)")

    @classmethod
    def from_validated_params(cls, params: "PercentageStopLoss.ParamSchema") -> "PercentageStopLoss":
        """Create instance from Pydantic-validated params."""
        return cls(**params.model_dump())

    stop_loss_percent: float = 0.01  # 1% default

    def calculate_stop_loss(self, context: PriceContext) -> float:
        if context.side == "LONG":
            return context.entry_price * (1.0 - self.stop_loss_percent)
        else:  # SHORT
            return context.entry_price * (1.0 + self.stop_loss_percent)
