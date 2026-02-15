"""Protocol for strategies that provide trailing stop levels."""
from typing import Dict, Protocol, runtime_checkable


@runtime_checkable
class TrailingLevelProvider(Protocol):
    """Protocol for accessing trailing stop levels.

    Implemented by:
    - ComposableStrategy (delegates to exit determiner)
    - ICTExitDeterminer (owns _trailing_levels dict)
    """

    @property
    def trailing_levels(self) -> Dict[str, float]:
        """Return dict of trailing levels keyed by '{symbol}_{side}'."""
        ...
