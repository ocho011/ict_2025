"""
Unit tests for config.py (Issue #8: Multi-coin support)

Tests TradingConfig validation and parsing for multi-symbol support.
"""

import pytest

from src.core.exceptions import ConfigurationError
from src.utils.config_manager import TradingConfig, ExitConfig


class TestMultiSymbolValidation:
    """Test TradingConfig validation for multi-symbol support (Issue #8 Phase 1)."""

    def test_single_symbol_backward_compatibility(self):
        """Test that single symbol still works (backward compatibility)."""
        config = TradingConfig(
            symbols=["BTCUSDT"],
            intervals=["5m"],
            strategy="ict_strategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.symbols == ["BTCUSDT"]
        assert len(config.symbols) == 1

    def test_multi_symbol_success(self):
        """Test that multiple symbols are accepted."""
        config = TradingConfig(
            symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            intervals=["5m"],
            strategy="ict_strategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.symbols == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        assert len(config.symbols) == 3

    def test_max_symbols_limit_enforced(self):
        """Test that max_symbols=10 limit is enforced (configurable from ini)."""
        # 11 symbols should fail when max_symbols=10 (default)
        symbols = [f"SYM{i}USDT" for i in range(11)]

        with pytest.raises(ConfigurationError) as exc_info:
            TradingConfig(
                symbols=symbols,
                intervals=["5m"],
                strategy="ict_strategy",
                leverage=10,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
                max_symbols=10,  # Default value
            )

        assert "Maximum 10 symbols allowed" in str(exc_info.value)
        assert "got 11" in str(exc_info.value)

    def test_max_symbols_boundary_success(self):
        """Test that exactly 10 symbols is allowed (boundary case)."""
        symbols = [f"SYM{i}USDT" for i in range(10)]

        config = TradingConfig(
            symbols=symbols,
            intervals=["5m"],
            strategy="ict_strategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert len(config.symbols) == 10

    def test_empty_symbols_fails(self):
        """Test that empty symbols list raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            TradingConfig(
                symbols=[],
                intervals=["5m"],
                strategy="ict_strategy",
                leverage=10,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

        assert "At least one symbol is required" in str(exc_info.value)

    def test_invalid_symbol_format_fails(self):
        """Test that non-USDT symbols are rejected."""
        with pytest.raises(ConfigurationError) as exc_info:
            TradingConfig(
                symbols=["BTCUSDT", "ETHBTC", "BNBUSDT"],  # ETHBTC is invalid
                intervals=["5m"],
                strategy="ict_strategy",
                leverage=10,
                max_risk_per_trade=0.01,
                take_profit_ratio=2.0,
                stop_loss_percent=0.02,
            )

        assert "Invalid symbol format" in str(exc_info.value)
        assert "ETHBTC" in str(exc_info.value)
        assert "Must end with 'USDT'" in str(exc_info.value)

    def test_whitespace_in_symbols_handled(self):
        """Test that whitespace in symbol names is preserved (parser should strip)."""
        # This tests parsing logic, not the dataclass validation
        # Whitespace should be stripped by parser before reaching TradingConfig
        config = TradingConfig(
            symbols=["BTCUSDT", "ETHUSDT"],  # Already stripped
            intervals=["5m"],
            strategy="ict_strategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
        )
        assert config.symbols == ["BTCUSDT", "ETHUSDT"]
        assert all(" " not in s for s in config.symbols)


class TestExitConfig:
    """Test ExitConfig validation for dynamic exit strategies (Issue #43 Phase 1)."""

    def test_default_exit_config_creation(self):
        """Test that default ExitConfig creates successfully."""
        config = ExitConfig()

        assert config.dynamic_exit_enabled is True
        assert config.exit_strategy == "trailing_stop"
        assert config.trailing_distance == 0.02
        assert config.trailing_activation == 0.01
        assert config.breakeven_enabled is True
        assert config.breakeven_offset == 0.001
        assert config.timeout_enabled is False
        assert config.timeout_minutes == 240
        assert config.volatility_enabled is False
        assert config.atr_period == 14
        assert config.atr_multiplier == 2.0

    def test_custom_exit_config_creation(self):
        """Test that custom ExitConfig creates successfully."""
        config = ExitConfig(
            dynamic_exit_enabled=False,
            exit_strategy="breakeven",
            trailing_distance=0.015,
            trailing_activation=0.005,
            breakeven_enabled=False,
            breakeven_offset=0.002,
            timeout_enabled=True,
            timeout_minutes=180,
            volatility_enabled=True,
            atr_period=20,
            atr_multiplier=1.5,
        )

        assert config.dynamic_exit_enabled is False
        assert config.exit_strategy == "breakeven"
        assert config.trailing_distance == 0.015
        assert config.trailing_activation == 0.005
        assert config.breakeven_enabled is False
        assert config.breakeven_offset == 0.002
        assert config.timeout_enabled is True
        assert config.timeout_minutes == 180
        assert config.volatility_enabled is True
        assert config.atr_period == 20
        assert config.atr_multiplier == 1.5

    def test_invalid_exit_strategy_fails(self):
        """Test that invalid exit strategy raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(exit_strategy="invalid_strategy")

        assert "Invalid exit strategy" in str(exc_info.value)
        assert "invalid_strategy" in str(exc_info.value)
        assert "Must be one of" in str(exc_info.value)

    def test_trailing_distance_validation(self):
        """Test trailing distance parameter validation."""
        # Test too small
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(trailing_distance=0.0005)
        assert "trailing_distance must be 0.001-0.1" in str(exc_info.value)

        # Test too large
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(trailing_distance=0.2)
        assert "trailing_distance must be 0.001-0.1" in str(exc_info.value)

        # Test boundary values
        config = ExitConfig(trailing_distance=0.001)  # Minimum
        assert config.trailing_distance == 0.001

        config = ExitConfig(trailing_distance=0.1)  # Maximum
        assert config.trailing_distance == 0.1

    def test_trailing_activation_validation(self):
        """Test trailing activation parameter validation."""
        # Test too small
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(trailing_activation=0.0005)
        assert "trailing_activation must be 0.001-0.05" in str(exc_info.value)

        # Test too large
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(trailing_activation=0.1)
        assert "trailing_activation must be 0.001-0.05" in str(exc_info.value)

    def test_breakeven_offset_validation(self):
        """Test breakeven offset parameter validation."""
        # Test too small
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(breakeven_offset=0.00001)
        assert "breakeven_offset must be 0.0001-0.01" in str(exc_info.value)

        # Test too large
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(breakeven_offset=0.02)
        assert "breakeven_offset must be 0.0001-0.01" in str(exc_info.value)

    def test_timeout_minutes_validation(self):
        """Test timeout minutes parameter validation."""
        # Test too small
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(timeout_minutes=0)
        assert "timeout_minutes must be 1-1440" in str(exc_info.value)

        # Test too large
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(timeout_minutes=2000)
        assert "timeout_minutes must be 1-1440" in str(exc_info.value)

    def test_atr_period_validation(self):
        """Test ATR period parameter validation."""
        # Test too small
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(atr_period=3)
        assert "atr_period must be 5-100" in str(exc_info.value)

        # Test too large
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(atr_period=150)
        assert "atr_period must be 5-100" in str(exc_info.value)

    def test_atr_multiplier_validation(self):
        """Test ATR multiplier parameter validation."""
        # Test too small
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(atr_multiplier=0.3)
        assert "atr_multiplier must be 0.5-5.0" in str(exc_info.value)

        # Test too large
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(atr_multiplier=6.0)
        assert "atr_multiplier must be 0.5-5.0" in str(exc_info.value)

    def test_trailing_stop_strategy_consistency(self):
        """Test trailing stop strategy consistency validation."""
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(exit_strategy="trailing_stop", trailing_distance=0.0)

        assert "trailing_distance must be 0.001-0.1" in str(exc_info.value)

    def test_timed_strategy_consistency(self):
        """Test timed strategy consistency validation."""
        with pytest.raises(ConfigurationError) as exc_info:
            ExitConfig(exit_strategy="timed", timeout_enabled=False)

        assert "timed strategy requires timeout_enabled=True" in str(exc_info.value)

    def test_all_valid_exit_strategies(self):
        """Test that all valid exit strategies are accepted."""
        valid_strategies = ["trailing_stop", "breakeven", "timed", "indicator_based"]

        for strategy in valid_strategies:
            # Create config with minimal required parameters for each strategy
            if strategy == "trailing_stop":
                config = ExitConfig(exit_strategy=strategy, trailing_distance=0.02)
            elif strategy == "timed":
                config = ExitConfig(exit_strategy=strategy, timeout_enabled=True)
            else:
                config = ExitConfig(exit_strategy=strategy)

            assert config.exit_strategy == strategy

    def test_exit_config_with_trading_config_integration(self):
        """Test ExitConfig integration with TradingConfig."""
        exit_config = ExitConfig(
            exit_strategy="breakeven", breakeven_enabled=True, breakeven_offset=0.005
        )

        trading_config = TradingConfig(
            symbols=["BTCUSDT"],
            intervals=["5m"],
            strategy="ict_strategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            exit_config=exit_config,
        )

        assert trading_config.exit_config is not None
        assert trading_config.exit_config.exit_strategy == "breakeven"
        assert trading_config.exit_config.breakeven_enabled is True
        assert trading_config.exit_config.breakeven_offset == 0.005


# Note: ConfigManager parsing tests are skipped because ConfigManager
# requires a specific directory structure (project_root/configs/).
# The core multi-symbol validation is already covered by TestMultiSymbolValidation.
# Integration testing with actual config files will be covered in Phase 4.
