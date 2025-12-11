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
            _queues: Three priority queues (data, signal, order)
            logger: Logger instance for debug/error tracking
            _running: Lifecycle flag (used in Subtask 4.4)
            _drop_count: Counter for dropped events per queue (monitoring)
        """
        # Subscriber registry: EventType → List[Callable]
        # defaultdict automatically creates empty list for new EventTypes
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)

        # Three priority queues with different capacities
        self._queues: Dict[str, asyncio.Queue] = {
            'data': asyncio.Queue(maxsize=1000),    # High throughput, can drop
            'signal': asyncio.Queue(maxsize=100),   # Medium priority, must process
            'order': asyncio.Queue(maxsize=50)      # Critical, never drop
        }

        # Logger for debugging subscription events
        self.logger = logging.getLogger(__name__)

        # Lifecycle flag (will be used in Subtask 4.4)
        self._running: bool = False

        # Monitoring: track dropped events per queue
        self._drop_count: Dict[str, int] = {
            'data': 0,
            'signal': 0,
            'order': 0
        }

        self.logger.debug(
            "EventBus initialized with queues: "
            f"data(1000), signal(100), order(50)"
        )

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
        handler_name = getattr(handler, '__name__', repr(handler))
        self.logger.debug(
            f"Handler '{handler_name}' subscribed to {event_type.value}"
        )

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

    async def publish(
        self,
        event: Event,
        queue_name: str = 'data'
    ) -> None:
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
        # 1. Validate queue name
        if queue_name not in self._queues:
            raise ValueError(
                f"Invalid queue_name '{queue_name}'. "
                f"Must be one of: {list(self._queues.keys())}"
            )

        queue = self._queues[queue_name]

        # 2. Define timeout strategy per queue type
        timeout_map = {
            'data': 1.0,    # Drop quickly for high-frequency data
            'signal': 5.0,  # Wait longer for important signals
            'order': None   # Never timeout for critical orders
        }
        timeout = timeout_map[queue_name]

        # 3. Attempt to publish with timeout
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
                await asyncio.wait_for(
                    queue.put(event),
                    timeout=timeout
                )
                self.logger.debug(
                    f"Published {event.event_type.value} to {queue_name} queue "
                    f"(qsize={queue.qsize()})"
                )

        except asyncio.TimeoutError:
            # 4. Handle timeout based on queue criticality
            if queue_name == 'data':
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
                'size': queue.qsize(),
                'maxsize': queue.maxsize,
                'drops': self._drop_count[queue_name]
            }
            for queue_name, queue in self._queues.items()
        }
