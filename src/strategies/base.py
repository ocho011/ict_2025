"""
Abstract base class for trading strategies.

Defines the strategy interface contract. Buffer management is delegated
to BufferManager (composition); backward-compatible properties/methods
are thin wrappers that forward to the internal BufferManager instance.
"""

import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING, Dict, List, Optional

from src.models.candle import Candle
from src.models.module_requirements import ModuleRequirements
from src.models.position import Position
from src.models.signal import Signal
from src.strategies.buffer_manager import BufferManager

if TYPE_CHECKING:
    from src.strategies.feature_store import FeatureStore


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Provides:
    - Unified buffer management via BufferManager (Issue #27)
    - Standard interface for signal generation
    - Configuration management

    Subclasses must implement:
    - analyze(): Main strategy logic for signal generation
    - should_exit(): Exit evaluation for open positions
    """

    def __init__(
        self, symbol: str, config: dict, intervals: Optional[List[str]] = None
    ) -> None:
        self.symbol: str = symbol
        self.config: dict = config
        self.buffer_size: int = config.get("buffer_size", 100)

        # Determine intervals from parameter or config
        if intervals is not None:
            _intervals = list(intervals)
        else:
            default_interval = config.get("default_interval", "1m")
            _intervals = [default_interval]

        # Delegate buffer management to BufferManager
        self._buffer = BufferManager(self.buffer_size, _intervals)

        # Feature store for centralized indicator management (composable architecture)
        self._feature_store: Optional["FeatureStore"] = None

        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Backward-compatible buffer access (delegation to BufferManager)
    # ------------------------------------------------------------------

    @property
    def buffers(self) -> Dict[str, deque]:
        return self._buffer.buffers

    @property
    def intervals(self) -> List[str]:
        return self._buffer.intervals

    @intervals.setter
    def intervals(self, value: List[str]) -> None:
        self._buffer.intervals = value

    @property
    def _initialized(self) -> Dict[str, bool]:
        return self._buffer._initialized

    def get_buffer(self, interval: str) -> Optional[deque]:
        """Get the candle buffer for a specific interval."""
        return self.buffers.get(interval)

    def initialize_with_historical_data(
        self, candles: List[Candle], interval: Optional[str] = None
    ) -> None:
        """Initialize strategy buffer with historical candle data."""
        def _on_initialized(target_interval: str, candle_list: List[Candle]) -> None:
            # Note: FeatureStore initialization is now handled by TradingEngine
            # to coordinate across multiple strategies/intervals if needed.
            pass

        self._buffer.initialize(candles, interval, on_initialized=_on_initialized)

    def update_buffer(self, candle: Candle) -> None:
        """Add candle to appropriate buffer based on candle.interval."""
        self._buffer.update(candle)

    def get_latest_candles(
        self, count: int, interval: Optional[str] = None
    ) -> List[Candle]:
        """Get the most recent N candles from buffer."""
        return self._buffer.get_latest(count, interval)

    def get_buffer_size_current(self, interval: Optional[str] = None) -> int:
        """Get current number of candles in buffer."""
        return self._buffer.get_current_size(interval)

    def is_buffer_ready(self, min_candles: int, interval: Optional[str] = None) -> bool:
        """Check if buffer has minimum required candles for analysis."""
        return self._buffer.is_buffer_ready(min_candles, interval)

    def is_ready(self) -> bool:
        """Check if all intervals have been initialized."""
        return self._buffer.is_all_ready()

    # ------------------------------------------------------------------
    # Data requirements
    # ------------------------------------------------------------------

    @property
    def data_requirements(self) -> ModuleRequirements:
        """Aggregated data requirements. ComposableStrategy overrides."""
        return ModuleRequirements.empty()

    # ------------------------------------------------------------------
    # Feature store
    # ------------------------------------------------------------------

    @property
    def feature_store(self) -> Optional["FeatureStore"]:
        """Get the feature store instance."""
        return self._feature_store

    def set_feature_store(self, store: "FeatureStore") -> None:
        """Set the feature store for centralized indicator management."""
        self._feature_store = store
        self.logger.info("FeatureStore configured for %s", self.symbol)

    def _update_feature_cache(self, candle: Candle) -> None:
        """Update feature store with new candle data."""
        # Note: FeatureStore.update is called by TradingEngine directly
        pass

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle and generate trading signal if conditions met.

        Called by TradingEngine for each new candle. Subclasses implement
        strategy logic here.

        Args:
            candle: Latest candle to analyze.

        Returns:
            Signal if conditions met, None otherwise.
        """

    @abstractmethod
    async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
        """
        Evaluate whether an open position should be exited.

        Called by TradingEngine when a position exists. Returns exit signal
        or None to keep position open.

        Args:
            position: Current open position.
            candle: Latest candle to analyze for exit conditions.

        Returns:
            Signal with CLOSE_LONG/CLOSE_SHORT if exit triggered, None otherwise.
        """

    async def check_exit(self, candle: Candle, position: Position) -> Optional[Signal]:
        """
        Optional exit check. Subclasses can override for custom exit logic
        (trailing stops, time-based exits, etc.).

        Default: returns None (positions exit via TP/SL orders only).
        """
        return None
