"""
Event-driven system coordinator
"""

from typing import Callable, Dict, Any


class EventHandler:
    """
    Coordinates system events and data flow
    """

    def __init__(self):
        self._handlers: Dict[str, list[Callable]] = {}

    def subscribe(self, event: str, handler: Callable):
        """Subscribe to an event"""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    async def emit(self, event: str, data: Any):
        """Emit an event to all subscribers"""
        if event in self._handlers:
            for handler in self._handlers[event]:
                await handler(data)
