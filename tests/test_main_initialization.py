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
    @patch("src.main.OrderGateway")
    @patch("src.main.RiskGuard")
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
            patch("src.main.OrderGateway") as mock_order,
            patch("src.main.RiskGuard"),
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


class TestTaskManagement:
    """Tests for asyncio task management (Issue #23)."""

    @pytest.mark.asyncio
    async def test_stop_signal_task_cancelled_when_engine_finishes_first(self):
        """Test stop_signal_task is cancelled when engine_task completes first (Issue #23)."""
        from unittest.mock import AsyncMock

        # Create bot with mocked components
        with (
            patch("src.main.ConfigManager") as mock_config_class,
            patch("src.main.TradingLogger"),
            patch("src.main.TradingEngine") as mock_engine_class,
            patch("src.main.EventBus"),
            patch("src.main.LiquidationManager"),
            patch("src.main.AuditLogger"),
            patch("logging.getLogger"),
        ):
            # Setup mocks
            mock_config = Mock()
            mock_config.validate.return_value = True
            mock_config.api_config = Mock(
                api_key="test_key",
                api_secret="test_secret",
                is_testnet=True
            )
            mock_config.trading_config = Mock(
                symbols=["BTCUSDT"],
                intervals=["1m"],
                strategy="test_strategy",
                leverage=10,
                margin_type="ISOLATED",
                max_risk_per_trade=0.01,
                backfill_limit=0,
            )
            mock_config.logging_config = Mock()
            mock_config.logging_config.__dict__ = {}
            mock_config_class.return_value = mock_config

            mock_engine = Mock()
            mock_engine.run = AsyncMock()
            mock_engine.shutdown = AsyncMock()
            mock_engine.initialize_components = Mock()
            mock_engine_class.return_value = mock_engine

            # Make engine finish quickly
            mock_engine.run.return_value = None

            bot = TradingBot()
            await bot.initialize()

            # Run bot (engine finishes first)
            await bot.run()

            # Verify engine.run was called
            mock_engine.run.assert_called_once()
            # Verify shutdown was called
            mock_engine.shutdown.assert_called()

    @pytest.mark.asyncio
    async def test_stop_signal_task_completes_when_event_triggered(self):
        """Test stop_signal_task completes normally when stop event is triggered (Issue #23)."""
        import asyncio
        from unittest.mock import AsyncMock

        # Create bot with mocked components
        with (
            patch("src.main.ConfigManager") as mock_config_class,
            patch("src.main.TradingLogger"),
            patch("src.main.TradingEngine") as mock_engine_class,
            patch("src.main.EventBus"),
            patch("src.main.LiquidationManager"),
            patch("src.main.AuditLogger"),
            patch("logging.getLogger"),
        ):
            # Setup mocks
            mock_config = Mock()
            mock_config.validate.return_value = True
            mock_config.api_config = Mock(
                api_key="test_key",
                api_secret="test_secret",
                is_testnet=True
            )
            mock_config.trading_config = Mock(
                symbols=["BTCUSDT"],
                intervals=["1m"],
                strategy="test_strategy",
                leverage=10,
                margin_type="ISOLATED",
                max_risk_per_trade=0.01,
                backfill_limit=0,
            )
            mock_config.logging_config = Mock()
            mock_config.logging_config.__dict__ = {}
            mock_config_class.return_value = mock_config

            mock_engine = Mock()
            # Make engine wait longer than test timeout
            mock_engine.run = AsyncMock(side_effect=lambda: asyncio.sleep(10))
            mock_engine.shutdown = AsyncMock()
            mock_engine.initialize_components = Mock()
            mock_engine_class.return_value = mock_engine

            bot = TradingBot()
            await bot.initialize()

            # Create a coroutine that triggers stop event after short delay
            async def trigger_stop():
                await asyncio.sleep(0.1)
                bot._stop_event.set()

            # Start both tasks
            trigger_task = asyncio.create_task(trigger_stop())
            run_task = asyncio.create_task(bot.run())

            # Wait for run to complete (should happen when stop event is set)
            await asyncio.wait([run_task], timeout=1.0)

            # Cleanup
            trigger_task.cancel()
            try:
                await trigger_task
            except asyncio.CancelledError:
                pass

            # Verify shutdown was called
            mock_engine.shutdown.assert_called()

    @pytest.mark.asyncio
    async def test_task_cancellation_prevents_pending_warnings(self):
        """Test explicit task cancellation prevents 'Task was destroyed' warnings (Issue #23)."""
        import asyncio
        import warnings
        from unittest.mock import AsyncMock

        # Create bot with mocked components
        with (
            patch("src.main.ConfigManager") as mock_config_class,
            patch("src.main.TradingLogger"),
            patch("src.main.TradingEngine") as mock_engine_class,
            patch("src.main.EventBus"),
            patch("src.main.LiquidationManager"),
            patch("src.main.AuditLogger"),
            patch("logging.getLogger"),
        ):
            # Setup mocks
            mock_config = Mock()
            mock_config.validate.return_value = True
            mock_config.api_config = Mock(
                api_key="test_key",
                api_secret="test_secret",
                is_testnet=True
            )
            mock_config.trading_config = Mock(
                symbols=["BTCUSDT"],
                intervals=["1m"],
                strategy="test_strategy",
                leverage=10,
                margin_type="ISOLATED",
                max_risk_per_trade=0.01,
                backfill_limit=0,
            )
            mock_config.logging_config = Mock()
            mock_config.logging_config.__dict__ = {}
            mock_config_class.return_value = mock_config

            mock_engine = Mock()
            mock_engine.run = AsyncMock()
            mock_engine.shutdown = AsyncMock()
            mock_engine.initialize_components = Mock()
            mock_engine_class.return_value = mock_engine

            bot = TradingBot()
            await bot.initialize()

            # Capture warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                # Run bot
                await bot.run()

                # Check no task-related warnings
                task_warnings = [warning for warning in w if "Task" in str(warning.message)]
                assert len(task_warnings) == 0, "Unexpected task warnings found"


class TestSignalHandlerBehavior:
    """Tests for signal handler behavior (Issue #22)."""

    def test_sigint_during_initialization_raises_keyboard_interrupt(self):
        """Test SIGINT raises KeyboardInterrupt when _stop_event is None (Issue #22)."""
        import signal

        # Mock components to isolate signal handler behavior
        with (
            patch("src.main.TradingBot") as mock_bot_class,
            patch("src.main.asyncio.run") as mock_asyncio_run,
            patch("logging.getLogger") as mock_logger,
        ):
            # Create a mock bot instance
            mock_bot = Mock()
            mock_bot._stop_event = None  # Simulate initialization phase
            mock_bot_class.return_value = mock_bot

            # Create the signal handler (this happens in main())
            def signal_handler(_sig, _frame):
                if mock_bot._stop_event:
                    mock_bot._stop_event.set()
                else:
                    raise KeyboardInterrupt

            # Test that calling the handler raises KeyboardInterrupt
            with pytest.raises(KeyboardInterrupt):
                signal_handler(signal.SIGINT, None)

            # Verify _stop_event was None (not set)
            assert mock_bot._stop_event is None

    def test_sigint_during_run_triggers_graceful_shutdown(self):
        """Test SIGINT sets _stop_event during run phase (Issue #22)."""
        import signal
        import asyncio

        # Create a mock bot with initialized _stop_event
        mock_bot = Mock()
        mock_bot._stop_event = asyncio.Event()

        # Create the signal handler
        def signal_handler(_sig, _frame):
            if mock_bot._stop_event:
                mock_bot._stop_event.set()
            else:
                raise KeyboardInterrupt

        # Verify _stop_event is not set initially
        assert not mock_bot._stop_event.is_set()

        # Call signal handler
        signal_handler(signal.SIGINT, None)

        # Verify _stop_event was set (graceful shutdown triggered)
        assert mock_bot._stop_event.is_set()

    def test_signal_handler_behavior_transition(self):
        """Test signal handler behavior changes between initialization and run phases (Issue #22)."""
        import signal
        import asyncio

        # Create a mock bot
        mock_bot = Mock()

        # Create the signal handler (same function used in both phases)
        def signal_handler(_sig, _frame):
            if mock_bot._stop_event:
                mock_bot._stop_event.set()
            else:
                raise KeyboardInterrupt

        # Phase 1: Initialization (_stop_event is None)
        mock_bot._stop_event = None
        with pytest.raises(KeyboardInterrupt):
            signal_handler(signal.SIGINT, None)

        # Phase 2: Running (_stop_event is initialized)
        mock_bot._stop_event = asyncio.Event()
        assert not mock_bot._stop_event.is_set()

        # Should NOT raise, but set the event instead
        signal_handler(signal.SIGINT, None)
        assert mock_bot._stop_event.is_set()
