"""
Event ID enumeration for performance metrics.

Each event ID represents a distinct measurement point in the trading system.
Used to categorize and aggregate latency metrics.
"""

from enum import IntEnum


class EventID(IntEnum):
    """
    Performance measurement event identifiers.

    Values are intentionally small integers for efficient storage
    in the lock-free ring buffer (fits in 8 bits).
    """

    # Data ingestion pipeline
    CANDLE_PROCESSING = 1
    SIGNAL_GENERATION = 2

    # Order execution pipeline
    ORDER_PLACEMENT = 3
    ORDER_FILL = 4

    # Event bus operations
    EVENT_BUS_PUBLISH = 5
    EVENT_BUS_HANDLE = 6

    # System health metrics
    QUEUE_BACKLOG = 7
    GC_PAUSE = 8
