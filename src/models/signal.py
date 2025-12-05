"""
Trading signal model
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict


class SignalType(Enum):
    """Trading signal types."""

    LONG_ENTRY = "long_entry"
    SHORT_ENTRY = "short_entry"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


@dataclass(frozen=True)
class Signal:
    """
    Trading signal with entry/exit parameters.

    Attributes:
        signal_type: Type of signal (entry/exit, long/short)
        symbol: Trading pair
        entry_price: Intended entry price
        take_profit: Target profit price
        stop_loss: Maximum loss price
        strategy_name: Name of strategy that generated signal
        timestamp: Signal generation time (UTC)
        confidence: Signal strength (0.0-1.0, default 1.0)
        metadata: Additional strategy-specific data
    """

    signal_type: SignalType
    symbol: str
    entry_price: float
    take_profit: float
    stop_loss: float
    strategy_name: str
    timestamp: datetime
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate signal parameters."""
        # Use object.__setattr__ for frozen dataclass validation
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")

        # Validate price logic based on signal type
        if self.signal_type == SignalType.LONG_ENTRY:
            if self.take_profit <= self.entry_price:
                raise ValueError("LONG: take_profit must be > entry_price")
            if self.stop_loss >= self.entry_price:
                raise ValueError("LONG: stop_loss must be < entry_price")
        elif self.signal_type == SignalType.SHORT_ENTRY:
            if self.take_profit >= self.entry_price:
                raise ValueError("SHORT: take_profit must be < entry_price")
            if self.stop_loss <= self.entry_price:
                raise ValueError("SHORT: stop_loss must be > entry_price")

    @property
    def risk_amount(self) -> float:
        """Risk per unit (entry - stop_loss)."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_amount(self) -> float:
        """Reward per unit (take_profit - entry)."""
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        """Risk-to-reward ratio (reward / risk)."""
        if self.risk_amount == 0:
            return 0.0
        return self.reward_amount / self.risk_amount
