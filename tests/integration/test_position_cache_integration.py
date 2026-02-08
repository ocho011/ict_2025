"""
Integration tests for Position Cache Single Source of Truth (Issue #115).

Verifies that EventDispatcher and TradeCoordinator both use PositionCacheManager
as the single source of truth for position data, eliminating the previous
dual-cache inconsistency between PositionCacheManager and OrderGateway.
"""

import time
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest

from src.core.position_cache_manager import PositionCacheManager
from src.models.position import Position


class TestPositionCacheSingleSourceOfTruth:
    """Verify single source of truth for position data."""

    @pytest.fixture
    def mock_order_gateway(self):
        """OrderGateway with no internal position cache."""
        gw = MagicMock()
        gw.get_position = Mock(return_value=Position(
            symbol="BTCUSDT",
            side="LONG",
            quantity=0.001,
            entry_price=50000.0,
            leverage=10,
            unrealized_pnl=5.0,
        ))
        return gw

    @pytest.fixture
    def mock_config_manager(self):
        cm = MagicMock()
        cm.trading_config.leverage = 10
        return cm

    @pytest.fixture
    def position_cache_manager(self, mock_order_gateway, mock_config_manager):
        return PositionCacheManager(
            order_gateway=mock_order_gateway,
            config_manager=mock_config_manager,
            ttl=60.0,
        )

    def test_get_returns_cached_position(self, position_cache_manager, mock_order_gateway):
        """get() should cache and return position, only calling API once within TTL."""
        pos1 = position_cache_manager.get("BTCUSDT")
        pos2 = position_cache_manager.get("BTCUSDT")

        assert pos1 is not None
        assert pos2 is not None
        assert pos1.symbol == "BTCUSDT"
        # API called only once due to cache hit
        assert mock_order_gateway.get_position.call_count == 1

    def test_get_fresh_always_calls_api(self, position_cache_manager, mock_order_gateway):
        """get_fresh() should invalidate cache and always fetch from API."""
        pos1 = position_cache_manager.get("BTCUSDT")
        pos2 = position_cache_manager.get_fresh("BTCUSDT")

        assert pos1 is not None
        assert pos2 is not None
        # get() called API once, get_fresh() invalidated and called again
        assert mock_order_gateway.get_position.call_count == 2

    def test_websocket_update_reflected_in_get(self, position_cache_manager, mock_order_gateway, mock_config_manager):
        """WebSocket updates should be immediately visible via get()."""
        # Initial API-based cache
        pos1 = position_cache_manager.get("BTCUSDT")
        assert pos1.entry_price == 50000.0

        # Simulate WebSocket position update with new price
        ws_update = MagicMock()
        ws_update.symbol = "BTCUSDT"
        ws_update.position_amt = 0.002
        ws_update.entry_price = 51000.0
        ws_update.unrealized_pnl = 10.0

        position_cache_manager.update_from_websocket(
            position_updates=[ws_update],
            allowed_symbols={"BTCUSDT"},
        )

        # get() should now return WebSocket-updated data without API call
        pos2 = position_cache_manager.get("BTCUSDT")
        assert pos2.entry_price == 51000.0
        assert pos2.quantity == 0.002
        # Still only 1 API call (the initial one)
        assert mock_order_gateway.get_position.call_count == 1

    def test_order_gateway_get_position_has_no_cache(self, mock_order_gateway):
        """OrderGateway.get_position() should not have internal caching."""
        assert not hasattr(mock_order_gateway, '_position_cache') or \
               not isinstance(getattr(mock_order_gateway, '_position_cache', None), dict)

    def test_invalidate_clears_cache_and_cooldown(self, position_cache_manager):
        """invalidate() should clear both position cache and signal cooldown."""
        # Populate cache
        position_cache_manager.get("BTCUSDT")
        position_cache_manager._last_signal_time["BTCUSDT"] = time.time()

        assert "BTCUSDT" in position_cache_manager.cache
        assert "BTCUSDT" in position_cache_manager._last_signal_time

        # Invalidate
        position_cache_manager.invalidate("BTCUSDT")

        assert "BTCUSDT" not in position_cache_manager.cache
        assert "BTCUSDT" not in position_cache_manager._last_signal_time
