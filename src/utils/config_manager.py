"""
Configuration management with INI files and environment overrides

Supports both legacy INI format and new hierarchical YAML format (Issue #18).
"""

import logging
import os
from configparser import ConfigParser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import yaml

from src.core.exceptions import ConfigurationError

# Imports for type hinting only; prevents circular dependency at runtime
# Only imported during static analysis (e.g., mypy, IDE)
if TYPE_CHECKING:
    from src.config.symbol_config import TradingConfigHierarchical


@dataclass
class BinanceConfig:
    """
    Binance endpoint configuration (Issue #92).

    Centralizes all Binance REST and WebSocket URLs for flexibility:
    - Proxy support (custom endpoint URLs)
    - Easy adaptation to Binance endpoint changes
    - Environment-specific URL selection (testnet/mainnet)

    Attributes:
        rest_testnet_url: REST API base URL for testnet
        rest_mainnet_url: REST API base URL for mainnet
        ws_testnet_url: Market data WebSocket URL for testnet
        ws_mainnet_url: Market data WebSocket URL for mainnet
        user_ws_testnet_url: User data WebSocket URL for testnet
        user_ws_mainnet_url: User data WebSocket URL for mainnet
    """

    # REST API endpoints
    rest_testnet_url: str = "https://testnet.binancefuture.com"
    rest_mainnet_url: str = "https://fapi.binance.com"

    # Market data WebSocket endpoints (public streams)
    ws_testnet_url: str = "wss://stream.binancefuture.com"
    ws_mainnet_url: str = "wss://fstream.binance.com"

    # User data WebSocket endpoints (private streams)
    user_ws_testnet_url: str = "wss://stream.binancefuture.com/ws"
    user_ws_mainnet_url: str = "wss://fstream.binance.com/ws"

    def get_rest_url(self, is_testnet: bool) -> str:
        """Get REST API URL based on environment."""
        return self.rest_testnet_url if is_testnet else self.rest_mainnet_url

    def get_ws_url(self, is_testnet: bool) -> str:
        """Get market data WebSocket URL based on environment."""
        return self.ws_testnet_url if is_testnet else self.ws_mainnet_url

    def get_user_ws_url(self, is_testnet: bool) -> str:
        """Get user data WebSocket URL based on environment."""
        return self.user_ws_testnet_url if is_testnet else self.user_ws_mainnet_url


@dataclass
class APIConfig:
    """Binance API configuration"""

    api_key: str
    api_secret: str
    is_testnet: bool = True

    def __post_init__(self):
        # Security: Never log API keys
        if not self.api_key or not self.api_secret:
            raise ConfigurationError("API key and secret are required")


@dataclass
class ExitConfig:
    """
    Dynamic exit strategy configuration for Issue #43 Phase 1.

    Supports multiple exit strategies beyond basic TP/SL for improved risk management
    and profit protection in ICT trading strategies.

    Validation Rules:
        - exit_strategy: must be one of supported strategies
        - trailing_distance: 0.001 - 0.1 (0.1% - 10%)
        - trailing_activation: 0.001 - 0.05 (0.1% - 5%)
        - breakeven_offset: 0.0001 - 0.01 (0.01% - 1%)
        - timeout_minutes: 1 - 1440 (1 minute - 24 hours)
        - atr_period: 5 - 100 (ATR calculation period)
        - atr_multiplier: 0.5 - 5.0 (ATR multiplier for stops)
    """

    # Dynamic exit enablement
    dynamic_exit_enabled: bool = True

    # Exit strategy selection
    exit_strategy: str = (
        "trailing_stop"  # trailing_stop, breakeven, timed, indicator_based
    )

    # Trailing stop parameters
    trailing_distance: float = 0.02  # 2% default
    trailing_activation: float = 0.01  # 1% profit to activate

    # BreakEven parameters
    breakeven_enabled: bool = True
    breakeven_offset: float = 0.001  # 0.1% offset

    # Time-based exit
    timeout_enabled: bool = False
    timeout_minutes: int = 240  # 4 hours default

    # Volatility-based
    volatility_enabled: bool = False
    atr_period: int = 14
    atr_multiplier: float = 2.0

    def __post_init__(self):
        """Validate exit configuration parameters."""
        # Validate exit strategy
        valid_strategies = {"trailing_stop", "breakeven", "timed", "indicator_based"}
        if self.exit_strategy not in valid_strategies:
            raise ConfigurationError(
                f"Invalid exit strategy: {self.exit_strategy}. "
                f"Must be one of {sorted(valid_strategies)}"
            )

        # Validate trailing stop parameters
        if self.trailing_distance < 0.001 or self.trailing_distance > 0.1:
            raise ConfigurationError(
                f"trailing_distance must be 0.001-0.1 (0.1%-10%), got {self.trailing_distance}"
            )

        if self.trailing_activation < 0.001 or self.trailing_activation > 0.05:
            raise ConfigurationError(
                f"trailing_activation must be 0.001-0.05 (0.1%-5%), got {self.trailing_activation}"
            )

        # Validate breakeven parameters
        if self.breakeven_offset < 0.0001 or self.breakeven_offset > 0.01:
            raise ConfigurationError(
                f"breakeven_offset must be 0.0001-0.01 (0.01%-1%), got {self.breakeven_offset}"
            )

        # Validate timeout parameters
        if self.timeout_minutes < 1 or self.timeout_minutes > 1440:
            raise ConfigurationError(
                f"timeout_minutes must be 1-1440 (1min-24h), got {self.timeout_minutes}"
            )

        # Validate ATR parameters
        if self.atr_period < 5 or self.atr_period > 100:
            raise ConfigurationError(f"atr_period must be 5-100, got {self.atr_period}")

        if self.atr_multiplier < 0.5 or self.atr_multiplier > 5.0:
            raise ConfigurationError(
                f"atr_multiplier must be 0.5-5.0, got {self.atr_multiplier}"
            )

        # Validate strategy consistency
        if self.exit_strategy == "trailing_stop" and self.trailing_distance <= 0:
            raise ConfigurationError(
                "trailing_stop strategy requires trailing_distance > 0"
            )

        if self.exit_strategy == "timed" and not self.timeout_enabled:
            raise ConfigurationError("timed strategy requires timeout_enabled=True")


@dataclass
class TradingConfig:
    """
    Trading strategy configuration

    Validation Rules:
        - leverage: 1-125 (Binance futures limits)
        - max_risk_per_trade: 0 < value ≤ 0.1 (0-10%)
        - take_profit_ratio: must be positive
        - stop_loss_percent: 0 < value ≤ 0.5 (0-50%)
        - backfill_limit: 0-1000 (0 = no backfilling)
        - symbols: each must end with 'USDT', max 10 symbols (Issue #8)
        - intervals: must be valid Binance interval formats
          (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w)
    """

    symbols: List[str]  # Multi-coin support (Issue #8)
    intervals: List[str]
    strategy: str
    leverage: int
    max_risk_per_trade: float
    take_profit_ratio: float
    stop_loss_percent: float
    backfill_limit: int = 100  # Default 100 candles
    margin_type: str = "ISOLATED"  # Default to ISOLATED margin (safer than CROSSED)
    strategy_config: Dict[str, Any] = field(default_factory=dict)  # Strategy-specific configuration
    exit_config: Optional[ExitConfig] = None  # Dynamic exit configuration (Issue #43)
    max_symbols: int = (
        10  # Maximum symbols allowed (Issue #69: configurable MAX_SYMBOLS)
    )
    strategy_type: str = "composable"  # "composable" | "monolithic"

    def __post_init__(self):
        # Validation
        if self.leverage < 1 or self.leverage > 125:
            raise ConfigurationError(
                f"Leverage must be between 1-125, got {self.leverage}"
            )

        if self.max_risk_per_trade <= 0 or self.max_risk_per_trade > 0.1:
            raise ConfigurationError(
                f"Max risk per trade must be 0-10%, got {self.max_risk_per_trade}"
            )

        # Validate take_profit_ratio
        if self.take_profit_ratio <= 0:
            raise ConfigurationError(
                f"Take profit ratio must be positive, got {self.take_profit_ratio}"
            )

        # Validate stop_loss_percent
        if self.stop_loss_percent <= 0 or self.stop_loss_percent > 0.5:
            raise ConfigurationError(
                f"Stop loss percent must be 0-50%, got {self.stop_loss_percent}"
            )

        # Validate backfill_limit
        if self.backfill_limit < 0 or self.backfill_limit > 1000:
            raise ConfigurationError(
                f"Backfill limit must be 0-1000, got {self.backfill_limit}"
            )

        # Validate margin_type
        if self.margin_type not in ("ISOLATED", "CROSSED"):
            raise ConfigurationError(
                f"Margin type must be 'ISOLATED' or 'CROSSED', got {self.margin_type}"
            )

        # Validate symbols (Issue #8: Multi-coin support)

        if len(self.symbols) == 0:
            raise ConfigurationError("At least one symbol is required")
        if len(self.symbols) > self.max_symbols:
            raise ConfigurationError(
                f"Maximum {self.max_symbols} symbols allowed, got {len(self.symbols)}"
            )

        # Validate each symbol format
        for symbol in self.symbols:
            if not symbol or not symbol.endswith("USDT"):
                raise ConfigurationError(
                    f"Invalid symbol format: {symbol}. Must end with 'USDT'"
                )

        # Validate intervals
        valid_intervals = {
            "1m",
            "3m",
            "5m",
            "15m",
            "30m",
            "1h",
            "2h",
            "4h",
            "6h",
            "8h",
            "12h",
            "1d",
            "3d",
            "1w",
        }
        for interval in self.intervals:
            if interval not in valid_intervals:
                raise ConfigurationError(
                    f"Invalid interval: {interval}. "
                    f"Must be one of {sorted(valid_intervals)}"
                )

        # Validate strategy_type
        if self.strategy_type not in ("composable", "monolithic"):
            raise ConfigurationError(
                f"strategy_type must be 'composable' or 'monolithic', got {self.strategy_type}"
            )


@dataclass
class LoggingConfig:
    """Logging system configuration"""

    log_level: str = "INFO"
    log_dir: str = "logs"
    log_live_data: bool = True  # Analysis mode: set False to disable live data logs

    def __post_init__(self):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            raise ConfigurationError(
                f"Invalid log level: {self.log_level}. Must be one of {valid_levels}"
            )


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
    close_positions: bool = True  # DEFAULT: True (close all positions)
    cancel_orders: bool = True  # DEFAULT: True (cancel all orders)

    # Performance and reliability defaults
    timeout_seconds: float = 5.0  # DEFAULT: 5 seconds (balance speed vs reliability)
    max_retries: int = 3  # DEFAULT: 3 retries (balance reliability vs time)
    retry_delay_seconds: float = 0.5  # DEFAULT: 0.5 seconds (exponential backoff base)

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
        if (
            self.emergency_liquidation
            and not self.close_positions
            and self.cancel_orders
        ):
            logger = logging.getLogger(__name__)
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
        logger = logging.getLogger(__name__)

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


class ConfigManager:
    """
    Manages system configuration from INI files with environment overrides
    """

    # --- Initialization ---

    def __init__(self, config_dir: str = "configs"):
        # Find project root (parent of src directory)
        # This ensures configs/ is found regardless of working directory
        project_root = Path(__file__).parent.parent.parent
        self.config_dir = project_root / config_dir

        self._api_config = None
        self._trading_config = None
        self._logging_config = None
        self._liquidation_config = None
        self._binance_config = None
        self._hierarchical_config: Optional["TradingConfigHierarchical"] = None

        # Load configurations
        self._load_configs()

    def _load_configs(self):
        """
        Load all configuration files using internal helper methods.

        Each loader utilizes ConfigParser to read INI files. After the '.read()'
        method is called, the instance acts as a structured data container that
        permits efficient keyed access and automatic type conversion (int, float, bool).

        For trading configuration, YAML format is preferred (Issue #18):
        - trading_config.yaml: New hierarchical per-symbol format
        - trading_config.ini: Legacy flat format (fallback)
        """
        self._api_config = self._load_api_config()
        self._binance_config = self._load_binance_config()
        self._hierarchical_config = self._load_hierarchical_config()
        self._trading_config = self._load_trading_config()
        self._logging_config = self._load_logging_config()
        self._liquidation_config = self._load_liquidation_config()

    # --- Public Properties ---

    @property
    def is_testnet(self) -> bool:
        """Check if running in testnet mode"""
        return self._api_config.is_testnet

    @property
    def api_config(self) -> APIConfig:
        """Get API configuration"""
        return self._api_config

    @property
    def trading_config(self) -> TradingConfig:
        """Get trading configuration"""
        return self._trading_config

    @property
    def hierarchical_config(self) -> Optional["TradingConfigHierarchical"]:
        """
        Get hierarchical per-symbol configuration (Issue #18).

        Returns:
            TradingConfigHierarchical if YAML config loaded, None otherwise
        """
        return self._hierarchical_config

    @property
    def has_hierarchical_config(self) -> bool:
        """Check if hierarchical per-symbol configuration is available."""
        return self._hierarchical_config is not None

    @property
    def logging_config(self) -> LoggingConfig:
        """Get logging configuration"""
        return self._logging_config

    @property
    def liquidation_config(self) -> LiquidationConfig:
        """Get liquidation configuration"""
        return self._liquidation_config

    @property
    def binance_config(self) -> BinanceConfig:
        """Get Binance endpoint configuration (Issue #92)"""
        return self._binance_config

    # --- Public Methods ---

    def validate(self) -> bool:
        """
        Validate all configurations

        Returns:
            bool: True if all validations pass, False otherwise

        Note:
            - API and Trading config validation happens in __post_init__
            - All validation errors are logged before returning
            - This method performs additional cross-config validation
        """
        import logging

        logger = logging.getLogger(__name__)
        errors = []

        # API config validation (already done in __post_init__)
        # Trading config validation (already done in __post_init__)

        # Cross-config validation: leverage warning in testnet
        if self._trading_config.leverage > 1 and self._api_config.is_testnet:
            logger.warning(
                f"Using {self._trading_config.leverage}x leverage in testnet mode"
            )

        # Log environment mode
        if self._api_config.is_testnet:
            logger.info("⚠️  Running in TESTNET mode")
        else:
            logger.warning("⚠️  Running in PRODUCTION mode with real funds!")

        # Log all accumulated errors
        for error in errors:
            logger.error(error)

        return len(errors) == 0

    # --- Private Loaders (Helpers) ---

    def _load_api_config(self) -> APIConfig:
        """
        Load API configuration with environment variable overrides
        Automatically selects testnet or mainnet credentials based on use_testnet flag

        Priority: ENV > INI file (environment-specific)
        """
        # Check if testnet mode is set via environment (highest priority)
        is_testnet_env = os.getenv("BINANCE_USE_TESTNET")

        # Environment variables for direct credential override
        api_key_env = os.getenv("BINANCE_API_KEY")
        api_secret_env = os.getenv("BINANCE_API_SECRET")

        # If environment variables provide complete configuration, use them
        if api_key_env and api_secret_env:
            is_testnet = is_testnet_env.lower() == "true" if is_testnet_env else True
            return APIConfig(
                api_key=api_key_env, api_secret=api_secret_env, is_testnet=is_testnet
            )

        # Load from INI file with environment-specific sections
        config_file = self.config_dir / "api_keys.ini"
        if not config_file.exists():
            raise ConfigurationError(
                f"API configuration not found. Either:\n"
                f"1. Set BINANCE_API_KEY, BINANCE_API_SECRET environment variables, or\n"
                f"2. Create {config_file} from api_keys.ini.example"
            )

        config = ConfigParser()
        # NOTE: .read() does NOT return a new object; it updates the internal state of the config instance.
        config.read(config_file)

        if "binance" not in config:
            raise ConfigurationError(
                "Invalid api_keys.ini: [binance] section not found"
            )

        # Determine which environment to use
        is_testnet = config["binance"].getboolean("use_testnet", True)

        # Override from environment variable if set
        if is_testnet_env is not None:
            is_testnet = is_testnet_env.lower() == "true"

        # Select appropriate credentials section
        env_section = "binance.testnet" if is_testnet else "binance.mainnet"

        if env_section not in config:
            raise ConfigurationError(
                f"Invalid api_keys.ini: [{env_section}] section not found. "
                f"Please update your config file using api_keys.ini.example as reference."
            )

        api_key = config[env_section].get("api_key")
        api_secret = config[env_section].get("api_secret")

        # Validate credentials are not placeholder values
        if not api_key or api_key.startswith("your_"):
            raise ConfigurationError(
                f"Invalid API key in [{env_section}]. Please set your actual credentials."
            )

        if not api_secret or api_secret.startswith("your_"):
            raise ConfigurationError(
                f"Invalid API secret in [{env_section}]. Please set your actual credentials."
            )

        return APIConfig(api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)

    def _load_trading_config(self) -> TradingConfig:
        """Load trading configuration from INI file"""
        config_file = self.config_dir / "trading_config.ini"

        if not config_file.exists():
            raise ConfigurationError(f"Trading configuration not found: {config_file}")

        config = ConfigParser()
        config.read(config_file)

        if "trading" not in config:
            raise ConfigurationError(
                "Invalid trading_config.ini: [trading] section not found"
            )

        trading = config["trading"]

        # Load strategy-specific configuration if available
        strategy_config = {}
        strategy_name = trading.get("strategy", "MockStrategy")
        if strategy_name in config:
            strat_section = config[strategy_name]
            for key in strat_section:
                raw_val = strat_section.get(key)
                if raw_val is None:
                    continue
                # Try boolean
                if raw_val.lower() in ('true', 'false'):
                    strategy_config[key] = strat_section.getboolean(key)
                else:
                    # Try int, then float, then keep as string
                    try:
                        strategy_config[key] = strat_section.getint(key)
                    except ValueError:
                        try:
                            strategy_config[key] = strat_section.getfloat(key)
                        except ValueError:
                            strategy_config[key] = raw_val

        # Load dynamic exit configuration if available (Issue #43)
        exit_config = None
        if "exit_config" in config:
            exit_section = config["exit_config"]
            exit_config = ExitConfig(
                dynamic_exit_enabled=exit_section.getboolean(
                    "dynamic_exit_enabled", True
                ),
                exit_strategy=exit_section.get("exit_strategy", "trailing_stop"),
                trailing_distance=exit_section.getfloat("trailing_distance", 0.02),
                trailing_activation=exit_section.getfloat("trailing_activation", 0.01),
                breakeven_enabled=exit_section.getboolean("breakeven_enabled", True),
                breakeven_offset=exit_section.getfloat("breakeven_offset", 0.001),
                timeout_enabled=exit_section.getboolean("timeout_enabled", False),
                timeout_minutes=exit_section.getint("timeout_minutes", 240),
                volatility_enabled=exit_section.getboolean("volatility_enabled", False),
                atr_period=exit_section.getint("atr_period", 14),
                atr_multiplier=exit_section.getfloat("atr_multiplier", 2.0),
            )

        # Parse symbols with backward compatibility (Issue #8)
        # Priority: symbols (new) > symbol (legacy)
        symbols_str = trading.get("symbols", trading.get("symbol", "BTCUSDT"))
        symbols = [s.strip() for s in symbols_str.split(",")]

        # Validate max_symbols range (Issue #69)
        max_symbols_value = trading.getint("max_symbols", 10)
        if not (1 <= max_symbols_value <= 20):
            raise ConfigurationError(
                f"max_symbols must be between 1-20, got {max_symbols_value}"
            )

        # Add resource warning for high symbol counts (>=15)
        if max_symbols_value >= 15:
            logger = logging.getLogger(__name__)
            logger.warning(
                f"⚠️  HIGH RESOURCE USAGE: {max_symbols_value} symbols configured. "
                f"Memory usage: ~{max_symbols_value * 5}MB per symbol per interval. "
                f"Consider reducing for better performance."
            )

        return TradingConfig(
            symbols=symbols,
            intervals=[
                i.strip() for i in trading.get("intervals", "1m,5m,15m").split(",")
            ],
            strategy=trading.get("strategy", "MockStrategy"),
            leverage=trading.getint("leverage", 1),
            max_risk_per_trade=trading.getfloat("max_risk_per_trade", 0.01),
            take_profit_ratio=trading.getfloat("take_profit_ratio", 2.0),
            stop_loss_percent=trading.getfloat("stop_loss_percent", 0.02),
            backfill_limit=trading.getint("backfill_limit", 100),
            margin_type=trading.get("margin_type", "ISOLATED"),
            strategy_config=strategy_config,
            exit_config=exit_config,
            max_symbols=max_symbols_value,
            strategy_type=trading.get("strategy_type", "composable"),
        )

    def _load_hierarchical_config(self) -> Optional["TradingConfigHierarchical"]:
        """
        Load hierarchical per-symbol configuration from YAML file (Issue #18).

        Supports the new trading_config.yaml format with per-symbol overrides.
        Returns None if YAML file doesn't exist (falls back to INI format).

        Returns:
            TradingConfigHierarchical if YAML exists, None otherwise
        """
        yaml_file = self.config_dir / "trading_config.yaml"

        if not yaml_file.exists():
            return None

        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "trading" not in data:
                logging.getLogger(__name__).warning(
                    f"YAML config {yaml_file} missing 'trading' section, using INI fallback"
                )
                return None

            # Import here to avoid circular dependency
            from src.config.symbol_config import TradingConfigHierarchical

            trading_data = data["trading"]
            return TradingConfigHierarchical.from_dict(trading_data)

        except yaml.YAMLError as e:
            logging.getLogger(__name__).error(f"Failed to parse YAML config: {e}")
            return None
        except Exception as e:
            logging.getLogger(__name__).error(
                f"Failed to load hierarchical config: {e}"
            )
            return None

    def _load_logging_config(self) -> LoggingConfig:
        """Load logging configuration from INI file"""
        config_file = self.config_dir / "trading_config.ini"

        if not config_file.exists():
            return LoggingConfig()  # Use defaults

        config = ConfigParser()
        config.read(config_file)

        if "logging" not in config:
            return LoggingConfig()  # Use defaults

        logging_section = config["logging"]

        return LoggingConfig(
            log_level=logging_section.get("log_level", "INFO"),
            log_dir=logging_section.get("log_dir", "logs"),
            log_live_data=logging_section.getboolean("log_live_data", True),
        )

    def _load_liquidation_config(self) -> LiquidationConfig:
        """
        Load liquidation configuration from INI file.

        Configuration Section: [liquidation]
        Default Values: Security-first defaults (emergency_liquidation=True)

        Returns:
            LiquidationConfig: Validated liquidation configuration
        """
        config_file = self.config_dir / "trading_config.ini"

        if not config_file.exists():
            # If config file doesn't exist, use security-first defaults
            return LiquidationConfig()

        config = ConfigParser()
        config.read(config_file)

        if "liquidation" not in config:
            # If [liquidation] section doesn't exist, use security-first defaults
            return LiquidationConfig()

        liquidation_section = config["liquidation"]

        return LiquidationConfig(
            emergency_liquidation=liquidation_section.getboolean(
                "emergency_liquidation", True
            ),
            close_positions=liquidation_section.getboolean("close_positions", True),
            cancel_orders=liquidation_section.getboolean("cancel_orders", True),
            timeout_seconds=liquidation_section.getfloat("timeout_seconds", 5.0),
            max_retries=liquidation_section.getint("max_retries", 3),
            retry_delay_seconds=liquidation_section.getfloat(
                "retry_delay_seconds", 0.5
            ),
        )

    def _load_binance_config(self) -> BinanceConfig:
        """
        Load Binance endpoint configuration from INI file (Issue #92).

        Configuration Section: [binance]
        Default Values: Official Binance endpoints

        Returns:
            BinanceConfig: Validated Binance endpoint configuration
        """
        config_file = self.config_dir / "trading_config.ini"

        if not config_file.exists():
            # If config file doesn't exist, use default endpoints
            return BinanceConfig()

        config = ConfigParser()
        config.read(config_file)

        if "binance" not in config:
            # If [binance] section doesn't exist, use default endpoints
            return BinanceConfig()

        binance_section = config["binance"]

        return BinanceConfig(
            rest_testnet_url=binance_section.get(
                "rest_testnet_url", "https://testnet.binancefuture.com"
            ),
            rest_mainnet_url=binance_section.get(
                "rest_mainnet_url", "https://fapi.binance.com"
            ),
            ws_testnet_url=binance_section.get(
                "ws_testnet_url", "wss://stream.binancefuture.com"
            ),
            ws_mainnet_url=binance_section.get(
                "ws_mainnet_url", "wss://fstream.binance.com"
            ),
            user_ws_testnet_url=binance_section.get(
                "user_ws_testnet_url", "wss://stream.binancefuture.com/ws"
            ),
            user_ws_mainnet_url=binance_section.get(
                "user_ws_mainnet_url", "wss://fstream.binance.com/ws"
            ),
        )
