"""
Integration tests for ICT strategy profile loading
"""

import pytest

from src.config.ict_profiles import ICTProfile, get_profile_parameters
from src.strategies.ict_strategy import ICTStrategy


class TestICTStrategyProfileLoading:
    """Tests for ICTStrategy profile-based parameter loading"""

    def test_load_strict_profile_default(self):
        """Test loading STRICT profile (default)"""
        config = {
            "buffer_size": 200,
            "active_profile": "strict",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Verify profile parameters loaded correctly
        assert strategy.swing_lookback == 5
        assert strategy.displacement_ratio == 1.5
        assert strategy.fvg_min_gap_percent == 0.001
        assert strategy.ob_min_strength == 1.5
        assert strategy.liquidity_tolerance == 0.001
        assert strategy.rr_ratio == 2.0

        # Verify active profile stored
        assert strategy.active_profile == "strict"

    def test_load_balanced_profile(self):
        """Test loading BALANCED profile"""
        config = {
            "buffer_size": 200,
            "active_profile": "balanced",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Verify BALANCED parameters
        assert strategy.swing_lookback == 7
        assert strategy.displacement_ratio == 1.3
        assert strategy.fvg_min_gap_percent == 0.002
        assert strategy.ob_min_strength == 1.3
        assert strategy.liquidity_tolerance == 0.002
        assert strategy.rr_ratio == 2.0

        assert strategy.active_profile == "balanced"

    def test_load_relaxed_profile(self):
        """Test loading RELAXED profile"""
        config = {
            "buffer_size": 200,
            "active_profile": "relaxed",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Verify RELAXED parameters
        assert strategy.swing_lookback == 10
        assert strategy.displacement_ratio == 1.2
        assert strategy.fvg_min_gap_percent == 0.005
        assert strategy.ob_min_strength == 1.2
        assert strategy.liquidity_tolerance == 0.005
        assert strategy.rr_ratio == 2.0

        assert strategy.active_profile == "relaxed"

    def test_config_override_profile_parameters(self):
        """Test that explicit config values override profile defaults"""
        config = {
            "buffer_size": 200,
            "active_profile": "strict",
            # Override some parameters explicitly
            "swing_lookback": 8,
            "displacement_ratio": 1.8,
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Overridden values
        assert strategy.swing_lookback == 8
        assert strategy.displacement_ratio == 1.8

        # Profile defaults for non-overridden values
        assert strategy.fvg_min_gap_percent == 0.001
        assert strategy.ob_min_strength == 1.5
        assert strategy.liquidity_tolerance == 0.001

    def test_invalid_profile_name_uses_strict_defaults(self):
        """Test that invalid profile name falls back to strict defaults"""
        config = {
            "buffer_size": 200,
            "active_profile": "invalid_profile",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Should fall back to strict defaults
        assert strategy.swing_lookback == 5
        assert strategy.displacement_ratio == 1.5
        assert strategy.active_profile == "strict"

    def test_missing_profile_uses_strict_defaults(self):
        """Test that missing active_profile uses strict defaults"""
        config = {
            "buffer_size": 200,
            # No active_profile specified
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Should default to strict
        assert strategy.swing_lookback == 5
        assert strategy.displacement_ratio == 1.5
        assert strategy.active_profile == "strict"

    def test_case_insensitive_profile_loading(self):
        """Test that profile loading is case-insensitive"""
        config_upper = {
            "buffer_size": 200,
            "active_profile": "BALANCED",
        }

        strategy_upper = ICTStrategy(symbol="BTCUSDT", config=config_upper)

        config_mixed = {
            "buffer_size": 200,
            "active_profile": "BaLaNcEd",
        }

        strategy_mixed = ICTStrategy(symbol="BTCUSDT", config=config_mixed)

        # Both should load balanced profile
        assert strategy_upper.swing_lookback == 7
        assert strategy_mixed.swing_lookback == 7
        assert strategy_upper.active_profile == "balanced"
        assert strategy_mixed.active_profile == "balanced"

    def test_profile_loading_with_all_overrides(self):
        """Test loading profile with all parameters explicitly overridden"""
        config = {
            "buffer_size": 200,
            "active_profile": "balanced",
            # Override ALL profile parameters
            "swing_lookback": 15,
            "displacement_ratio": 2.0,
            "fvg_min_gap_percent": 0.01,
            "ob_min_strength": 2.5,
            "liquidity_tolerance": 0.01,
            "rr_ratio": 3.0,
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # All values should use config overrides
        assert strategy.swing_lookback == 15
        assert strategy.displacement_ratio == 2.0
        assert strategy.fvg_min_gap_percent == 0.01
        assert strategy.ob_min_strength == 2.5
        assert strategy.liquidity_tolerance == 0.01
        assert strategy.rr_ratio == 3.0

        # Profile name still stored
        assert strategy.active_profile == "balanced"

    def test_killzone_parameter_loading(self):
        """Test that use_killzones parameter loads correctly"""
        config_with_killzones = {
            "buffer_size": 200,
            "active_profile": "strict",
            "use_killzones": True,
        }

        strategy_with_kz = ICTStrategy(symbol="BTCUSDT", config=config_with_killzones)
        assert strategy_with_kz.use_killzones is True

        config_without_killzones = {
            "buffer_size": 200,
            "active_profile": "strict",
            "use_killzones": False,
        }

        strategy_without_kz = ICTStrategy(symbol="BTCUSDT", config=config_without_killzones)
        assert strategy_without_kz.use_killzones is False

    def test_buffer_size_parameter_loading(self):
        """Test that buffer_size parameter loads correctly"""
        config = {
            "buffer_size": 500,
            "active_profile": "balanced",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Verify buffer_size is set (MTFBuffer initialization)
        # Note: buffer_size is used in parent MTFStrategy.__init__
        assert hasattr(strategy, "buffer_size")


class TestICTStrategyConditionStats:
    """Tests for ICT strategy condition statistics tracking"""

    def test_condition_stats_initialized(self):
        """Test that condition stats are initialized on strategy creation"""
        config = {
            "buffer_size": 200,
            "active_profile": "strict",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Verify condition_stats dictionary exists
        assert hasattr(strategy, "condition_stats")
        assert isinstance(strategy.condition_stats, dict)

        # Verify all expected keys are present
        expected_keys = [
            "total_checks",
            "killzone_ok",
            "trend_ok",
            "zone_ok",
            "fvg_ob_ok",
            "inducement_ok",
            "displacement_ok",
            "all_conditions_ok",
            "signals_generated",
        ]

        for key in expected_keys:
            assert key in strategy.condition_stats
            assert strategy.condition_stats[key] == 0

    def test_get_condition_stats(self):
        """Test get_condition_stats method"""
        config = {
            "buffer_size": 200,
            "active_profile": "balanced",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        stats = strategy.get_condition_stats()

        # Should return copy of condition_stats
        assert isinstance(stats, dict)
        assert "total_checks" in stats

        # Verify success_rates calculated when total_checks > 0
        # Initially all should be 0
        strategy.condition_stats["total_checks"] = 100
        strategy.condition_stats["killzone_ok"] = 80
        strategy.condition_stats["trend_ok"] = 60

        stats = strategy.get_condition_stats()

        assert "success_rates" in stats
        assert stats["success_rates"]["killzone_rate"] == 0.8
        assert stats["success_rates"]["trend_rate"] == 0.6

    def test_reset_condition_stats(self):
        """Test reset_condition_stats method"""
        config = {
            "buffer_size": 200,
            "active_profile": "relaxed",
        }

        strategy = ICTStrategy(symbol="BTCUSDT", config=config)

        # Modify some stats
        strategy.condition_stats["total_checks"] = 100
        strategy.condition_stats["signals_generated"] = 5

        # Reset
        strategy.reset_condition_stats()

        # All should be back to 0
        for value in strategy.condition_stats.values():
            assert value == 0


class TestProfileParameterValidation:
    """Tests for profile parameter value validation"""

    def test_profile_parameters_within_valid_ranges(self):
        """Test that all profile parameters are within valid ranges"""
        for profile_name in ["strict", "balanced", "relaxed"]:
            config = {
                "buffer_size": 200,
                "active_profile": profile_name,
            }

            strategy = ICTStrategy(symbol="BTCUSDT", config=config)

            # Verify all parameters are positive
            assert strategy.swing_lookback > 0
            assert strategy.displacement_ratio > 0
            assert strategy.fvg_min_gap_percent > 0
            assert strategy.ob_min_strength > 0
            assert strategy.liquidity_tolerance > 0
            assert strategy.rr_ratio > 0

            # Verify parameters are within reasonable ranges
            assert 1 <= strategy.swing_lookback <= 20
            assert 1.0 <= strategy.displacement_ratio <= 3.0
            assert 0.0001 <= strategy.fvg_min_gap_percent <= 0.1
            assert 1.0 <= strategy.ob_min_strength <= 3.0
            assert 0.0001 <= strategy.liquidity_tolerance <= 0.1
            assert 1.0 <= strategy.rr_ratio <= 10.0
