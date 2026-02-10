"""
Always-signal entry determination for testing.

Extracted from AlwaysSignalStrategy.analyze().
WARNING: TEST ONLY - generates signals on every closed candle.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.entry.base import EntryDeterminer, EntryContext, EntryDecision
from src.models.signal import SignalType


@dataclass
class AlwaysEntryDeterminer(EntryDeterminer):
    """
    Test-only entry determiner that always generates signals.

    Supports three modes:
    - ALTERNATE: Alternates between LONG and SHORT (default)
    - LONG: Always generates LONG signals
    - SHORT: Always generates SHORT signals
    """
    signal_mode: str = "ALTERNATE"

    def __post_init__(self):
        self._last_signal_type: Optional[SignalType] = None
        self.logger = logging.getLogger(__name__)
        if self.signal_mode not in ["LONG", "SHORT", "ALTERNATE"]:
            raise ValueError(
                f"signal_mode must be 'LONG', 'SHORT', or 'ALTERNATE', got '{self.signal_mode}'"
            )
        self.logger.warning(
            "AlwaysEntryDeterminer loaded - TEST ONLY, DO NOT USE WITH REAL MONEY"
        )

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        """Generate entry decision on every closed candle."""
        candle = context.candle
        if not candle.is_closed:
            return None

        if self.signal_mode == "ALTERNATE":
            if self._last_signal_type == SignalType.LONG_ENTRY:
                signal_type = SignalType.SHORT_ENTRY
            else:
                signal_type = SignalType.LONG_ENTRY
        elif self.signal_mode == "LONG":
            signal_type = SignalType.LONG_ENTRY
        else:
            signal_type = SignalType.SHORT_ENTRY

        self._last_signal_type = signal_type
        self.logger.info(f"TEST SIGNAL: {signal_type.value} @ {candle.close}")

        return EntryDecision(
            signal_type=signal_type,
            entry_price=candle.close,
            metadata={"test_mode": self.signal_mode},
        )
