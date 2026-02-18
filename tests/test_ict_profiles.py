"""
Unit tests for ICT strategy parameter profiles
"""

import pytest

from src.config.ict_profiles import (
    ICTProfile,
    PROFILE_PARAMETERS,
    compare_profiles,
    get_profile_info,
    get_profile_parameters,
    list_all_profiles,
    load_profile_from_name,
)


class TestICTProfile:
    """Tests for ICTProfile enum"""

    def test_profile_enum_values(self):
        """Test that profile enum values are correct"""
        assert ICTProfile.STRICT.value == "strict"
        assert ICTProfile.BALANCED.value == "balanced"
        assert ICTProfile.RELAXED.value == "relaxed"

    def test_all_profiles_defined(self):
        """Test that all profiles are defined in PROFILE_PARAMETERS"""
        for profile in ICTProfile:
            assert profile in PROFILE_PARAMETERS


class TestGetProfileParameters:
    """Tests for get_profile_parameters function"""

    def test_strict_profile_parameters(self):
        """Test STRICT profile parameter values"""
        params = get_profile_parameters(ICTProfile.STRICT)

        assert params["swing_lookback"] == 5
        assert params["displacement_ratio"] == 1.5
        assert params["fvg_min_gap_percent"] == 0.001
        assert params["ob_min_strength"] == 1.5
        assert params["liquidity_tolerance"] == 0.001
        assert params["rr_ratio"] == 2.0

        # Verify metadata fields are excluded
        assert "description" not in params
        assert "signal_frequency" not in params
        assert "use_case" not in params

    def test_balanced_profile_parameters(self):
        """Test BALANCED profile parameter values"""
        params = get_profile_parameters(ICTProfile.BALANCED)

        assert params["swing_lookback"] == 5
        assert params["displacement_ratio"] == 1.3
        assert params["fvg_min_gap_percent"] == 0.001
        assert params["ob_min_strength"] == 1.3
        assert params["liquidity_tolerance"] == 0.002
        assert params["min_rr_ratio"] == 1.2

    def test_relaxed_profile_parameters(self):
        """Test RELAXED profile parameter values"""
        params = get_profile_parameters(ICTProfile.RELAXED)

        assert params["swing_lookback"] == 3
        assert params["displacement_ratio"] == 1.1
        assert params["fvg_min_gap_percent"] == 0.0005
        assert params["ob_min_strength"] == 1.1
        assert params["liquidity_tolerance"] == 0.005
        assert params["min_rr_ratio"] == 1.0

    def test_profile_parameter_progression(self):
        """Test that parameters relax progressively from STRICT to RELAXED"""
        strict = get_profile_parameters(ICTProfile.STRICT)
        balanced = get_profile_parameters(ICTProfile.BALANCED)
        relaxed = get_profile_parameters(ICTProfile.RELAXED)

        # Swing lookback decreases or stays same (less history = more signals)
        assert strict["swing_lookback"] >= balanced["swing_lookback"] >= relaxed["swing_lookback"]

        # Displacement ratio decreases (easier to trigger)
        assert strict["displacement_ratio"] > balanced["displacement_ratio"] > relaxed["displacement_ratio"]

        # FVG min gap: strict/balanced same, relaxed lower (more permissive)
        assert strict["fvg_min_gap_percent"] >= balanced["fvg_min_gap_percent"] >= relaxed["fvg_min_gap_percent"]
        assert strict["ob_min_strength"] > balanced["ob_min_strength"] > relaxed["ob_min_strength"]
        assert strict["liquidity_tolerance"] < balanced["liquidity_tolerance"] < relaxed["liquidity_tolerance"]

        # RR ratio remains constant
        assert strict["rr_ratio"] == balanced["rr_ratio"] == relaxed["rr_ratio"] == 2.0


class TestGetProfileInfo:
    """Tests for get_profile_info function"""

    def test_strict_profile_info(self):
        """Test STRICT profile information"""
        info = get_profile_info(ICTProfile.STRICT)

        assert "description" in info
        assert "signal_frequency" in info
        assert "use_case" in info

        assert "1-2" in info["signal_frequency"]
        assert "baseline" in info["description"].lower()

    def test_balanced_profile_info(self):
        """Test BALANCED profile information"""
        info = get_profile_info(ICTProfile.BALANCED)

        assert "5-10" in info["signal_frequency"]
        assert "recommended" in info["description"].lower()

    def test_relaxed_profile_info(self):
        """Test RELAXED profile information"""
        info = get_profile_info(ICTProfile.RELAXED)

        assert "15-20" in info["signal_frequency"]
        assert "maximum" in info["use_case"].lower() or "false positive" in info["use_case"].lower()


class TestLoadProfileFromName:
    """Tests for load_profile_from_name function"""

    def test_load_strict_by_name(self):
        """Test loading STRICT profile by name"""
        profile = load_profile_from_name("strict")
        assert profile == ICTProfile.STRICT

    def test_load_balanced_by_name(self):
        """Test loading BALANCED profile by name"""
        profile = load_profile_from_name("balanced")
        assert profile == ICTProfile.BALANCED

    def test_load_relaxed_by_name(self):
        """Test loading RELAXED profile by name"""
        profile = load_profile_from_name("relaxed")
        assert profile == ICTProfile.RELAXED

    def test_load_case_insensitive(self):
        """Test that profile loading is case-insensitive"""
        assert load_profile_from_name("STRICT") == ICTProfile.STRICT
        assert load_profile_from_name("Balanced") == ICTProfile.BALANCED
        assert load_profile_from_name("ReLaXeD") == ICTProfile.RELAXED

    def test_load_invalid_name_raises_error(self):
        """Test that invalid profile name raises ValueError"""
        with pytest.raises(ValueError, match="Unknown profile name"):
            load_profile_from_name("invalid")

        with pytest.raises(ValueError, match="Unknown profile name"):
            load_profile_from_name("aggressive")

    def test_error_message_includes_valid_options(self):
        """Test that error message includes valid profile names"""
        with pytest.raises(ValueError, match="strict.*balanced.*relaxed"):
            load_profile_from_name("nonexistent")


class TestListAllProfiles:
    """Tests for list_all_profiles function"""

    def test_list_all_profiles_structure(self):
        """Test that list_all_profiles returns complete profile data"""
        all_profiles = list_all_profiles()

        assert len(all_profiles) == 3
        assert "strict" in all_profiles
        assert "balanced" in all_profiles
        assert "relaxed" in all_profiles

    def test_profile_contains_both_params_and_info(self):
        """Test that each profile contains both parameters and info"""
        all_profiles = list_all_profiles()

        for profile_name, profile_data in all_profiles.items():
            # Parameter fields
            assert "swing_lookback" in profile_data
            assert "displacement_ratio" in profile_data
            assert "fvg_min_gap_percent" in profile_data
            assert "ob_min_strength" in profile_data
            assert "liquidity_tolerance" in profile_data
            assert "rr_ratio" in profile_data

            # Info fields
            assert "description" in profile_data
            assert "signal_frequency" in profile_data
            assert "use_case" in profile_data


class TestCompareProfiles:
    """Tests for compare_profiles function"""

    def test_compare_profiles_returns_string(self):
        """Test that compare_profiles returns formatted string"""
        comparison = compare_profiles()

        assert isinstance(comparison, str)
        assert len(comparison) > 0

    def test_comparison_includes_all_profiles(self):
        """Test that comparison includes all profile names"""
        comparison = compare_profiles()

        assert "Strict" in comparison or "strict" in comparison
        assert "Balanced" in comparison or "balanced" in comparison
        assert "Relaxed" in comparison or "relaxed" in comparison

    def test_comparison_includes_all_parameters(self):
        """Test that comparison includes all parameter names"""
        comparison = compare_profiles()

        assert "swing_lookback" in comparison
        assert "displacement_ratio" in comparison
        assert "fvg_min_gap_percent" in comparison
        assert "ob_min_strength" in comparison
        assert "liquidity_tolerance" in comparison
        assert "rr_ratio" in comparison

    def test_comparison_includes_use_cases(self):
        """Test that comparison includes use case information"""
        comparison = compare_profiles()

        assert "Use Cases" in comparison or "use case" in comparison.lower()


class TestProfileIntegration:
    """Integration tests for profile system"""

    def test_profile_roundtrip(self):
        """Test loading profile by name and getting parameters"""
        profile_name = "balanced"

        # Load profile
        profile = load_profile_from_name(profile_name)

        # Get parameters
        params = get_profile_parameters(profile)

        # Verify parameters match expected values
        assert params["swing_lookback"] == 5
        assert params["displacement_ratio"] == 1.3

    def test_all_profiles_have_valid_numeric_values(self):
        """Test that all profile parameters are valid numeric values"""
        for profile in ICTProfile:
            params = get_profile_parameters(profile)

            # All values should be positive numbers
            assert params["swing_lookback"] > 0
            assert params["displacement_ratio"] > 0
            assert params["fvg_min_gap_percent"] > 0
            assert params["ob_min_strength"] > 0
            assert params["liquidity_tolerance"] > 0
            assert params["rr_ratio"] > 0

            # All should be reasonable ranges
            assert 1 <= params["swing_lookback"] <= 20
            assert 1.0 <= params["displacement_ratio"] <= 2.0
            assert 0.0001 <= params["fvg_min_gap_percent"] <= 0.01
            assert 1.0 <= params["ob_min_strength"] <= 2.0
            assert 0.0001 <= params["liquidity_tolerance"] <= 0.01
            assert 1.0 <= params["rr_ratio"] <= 5.0

    def test_profile_parameter_types(self):
        """Test that profile parameters have correct types"""
        for profile in ICTProfile:
            params = get_profile_parameters(profile)

            assert isinstance(params["swing_lookback"], int)
            assert isinstance(params["displacement_ratio"], float)
            assert isinstance(params["fvg_min_gap_percent"], float)
            assert isinstance(params["ob_min_strength"], float)
            assert isinstance(params["liquidity_tolerance"], float)
            assert isinstance(params["rr_ratio"], float)
