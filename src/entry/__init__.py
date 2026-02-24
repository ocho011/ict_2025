"""
Entry determination module.

Provides abstract base class and data types for entry signal determination.
Entry determiners decide WHEN and at WHAT PRICE to enter a trade.
"""

from src.entry.base import EntryContext, EntryDecision, EntryDeterminer
from src.entry.always_entry import AlwaysEntryDeterminer
from src.entry.sma_entry import SMAEntryDeterminer

# ICTEntryDeterminer moved to src.strategies.ict.entry
# Backward compat: `from src.entry.ict_entry import ICTEntryDeterminer` still works

__all__ = [
    "EntryDeterminer",
    "EntryContext",
    "EntryDecision",
    "AlwaysEntryDeterminer",
    "SMAEntryDeterminer",
]
