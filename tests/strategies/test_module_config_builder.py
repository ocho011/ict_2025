"""
Unit tests for ModuleConfigBuilder.

Tests the build_module_config() function that maps strategy names
to composable StrategyModuleConfig bundles with all 4 determiners.
"""

import pytest

from src.entry import AlwaysEntryDeterminer, SMAEntryDeterminer
from src.exit import NullExitDeterminer
from src.strategies.ict.entry import ICTEntryDeterminer
from src.strategies.ict.exit import ICTExitDeterminer
from src.pricing.base import StrategyModuleConfig
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
from src.pricing.take_profit.displacement import DisplacementTakeProfit
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.strategies.module_config_builder import build_module_config
from src.utils.config_manager import ExitConfig


class TestICTStrategyConfig:
    """Tests for ICT strategy module configuration."""

    def test_returns_correct_determiner_types(self):
        config = {
            "swing_lookback": 5,
            "displacement_ratio": 1.5,
            "mtf_interval": "1h",
            "htf_interval": "4h",
            "ltf_interval": "5m",
            "rr_ratio": 2.0,
        }
        module_config, intervals, min_rr = build_module_config("ict_strategy", config)

        assert isinstance(module_config, StrategyModuleConfig)
        assert isinstance(module_config.entry_determiner, ICTEntryDeterminer)
        assert isinstance(module_config.stop_loss_determiner, ZoneBasedStopLoss)
        assert isinstance(module_config.take_profit_determiner, DisplacementTakeProfit)
        assert isinstance(module_config.exit_determiner, ICTExitDeterminer)

    def test_multi_timeframe_intervals(self):
        config = {"ltf_interval": "5m", "mtf_interval": "1h", "htf_interval": "4h"}
        _, intervals, _ = build_module_config("ict_strategy", config)
        assert intervals == ["5m", "1h", "4h"]

    def test_custom_rr_ratio(self):
        config = {"rr_ratio": 3.0}
        _, _, min_rr = build_module_config("ict_strategy", config)
        assert min_rr == 3.0

    def test_with_exit_config(self):
        exit_config = ExitConfig()
        config = {}
        module_config, _, _ = build_module_config(
            "ict_strategy", config, exit_config=exit_config
        )
        assert isinstance(module_config.exit_determiner, ICTExitDeterminer)

    def test_default_intervals(self):
        config = {}
        _, intervals, _ = build_module_config("ict_strategy", config)
        assert intervals == ["5m", "1h", "4h"]


class TestSMAStrategyConfig:
    """Tests for SMA strategy module configuration."""

    def test_returns_correct_determiner_types(self):
        module_config, intervals, _ = build_module_config("mock_sma", {})

        assert isinstance(module_config, StrategyModuleConfig)
        assert isinstance(module_config.entry_determiner, SMAEntryDeterminer)
        assert isinstance(module_config.stop_loss_determiner, PercentageStopLoss)
        assert isinstance(module_config.take_profit_determiner, RiskRewardTakeProfit)
        assert isinstance(module_config.exit_determiner, NullExitDeterminer)

    def test_no_intervals(self):
        _, intervals, _ = build_module_config("mock_sma", {})
        assert intervals is None


class TestAlwaysSignalConfig:
    """Tests for AlwaysSignal strategy module configuration."""

    def test_returns_correct_determiner_types(self):
        module_config, intervals, _ = build_module_config("always_signal", {})

        assert isinstance(module_config, StrategyModuleConfig)
        assert isinstance(module_config.entry_determiner, AlwaysEntryDeterminer)
        assert isinstance(module_config.stop_loss_determiner, PercentageStopLoss)
        assert isinstance(module_config.take_profit_determiner, RiskRewardTakeProfit)
        assert isinstance(module_config.exit_determiner, NullExitDeterminer)
        assert intervals is None


class TestBuildModuleConfigGeneral:
    """General tests for build_module_config."""

    def test_unknown_strategy_raises_error(self):
        with pytest.raises(ValueError, match="Unknown strategy name"):
            build_module_config("nonexistent", {})

    def test_per_symbol_isolation(self):
        mc1, _, _ = build_module_config("mock_sma", {})
        mc2, _, _ = build_module_config("mock_sma", {})

        assert mc1 is not mc2
        assert mc1.entry_determiner is not mc2.entry_determiner
        assert mc1.stop_loss_determiner is not mc2.stop_loss_determiner

    def test_default_rr_ratio(self):
        _, _, min_rr = build_module_config("mock_sma", {})
        assert min_rr == 2.0
