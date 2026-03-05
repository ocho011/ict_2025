"""
Null Exit Determiner module.
Used when positions are managed solely by TP/SL orders.
"""

from typing import Optional
from src.strategies.modules.base.exit import ExitContext, ExitDeterminer
from src.models.signal import Signal
from src.strategies.decorators import register_module


from pydantic import BaseModel

@register_module('exit', 'null_exit', description='No-op 청산 결정자 (TP/SL만 의존)')
class NullExitDeterminer(ExitDeterminer):
    """
    Exit determiner that never triggers an exit signal.
    """

    class ParamSchema(BaseModel):
        """No parameters needed."""
        pass

    @classmethod
    def from_validated_params(cls, params: "NullExitDeterminer.ParamSchema") -> "NullExitDeterminer":
        return cls()

    def should_exit(self, context: ExitContext) -> Optional[Signal]:
        return None
