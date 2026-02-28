"""
Tests for ConfigUpdateEvent, StrategyHotReloader, and UIConfigHook.

Tests:
1. ConfigUpdateEvent immutability
2. UIConfigHook.get_dynamic_params_from_ui
3. UIConfigHook.apply_config_update
4. StrategyHotReloader params-only update
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.events.config_events import ConfigUpdateEvent, ConfigReloadCompleteEvent
from src.config.ui_config_hook import UIConfigHook, UIConfigUpdate


class TestConfigUpdateEvent:
    """Tests for ConfigUpdateEvent dataclass."""

    def test_create_params_only_event(self):
        event = ConfigUpdateEvent(
            symbol="BTCUSDT",
            category="entry",
            params={"lookback": 10},
        )
        assert event.symbol == "BTCUSDT"
        assert event.category == "entry"
        assert event.module_type is None
        assert event.requires_strategy_rebuild is False

    def test_create_rebuild_event(self):
        event = ConfigUpdateEvent(
            symbol="BTCUSDT",
            category="entry",
            module_type="ict_entry",
            requires_strategy_rebuild=True,
        )
        assert event.requires_strategy_rebuild is True
        assert event.module_type == "ict_entry"

    def test_frozen_immutability(self):
        event = ConfigUpdateEvent(symbol="BTCUSDT", category="entry")
        with pytest.raises(AttributeError):
            event.symbol = "ETHUSDT"


class TestConfigReloadCompleteEvent:
    """Tests for ConfigReloadCompleteEvent."""

    def test_create_reload_complete(self):
        event = ConfigReloadCompleteEvent(
            symbol="BTCUSDT",
            old_strategy_name="sma_entry",
            new_strategy_name="ict_entry",
            positions_closed=2,
        )
        assert event.positions_closed == 2
        assert event.old_strategy_name == "sma_entry"


class TestUIConfigHook:
    """Tests for UIConfigHook."""

    def _make_hook(self):
        """Create UIConfigHook with mocked dependencies."""
        mock_config = MagicMock()
        mock_symbol_config = MagicMock()
        mock_symbol_config.modules = {
            "entry": {"type": "sma_entry", "params": {"period": 20}},
            "stop_loss": {"type": "percentage_sl", "params": {}},
        }
        mock_config.get_symbol_config.return_value = mock_symbol_config
        mock_config.get_enabled_symbols.return_value = ["BTCUSDT", "ETHUSDT"]

        mock_registry = MagicMock()
        mock_registry.get_param_schema.return_value = None
        mock_registry.get_available_modules.return_value = []

        return UIConfigHook(
            hierarchical_config=mock_config,
            registry=mock_registry,
        )

    def test_get_dynamic_params_from_ui(self):
        hook = self._make_hook()
        result = hook.get_dynamic_params_from_ui("BTCUSDT")

        assert result["symbol"] == "BTCUSDT"
        assert "entry" in result
        assert "stop_loss" in result

    def test_get_all_symbols_config(self):
        hook = self._make_hook()
        results = hook.get_all_symbols_config()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_apply_config_update_params_only(self):
        hook = self._make_hook()
        callback = AsyncMock()
        hook._on_config_event = callback

        update = UIConfigUpdate(
            symbol="BTCUSDT",
            module_category="entry",
            params={"period": 30},
        )
        event = await hook.apply_config_update(update)

        assert isinstance(event, ConfigUpdateEvent)
        assert event.requires_strategy_rebuild is False
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_config_update_module_change(self):
        hook = self._make_hook()
        callback = AsyncMock()
        hook._on_config_event = callback

        update = UIConfigUpdate(
            symbol="BTCUSDT",
            module_category="entry",
            module_type="ict_entry",
            params={},
        )
        event = await hook.apply_config_update(update)

        assert isinstance(event, ConfigUpdateEvent)
        assert event.requires_strategy_rebuild is True


class TestStrategyHotReloader:
    """Tests for StrategyHotReloader."""

    @pytest.mark.asyncio
    async def test_params_only_update(self):
        from src.core.strategy_hot_reloader import StrategyHotReloader

        mock_strategy = MagicMock()
        # config must be a MagicMock so .update() is trackable
        mock_strategy.config = MagicMock()
        strategies = {"BTCUSDT": mock_strategy}

        reloader = StrategyHotReloader(
            strategies=strategies,
            assembler=MagicMock(),
            hierarchical_config=MagicMock(),
        )

        event = ConfigUpdateEvent(
            symbol="BTCUSDT",
            category="entry",
            params={"lookback": 10},
            requires_strategy_rebuild=False,
        )

        result = await reloader.on_config_update(event)
        assert result is None  # No rebuild event
        mock_strategy.config.update.assert_called_once_with({"lookback": 10})

    @pytest.mark.asyncio
    async def test_rebuild_closes_positions_first(self):
        from src.core.strategy_hot_reloader import StrategyHotReloader

        mock_strategy = MagicMock()
        mock_strategy.module_config.entry_determiner.name = "old"
        strategies = {"BTCUSDT": mock_strategy}

        mock_closer = MagicMock()
        mock_closer.get_open_positions.return_value = []

        mock_assembler = MagicMock()
        mock_module_config = MagicMock()
        mock_module_config.entry_determiner.name = "new"
        mock_assembler.assemble_for_symbol.return_value = (
            mock_module_config, ["5m"], 1.5
        )

        mock_hierarchical = MagicMock()

        reloader = StrategyHotReloader(
            strategies=strategies,
            assembler=mock_assembler,
            hierarchical_config=mock_hierarchical,
            position_closer=mock_closer,
        )

        event = ConfigUpdateEvent(
            symbol="BTCUSDT",
            category="entry",
            module_type="ict_entry",
            requires_strategy_rebuild=True,
        )

        # Patch where StrategyFactory is imported in _rebuild_strategy
        with patch("src.strategies.StrategyFactory") as mock_factory:
            mock_factory.create_composed.return_value = MagicMock()
            result = await reloader.on_config_update(event)

        assert isinstance(result, ConfigReloadCompleteEvent)
        assert result.symbol == "BTCUSDT"
        mock_closer.get_open_positions.assert_called_once_with("BTCUSDT")
