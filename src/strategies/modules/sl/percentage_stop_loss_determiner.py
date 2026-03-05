"""Percentage-based Stop Loss Determiner module."""

from dataclasses import dataclass
from pydantic import BaseModel, Field
from src.strategies.modules.base.pricing import StopLossDeterminer, PriceContext
from src.strategies.decorators import register_module


@register_module(
    'stop_loss', 'fixed_percent_sl',
    description='고정 비율 손절가 결정자',
)
@dataclass(frozen=True)
class PercentageStopLossDeterminer(StopLossDeterminer):
    """Fixed percentage stop loss from entry price."""

    class ParamSchema(BaseModel):
        """Pydantic schema for percentage SL parameters."""
        stop_loss_percent: float = Field(0.02, ge=0.001, le=0.1, description="손절 비율 (0.02 = 2%)")

    @classmethod
    def from_validated_params(cls, params: "PercentageStopLossDeterminer.ParamSchema") -> "PercentageStopLossDeterminer":
        """Create instance from Pydantic-validated params."""
        return cls(**params.model_dump())

    stop_loss_percent: float = 0.02

    def calculate_stop_loss(self, context: PriceContext) -> float:
        if context.side == "LONG":
            return context.entry_price * (1.0 - self.stop_loss_percent)
        else:  # SHORT
            return context.entry_price * (1.0 + self.stop_loss_percent)
