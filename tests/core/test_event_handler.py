"""
Unit tests for EventBus core functionality (Subtask 4.1)

Tests the subscriber registry and event routing foundation
of the EventBus class before queue implementation.
"""

import threading
import pytest

from src.core.event_handler import EventBus
from src.models.event import Event, EventType


class TestEventBusCore:
    """Test EventBus subscriber registry and routing."""

    def test_subscribe_adds_handler(self):
        """Verify subscribe() adds handler to subscriber registry."""
        bus = EventBus()

        def my_handler(event):
            pass

        # Subscribe handler to event type
        bus.subscribe(EventType.CANDLE_CLOSED, my_handler)

        # Verify handler was added
        handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
        assert my_handler in handlers
        assert len(handlers) == 1

    def test_multiple_handlers_same_event(self):
        """Verify multiple handlers can subscribe to same event type."""
        bus = EventBus()

        def handler_1(event):
            pass

        def handler_2(event):
            pass

        # Subscribe both handlers
        bus.subscribe(EventType.CANDLE_CLOSED, handler_1)
        bus.subscribe(EventType.CANDLE_CLOSED, handler_2)

        # Verify both handlers registered
        handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
        assert handler_1 in handlers
        assert handler_2 in handlers
        assert len(handlers) == 2

        # Verify order is preserved
        assert handlers[0] is handler_1
        assert handlers[1] is handler_2

    def test_empty_handler_list_for_unsubscribed_events(self):
        """Verify _get_handlers() returns empty list for unregistered events."""
        bus = EventBus()

        # Don't subscribe any handlers

        # Get handlers for event with no subscriptions
        handlers = bus._get_handlers(EventType.SIGNAL_GENERATED)

        # Verify empty list returned (not None or error)
        assert handlers == []
        assert len(handlers) == 0
        assert isinstance(handlers, list)

    def test_sync_and_async_callables_registered(self):
        """Verify both sync and async handlers can be registered."""
        bus = EventBus()

        def sync_handler(event):
            pass

        async def async_handler(event):
            pass

        # Subscribe both types
        bus.subscribe(EventType.CANDLE_CLOSED, sync_handler)
        bus.subscribe(EventType.CANDLE_CLOSED, async_handler)

        # Verify both registered
        handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
        assert sync_handler in handlers
        assert async_handler in handlers

        # Verify they're callable
        assert callable(sync_handler)
        assert callable(async_handler)

    def test_thread_safety_concurrent_subscriptions(self):
        """Verify concurrent subscriptions from multiple threads are safe."""
        bus = EventBus()

        def handler(event):
            pass

        # Subscribe from multiple threads simultaneously
        threads = []
        for i in range(10):
            t = threading.Thread(
                target=lambda: bus.subscribe(EventType.CANDLE_CLOSED, handler)
            )
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Verify all subscriptions succeeded
        handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
        assert len(handlers) == 10  # All 10 subscriptions succeeded
        assert all(h is handler for h in handlers)

    def test_initialization_sets_default_values(self):
        """Verify __init__ sets all required attributes correctly."""
        bus = EventBus()

        # Check _subscribers is defaultdict
        assert hasattr(bus, '_subscribers')
        from collections import defaultdict
        assert isinstance(bus._subscribers, defaultdict)

        # Check logger exists
        assert hasattr(bus, 'logger')
        assert bus.logger is not None

        # Check _running flag initialized to False
        assert hasattr(bus, '_running')
        assert bus._running is False

    def test_subscribe_different_event_types(self):
        """Verify handlers can subscribe to different event types independently."""
        bus = EventBus()

        def candle_handler(event):
            pass

        def signal_handler(event):
            pass

        # Subscribe to different event types
        bus.subscribe(EventType.CANDLE_CLOSED, candle_handler)
        bus.subscribe(EventType.SIGNAL_GENERATED, signal_handler)

        # Verify each event type has correct handler
        candle_handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
        signal_handlers = bus._get_handlers(EventType.SIGNAL_GENERATED)

        assert candle_handler in candle_handlers
        assert signal_handler in signal_handlers
        assert candle_handler not in signal_handlers
        assert signal_handler not in candle_handlers

    def test_same_handler_multiple_subscriptions_allowed(self):
        """Verify same handler can subscribe multiple times (no deduplication)."""
        bus = EventBus()

        def my_handler(event):
            pass

        # Subscribe same handler 3 times
        bus.subscribe(EventType.CANDLE_CLOSED, my_handler)
        bus.subscribe(EventType.CANDLE_CLOSED, my_handler)
        bus.subscribe(EventType.CANDLE_CLOSED, my_handler)

        # Verify handler appears 3 times
        handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
        assert len(handlers) == 3
        assert all(h is my_handler for h in handlers)


class TestEventBusLogging:
    """Test EventBus logging behavior."""

    def test_initialization_logs_debug_message(self, caplog):
        """Verify initialization logs debug message."""
        import logging
        caplog.set_level(logging.DEBUG)

        bus = EventBus()

        # Check debug log was created
        assert "EventBus initialized" in caplog.text

    def test_subscribe_logs_handler_name(self, caplog):
        """Verify subscribe() logs handler name at debug level."""
        import logging
        caplog.set_level(logging.DEBUG)

        bus = EventBus()

        def test_handler(event):
            pass

        bus.subscribe(EventType.CANDLE_CLOSED, test_handler)

        # Check handler name appears in logs
        assert "test_handler" in caplog.text
        assert "subscribed" in caplog.text.lower()
        assert EventType.CANDLE_CLOSED.value in caplog.text

    def test_subscribe_logs_lambda_handler(self, caplog):
        """Verify subscribe() logs lambda handlers gracefully."""
        import logging
        caplog.set_level(logging.DEBUG)

        bus = EventBus()

        # Lambda doesn't have __name__, should use repr
        bus.subscribe(EventType.CANDLE_CLOSED, lambda e: None)

        # Check something was logged (repr will contain <lambda>)
        assert "subscribed" in caplog.text.lower()
        assert EventType.CANDLE_CLOSED.value in caplog.text
