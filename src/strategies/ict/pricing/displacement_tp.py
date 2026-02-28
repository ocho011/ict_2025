"""ICT displacement-based take profit calculation."""

from dataclasses import dataclass
from src.pricing.base import TakeProfitDeterminer, PriceContext
from pydantic import BaseModel, Field
from src.strategies.decorators import register_module


@register_module(
    'take_profit', 'displacement_tp',
    description='ICT 디스플레이스먼트 기반 익절가 결정자',
)
@dataclass(frozen=True)
class DisplacementTakeProfit(TakeProfitDeterminer):
    """
    ICT displacement-based take profit.

    Uses displacement size as the risk measure instead of SL distance.
    Falls back to SL-based calculation if no displacement provided.
    """

    class ParamSchema(BaseModel):
        """Pydantic schema for displacement TP parameters."""
        risk_reward_ratio: float = Field(2.0, ge=1.0, le=10.0, description="리스크/리워드 비율")
        fallback_risk_percent: float = Field(0.02, ge=0.005, le=0.05, description="폴백 리스크 비율")

    @classmethod
    def from_validated_params(cls, params: "DisplacementTakeProfit.ParamSchema") -> "DisplacementTakeProfit":
        """Create instance from Pydantic-validated params."""
        return cls(**params.model_dump())

    risk_reward_ratio: float = 2.0
    fallback_risk_percent: float = 0.02  # 2% fallback

    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        # Calculate actual SL distance as the true risk measure (Issue #102)
        sl_distance = abs(context.entry_price - stop_loss)

        # Use displacement size if available
        displacement_size = context.extras.get("displacement_size")
        if displacement_size and displacement_size > 0:
            displacement_risk = displacement_size
        else:
            displacement_risk = context.entry_price * self.fallback_risk_percent

        # Use the more conservative (larger) risk for consistent R:R (Issue #102)
        # This ensures TP is never closer than what the actual SL distance warrants
        risk_amount = max(sl_distance, displacement_risk) if sl_distance > 0 else displacement_risk

        reward_amount = risk_amount * self.risk_reward_ratio

        if context.side == "LONG":
            tp = context.entry_price + reward_amount
            return tp if tp > context.entry_price else context.entry_price * 1.02
        else:  # SHORT
            tp = context.entry_price - reward_amount
            return tp if tp < context.entry_price else context.entry_price * 0.98
