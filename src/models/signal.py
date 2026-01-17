"""
Trading signal model
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


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
        entry_price: Intended entry price (for entry) or current price (for exit)
        take_profit: Target profit price (required for ENTRY, optional for EXIT)
        stop_loss: Maximum loss price (required for ENTRY, optional for EXIT)
        strategy_name: Name of strategy that generated signal
        timestamp: Signal generation time (UTC)
        confidence: Signal strength (0.0-1.0, default 1.0)
        exit_reason: Reason for exit signal (e.g., "trailing_stop", "time_exit")
        metadata: Additional strategy-specific data
    """

    signal_type: SignalType
    symbol: str
    entry_price: float
    strategy_name: str
    timestamp: datetime
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    confidence: float = 1.0
    exit_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate signal parameters."""
        # Use object.__setattr__ for frozen dataclass validation
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")

        # Validate price logic based on signal type
        # ENTRY signals MUST have TP/SL
        if self.signal_type == SignalType.LONG_ENTRY:
            if self.take_profit is None:
                raise ValueError("LONG_ENTRY: take_profit is required")
            if self.stop_loss is None:
                raise ValueError("LONG_ENTRY: stop_loss is required")
            if self.take_profit <= self.entry_price:
                raise ValueError("LONG: take_profit must be > entry_price")
            if self.stop_loss >= self.entry_price:
                raise ValueError("LONG: stop_loss must be < entry_price")
        elif self.signal_type == SignalType.SHORT_ENTRY:
            if self.take_profit is None:
                raise ValueError("SHORT_ENTRY: take_profit is required")
            if self.stop_loss is None:
                raise ValueError("SHORT_ENTRY: stop_loss is required")
            if self.take_profit >= self.entry_price:
                raise ValueError("SHORT: take_profit must be < entry_price")
            if self.stop_loss <= self.entry_price:
                raise ValueError("SHORT: stop_loss must be > entry_price")
        # EXIT signals: TP/SL are optional (position is being closed)

    @property
    def is_entry_signal(self) -> bool:
        """Check if this is an entry signal (LONG_ENTRY or SHORT_ENTRY)."""
        return self.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY)

    @property
    def is_exit_signal(self) -> bool:
        """Check if this is an exit signal (CLOSE_LONG or CLOSE_SHORT)."""
        return self.signal_type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT)

    @property
    def risk_amount(self) -> float:
        """Risk per unit (entry - stop_loss). Returns 0.0 for exit signals."""
        if self.stop_loss is None:
            return 0.0
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_amount(self) -> float:
        """Reward per unit (take_profit - entry). Returns 0.0 for exit signals."""
        if self.take_profit is None:
            return 0.0
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        """Risk-to-reward ratio (reward / risk). Returns 0.0 for exit signals."""
        if self.risk_amount == 0:
            return 0.0
        return self.reward_amount / self.risk_amount
