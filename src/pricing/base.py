"""
Base interfaces and data structures for price determination.

Real-time Trading Guideline Compliance:
- PriceContext uses @dataclass(frozen=True) for immutability
- No datetime parsing in hot path - use int timestamp
- All ABCs define minimal interface surface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
import time

from src.entry.base import EntryDeterminer
from src.exit.base import ExitDeterminer


@dataclass(frozen=True)
class PriceContext:
    """
    Immutable context for price calculations.

    Strategy-specific data passed via extras dict for extensibility.
    Real-time compliance: Uses int timestamp, no datetime parsing.
    """
    entry_price: float
    side: str  # "LONG" | "SHORT"
    symbol: str
    timestamp: int  # Unix timestamp in milliseconds
    extras: Dict[str, Any] = field(default_factory=dict)  # Strategy-specific data

    @classmethod
    def from_strategy(
        cls,
        entry_price: float,
        side: str,
        symbol: str,
        extras: Optional[Dict[str, Any]] = None,
    ) -> "PriceContext":
        """Factory method for strategy use."""
        return cls(
            entry_price=entry_price,
            side=side,
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            extras=extras or {},
        )


class StopLossDeterminer(ABC):
    """Abstract base for stop loss determination."""

    @abstractmethod
    def calculate_stop_loss(self, context: PriceContext) -> float:
        """Calculate stop loss price."""
        pass


class TakeProfitDeterminer(ABC):
    """Abstract base for take profit determination."""

    @abstractmethod
    def calculate_take_profit(self, context: PriceContext, stop_loss: float) -> float:
        """Calculate take profit price. May use SL distance for risk-reward."""
        pass


@dataclass(frozen=True)
class PriceDeterminerConfig:
    """Configuration bundle for strategy injection."""
    stop_loss_determiner: StopLossDeterminer
    take_profit_determiner: TakeProfitDeterminer


@dataclass(frozen=True)
class StrategyModuleConfig:
    """
    Complete module bundle for composable strategy assembly.

    Extends PriceDeterminerConfig with entry and exit determiners.
    """
    entry_determiner: EntryDeterminer
    stop_loss_determiner: StopLossDeterminer
    take_profit_determiner: TakeProfitDeterminer
    exit_determiner: ExitDeterminer  # Default: NullExitDeterminer
