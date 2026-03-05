"""
Always Entry Determiner module (for testing).
"""

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from src.strategies.modules.base.entry import EntryDeterminer, EntryContext, EntryDecision
from src.models.signal import SignalType
from src.strategies.decorators import register_module


@register_module(
    'entry', 'always_entry',
    description='항상 진입 신호를 생성하는 결정자 (테스트용)',
)
@dataclass
class AlwaysEntryDeterminer(EntryDeterminer):
    """
    Entry determiner that generates a signal on every closed candle.
    Used for end-to-end integration testing of the order pipeline.
    """

    class ParamSchema(BaseModel):
        """Pydantic schema for parameters."""
        signal_type: str = Field("LONG", description="생성할 신호 타입 (LONG/SHORT)")

    @classmethod
    def from_validated_params(cls, params: "AlwaysEntryDeterminer.ParamSchema") -> "AlwaysEntryDeterminer":
        """Create instance from Pydantic-validated params."""
        return cls(signal_type=params.signal_type)

    signal_type: str = "LONG"

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        """
        Generate an entry decision for every closed candle.
        """
        if not context.candle.is_closed:
            return None

        sig_type = (
            SignalType.LONG_ENTRY
            if self.signal_type.upper() == "LONG"
            else SignalType.SHORT_ENTRY
        )

        return EntryDecision(
            signal_type=sig_type,
            entry_price=context.candle.close,
            confidence=1.0,
            metadata={"reason": "always_signal_testing"},
        )
