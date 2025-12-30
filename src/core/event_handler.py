"""
Event-driven system coordinator with multi-queue support
"""

import asyncio  # Used in future subtasks (4.2+)
import logging
from collections import defaultdict
from typing import Callable, Dict, List

from src.models.event import Event, EventType


class EventBus:
    """
    Central event coordination with subscriber registry.

    This class implements the pub-sub pattern foundation for event-driven
    architecture. In Subtask 4.1, we focus on subscriber management only.
    Queue system and publishing will be added in subsequent subtasks.

    Architecture:
        - Type-safe event routing via EventType enum
        - Multiple handlers per event type
        - Support for both sync and async handlers
        - Thread-safe subscriber storage with defaultdict

    Lifecycle:
        - Subtask 4.1: Subscriber registry and routing
        - Subtask 4.2: Queue system and publishing
        - Subtask 4.3: Async queue processors
        - Subtask 4.4: Lifecycle management (start/stop/shutdown)
    """

    def __init__(self):
        """
        Initialize EventBus with subscriber registry and multi-queue system.

        Attributes:
            _subscribers: Maps EventType to list of handler functions
            _queues: Three priority queues (data, signal, order) - created in start()
            logger: Logger instance for debug/error tracking
            _running: Lifecycle flag for processor control
            _drop_count: Counter for dropped events per queue (monitoring)
            _processor_tasks: List of processor task references for cancellation

        Notes:
            - Queues are created lazily in start() to ensure proper event loop binding
            - Creating queues in __init__ causes "attached to different loop" errors
        """
        # Subscriber registry: EventType → List[Callable]
        # defaultdict automatically creates empty list for new EventTypes
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)

        # Three priority queues - will be created in start() with proper event loop
        # Creating them here causes RuntimeError when event loop changes
        self._queues: Dict[str, asyncio.Queue] = {}

        # Logger for debugging subscription events
        self.logger = logging.getLogger(__name__)

        # Lifecycle flag for processor control
        self._running: bool = False

        # Processor task references for cancellation during shutdown
        self._processor_tasks: List[asyncio.Task] = []

        # Monitoring: track dropped events per queue
        self._drop_count: Dict[str, int] = {"data": 0, "signal": 0, "order": 0}

        self.logger.debug("EventBus initialized (queues will be created in start())")

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """
        Register a handler function for a specific event type.

        This method implements the "subscribe" side of the pub-sub pattern.
        Multiple handlers can subscribe to the same event type, and all will
        be called when that event is published.

        Args:
            event_type: The type of event to subscribe to (EventType enum)
            handler: Callable to invoke when event occurs. Can be sync or async.
                     Signature: (Event) -> None or (Event) -> Awaitable[None]

        Notes:
            - No duplicate checking: Same handler can subscribe multiple times
            - Both sync and async handlers supported (checked at execution time)
            - Thread-safe: defaultdict handles concurrent subscriptions

        Example:
            ```python
            bus = EventBus()

            def my_handler(event: Event):
                print(f"Received: {event.data}")

            async def async_handler(event: Event):
                await asyncio.sleep(0.1)
                print(f"Async received: {event.data}")

            bus.subscribe(EventType.CANDLE_CLOSED, my_handler)
            bus.subscribe(EventType.CANDLE_CLOSED, async_handler)
            ```
        """
        # Add handler to the list for this event type
        self._subscribers[event_type].append(handler)

        # Log subscription for debugging
        handler_name = getattr(handler, "__name__", repr(handler))
        self.logger.debug(f"Handler '{handler_name}' subscribed to {event_type.value}")

    def _get_handlers(self, event_type: EventType) -> List[Callable]:
        """
        Retrieve all handlers registered for a specific event type.

        This is a helper method used internally by event processors
        (to be implemented in Subtask 4.3).

        Args:
            event_type: The event type to get handlers for

        Returns:
            List of handler callables. Empty list if no handlers registered.

        Notes:
            - Returns a reference to the internal list (not a copy)
            - Safe to iterate: defaultdict ensures list exists
            - Empty list is safe to iterate (no special handling needed)

        Example:
            ```python
            handlers = bus._get_handlers(EventType.CANDLE_CLOSED)
            for handler in handlers:
                handler(event)  # Will execute 0+ times
            ```
        """
        return self._subscribers[event_type]

    async def publish(self, event: Event, queue_name: str = "data") -> None:
        """
        Publish event to specified queue with overflow handling.

        This method implements the "publish" side of the pub-sub pattern.
        Events are routed to one of three priority queues based on criticality.

        Args:
            event: Event to publish (from src.models.event.Event)
            queue_name: Target queue ('data', 'signal', 'order'). Defaults to 'data'.

        Raises:
            ValueError: If queue_name is not in ['data', 'signal', 'order']
            asyncio.TimeoutError: For signal/order queues if timeout exceeded

        Overflow Handling:
            - data queue: Drop event on timeout, log warning, increment drop_count
            - signal queue: Block for up to 5s, raise TimeoutError if full
            - order queue: Block indefinitely (no timeout), never drop

        Example:
            ```python
            bus = EventBus()

            # High-frequency data (may drop under load)
            await bus.publish(
                Event(EventType.CANDLE_UPDATE, candle),
                queue_name='data'
            )

            # Trading signal (must process, creates backpressure)
            await bus.publish(
                Event(EventType.SIGNAL_GENERATED, signal),
                queue_name='signal'
            )

            # Critical order (never drops, blocks indefinitely)
            await bus.publish(
                Event(EventType.ORDER_PLACED, order),
                queue_name='order'
            )
            ```

        Notes:
            - Data queue drops are expected under high load (design feature)
            - Signal/order timeouts indicate system overload (needs investigation)
            - Monitor drop_count via get_queue_stats() for operational alerts
        """
        # 1. Validate queues are initialized
        if not self._queues:
            raise RuntimeError(
                "EventBus queues not initialized. " "Call start() before publishing events."
            )

        # 2. Validate queue name
        if queue_name not in self._queues:
            raise ValueError(
                f"Invalid queue_name '{queue_name}'. "
                f"Must be one of: {list(self._queues.keys())}"
            )

        queue = self._queues[queue_name]

        # 3. Define timeout strategy per queue type
        timeout_map = {
            "data": 1.0,  # Drop quickly for high-frequency data
            "signal": 5.0,  # Wait longer for important signals
            "order": None,  # Never timeout for critical orders
        }
        timeout = timeout_map[queue_name]

        # 4. Attempt to publish with timeout
        try:
            if timeout is None:
                # Order queue: block indefinitely, never drop
                await queue.put(event)
                self.logger.debug(
                    f"Published {event.event_type.value} to {queue_name} queue "
                    f"(qsize={queue.qsize()})"
                )
            else:
                # Data/Signal queues: timeout-based overflow handling
                await asyncio.wait_for(queue.put(event), timeout=timeout)
                self.logger.debug(
                    f"Published {event.event_type.value} to {queue_name} queue "
                    f"(qsize={queue.qsize()})"
                )

        except asyncio.TimeoutError:
            # 5. Handle timeout based on queue criticality
            if queue_name == "data":
                # Data queue: drop is acceptable, log and continue
                self._drop_count[queue_name] += 1
                self.logger.warning(
                    f"Dropped {event.event_type.value} from {queue_name} queue "
                    f"(full, timeout={timeout}s). "
                    f"Total drops: {self._drop_count[queue_name]}"
                )
            else:
                # Signal/Order queues: timeout is serious, re-raise
                self.logger.error(
                    f"Failed to publish {event.event_type.value} to "
                    f"{queue_name} queue (timeout={timeout}s, "
                    f"qsize={queue.qsize()}). System overload!"
                )
                raise

    async def _process_queue(self, queue_name: str) -> None:
        """
        Continuously process events from the specified queue.

        This is the core event processing loop. It runs continuously while
        _running=True, polling the queue for events and dispatching them to
        registered handlers with comprehensive error isolation.

        Args:
            queue_name: Name of queue to process ('data', 'signal', or 'order')

        Process Flow:
            1. Poll queue with 0.1s timeout (non-blocking)
            2. Get handlers registered for event type
            3. Execute each handler sequentially (sync or async)
            4. Isolate handler errors (one fails → others continue)
            5. Mark queue task as done
            6. Repeat until _running=False

        Error Handling:
            - Handler exceptions: Logged with exc_info=True, continue processing
            - Queue TimeoutError: Expected when empty, continue loop
            - Other exceptions: Logged as critical, continue loop

        Performance:
            - Handler execution is sequential (guarantees ordering)
            - Empty queue polling: 10 iterations/sec (0.1s timeout)
            - Handlers should be fast (<10ms); heavy work → spawn tasks

        Example:
            ```python
            # In Subtask 4.4, start() will spawn processor tasks:
            async def start(self):
                self._running = True
                tasks = [
                    asyncio.create_task(self._process_queue('data')),
                    asyncio.create_task(self._process_queue('signal')),
                    asyncio.create_task(self._process_queue('order'))
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
            ```

        Notes:
            - Sequential handler execution prevents race conditions
            - Handler isolation prevents cascade failures
            - 0.1s timeout allows responsive shutdown (checks _running flag)
            - Method is private (internal to EventBus lifecycle)
        """
        queue = self._queues[queue_name]

        self.logger.info(f"Starting {queue_name} queue processor")

        while self._running:
            try:
                # 1. Poll queue with timeout (non-blocking)
                event = await asyncio.wait_for(
                    queue.get(), timeout=0.1  # Check _running flag 10x per second
                )

                # 2. Get handlers for this event type
                handlers = self._get_handlers(event.event_type)

                if not handlers:
                    self.logger.debug(
                        f"No handlers for {event.event_type.value} in {queue_name} queue"
                    )

                # 3. Execute each handler sequentially with error isolation
                for handler in handlers:
                    handler_name = getattr(handler, "__name__", repr(handler))

                    try:
                        # Detect async vs sync handler
                        if asyncio.iscoroutinefunction(handler):
                            self.logger.debug(
                                f"Executing async handler '{handler_name}' "
                                f"for {event.event_type.value}"
                            )
                            await handler(event)
                        else:
                            self.logger.debug(
                                f"Executing sync handler '{handler_name}' "
                                f"for {event.event_type.value}"
                            )
                            handler(event)  # Direct call for sync handlers

                    except Exception as e:
                        # Handler error: log but continue processing other handlers
                        self.logger.error(
                            f"Handler '{handler_name}' failed for "
                            f"{event.event_type.value} in {queue_name} queue: {e}",
                            exc_info=True,  # Include full traceback
                        )
                        # Don't raise - continue to next handler

                # 4. Mark task as done (for queue.join() in shutdown)
                queue.task_done()

            except asyncio.TimeoutError:
                # No event available - not an error, continue loop
                continue

            except Exception as e:
                # Unexpected processor error (shouldn't happen, but be defensive)
                self.logger.critical(f"Processor error in {queue_name} queue: {e}", exc_info=True)
                # Don't crash processor - continue loop

        self.logger.info(f"Stopped {queue_name} queue processor")

    def get_queue_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Get current queue statistics for monitoring.

        Returns dict with queue sizes, capacities, and drop counts:
        {
            'data': {'size': 42, 'maxsize': 1000, 'drops': 5},
            'signal': {'size': 3, 'maxsize': 100, 'drops': 0},
            'order': {'size': 0, 'maxsize': 50, 'drops': 0}
        }

        Useful for:
        - Operational monitoring and alerting
        - Performance tuning (queue sizing)
        - Capacity planning
        - Debugging event flow bottlenecks

        Example:
            ```python
            stats = bus.get_queue_stats()

            # Alert if data queue is consistently full
            if stats['data']['size'] > 900:
                logger.warning("Data queue near capacity!")

            # Alert on any signal drops (should never happen)
            if stats['signal']['drops'] > 0:
                logger.critical("Signal queue dropped events!")
            ```
        """
        return {
            queue_name: {
                "size": queue.qsize(),
                "maxsize": queue.maxsize,
                "drops": self._drop_count[queue_name],
            }
            for queue_name, queue in self._queues.items()
        }

    async def start(self) -> None:
        """
        Start all queue processors and run until stop() is called.

        Creates three processor tasks (data, signal, order) and runs them
        concurrently using asyncio.gather with return_exceptions=True to
        prevent single task failure from crashing the entire EventBus.

        Process Flow:
            1. Create queues with current event loop (if not already created)
            2. Set _running flag to True
            3. Create 3 processor tasks with descriptive names
            4. Store task references in _processor_tasks
            5. Wait for all tasks with gather (blocks until stop())

        Error Handling:
            - return_exceptions=True logs task errors without propagating
            - Individual processor errors don't crash EventBus
            - Task names enable debugging (data_processor, signal_processor, order_processor)

        Lifecycle:
            - Blocks until stop() sets _running=False
            - Processors exit their loops on _running=False
            - gather completes when all processors exit

        Example:
            ```python
            bus = EventBus()
            # Register handlers first
            bus.subscribe(EventType.CANDLE_CLOSED, handler)

            # Start processors (blocks until stop())
            asyncio.create_task(bus.start())

            # Later, to stop:
            bus.stop()  # Processors exit within 0.5s
            ```

        Notes:
            - Must call stop() to exit (or KeyboardInterrupt)
            - Use shutdown() for graceful cleanup with pending events
            - Task names aid debugging in asyncio task list
            - Queues created here to ensure proper event loop binding
        """
        # Create queues with current event loop (prevents "different loop" errors)
        if not self._queues:
            self._queues = {
                "data": asyncio.Queue(maxsize=1000),  # High throughput, can drop
                "signal": asyncio.Queue(maxsize=100),  # Medium priority, must process
                "order": asyncio.Queue(maxsize=50),  # Critical, never drop
            }
            self.logger.debug(
                "Created queues with current event loop: data(1000), signal(100), order(50)"
            )

        self._running = True
        self.logger.info("Starting EventBus processors")

        # Create processor tasks with descriptive names
        self._processor_tasks = [
            asyncio.create_task(self._process_queue("data"), name="data_processor"),
            asyncio.create_task(self._process_queue("signal"), name="signal_processor"),
            asyncio.create_task(self._process_queue("order"), name="order_processor"),
        ]

        # Wait for all processors (runs until stop() called)
        # return_exceptions=True prevents single task error from crashing EventBus
        await asyncio.gather(*self._processor_tasks, return_exceptions=True)

        self.logger.info("EventBus processors stopped")

    def stop(self) -> None:
        """
        Signal all processors to stop by setting _running flag.

        This is a non-blocking operation that signals processors to exit
        their loops. Processors will finish their current event and exit
        within approximately 0.1s (the queue polling timeout).

        Process Flow:
            1. Log stop request
            2. Set _running=False
            3. Return immediately

        Timing:
            - Non-blocking call (returns immediately)
            - Processors check _running every 0.1s (timeout period)
            - Expect processors to exit within 0.5s

        Usage:
            ```python
            # In main application or signal handler
            event_bus.stop()  # Signal shutdown

            # Optionally wait for graceful cleanup
            await event_bus.shutdown(timeout=10.0)
            ```

        Notes:
            - Does NOT wait for processors to exit
            - Does NOT cancel tasks (use shutdown() for that)
            - Safe to call multiple times (idempotent)
            - Typically followed by shutdown() for cleanup
        """
        self.logger.info("Stopping EventBus processors")
        self._running = False

    async def shutdown(self, timeout: float = 5.0) -> None:
        """
        Gracefully shutdown EventBus with pending event processing.

        Performs graceful shutdown sequence:
        1. Wait for queues to drain (all events processed)
        2. Stop processors (set _running=False)
        3. Cancel processor tasks if needed

        Args:
            timeout: Max seconds to wait per queue for pending events (default: 5.0)

        Process Flow:
            1. For each queue, wait for queue.join() with timeout
            2. If timeout: log warning, continue to next queue
            3. Call stop() to signal processors
            4. Wait briefly for processors to exit gracefully
            5. Cancel processor tasks if still running

        Error Handling:
            - TimeoutError per queue: logged as warning, continues
            - Task cancellation: always attempted (defensive)
            - Pending events logged if timeout exceeded

        Example:
            ```python
            try:
                await event_bus.start()
            except KeyboardInterrupt:
                await event_bus.shutdown(timeout=10.0)
                # All pending events processed or timeout logged
            ```

        Critical for Trading:
            - Order queue events MUST be processed or logged
            - Timeout prevents indefinite hanging
            - Cancellation as last resort

        Notes:
            - Drains queues BEFORE stopping processors
            - Timeout applies PER QUEUE (total time = 3 * timeout)
            - Defensive hasattr check for _processor_tasks
            - 0.5s grace period for processor exit
        """
        self.logger.info("Shutting down EventBus gracefully")

        # Wait for queues to drain (all events processed)
        for queue_name, queue in self._queues.items():
            try:
                self.logger.debug(
                    f"Waiting for {queue_name} queue to drain " f"(pending: {queue.qsize()})"
                )
                await asyncio.wait_for(queue.join(), timeout=timeout)
                self.logger.debug(f"Queue {queue_name} drained successfully")

            except asyncio.TimeoutError:
                pending = queue.qsize()
                self.logger.warning(
                    f"Queue {queue_name} didn't drain in {timeout}s "
                    f"({pending} events remaining). Proceeding with shutdown."
                )
                # Continue to next queue (don't block shutdown)

        # Signal processors to stop AFTER queues drained
        self.stop()

        # Wait briefly for processors to exit gracefully
        await asyncio.sleep(0.5)

        # Cancel processor tasks if still running (defensive check)
        if hasattr(self, "_processor_tasks") and self._processor_tasks:
            self.logger.debug(f"Cancelling {len(self._processor_tasks)} processor tasks")
            for task in self._processor_tasks:
                if not task.done():
                    task.cancel()

        self.logger.info("EventBus shutdown complete")
