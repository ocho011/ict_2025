"""
Test configuration loading with separate mainnet/testnet credentials
"""

import os
import tempfile
from pathlib import Path
import pytest
from src.utils.config import ConfigManager, APIConfig
from src.core.exceptions import ConfigurationError


class TestEnvironmentSeparation:
    """Test mainnet/testnet credential separation"""

    def setup_method(self):
        """Create temporary config directory for each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = Path(self.temp_dir)

        # Create trading config (required)
        trading_config = self.config_path / "trading_config.ini"
        trading_config.write_text("""[trading]
symbol = BTCUSDT
intervals = 1m,5m
strategy = MockStrategy
leverage = 1
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02
""")

    def teardown_method(self):
        """Clean up temporary files"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_testnet_credentials_loaded(self):
        """Test that testnet credentials are loaded when use_testnet=true"""
        # Create API config with testnet selected
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = true

[binance.testnet]
api_key = testnet_key_123
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        config = ConfigManager(config_dir=self.temp_dir)

        assert config.api_config.api_key == "testnet_key_123"
        assert config.api_config.api_secret == "testnet_secret_456"
        assert config.api_config.is_testnet is True

    def test_mainnet_credentials_loaded(self):
        """Test that mainnet credentials are loaded when use_testnet=false"""
        # Create API config with mainnet selected
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = false

[binance.testnet]
api_key = testnet_key_123
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        config = ConfigManager(config_dir=self.temp_dir)

        assert config.api_config.api_key == "mainnet_key_789"
        assert config.api_config.api_secret == "mainnet_secret_abc"
        assert config.api_config.is_testnet is False

    def test_environment_variable_override(self):
        """Test that BINANCE_USE_TESTNET environment variable overrides INI"""
        # Create API config with testnet in INI
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = true

[binance.testnet]
api_key = testnet_key_123
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        # Override to mainnet via environment
        os.environ["BINANCE_USE_TESTNET"] = "false"

        try:
            config = ConfigManager(config_dir=self.temp_dir)

            assert config.api_config.api_key == "mainnet_key_789"
            assert config.api_config.is_testnet is False
        finally:
            del os.environ["BINANCE_USE_TESTNET"]

    def test_direct_env_credentials(self):
        """Test direct credential loading from environment variables"""
        os.environ["BINANCE_API_KEY"] = "env_key_xyz"
        os.environ["BINANCE_API_SECRET"] = "env_secret_xyz"
        os.environ["BINANCE_USE_TESTNET"] = "false"

        try:
            config = ConfigManager(config_dir=self.temp_dir)

            assert config.api_config.api_key == "env_key_xyz"
            assert config.api_config.api_secret == "env_secret_xyz"
            assert config.api_config.is_testnet is False
        finally:
            del os.environ["BINANCE_API_KEY"]
            del os.environ["BINANCE_API_SECRET"]
            del os.environ["BINANCE_USE_TESTNET"]

    def test_missing_environment_section_error(self):
        """Test error when selected environment section is missing"""
        # Create config without testnet section
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = true

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        with pytest.raises(ConfigurationError, match="binance.testnet.*not found"):
            ConfigManager(config_dir=self.temp_dir)

    def test_placeholder_credentials_rejected(self):
        """Test that placeholder values are rejected"""
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = true

[binance.testnet]
api_key = your_testnet_api_key_here
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        with pytest.raises(ConfigurationError, match="Invalid API key"):
            ConfigManager(config_dir=self.temp_dir)

    def test_default_testnet_mode(self):
        """Test that testnet is default when use_testnet is not specified"""
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]

[binance.testnet]
api_key = testnet_key_123
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        config = ConfigManager(config_dir=self.temp_dir)

        assert config.api_config.is_testnet is True
        assert config.api_config.api_key == "testnet_key_123"

    def test_validation_warning_messages(self):
        """Test that appropriate warnings are shown for testnet/mainnet"""
        import io
        import sys

        # Test testnet warning
        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = true

[binance.testnet]
api_key = testnet_key_123
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        config = ConfigManager(config_dir=self.temp_dir)

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        config.validate()

        sys.stdout = sys.__stdout__
        output = captured_output.getvalue()

        assert "TESTNET mode" in output

    def test_mainnet_production_warning(self):
        """Test that mainnet mode shows production warning"""
        import io
        import sys

        api_config = self.config_path / "api_keys.ini"
        api_config.write_text("""[binance]
use_testnet = false

[binance.testnet]
api_key = testnet_key_123
api_secret = testnet_secret_456

[binance.mainnet]
api_key = mainnet_key_789
api_secret = mainnet_secret_abc
""")

        config = ConfigManager(config_dir=self.temp_dir)

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        config.validate()

        sys.stdout = sys.__stdout__
        output = captured_output.getvalue()

        assert "PRODUCTION mode" in output
        assert "real funds" in output.lower()
