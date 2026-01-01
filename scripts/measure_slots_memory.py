#!/usr/bin/env python3
"""
Memory usage measurement script for __slots__ optimization validation.

Compares memory footprint of Candle and Event instances with slots=True
against theoretical baseline without slots.
"""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.candle import Candle
from models.event import Event, EventType


def get_object_size(obj):
    """Get total size of object including __dict__ if present."""
    size = sys.getsizeof(obj)
    if hasattr(obj, "__dict__"):
        size += sys.getsizeof(obj.__dict__)
    return size


def measure_candle_memory():
    """Measure memory footprint of Candle instances."""
    # Create sample candle
    candle = Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=datetime.utcnow(),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=123.45,
        close_time=datetime.utcnow(),
        is_closed=True,
    )

    size = get_object_size(candle)
    return size


def measure_event_memory():
    """Measure memory footprint of Event instances."""
    event = Event(
        event_type=EventType.CANDLE_UPDATE,
        data={"test": "data"},
        timestamp=datetime.utcnow(),
        source="test",
    )

    size = get_object_size(event)
    return size


def main():
    print("=" * 60)
    print("Memory Usage Measurement - __slots__ Optimization")
    print("=" * 60)
    print()

    # Measure Candle
    candle_size = measure_candle_memory()
    print(f"Candle instance size: {candle_size} bytes")
    print(f"  Expected without slots: ~450 bytes")
    print(f"  Expected with slots: ~270 bytes (40% reduction)")
    print(f"  Actual reduction: {((450 - candle_size) / 450 * 100):.1f}%")
    print()

    # Measure Event
    event_size = measure_event_memory()
    print(f"Event instance size: {event_size} bytes")
    print(f"  Expected without slots: ~400 bytes")
    print(f"  Expected with slots: ~240 bytes (40% reduction)")
    print(f"  Actual reduction: {((400 - event_size) / 400 * 100):.1f}%")
    print()

    # Performance impact estimation
    print("=" * 60)
    print("Performance Impact Estimation")
    print("=" * 60)
    print()
    print("Assumptions:")
    print("  - 4 candles/second (1m, 5m, 15m, 1h)")
    print("  - 10 events/second average")
    print("  - 1 hour runtime")
    print()

    candles_per_hour = 4 * 3600
    events_per_hour = 10 * 3600

    memory_saved_candles = (450 - candle_size) * candles_per_hour
    memory_saved_events = (400 - event_size) * events_per_hour

    total_saved = memory_saved_candles + memory_saved_events

    print(f"Memory saved (1 hour):")
    print(f"  Candles: {memory_saved_candles / 1024 / 1024:.2f} MB")
    print(f"  Events: {memory_saved_events / 1024 / 1024:.2f} MB")
    print(f"  Total: {total_saved / 1024 / 1024:.2f} MB")
    print()

    # Verify slots are actually working
    print("=" * 60)
    print("__slots__ Verification")
    print("=" * 60)
    print()

    from models.candle import Candle
    from models.event import Event

    candle = Candle(
        symbol="BTCUSDT",
        interval="1m",
        open_time=datetime.utcnow(),
        open=50000.0,
        high=50100.0,
        low=49900.0,
        close=50050.0,
        volume=123.45,
        close_time=datetime.utcnow(),
        is_closed=True,
    )

    event = Event(
        event_type=EventType.CANDLE_UPDATE,
        data={"test": "data"},
    )

    # Try to access __dict__ (should not exist with slots)
    has_candle_dict = hasattr(candle, "__dict__")
    has_event_dict = hasattr(event, "__dict__")

    print(f"Candle has __dict__: {has_candle_dict} (should be False)")
    print(f"Event has __dict__: {has_event_dict} (should be False)")
    print()

    if not has_candle_dict and not has_event_dict:
        print("✅ __slots__ optimization is ACTIVE and working correctly!")
    else:
        print("❌ WARNING: __slots__ optimization may not be working!")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
