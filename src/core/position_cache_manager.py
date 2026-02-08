"""Position cache manager for low-latency position state tracking.

This module provides PositionCacheManager, which maintains a time-based cache
of position states to minimize REST API calls during high-frequency trading.
The cache is kept synchronized with real-time WebSocket updates.

Key features:
- TTL-based cache invalidation (default 60s)
- WebSocket-driven cache updates for sub-second freshness
- Graceful handling of API failures (Issue #41)
- Signal cooldown tracking coupled with cache invalidation (Issue #101)
"""

import logging
import time
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from src.models.position import Position


class PositionCacheManager:
    """Manages position cache with TTL-based expiration and WebSocket updates.

    Extracted from TradingEngine to separate position cache management
    from engine orchestration (Issue #110 Phase 1).

    Attributes:
        _order_gateway: OrderGateway instance for position queries
        _config_manager: ConfigManager for trading configuration (leverage)
        _cache: Position cache with timestamps (symbol -> (Position|None, timestamp))
        _ttl: Cache time-to-live in seconds
        _last_signal_time: Signal cooldown tracking (symbol -> timestamp)
    """

    def __init__(
        self,
        order_gateway,
        config_manager,
        ttl: float = 60.0,
    ):
        self._order_gateway = order_gateway
        self._config_manager = config_manager
        self._cache: dict[str, tuple[Optional["Position"], float]] = {}
        self._ttl = ttl
        self._last_signal_time: Dict[str, float] = {}
        self.logger = logging.getLogger(__name__)

    @property
    def cache(self) -> dict[str, tuple[Optional["Position"], float]]:
        """Access internal cache dict (needed by EventDispatcher for uncertain state check)."""
        return self._cache

    def get(self, symbol: str) -> Optional["Position"]:
        """
        Get cached position for symbol, refreshing if TTL expired.

        Uses cached position to reduce API rate limit pressure.
        Cache TTL is 60 seconds by default.

        Args:
            symbol: Trading pair to get position for

        Returns:
            Position if exists and cache valid, None otherwise
            (Returns None on API failure to prevent using stale/uncertain data - Issue #41)
        """
        current_time = time.time()

        # Check if cache exists and is still valid
        if symbol in self._cache:
            cached_position, cache_time = self._cache[symbol]
            if current_time - cache_time < self._ttl:
                return cached_position

        # Cache expired or missing - refresh from API
        try:
            position = self._order_gateway.get_position(symbol)
            self._cache[symbol] = (position, current_time)
            return position
        except Exception as e:
            self.logger.error(
                f"Failed to refresh position cache for {symbol}: {e}. "
                f"Returning None to indicate uncertain state (Issue #41)."
            )
            # CRITICAL: Do NOT update self._cache[symbol] here.
            # This allows callers to distinguish between success (None in cache)
            # and failure (expired data in cache).
            return None

    def invalidate(self, symbol: str) -> None:
        """
        Invalidate position cache for symbol.

        Called after order execution to ensure fresh position data
        is fetched on next check.

        Args:
            symbol: Trading pair to invalidate cache for
        """
        if symbol in self._cache:
            del self._cache[symbol]
            self.logger.debug(f"Position cache invalidated for {symbol}")
        # Clear signal cooldown so new entries are possible after position close (Issue #101)
        if symbol in self._last_signal_time:
            del self._last_signal_time[symbol]
            self.logger.debug(f"Signal cooldown cleared for {symbol}")

    def update_from_websocket(
        self,
        position_updates: list,
        allowed_symbols: set[str],
    ) -> None:
        """
        Handle position updates from WebSocket ACCOUNT_UPDATE events.

        Updates position cache directly from WebSocket data, eliminating
        the need for REST API calls and reducing rate limit pressure
        (Issue #41 rate limit fix).

        Args:
            position_updates: List of PositionUpdate objects from WebSocket
            allowed_symbols: Set of symbols in active strategies
        """
        from src.models.position import Position

        current_time = time.time()

        for update in position_updates:
            symbol = update.symbol

            # Skip if symbol not in our configured symbols
            if symbol not in allowed_symbols:
                continue

            # Create Position object from WebSocket data
            if abs(update.position_amt) > 0:
                # Active position exists
                position = Position(
                    symbol=symbol,
                    side="LONG" if update.position_amt > 0 else "SHORT",
                    quantity=abs(update.position_amt),
                    entry_price=update.entry_price,
                    leverage=self._config_manager.trading_config.leverage,
                    unrealized_pnl=update.unrealized_pnl,
                )
                self._cache[symbol] = (position, current_time)
                self.logger.debug(
                    f"Position cache updated via WebSocket: {symbol} "
                    f"{position.side} qty={position.quantity} @ {position.entry_price}"
                )
            else:
                # No position (closed or never opened)
                self._cache[symbol] = (None, current_time)
                self.logger.debug(
                    f"Position cache cleared via WebSocket: {symbol} (no position)"
                )

    def is_stale(self, symbol: str) -> bool:
        """Check if cached position is stale or missing.

        Args:
            symbol: Trading symbol

        Returns:
            True if symbol not in cache or TTL expired, False otherwise
        """
        if symbol not in self._cache:
            return True

        _, cache_time = self._cache[symbol]
        return (time.time() - cache_time) >= self._ttl
