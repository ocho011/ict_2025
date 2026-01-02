"""
Emergency liquidation configuration with security-first validation.

Design Principles:
- Default to capital protection (emergency_liquidation=True)
- Explicit warnings when capital protection is disabled
- Comprehensive validation with meaningful error messages
- Immutable configuration (dataclass frozen after validation)
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class LiquidationConfig:
    """
    Configuration for emergency position liquidation system.

    Security-First Design:
    - Default emergency_liquidation=True protects capital by default
    - Explicit opt-out required to disable liquidation (reverse the risk)
    - Comprehensive validation prevents misconfigurations
    - CRITICAL warnings when capital protection is disabled

    Attributes:
        emergency_liquidation: Enable emergency liquidation on shutdown (DEFAULT: True)
        close_positions: Close all open positions during liquidation (DEFAULT: True)
        cancel_orders: Cancel all pending orders during liquidation (DEFAULT: True)
        timeout_seconds: Maximum time allowed for liquidation operations (DEFAULT: 5.0)
        max_retries: Maximum retry attempts for failed operations (DEFAULT: 3)
        retry_delay_seconds: Delay between retry attempts (DEFAULT: 0.5)

    Validation Rules:
        - timeout_seconds: 1.0 - 30.0 seconds (minimum 1s, maximum 30s)
        - max_retries: 0 - 10 (0 = no retries, 10 = maximum)
        - retry_delay_seconds: 0.1 - 5.0 seconds
        - close_positions=False requires explicit acknowledgment (not auto-allowed)
        - cancel_orders should always be True (orders without positions are orphans)

    Security Warnings:
        - CRITICAL log when emergency_liquidation=False (capital at risk)
        - WARNING when close_positions=False (positions remain exposed)
        - WARNING when cancel_orders=False (orphaned orders)
    """

    # Security-first defaults: Protect capital by default
    emergency_liquidation: bool = True  # DEFAULT: True (capital protection)
    close_positions: bool = True        # DEFAULT: True (close all positions)
    cancel_orders: bool = True          # DEFAULT: True (cancel all orders)

    # Performance and reliability defaults
    timeout_seconds: float = 5.0        # DEFAULT: 5 seconds (balance speed vs reliability)
    max_retries: int = 3                # DEFAULT: 3 retries (balance reliability vs time)
    retry_delay_seconds: float = 0.5   # DEFAULT: 0.5 seconds (exponential backoff base)

    def __post_init__(self) -> None:
        """
        Validate configuration on creation.

        Validation Strategy:
        1. Type validation (runtime type checking)
        2. Range validation (business rules enforcement)
        3. Consistency validation (cross-field logic)
        4. Security validation (capital protection warnings)

        Raises:
            ConfigurationError: If any validation fails
        """
        # 1. Type Validation
        self._validate_types()

        # 2. Range Validation
        self._validate_ranges()

        # 3. Consistency Validation
        self._validate_consistency()

        # 4. Security Validation (warnings for risky configurations)
        self._validate_security()

    def _validate_types(self) -> None:
        """Validate field types at runtime."""
        if not isinstance(self.emergency_liquidation, bool):
            raise ConfigurationError(
                f"emergency_liquidation must be bool, got {type(self.emergency_liquidation).__name__}"
            )

        if not isinstance(self.close_positions, bool):
            raise ConfigurationError(
                f"close_positions must be bool, got {type(self.close_positions).__name__}"
            )

        if not isinstance(self.cancel_orders, bool):
            raise ConfigurationError(
                f"cancel_orders must be bool, got {type(self.cancel_orders).__name__}"
            )

        if not isinstance(self.timeout_seconds, (int, float)):
            raise ConfigurationError(
                f"timeout_seconds must be numeric, got {type(self.timeout_seconds).__name__}"
            )

        if not isinstance(self.max_retries, int):
            raise ConfigurationError(
                f"max_retries must be int, got {type(self.max_retries).__name__}"
            )

        if not isinstance(self.retry_delay_seconds, (int, float)):
            raise ConfigurationError(
                f"retry_delay_seconds must be numeric, got {type(self.retry_delay_seconds).__name__}"
            )

    def _validate_ranges(self) -> None:
        """Validate field value ranges."""
        # Timeout validation: 1-30 seconds
        if self.timeout_seconds < 1.0 or self.timeout_seconds > 30.0:
            raise ConfigurationError(
                f"timeout_seconds must be 1.0-30.0 seconds, got {self.timeout_seconds}"
            )

        # Retry validation: 0-10 retries
        if self.max_retries < 0 or self.max_retries > 10:
            raise ConfigurationError(
                f"max_retries must be 0-10, got {self.max_retries}"
            )

        # Retry delay validation: 0.1-5.0 seconds
        if self.retry_delay_seconds < 0.1 or self.retry_delay_seconds > 5.0:
            raise ConfigurationError(
                f"retry_delay_seconds must be 0.1-5.0 seconds, got {self.retry_delay_seconds}"
            )

    def _validate_consistency(self) -> None:
        """Validate cross-field consistency."""
        # If emergency_liquidation is disabled, both close_positions and cancel_orders must be False
        # (Otherwise it's confusing: "liquidation disabled but positions closed?")
        if not self.emergency_liquidation:
            if self.close_positions or self.cancel_orders:
                raise ConfigurationError(
                    "Inconsistent configuration: emergency_liquidation=False but "
                    f"close_positions={self.close_positions} or cancel_orders={self.cancel_orders}. "
                    "If liquidation is disabled, both should be False."
                )

        # If emergency_liquidation is enabled but close_positions is False, warn (unusual)
        if self.emergency_liquidation and not self.close_positions and self.cancel_orders:
            logger.warning(
                "Unusual configuration: emergency_liquidation=True but close_positions=False. "
                "Orders will be cancelled but positions will remain open. "
                "This is valid for testing but unusual for production."
            )

    def _validate_security(self) -> None:
        """
        Validate security-critical configuration and emit warnings.

        Security Philosophy (Taleb's Paranoia):
        - Default to capital protection
        - Make risky configurations loud and explicit
        - Assume user error, require acknowledgment
        """
        # CRITICAL: Capital protection disabled
        if not self.emergency_liquidation:
            logger.critical(
                "🚨 CAPITAL AT RISK: emergency_liquidation=False 🚨\n"
                "Positions will remain OPEN after shutdown, exposed to market volatility.\n"
                "This configuration is ONLY safe if:\n"
                "  1. You are in a development/testing environment\n"
                "  2. You will manually manage positions before market moves\n"
                "  3. You accept the risk of overnight/weekend exposure\n"
                "\n"
                "For production environments, emergency_liquidation=True is STRONGLY recommended."
            )

        # WARNING: Positions remain open
        if self.emergency_liquidation and not self.close_positions:
            logger.warning(
                "⚠️  POSITIONS WILL REMAIN OPEN: close_positions=False\n"
                "Emergency liquidation will cancel orders but NOT close positions.\n"
                "Positions remain exposed to market risk after shutdown."
            )

        # WARNING: Orders remain active
        if self.emergency_liquidation and not self.cancel_orders:
            logger.warning(
                "⚠️  ORDERS WILL REMAIN ACTIVE: cancel_orders=False\n"
                "Pending orders (TP, SL, limit orders) will remain on the exchange.\n"
                "Orders may fill unexpectedly when bot is offline, creating orphaned positions."
            )

        # INFO: Security-first configuration detected
        if self.emergency_liquidation and self.close_positions and self.cancel_orders:
            logger.info(
                "✅ Security-first configuration: emergency_liquidation=True, "
                "close_positions=True, cancel_orders=True. Capital protection enabled."
            )

    def to_dict(self) -> dict:
        """
        Export configuration as dictionary for serialization.

        Returns:
            dict: Configuration as key-value pairs
        """
        return {
            "emergency_liquidation": self.emergency_liquidation,
            "close_positions": self.close_positions,
            "cancel_orders": self.cancel_orders,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
        }

    @classmethod
    def from_dict(cls, config_dict: dict) -> "LiquidationConfig":
        """
        Create LiquidationConfig from dictionary.

        Args:
            config_dict: Configuration dictionary

        Returns:
            LiquidationConfig: Validated configuration instance

        Raises:
            ConfigurationError: If validation fails
        """
        return cls(
            emergency_liquidation=config_dict.get("emergency_liquidation", True),
            close_positions=config_dict.get("close_positions", True),
            cancel_orders=config_dict.get("cancel_orders", True),
            timeout_seconds=config_dict.get("timeout_seconds", 5.0),
            max_retries=config_dict.get("max_retries", 3),
            retry_delay_seconds=config_dict.get("retry_delay_seconds", 0.5),
        )

    def __repr__(self) -> str:
        """Human-readable representation for debugging."""
        return (
            f"LiquidationConfig("
            f"emergency_liquidation={self.emergency_liquidation}, "
            f"close_positions={self.close_positions}, "
            f"cancel_orders={self.cancel_orders}, "
            f"timeout={self.timeout_seconds}s, "
            f"retries={self.max_retries}, "
            f"retry_delay={self.retry_delay_seconds}s)"
        )
