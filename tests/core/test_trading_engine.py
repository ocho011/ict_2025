"""
Unit tests for TradingEngine orchestrator (Subtask 4.5 - Updated for Phase 1 & 2)

Tests component integration, event handlers, and lifecycle management with
Separation of Concerns pattern.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from src.core.trading_engine import TradingEngine
from src.models.candle import Candle
from src.models.event import Event, EventType, QueueType
from src.models.signal import Signal, SignalType


@pytest.fixture
def trading_engine():
    """Create TradingEngine with mocked components."""
    mock_audit_logger = MagicMock()
    engine = TradingEngine(audit_logger=mock_audit_logger)

    # Mock all required components
    engine.event_bus = Mock()
    engine.event_bus.subscribe = Mock()
    engine.event_bus.publish = AsyncMock()
    engine.event_bus.start = AsyncMock()
    engine.event_bus.shutdown = AsyncMock()

    engine.data_collector = Mock()
    engine.data_collector.intervals = ["1h"]
    engine.data_collector.start_streaming = AsyncMock()
    engine.data_collector.stop = AsyncMock()

    engine.strategy = AsyncMock()
    engine.strategies = {"BTCUSDT": engine.strategy, "ETHUSDT": AsyncMock()}

    engine.order_manager = Mock()
    engine.order_manager.get_position = Mock(return_value=None)
    engine.order_manager.get_account_balance = Mock(return_value=1000.0)
    engine.order_manager.execute_signal = Mock(
        return_value=(Mock(order_id="TEST123", quantity=0.1), [])
    )

    engine.risk_manager = Mock()
    engine.risk_manager.validate_risk = Mock(return_value=True)
    engine.risk_manager.calculate_position_size = Mock(return_value=0.1)

    engine.config_manager = Mock()
    engine.config_manager.trading_config = Mock(leverage=10)

    engine.logger = Mock()

    # Mock trading_bot (required by run() method)
    engine.trading_bot = Mock()
    engine.trading_bot.set_event_loop = Mock()

    return engine


class TestTradingEngineInit:
    """Test TradingEngine initialization and setup (Updated for Issue #5)."""

    def test_init_creates_empty_components(self):
        """Verify __init__ creates placeholders for components."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        assert engine.event_bus is None
        assert engine.data_collector is None
        assert not engine.strategies
        assert engine.order_manager is None
        assert engine.risk_manager is None
        assert engine.config_manager is None
        assert engine._running is False

    def test_set_components_injects_all_dependencies(self):
        """Verify set_components() injects all required components (DEPRECATED)."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Create mocks
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()
        mock_collector = Mock()
        mock_strategy = Mock()
        mock_order_manager = Mock()
        mock_risk_manager = Mock()
        mock_config_manager = Mock()

        # Inject components (without trading_bot - removed in Issue #5)
        engine.set_components(
            event_bus=mock_event_bus,
            data_collector=mock_collector,
            strategy=mock_strategy,
            order_manager=mock_order_manager,
            risk_manager=mock_risk_manager,
            config_manager=mock_config_manager,
        )

        # Verify injection
        assert engine.event_bus is mock_event_bus
        assert engine.data_collector is mock_collector
        assert engine.strategy is mock_strategy
        assert engine.order_manager is mock_order_manager
        assert engine.risk_manager is mock_risk_manager
        assert engine.config_manager is mock_config_manager

    def test_set_components_registers_handlers(self):
        """Verify set_components() registers event handlers (DEPRECATED)."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Create mock EventBus
        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()

        # Inject components (without trading_bot - removed in Issue #5)
        engine.set_components(
            event_bus=mock_event_bus,
            data_collector=Mock(),
            strategy=Mock(),
            order_manager=Mock(),
            risk_manager=Mock(),
            config_manager=Mock(),
        )

        # Verify handlers subscribed
        assert mock_event_bus.subscribe.call_count == 3

        # Verify correct event types registered
        subscribe_calls = mock_event_bus.subscribe.call_args_list
        event_types = [call[0][0] for call in subscribe_calls]

        assert EventType.CANDLE_CLOSED in event_types
        assert EventType.SIGNAL_GENERATED in event_types
        assert EventType.ORDER_FILLED in event_types


class TestEventHandlers:
    """Test event handler methods."""

    @pytest.mark.asyncio
    async def test_on_candle_closed_calls_strategy(self, trading_engine):
        """Verify _on_candle_closed() calls strategy.analyze()."""
        # Mock strategy to return signal
        mock_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        trading_engine.strategy.analyze.return_value = mock_signal

        # Create candle event
        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volume=100.0,
            is_closed=True,
        )
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler
        await trading_engine._on_candle_closed(event)

        # Verify strategy called
        trading_engine.strategy.analyze.assert_called_once_with(candle)

    @pytest.mark.asyncio
    async def test_on_candle_closed_publishes_signal(self, trading_engine):
        """Verify signal published to signal queue when returned."""
        # Mock strategy to return signal
        mock_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        trading_engine.strategy.analyze.return_value = mock_signal

        # Create candle event
        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volume=100.0,
            is_closed=True,
        )
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler
        await trading_engine._on_candle_closed(event)

        # Verify signal published
        trading_engine.event_bus.publish.assert_called_once()
        call_args = trading_engine.event_bus.publish.call_args

        # Check event type and queue
        published_event = call_args[0][0]
        queue_type = call_args[1]["queue_type"]

        assert published_event.event_type == EventType.SIGNAL_GENERATED
        assert published_event.data == mock_signal
        assert queue_type == QueueType.SIGNAL

    @pytest.mark.asyncio
    async def test_on_candle_closed_handles_no_signal(self, trading_engine):
        """Verify graceful handling when strategy returns None."""
        # Mock strategy returning None (no signal)
        trading_engine.strategy.analyze.return_value = None

        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            is_closed=True,
        )
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler
        await trading_engine._on_candle_closed(event)

        # Verify no signal published
        trading_engine.event_bus.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_signal_generated_validates_and_executes(self, trading_engine):
        """Verify _on_signal_generated() validates and executes signal."""
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="ETHUSDT",
            entry_price=3000.0,
            take_profit=3300.0,
            stop_loss=2900.0,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)

        # Call handler
        await trading_engine._on_signal_generated(event)

        # Verify risk validation called
        trading_engine.risk_manager.validate_risk.assert_called_once()

        # Verify order execution called
        trading_engine.order_manager.execute_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_signal_generated_rejects_invalid_signals(self, trading_engine):
        """Verify signal rejected when risk validation fails."""
        # Mock risk manager to reject signal
        trading_engine.risk_manager.validate_risk.return_value = False

        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        event = Event(EventType.SIGNAL_GENERATED, signal)

        # Call handler
        await trading_engine._on_signal_generated(event)

        # Verify order NOT executed
        trading_engine.order_manager.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_order_filled_logs_order(self, trading_engine):
        """Verify _on_order_filled() logs order details."""
        # Mock order
        mock_order = Mock()
        mock_order.order_id = "ORDER123"
        mock_order.symbol = "BTCUSDT"
        mock_order.side = Mock(value="BUY")
        mock_order.quantity = 1.5
        mock_order.price = 50000.0

        event = Event(EventType.ORDER_FILLED, mock_order)

        # Call handler
        await trading_engine._on_order_filled(event)

        # Verify logger called with order info
        assert trading_engine.logger.info.called

    @pytest.mark.asyncio
    async def test_handler_errors_isolated(self, trading_engine):
        """Verify handler exceptions don't crash engine."""
        # Mock strategy that raises exception
        trading_engine.strategy.analyze.side_effect = RuntimeError("Strategy error")

        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
            is_closed=True,
        )
        event = Event(EventType.CANDLE_CLOSED, candle)

        # Call handler - should not raise
        await trading_engine._on_candle_closed(event)

        # Verify error logged
        assert trading_engine.logger.error.called


class TestLifecycle:
    """Test run() and shutdown() lifecycle methods."""

    @pytest.mark.asyncio
    async def test_run_starts_eventbus_and_collector(self, trading_engine):
        """Verify run() starts EventBus and DataCollector."""

        # Mock EventBus.start() to return quickly
        async def quick_complete():
            await asyncio.sleep(0.01)

        trading_engine.event_bus.start.side_effect = quick_complete
        trading_engine.data_collector.start_streaming.side_effect = quick_complete

        # Run with timeout
        run_task = asyncio.create_task(trading_engine.run())
        await asyncio.sleep(0.05)

        # Cancel
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass

        # Verify components started
        trading_engine.event_bus.start.assert_called_once()
        trading_engine.data_collector.start_streaming.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_components(self, trading_engine):
        """Verify shutdown() stops all components gracefully."""
        # Set _running to True (simulating running state)
        trading_engine._running = True

        # Call shutdown
        await trading_engine.shutdown()

        # Verify components stopped
        trading_engine.data_collector.stop.assert_called_once()
        trading_engine.event_bus.shutdown.assert_called_once_with(timeout=10.0)

        # Verify _running flag set to False
        assert trading_engine._running is False

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self, trading_engine):
        """Verify shutdown can be called multiple times safely."""
        trading_engine._running = True

        # Call shutdown twice
        await trading_engine.shutdown()
        await trading_engine.shutdown()

        # Verify components only stopped once
        assert trading_engine.data_collector.stop.call_count == 1
        assert trading_engine.event_bus.shutdown.call_count == 1


class TestIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_pipeline_candle_to_order(self, trading_engine):
        """Integration: Candle → Strategy → Signal → RiskManager → Order → Event."""
        # Track published events
        published_events = []

        async def capture_publish(event, queue_type=QueueType.DATA):
            published_events.append((event, queue_type))

        trading_engine.event_bus.publish = capture_publish

        # Mock strategy to return signal
        expected_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name="test",
            timestamp=datetime.now(timezone.utc),
        )
        trading_engine.strategy.analyze.return_value = expected_signal

        # Mock order execution
        mock_order = Mock(order_id="ORDER123", quantity=0.1)
        trading_engine.order_manager.execute_signal.return_value = (mock_order, [])

        # Create candle and trigger handler
        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volume=100.0,
            is_closed=True,
        )
        candle_event = Event(EventType.CANDLE_CLOSED, candle)

        # Process candle → signal
        await trading_engine._on_candle_closed(candle_event)

        # Verify signal published
        assert len(published_events) == 1
        signal_event, queue_type = published_events[0]
        assert signal_event.event_type == EventType.SIGNAL_GENERATED
        assert signal_event.data == expected_signal
        assert queue_type == QueueType.SIGNAL

        # Process signal → order
        await trading_engine._on_signal_generated(signal_event)

        # Verify order published
        assert len(published_events) == 2
        order_event, queue_type = published_events[1]
        assert order_event.event_type == EventType.ORDER_FILLED
        assert order_event.data == mock_order
        assert queue_type == QueueType.ORDER

        # Verify strategy was called
        trading_engine.strategy.analyze.assert_called_once_with(candle)

        # Verify risk validation was called
        trading_engine.risk_manager.validate_risk.assert_called_once()

        # Verify order execution was called
        trading_engine.order_manager.execute_signal.assert_called_once()


class TestStrategyCompatibilityValidation:
    """Test strategy-DataCollector compatibility validation (Issue #7 Phase 2)."""

    def test_validate_mtf_strategy_all_intervals_available(self):
        """Test MTF strategy passes when all required intervals are available."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy
        from src.core.exceptions import ConfigurationError

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = Mock(spec=MultiTimeframeStrategy)
        engine.strategy.intervals = ['5m', '1h', '4h']
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with matching intervals
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '1h', '4h']

        engine.logger = Mock()

        # Validation should pass without exception
        engine._validate_strategy_compatibility()

        # Verify info log was called
        engine.logger.info.assert_called()
        assert "✅ Strategy-DataCollector compatibility validated" in str(
            engine.logger.info.call_args
        )

    def test_validate_mtf_strategy_extra_intervals_ok(self):
        """Test MTF strategy passes when DataCollector has extra intervals."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = Mock(spec=MultiTimeframeStrategy)
        engine.strategy.intervals = ['5m', '1h', '4h']
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with extra '15m' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '15m', '1h', '4h']

        engine.logger = Mock()

        # Validation should pass (extra intervals are OK)
        engine._validate_strategy_compatibility()

        # Verify info log was called
        engine.logger.info.assert_called()

    def test_validate_mtf_strategy_missing_intervals_fails(self):
        """Test MTF strategy fails when required intervals are missing."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy
        from src.core.exceptions import ConfigurationError

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = Mock(spec=MultiTimeframeStrategy)
        engine.strategy.intervals = ['5m', '1h', '4h']
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector missing '4h' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '1h']

        engine.logger = Mock()

        # Validation should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            engine._validate_strategy_compatibility()

        # Verify error message contains missing interval
        assert "'4h'" in str(exc_info.value)
        assert "Missing: ['4h']" in str(exc_info.value)

        # Verify error log was called
        engine.logger.error.assert_called()

    def test_validate_single_interval_strategy_single_collector(self):
        """Test single-interval strategy passes with single-interval DataCollector."""
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock single-interval strategy (BaseStrategy)
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with single interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m']

        engine.logger = Mock()

        # Validation should pass
        engine._validate_strategy_compatibility()

        # Verify info log was called (no warning)
        engine.logger.info.assert_called()
        assert "✅ Strategy-DataCollector compatibility validated" in str(
            engine.logger.info.call_args
        )
        engine.logger.warning.assert_not_called()

    def test_validate_single_interval_strategy_multi_collector_warns(self):
        """Test single-interval strategy warns when DataCollector has multiple intervals."""
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock single-interval strategy (BaseStrategy)
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with multiple intervals (wasteful)
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '1h', '4h']

        engine.logger = Mock()

        # Validation should pass but log warning
        engine._validate_strategy_compatibility()

        # Verify warning log was called
        engine.logger.warning.assert_called()
        assert "⚠️ Single-interval strategy" in str(engine.logger.warning.call_args)
        assert "reduce WebSocket bandwidth" in str(engine.logger.warning.call_args)


class TestInitializationOrder:
    """Test initialization order for fail-fast behavior (Issue #24)."""

    def test_validation_runs_before_event_handler_setup(self):
        """Test validation fails before event handlers are registered."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy
        from src.core.exceptions import ConfigurationError
        from unittest.mock import patch, MagicMock

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock components
        mock_config = MagicMock()
        mock_config.trading_config = MagicMock()
        mock_config.trading_config.symbols = ["BTCUSDT"]
        mock_config.trading_config.intervals = ["5m", "1h"]  # Missing 4h
        mock_config.trading_config.leverage = 10
        mock_config.trading_config.margin_type = "ISOLATED"
        mock_config.trading_config.strategy = "multi_timeframe_ict"
        mock_config.trading_config.take_profit_ratio = 2.0
        mock_config.trading_config.stop_loss_percent = 0.01
        mock_config.trading_config.ict_config = None
        mock_config.trading_config.max_risk_per_trade = 0.02

        mock_event_bus = MagicMock()
        mock_event_bus.subscribe = MagicMock()

        # Patch components that would be created (patch at import location)
        with patch('src.core.binance_service.BinanceServiceClient') as mock_service_cls, \
             patch('src.execution.order_manager.OrderExecutionManager') as mock_order_cls, \
             patch('src.risk.manager.RiskManager') as mock_risk_cls, \
             patch('src.strategies.StrategyFactory.create') as mock_strategy_factory, \
             patch('src.core.data_collector.BinanceDataCollector') as mock_collector_cls:

            # Setup mocks
            mock_service_cls.return_value = MagicMock()
            mock_order_cls.return_value = MagicMock()
            mock_risk_cls.return_value = MagicMock()

            # Create MTF strategy that requires ['5m', '1h', '4h']
            mock_strategy = MagicMock(spec=MultiTimeframeStrategy)
            mock_strategy.intervals = ['5m', '1h', '4h']  # Requires 4h but config only has 5m, 1h
            mock_strategy_factory.return_value = mock_strategy

            # Create DataCollector with intervals from config
            mock_collector = MagicMock()
            mock_collector.intervals = ["5m", "1h"]  # Missing 4h
            mock_collector_cls.return_value = mock_collector

            # Attempt initialization - should fail during validation
            with pytest.raises(ConfigurationError) as exc_info:
                engine.initialize_components(
                    config_manager=mock_config,
                    event_bus=mock_event_bus,
                    api_key="test_key",
                    api_secret="test_secret",
                    is_testnet=True,
                )

            # Verify error message
            assert "'4h'" in str(exc_info.value)
            assert "Missing: ['4h']" in str(exc_info.value)

            # CRITICAL: Verify event handlers were NOT registered
            # (validation failed before _setup_event_handlers() was called)
            mock_event_bus.subscribe.assert_not_called()

    def test_validation_runs_before_api_calls(self):
        """Test validation fails before leverage/margin API calls."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy
        from src.core.exceptions import ConfigurationError
        from unittest.mock import patch, MagicMock

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock components
        mock_config = MagicMock()
        mock_config.trading_config = MagicMock()
        mock_config.trading_config.symbols = ["BTCUSDT"]
        mock_config.trading_config.intervals = ["5m", "1h"]  # Missing 4h
        mock_config.trading_config.leverage = 10
        mock_config.trading_config.margin_type = "ISOLATED"
        mock_config.trading_config.strategy = "multi_timeframe_ict"
        mock_config.trading_config.take_profit_ratio = 2.0
        mock_config.trading_config.stop_loss_percent = 0.01
        mock_config.trading_config.ict_config = None
        mock_config.trading_config.max_risk_per_trade = 0.02

        mock_event_bus = MagicMock()

        # Patch components (patch at import location)
        with patch('src.core.binance_service.BinanceServiceClient') as mock_service_cls, \
             patch('src.execution.order_manager.OrderExecutionManager') as mock_order_cls, \
             patch('src.risk.manager.RiskManager') as mock_risk_cls, \
             patch('src.strategies.StrategyFactory.create') as mock_strategy_factory, \
             patch('src.core.data_collector.BinanceDataCollector') as mock_collector_cls:

            # Setup mocks
            mock_service_cls.return_value = MagicMock()

            mock_order_manager = MagicMock()
            mock_order_manager.set_leverage = MagicMock(return_value=True)
            mock_order_manager.set_margin_type = MagicMock(return_value=True)
            mock_order_cls.return_value = mock_order_manager

            mock_risk_cls.return_value = MagicMock()

            # Create MTF strategy that requires ['5m', '1h', '4h']
            mock_strategy = MagicMock(spec=MultiTimeframeStrategy)
            mock_strategy.intervals = ['5m', '1h', '4h']
            mock_strategy_factory.return_value = mock_strategy

            # Create DataCollector with intervals from config
            mock_collector = MagicMock()
            mock_collector.intervals = ["5m", "1h"]  # Missing 4h
            mock_collector_cls.return_value = mock_collector

            # Attempt initialization - should fail during validation
            with pytest.raises(ConfigurationError):
                engine.initialize_components(
                    config_manager=mock_config,
                    event_bus=mock_event_bus,
                    api_key="test_key",
                    api_secret="test_secret",
                    is_testnet=True,
                )

            # CRITICAL: Verify API calls were NOT made
            # (validation failed before set_leverage/set_margin_type)
            mock_order_manager.set_leverage.assert_not_called()
            mock_order_manager.set_margin_type.assert_not_called()


class TestIntervalFiltering:
    """Test interval filtering in event handlers (Issue #7 Phase 3)."""

    @pytest.mark.asyncio
    async def test_mtf_strategy_processes_required_interval(self):
        """Test MTF strategy processes candles from required intervals."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = AsyncMock(spec=MultiTimeframeStrategy)
        engine.strategy.intervals = ['5m', '1h', '4h']
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '1h', '4h']

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.logger = Mock()

        # Create candle with required interval '5m'
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=50500.0,
            low=49800.0,
            close=50300.0,
            volume=100.0,
            is_closed=True,
        )

        event = Event(EventType.CANDLE_CLOSED, candle)

        # Process candle
        await engine._on_candle_closed(event)

        # Verify analyze() was called (not filtered)
        engine.strategy.analyze.assert_called_once_with(candle)

    @pytest.mark.asyncio
    async def test_mtf_strategy_filters_unrequired_interval(self):
        """Test MTF strategy filters out candles from unrequired intervals."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = AsyncMock(spec=MultiTimeframeStrategy)
        engine.strategy.intervals = ['5m', '1h', '4h']
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with extra '15m' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '15m', '1h', '4h']

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.logger = Mock()

        # Create candle with unrequired interval '15m'
        candle = Candle(
            symbol="BTCUSDT",
            interval="15m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=50500.0,
            low=49800.0,
            close=50300.0,
            volume=100.0,
            is_closed=True,
        )

        event = Event(EventType.CANDLE_CLOSED, candle)

        # Process candle
        await engine._on_candle_closed(event)

        # Verify analyze() was NOT called (filtered)
        engine.strategy.analyze.assert_not_called()

        # Verify debug log was called
        engine.logger.debug.assert_called()
        assert "Filtering 15m candle" in str(engine.logger.debug.call_args)

    @pytest.mark.asyncio
    async def test_single_strategy_processes_first_interval(self):
        """Test single-interval strategy processes first DataCollector interval."""
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock single-interval strategy (BaseStrategy)
        engine.strategy = AsyncMock(spec=BaseStrategy)
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with '5m' as first interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '1h']

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.logger = Mock()

        # Create candle with first interval '5m'
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=50500.0,
            low=49800.0,
            close=50300.0,
            volume=100.0,
            is_closed=True,
        )

        event = Event(EventType.CANDLE_CLOSED, candle)

        # Process candle
        await engine._on_candle_closed(event)

        # Verify analyze() was called (not filtered)
        engine.strategy.analyze.assert_called_once_with(candle)

    @pytest.mark.asyncio
    async def test_single_strategy_filters_non_first_interval(self):
        """Test single-interval strategy filters out non-first intervals."""
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock single-interval strategy (BaseStrategy)
        engine.strategy = AsyncMock(spec=BaseStrategy)
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with '5m' as first interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ['5m', '1h']

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.logger = Mock()

        # Create candle with non-first interval '1h'
        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=50500.0,
            low=49800.0,
            close=50300.0,
            volume=100.0,
            is_closed=True,
        )

        event = Event(EventType.CANDLE_CLOSED, candle)

        # Process candle
        await engine._on_candle_closed(event)

        # Verify analyze() was NOT called (filtered)
        engine.strategy.analyze.assert_not_called()

        # Verify debug log was called
        engine.logger.debug.assert_called()
        assert "Filtering 1h candle" in str(engine.logger.debug.call_args)


class TestBackfillIntervalFix:
    """Tests for Issue #26: Backfill should use strategy.intervals, not data_collector.intervals."""

    @pytest.mark.asyncio
    async def test_mtf_strategy_uses_own_intervals_not_datacollector(self):
        """Test MTF strategy only fetches intervals it actually needs (Issue #26)."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy

        # Setup engine
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Setup data_collector with MORE intervals than strategy needs
        mock_data_collector = Mock()
        mock_data_collector.intervals = ["1m", "5m", "15m", "1h", "4h"]  # System-wide intervals
        mock_data_collector.get_historical_candles = Mock(return_value=[])
        engine.data_collector = mock_data_collector

        # Create MTF strategy that only uses SUBSET of intervals
        mock_strategy = Mock(spec=MultiTimeframeStrategy)
        mock_strategy.intervals = ["5m", "1h", "4h"]  # Strategy only needs these 3
        mock_strategy.initialize_with_historical_data = Mock()

        engine.strategies = {"BTCUSDT": mock_strategy}

        # Execute backfill
        await engine.initialize_strategy_with_backfill(limit=100)

        # Verify get_historical_candles was called ONLY for strategy's intervals
        assert mock_data_collector.get_historical_candles.call_count == 3

        # Verify it was NOT called for "1m" and "15m" (not in strategy.intervals)
        called_intervals = [
            call[1]["interval"] for call in mock_data_collector.get_historical_candles.call_args_list
        ]
        assert called_intervals == ["5m", "1h", "4h"]
        assert "1m" not in called_intervals
        assert "15m" not in called_intervals

    @pytest.mark.asyncio
    async def test_backfill_prevents_unnecessary_api_calls(self):
        """Test backfill reduces API calls when strategy needs fewer intervals (Issue #26)."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy

        # Setup engine
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # DataCollector has 5 intervals (system-wide)
        mock_data_collector = Mock()
        mock_data_collector.intervals = ["1m", "5m", "15m", "1h", "4h"]
        mock_data_collector.get_historical_candles = Mock(return_value=[Mock()])
        engine.data_collector = mock_data_collector

        # Strategy only needs 2 intervals
        mock_strategy = Mock(spec=MultiTimeframeStrategy)
        mock_strategy.intervals = ["5m", "1h"]  # Only 2 out of 5
        mock_strategy.initialize_with_historical_data = Mock()

        engine.strategies = {"BTCUSDT": mock_strategy}

        # Execute backfill
        await engine.initialize_strategy_with_backfill(limit=100)

        # Verify API calls reduced from 5 (data_collector) to 2 (strategy)
        assert mock_data_collector.get_historical_candles.call_count == 2  # Not 5!

        # Verify strategy was initialized with correct intervals
        assert mock_strategy.initialize_with_historical_data.call_count == 2

    @pytest.mark.asyncio
    async def test_backfill_respects_strategy_compatibility_validation(self):
        """Test backfill assumes strategy intervals are subset of data_collector (Issue #26)."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy

        # Setup engine
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # DataCollector has specific intervals
        mock_data_collector = Mock()
        mock_data_collector.intervals = ["1m", "5m", "1h"]
        mock_data_collector.get_historical_candles = Mock(return_value=[Mock()])
        engine.data_collector = mock_data_collector

        # Strategy intervals are SUBSET (validated by _validate_strategy_compatibility earlier)
        mock_strategy = Mock(spec=MultiTimeframeStrategy)
        mock_strategy.intervals = ["5m", "1h"]  # Subset of data_collector.intervals
        mock_strategy.initialize_with_historical_data = Mock()

        engine.strategies = {"BTCUSDT": mock_strategy}

        # Execute backfill (should work because subset is valid)
        await engine.initialize_strategy_with_backfill(limit=100)

        # Verify calls were made for strategy intervals
        called_intervals = [
            call[1]["interval"] for call in mock_data_collector.get_historical_candles.call_args_list
        ]
        assert set(called_intervals) == {"5m", "1h"}
        assert set(called_intervals).issubset(set(mock_data_collector.intervals))
