"""
Event model for event-driven architecture
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class EventType(Enum):
    """Event types for event-driven architecture."""

    CANDLE_UPDATE = "candle_update"
    CANDLE_CLOSED = "candle_closed"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_PARTIALLY_FILLED = "order_partially_filled"  # Partial fill from exchange
    ORDER_UPDATE = "order_update"  # User Data Stream order update events
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"


class QueueType(Enum):
    """Queue types for event distribution priority."""

    DATA = "data"  # Keep for backward compatibility (unused after migration)
    CANDLE_UPDATE = "candle_update"  # High freq, can drop
    CANDLE_CLOSED = "candle_closed"  # Low freq, critical
    SIGNAL = "signal"
    ORDER = "order"


@dataclass
class Event:
    """
    System event for event-driven architecture.

    Performance note: slots=True disabled for Python 3.9 compatibility
    Events are created frequently (4+ times/second), so memory efficiency is critical
    for high-frequency event processing.

    Attributes:
        event_type: Type of event
        data: Event payload (Candle, Signal, Order, etc.)
        timestamp: Event occurrence time (UTC)
        source: Component that generated event
    """

    event_type: EventType
    data: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: Optional[str] = None
