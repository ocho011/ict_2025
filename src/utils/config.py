"""
Configuration management with INI files and environment overrides
"""

import os
from dataclasses import dataclass
from pathlib import Path
from configparser import ConfigParser
from typing import List
from src.core.exceptions import ConfigurationError


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
    """Trading strategy configuration"""
    symbol: str
    intervals: List[str]
    strategy: str
    leverage: int
    max_risk_per_trade: float
    take_profit_ratio: float
    stop_loss_percent: float

    def __post_init__(self):
        # Validation
        if self.leverage < 1 or self.leverage > 125:
            raise ConfigurationError(f"Leverage must be between 1-125, got {self.leverage}")

        if self.max_risk_per_trade <= 0 or self.max_risk_per_trade > 0.1:
            raise ConfigurationError(
                f"Max risk per trade must be 0-10%, got {self.max_risk_per_trade}"
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
                f"Invalid log level: {self.log_level}. "
                f"Must be one of {valid_levels}"
            )


class ConfigManager:
    """
    Manages system configuration from INI files with environment overrides
    """

    def __init__(self, config_dir: str = "configs"):
        self.config_dir = Path(config_dir)
        self._api_config = None
        self._trading_config = None
        self._logging_config = None

        # Load configurations
        self._load_configs()

    def _load_configs(self):
        """Load all configuration files"""
        self._api_config = self._load_api_config()
        self._trading_config = self._load_trading_config()
        self._logging_config = self._load_logging_config()

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
                api_key=api_key_env,
                api_secret=api_secret_env,
                is_testnet=is_testnet
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

        return APIConfig(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=is_testnet
        )

    def _load_trading_config(self) -> TradingConfig:
        """Load trading configuration from INI file"""
        config_file = self.config_dir / "trading_config.ini"

        if not config_file.exists():
            raise ConfigurationError(
                f"Trading configuration not found: {config_file}"
            )

        config = ConfigParser()
        config.read(config_file)

        if "trading" not in config:
            raise ConfigurationError("Invalid trading_config.ini: [trading] section not found")

        trading = config["trading"]

        return TradingConfig(
            symbol=trading.get("symbol", "BTCUSDT"),
            intervals=trading.get("intervals", "1m,5m,15m").split(","),
            strategy=trading.get("strategy", "MockStrategy"),
            leverage=trading.getint("leverage", 1),
            max_risk_per_trade=trading.getfloat("max_risk_per_trade", 0.01),
            take_profit_ratio=trading.getfloat("take_profit_ratio", 2.0),
            stop_loss_percent=trading.getfloat("stop_loss_percent", 0.02)
        )

    def validate(self) -> None:
        """
        Validate all configurations

        Raises:
            ConfigurationError: If any validation fails
        """
        # API config validation happens in __post_init__
        # Trading config validation happens in __post_init__

        # Additional cross-config validation
        if self._api_config.is_testnet:
            print("⚠️  WARNING: Running in TESTNET mode")
        else:
            print("⚠️  WARNING: Running in PRODUCTION mode with real funds!")

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
            log_dir=logging_section.get("log_dir", "logs")
        )

    @property
    def logging_config(self) -> LoggingConfig:
        """Get logging configuration"""
        return self._logging_config
