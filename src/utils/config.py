"""
Configuration management with INI files and environment overrides
"""

import os
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.exceptions import ConfigurationError
from src.execution.liquidation_config import LiquidationConfig


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
class TradingConfig:
    """
    Trading strategy configuration

    Validation Rules:
        - leverage: 1-125 (Binance futures limits)
        - max_risk_per_trade: 0 < value ≤ 0.1 (0-10%)
        - take_profit_ratio: must be positive
        - stop_loss_percent: 0 < value ≤ 0.5 (0-50%)
        - backfill_limit: 0-1000 (0 = no backfilling)
        - symbol: must end with 'USDT'
        - intervals: must be valid Binance interval formats
          (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w)
    """

    symbol: str
    intervals: List[str]
    strategy: str
    leverage: int
    max_risk_per_trade: float
    take_profit_ratio: float
    stop_loss_percent: float
    backfill_limit: int = 100  # Default 100 candles
    margin_type: str = "ISOLATED"  # Default to ISOLATED margin (safer than CROSSED)
    ict_config: Optional[Dict[str, Any]] = None  # ICT strategy specific configuration

    def __post_init__(self):
        # Validation
        if self.leverage < 1 or self.leverage > 125:
            raise ConfigurationError(f"Leverage must be between 1-125, got {self.leverage}")

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
            raise ConfigurationError(f"Backfill limit must be 0-1000, got {self.backfill_limit}")

        # Validate margin_type
        if self.margin_type not in ("ISOLATED", "CROSSED"):
            raise ConfigurationError(
                f"Margin type must be 'ISOLATED' or 'CROSSED', got {self.margin_type}"
            )

        # Validate symbol format
        if not self.symbol or not self.symbol.endswith("USDT"):
            raise ConfigurationError(f"Invalid symbol format: {self.symbol}. Must end with 'USDT'")

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
                    f"Invalid interval: {interval}. " f"Must be one of {sorted(valid_intervals)}"
                )


@dataclass
class LoggingConfig:
    """Logging system configuration"""

    log_level: str = "INFO"
    log_dir: str = "logs"

    def __post_init__(self):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            raise ConfigurationError(
                f"Invalid log level: {self.log_level}. " f"Must be one of {valid_levels}"
            )


class ConfigManager:
    """
    Manages system configuration from INI files with environment overrides
    """

    def __init__(self, config_dir: str = "configs"):
        # Find project root (parent of src directory)
        # This ensures configs/ is found regardless of working directory
        project_root = Path(__file__).parent.parent.parent
        self.config_dir = project_root / config_dir

        self._api_config = None
        self._trading_config = None
        self._logging_config = None
        self._liquidation_config = None

        # Load configurations
        self._load_configs()

    def _load_configs(self):
        """
        Load all configuration files using internal helper methods.
        
        Each loader utilizes ConfigParser to read INI files. After the '.read()' 
        method is called, the instance acts as a structured data container that 
        permits efficient keyed access and automatic type conversion (int, float, bool).
        """
        self._api_config = self._load_api_config()
        self._trading_config = self._load_trading_config()
        self._logging_config = self._load_logging_config()
        self._liquidation_config = self._load_liquidation_config()

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
            return APIConfig(api_key=api_key_env, api_secret=api_secret_env, is_testnet=is_testnet)

        # Load from INI file with environment-specific sections
        config_file = self.config_dir / "api_keys.ini"
        if not config_file.exists():
            raise ConfigurationError(
                f"API configuration not found. Either:\n"
                f"1. Set BINANCE_API_KEY, BINANCE_API_SECRET environment variables, or\n"
                f"2. Create {config_file} from api_keys.ini.example"
            )

        config = ConfigParser()
        config.read(config_file)

        if "binance" not in config:
            raise ConfigurationError("Invalid api_keys.ini: [binance] section not found")

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
            raise ConfigurationError("Invalid trading_config.ini: [trading] section not found")

        trading = config["trading"]

        # Load ICT strategy specific configuration if available
        ict_config = None
        if "ict_strategy" in config:
            ict_section = config["ict_strategy"]
            ict_config = {
                "buffer_size": ict_section.getint("buffer_size", 200),
                "swing_lookback": ict_section.getint("swing_lookback", 5),
                "displacement_ratio": ict_section.getfloat("displacement_ratio", 1.5),
                "fvg_min_gap_percent": ict_section.getfloat("fvg_min_gap_percent", 0.001),
                "ob_min_strength": ict_section.getfloat("ob_min_strength", 1.5),
                "liquidity_tolerance": ict_section.getfloat("liquidity_tolerance", 0.001),
                "rr_ratio": ict_section.getfloat("rr_ratio", 2.0),
                "use_killzones": ict_section.getboolean("use_killzones", True),
            }

        return TradingConfig(
            symbol=trading.get("symbol", "BTCUSDT"),
            intervals=trading.get("intervals", "1m,5m,15m").split(","),
            strategy=trading.get("strategy", "MockStrategy"),
            leverage=trading.getint("leverage", 1),
            max_risk_per_trade=trading.getfloat("max_risk_per_trade", 0.01),
            take_profit_ratio=trading.getfloat("take_profit_ratio", 2.0),
            stop_loss_percent=trading.getfloat("stop_loss_percent", 0.02),
            backfill_limit=trading.getint("backfill_limit", 100),
            margin_type=trading.get("margin_type", "ISOLATED"),
            ict_config=ict_config,
        )

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
            logger.warning(f"Using {self._trading_config.leverage}x leverage in testnet mode")

        # Log environment mode
        if self._api_config.is_testnet:
            logger.info("⚠️  Running in TESTNET mode")
        else:
            logger.warning("⚠️  Running in PRODUCTION mode with real funds!")

        # Log all accumulated errors
        for error in errors:
            logger.error(error)

        return len(errors) == 0

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
        )

    @property
    def logging_config(self) -> LoggingConfig:
        """Get logging configuration"""
        return self._logging_config

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
            emergency_liquidation=liquidation_section.getboolean("emergency_liquidation", True),
            close_positions=liquidation_section.getboolean("close_positions", True),
            cancel_orders=liquidation_section.getboolean("cancel_orders", True),
            timeout_seconds=liquidation_section.getfloat("timeout_seconds", 5.0),
            max_retries=liquidation_section.getint("max_retries", 3),
            retry_delay_seconds=liquidation_section.getfloat("retry_delay_seconds", 0.5),
        )

    @property
    def liquidation_config(self) -> LiquidationConfig:
        """Get liquidation configuration"""
        return self._liquidation_config
