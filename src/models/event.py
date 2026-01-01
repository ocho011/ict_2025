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
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"


@dataclass(slots=True)
class Event:
    """
    System event for event-driven architecture.

    Performance optimization: Using slots=True to reduce memory footprint by ~40%.
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
