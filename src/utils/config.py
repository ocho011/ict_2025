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


class ConfigManager:
    """
    Manages system configuration from INI files with environment overrides
    """

    def __init__(self, config_dir: str = "configs"):
        self.config_dir = Path(config_dir)
        self._api_config = None
        self._trading_config = None

        # Load configurations
        self._load_configs()

    def _load_configs(self):
        """Load all configuration files"""
        self._api_config = self._load_api_config()
        self._trading_config = self._load_trading_config()

    def _load_api_config(self) -> APIConfig:
        """
        Load API configuration with environment variable overrides

        Priority: ENV > INI file
        """
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")
        is_testnet = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

        # If not in env, try loading from INI (not recommended for production)
        if not api_key or not api_secret:
            config_file = self.config_dir / "api_keys.ini"
            if not config_file.exists():
                raise ConfigurationError(
                    f"API configuration not found. Set BINANCE_API_KEY and BINANCE_API_SECRET "
                    f"environment variables, or create {config_file}"
                )

            config = ConfigParser()
            config.read(config_file)

            if "binance" not in config:
                raise ConfigurationError("Invalid api_keys.ini: [binance] section not found")

            api_key = config["binance"].get("api_key")
            api_secret = config["binance"].get("api_secret")
            is_testnet = config["binance"].getboolean("testnet", True)

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
