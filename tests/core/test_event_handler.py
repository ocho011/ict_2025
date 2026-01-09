"""
Unit tests for EventBus core functionality (Subtask 4.1)

Tests the subscriber registry and event routing foundation
of the EventBus class before queue implementation.
"""

import asyncio
import threading

import pytest

from src.core.event_handler import EventBus
from src.models.event import Event, EventType


@pytest.fixture
async def event_bus_with_queues():
    """Create EventBus with queues initialized (without starting processors)."""
    bus = EventBus()
    # Initialize queues directly (mimics what start() does)
    # Must be async to create queues in the test's event loop
    bus._queues = {
        "data": asyncio.Queue(maxsize=1000),
        "signal": asyncio.Queue(maxsize=100),
        "order": asyncio.Queue(maxsize=50),
    }
    return bus


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
            t = threading.Thread(target=lambda: bus.subscribe(EventType.CANDLE_CLOSED, handler))
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
        assert hasattr(bus, "_subscribers")
        from collections import defaultdict

        assert isinstance(bus._subscribers, defaultdict)

        # Check logger exists
        assert hasattr(bus, "logger")
        assert bus.logger is not None

        # Check _running flag initialized to False
        assert hasattr(bus, "_running")
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

        EventBus()

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

    def test_queues_initialized_with_correct_sizes(self, event_bus_with_queues):
        """Verify all three queues created with correct maxsize."""
        bus = event_bus_with_queues

        stats = bus.get_queue_stats()

        assert "data" in stats
        assert "signal" in stats
        assert "order" in stats

        assert stats["data"]["maxsize"] == 1000
        assert stats["signal"]["maxsize"] == 100
        assert stats["order"]["maxsize"] == 50

        # All queues start empty
        assert stats["data"]["size"] == 0
        assert stats["signal"]["size"] == 0
        assert stats["order"]["size"] == 0

        # No drops initially
        assert stats["data"]["drops"] == 0
        assert stats["signal"]["drops"] == 0
        assert stats["order"]["drops"] == 0

    @pytest.mark.asyncio
    async def test_data_queue_drops_events_when_full(self, event_bus_with_queues):
        """Verify data queue drops events after timeout when full."""
        bus = event_bus_with_queues

        # Fill data queue to capacity (1000 events)
        for i in range(1000):
            event = Event(EventType.CANDLE_UPDATE, {"id": i}, source="test")
            await bus.publish(event, queue_name="data")

        # Verify queue is full
        stats = bus.get_queue_stats()
        assert stats["data"]["size"] == 1000

        # Attempt to publish one more (should drop due to timeout)
        overflow_event = Event(EventType.CANDLE_UPDATE, {"id": 1000}, source="test")

        # Should not raise exception (drops gracefully)
        await bus.publish(overflow_event, queue_name="data")

        # Verify drop was counted
        stats_after = bus.get_queue_stats()
        assert stats_after["data"]["drops"] == 1

        # Queue still at capacity (event was dropped, not added)
        assert stats_after["data"]["size"] == 1000

    @pytest.mark.asyncio
    async def test_signal_queue_raises_timeout_when_full(self, event_bus_with_queues):
        """Verify signal queue raises TimeoutError when full (no drops)."""
        import asyncio

        bus = event_bus_with_queues

        # Fill signal queue to capacity (100 events)
        for i in range(100):
            event = Event(EventType.SIGNAL_GENERATED, {"id": i}, source="test")
            await bus.publish(event, queue_name="signal")

        # Verify queue is full
        stats = bus.get_queue_stats()
        assert stats["signal"]["size"] == 100

        # Attempt to publish one more (should raise TimeoutError)
        overflow_event = Event(EventType.SIGNAL_GENERATED, {"id": 100}, source="test")

        with pytest.raises(asyncio.TimeoutError):
            await bus.publish(overflow_event, queue_name="signal")

        # Verify no drops (signal queue never drops)
        stats_after = bus.get_queue_stats()
        assert stats_after["signal"]["drops"] == 0

    @pytest.mark.asyncio
    async def test_order_queue_blocks_indefinitely_when_full(self, event_bus_with_queues):
        """Verify order queue blocks without timeout (never drops)."""
        import asyncio

        bus = event_bus_with_queues

        # Fill order queue to capacity (50 events)
        for i in range(50):
            event = Event(EventType.ORDER_PLACED, {"id": i}, source="test")
            await bus.publish(event, queue_name="order")

        # Verify queue is full
        stats = bus.get_queue_stats()
        assert stats["order"]["size"] == 50

        # Attempt to publish with short timeout to verify blocking behavior
        overflow_event = Event(EventType.ORDER_PLACED, {"id": 50}, source="test")

        # Use wait_for to simulate timeout (order queue itself has no timeout)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                bus.publish(overflow_event, queue_name="order"),
                timeout=0.5,  # Short timeout to verify blocking
            )

        # Verify no drops (order queue NEVER drops)
        stats_after = bus.get_queue_stats()
        assert stats_after["order"]["drops"] == 0

    @pytest.mark.asyncio
    async def test_publish_raises_valueerror_for_invalid_queue(self, event_bus_with_queues):
        """Verify publish() validates queue_name parameter."""
        bus = event_bus_with_queues
        event = Event(EventType.CANDLE_UPDATE, {}, source="test")

        with pytest.raises(ValueError) as exc_info:
            await bus.publish(event, queue_name="invalid_queue")

        assert "Invalid queue_name 'invalid_queue'" in str(exc_info.value)
        assert "data" in str(exc_info.value)
        assert "signal" in str(exc_info.value)
        assert "order" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_queue_stats_reflects_current_state(self, event_bus_with_queues):
        """Verify get_queue_stats() returns accurate real-time data."""
        bus = event_bus_with_queues

        # Initial state
        stats = bus.get_queue_stats()
        assert stats["data"]["size"] == 0

        # Publish 10 events to data queue
        for i in range(10):
            event = Event(EventType.CANDLE_UPDATE, {"id": i}, source="test")
            await bus.publish(event, queue_name="data")

        # Verify stats updated
        stats_after = bus.get_queue_stats()
        assert stats_after["data"]["size"] == 10
        assert stats_after["data"]["drops"] == 0

        # Publish 5 to signal, 2 to order
        for i in range(5):
            await bus.publish(
                Event(EventType.SIGNAL_GENERATED, {"id": i}, source="test"), queue_name="signal"
            )
        for i in range(2):
            await bus.publish(
                Event(EventType.ORDER_PLACED, {"id": i}, source="test"), queue_name="order"
            )

        # Verify all queues tracked independently
        final_stats = bus.get_queue_stats()
        assert final_stats["data"]["size"] == 10
        assert final_stats["signal"]["size"] == 5
        assert final_stats["order"]["size"] == 2


class TestEventBusProcessors:
    """Test suite for Subtask 4.3: Async queue processors with error recovery."""

    @pytest.mark.asyncio
    async def test_processor_executes_async_handler(self, event_bus_with_queues):
        """Verify processor correctly awaits async handlers."""
        bus = event_bus_with_queues
        bus._running = True

        executed = []

        async def async_handler(event):
            await asyncio.sleep(0.01)  # Simulating async work
            executed.append(event.data)

        # Subscribe handler
        bus.subscribe(EventType.CANDLE_CLOSED, async_handler)

        # Publish event to data queue
        event = Event(EventType.CANDLE_CLOSED, {"test": "data"}, source="test")
        await bus.publish(event, queue_name="data")

        # Start processor (will process 1 event then we stop it)
        processor_task = asyncio.create_task(bus._process_queue("data"))
        await asyncio.sleep(0.05)  # Let it process
        bus._running = False
        await processor_task

        # Verify handler was executed
        assert len(executed) == 1
        assert executed[0] == {"test": "data"}

    @pytest.mark.asyncio
    async def test_processor_executes_sync_handler(self, event_bus_with_queues):
        """Verify processor correctly calls sync handlers."""
        bus = event_bus_with_queues
        bus._running = True

        executed = []

        def sync_handler(event):
            executed.append(event.data)

        bus.subscribe(EventType.CANDLE_CLOSED, sync_handler)

        event = Event(EventType.CANDLE_CLOSED, {"test": "sync"}, source="test")
        await bus.publish(event, queue_name="data")

        processor_task = asyncio.create_task(bus._process_queue("data"))
        await asyncio.sleep(0.05)
        bus._running = False
        await processor_task

        assert len(executed) == 1
        assert executed[0] == {"test": "sync"}

    @pytest.mark.asyncio
    async def test_processor_isolates_handler_errors(self, event_bus_with_queues):
        """Verify one handler error doesn't affect others."""
        bus = event_bus_with_queues
        bus._running = True

        executed = []

        def handler_1(event):
            executed.append("handler_1")

        def handler_2_fails(event):
            executed.append("handler_2_called")
            raise ValueError("Handler 2 intentional failure")

        def handler_3(event):
            executed.append("handler_3")

        # Subscribe all three handlers
        bus.subscribe(EventType.CANDLE_CLOSED, handler_1)
        bus.subscribe(EventType.CANDLE_CLOSED, handler_2_fails)
        bus.subscribe(EventType.CANDLE_CLOSED, handler_3)

        event = Event(EventType.CANDLE_CLOSED, {}, source="test")
        await bus.publish(event, queue_name="data")

        processor_task = asyncio.create_task(bus._process_queue("data"))
        await asyncio.sleep(0.05)
        bus._running = False
        await processor_task

        # Verify all handlers executed (2 succeeded, 1 failed but logged)
        assert "handler_1" in executed
        assert "handler_2_called" in executed
        assert "handler_3" in executed

    @pytest.mark.asyncio
    async def test_processor_continues_after_handler_error(self, event_bus_with_queues):
        """Verify processor processes multiple events despite errors."""
        bus = event_bus_with_queues
        bus._running = True

        executed_count = [0]

        def failing_handler(event):
            executed_count[0] += 1
            raise RuntimeError("Always fails")

        bus.subscribe(EventType.CANDLE_CLOSED, failing_handler)

        # Publish 3 events
        for i in range(3):
            event = Event(EventType.CANDLE_CLOSED, {"id": i}, source="test")
            await bus.publish(event, queue_name="data")

        processor_task = asyncio.create_task(bus._process_queue("data"))
        await asyncio.sleep(0.1)  # Let it process all 3
        bus._running = False
        await processor_task

        # Verify all 3 events were attempted (all failed but processor continued)
        assert executed_count[0] == 3

    @pytest.mark.asyncio
    async def test_processor_handles_empty_queue_timeout(self, event_bus_with_queues):
        """Verify processor continues when queue is empty (TimeoutError)."""
        bus = event_bus_with_queues
        bus._running = True

        # Start processor on empty queue
        processor_task = asyncio.create_task(bus._process_queue("data"))

        # Let it run for a bit (will hit TimeoutError multiple times)
        await asyncio.sleep(0.3)  # 3x the 0.1s timeout

        # Should still be running, not crashed
        assert not processor_task.done()

        # Stop gracefully
        bus._running = False
        await processor_task

    @pytest.mark.asyncio
    async def test_processor_stops_when_running_false(self, event_bus_with_queues):
        """Verify processor exits loop when _running flag set to False."""
        bus = event_bus_with_queues
        bus._running = True

        processor_task = asyncio.create_task(bus._process_queue("data"))
        await asyncio.sleep(0.05)  # Let it start

        # Stop processor
        bus._running = False

        # Should exit within ~0.1s (timeout period)
        await asyncio.wait_for(processor_task, timeout=0.5)

        # Verify task completed (not cancelled or error)
        assert processor_task.done()
        assert not processor_task.cancelled()

    @pytest.mark.asyncio
    async def test_handlers_execute_sequentially(self, event_bus_with_queues):
        """Verify handlers execute in order, not parallel."""
        bus = event_bus_with_queues
        bus._running = True

        execution_order = []

        async def handler_1(event):
            execution_order.append("start_1")
            await asyncio.sleep(0.01)
            execution_order.append("end_1")

        async def handler_2(event):
            execution_order.append("start_2")
            await asyncio.sleep(0.01)
            execution_order.append("end_2")

        bus.subscribe(EventType.CANDLE_CLOSED, handler_1)
        bus.subscribe(EventType.CANDLE_CLOSED, handler_2)

        event = Event(EventType.CANDLE_CLOSED, {}, source="test")
        await bus.publish(event, queue_name="data")

        processor_task = asyncio.create_task(bus._process_queue("data"))
        await asyncio.sleep(0.05)
        bus._running = False
        await processor_task

        # Verify sequential execution (1 completes before 2 starts)
        assert execution_order == ["start_1", "end_1", "start_2", "end_2"]


class TestEventBusLifecycle:
    """Test suite for Subtask 4.4: Lifecycle management with start/stop/shutdown."""

    @pytest.mark.asyncio
    async def test_start_creates_processor_tasks(self):
        """Verify start() spawns 3 processor tasks with names."""
        bus = EventBus()

        # Start in background
        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.1)  # Let processors start

        # Verify 3 tasks created
        assert len(bus._processor_tasks) == 3

        # Verify task names
        task_names = {task.get_name() for task in bus._processor_tasks}
        assert task_names == {"data_processor", "signal_processor", "order_processor"}

        # Verify tasks running
        for task in bus._processor_tasks:
            assert not task.done()

        # Cleanup
        bus.stop()
        await start_task

    @pytest.mark.asyncio
    async def test_processors_run_until_stopped(self):
        """Verify processors run continuously until stop() called."""
        bus = EventBus()

        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.3)  # Let run for 3x timeout period

        # Processors should still be running
        for task in bus._processor_tasks:
            assert not task.done()

        # Stop and verify exit
        bus.stop()
        await asyncio.wait_for(start_task, timeout=1.0)

        # All tasks should be done
        for task in bus._processor_tasks:
            assert task.done()

    @pytest.mark.asyncio
    async def test_stop_sets_running_flag(self):
        """Verify stop() sets _running=False immediately."""
        bus = EventBus()

        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.1)

        # Verify _running is True
        assert bus._running is True

        # Stop and verify flag
        bus.stop()
        assert bus._running is False

        await start_task

    @pytest.mark.asyncio
    async def test_processors_exit_after_stop(self):
        """Verify processors exit within 0.5s after stop()."""
        bus = EventBus()

        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.1)

        # Stop and measure exit time
        import time

        start_time = time.time()
        bus.stop()
        await asyncio.wait_for(start_task, timeout=1.0)
        elapsed = time.time() - start_time

        # Should exit within 0.5s (0.1s timeout * 5 iterations max)
        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_pending_events(self):
        """Verify shutdown() waits for queue.join()."""
        bus = EventBus()

        executed = []

        def handler(event):
            executed.append(event.data)

        bus.subscribe(EventType.CANDLE_CLOSED, handler)

        # Start processors
        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.1)

        # Publish events
        for i in range(3):
            event = Event(EventType.CANDLE_CLOSED, {"id": i}, source="test")
            await bus.publish(event, queue_name="data")

        # Shutdown gracefully
        await bus.shutdown(timeout=2.0)
        await start_task

        # Verify all events processed
        assert len(executed) == 3
        assert executed == [{"id": 0}, {"id": 1}, {"id": 2}]

    @pytest.mark.asyncio
    async def test_shutdown_timeout_prevents_hanging(self, caplog):
        """Verify shutdown() times out gracefully with warning."""
        import logging

        bus = EventBus()

        # Handler that blocks indefinitely
        async def blocking_handler(event):
            await asyncio.sleep(100)  # Simulates slow processing

        bus.subscribe(EventType.CANDLE_CLOSED, blocking_handler)

        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.1)

        # Publish event
        event = Event(EventType.CANDLE_CLOSED, {}, source="test")
        await bus.publish(event, queue_name="data")

        # Shutdown with short timeout
        with caplog.at_level(logging.WARNING):
            await bus.shutdown(timeout=0.5)

        await asyncio.wait_for(start_task, timeout=1.0)

        # Verify warning logged
        assert "didn't drain" in caplog.text
        assert "data" in caplog.text

    @pytest.mark.asyncio
    async def test_integration_start_publish_stop(self):
        """Full lifecycle: start → publish → stop → verify."""
        bus = EventBus()

        executed = []

        async def async_handler(event):
            await asyncio.sleep(0.01)
            executed.append(event.data)

        bus.subscribe(EventType.CANDLE_CLOSED, async_handler)
        bus.subscribe(EventType.SIGNAL_GENERATED, async_handler)

        # Start processors
        start_task = asyncio.create_task(bus.start())
        await asyncio.sleep(0.1)

        # Publish to multiple queues
        for i in range(5):
            await bus.publish(
                Event(EventType.CANDLE_CLOSED, {"candle": i}, source="test"), queue_name="data"
            )

        for i in range(3):
            await bus.publish(
                Event(EventType.SIGNAL_GENERATED, {"signal": i}, source="test"), queue_name="signal"
            )

        # Graceful shutdown
        await bus.shutdown(timeout=2.0)
        await start_task

        # Verify all events processed
        assert len(executed) == 8

        # Verify queue stats
        stats = bus.get_queue_stats()
        assert stats["data"]["size"] == 0
        assert stats["signal"]["size"] == 0
