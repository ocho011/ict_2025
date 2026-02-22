"""
Base interfaces and data structures for entry determination.

Real-time Trading Guideline Compliance:
- EntryContext uses @dataclass(frozen=True) for immutability
- EntryDecision uses @dataclass(frozen=True) for immutability
- No datetime parsing in hot path - use int timestamp
- ABC defines minimal interface surface
"""

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.candle import Candle
from src.models.signal import SignalType


@dataclass(frozen=True)
class EntryContext:
    """
    Immutable context for entry determination.

    Hot path compliant: frozen dataclass, int timestamp, no datetime parsing.
    Contains everything an EntryDeterminer needs to decide on entry.

    Buffers are passed by reference (not deep copied) for performance.
    Determiners MUST NOT modify buffers - they are read-only.
    """

    symbol: str
    candle: Candle  # Current candle being analyzed
    buffers: Dict[str, deque]  # Read-only reference to candle buffers
    indicator_cache: Optional[Any]  # IndicatorStateCache or None
    timestamp: int  # Unix ms (no datetime parsing)
    config: dict  # Strategy-specific config params

    # Optional typed fields for specific determiner needs
    intervals: Optional[List[str]] = None  # Informational only


@dataclass(frozen=True)
class EntryDecision:
    """
    Raw entry decision before TP/SL calculation.

    NOT a Signal - this is an intermediate result that ComposableStrategy
    uses to then calculate TP/SL and create the final Signal.

    Why not Signal? Signal.__post_init__() validates that ENTRY signals
    MUST have take_profit and stop_loss values. The entry determiner
    cannot provide these because they are calculated by separate
    determiners (StopLossDeterminer, TakeProfitDeterminer) AFTER
    the entry decision is made.

    Flow: EntryDeterminer.analyze() -> EntryDecision
          -> ComposableStrategy calculates TP/SL
          -> ComposableStrategy assembles final Signal

    metadata: Public metadata that becomes part of the final Signal.
    price_extras: Strategy-specific data passed to PriceContext.extras
                  for downstream SL/TP determiners. Replaces _-prefixed
                  metadata transport pattern.
    """

    signal_type: SignalType  # LONG_ENTRY or SHORT_ENTRY
    entry_price: float
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    price_extras: Dict[str, Any] = field(default_factory=dict)


class EntryDeterminer(ABC):
    """Abstract base for entry signal determination."""

    @abstractmethod
    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        """
        Analyze market context and return entry decision if conditions met.

        Returns:
            EntryDecision if entry conditions met, None otherwise.
            EntryDecision carries metadata for downstream TP/SL calculation.
            The ComposableStrategy will use this to calculate TP/SL via
            separate determiners and assemble the final Signal.
        """
        pass

    @property
    def name(self) -> str:
        """Determiner name for logging/metadata."""
        return self.__class__.__name__
