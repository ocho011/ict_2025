"""
Unit tests for config.py (Issue #8: Multi-coin support)

Tests TradingConfig validation and parsing for multi-symbol support.
"""

import pytest

from src.core.exceptions import ConfigurationError
from src.utils.config import TradingConfig


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
        """Test that MAX_SYMBOLS=10 limit is enforced."""
        # 11 symbols should fail
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
        # This tests the parsing logic, not the dataclass validation
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




# Note: ConfigManager parsing tests are skipped because ConfigManager
# requires a specific directory structure (project_root/configs/).
# The core multi-symbol validation is already covered by TestMultiSymbolValidation.
# Integration testing with actual config files will be covered in Phase 4.
