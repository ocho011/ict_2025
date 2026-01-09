"""
Unit tests for LiquidationConfig with comprehensive validation coverage.

Test Coverage:
- Default values (security-first defaults)
- Type validation (runtime type checking)
- Range validation (business rules)
- Consistency validation (cross-field logic)
- Security validation (warnings for risky configurations)
- Serialization (to_dict, from_dict)
"""

import pytest
from src.core.exceptions import ConfigurationError
from src.utils.config import LiquidationConfig


class TestLiquidationConfigDefaults:
    """Test default values follow security-first design."""

    def test_default_values_are_security_first(self):
        """Verify defaults protect capital by default."""
        config = LiquidationConfig()

        assert config.emergency_liquidation is True, "Default should protect capital"
        assert config.close_positions is True, "Default should close positions"
        assert config.cancel_orders is True, "Default should cancel orders"
        assert config.timeout_seconds == 5.0
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 0.5

    def test_repr_is_readable(self):
        """Verify __repr__ provides useful debugging output."""
        config = LiquidationConfig()
        repr_str = repr(config)

        assert "LiquidationConfig" in repr_str
        assert "emergency_liquidation=True" in repr_str
        assert "close_positions=True" in repr_str
        assert "timeout=5.0s" in repr_str


class TestLiquidationConfigTypeValidation:
    """Test type validation catches incorrect types."""

    def test_emergency_liquidation_must_be_bool(self):
        """emergency_liquidation must be bool."""
        with pytest.raises(ConfigurationError, match="must be bool"):
            LiquidationConfig(emergency_liquidation="true")  # string not bool

    def test_close_positions_must_be_bool(self):
        """close_positions must be bool."""
        with pytest.raises(ConfigurationError, match="must be bool"):
            LiquidationConfig(close_positions=1)  # int not bool

    def test_cancel_orders_must_be_bool(self):
        """cancel_orders must be bool."""
        with pytest.raises(ConfigurationError, match="must be bool"):
            LiquidationConfig(cancel_orders="yes")  # string not bool

    def test_timeout_seconds_must_be_numeric(self):
        """timeout_seconds must be numeric (int or float)."""
        with pytest.raises(ConfigurationError, match="must be numeric"):
            LiquidationConfig(timeout_seconds="5.0")  # string not numeric

    def test_max_retries_must_be_int(self):
        """max_retries must be int."""
        with pytest.raises(ConfigurationError, match="must be int"):
            LiquidationConfig(max_retries=3.5)  # float not int

    def test_retry_delay_seconds_must_be_numeric(self):
        """retry_delay_seconds must be numeric."""
        with pytest.raises(ConfigurationError, match="must be numeric"):
            LiquidationConfig(retry_delay_seconds=None)  # None not numeric


class TestLiquidationConfigRangeValidation:
    """Test range validation enforces business rules."""

    def test_timeout_minimum_1_second(self):
        """timeout_seconds must be >= 1.0."""
        with pytest.raises(ConfigurationError, match="must be 1.0-30.0"):
            LiquidationConfig(timeout_seconds=0.5)

    def test_timeout_maximum_30_seconds(self):
        """timeout_seconds must be <= 30.0."""
        with pytest.raises(ConfigurationError, match="must be 1.0-30.0"):
            LiquidationConfig(timeout_seconds=31.0)

    def test_timeout_valid_range_accepted(self):
        """Valid timeout values are accepted."""
        config = LiquidationConfig(timeout_seconds=10.0)
        assert config.timeout_seconds == 10.0

    def test_max_retries_minimum_0(self):
        """max_retries must be >= 0."""
        with pytest.raises(ConfigurationError, match="must be 0-10"):
            LiquidationConfig(max_retries=-1)

    def test_max_retries_maximum_10(self):
        """max_retries must be <= 10."""
        with pytest.raises(ConfigurationError, match="must be 0-10"):
            LiquidationConfig(max_retries=11)

    def test_max_retries_valid_range_accepted(self):
        """Valid retry values are accepted."""
        config = LiquidationConfig(max_retries=5)
        assert config.max_retries == 5

    def test_retry_delay_minimum_0_1_seconds(self):
        """retry_delay_seconds must be >= 0.1."""
        with pytest.raises(ConfigurationError, match="must be 0.1-5.0"):
            LiquidationConfig(retry_delay_seconds=0.05)

    def test_retry_delay_maximum_5_seconds(self):
        """retry_delay_seconds must be <= 5.0."""
        with pytest.raises(ConfigurationError, match="must be 0.1-5.0"):
            LiquidationConfig(retry_delay_seconds=5.5)

    def test_retry_delay_valid_range_accepted(self):
        """Valid retry delay values are accepted."""
        config = LiquidationConfig(retry_delay_seconds=1.0)
        assert config.retry_delay_seconds == 1.0


class TestLiquidationConfigConsistencyValidation:
    """Test cross-field consistency validation."""

    def test_disabled_liquidation_requires_both_flags_false(self):
        """If emergency_liquidation=False, both close/cancel must be False."""
        # Invalid: liquidation disabled but close_positions=True
        with pytest.raises(ConfigurationError, match="Inconsistent configuration"):
            LiquidationConfig(
                emergency_liquidation=False,
                close_positions=True,
                cancel_orders=False
            )

        # Invalid: liquidation disabled but cancel_orders=True
        with pytest.raises(ConfigurationError, match="Inconsistent configuration"):
            LiquidationConfig(
                emergency_liquidation=False,
                close_positions=False,
                cancel_orders=True
            )

        # Valid: liquidation disabled, both flags False
        config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False
        )
        assert config.emergency_liquidation is False


class TestLiquidationConfigSecurityValidation:
    """Test security warnings for risky configurations."""

    def test_disabled_liquidation_logs_critical_warning(self, caplog):
        """Disabled liquidation triggers CRITICAL log."""
        import logging
        caplog.set_level(logging.CRITICAL)

        LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False
        )

        assert "CAPITAL AT RISK" in caplog.text
        assert "emergency_liquidation=False" in caplog.text

    def test_security_first_config_logs_info(self, caplog):
        """Security-first configuration logs INFO confirmation."""
        import logging
        caplog.set_level(logging.INFO)

        LiquidationConfig(
            emergency_liquidation=True,
            close_positions=True,
            cancel_orders=True
        )

        assert "Security-first configuration" in caplog.text


class TestLiquidationConfigSerialization:
    """Test serialization to/from dictionary."""

    def test_to_dict_exports_all_fields(self):
        """to_dict() exports all configuration fields."""
        config = LiquidationConfig(
            emergency_liquidation=True,
            close_positions=True,
            cancel_orders=True,
            timeout_seconds=10.0,
            max_retries=5,
            retry_delay_seconds=1.0,
        )

        config_dict = config.to_dict()

        assert config_dict["emergency_liquidation"] is True
        assert config_dict["close_positions"] is True
        assert config_dict["cancel_orders"] is True
        assert config_dict["timeout_seconds"] == 10.0
        assert config_dict["max_retries"] == 5
        assert config_dict["retry_delay_seconds"] == 1.0

    def test_from_dict_creates_valid_config(self):
        """from_dict() creates valid LiquidationConfig."""
        config_dict = {
            "emergency_liquidation": False,
            "close_positions": False,
            "cancel_orders": False,
            "timeout_seconds": 15.0,
            "max_retries": 7,
            "retry_delay_seconds": 2.0,
        }

        config = LiquidationConfig.from_dict(config_dict)

        assert config.emergency_liquidation is False
        assert config.close_positions is False
        assert config.cancel_orders is False
        assert config.timeout_seconds == 15.0
        assert config.max_retries == 7
        assert config.retry_delay_seconds == 2.0

    def test_from_dict_uses_defaults_for_missing_fields(self):
        """from_dict() uses defaults for missing fields."""
        config_dict = {}  # Empty dict

        config = LiquidationConfig.from_dict(config_dict)

        # Should use security-first defaults
        assert config.emergency_liquidation is True
        assert config.close_positions is True
        assert config.cancel_orders is True
        assert config.timeout_seconds == 5.0
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 0.5

    def test_roundtrip_serialization(self):
        """Config → dict → Config preserves values."""
        original = LiquidationConfig(
            emergency_liquidation=True,
            close_positions=False,
            cancel_orders=True,
            timeout_seconds=7.5,
            max_retries=2,
            retry_delay_seconds=0.75,
        )

        config_dict = original.to_dict()
        restored = LiquidationConfig.from_dict(config_dict)

        assert restored.emergency_liquidation == original.emergency_liquidation
        assert restored.close_positions == original.close_positions
        assert restored.cancel_orders == original.cancel_orders
        assert restored.timeout_seconds == original.timeout_seconds
        assert restored.max_retries == original.max_retries
        assert restored.retry_delay_seconds == original.retry_delay_seconds
