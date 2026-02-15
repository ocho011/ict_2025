"""
Base interfaces and data structures for exit determination.

Real-time Trading Guideline Compliance:
- ExitContext uses @dataclass(frozen=True) for immutability
- No datetime parsing in hot path - use int timestamp
- ABC defines minimal interface surface
"""

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal


@dataclass(frozen=True)
class ExitContext:
    """
    Immutable context for exit determination.

    Contains position info + market state for exit decisions.
    Hot path compliant: frozen dataclass, int timestamp.

    Note: config is the raw strategy config dict for general-purpose access.
    ICTExitDeterminer does NOT use this field for ExitConfig access.
    ExitConfig is passed directly as a constructor parameter to ICTExitDeterminer.
    """

    symbol: str
    candle: Candle
    position: Position  # Current open position
    buffers: Dict[str, deque]  # Read-only buffer reference
    indicator_cache: Optional[Any]  # IndicatorStateCache or None
    timestamp: int  # Unix ms
    config: dict  # Strategy-specific config (plain dict)
    intervals: Optional[List[str]] = None


class ExitDeterminer(ABC):
    """Abstract base for exit signal determination."""

    @abstractmethod
    def should_exit(self, context: ExitContext) -> Optional[Signal]:
        """
        Evaluate whether position should be exited.

        Returns:
            Signal with CLOSE_LONG/CLOSE_SHORT if exit triggered, None otherwise.
        """
        pass


class NullExitDeterminer(ExitDeterminer):
    """Default no-op exit determiner. Relies on TP/SL orders only."""

    def should_exit(self, context: ExitContext) -> Optional[Signal]:
        return None
