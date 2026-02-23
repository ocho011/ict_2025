"""
Buffer management for trading strategies.

Extracted from BaseStrategy to separate buffer lifecycle (init, update, query)
from strategy logic (analyze, exit). Uses composition pattern — BaseStrategy
delegates buffer operations to BufferManager via thin wrappers.

Performance: All operations are O(1) for append/evict (deque with maxlen).
"""

import logging
from collections import deque
from typing import Callable, Dict, List, Optional

from src.models.candle import Candle


class BufferManager:
    """Manages candle buffers for single/multi-timeframe strategies."""

    def __init__(self, buffer_size: int, intervals: List[str]) -> None:
        self.buffer_size: int = buffer_size
        self.intervals: List[str] = list(intervals)
        self.buffers: Dict[str, deque] = {
            iv: deque(maxlen=buffer_size) for iv in self.intervals
        }
        self._initialized: Dict[str, bool] = {
            iv: False for iv in self.intervals
        }
        self.logger = logging.getLogger(self.__class__.__name__)

    def initialize(
        self,
        candles: List[Candle],
        interval: Optional[str] = None,
        on_initialized: Optional[Callable[[str, List[Candle]], None]] = None,
    ) -> None:
        """
        Initialize buffer with historical candle data.

        Called once during system startup after backfilling completes.
        Does NOT trigger signal generation — used only for warmup phase.

        Args:
            candles: Historical candles in chronological order (oldest first).
            interval: Target interval. If None, auto-detects from candles or uses first.
            on_initialized: Optional callback(target_interval, candle_list) invoked
                after buffer is populated (e.g. for indicator cache warmup).
        """
        # Determine target interval
        if interval is not None:
            target_interval = interval
        elif candles and hasattr(candles[0], "interval"):
            target_interval = candles[0].interval
        else:
            target_interval = self.intervals[0] if self.intervals else "1m"

        # Validate interval is registered
        if target_interval not in self.buffers:
            self.logger.warning(
                "Interval '%s' not registered. Registered: %s. "
                "Creating new buffer for this interval.",
                target_interval, self.intervals,
            )
            self.intervals.append(target_interval)
            self.buffers[target_interval] = deque(maxlen=self.buffer_size)
            self._initialized[target_interval] = False

        if not candles:
            self.logger.warning(
                "No historical candles provided for %s. "
                "Strategy will start with empty buffer.",
                target_interval,
            )
            self._initialized[target_interval] = True
            return

        self.logger.info(
            "Initializing %s buffer with %d historical candles",
            target_interval, len(candles),
        )

        # Clear existing buffer (in case of re-initialization)
        self.buffers[target_interval].clear()

        # Add candles respecting maxlen (keeps most recent)
        for candle in candles[-self.buffer_size:]:
            self.buffers[target_interval].append(candle)

        # Mark interval as initialized
        self._initialized[target_interval] = True

        self.logger.info(
            "%s initialization complete: %d candles in buffer",
            target_interval, len(self.buffers[target_interval]),
        )

        # Callback for indicator cache initialization
        if on_initialized is not None:
            on_initialized(target_interval, list(self.buffers[target_interval]))

    def update(self, candle: Candle) -> None:
        """
        Add candle to appropriate buffer based on candle.interval.

        Auto-registers unknown intervals. O(1) append with FIFO eviction.
        """
        interval = candle.interval

        if interval not in self.buffers:
            self.logger.debug(
                "Auto-registering interval '%s'", interval,
            )
            self.intervals.append(interval)
            self.buffers[interval] = deque(maxlen=self.buffer_size)
            self._initialized[interval] = True

        self.buffers[interval].append(candle)

    def get_latest(self, count: int, interval: Optional[str] = None) -> List[Candle]:
        """Get the most recent N candles from buffer. Empty list if insufficient."""
        target_interval = interval or (self.intervals[0] if self.intervals else None)
        if not target_interval or target_interval not in self.buffers:
            return []

        buffer = self.buffers[target_interval]
        if len(buffer) < count:
            return []
        return list(buffer)[-count:]

    def get_current_size(self, interval: Optional[str] = None) -> int:
        """Get current number of candles in buffer."""
        target_interval = interval or (self.intervals[0] if self.intervals else None)
        if not target_interval or target_interval not in self.buffers:
            return 0
        return len(self.buffers[target_interval])

    def is_buffer_ready(self, min_candles: int, interval: Optional[str] = None) -> bool:
        """Check if buffer has minimum required candles for analysis."""
        target_interval = interval or (self.intervals[0] if self.intervals else None)
        if not target_interval or target_interval not in self.buffers:
            return False
        return len(self.buffers[target_interval]) >= min_candles

    def is_all_ready(self) -> bool:
        """Check if all intervals have been initialized."""
        return all(self._initialized.values())
