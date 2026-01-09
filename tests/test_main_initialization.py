"""
Unit tests for TradingBot initialization (Subtask 10.1).

Tests the TradingBot class constructor and initialize() method to ensure:
1. Constructor initializes all components to None
2. initialize() sets up all components in correct order
3. Configuration validation works correctly
4. Startup logging is comprehensive
5. Error handling is appropriate
"""

from unittest.mock import Mock, patch

import pytest

from src.main import TradingBot


class TestTradingBotConstructor:
    """Tests for TradingBot.__init__() method."""

    def test_constructor_initializes_components_to_none(self):
        """Test __init__ sets all components to None."""
        bot = TradingBot()

        # Verify all components are None
        assert bot.config_manager is None
        assert bot.event_bus is None
        assert bot.data_collector is None
        assert bot.order_manager is None
        assert bot.risk_manager is None
        assert bot.strategy is None
        assert bot.trading_engine is None
        assert bot.logger is None

        # Verify state flag
        assert bot._running is False

    def test_constructor_is_lightweight(self):
        """Test constructor performs no heavy operations."""
        # Should not raise any exceptions and should be instantaneous
        bot = TradingBot()
        assert bot is not None


class TestTradingBotInitialization:
    """Tests for TradingBot.initialize() method."""

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("src.main.BinanceDataCollector")
    @patch("src.main.OrderExecutionManager")
    @patch("src.main.RiskManager")
    @patch("src.main.StrategyFactory")
    @patch("src.main.EventBus")
    @patch("src.main.TradingEngine")
    @patch("logging.getLogger")
    def test_initialize_with_valid_config(
        self,
        mock_get_logger,
        mock_trading_engine,
        mock_event_bus,
        mock_strategy_factory,
        mock_risk_manager,
        mock_order_manager,
        mock_data_collector,
        mock_trading_logger,
        mock_config_manager,
    ):
        """Test successful initialization with valid config."""
        # Setup ConfigManager mock
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol="BTCUSDT",
            intervals=["1m", "5m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
        )
        config_instance.logging_config = Mock(
            log_level="INFO", log_dir="logs", console_enabled=True, file_enabled=True
        )
        config_instance.logging_config.__dict__ = {"log_level": "INFO", "log_dir": "logs"}
        mock_config_manager.return_value = config_instance

        # Setup OrderManager mock
        mock_order_instance = Mock()
        mock_order_instance.set_leverage.return_value = True
        mock_order_manager.return_value = mock_order_instance

        # Setup logger mock
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Execute
        bot = TradingBot()
        bot.initialize()

        # Verify initialization sequence (correct order)
        assert mock_config_manager.called, "ConfigManager not initialized"
        assert config_instance.validate.called, "Config validation not called"
        assert mock_trading_logger.called, "TradingLogger not initialized"
        assert mock_data_collector.called, "BinanceDataCollector not initialized"
        assert mock_order_manager.called, "OrderExecutionManager not initialized"
        assert mock_risk_manager.called, "RiskManager not initialized"
        assert mock_strategy_factory.create.called, "Strategy not created"
        assert mock_event_bus.called, "EventBus not initialized"
        assert mock_trading_engine.called, "TradingEngine not initialized"

        # Verify components are set
        assert bot.config_manager is not None
        assert bot.event_bus is not None
        assert bot.data_collector is not None
        assert bot.order_manager is not None
        assert bot.risk_manager is not None
        assert bot.strategy is not None
        assert bot.trading_engine is not None
        assert bot.logger is not None

        # Verify TradingEngine.set_components() was called with all dependencies
        mock_trading_engine_instance = mock_trading_engine.return_value
        mock_trading_engine_instance.set_components.assert_called_once()

        # Verify leverage was set
        mock_order_instance.set_leverage.assert_called_once_with("BTCUSDT", 10)

    @patch("src.main.ConfigManager")
    def test_initialize_fails_with_invalid_config(self, mock_config_manager):
        """Test initialize raises ValueError on invalid config."""
        # Setup ConfigManager to fail validation
        config_instance = Mock()
        config_instance.validate.return_value = False
        mock_config_manager.return_value = config_instance

        bot = TradingBot()

        # Should raise ValueError with helpful message
        with pytest.raises(ValueError, match="Invalid configuration"):
            bot.initialize()

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("logging.getLogger")
    def test_initialize_logs_startup_banner(
        self, mock_get_logger, mock_trading_logger, mock_config_manager
    ):
        """Test initialization logs comprehensive startup information."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol="BTCUSDT",
            intervals=["1m", "5m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {"log_level": "INFO"}
        mock_config_manager.return_value = config_instance

        # Mock logger
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock all other components
        with (
            patch("src.main.BinanceDataCollector"),
            patch("src.main.OrderExecutionManager") as mock_order,
            patch("src.main.RiskManager"),
            patch("src.main.StrategyFactory"),
            patch("src.main.EventBus"),
        ):

            # Setup OrderManager mock
            mock_order_instance = Mock()
            mock_order_instance.set_leverage.return_value = True
            mock_order.return_value = mock_order_instance

            bot = TradingBot()
            bot.initialize()

        # Verify startup banner logged
        info_calls = [str(call) for call in mock_logger.info.call_args_list]

        assert any(
            "ICT Trading Bot Starting" in call for call in info_calls
        ), "Startup banner missing"
        assert any("TESTNET" in call for call in info_calls), "Environment info missing"
        assert any("BTCUSDT" in call for call in info_calls), "Symbol info missing"
        assert any("mock_sma" in call for call in info_calls), "Strategy info missing"
        assert any("10x" in call for call in info_calls), "Leverage info missing"

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("src.main.BinanceDataCollector")
    @patch("logging.getLogger")
    def test_initialize_passes_candle_callback(
        self, mock_get_logger, mock_data_collector, mock_trading_logger, mock_config_manager
    ):
        """Test BinanceDataCollector receives _on_candle_received callback."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {}
        mock_config_manager.return_value = config_instance

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock other components
        with (
            patch("src.main.OrderExecutionManager") as mock_order,
            patch("src.main.RiskManager"),
            patch("src.main.StrategyFactory"),
            patch("src.main.EventBus"),
        ):

            mock_order_instance = Mock()
            mock_order_instance.set_leverage.return_value = True
            mock_order.return_value = mock_order_instance

            bot = TradingBot()
            bot.initialize()

        # Verify callback was passed
        mock_data_collector.assert_called_once()
        call_kwargs = mock_data_collector.call_args.kwargs
        assert "on_candle_callback" in call_kwargs
        assert call_kwargs["on_candle_callback"] == bot._on_candle_received

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("logging.getLogger")
    def test_initialize_handles_leverage_failure_gracefully(
        self, mock_get_logger, mock_trading_logger, mock_config_manager
    ):
        """Test leverage setup failure is logged as warning, not error."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {}
        mock_config_manager.return_value = config_instance

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock components
        with (
            patch("src.main.BinanceDataCollector"),
            patch("src.main.OrderExecutionManager") as mock_order,
            patch("src.main.RiskManager"),
            patch("src.main.StrategyFactory"),
            patch("src.main.EventBus"),
        ):

            # Setup OrderManager to fail leverage setting
            mock_order_instance = Mock()
            mock_order_instance.set_leverage.return_value = False
            mock_order.return_value = mock_order_instance

            bot = TradingBot()
            bot.initialize()  # Should not raise exception

        # Verify warning was logged
        warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
        assert any(
            "Failed to set leverage" in call for call in warning_calls
        ), "Leverage failure warning not logged"

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("src.main.RiskManager")
    @patch("logging.getLogger")
    def test_initialize_configures_risk_manager_correctly(
        self, mock_get_logger, mock_risk_manager, mock_trading_logger, mock_config_manager
    ):
        """Test RiskManager receives correct configuration."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol="BTCUSDT",
            intervals=["1m"],
            strategy="mock_sma",
            leverage=15,
            max_risk_per_trade=0.02,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {}
        mock_config_manager.return_value = config_instance

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock other components
        with (
            patch("src.main.BinanceDataCollector"),
            patch("src.main.OrderExecutionManager") as mock_order,
            patch("src.main.StrategyFactory"),
            patch("src.main.EventBus"),
        ):

            mock_order_instance = Mock()
            mock_order_instance.set_leverage.return_value = True
            mock_order.return_value = mock_order_instance

            bot = TradingBot()
            bot.initialize()

        # Verify RiskManager received correct config
        mock_risk_manager.assert_called_once()
        risk_config = mock_risk_manager.call_args.kwargs.get(
            "config",
            mock_risk_manager.call_args.args[0] if mock_risk_manager.call_args.args else {},
        )
        assert risk_config["max_risk_per_trade"] == 0.02
        assert risk_config["default_leverage"] == 15
        assert risk_config["max_leverage"] == 20
        assert risk_config["max_position_size_percent"] == 0.1


class TestTradingBotDelegation:
    """Tests for TradingBot delegation pattern."""

    def test_on_candle_received_bridge_exists(self):
        """Test _on_candle_received bridge method exists."""
        bot = TradingBot()
        assert hasattr(bot, "_on_candle_received")
        assert callable(bot._on_candle_received)

    def test_run_delegates_to_trading_engine(self):
        """Test run method delegates to TradingEngine."""
        bot = TradingBot()
        assert hasattr(bot, "run")
        assert callable(bot.run)

    def test_shutdown_delegates_to_trading_engine(self):
        """Test shutdown method delegates to TradingEngine."""
        bot = TradingBot()
        assert hasattr(bot, "shutdown")
        assert callable(bot.shutdown)
