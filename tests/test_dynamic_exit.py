"""
Comprehensive unit tests for dynamic exit strategies (Issue #43).

Tests for:
1. ExitConfig validation and parameter validation
2. ICT Strategy trailing stop exit logic
3. ICT Strategy breakeven exit logic
4. ICT Strategy timed exit logic
5. ICT Strategy indicator-based exit logic
6. Integration with ExitConfig and strategy initialization
7. Edge cases and error handling
8. Performance and real-time behavior
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.core.exceptions import ConfigurationError
from src.utils.config_manager import ExitConfig


class TestExitConfig:
    """Test suite for ExitConfig validation and functionality."""

    def test_default_config_values(self):
        """Test default ExitConfig values are valid."""
        config = ExitConfig()

        assert config.dynamic_exit_enabled is True
        assert config.exit_strategy == "trailing_stop"
        assert config.trailing_distance == 0.02
        assert config.trailing_activation == 0.01
        assert config.breakeven_enabled is True
        assert config.breakeven_offset == 0.001
        assert config.timeout_enabled is False
        assert config.timeout_minutes == 240
        assert config.volatility_enabled is False
        assert config.atr_period == 14
        assert config.atr_multiplier == 2.0

    def test_valid_trailing_stop_config(self):
        """Test valid trailing stop configuration."""
        config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.03,
            trailing_activation=0.02,
        )

        assert config.exit_strategy == "trailing_stop"
        assert config.trailing_distance == 0.03
        assert config.trailing_activation == 0.02

    def test_valid_breakeven_config(self):
        """Test valid breakeven configuration."""
        config = ExitConfig(
            exit_strategy="breakeven", breakeven_enabled=True, breakeven_offset=0.002
        )

        assert config.exit_strategy == "breakeven"
        assert config.breakeven_enabled is True
        assert config.breakeven_offset == 0.002

    def test_valid_timed_config(self):
        """Test valid timed exit configuration."""
        config = ExitConfig(
            exit_strategy="timed", timeout_enabled=True, timeout_minutes=120
        )

        assert config.exit_strategy == "timed"
        assert config.timeout_enabled is True
        assert config.timeout_minutes == 120

    def test_invalid_exit_strategy(self):
        """Test invalid exit strategy raises error."""
        with pytest.raises(ConfigurationError, match="Invalid exit strategy"):
            ExitConfig(exit_strategy="invalid_strategy")

    def test_invalid_trailing_distance(self):
        """Test invalid trailing distance raises error."""
        # Test too small
        with pytest.raises(ConfigurationError, match="trailing_distance must be 0.001-0.1"):
            ExitConfig(trailing_distance=0.0005)

        # Test too large
        with pytest.raises(ConfigurationError, match="trailing_distance must be 0.001-0.1"):
            ExitConfig(trailing_distance=0.2)

    def test_invalid_trailing_activation(self):
        """Test invalid trailing activation raises error."""
        # Test too small
        with pytest.raises(ConfigurationError, match="trailing_activation must be 0.001-0.05"):
            ExitConfig(trailing_activation=0.0005)

        # Test too large
        with pytest.raises(ConfigurationError, match="trailing_activation must be 0.001-0.05"):
            ExitConfig(trailing_activation=0.1)

    def test_invalid_breakeven_offset(self):
        """Test invalid breakeven offset raises error."""
        # Test too small
        with pytest.raises(ConfigurationError, match="breakeven_offset must be 0.0001-0.01"):
            ExitConfig(breakeven_offset=0.00005)

        # Test too large
        with pytest.raises(ConfigurationError, match="breakeven_offset must be 0.0001-0.01"):
            ExitConfig(breakeven_offset=0.02)

    def test_invalid_timeout_minutes(self):
        """Test invalid timeout minutes raises error."""
        # Test too small
        with pytest.raises(ConfigurationError, match="timeout_minutes must be 1-1440"):
            ExitConfig(timeout_minutes=0)

        # Test too large
        with pytest.raises(ConfigurationError, match="timeout_minutes must be 1-1440"):
            ExitConfig(timeout_minutes=2000)

    def test_invalid_atr_period(self):
        """Test invalid ATR period raises error."""
        # Test too small
        with pytest.raises(ConfigurationError, match="atr_period must be 5-100"):
            ExitConfig(atr_period=2)

        # Test too large
        with pytest.raises(ConfigurationError, match="atr_period must be 5-100"):
            ExitConfig(atr_period=200)

    def test_invalid_atr_multiplier(self):
        """Test invalid ATR multiplier raises error."""
        # Test too small
        with pytest.raises(ConfigurationError, match="atr_multiplier must be 0.5-5.0"):
            ExitConfig(atr_multiplier=0.2)

        # Test too large
        with pytest.raises(ConfigurationError, match="atr_multiplier must be 0.5-5.0"):
            ExitConfig(atr_multiplier=10.0)

    def test_inconsistent_trailing_stop_config(self):
        """Test trailing_stop config without distance raises error."""
        with pytest.raises(
            ConfigurationError, match="trailing_distance must be 0.001-0.1"
        ):
            ExitConfig(exit_strategy="trailing_stop", trailing_distance=0)

    def test_inconsistent_timed_config(self):
        """Test timed config without timeout enabled raises error."""
        with pytest.raises(
            ConfigurationError, match="timed strategy requires timeout_enabled=True"
        ):
            ExitConfig(exit_strategy="timed", timeout_enabled=False)

