"""
Comprehensive validation tests for configuration management

Tests all validation rules for APIConfig, TradingConfig, and ConfigManager
"""

import pytest
from pathlib import Path
from src.utils.config import APIConfig, TradingConfig, LoggingConfig, ConfigManager
from src.core.exceptions import ConfigurationError


class TestAPIConfigValidation:
    """Test APIConfig validation rules"""

    def test_valid_api_config(self):
        """Valid configuration should not raise"""
        config = APIConfig(
            api_key="test_key_12345678",
            api_secret="test_secret_12345678",
            is_testnet=True,
        )
        assert config.api_key == "test_key_12345678"
        assert config.api_secret == "test_secret_12345678"
        assert config.is_testnet is True

    def test_empty_api_key_raises(self):
        """Empty API key should raise ConfigurationError"""
        with pytest.raises(ConfigurationError, match="API key and secret are required"):
            APIConfig(api_key="", api_secret="test_secret")

    def test_empty_api_secret_raises(self):
        """Empty API secret should raise ConfigurationError"""
        with pytest.raises(ConfigurationError, match="API key and secret are required"):
            APIConfig(api_key="test_key", api_secret="")

    def test_both_empty_raises(self):
        """Both empty should raise ConfigurationError"""
        with pytest.raises(ConfigurationError, match="API key and secret are required"):
            APIConfig(api_key="", api_secret="")

    def test_default_testnet_flag(self):
        """Default testnet flag should be True"""
        config = APIConfig(api_key="test_key", api_secret="test_secret")
        assert config.is_testnet is True

    def test_mainnet_mode(self):
        """Mainnet mode should be settable"""
        config = APIConfig(
            api_key="test_key", api_secret="test_secret", is_testnet=False
        )
        assert config.is_testnet is False


class TestTradingConfigValidation:
    """Test TradingConfig validation rules"""

    def test_valid_trading_config(self):
        """Valid configuration should not raise"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m", "5m"],
            strategy="MockStrategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.leverage == 10
        assert config.symbol == "BTCUSDT"
        assert len(config.intervals) == 2

    # Leverage validation tests
    def test_leverage_minimum_valid(self):
        """Leverage of 1 should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.leverage == 1

    def test_leverage_maximum_valid(self):
        """Leverage of 125 should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=125,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.leverage == 125

    def test_leverage_too_low_raises(self):
        """Leverage < 1 should raise"""
        with pytest.raises(ConfigurationError, match="Leverage must be between 1-125"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=0,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_leverage_negative_raises(self):
        """Negative leverage should raise"""
        with pytest.raises(ConfigurationError, match="Leverage must be between 1-125"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=-5,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_leverage_too_high_raises(self):
        """Leverage > 125 should raise"""
        with pytest.raises(ConfigurationError, match="Leverage must be between 1-125"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=126,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    # Risk per trade validation tests
    def test_risk_minimum_valid(self):
        """Minimum valid risk (just above 0) should work"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.001,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.max_risk_per_trade == 0.001

    def test_risk_maximum_valid(self):
        """Risk of exactly 10% should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.1,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.max_risk_per_trade == 0.1

    def test_risk_zero_raises(self):
        """Risk = 0 should raise"""
        with pytest.raises(
            ConfigurationError, match="Max risk per trade must be 0-10%"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.0,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_risk_negative_raises(self):
        """Negative risk should raise"""
        with pytest.raises(
            ConfigurationError, match="Max risk per trade must be 0-10%"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=-0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_risk_too_high_raises(self):
        """Risk > 10% should raise"""
        with pytest.raises(
            ConfigurationError, match="Max risk per trade must be 0-10%"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.11,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    # Take profit ratio validation tests
    def test_take_profit_positive_valid(self):
        """Positive take profit ratio should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=3.5,
            stop_loss_percent=0.02,
        )
        assert config.take_profit_ratio == 3.5

    def test_take_profit_zero_raises(self):
        """Zero take profit ratio should raise"""
        with pytest.raises(
            ConfigurationError, match="Take profit ratio must be positive"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=0.0,
                stop_loss_percent=0.02,
            )

    def test_take_profit_negative_raises(self):
        """Negative take profit ratio should raise"""
        with pytest.raises(
            ConfigurationError, match="Take profit ratio must be positive"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=-1.0,
                stop_loss_percent=0.02,
            )

    # Stop loss percent validation tests
    def test_stop_loss_minimum_valid(self):
        """Minimum valid stop loss (just above 0) should work"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.001,
        )
        assert config.stop_loss_percent == 0.001

    def test_stop_loss_maximum_valid(self):
        """Stop loss of exactly 50% should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.5,
        )
        assert config.stop_loss_percent == 0.5

    def test_stop_loss_zero_raises(self):
        """Stop loss = 0 should raise"""
        with pytest.raises(
            ConfigurationError, match="Stop loss percent must be 0-50%"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.0,
            )

    def test_stop_loss_negative_raises(self):
        """Negative stop loss should raise"""
        with pytest.raises(
            ConfigurationError, match="Stop loss percent must be 0-50%"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=-0.01,
            )

    def test_stop_loss_too_high_raises(self):
        """Stop loss > 50% should raise"""
        with pytest.raises(
            ConfigurationError, match="Stop loss percent must be 0-50%"
        ):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.51,
            )

    # Symbol format validation tests
    def test_valid_usdt_symbols(self):
        """Valid USDT symbols should work"""
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
        for symbol in symbols:
            config = TradingConfig(
                symbol=symbol,
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )
            assert config.symbol == symbol

    def test_invalid_symbol_format_raises(self):
        """Symbol not ending with USDT should raise"""
        with pytest.raises(ConfigurationError, match="Invalid symbol format"):
            TradingConfig(
                symbol="BTCBUSD",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_empty_symbol_raises(self):
        """Empty symbol should raise"""
        with pytest.raises(ConfigurationError, match="Invalid symbol format"):
            TradingConfig(
                symbol="",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_lowercase_symbol_raises(self):
        """Lowercase symbol should raise"""
        with pytest.raises(ConfigurationError, match="Invalid symbol format"):
            TradingConfig(
                symbol="btcusdt",
                intervals=["1m"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    # Interval validation tests
    def test_valid_single_interval(self):
        """Single valid interval should work"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1h"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.intervals == ["1h"]

    def test_valid_multiple_intervals(self):
        """Multiple valid intervals should work"""
        intervals = ["1m", "5m", "15m", "1h", "4h", "1d"]
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=intervals,
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert len(config.intervals) == 6

    def test_all_valid_intervals(self):
        """All valid Binance intervals should work"""
        valid_intervals = [
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
        ]
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=valid_intervals,
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert len(config.intervals) == len(valid_intervals)

    def test_invalid_interval_format_raises(self):
        """Invalid interval format should raise"""
        with pytest.raises(ConfigurationError, match="Invalid interval"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1x"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_invalid_interval_in_list_raises(self):
        """One invalid interval in list should raise"""
        with pytest.raises(ConfigurationError, match="Invalid interval"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m", "5m", "invalid", "1h"],
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    def test_unsupported_interval_raises(self):
        """Unsupported but plausible intervals should raise"""
        with pytest.raises(ConfigurationError, match="Invalid interval"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["2m"],  # Not supported by Binance
                strategy="test",
                leverage=1,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

    # Margin type validation tests
    def test_margin_type_isolated_valid(self):
        """ISOLATED margin type should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            margin_type='ISOLATED'
        )
        assert config.margin_type == 'ISOLATED'

    def test_margin_type_crossed_valid(self):
        """CROSSED margin type should be valid"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            margin_type='CROSSED'
        )
        assert config.margin_type == 'CROSSED'

    def test_margin_type_default_isolated(self):
        """Default margin type should be ISOLATED"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02
        )
        assert config.margin_type == 'ISOLATED'

    def test_margin_type_invalid_raises(self):
        """Invalid margin type should raise ConfigurationError"""
        with pytest.raises(ConfigurationError, match="Margin type must be 'ISOLATED' or 'CROSSED'"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=10,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
                margin_type='INVALID'
            )

    def test_margin_type_lowercase_raises(self):
        """Lowercase margin type should raise ConfigurationError"""
        with pytest.raises(ConfigurationError, match="Margin type must be 'ISOLATED' or 'CROSSED'"):
            TradingConfig(
                symbol="BTCUSDT",
                intervals=["1m"],
                strategy="test",
                leverage=10,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
                margin_type='isolated'  # lowercase not accepted
            )


class TestLoggingConfigValidation:
    """Test LoggingConfig validation rules"""

    def test_valid_logging_config(self):
        """Valid configuration should not raise"""
        config = LoggingConfig(log_level="INFO", log_dir="logs")
        assert config.log_level == "INFO"
        assert config.log_dir == "logs"

    def test_all_valid_log_levels(self):
        """All valid log levels should work"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        for level in valid_levels:
            config = LoggingConfig(log_level=level)
            assert config.log_level == level

    def test_invalid_log_level_raises(self):
        """Invalid log level should raise"""
        with pytest.raises(ConfigurationError, match="Invalid log level"):
            LoggingConfig(log_level="INVALID")

    def test_lowercase_log_level_accepted(self):
        """Lowercase log level should be accepted and converted to uppercase"""
        config = LoggingConfig(log_level="info")
        # The implementation uses .upper() so lowercase is accepted
        assert config.log_level == "info"  # Stored as provided

    def test_default_values(self):
        """Default values should be set correctly"""
        config = LoggingConfig()
        assert config.log_level == "INFO"
        assert config.log_dir == "logs"


class TestConfigManagerValidation:
    """Test ConfigManager.validate() method"""

    def test_validate_returns_true_for_valid_config(self, tmp_path):
        """Valid configuration should return True"""
        # Create test config files
        api_config = tmp_path / "api_keys.ini"
        api_config.write_text(
            """
[binance]
use_testnet = true

[binance.testnet]
api_key = test_key_12345678
api_secret = test_secret_12345678
        """
        )

        trading_config = tmp_path / "trading_config.ini"
        trading_config.write_text(
            """
[trading]
symbol = BTCUSDT
intervals = 1m,5m
strategy = MockStrategy
leverage = 1
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02
        """
        )

        manager = ConfigManager(config_dir=str(tmp_path))
        assert manager.validate() is True

    def test_validate_returns_true_with_warnings(self, tmp_path, caplog):
        """Configuration with warnings should still return True"""
        # Create test config with high leverage in testnet
        api_config = tmp_path / "api_keys.ini"
        api_config.write_text(
            """
[binance]
use_testnet = true

[binance.testnet]
api_key = test_key_12345678
api_secret = test_secret_12345678
        """
        )

        trading_config = tmp_path / "trading_config.ini"
        trading_config.write_text(
            """
[trading]
symbol = BTCUSDT
intervals = 1m
strategy = MockStrategy
leverage = 10
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02
        """
        )

        manager = ConfigManager(config_dir=str(tmp_path))
        result = manager.validate()

        assert result is True
        # Check that leverage warning was logged
        assert "leverage in testnet mode" in caplog.text.lower()

    def test_validate_logs_testnet_mode(self, tmp_path, caplog):
        """Testnet mode should be logged"""
        import logging

        # Set logging level to capture INFO messages
        caplog.set_level(logging.INFO)

        api_config = tmp_path / "api_keys.ini"
        api_config.write_text(
            """
[binance]
use_testnet = true

[binance.testnet]
api_key = test_key
api_secret = test_secret
        """
        )

        trading_config = tmp_path / "trading_config.ini"
        trading_config.write_text(
            """
[trading]
symbol = BTCUSDT
intervals = 1m
strategy = test
leverage = 1
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02
        """
        )

        manager = ConfigManager(config_dir=str(tmp_path))
        manager.validate()

        assert "TESTNET mode" in caplog.text

    def test_validate_logs_production_mode(self, tmp_path, caplog):
        """Production mode should be logged with warning"""
        api_config = tmp_path / "api_keys.ini"
        api_config.write_text(
            """
[binance]
use_testnet = false

[binance.mainnet]
api_key = test_key_mainnet
api_secret = test_secret_mainnet
        """
        )

        trading_config = tmp_path / "trading_config.ini"
        trading_config.write_text(
            """
[trading]
symbol = BTCUSDT
intervals = 1m
strategy = test
leverage = 1
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02
        """
        )

        manager = ConfigManager(config_dir=str(tmp_path))
        manager.validate()

        assert "PRODUCTION mode" in caplog.text
        assert "real funds" in caplog.text.lower()


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_leverage_boundary_values(self):
        """Test leverage at exact boundaries"""
        # Test leverage = 1 (minimum)
        config1 = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config1.leverage == 1

        # Test leverage = 125 (maximum)
        config2 = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=125,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config2.leverage == 125

    def test_risk_boundary_values(self):
        """Test risk at exact boundaries"""
        # Test minimum (just above 0)
        config1 = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.0001,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config1.max_risk_per_trade == 0.0001

        # Test maximum (exactly 10%)
        config2 = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.1,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config2.max_risk_per_trade == 0.1

    def test_empty_intervals_list(self):
        """Empty intervals list should work (will fail elsewhere but validation passes)"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=[],
            strategy="test",
            leverage=1,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.intervals == []

    def test_very_high_leverage_and_risk_combination(self):
        """Valid but dangerous configuration should still validate"""
        config = TradingConfig(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="test",
            leverage=125,
            max_risk_per_trade=0.1,
            take_profit_ratio=1.1,
            stop_loss_percent=0.5,
        )
        assert config.leverage == 125
        assert config.max_risk_per_trade == 0.1
