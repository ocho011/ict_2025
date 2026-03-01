"""
Configuration update events for strategy hot reload.

Separate from trading events (Event/EventType in src/models/event.py)
because config events have different lifecycle and frequency.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ConfigUpdateEvent:
    """
    Setting change event from UI.

    Dispatched when UI modifies a symbol's module configuration.
    StrategyHotReloader listens and acts accordingly.
    """
    symbol: str
    category: str  # 'entry' | 'stop_loss' | 'take_profit' | 'exit'
    module_type: Optional[str] = None  # None = params-only change
    params: Dict[str, Any] = field(default_factory=dict)
    requires_strategy_rebuild: bool = False


@dataclass(frozen=True)
class ConfigReloadCompleteEvent:
    """Emitted after strategy replacement completes."""
    symbol: str
    old_strategy_name: str
    new_strategy_name: str
    positions_closed: int
