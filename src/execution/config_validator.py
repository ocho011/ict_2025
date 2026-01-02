"""
Configuration validator for production deployment.

Validates liquidation configuration against production requirements,
detects configuration changes, and performs pre-deployment checks.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import logging

from src.execution.liquidation_config import LiquidationConfig


logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    """Validation severity level."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationType(Enum):
    """Type of validation check."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    CONFIGURATION = "configuration"
    DEPLOYMENT = "deployment"


@dataclass
class ValidationIssue:
    """Represents a validation issue found during checks."""

    level: ValidationLevel
    type: ValidationType
    message: str
    field: Optional[str] = None
    recommendation: Optional[str] = None

    def __str__(self) -> str:
        """String representation of validation issue."""
        parts = [f"[{self.level.value.upper()}]"]
        if self.field:
            parts.append(f"[{self.field}]")
        parts.append(self.message)
        if self.recommendation:
            parts.append(f"→ {self.recommendation}")
        return " ".join(parts)


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    environment: Optional[str] = None

    @property
    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(
            issue.level in (ValidationLevel.ERROR, ValidationLevel.CRITICAL)
            for issue in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return any(issue.level == ValidationLevel.WARNING for issue in self.issues)

    def get_issues_by_level(self, level: ValidationLevel) -> List[ValidationIssue]:
        """Get all issues of a specific level."""
        return [issue for issue in self.issues if issue.level == level]

    def get_issues_by_type(self, issue_type: ValidationType) -> List[ValidationIssue]:
        """Get all issues of a specific type."""
        return [issue for issue in self.issues if issue.type == issue_type]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "is_valid": self.is_valid,
            "environment": self.environment,
            "issues": [
                {
                    "level": issue.level.value,
                    "type": issue.type.value,
                    "message": issue.message,
                    "field": issue.field,
                    "recommendation": issue.recommendation,
                }
                for issue in self.issues
            ],
        }


@dataclass
class ConfigChange:
    """Represents a configuration change detected."""

    field: str
    old_value: Any
    new_value: Any
    impact: ValidationLevel
    description: str

    def __str__(self) -> str:
        """String representation of config change."""
        return (
            f"[{self.impact.value.upper()}] {self.field}: "
            f"{self.old_value} → {self.new_value} ({self.description})"
        )


@dataclass
class DeploymentReadiness:
    """Assessment of deployment readiness."""

    is_ready: bool
    environment: str
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "is_ready": self.is_ready,
            "environment": self.environment,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class LiquidationConfigValidator:
    """
    Validates liquidation configuration for production deployment.

    Performs comprehensive validation including:
    - Security requirements enforcement
    - Performance boundary checks
    - Environment-specific validation
    - Configuration change detection
    - Deployment readiness assessment

    Example:
        >>> config = LiquidationConfig()
        >>> validator = LiquidationConfigValidator()
        >>> result = validator.validate_production_config(config, is_testnet=False)
        >>> if not result.is_valid:
        ...     for issue in result.issues:
        ...         print(issue)
    """

    # Production requirements
    MIN_TIMEOUT_PRODUCTION = 3.0  # seconds
    MAX_TIMEOUT_PRODUCTION = 30.0  # seconds
    MIN_RETRIES_PRODUCTION = 1
    MAX_RETRIES_PRODUCTION = 5

    # Testnet can be more relaxed
    MIN_TIMEOUT_TESTNET = 1.0
    MAX_TIMEOUT_TESTNET = 60.0
    MIN_RETRIES_TESTNET = 0
    MAX_RETRIES_TESTNET = 10

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize validator.

        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

    def validate_production_config(
        self,
        config: LiquidationConfig,
        is_testnet: bool = False,
    ) -> ValidationResult:
        """
        Validate liquidation configuration against production requirements.

        Args:
            config: Configuration to validate
            is_testnet: Whether this is testnet environment

        Returns:
            ValidationResult with all issues found
        """
        environment = "testnet" if is_testnet else "production"
        issues: List[ValidationIssue] = []

        self.logger.info(f"Validating liquidation config for {environment}")

        # Security validations (CRITICAL)
        issues.extend(self._validate_security(config, is_testnet))

        # Performance validations (WARNING/ERROR)
        issues.extend(self._validate_performance(config, is_testnet))

        # Configuration consistency (WARNING/ERROR)
        issues.extend(self._validate_consistency(config, is_testnet))

        # Deployment-specific checks
        issues.extend(self._validate_deployment(config, is_testnet))

        # Determine if configuration is valid
        is_valid = not any(
            issue.level in (ValidationLevel.ERROR, ValidationLevel.CRITICAL)
            for issue in issues
        )

        result = ValidationResult(
            is_valid=is_valid,
            issues=issues,
            environment=environment,
        )

        self._log_validation_result(result)

        return result

    def _validate_security(
        self,
        config: LiquidationConfig,
        is_testnet: bool,
    ) -> List[ValidationIssue]:
        """Validate security requirements."""
        issues: List[ValidationIssue] = []

        # CRITICAL: emergency_liquidation must be True in production
        if not is_testnet and not config.emergency_liquidation:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    type=ValidationType.SECURITY,
                    field="emergency_liquidation",
                    message="Emergency liquidation is DISABLED in PRODUCTION",
                    recommendation="Set emergency_liquidation=true to protect capital",
                )
            )

        # WARNING: emergency_liquidation disabled even in testnet
        if is_testnet and not config.emergency_liquidation:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.SECURITY,
                    field="emergency_liquidation",
                    message="Emergency liquidation is disabled in testnet",
                    recommendation="Enable for realistic testing",
                )
            )

        # CRITICAL: At least one liquidation action must be enabled
        if not config.close_positions and not config.cancel_orders:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.CRITICAL,
                    type=ValidationType.SECURITY,
                    field="close_positions,cancel_orders",
                    message="Both position close and order cancel are disabled",
                    recommendation="Enable at least one liquidation action",
                )
            )

        return issues

    def _validate_performance(
        self,
        config: LiquidationConfig,
        is_testnet: bool,
    ) -> List[ValidationIssue]:
        """Validate performance boundaries."""
        issues: List[ValidationIssue] = []

        # Timeout validation (environment-specific)
        if is_testnet:
            min_timeout = self.MIN_TIMEOUT_TESTNET
            max_timeout = self.MAX_TIMEOUT_TESTNET
        else:
            min_timeout = self.MIN_TIMEOUT_PRODUCTION
            max_timeout = self.MAX_TIMEOUT_PRODUCTION

        if config.timeout_seconds < min_timeout:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.ERROR,
                    type=ValidationType.PERFORMANCE,
                    field="timeout_seconds",
                    message=f"Timeout {config.timeout_seconds}s is below minimum {min_timeout}s",
                    recommendation=f"Increase timeout to at least {min_timeout}s",
                )
            )

        if config.timeout_seconds > max_timeout:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    field="timeout_seconds",
                    message=f"Timeout {config.timeout_seconds}s exceeds recommended {max_timeout}s",
                    recommendation=f"Consider reducing to {max_timeout}s for faster shutdown",
                )
            )

        # Retry validation (environment-specific)
        if is_testnet:
            min_retries = self.MIN_RETRIES_TESTNET
            max_retries = self.MAX_RETRIES_TESTNET
        else:
            min_retries = self.MIN_RETRIES_PRODUCTION
            max_retries = self.MAX_RETRIES_PRODUCTION

        if config.max_retries < min_retries:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    field="max_retries",
                    message=f"Retries {config.max_retries} below recommended {min_retries}",
                    recommendation=f"Increase to at least {min_retries} for resilience",
                )
            )

        if config.max_retries > max_retries:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    field="max_retries",
                    message=f"Retries {config.max_retries} exceeds recommended {max_retries}",
                    recommendation=f"Reduce to {max_retries} to prevent retry storms",
                )
            )

        # Retry delay validation
        if config.retry_delay_seconds < 0.1:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    field="retry_delay_seconds",
                    message=f"Retry delay {config.retry_delay_seconds}s is very short",
                    recommendation="Consider increasing to 0.5s to avoid API rate limits",
                )
            )

        if config.retry_delay_seconds > 2.0:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    field="retry_delay_seconds",
                    message=f"Retry delay {config.retry_delay_seconds}s is quite long",
                    recommendation="Consider reducing to 1.0s for faster recovery",
                )
            )

        return issues

    def _validate_consistency(
        self,
        config: LiquidationConfig,
        is_testnet: bool,
    ) -> List[ValidationIssue]:
        """Validate configuration consistency."""
        issues: List[ValidationIssue] = []

        # If emergency_liquidation is enabled but no actions configured
        if config.emergency_liquidation:
            if not config.close_positions:
                issues.append(
                    ValidationIssue(
                        level=ValidationLevel.WARNING,
                        type=ValidationType.CONFIGURATION,
                        field="close_positions",
                        message="Emergency liquidation enabled but position close disabled",
                        recommendation="Enable close_positions for effective liquidation",
                    )
                )

            if not config.cancel_orders:
                issues.append(
                    ValidationIssue(
                        level=ValidationLevel.INFO,
                        type=ValidationType.CONFIGURATION,
                        field="cancel_orders",
                        message="Order cancellation is disabled",
                        recommendation="Consider enabling for complete liquidation",
                    )
                )

        # Calculate total possible liquidation time
        total_time = config.timeout_seconds + (
            config.max_retries * config.retry_delay_seconds * 2  # Exponential backoff worst case
        )

        if total_time > 30.0 and not is_testnet:
            issues.append(
                ValidationIssue(
                    level=ValidationLevel.WARNING,
                    type=ValidationType.PERFORMANCE,
                    field="timeout_seconds,max_retries,retry_delay_seconds",
                    message=f"Total liquidation time could exceed {total_time:.1f}s",
                    recommendation="Reduce timeout or retries for faster shutdown",
                )
            )

        return issues

    def _validate_deployment(
        self,
        config: LiquidationConfig,
        is_testnet: bool,
    ) -> List[ValidationIssue]:
        """Validate deployment-specific requirements."""
        issues: List[ValidationIssue] = []

        # Production-only checks
        if not is_testnet:
            # Recommend specific production settings
            if config.timeout_seconds != 5.0:
                issues.append(
                    ValidationIssue(
                        level=ValidationLevel.INFO,
                        type=ValidationType.DEPLOYMENT,
                        field="timeout_seconds",
                        message=f"Using non-standard timeout: {config.timeout_seconds}s",
                        recommendation="Standard production timeout is 5.0s",
                    )
                )

            if config.max_retries != 3:
                issues.append(
                    ValidationIssue(
                        level=ValidationLevel.INFO,
                        type=ValidationType.DEPLOYMENT,
                        field="max_retries",
                        message=f"Using non-standard retry count: {config.max_retries}",
                        recommendation="Standard production retries is 3",
                    )
                )

        return issues

    def detect_config_changes(
        self,
        old_config: LiquidationConfig,
        new_config: LiquidationConfig,
    ) -> List[ConfigChange]:
        """
        Detect changes between two configurations.

        Args:
            old_config: Previous configuration
            new_config: New configuration

        Returns:
            List of detected changes with impact assessment
        """
        changes: List[ConfigChange] = []

        # Check each field
        if old_config.emergency_liquidation != new_config.emergency_liquidation:
            impact = ValidationLevel.CRITICAL
            if new_config.emergency_liquidation:
                description = "ENABLED capital protection"
            else:
                description = "DISABLED capital protection - HIGH RISK"

            changes.append(
                ConfigChange(
                    field="emergency_liquidation",
                    old_value=old_config.emergency_liquidation,
                    new_value=new_config.emergency_liquidation,
                    impact=impact,
                    description=description,
                )
            )

        if old_config.close_positions != new_config.close_positions:
            changes.append(
                ConfigChange(
                    field="close_positions",
                    old_value=old_config.close_positions,
                    new_value=new_config.close_positions,
                    impact=ValidationLevel.WARNING,
                    description="Position closure behavior changed",
                )
            )

        if old_config.cancel_orders != new_config.cancel_orders:
            changes.append(
                ConfigChange(
                    field="cancel_orders",
                    old_value=old_config.cancel_orders,
                    new_value=new_config.cancel_orders,
                    impact=ValidationLevel.INFO,
                    description="Order cancellation behavior changed",
                )
            )

        if old_config.timeout_seconds != new_config.timeout_seconds:
            change_pct = abs(
                (new_config.timeout_seconds - old_config.timeout_seconds)
                / old_config.timeout_seconds
            ) * 100

            if change_pct > 50:
                impact = ValidationLevel.WARNING
                description = f"Timeout changed significantly ({change_pct:.0f}%)"
            else:
                impact = ValidationLevel.INFO
                description = "Timeout adjusted"

            changes.append(
                ConfigChange(
                    field="timeout_seconds",
                    old_value=old_config.timeout_seconds,
                    new_value=new_config.timeout_seconds,
                    impact=impact,
                    description=description,
                )
            )

        if old_config.max_retries != new_config.max_retries:
            changes.append(
                ConfigChange(
                    field="max_retries",
                    old_value=old_config.max_retries,
                    new_value=new_config.max_retries,
                    impact=ValidationLevel.INFO,
                    description="Retry count changed",
                )
            )

        if old_config.retry_delay_seconds != new_config.retry_delay_seconds:
            changes.append(
                ConfigChange(
                    field="retry_delay_seconds",
                    old_value=old_config.retry_delay_seconds,
                    new_value=new_config.retry_delay_seconds,
                    impact=ValidationLevel.INFO,
                    description="Retry delay adjusted",
                )
            )

        return changes

    def check_deployment_readiness(
        self,
        config: LiquidationConfig,
        is_testnet: bool = False,
    ) -> DeploymentReadiness:
        """
        Check if configuration is ready for deployment.

        Args:
            config: Configuration to check
            is_testnet: Whether this is testnet deployment

        Returns:
            DeploymentReadiness assessment
        """
        environment = "testnet" if is_testnet else "production"
        blockers: List[str] = []
        warnings: List[str] = []
        recommendations: List[str] = []

        # Validate configuration
        validation_result = self.validate_production_config(config, is_testnet)

        # Extract blockers (CRITICAL/ERROR)
        for issue in validation_result.get_issues_by_level(ValidationLevel.CRITICAL):
            blockers.append(f"{issue.field}: {issue.message}")

        for issue in validation_result.get_issues_by_level(ValidationLevel.ERROR):
            blockers.append(f"{issue.field}: {issue.message}")

        # Extract warnings
        for issue in validation_result.get_issues_by_level(ValidationLevel.WARNING):
            warnings.append(f"{issue.field}: {issue.message}")

        # Extract recommendations
        for issue in validation_result.issues:
            if issue.recommendation:
                recommendations.append(f"{issue.field}: {issue.recommendation}")

        # Additional production checks
        if not is_testnet:
            # Recommend testing first
            recommendations.append(
                "Test liquidation flow in testnet environment before production deployment"
            )

            # Recommend monitoring setup
            recommendations.append(
                "Ensure liquidation events are monitored in production alerting system"
            )

            # Recommend documentation review
            recommendations.append(
                "Review emergency liquidation runbook before deployment"
            )

        is_ready = len(blockers) == 0

        readiness = DeploymentReadiness(
            is_ready=is_ready,
            environment=environment,
            blockers=blockers,
            warnings=warnings,
            recommendations=recommendations,
        )

        self._log_deployment_readiness(readiness)

        return readiness

    def _log_validation_result(self, result: ValidationResult) -> None:
        """Log validation result summary."""
        if result.is_valid:
            self.logger.info(
                f"Configuration validation PASSED for {result.environment} "
                f"({len(result.issues)} non-blocking issues)"
            )
        else:
            self.logger.error(
                f"Configuration validation FAILED for {result.environment} "
                f"({len(result.get_issues_by_level(ValidationLevel.CRITICAL))} critical, "
                f"{len(result.get_issues_by_level(ValidationLevel.ERROR))} errors)"
            )

        # Log critical/error issues
        for issue in result.get_issues_by_level(ValidationLevel.CRITICAL):
            self.logger.critical(str(issue))

        for issue in result.get_issues_by_level(ValidationLevel.ERROR):
            self.logger.error(str(issue))

    def _log_deployment_readiness(self, readiness: DeploymentReadiness) -> None:
        """Log deployment readiness summary."""
        if readiness.is_ready:
            self.logger.info(
                f"Deployment READY for {readiness.environment} "
                f"({len(readiness.warnings)} warnings, "
                f"{len(readiness.recommendations)} recommendations)"
            )
        else:
            self.logger.error(
                f"Deployment BLOCKED for {readiness.environment} "
                f"({len(readiness.blockers)} blockers)"
            )
            for blocker in readiness.blockers:
                self.logger.error(f"BLOCKER: {blocker}")
