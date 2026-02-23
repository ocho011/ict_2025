"""
Integration tests for module data requirements across the strategy system.

Covers: determiner requirements, aggregation, builder integration, engine backfill.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.entry.always_entry import AlwaysEntryDeterminer
from src.entry.ict_entry import ICTEntryDeterminer
from src.entry.sma_entry import SMAEntryDeterminer
from src.exit.base import NullExitDeterminer
from src.exit.ict_exit import ICTExitDeterminer
from src.models.module_requirements import ModuleRequirements
from src.pricing.base import StrategyModuleConfig
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
from src.pricing.take_profit.displacement import DisplacementTakeProfit
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.strategies.composable import ComposableStrategy
from src.strategies.module_config_builder import build_module_config


class TestDeterminerRequirements:
    """Test individual determiner requirements declarations."""

    def test_ict_entry_requirements(self):
        entry = ICTEntryDeterminer()
        req = entry.requirements
        assert req.timeframes == frozenset({"5m", "1h", "4h"})
        assert req.min_candles["5m"] == 50
        assert req.min_candles["1h"] == 50
        assert req.min_candles["4h"] == 50

    def test_ict_entry_custom_intervals(self):
        entry = ICTEntryDeterminer(
            ltf_interval="1m",
            mtf_interval="15m",
            htf_interval="1h",
            swing_lookback=10,
        )
        req = entry.requirements
        assert req.timeframes == frozenset({"1m", "15m", "1h"})
        assert req.min_candles["1m"] == 50  # max(50, 10*4=40)

    def test_ict_entry_large_swing_lookback(self):
        entry = ICTEntryDeterminer(swing_lookback=20)
        req = entry.requirements
        assert req.min_candles["5m"] == 80  # max(50, 20*4=80)

    def test_ict_exit_requirements(self):
        exit_det = ICTExitDeterminer()
        req = exit_det.requirements
        assert req.timeframes == frozenset({"1h", "4h"})
        assert req.min_candles["1h"] == 50
        assert req.min_candles["4h"] == 50

    def test_sma_entry_returns_empty(self):
        entry = SMAEntryDeterminer()
        assert entry.requirements == ModuleRequirements.empty()

    def test_always_entry_returns_empty(self):
        entry = AlwaysEntryDeterminer()
        assert entry.requirements == ModuleRequirements.empty()

    def test_null_exit_returns_empty(self):
        exit_det = NullExitDeterminer()
        assert exit_det.requirements == ModuleRequirements.empty()

    def test_percentage_sl_returns_empty(self):
        sl = PercentageStopLoss()
        assert sl.requirements == ModuleRequirements.empty()

    def test_risk_reward_tp_returns_empty(self):
        tp = RiskRewardTakeProfit()
        assert tp.requirements == ModuleRequirements.empty()

    def test_zone_based_sl_returns_empty(self):
        sl = ZoneBasedStopLoss()
        assert sl.requirements == ModuleRequirements.empty()

    def test_displacement_tp_returns_empty(self):
        tp = DisplacementTakeProfit()
        assert tp.requirements == ModuleRequirements.empty()


class TestStrategyModuleConfigAggregation:
    """Test StrategyModuleConfig.aggregated_requirements."""

    def test_ict_aggregated_requirements(self):
        mc = StrategyModuleConfig(
            entry_determiner=ICTEntryDeterminer(),
            stop_loss_determiner=ZoneBasedStopLoss(),
            take_profit_determiner=DisplacementTakeProfit(),
            exit_determiner=ICTExitDeterminer(),
        )
        agg = mc.aggregated_requirements
        assert agg.timeframes == frozenset({"5m", "1h", "4h"})
        assert agg.min_candles["5m"] == 50
        assert agg.min_candles["1h"] == 50
        assert agg.min_candles["4h"] == 50

    def test_sma_aggregated_requirements_empty(self):
        mc = StrategyModuleConfig(
            entry_determiner=SMAEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=NullExitDeterminer(),
        )
        agg = mc.aggregated_requirements
        assert agg.timeframes == frozenset()
        assert dict(agg.min_candles) == {}

    def test_always_signal_aggregated_requirements_empty(self):
        mc = StrategyModuleConfig(
            entry_determiner=AlwaysEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=NullExitDeterminer(),
        )
        agg = mc.aggregated_requirements
        assert agg.timeframes == frozenset()
        assert dict(agg.min_candles) == {}


class TestComposableStrategyDataRequirements:
    """Test ComposableStrategy.data_requirements."""

    def test_ict_composable_data_requirements(self):
        mc = StrategyModuleConfig(
            entry_determiner=ICTEntryDeterminer(),
            stop_loss_determiner=ZoneBasedStopLoss(),
            take_profit_determiner=DisplacementTakeProfit(),
            exit_determiner=ICTExitDeterminer(),
        )
        cs = ComposableStrategy("BTCUSDT", {"buffer_size": 100}, mc, intervals=["5m", "1h", "4h"])
        assert cs.data_requirements.timeframes == frozenset({"5m", "1h", "4h"})

    def test_sma_composable_data_requirements_empty(self):
        mc = StrategyModuleConfig(
            entry_determiner=SMAEntryDeterminer(),
            stop_loss_determiner=PercentageStopLoss(),
            take_profit_determiner=RiskRewardTakeProfit(),
            exit_determiner=NullExitDeterminer(),
        )
        cs = ComposableStrategy("BTCUSDT", {}, mc)
        assert cs.data_requirements == ModuleRequirements.empty()

    def test_buffer_size_warning(self, caplog):
        mc = StrategyModuleConfig(
            entry_determiner=ICTEntryDeterminer(),
            stop_loss_determiner=ZoneBasedStopLoss(),
            take_profit_determiner=DisplacementTakeProfit(),
            exit_determiner=ICTExitDeterminer(),
        )
        with caplog.at_level(logging.WARNING):
            cs = ComposableStrategy(
                "BTCUSDT", {"buffer_size": 20}, mc, intervals=["5m", "1h", "4h"]
            )
        assert "buffer_size=20 < max min_candles=50" in caplog.text


class TestBuildModuleConfigIntegration:
    """Test build_module_config derives intervals from requirements."""

    def test_ict_intervals_from_requirements(self):
        mc, intervals, rr = build_module_config("ict_strategy", {})
        assert intervals == ["5m", "1h", "4h"]

    def test_sma_intervals_none(self):
        mc, intervals, rr = build_module_config("mock_sma", {})
        assert intervals is None

    def test_always_signal_intervals_none(self):
        mc, intervals, rr = build_module_config("always_signal", {})
        assert intervals is None

    def test_ict_custom_intervals(self):
        config = {
            "ltf_interval": "1m",
            "mtf_interval": "15m",
            "htf_interval": "1h",
        }
        mc, intervals, rr = build_module_config("ict_strategy", config)
        assert intervals == ["1m", "15m", "1h"]
