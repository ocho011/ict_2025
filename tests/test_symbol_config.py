"""
Tests for Per-Symbol Strategy Configuration (Issue #18).

This module tests:
1. SymbolConfig validation
2. TradingConfigHierarchical creation and methods
3. Config inheritance and override logic
4. YAML and INI format support
"""

import pytest

from src.config.symbol_config import (
    SymbolConfig,
    TradingConfigHierarchical,
    VALID_STRATEGIES,
    VALID_INTERVALS,
)
from src.core.exceptions import ConfigurationError


# -----------------------------------------------------------------------------
# Test SymbolConfig
# -----------------------------------------------------------------------------


class TestSymbolConfig:
    """Tests for SymbolConfig dataclass."""

    def test_create_valid_btc_config(self):
        """Test creating a valid BTC config."""
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="ict_strategy",
            leverage=2,
            max_risk_per_trade=0.01,
        )

        assert config.symbol == "BTCUSDT"
        assert config.strategy == "ict_strategy"
        assert config.leverage == 2
        assert config.enabled is True
        assert config.ict_config is not None  # Auto-created for ICT

    def test_create_config_with_ict_settings(self):
        """Test creating config with ICT-specific settings."""
        ict_config = {
            "active_profile": "strict",
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
            "use_killzones": True,
        }

        config = SymbolConfig(
            symbol="ETHUSDT",
            strategy="ict_strategy",
            leverage=3,
            ict_config=ict_config,
        )

        assert config.ict_config["active_profile"] == "strict"
        assert config.ict_config["ltf_interval"] == "5m"

    def test_invalid_symbol_format_raises(self):
        """Test that invalid symbol format raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="must end with 'USDT'"):
            SymbolConfig(
                symbol="BTCETH",  # Invalid - should end with USDT
                strategy="ict_strategy",
            )

    def test_invalid_strategy_raises(self):
        """Test that invalid strategy raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid strategy"):
            SymbolConfig(
                symbol="BTCUSDT",
                strategy="invalid_strategy",
            )

    def test_leverage_out_of_range_raises(self):
        """Test that leverage out of range raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Leverage must be 1-125"):
            SymbolConfig(
                symbol="BTCUSDT",
                strategy="ict_strategy",
                leverage=200,  # Max is 125
            )

    def test_negative_leverage_raises(self):
        """Test that negative leverage raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Leverage must be 1-125"):
            SymbolConfig(
                symbol="BTCUSDT",
                strategy="ict_strategy",
                leverage=0,
            )

    def test_risk_out_of_range_raises(self):
        """Test that risk out of range raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Max risk per trade"):
            SymbolConfig(
                symbol="BTCUSDT",
                strategy="ict_strategy",
                max_risk_per_trade=0.15,  # Max is 0.1 (10%)
            )

    def test_invalid_margin_type_raises(self):
        """Test that invalid margin type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Margin type must be"):
            SymbolConfig(
                symbol="BTCUSDT",
                strategy="ict_strategy",
                margin_type="INVALID",
            )

    def test_invalid_interval_raises(self):
        """Test that invalid interval raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid interval"):
            SymbolConfig(
                symbol="BTCUSDT",
                strategy="ict_strategy",
                intervals=["5m", "invalid_interval"],
            )

    def test_get_strategy_config_for_ict(self):
        """Test get_strategy_config returns ICT config."""
        ict_config = {"active_profile": "balanced"}
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="ict_strategy",
            ict_config=ict_config,
        )

        result = config.get_strategy_config()
        assert result["active_profile"] == "balanced"

    def test_get_strategy_config_for_momentum(self):
        """Test get_strategy_config returns momentum config."""
        momentum_config = {"fast_period": 12}
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="momentum_strategy",
            momentum_config=momentum_config,
            ict_config=None,
        )

        result = config.get_strategy_config()
        assert result["fast_period"] == 12

    def test_to_trading_config_dict(self):
        """Test conversion to TradingConfig-compatible dict."""
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="ict_strategy",
            leverage=2,
            max_risk_per_trade=0.01,
            intervals=["5m", "1h"],
        )

        result = config.to_trading_config_dict()

        assert result["symbols"] == ["BTCUSDT"]
        assert result["leverage"] == 2
        assert result["intervals"] == ["5m", "1h"]
        assert "ict_config" in result


# -----------------------------------------------------------------------------
# Test TradingConfigHierarchical
# -----------------------------------------------------------------------------


class TestTradingConfigHierarchical:
    """Tests for TradingConfigHierarchical class."""

    @pytest.fixture
    def sample_config_dict(self):
        """Sample configuration dictionary."""
        return {
            "defaults": {
                "leverage": 1,
                "max_risk_per_trade": 0.01,
                "margin_type": "ISOLATED",
                "backfill_limit": 200,
            },
            "symbols": {
                "BTCUSDT": {
                    "strategy": "ict_strategy",
                    "leverage": 2,
                    "ict_config": {
                        "active_profile": "strict",
                    },
                },
                "ETHUSDT": {
                    "strategy": "ict_strategy",
                    "leverage": 3,
                    "enabled": False,  # Disabled
                    "ict_config": {
                        "active_profile": "balanced",
                    },
                },
            },
        }

    def test_from_dict(self, sample_config_dict):
        """Test creating config from dictionary."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        assert "BTCUSDT" in config.symbols
        assert "ETHUSDT" in config.symbols
        assert config.symbols["BTCUSDT"].leverage == 2
        assert config.symbols["ETHUSDT"].leverage == 3

    def test_get_symbol_config_existing(self, sample_config_dict):
        """Test getting config for existing symbol."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        btc_config = config.get_symbol_config("BTCUSDT")

        assert btc_config.symbol == "BTCUSDT"
        assert btc_config.leverage == 2
        assert btc_config.ict_config["active_profile"] == "strict"

    def test_get_symbol_config_with_defaults(self, sample_config_dict):
        """Test getting config for unconfigured symbol uses defaults."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        # SOLUSDT not in symbols, should use defaults
        sol_config = config.get_symbol_config("SOLUSDT")

        assert sol_config.symbol == "SOLUSDT"
        assert sol_config.leverage == 1  # Default leverage

    def test_get_symbol_config_no_defaults_raises(self):
        """Test getting config for unknown symbol without defaults raises."""
        config = TradingConfigHierarchical(defaults={}, symbols={})

        with pytest.raises(ConfigurationError, match="not configured"):
            config.get_symbol_config("BTCUSDT")

    def test_get_enabled_symbols(self, sample_config_dict):
        """Test getting list of enabled symbols."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        enabled = config.get_enabled_symbols()

        assert "BTCUSDT" in enabled
        assert "ETHUSDT" not in enabled  # Disabled

    def test_get_symbols_by_strategy(self, sample_config_dict):
        """Test getting symbols filtered by strategy."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        ict_symbols = config.get_symbols_by_strategy("ict_strategy")

        assert "BTCUSDT" in ict_symbols
        # ETHUSDT is disabled, so not included
        assert "ETHUSDT" not in ict_symbols

    def test_defaults_inheritance(self, sample_config_dict):
        """Test that symbol config inherits from defaults."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        btc_config = config.get_symbol_config("BTCUSDT")

        # Leverage overridden
        assert btc_config.leverage == 2
        # These should come from defaults
        assert btc_config.max_risk_per_trade == 0.01
        assert btc_config.margin_type == "ISOLATED"
        assert btc_config.backfill_limit == 200

    def test_to_legacy_trading_config_list(self, sample_config_dict):
        """Test conversion to legacy TradingConfig format."""
        config = TradingConfigHierarchical.from_dict(sample_config_dict)

        legacy_configs = config.to_legacy_trading_config_list()

        # Only enabled symbols
        assert len(legacy_configs) == 1  # Only BTCUSDT (ETHUSDT disabled)
        assert legacy_configs[0]["symbols"] == ["BTCUSDT"]
        assert legacy_configs[0]["leverage"] == 2


class TestTradingConfigHierarchicalINI:
    """Tests for INI format support."""

    def test_from_ini_sections(self):
        """Test creating config from INI sections."""
        trading_section = {
            "strategy": "ict_strategy",
            "leverage": "1",
            "max_risk_per_trade": "0.01",
            "margin_type": "ISOLATED",
            "backfill_limit": "200",
            "intervals": "5m,1h,4h",
        }

        strategy_sections = {
            "BTCUSDT": {
                "strategy": "ict_strategy",
                "leverage": "2",
                "active_profile": "strict",
                "ltf_interval": "5m",
            },
            "ETHUSDT": {
                "strategy": "ict_strategy",
                "leverage": "3",
                "active_profile": "balanced",
            },
        }

        config = TradingConfigHierarchical.from_ini_sections(
            trading_section, strategy_sections
        )

        assert "BTCUSDT" in config.symbols
        assert config.symbols["BTCUSDT"].leverage == 2
        assert config.symbols["BTCUSDT"].ict_config["active_profile"] == "strict"

    def test_from_ini_sections_with_disabled_symbol(self):
        """Test INI parsing with disabled symbol."""
        trading_section = {
            "strategy": "ict_strategy",
            "leverage": "1",
            "intervals": "5m,1h",
        }

        strategy_sections = {
            "BTCUSDT": {
                "strategy": "ict_strategy",
                "leverage": "2",
                "enabled": "true",
            },
            "XRPUSDT": {
                "strategy": "ict_strategy",
                "enabled": "false",
            },
        }

        config = TradingConfigHierarchical.from_ini_sections(
            trading_section, strategy_sections
        )

        assert config.symbols["BTCUSDT"].enabled is True
        assert config.symbols["XRPUSDT"].enabled is False


# -----------------------------------------------------------------------------
# Test Validation Constants
# -----------------------------------------------------------------------------


class TestValidationConstants:
    """Tests for validation constants."""

    def test_valid_strategies(self):
        """Test VALID_STRATEGIES contains expected values."""
        assert "ict_strategy" in VALID_STRATEGIES
        assert "momentum_strategy" in VALID_STRATEGIES
        assert "mock_strategy" in VALID_STRATEGIES

    def test_valid_intervals(self):
        """Test VALID_INTERVALS contains Binance intervals."""
        assert "1m" in VALID_INTERVALS
        assert "5m" in VALID_INTERVALS
        assert "1h" in VALID_INTERVALS
        assert "4h" in VALID_INTERVALS
        assert "1d" in VALID_INTERVALS

    def test_all_strategies_are_strings(self):
        """Test all strategies are strings."""
        for strategy in VALID_STRATEGIES:
            assert isinstance(strategy, str)

    def test_all_intervals_are_strings(self):
        """Test all intervals are strings."""
        for interval in VALID_INTERVALS:
            assert isinstance(interval, str)


# -----------------------------------------------------------------------------
# Test ConfigManager Integration
# -----------------------------------------------------------------------------


class TestConfigManagerHierarchicalIntegration:
    """Tests for ConfigManager hierarchical config loading."""

    @pytest.fixture
    def temp_config_dir(self, tmp_path):
        """Create a temporary config directory with test files."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        # Create minimal API config
        api_config = config_dir / "api_keys.ini"
        api_config.write_text("""
[binance]
use_testnet = true

[binance.testnet]
api_key = test_key_12345
api_secret = test_secret_67890
""")

        # Create legacy trading config
        trading_config = config_dir / "trading_config.ini"
        trading_config.write_text("""
[trading]
symbols = BTCUSDT
intervals = 5m,1h
strategy = ict_strategy
leverage = 2
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02
margin_type = ISOLATED
backfill_limit = 200
""")

        return config_dir

    @pytest.fixture
    def yaml_config_content(self):
        """Sample YAML config content."""
        return """
trading:
  defaults:
    leverage: 1
    max_risk_per_trade: 0.01
    margin_type: ISOLATED
    backfill_limit: 200

  symbols:
    BTCUSDT:
      strategy: ict_strategy
      enabled: true
      leverage: 2
      ict_config:
        active_profile: strict

    ETHUSDT:
      strategy: ict_strategy
      enabled: true
      leverage: 3
      ict_config:
        active_profile: balanced
"""

    def test_config_manager_without_yaml(self, temp_config_dir, monkeypatch):
        """Test ConfigManager works without YAML config."""
        from src.utils.config_manager import ConfigManager

        # Patch the config_dir
        cm = ConfigManager.__new__(ConfigManager)
        cm.config_dir = temp_config_dir
        cm._api_config = None
        cm._trading_config = None
        cm._logging_config = None
        cm._liquidation_config = None
        cm._hierarchical_config = None
        cm._load_configs()

        # Should not have hierarchical config
        assert cm.has_hierarchical_config is False
        assert cm.hierarchical_config is None

        # Should still load legacy config
        assert cm.trading_config is not None
        assert "BTCUSDT" in cm.trading_config.symbols

    def test_config_manager_with_yaml(self, temp_config_dir, yaml_config_content):
        """Test ConfigManager loads YAML config when available."""
        from src.utils.config_manager import ConfigManager

        # Create YAML config file
        yaml_file = temp_config_dir / "trading_config.yaml"
        yaml_file.write_text(yaml_config_content)

        # Patch the config_dir
        cm = ConfigManager.__new__(ConfigManager)
        cm.config_dir = temp_config_dir
        cm._api_config = None
        cm._trading_config = None
        cm._logging_config = None
        cm._liquidation_config = None
        cm._hierarchical_config = None
        cm._load_configs()

        # Should have hierarchical config
        assert cm.has_hierarchical_config is True
        assert cm.hierarchical_config is not None

        # Verify hierarchical config content
        btc_config = cm.hierarchical_config.get_symbol_config("BTCUSDT")
        assert btc_config.symbol == "BTCUSDT"
        assert btc_config.leverage == 2
        assert btc_config.ict_config["active_profile"] == "strict"

        eth_config = cm.hierarchical_config.get_symbol_config("ETHUSDT")
        assert eth_config.leverage == 3
        assert eth_config.ict_config["active_profile"] == "balanced"

    def test_config_manager_yaml_invalid_structure(self, temp_config_dir):
        """Test ConfigManager handles invalid YAML structure."""
        from src.utils.config_manager import ConfigManager

        # Create invalid YAML (missing trading section)
        yaml_file = temp_config_dir / "trading_config.yaml"
        yaml_file.write_text("invalid:\n  key: value\n")

        cm = ConfigManager.__new__(ConfigManager)
        cm.config_dir = temp_config_dir
        cm._api_config = None
        cm._trading_config = None
        cm._logging_config = None
        cm._liquidation_config = None
        cm._hierarchical_config = None
        cm._load_configs()

        # Should fall back to no hierarchical config
        assert cm.has_hierarchical_config is False

    def test_hierarchical_config_get_enabled_symbols(
        self, temp_config_dir, yaml_config_content
    ):
        """Test getting enabled symbols from hierarchical config."""
        from src.utils.config_manager import ConfigManager

        yaml_file = temp_config_dir / "trading_config.yaml"
        yaml_file.write_text(yaml_config_content)

        cm = ConfigManager.__new__(ConfigManager)
        cm.config_dir = temp_config_dir
        cm._api_config = None
        cm._trading_config = None
        cm._logging_config = None
        cm._liquidation_config = None
        cm._hierarchical_config = None
        cm._load_configs()

        enabled = cm.hierarchical_config.get_enabled_symbols()
        assert "BTCUSDT" in enabled
        assert "ETHUSDT" in enabled
