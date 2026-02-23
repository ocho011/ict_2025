"""
Exit determination module.

Provides abstract base class and data types for exit signal determination.
Exit determiners decide WHEN to exit an open position.
"""

from src.exit.base import ExitContext, ExitDeterminer, NullExitDeterminer

# ICTExitDeterminer moved to src.strategies.ict.exit
# Backward compat: `from src.exit.ict_exit import ICTExitDeterminer` still works

__all__ = [
    "ExitDeterminer",
    "ExitContext",
    "NullExitDeterminer",
]
