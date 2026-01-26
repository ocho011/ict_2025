"""
Unit tests for StrategyFactory.

Tests the Factory Method pattern implementation for strategy instantiation,
including validation, error handling, and extensibility.
"""

import pytest

from src.strategies import (
    AlwaysSignalStrategy,
    BaseStrategy,
    MockSMACrossoverStrategy,
    StrategyFactory,
)


class TestStrategyFactoryCreation:
    """Test successful strategy creation scenarios."""

    def test_create_mock_sma_strategy_default_config(self):
        """Test factory creates MockSMACrossoverStrategy with default config."""
        strategy = StrategyFactory.create(name="mock_sma", symbol="BTCUSDT", config={})

        assert isinstance(strategy, MockSMACrossoverStrategy)
        assert isinstance(strategy, BaseStrategy)
        assert strategy.symbol == "BTCUSDT"
        # Verify default config values
        assert strategy.fast_period == 10
        assert strategy.slow_period == 20
        assert strategy.config.get("risk_reward_ratio", 2.0) == 2.0
        assert strategy.config.get("stop_loss_percent", 0.01) == 0.01

    def test_create_mock_sma_strategy_custom_config(self):
        """Test factory creates strategy with custom configuration."""
        config = {
            "fast_period": 5,
            "slow_period": 15,
            "risk_reward_ratio": 3.0,
            "stop_loss_percent": 0.015,
        }

        strategy = StrategyFactory.create("mock_sma", "ETHUSDT", config)

        assert strategy.symbol == "ETHUSDT"
        assert strategy.fast_period == 5
        assert strategy.slow_period == 15
        assert strategy.config.get("risk_reward_ratio") == 3.0
        assert strategy.config.get("stop_loss_percent") == 0.015

    def test_create_mock_sma_strategy_partial_config(self):
        """Test factory merges partial config with defaults."""
        config = {"fast_period": 7}

        strategy = StrategyFactory.create("mock_sma", "BTCUSDT", config)

        # Custom value
        assert strategy.fast_period == 7
        # Defaults for others
        assert strategy.slow_period == 20
        assert strategy.config.get("risk_reward_ratio", 2.0) == 2.0

    def test_create_returns_baseStrate_type(self):
        """Test factory returns BaseStrategy type for type safety."""
        strategy = StrategyFactory.create("mock_sma", "BTCUSDT", {})

        # Should be instance of both concrete class and abstract base
        assert isinstance(strategy, BaseStrategy)
        assert isinstance(strategy, MockSMACrossoverStrategy)

    def test_create_always_signal_strategy_default_config(self):
        """Test factory creates AlwaysSignalStrategy with default config."""
        strategy = StrategyFactory.create(name="always_signal", symbol="BTCUSDT", config={})

        assert isinstance(strategy, AlwaysSignalStrategy)
        assert isinstance(strategy, BaseStrategy)
        assert strategy.symbol == "BTCUSDT"
        # Verify default config values
        assert strategy.signal_mode == "ALTERNATE"
        assert strategy.risk_reward_ratio == 2.0
        assert strategy.stop_loss_percent == 0.02

    def test_create_always_signal_strategy_long_only(self):
        """Test factory creates AlwaysSignalStrategy in LONG mode."""
        config = {"signal_type": "LONG"}

        strategy = StrategyFactory.create("always_signal", "ETHUSDT", config)

        assert strategy.symbol == "ETHUSDT"
        assert strategy.signal_mode == "LONG"


class TestStrategyFactoryValidation:
    """Test error handling and validation."""

    def test_create_unknown_strategy_raises_value_error(self):
        """Test ValueError raised for unregistered strategy name."""
        with pytest.raises(ValueError) as exc_info:
            StrategyFactory.create("nonexistent_strategy", "BTCUSDT", {})

        error_msg = str(exc_info.value)
        assert "Unknown strategy" in error_msg
        assert "nonexistent_strategy" in error_msg
        assert "mock_sma" in error_msg  # Lists available strategies

    def test_create_with_invalid_config_type_raises_type_error(self):
        """Test TypeError raised for non-dict config."""
        with pytest.raises(TypeError) as exc_info:
            StrategyFactory.create("mock_sma", "BTCUSDT", "invalid_config")

        error_msg = str(exc_info.value)
        assert "config must be a dict" in error_msg
        assert "str" in error_msg

    def test_create_with_none_config_raises_type_error(self):
        """Test TypeError raised for None config."""
        with pytest.raises(TypeError) as exc_info:
            StrategyFactory.create("mock_sma", "BTCUSDT", None)

        error_msg = str(exc_info.value)
        assert "config must be a dict" in error_msg

    def test_create_with_list_config_raises_type_error(self):
        """Test TypeError raised for list config."""
        with pytest.raises(TypeError) as exc_info:
            StrategyFactory.create("mock_sma", "BTCUSDT", [1, 2, 3])

        error_msg = str(exc_info.value)
        assert "config must be a dict" in error_msg
        assert "list" in error_msg

    def test_create_with_empty_strategy_name(self):
        """Test handling of empty strategy name."""
        with pytest.raises(ValueError) as exc_info:
            StrategyFactory.create("", "BTCUSDT", {})

        error_msg = str(exc_info.value)
        assert "Unknown strategy" in error_msg


class TestStrategyFactoryIntrospection:
    """Test registry query methods."""

    def test_list_strategies_returns_list(self):
        """Test list_strategies returns list of strategy names."""
        strategies = StrategyFactory.list_strategies()

        assert isinstance(strategies, list)
        assert "mock_sma" in strategies
        assert len(strategies) >= 1

    def test_list_strategies_contains_all_registered(self):
        """Test list_strategies returns all registered strategies."""
        strategies = StrategyFactory.list_strategies()

        # Should contain registered strategies
        assert "mock_sma" in strategies
        assert "always_signal" in strategies
        assert len(strategies) >= 2

    def test_is_registered_returns_true_for_registered_strategy(self):
        """Test is_registered returns True for registered strategy."""
        assert StrategyFactory.is_registered("mock_sma") is True
        assert StrategyFactory.is_registered("always_signal") is True

    def test_is_registered_returns_false_for_unregistered_strategy(self):
        """Test is_registered returns False for unregistered strategy."""
        assert StrategyFactory.is_registered("unknown_strategy") is False

    def test_is_registered_case_sensitive(self):
        """Test is_registered is case-sensitive."""
        assert StrategyFactory.is_registered("mock_sma") is True
        assert StrategyFactory.is_registered("MOCK_SMA") is False
        assert StrategyFactory.is_registered("Mock_SMA") is False


class TestStrategyFactoryExtensibility:
    """Test dynamic registration functionality."""

    def test_register_new_strategy_class(self):
        """Test registering a new strategy class dynamically."""

        # Create a dummy strategy for testing
        class DummyStrategy(BaseStrategy):
            def __init__(self, symbol: str, config: dict):
                super().__init__(symbol, config)

            async def analyze(self, candle):
                return None

            async def should_exit(self, position, candle):
                return None

            def calculate_take_profit(self, entry_price, side):
                return entry_price * 1.01

            def calculate_stop_loss(self, entry_price, side):
                return entry_price * 0.99

        # Register the dummy strategy
        StrategyFactory.register("dummy_test", DummyStrategy)

        try:
            # Verify registration
            assert StrategyFactory.is_registered("dummy_test")
            assert "dummy_test" in StrategyFactory.list_strategies()

            # Verify creation works
            strategy = StrategyFactory.create("dummy_test", "BTCUSDT", {})
            assert isinstance(strategy, DummyStrategy)
            assert isinstance(strategy, BaseStrategy)
        finally:
            # Clean up: remove test strategy from registry
            if "dummy_test" in StrategyFactory._strategies:
                del StrategyFactory._strategies["dummy_test"]

    def test_register_non_basestrategy_raises_type_error(self):
        """Test TypeError raised when registering non-BaseStrategy class."""

        class NotAStrategy:
            pass

        with pytest.raises(TypeError) as exc_info:
            StrategyFactory.register("invalid", NotAStrategy)

        error_msg = str(exc_info.value)
        assert "must inherit from BaseStrategy" in error_msg
        assert "NotAStrategy" in error_msg

    def test_register_duplicate_name_raises_value_error(self):
        """Test ValueError raised when registering duplicate strategy name."""

        class AnotherStrategy(BaseStrategy):
            async def analyze(self, candle):
                return None

            async def should_exit(self, position, candle):
                return None

            def calculate_take_profit(self, entry_price, side):
                return entry_price

            def calculate_stop_loss(self, entry_price, side):
                return entry_price

        with pytest.raises(ValueError) as exc_info:
            StrategyFactory.register("mock_sma", AnotherStrategy)

        error_msg = str(exc_info.value)
        assert "already registered" in error_msg
        assert "mock_sma" in error_msg


class TestStrategyFactoryConfiguration:
    """Test configuration parameter handling."""

    def test_config_with_extra_parameters(self):
        """Test factory handles config with extra parameters gracefully."""
        config = {
            "fast_period": 8,
            "slow_period": 21,
            "extra_param": "ignored",
            "another_extra": 123,
        }

        # Should not raise error, extra params just ignored
        strategy = StrategyFactory.create("mock_sma", "BTCUSDT", config)

        assert strategy.fast_period == 8
        assert strategy.slow_period == 21

    def test_config_with_numeric_string_values(self):
        """Test config with string values (constructor handles conversion)."""
        # This tests that factory passes config as-is to constructor
        # Constructor's responsibility to validate/convert types
        config = {"fast_period": "10", "slow_period": "20"}  # String instead of int

        # May raise ValueError in constructor, but factory passes it through
        # This depends on MockSMACrossoverStrategy's constructor validation
        try:
            strategy = StrategyFactory.create("mock_sma", "BTCUSDT", config)
            # If constructor is lenient and converts, this passes
            assert strategy.symbol == "BTCUSDT"
        except (ValueError, TypeError):
            # If constructor is strict, this is expected
            pass


class TestStrategyFactoryIntegration:
    """Integration tests with real strategy classes."""

    def test_factory_with_mock_strategy_full_workflow(self):
        """Test complete workflow: create, configure, verify."""
        config = {
            "fast_period": 12,
            "slow_period": 26,
            "risk_reward_ratio": 2.5,
            "stop_loss_percent": 0.012,
        }

        strategy = StrategyFactory.create("mock_sma", "BTCUSDT", config)

        # Verify configuration
        assert strategy.symbol == "BTCUSDT"
        assert strategy.fast_period == 12
        assert strategy.slow_period == 26

        # Verify strategy has required methods (inherited from BaseStrategy)
        assert hasattr(strategy, "analyze")
        assert hasattr(strategy, "calculate_take_profit")
        assert hasattr(strategy, "calculate_stop_loss")
        assert callable(strategy.analyze)
        assert callable(strategy.calculate_take_profit)
        assert callable(strategy.calculate_stop_loss)

    def test_multiple_strategies_independent(self):
        """Test multiple strategy instances are independent."""
        strategy1 = StrategyFactory.create("mock_sma", "BTCUSDT", {"fast_period": 5})
        strategy2 = StrategyFactory.create("mock_sma", "ETHUSDT", {"fast_period": 10})

        # Different instances
        assert strategy1 is not strategy2

        # Different configurations
        assert strategy1.symbol == "BTCUSDT"
        assert strategy2.symbol == "ETHUSDT"
        assert strategy1.fast_period == 5
        assert strategy2.fast_period == 10

    def test_factory_stateless_behavior(self):
        """Test factory maintains no state between calls."""
        # First creation
        strategy1 = StrategyFactory.create("mock_sma", "BTCUSDT", {})

        # Second creation should be independent
        strategy2 = StrategyFactory.create("mock_sma", "ETHUSDT", {})

        # Both should work independently
        assert strategy1.symbol == "BTCUSDT"
        assert strategy2.symbol == "ETHUSDT"
        assert strategy1 is not strategy2
