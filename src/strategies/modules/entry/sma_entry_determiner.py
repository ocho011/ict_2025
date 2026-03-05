"""
SMA Crossover Entry Determiner module.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from src.strategies.modules.base.entry import EntryDeterminer, EntryContext, EntryDecision
from src.models.signal import SignalType
from src.strategies.decorators import register_module


@register_module(
    'entry', 'sma_entry',
    description='SMA 교차 기반 진입 결정자',
    compatible_with={
        'stop_loss': ['percentage_sl'],
        'take_profit': ['rr_take_profit'],
        'exit': ['null_exit'],
    }
)
@dataclass
class SMAEntryDeterminer(EntryDeterminer):
    """
    SMA crossover entry determination.
    """

    class ParamSchema(BaseModel):
        """Pydantic schema for SMA entry parameters."""
        fast_period: int = Field(10, ge=2, le=100, description="Fast SMA 기간")
        slow_period: int = Field(20, ge=5, le=200, description="Slow SMA 기간")

    @classmethod
    def from_validated_params(cls, params: "SMAEntryDeterminer.ParamSchema") -> "SMAEntryDeterminer":
        """Create instance from Pydantic-validated params."""
        return cls(**params.model_dump())

    fast_period: int = 10
    slow_period: int = 20

    def __post_init__(self):
        self._last_signal_type: Optional[SignalType] = None
        self.logger = logging.getLogger(__name__)
        if self.fast_period >= self.slow_period:
            raise ValueError(
                f"fast_period ({self.fast_period}) must be < slow_period ({self.slow_period})"
            )

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        """
        Analyze candle for SMA crossover signals.
        """
        candle = context.candle

        if not candle.is_closed:
            return None

        buffer = context.buffers.get(candle.interval)
        if buffer is None:
            return None

        if len(buffer) < self.slow_period + 1:
            return None

        close_prices = np.array([c.close for c in buffer])

        current_fast_sma = np.mean(close_prices[-self.fast_period:])
        current_slow_sma = np.mean(close_prices[-self.slow_period:])

        previous_fast_sma = np.mean(close_prices[-(self.fast_period + 1):-1])
        previous_slow_sma = np.mean(close_prices[-(self.slow_period + 1):-1])

        if previous_fast_sma <= previous_slow_sma and current_fast_sma > current_slow_sma:
            if self._last_signal_type == SignalType.LONG_ENTRY:
                return None

            self._last_signal_type = SignalType.LONG_ENTRY
            return EntryDecision(
                signal_type=SignalType.LONG_ENTRY,
                entry_price=candle.close,
                metadata={"crossover": "golden_cross"},
            )

        if previous_fast_sma >= previous_slow_sma and current_fast_sma < current_slow_sma:
            if self._last_signal_type == SignalType.SHORT_ENTRY:
                return None

            self._last_signal_type = SignalType.SHORT_ENTRY
            return EntryDecision(
                signal_type=SignalType.SHORT_ENTRY,
                entry_price=candle.close,
                metadata={"crossover": "death_cross"},
            )

        return None
