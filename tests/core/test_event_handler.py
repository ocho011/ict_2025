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


class TestEventBusQueues:
    """Test EventBus multi-queue system (Subtask 4.2)."""

    def test_queues_initialized_with_correct_sizes(self):
        """Verify all three queues created with correct maxsize."""
        bus = EventBus()

        stats = bus.get_queue_stats()

        assert 'data' in stats
        assert 'signal' in stats
        assert 'order' in stats

        assert stats['data']['maxsize'] == 1000
        assert stats['signal']['maxsize'] == 100
        assert stats['order']['maxsize'] == 50

        # All queues start empty
        assert stats['data']['size'] == 0
        assert stats['signal']['size'] == 0
        assert stats['order']['size'] == 0

        # No drops initially
        assert stats['data']['drops'] == 0
        assert stats['signal']['drops'] == 0
        assert stats['order']['drops'] == 0

    @pytest.mark.asyncio
    async def test_data_queue_drops_events_when_full(self):
        """Verify data queue drops events after timeout when full."""
        bus = EventBus()

        # Fill data queue to capacity (1000 events)
        for i in range(1000):
            event = Event(EventType.CANDLE_UPDATE, {'id': i}, source='test')
            await bus.publish(event, queue_name='data')

        # Verify queue is full
        stats = bus.get_queue_stats()
        assert stats['data']['size'] == 1000

        # Attempt to publish one more (should drop due to timeout)
        overflow_event = Event(EventType.CANDLE_UPDATE, {'id': 1000}, source='test')

        # Should not raise exception (drops gracefully)
        await bus.publish(overflow_event, queue_name='data')

        # Verify drop was counted
        stats_after = bus.get_queue_stats()
        assert stats_after['data']['drops'] == 1

        # Queue still at capacity (event was dropped, not added)
        assert stats_after['data']['size'] == 1000

    @pytest.mark.asyncio
    async def test_signal_queue_raises_timeout_when_full(self):
        """Verify signal queue raises TimeoutError when full (no drops)."""
        import asyncio
        bus = EventBus()

        # Fill signal queue to capacity (100 events)
        for i in range(100):
            event = Event(EventType.SIGNAL_GENERATED, {'id': i}, source='test')
            await bus.publish(event, queue_name='signal')

        # Verify queue is full
        stats = bus.get_queue_stats()
        assert stats['signal']['size'] == 100

        # Attempt to publish one more (should raise TimeoutError)
        overflow_event = Event(EventType.SIGNAL_GENERATED, {'id': 100}, source='test')

        with pytest.raises(asyncio.TimeoutError):
            await bus.publish(overflow_event, queue_name='signal')

        # Verify no drops (signal queue never drops)
        stats_after = bus.get_queue_stats()
        assert stats_after['signal']['drops'] == 0

    @pytest.mark.asyncio
    async def test_order_queue_blocks_indefinitely_when_full(self):
        """Verify order queue blocks without timeout (never drops)."""
        import asyncio
        bus = EventBus()

        # Fill order queue to capacity (50 events)
        for i in range(50):
            event = Event(EventType.ORDER_PLACED, {'id': i}, source='test')
            await bus.publish(event, queue_name='order')

        # Verify queue is full
        stats = bus.get_queue_stats()
        assert stats['order']['size'] == 50

        # Attempt to publish with short timeout to verify blocking behavior
        overflow_event = Event(EventType.ORDER_PLACED, {'id': 50}, source='test')

        # Use wait_for to simulate timeout (order queue itself has no timeout)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                bus.publish(overflow_event, queue_name='order'),
                timeout=0.5  # Short timeout to verify blocking
            )

        # Verify no drops (order queue NEVER drops)
        stats_after = bus.get_queue_stats()
        assert stats_after['order']['drops'] == 0

    @pytest.mark.asyncio
    async def test_publish_raises_valueerror_for_invalid_queue(self):
        """Verify publish() validates queue_name parameter."""
        bus = EventBus()
        event = Event(EventType.CANDLE_UPDATE, {}, source='test')

        with pytest.raises(ValueError) as exc_info:
            await bus.publish(event, queue_name='invalid_queue')

        assert "Invalid queue_name 'invalid_queue'" in str(exc_info.value)
        assert "data" in str(exc_info.value)
        assert "signal" in str(exc_info.value)
        assert "order" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_queue_stats_reflects_current_state(self):
        """Verify get_queue_stats() returns accurate real-time data."""
        bus = EventBus()

        # Initial state
        stats = bus.get_queue_stats()
        assert stats['data']['size'] == 0

        # Publish 10 events to data queue
        for i in range(10):
            event = Event(EventType.CANDLE_UPDATE, {'id': i}, source='test')
            await bus.publish(event, queue_name='data')

        # Verify stats updated
        stats_after = bus.get_queue_stats()
        assert stats_after['data']['size'] == 10
        assert stats_after['data']['drops'] == 0

        # Publish 5 to signal, 2 to order
        for i in range(5):
            await bus.publish(
                Event(EventType.SIGNAL_GENERATED, {'id': i}, source='test'),
                queue_name='signal'
            )
        for i in range(2):
            await bus.publish(
                Event(EventType.ORDER_PLACED, {'id': i}, source='test'),
                queue_name='order'
            )

        # Verify all queues tracked independently
        final_stats = bus.get_queue_stats()
        assert final_stats['data']['size'] == 10
        assert final_stats['signal']['size'] == 5
        assert final_stats['order']['size'] == 2
