"""Risk-reward ratio based take profit calculation."""

from dataclasses import dataclass
from pydantic import BaseModel, Field
from src.pricing.base import TakeProfitDeterminer, PriceContext
from src.strategies.decorators import register_module


@register_module(
    'take_profit', 'rr_take_profit',
    description='리스크/리워드 비율 기반 익절가 결정자',
)
@dataclass(frozen=True)
class RiskRewardTakeProfit(TakeProfitDeterminer):
    """Take profit based on risk-reward ratio from stop loss distance."""

    class ParamSchema(BaseModel):
        """Pydantic schema for RR take profit parameters."""
        risk_reward_ratio: float = Field(2.0, ge=1.0, le=10.0, description="리스크/리워드 비율")

    @classmethod
    def from_validated_params(cls, params: "RiskRewardTakeProfit.ParamSchema") -> "RiskRewardTakeProfit":
        """Create instance from Pydantic-validated params."""
        return cls(**params.model_dump())

    risk_reward_ratio: float = 2.0

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        sl_distance = abs(context.entry_price - stop_loss)
        tp_distance = sl_distance * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + tp_distance
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - tp_distance
            return tp if tp < context.entry_price else context.entry_price * 0.98
