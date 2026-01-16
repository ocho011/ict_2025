"""
Unit tests for TradingBot initialization (Subtask 10.1).

Tests the TradingBot class constructor and initialize() method to ensure:
1. Constructor initializes all components to None
2. initialize() sets up all components in correct order
3. Configuration validation works correctly
4. Startup logging is comprehensive
5. Error handling is appropriate
"""

from unittest.mock import Mock, patch, AsyncMock

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
    @pytest.mark.asyncio
    async def test_initialize_with_valid_config(
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
            symbols=["BTCUSDT"],
            intervals=["1m", "5m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
            margin_type="ISOLATED"
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {"log_level": "INFO", "log_dir": "logs"}
        mock_config_manager.return_value = config_instance

        # Setup TradingEngine mock
        mock_engine_instance = mock_trading_engine.return_value
        mock_engine_instance.initialize_strategy_with_backfill = AsyncMock()
        mock_engine_instance.order_manager = Mock()
        mock_engine_instance.data_collector = Mock()
        mock_engine_instance.risk_manager = Mock()

        # Setup OrderManager mock
        mock_order_instance = Mock()
        mock_order_instance.set_leverage.return_value = True
        mock_order_manager.return_value = mock_order_instance

        # Setup logger mock
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Execute
        bot = TradingBot()
        await bot.initialize()

        # Verify initialization sequence
        assert mock_config_manager.called
        assert mock_trading_logger.called
        assert mock_trading_engine.called

        # Verify delegation to initialize_components
        mock_trading_engine_instance = mock_trading_engine.return_value
        mock_trading_engine_instance.initialize_components.assert_called_once()
        
        # Verify components are set from TradingEngine
        assert bot.trading_engine == mock_trading_engine_instance
        assert bot.order_manager == mock_trading_engine_instance.order_manager
        assert bot.data_collector == mock_trading_engine_instance.data_collector
        assert bot.risk_manager == mock_trading_engine_instance.risk_manager

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @pytest.mark.asyncio
    async def test_initialize_fails_with_invalid_config(self, mock_trading_logger, mock_config_manager):
        """Test initialize raises ValueError on invalid config."""
        # Setup ConfigManager to fail validation
        config_instance = Mock()
        config_instance.validate.return_value = False
        mock_config_manager.return_value = config_instance

        bot = TradingBot()

        # Should raise ValueError with helpful message
        with pytest.raises(ValueError, match="Invalid configuration"):
            await bot.initialize()

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("src.main.TradingEngine")
    @patch("logging.getLogger")
    @pytest.mark.asyncio
    async def test_initialize_logs_startup_banner(
        self, mock_get_logger, mock_trading_engine, mock_trading_logger, mock_config_manager
    ):
        """Test initialization logs comprehensive startup information."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbols=["BTCUSDT"],
            intervals=["1m", "5m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
            margin_type="ISOLATED"
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {"log_level": "INFO"}
        mock_config_manager.return_value = config_instance

        # Mock logger
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock TradingEngine instance
        mock_engine_instance = mock_trading_engine.return_value
        mock_engine_instance.initialize_strategy_with_backfill = AsyncMock()

        # Mock all other components
        with (
            patch("src.main.BinanceDataCollector"),
            patch("src.main.OrderExecutionManager") as mock_order,
            patch("src.main.RiskManager"),
            patch("src.main.StrategyFactory"),
            patch("src.main.EventBus"),
            patch("src.main.LiquidationManager"),
        ):

            # Setup OrderManager mock
            mock_order_instance = Mock()
            mock_order_instance.set_leverage.return_value = True
            mock_order.return_value = mock_order_instance

            bot = TradingBot()
            await bot.initialize()

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
    @patch("src.main.TradingEngine")
    @patch("logging.getLogger")
    @pytest.mark.asyncio
    async def test_initialize_passes_candle_callback(
        self, mock_get_logger, mock_trading_engine, mock_trading_logger, mock_config_manager
    ):
        """Test delegation of initialization."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(is_testnet=True)
        config_instance.trading_config = Mock(
            symbols=["BTCUSDT"],
            intervals=["1m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            margin_type="ISOLATED",
            backfill_limit=0
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {}
        mock_config_manager.return_value = config_instance
        
        mock_engine_instance = mock_trading_engine.return_value
        mock_engine_instance.initialize_components = Mock()

        # Execute
        bot = TradingBot()
        await bot.initialize()

        # Verify TradingEngine.initialize_components was called
        mock_engine_instance.initialize_components.assert_called_once()

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("src.main.TradingEngine")
    @patch("logging.getLogger")
    @pytest.mark.asyncio
    async def test_initialize_delegates_to_trading_engine(
        self, mock_get_logger, mock_trading_engine, mock_trading_logger, mock_config_manager
    ):
        """Test delegation to TradingEngine."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key="test_key", api_secret="test_secret", is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbols=["BTCUSDT"],
            intervals=["1m"],
            strategy="mock_sma",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01,
            backfill_limit=100,
            margin_type="ISOLATED"
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {"log_level": "INFO"}
        mock_config_manager.return_value = config_instance

        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger

        # Mock TradingEngine instance components
        mock_engine_instance = mock_trading_engine.return_value
        mock_engine_instance.initialize_strategy_with_backfill = AsyncMock()
        mock_engine_instance.order_manager = Mock()
        mock_engine_instance.data_collector = Mock()
        mock_engine_instance.risk_manager = Mock()

        # Execute
        bot = TradingBot()
        await bot.initialize()

        # Verify TradingEngine.initialize_components was called with correct args
        mock_engine_instance.initialize_components.assert_called_once_with(
            config_manager=config_instance,
            event_bus=bot.event_bus,
            api_key="test_key",
            api_secret="test_secret",
            is_testnet=True
        )

    @patch("src.main.ConfigManager")
    @patch("src.main.TradingLogger")
    @patch("src.main.TradingEngine")
    @patch("logging.getLogger")
    @pytest.mark.asyncio
    async def test_initialize_with_backfill(
        self, mock_get_logger, mock_trading_engine, mock_trading_logger, mock_config_manager
    ):
        """Test strategy initialization with backfill."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(is_testnet=True)
        config_instance.trading_config = Mock(
            symbols=["BTCUSDT"],
            intervals=["1m"],
            strategy="mock_sma",
            leverage=10,
            backfill_limit=100,
            margin_type="ISOLATED",
            max_risk_per_trade=0.01
        )
        config_instance.logging_config = Mock()
        config_instance.logging_config.__dict__ = {"log_level": "INFO"}
        mock_config_manager.return_value = config_instance

        mock_engine_instance = mock_trading_engine.return_value
        mock_engine_instance.initialize_strategy_with_backfill = AsyncMock()

        # Execute
        bot = TradingBot()
        await bot.initialize()

        # Verify backfill was called
        mock_engine_instance.initialize_strategy_with_backfill.assert_called_once_with(limit=100)


class TestTradingBotDelegation:
    """Tests for TradingBot delegation pattern."""

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
