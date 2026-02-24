"""Tests for ICT package isolation and self-registration."""

import pytest


class TestICTPackageImports:
    """Verify ICT classes are importable from canonical paths."""

    def test_import_entry_determiner(self):
        from src.strategies.ict.entry import ICTEntryDeterminer
        assert ICTEntryDeterminer is not None

    def test_import_exit_determiner(self):
        from src.strategies.ict.exit import ICTExitDeterminer
        assert ICTExitDeterminer is not None

    def test_import_zone_based_sl(self):
        from src.strategies.ict.pricing.zone_based_sl import ZoneBasedStopLoss
        assert ZoneBasedStopLoss is not None

    def test_import_displacement_tp(self):
        from src.strategies.ict.pricing.displacement_tp import DisplacementTakeProfit
        assert DisplacementTakeProfit is not None

    def test_import_profiles(self):
        from src.strategies.ict.profiles import ICTProfile, get_profile_parameters
        assert ICTProfile.STRICT is not None
        params = get_profile_parameters(ICTProfile.BALANCED)
        assert "displacement_ratio" in params

    def test_import_indicator_cache(self):
        from src.strategies.ict.indicator_cache import IndicatorStateCache
        cache = IndicatorStateCache()
        assert cache is not None

    def test_import_detectors(self):
        from src.strategies.ict.detectors.fvg import detect_bullish_fvg
        from src.strategies.ict.detectors.killzones import is_killzone_active
        from src.strategies.ict.detectors.liquidity import calculate_premium_discount
        from src.strategies.ict.detectors.market_structure import get_current_trend
        from src.strategies.ict.detectors.order_block import identify_bullish_ob
        from src.strategies.ict.detectors.smc import detect_displacement
        assert all([
            detect_bullish_fvg, is_killzone_active, calculate_premium_discount,
            get_current_trend, identify_bullish_ob, detect_displacement,
        ])


class TestICTBackwardCompatImports:
    """Verify re-export stubs work for backward compatibility."""

    def test_entry_stub(self):
        from src.entry.ict_entry import ICTEntryDeterminer
        from src.strategies.ict.entry import ICTEntryDeterminer as Canonical
        assert ICTEntryDeterminer is Canonical

    def test_exit_stub(self):
        from src.exit.ict_exit import ICTExitDeterminer
        from src.strategies.ict.exit import ICTExitDeterminer as Canonical
        assert ICTExitDeterminer is Canonical

    def test_detector_stubs(self):
        from src.detectors.ict_fvg import detect_bullish_fvg
        from src.strategies.ict.detectors.fvg import detect_bullish_fvg as Canonical
        assert detect_bullish_fvg is Canonical

    def test_profiles_stub(self):
        from src.config.ict_profiles import ICTProfile
        from src.strategies.ict.profiles import ICTProfile as Canonical
        assert ICTProfile is Canonical

    def test_indicator_cache_stub(self):
        from src.strategies.indicator_cache import IndicatorStateCache
        from src.strategies.ict.indicator_cache import IndicatorStateCache as Canonical
        assert IndicatorStateCache is Canonical

    def test_pricing_stubs(self):
        from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
        from src.strategies.ict.pricing.zone_based_sl import ZoneBasedStopLoss as Canonical
        assert ZoneBasedStopLoss is Canonical

        from src.pricing.take_profit.displacement import DisplacementTakeProfit
        from src.strategies.ict.pricing.displacement_tp import DisplacementTakeProfit as CanonicalTP
        assert DisplacementTakeProfit is CanonicalTP


class TestICTSelfRegistration:
    """Verify ICT strategy auto-registers in the strategy registry."""

    def test_ict_strategy_in_registry(self):
        from src.strategies.module_config_builder import get_registered_strategies
        strategies = get_registered_strategies()
        assert "ict_strategy" in strategies

    def test_build_ict_config(self):
        from src.strategies.module_config_builder import build_module_config
        config = {"active_profile": "strict"}
        module_config, intervals, min_rr = build_module_config("ict_strategy", config)
        assert module_config is not None
        assert intervals is not None  # ICT is multi-timeframe
        assert len(intervals) >= 2
        assert min_rr > 0

    def test_all_strategies_registered(self):
        from src.strategies.module_config_builder import get_registered_strategies
        strategies = get_registered_strategies()
        assert strategies == {"ict_strategy", "mock_sma", "always_signal"}
