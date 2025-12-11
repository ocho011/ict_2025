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
        Initialize EventBus with empty subscriber registry.

        Attributes:
            _subscribers: Maps EventType to list of handler functions
            logger: Logger instance for debug/error tracking
            _running: Lifecycle flag (used in Subtask 4.4)
        """
        # Subscriber registry: EventType → List[Callable]
        # defaultdict automatically creates empty list for new EventTypes
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)

        # Logger for debugging subscription events
        self.logger = logging.getLogger(__name__)

        # Lifecycle flag (will be used in Subtask 4.4)
        self._running: bool = False

        self.logger.debug("EventBus initialized")

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
