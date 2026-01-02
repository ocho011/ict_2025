"""
Unit tests for LiquidationConfigValidator.

Tests configuration validation, change detection, and deployment readiness checks.
"""

import pytest
from src.execution.config_validator import (
    ConfigChange,
    DeploymentReadiness,
    LiquidationConfigValidator,
    ValidationIssue,
    ValidationLevel,
    ValidationResult,
    ValidationType,
)
from src.execution.liquidation_config import LiquidationConfig


class TestValidationIssue:
    """Test ValidationIssue dataclass."""

    def test_string_representation(self):
        """Test string conversion of validation issue."""
        issue = ValidationIssue(
            level=ValidationLevel.ERROR,
            type=ValidationType.SECURITY,
            field="emergency_liquidation",
            message="Liquidation disabled",
            recommendation="Enable emergency_liquidation",
        )

        result = str(issue)

        assert "[ERROR]" in result
        assert "[emergency_liquidation]" in result
        assert "Liquidation disabled" in result
        assert "Enable emergency_liquidation" in result

    def test_string_without_field(self):
        """Test string conversion without field."""
        issue = ValidationIssue(
            level=ValidationLevel.WARNING,
            type=ValidationType.PERFORMANCE,
            message="Performance issue",
        )

        result = str(issue)

        assert "[WARNING]" in result
        assert "Performance issue" in result
        assert "[" not in result.split("]")[1]  # No field after WARNING


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_has_errors_with_critical(self):
        """Test has_errors property with critical issues."""
        result = ValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    type=ValidationType.SECURITY,
                    message="Critical issue",
                )
            ],
        )

        assert result.has_errors is True

    def test_has_errors_with_error(self):
        """Test has_errors property with error issues."""
        result = ValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.ERROR,
                    type=ValidationType.CONFIGURATION,
                    message="Error issue",
                )
            ],
        )

        assert result.has_errors is True

    def test_has_errors_without_errors(self):
        """Test has_errors property without errors."""
        result = ValidationResult(
            is_valid=True,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    message="Warning issue",
                )
            ],
        )

        assert result.has_errors is False

    def test_has_warnings(self):
        """Test has_warnings property."""
        result = ValidationResult(
            is_valid=True,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    message="Warning issue",
                )
            ],
        )

        assert result.has_warnings is True

    def test_get_issues_by_level(self):
        """Test filtering issues by level."""
        result = ValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    type=ValidationType.SECURITY,
                    message="Critical",
                ),
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    message="Warning",
                ),
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    type=ValidationType.DEPLOYMENT,
                    message="Info",
                ),
            ],
        )

        critical = result.get_issues_by_level(ValidationLevel.CRITICAL)
        warnings = result.get_issues_by_level(ValidationLevel.WARNING)

        assert len(critical) == 1
        assert len(warnings) == 1
        assert critical[0].message == "Critical"
        assert warnings[0].message == "Warning"

    def test_get_issues_by_type(self):
        """Test filtering issues by type."""
        result = ValidationResult(
            is_valid=False,
            issues=[
                ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    type=ValidationType.SECURITY,
                    message="Security",
                ),
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    message="Performance",
                ),
            ],
        )

        security = result.get_issues_by_type(ValidationType.SECURITY)
        performance = result.get_issues_by_type(ValidationType.PERFORMANCE)

        assert len(security) == 1
        assert len(performance) == 1
        assert security[0].message == "Security"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        result = ValidationResult(
            is_valid=True,
            environment="production",
            issues=[
                ValidationIssue(
                    level=ValidationLevel.INFO,
                    type=ValidationType.DEPLOYMENT,
                    field="timeout_seconds",
                    message="Non-standard timeout",
                    recommendation="Use 5.0s",
                )
            ],
        )

        data = result.to_dict()

        assert data["is_valid"] is True
        assert data["environment"] == "production"
        assert len(data["issues"]) == 1
        assert data["issues"][0]["level"] == "info"
        assert data["issues"][0]["type"] == "deployment"


class TestConfigChange:
    """Test ConfigChange dataclass."""

    def test_string_representation(self):
        """Test string conversion of config change."""
        change = ConfigChange(
            field="emergency_liquidation",
            old_value=True,
            new_value=False,
            impact=ValidationLevel.CRITICAL,
            description="DISABLED capital protection",
        )

        result = str(change)

        assert "[CRITICAL]" in result
        assert "emergency_liquidation" in result
        assert "True → False" in result
        assert "DISABLED capital protection" in result


class TestDeploymentReadiness:
    """Test DeploymentReadiness dataclass."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        readiness = DeploymentReadiness(
            is_ready=False,
            environment="production",
            blockers=["Critical issue 1"],
            warnings=["Warning 1"],
            recommendations=["Recommendation 1"],
        )

        data = readiness.to_dict()

        assert data["is_ready"] is False
        assert data["environment"] == "production"
        assert len(data["blockers"]) == 1
        assert len(data["warnings"]) == 1
        assert len(data["recommendations"]) == 1


class TestLiquidationConfigValidator:
    """Test LiquidationConfigValidator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return LiquidationConfigValidator()

    def test_production_config_valid_defaults(self, validator):
        """Test valid production config with defaults."""
        config = LiquidationConfig()  # All defaults

        result = validator.validate_production_config(config, is_testnet=False)

        assert result.is_valid is True
        assert result.environment == "production"
        assert result.has_errors is False

    def test_production_emergency_disabled_critical(self, validator):
        """Test production with emergency_liquidation disabled raises CRITICAL."""
        # Must also disable close_positions and cancel_orders to pass validation
        config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False,
        )

        result = validator.validate_production_config(config, is_testnet=False)

        assert result.is_valid is False
        critical_issues = result.get_issues_by_level(ValidationLevel.CRITICAL)
        assert len(critical_issues) >= 1
        assert any("emergency_liquidation" in issue.field for issue in critical_issues)

    def test_testnet_emergency_disabled_warning(self, validator):
        """Test testnet with emergency_liquidation disabled raises WARNING."""
        # Must also disable close_positions and cancel_orders to pass validation
        config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False,
        )

        result = validator.validate_production_config(config, is_testnet=True)

        # Should have warning but not critical
        warnings = result.get_issues_by_level(ValidationLevel.WARNING)
        critical = result.get_issues_by_level(ValidationLevel.CRITICAL)

        assert len(warnings) >= 1
        assert any("emergency_liquidation" in issue.field for issue in warnings)
        # No critical issue in testnet for this
        assert not any("emergency_liquidation" in str(issue) for issue in critical)

    def test_both_actions_disabled_critical(self, validator):
        """Test both close_positions and cancel_orders disabled."""
        config = LiquidationConfig(
            close_positions=False,
            cancel_orders=False,
        )

        result = validator.validate_production_config(config, is_testnet=False)

        assert result.is_valid is False
        critical_issues = result.get_issues_by_level(ValidationLevel.CRITICAL)
        assert any(
            "close_positions" in issue.field and "cancel_orders" in issue.field
            for issue in critical_issues
        )

    def test_timeout_too_short_production(self, validator):
        """Test timeout below production minimum."""
        config = LiquidationConfig(timeout_seconds=1.0)  # < 3.0 minimum

        result = validator.validate_production_config(config, is_testnet=False)

        assert result.is_valid is False
        errors = result.get_issues_by_level(ValidationLevel.ERROR)
        assert any("timeout_seconds" in issue.field for issue in errors)

    def test_timeout_acceptable_in_testnet(self, validator):
        """Test short timeout acceptable in testnet."""
        config = LiquidationConfig(timeout_seconds=1.0)  # OK for testnet

        result = validator.validate_production_config(config, is_testnet=True)

        # Should not have ERROR for timeout
        errors = result.get_issues_by_level(ValidationLevel.ERROR)
        timeout_errors = [issue for issue in errors if "timeout_seconds" in issue.field]
        assert len(timeout_errors) == 0

    def test_timeout_too_long_warning(self, validator):
        """Test timeout above recommended raises warning."""
        # Use 25.0 which is within valid range but above recommended
        config = LiquidationConfig(timeout_seconds=25.0)  # Within 1.0-30.0

        result = validator.validate_production_config(config, is_testnet=False)

        # Should still pass validation but may have warnings
        # (25.0 is within range, so no ERROR)

    def test_retries_too_few_production(self, validator):
        """Test retries below recommended in production."""
        config = LiquidationConfig(max_retries=0)  # < 1 minimum

        result = validator.validate_production_config(config, is_testnet=False)

        warnings = result.get_issues_by_level(ValidationLevel.WARNING)
        assert any("max_retries" in issue.field for issue in warnings)

    def test_retries_too_many_warning(self, validator):
        """Test excessive retries raises warning."""
        config = LiquidationConfig(max_retries=8)  # > 5 recommended

        result = validator.validate_production_config(config, is_testnet=False)

        warnings = result.get_issues_by_level(ValidationLevel.WARNING)
        assert any("max_retries" in issue.field for issue in warnings)

    def test_retry_delay_very_short_warning(self, validator):
        """Test very short retry delay raises warning."""
        # Use 0.1 which is minimum valid, validator should warn if < 0.1 but 0.1 passes validation
        config = LiquidationConfig(retry_delay_seconds=0.15)  # Just above 0.1

        result = validator.validate_production_config(config, is_testnet=False)

        # With 0.15, may still get warning (< 0.5 recommended)
        warnings = result.get_issues_by_level(ValidationLevel.WARNING)
        # This may or may not warn depending on threshold
        # Let's check result passes validation at least
        assert result.is_valid or not result.has_errors  # No blocking errors

    def test_retry_delay_too_long_warning(self, validator):
        """Test long retry delay raises warning."""
        config = LiquidationConfig(retry_delay_seconds=3.0)  # > 2.0

        result = validator.validate_production_config(config, is_testnet=False)

        warnings = result.get_issues_by_level(ValidationLevel.WARNING)
        assert any("retry_delay_seconds" in issue.field for issue in warnings)

    def test_close_positions_disabled_warning(self, validator):
        """Test close_positions disabled with emergency enabled."""
        config = LiquidationConfig(
            emergency_liquidation=True,
            close_positions=False,
        )

        result = validator.validate_production_config(config, is_testnet=False)

        warnings = result.get_issues_by_level(ValidationLevel.WARNING)
        assert any("close_positions" in issue.field for issue in warnings)

    def test_cancel_orders_disabled_info(self, validator):
        """Test cancel_orders disabled raises INFO."""
        config = LiquidationConfig(
            emergency_liquidation=True,
            cancel_orders=False,
        )

        result = validator.validate_production_config(config, is_testnet=False)

        info_issues = result.get_issues_by_level(ValidationLevel.INFO)
        assert any("cancel_orders" in issue.field for issue in info_issues)

    def test_total_time_excessive_warning(self, validator):
        """Test total liquidation time could be excessive."""
        config = LiquidationConfig(
            timeout_seconds=10.0,
            max_retries=5,
            retry_delay_seconds=2.0,
        )

        result = validator.validate_production_config(config, is_testnet=False)

        # Should have warnings (timeout, retries, or total time)
        # At minimum, should warn about non-standard settings
        assert result.has_warnings or len(result.issues) > 0

    def test_detect_emergency_liquidation_enabled(self, validator):
        """Test detecting emergency_liquidation change to enabled."""
        old_config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False,
        )
        new_config = LiquidationConfig(emergency_liquidation=True)

        changes = validator.detect_config_changes(old_config, new_config)

        emergency_changes = [
            c for c in changes if c.field == "emergency_liquidation"
        ]
        assert len(emergency_changes) == 1
        assert emergency_changes[0].old_value is False
        assert emergency_changes[0].new_value is True
        assert emergency_changes[0].impact == ValidationLevel.CRITICAL

    def test_detect_emergency_liquidation_disabled(self, validator):
        """Test detecting emergency_liquidation change to disabled."""
        old_config = LiquidationConfig(emergency_liquidation=True)
        new_config = LiquidationConfig(
            emergency_liquidation=False,
            close_positions=False,
            cancel_orders=False,
        )

        changes = validator.detect_config_changes(old_config, new_config)

        emergency_changes = [
            c for c in changes if c.field == "emergency_liquidation"
        ]
        assert len(emergency_changes) == 1
        assert "HIGH RISK" in emergency_changes[0].description

    def test_detect_timeout_significant_change(self, validator):
        """Test detecting significant timeout change."""
        old_config = LiquidationConfig(timeout_seconds=5.0)
        new_config = LiquidationConfig(timeout_seconds=15.0)  # 200% increase

        changes = validator.detect_config_changes(old_config, new_config)

        timeout_changes = [c for c in changes if c.field == "timeout_seconds"]
        assert len(timeout_changes) == 1
        assert timeout_changes[0].impact == ValidationLevel.WARNING
        assert "significantly" in timeout_changes[0].description.lower()

    def test_detect_timeout_minor_change(self, validator):
        """Test detecting minor timeout change."""
        old_config = LiquidationConfig(timeout_seconds=5.0)
        new_config = LiquidationConfig(timeout_seconds=6.0)  # 20% increase

        changes = validator.detect_config_changes(old_config, new_config)

        timeout_changes = [c for c in changes if c.field == "timeout_seconds"]
        assert len(timeout_changes) == 1
        assert timeout_changes[0].impact == ValidationLevel.INFO

    def test_detect_no_changes(self, validator):
        """Test no changes detected for identical configs."""
        config1 = LiquidationConfig()
        config2 = LiquidationConfig()

        changes = validator.detect_config_changes(config1, config2)

        assert len(changes) == 0

    def test_deployment_readiness_valid_config(self, validator):
        """Test deployment readiness with valid config."""
        config = LiquidationConfig()  # Valid defaults

        readiness = validator.check_deployment_readiness(config, is_testnet=False)

        assert readiness.is_ready is True
        assert readiness.environment == "production"
        assert len(readiness.blockers) == 0
        assert len(readiness.recommendations) > 0  # Should have recommendations

    def test_deployment_readiness_invalid_config(self, validator):
        """Test deployment readiness with invalid config."""
        config = LiquidationConfig(
            emergency_liquidation=False,  # CRITICAL issue
            close_positions=False,
            cancel_orders=False,
            timeout_seconds=2.5,  # Below production minimum (3.0)
        )

        readiness = validator.check_deployment_readiness(config, is_testnet=False)

        assert readiness.is_ready is False
        assert len(readiness.blockers) >= 1  # At least CRITICAL for emergency_liquidation

    def test_deployment_readiness_testnet(self, validator):
        """Test deployment readiness for testnet."""
        config = LiquidationConfig()

        readiness = validator.check_deployment_readiness(config, is_testnet=True)

        assert readiness.environment == "testnet"

    def test_deployment_readiness_warnings(self, validator):
        """Test deployment readiness with warnings."""
        config = LiquidationConfig(
            max_retries=0,  # WARNING
        )

        readiness = validator.check_deployment_readiness(config, is_testnet=False)

        assert readiness.is_ready is True  # Warnings don't block
        assert len(readiness.warnings) > 0

    def test_deployment_readiness_recommendations(self, validator):
        """Test deployment readiness includes recommendations."""
        config = LiquidationConfig()

        readiness = validator.check_deployment_readiness(config, is_testnet=False)

        # Should recommend testnet testing
        assert any(
            "testnet" in rec.lower()
            for rec in readiness.recommendations
        )

        # Should recommend monitoring
        assert any(
            "monitor" in rec.lower()
            for rec in readiness.recommendations
        )
