"""
Unit tests for TradingEngine orchestrator (Updated for Issue #110 refactor)

Tests component integration, event handlers, and lifecycle management with
delegated modules (PositionCacheManager, TradeCoordinator, EventDispatcher).
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.core.trading_engine import TradingEngine
from src.core.exceptions import EngineState
from src.models.candle import Candle
from src.models.event import Event, EventType, QueueType
from src.models.signal import Signal, SignalType


@pytest.fixture
def trading_engine():
    """Create TradingEngine with mocked components and extracted modules."""
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
    # Issue #27: All strategies have intervals attribute (unified interface)
    engine.strategy.intervals = ["1h"]
    eth_strategy = AsyncMock()
    eth_strategy.intervals = ["1h"]
    engine.strategies = {"BTCUSDT": engine.strategy, "ETHUSDT": eth_strategy}

    engine.order_gateway = Mock()
    engine.order_gateway.get_position = Mock(return_value=None)
    engine.order_gateway.get_account_balance = Mock(return_value=1000.0)
    engine.order_gateway.execute_signal = Mock(
        return_value=(Mock(order_id="TEST123", quantity=0.1), [])
    )

    engine.risk_guard = Mock()
    engine.risk_guard.validate_risk = Mock(return_value=True)
    engine.risk_guard.calculate_position_size = Mock(return_value=0.1)

    engine.config_manager = Mock()
    engine.config_manager.trading_config = Mock(leverage=10)

    # Create extracted modules with the mocked components (Issue #110)
    from src.core.position_cache_manager import PositionCacheManager
    from src.execution.trade_coordinator import TradeCoordinator
    from src.core.event_dispatcher import EventDispatcher

    engine.position_cache_manager = PositionCacheManager(
        order_gateway=engine.order_gateway,
        config_manager=engine.config_manager,
    )

    engine.trade_coordinator = TradeCoordinator(
        order_gateway=engine.order_gateway,
        risk_guard=engine.risk_guard,
        config_manager=engine.config_manager,
        audit_logger=mock_audit_logger,
        position_cache_manager=engine.position_cache_manager,
    )

    engine.event_dispatcher = EventDispatcher(
        strategies=engine.strategies,
        position_cache_manager=engine.position_cache_manager,
        event_bus=engine.event_bus,
        audit_logger=mock_audit_logger,
        order_gateway=engine.order_gateway,
        engine_state_getter=lambda: engine._engine_state,
        event_loop_getter=lambda: engine._event_loop,
        log_live_data=True,
    )

    engine.logger = Mock()

    # Mock trading_bot (required by run() method)
    engine.trading_bot = Mock()
    engine.trading_bot.set_event_loop = Mock()

    return engine


class TestTradingEngineInit:
    """Test TradingEngine initialization and setup (Updated for Issue #110)."""

    def test_init_creates_empty_components(self):
        """Verify __init__ creates placeholders for components."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        assert engine.event_bus is None
        assert engine.data_collector is None
        assert not engine.strategies
        assert engine.order_gateway is None
        assert engine.risk_guard is None
        assert engine.config_manager is None
        assert engine._running is False

        # Issue #110: Extracted modules start as None
        assert engine.position_cache_manager is None
        assert engine.trade_coordinator is None
        assert engine.event_dispatcher is None

    @patch("src.core.binance_service.BinanceServiceClient")
    @patch("src.execution.order_gateway.OrderGateway")
    @patch("src.risk.risk_guard.RiskGuard")
    @patch("src.strategies.StrategyFactory.create_composed")
    @patch("src.strategies.module_config_builder.build_module_config")
    @patch("src.core.data_collector.BinanceDataCollector")
    def test_initialize_components_success(
        self,
        mock_collector_cls,
        mock_build_module_config,
        mock_strategy_factory,
        mock_risk_cls,
        mock_order_cls,
        mock_service_cls,
    ):
        """Verify initialize_components() creates and wires all components."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock dependencies
        mock_config_manager = Mock()
        mock_config_manager.trading_config = Mock()
        mock_config_manager.trading_config.symbols = ["BTCUSDT"]
        mock_config_manager.trading_config.intervals = ["1h"]
        mock_config_manager.trading_config.leverage = 10
        mock_config_manager.trading_config.margin_type = "ISOLATED"
        mock_config_manager.trading_config.strategy = "ict"
        mock_config_manager.trading_config.take_profit_ratio = 2.0
        mock_config_manager.trading_config.stop_loss_percent = 0.01
        mock_config_manager.trading_config.ict_config = {"use_killzones": True}
        mock_config_manager.trading_config.max_risk_per_trade = 0.02
        mock_config_manager.trading_config.exit_config = MagicMock()

        mock_event_bus = Mock()
        mock_event_bus.subscribe = Mock()

        # Mock component instances
        mock_service = Mock()
        mock_service_cls.return_value = mock_service

        mock_order_gateway = Mock()
        mock_order_gateway.set_leverage = Mock(return_value=True)
        mock_order_gateway.set_margin_type = Mock(return_value=True)
        mock_order_cls.return_value = mock_order_gateway

        mock_risk_guard = Mock()
        mock_risk_cls.return_value = mock_risk_guard

        mock_strategy = Mock()
        # Ensure strategy intervals match config so validation passes
        mock_strategy.intervals = ["1h"]
        mock_build_module_config.return_value = (MagicMock(), ["1h"], 1.5)
        mock_strategy_factory.return_value = mock_strategy

        mock_collector = Mock()
        mock_collector.intervals = ["1h"]
        mock_collector_cls.return_value = mock_collector

        # Initialize
        engine.initialize_components(
            config_manager=mock_config_manager,
            event_bus=mock_event_bus,
            api_key="test_key",
            api_secret="test_secret",
            is_testnet=True,
        )

        # Verify components stored
        assert engine.config_manager is mock_config_manager
        assert engine.event_bus is mock_event_bus
        assert engine.order_gateway is mock_order_gateway
        assert engine.risk_guard is mock_risk_guard
        assert engine.data_collector is mock_collector
        assert engine.strategies["BTCUSDT"] is mock_strategy

        # Issue #110: Verify extracted modules created
        assert engine.position_cache_manager is not None
        assert engine.trade_coordinator is not None
        assert engine.event_dispatcher is not None

        # Verify handlers registered (4 handlers: CANDLE_CLOSED, SIGNAL_GENERATED,
        # ORDER_FILLED, ORDER_PARTIALLY_FILLED - Issue #97)
        assert mock_event_bus.subscribe.call_count == 4

        # Verify API configuration calls
        mock_order_gateway.set_leverage.assert_called_with("BTCUSDT", 10)
        mock_order_gateway.set_margin_type.assert_called_with("BTCUSDT", "ISOLATED")


class TestEventHandlers:
    """Test event handler methods (delegated via Issue #110)."""

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

        # Call handler (delegates to EventDispatcher)
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

        # Call handler (delegates to TradeCoordinator)
        await trading_engine._on_signal_generated(event)

        # Verify risk validation called
        trading_engine.risk_guard.validate_risk.assert_called_once()

        # Verify order execution called
        trading_engine.order_gateway.execute_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_signal_generated_rejects_invalid_signals(self, trading_engine):
        """Verify signal rejected when risk validation fails."""
        # Mock risk manager to reject signal
        trading_engine.risk_guard.validate_risk.return_value = False

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
        trading_engine.order_gateway.execute_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_order_filled_logs_order(self, trading_engine):
        """Verify _on_order_filled() logs order details."""
        # Mock order
        mock_order = Mock()
        mock_order.order_id = "ORDER123"
        mock_order.symbol = "BTCUSDT"
        mock_order.side = Mock(value="BUY")
        mock_order.order_type = Mock(value="MARKET")
        mock_order.quantity = 1.5
        mock_order.price = 50000.0
        mock_order.filled_quantity = 1.5

        event = Event(EventType.ORDER_FILLED, mock_order)

        # Call handler (delegates to TradeCoordinator)
        await trading_engine._on_order_filled(event)

        # TradeCoordinator has its own logger - verify it ran without error
        # (the mock order_type needs to support 'in' check for OrderType enum)

    @pytest.mark.asyncio
    async def test_on_order_partially_filled_tracks_entry_data(self, trading_engine):
        """Test that partial fill handler updates position entry data (Issue #97)."""
        from src.models.order import Order, OrderType, OrderSide, OrderStatus

        # Create a partial fill order
        partial_order = Order(
            order_id="123456",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            filled_quantity=0.5,  # Half filled
            price=50000.0,
            status=OrderStatus.PARTIALLY_FILLED,
        )

        event = Event(
            event_type=EventType.ORDER_PARTIALLY_FILLED,
            data=partial_order,
        )

        # Process the partial fill event (delegates to TradeCoordinator)
        await trading_engine._on_order_partially_filled(event)

        # Verify position entry data was tracked (via backward-compat property)
        assert "BTCUSDT" in trading_engine._position_entry_data
        entry_data = trading_engine._position_entry_data["BTCUSDT"]
        assert entry_data.entry_price == 50000.0
        assert entry_data.quantity == 0.5  # Should use filled_quantity, not total
        assert entry_data.side == "LONG"  # BUY = LONG

    def test_on_order_fill_from_websocket_publishes_filled_event(self, trading_engine):
        """Verify _on_order_fill_from_websocket() creates Order/Event and publishes to EventBus (Issue #107)."""
        import asyncio
        from src.models.order import Order, OrderType, OrderSide, OrderStatus

        # Setup event loop mock
        mock_loop = Mock()
        mock_future = Mock()
        mock_loop.call_soon_threadsafe = Mock()
        trading_engine._event_loop = mock_loop

        # Raw order data as received from Binance WebSocket
        order_data = {
            "s": "BTCUSDT",
            "i": 123456789,
            "S": "BUY",
            "ot": "TAKE_PROFIT_MARKET",
            "q": "1.0",
            "ap": "50000.0",
            "sp": "49500.0",
            "X": "FILLED",
            "z": "1.0",
        }

        # Mock asyncio.run_coroutine_threadsafe
        with patch("src.core.trading_engine.asyncio.run_coroutine_threadsafe", return_value=mock_future) as mock_rcts:
            trading_engine._on_order_fill_from_websocket(order_data)

            # Verify run_coroutine_threadsafe was called
            mock_rcts.assert_called_once()
            call_args = mock_rcts.call_args

            # Verify it was called with the mock event loop
            assert call_args[0][1] is mock_loop

        # Verify logger info was called
        trading_engine.logger.info.assert_called()
        log_message = str(trading_engine.logger.info.call_args)
        assert "ORDER_FILLED" in log_message
        assert "BTCUSDT" in log_message

    def test_on_order_fill_from_websocket_handles_partial_fill(self, trading_engine):
        """Verify _on_order_fill_from_websocket() handles PARTIALLY_FILLED status (Issue #107)."""
        import asyncio

        mock_loop = Mock()
        trading_engine._event_loop = mock_loop

        order_data = {
            "s": "ETHUSDT",
            "i": 987654321,
            "S": "SELL",
            "ot": "MARKET",
            "q": "10.0",
            "ap": "3000.0",
            "sp": "0",
            "X": "PARTIALLY_FILLED",
            "z": "5.0",
        }

        with patch("src.core.trading_engine.asyncio.run_coroutine_threadsafe") as mock_rcts:
            trading_engine._on_order_fill_from_websocket(order_data)
            mock_rcts.assert_called_once()

        log_message = str(trading_engine.logger.info.call_args)
        assert "ORDER_PARTIALLY_FILLED" in log_message
        assert "ETHUSDT" in log_message

    def test_on_order_fill_from_websocket_no_event_loop(self, trading_engine):
        """Verify _on_order_fill_from_websocket() warns when event loop not available (Issue #107)."""
        trading_engine._event_loop = None

        order_data = {
            "s": "BTCUSDT",
            "i": 123456789,
            "S": "BUY",
            "ot": "MARKET",
            "q": "1.0",
            "ap": "50000.0",
            "sp": "0",
            "X": "FILLED",
            "z": "1.0",
        }

        trading_engine._on_order_fill_from_websocket(order_data)

        # Verify warning was logged
        trading_engine.logger.warning.assert_called()
        warning_message = str(trading_engine.logger.warning.call_args)
        assert "Event loop not available" in warning_message

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

        # EventDispatcher has its own logger - error is isolated


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
    """End-to-end integration tests (Issue #110: tests delegate flow)."""

    @pytest.mark.asyncio
    async def test_full_pipeline_candle_to_order(self, trading_engine):
        """Integration: Candle → Strategy → Signal → RiskGuard → Order → Event."""
        # Track published events
        published_events = []

        async def capture_publish(event, queue_type=QueueType.CANDLE_UPDATE):
            published_events.append((event, queue_type))

        trading_engine.event_bus.publish = capture_publish
        # Also update EventDispatcher's reference to event_bus
        trading_engine.event_dispatcher._event_bus = trading_engine.event_bus

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
        trading_engine.order_gateway.execute_signal.return_value = (mock_order, [])

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

        # Process candle → signal (via EventDispatcher)
        await trading_engine._on_candle_closed(candle_event)

        # Verify signal published
        assert len(published_events) == 1
        signal_event, queue_type = published_events[0]
        assert signal_event.event_type == EventType.SIGNAL_GENERATED
        assert signal_event.data == expected_signal
        assert queue_type == QueueType.SIGNAL

        # Process signal → order (via TradeCoordinator)
        await trading_engine._on_signal_generated(signal_event)

        # After Issue #97: ORDER_FILLED events come from WebSocket confirmation,
        # not from signal processing. Only SIGNAL_GENERATED is published here.
        assert len(published_events) == 1

        # Verify strategy was called
        trading_engine.strategy.analyze.assert_called_once_with(candle)

        # Verify risk validation was called
        trading_engine.risk_guard.validate_risk.assert_called_once()

        # Verify order execution was called
        trading_engine.order_gateway.execute_signal.assert_called_once()


class TestStrategyCompatibilityValidation:
    """Test strategy-DataCollector compatibility validation (Issue #7 Phase 2)."""

    def test_validate_mtf_strategy_all_intervals_available(self):
        """Test strategy passes when all required intervals are available."""
        from src.strategies.base import BaseStrategy
        from src.core.exceptions import ConfigurationError

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock strategy with intervals ['5m', '1h', '4h']
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m", "1h", "4h"]
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with matching intervals
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h", "4h"]

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
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m", "1h", "4h"]
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with extra '15m' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "15m", "1h", "4h"]

        engine.logger = Mock()

        # Validation should pass (extra intervals are OK)
        engine._validate_strategy_compatibility()

        # Verify info log was called
        engine.logger.info.assert_called()

    def test_validate_mtf_strategy_missing_intervals_fails(self):
        """Test MTF strategy fails when required intervals are missing."""
        from src.strategies.base import BaseStrategy
        from src.core.exceptions import ConfigurationError

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m", "1h", "4h"]
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector missing '4h' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h"]

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
        """Test single-interval strategy passes with single-interval DataCollector.

        Issue #27: All strategies now have intervals attribute (unified interface).
        """
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock single-interval strategy (BaseStrategy)
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m"]
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with single interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m"]

        engine.logger = Mock()

        # Validation should pass
        engine._validate_strategy_compatibility()

        # Verify info log was called (no warning)
        engine.logger.info.assert_called()
        assert "✅ Strategy-DataCollector compatibility validated" in str(
            engine.logger.info.call_args
        )

    def test_validate_single_interval_strategy_multi_collector_passes(self):
        """Test single-interval strategy passes when DataCollector has multiple intervals.

        Issue #27: No more warning for unused intervals - validation now unified.
        """
        from src.strategies.base import BaseStrategy

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock single-interval strategy (BaseStrategy)
        engine.strategy = Mock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m"]
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with multiple intervals
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h", "4h"]

        engine.logger = Mock()

        # Validation should pass
        engine._validate_strategy_compatibility()

        # Verify info log was called
        engine.logger.info.assert_called()
        assert "✅ Strategy-DataCollector compatibility validated" in str(
            engine.logger.info.call_args
        )


class TestInitializationOrder:
    """Test initialization order for fail-fast behavior (Issue #24)."""

    def test_validation_runs_before_event_handler_setup(self):
        """Test validation fails before event handlers are registered."""
        from src.strategies.base import BaseStrategy
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
        with (
            patch("src.core.binance_service.BinanceServiceClient") as mock_service_cls,
            patch(
                "src.execution.order_gateway.OrderGateway"
            ) as mock_order_cls,
            patch("src.risk.risk_guard.RiskGuard") as mock_risk_cls,
            patch("src.strategies.module_config_builder.build_module_config") as mock_build_module_config,
            patch("src.strategies.StrategyFactory.create_composed") as mock_strategy_factory,
            patch("src.core.data_collector.BinanceDataCollector") as mock_collector_cls,
        ):
            # Setup mocks
            mock_service_cls.return_value = MagicMock()
            mock_order_cls.return_value = MagicMock()
            mock_risk_cls.return_value = MagicMock()
            mock_build_module_config.return_value = (MagicMock(), ["5m", "1h", "4h"], 1.5)

            # Create MTF strategy that requires ['5m', '1h', '4h']
            mock_strategy = MagicMock(spec=BaseStrategy)
            mock_strategy.intervals = [
                "5m",
                "1h",
                "4h",
            ]  # Requires 4h but config only has 5m, 1h
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
        from src.strategies.base import BaseStrategy
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
        with (
            patch("src.core.binance_service.BinanceServiceClient") as mock_service_cls,
            patch(
                "src.execution.order_gateway.OrderGateway"
            ) as mock_order_cls,
            patch("src.risk.risk_guard.RiskGuard") as mock_risk_cls,
            patch("src.strategies.module_config_builder.build_module_config") as mock_build_module_config,
            patch("src.strategies.StrategyFactory.create_composed") as mock_strategy_factory,
            patch("src.core.data_collector.BinanceDataCollector") as mock_collector_cls,
        ):
            # Setup mocks
            mock_service_cls.return_value = MagicMock()

            mock_order_gateway = MagicMock()
            mock_order_gateway.set_leverage = MagicMock(return_value=True)
            mock_order_gateway.set_margin_type = MagicMock(return_value=True)
            mock_order_cls.return_value = mock_order_gateway

            mock_risk_cls.return_value = MagicMock()
            mock_build_module_config.return_value = (MagicMock(), ["5m", "1h", "4h"], 1.5)

            # Create MTF strategy that requires ['5m', '1h', '4h']
            mock_strategy = MagicMock(spec=BaseStrategy)
            mock_strategy.intervals = ["5m", "1h", "4h"]
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
            mock_order_gateway.set_leverage.assert_not_called()
            mock_order_gateway.set_margin_type.assert_not_called()


class TestIntervalFiltering:
    """Test interval filtering in event handlers (Issue #7 Phase 3, Issue #110)."""

    @pytest.mark.asyncio
    async def test_mtf_strategy_processes_required_interval(self):
        """Test MTF strategy processes candles from required intervals."""
        from src.strategies.base import BaseStrategy
        from src.core.position_cache_manager import PositionCacheManager
        from src.core.event_dispatcher import EventDispatcher

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = AsyncMock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m", "1h", "4h"]
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h", "4h"]

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.order_gateway = Mock()
        engine.order_gateway.get_position.return_value = None
        engine.config_manager = Mock()
        engine.config_manager.trading_config = Mock(leverage=10)
        engine.logger = Mock()

        # Create extracted modules
        engine.position_cache_manager = PositionCacheManager(
            order_gateway=engine.order_gateway,
            config_manager=engine.config_manager,
        )
        engine.event_dispatcher = EventDispatcher(
            strategies=engine.strategies,
            position_cache_manager=engine.position_cache_manager,
            event_bus=engine.event_bus,
            audit_logger=mock_audit_logger,
            order_gateway=engine.order_gateway,
            engine_state_getter=lambda: engine._engine_state,
            event_loop_getter=lambda: engine._event_loop,
        )

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
        from src.strategies.base import BaseStrategy
        from src.core.position_cache_manager import PositionCacheManager
        from src.core.event_dispatcher import EventDispatcher

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock MTF strategy with intervals ['5m', '1h', '4h']
        engine.strategy = AsyncMock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m", "1h", "4h"]
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock DataCollector with extra '15m' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "15m", "1h", "4h"]

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.order_gateway = Mock()
        engine.order_gateway.get_position.return_value = None
        engine.config_manager = Mock()
        engine.config_manager.trading_config = Mock(leverage=10)
        engine.logger = Mock()

        # Create extracted modules
        engine.position_cache_manager = PositionCacheManager(
            order_gateway=engine.order_gateway,
            config_manager=engine.config_manager,
        )
        engine.event_dispatcher = EventDispatcher(
            strategies=engine.strategies,
            position_cache_manager=engine.position_cache_manager,
            event_bus=engine.event_bus,
            audit_logger=mock_audit_logger,
            order_gateway=engine.order_gateway,
            engine_state_getter=lambda: engine._engine_state,
            event_loop_getter=lambda: engine._event_loop,
        )

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

    @pytest.mark.asyncio
    async def test_single_strategy_processes_registered_interval(self):
        """Test single-interval strategy processes intervals it registered."""
        from src.strategies.base import BaseStrategy
        from src.core.position_cache_manager import PositionCacheManager
        from src.core.event_dispatcher import EventDispatcher

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        engine.strategy = AsyncMock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m"]
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h"]

        engine.event_bus = AsyncMock()
        engine.order_gateway = Mock()
        engine.order_gateway.get_position.return_value = None
        engine.config_manager = Mock()
        engine.config_manager.trading_config = Mock(leverage=10)
        engine.logger = Mock()

        engine.position_cache_manager = PositionCacheManager(
            order_gateway=engine.order_gateway,
            config_manager=engine.config_manager,
        )
        engine.event_dispatcher = EventDispatcher(
            strategies=engine.strategies,
            position_cache_manager=engine.position_cache_manager,
            event_bus=engine.event_bus,
            audit_logger=mock_audit_logger,
            order_gateway=engine.order_gateway,
            engine_state_getter=lambda: engine._engine_state,
            event_loop_getter=lambda: engine._event_loop,
        )

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
        await engine._on_candle_closed(event)

        engine.strategy.analyze.assert_called_once_with(candle)

    @pytest.mark.asyncio
    async def test_single_strategy_filters_unregistered_interval(self):
        """Test single-interval strategy filters out intervals not in strategy.intervals."""
        from src.strategies.base import BaseStrategy
        from src.core.position_cache_manager import PositionCacheManager
        from src.core.event_dispatcher import EventDispatcher

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        engine.strategy = AsyncMock(spec=BaseStrategy)
        engine.strategy.intervals = ["5m"]
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h"]

        engine.event_bus = AsyncMock()
        engine.order_gateway = Mock()
        engine.order_gateway.get_position.return_value = None
        engine.config_manager = Mock()
        engine.config_manager.trading_config = Mock(leverage=10)
        engine.logger = Mock()

        engine.position_cache_manager = PositionCacheManager(
            order_gateway=engine.order_gateway,
            config_manager=engine.config_manager,
        )
        engine.event_dispatcher = EventDispatcher(
            strategies=engine.strategies,
            position_cache_manager=engine.position_cache_manager,
            event_bus=engine.event_bus,
            audit_logger=mock_audit_logger,
            order_gateway=engine.order_gateway,
            engine_state_getter=lambda: engine._engine_state,
            event_loop_getter=lambda: engine._event_loop,
        )

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
        await engine._on_candle_closed(event)

        engine.strategy.analyze.assert_not_called()


class TestBackfillIntervalFix:
    """Tests for Issue #26: Backfill should use strategy.intervals, not data_collector.intervals."""

    @pytest.mark.asyncio
    async def test_mtf_strategy_uses_own_intervals_not_datacollector(self):
        """Test MTF strategy only fetches intervals it actually needs (Issue #26)."""
        from src.strategies.base import BaseStrategy

        # Setup engine
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Setup data_collector with MORE intervals than strategy needs
        mock_data_collector = Mock()
        mock_data_collector.intervals = [
            "1m",
            "5m",
            "15m",
            "1h",
            "4h",
        ]  # System-wide intervals
        mock_data_collector.get_historical_candles = Mock(return_value=[])
        engine.data_collector = mock_data_collector

        # Create MTF strategy that only uses SUBSET of intervals
        mock_strategy = Mock(spec=BaseStrategy)
        mock_strategy.intervals = ["5m", "1h", "4h"]  # Strategy only needs these 3
        mock_strategy.initialize_with_historical_data = Mock()

        engine.strategies = {"BTCUSDT": mock_strategy}

        # Execute backfill
        await engine.initialize_strategy_with_backfill(limit=100)

        # Verify get_historical_candles was called ONLY for strategy's intervals
        assert mock_data_collector.get_historical_candles.call_count == 3

        # Verify it was NOT called for "1m" and "15m" (not in strategy.intervals)
        called_intervals = [
            call[1]["interval"]
            for call in mock_data_collector.get_historical_candles.call_args_list
        ]
        assert called_intervals == ["5m", "1h", "4h"]
        assert "1m" not in called_intervals
        assert "15m" not in called_intervals

    @pytest.mark.asyncio
    async def test_backfill_prevents_unnecessary_api_calls(self):
        """Test backfill reduces API calls when strategy needs fewer intervals (Issue #26)."""
        from src.strategies.base import BaseStrategy

        # Setup engine
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # DataCollector has 5 intervals (system-wide)
        mock_data_collector = Mock()
        mock_data_collector.intervals = ["1m", "5m", "15m", "1h", "4h"]
        mock_data_collector.get_historical_candles = Mock(return_value=[Mock()])
        engine.data_collector = mock_data_collector

        # Strategy only needs 2 intervals
        mock_strategy = Mock(spec=BaseStrategy)
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
        from src.strategies.base import BaseStrategy

        # Setup engine
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # DataCollector has specific intervals
        mock_data_collector = Mock()
        mock_data_collector.intervals = ["1m", "5m", "1h"]
        mock_data_collector.get_historical_candles = Mock(return_value=[Mock()])
        engine.data_collector = mock_data_collector

        # Strategy intervals are SUBSET (validated by _validate_strategy_compatibility earlier)
        mock_strategy = Mock(spec=BaseStrategy)
        mock_strategy.intervals = ["5m", "1h"]  # Subset of data_collector.intervals
        mock_strategy.initialize_with_historical_data = Mock()

        engine.strategies = {"BTCUSDT": mock_strategy}

        # Execute backfill (should work because subset is valid)
        await engine.initialize_strategy_with_backfill(limit=100)

        # Verify calls were made for strategy intervals
        called_intervals = [
            call[1]["interval"]
            for call in mock_data_collector.get_historical_candles.call_args_list
        ]
        assert set(called_intervals) == {"5m", "1h"}
        assert set(called_intervals).issubset(set(mock_data_collector.intervals))


class TestIssue41PositionUncertainty:
    """Tests for Issue #41: Handle uncertain position state gracefully (Issue #110)."""

    @pytest.mark.asyncio
    async def test_on_candle_closed_skips_on_position_refresh_failure(self):
        """Verify _on_candle_closed() skips analysis when position refresh fails."""
        from src.core.position_cache_manager import PositionCacheManager
        from src.core.event_dispatcher import EventDispatcher

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock strategy
        engine.strategy = AsyncMock()
        engine.strategy.intervals = ["1h"]
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock OrderManager to RAISE an exception on get_position
        engine.order_gateway = Mock()
        engine.order_gateway.get_position.side_effect = Exception(
            "API Connection Error"
        )

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.config_manager = Mock()
        engine.config_manager.trading_config = Mock(leverage=10)
        engine.logger = Mock()

        # Create extracted modules
        engine.position_cache_manager = PositionCacheManager(
            order_gateway=engine.order_gateway,
            config_manager=engine.config_manager,
        )
        engine.event_dispatcher = EventDispatcher(
            strategies=engine.strategies,
            position_cache_manager=engine.position_cache_manager,
            event_bus=engine.event_bus,
            audit_logger=mock_audit_logger,
            order_gateway=engine.order_gateway,
            engine_state_getter=lambda: engine._engine_state,
            event_loop_getter=lambda: engine._event_loop,
        )

        # Create candle
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

        # Process candle - should skip analysis because refresh fails and returns None
        await engine._on_candle_closed(event)

        # Verify strategy.analyze() was NEVER called
        engine.strategy.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_candle_closed_proceeds_on_confirmed_no_position(self):
        """Verify _on_candle_closed() proceeds when position state is confirmed (None)."""
        from src.core.position_cache_manager import PositionCacheManager
        from src.core.event_dispatcher import EventDispatcher

        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Mock strategy
        engine.strategy = AsyncMock()
        engine.strategy.intervals = ["1h"]
        engine.strategy.analyze = AsyncMock(return_value=None)
        engine.strategies = {"BTCUSDT": engine.strategy}

        # Mock OrderManager to return None (No position)
        engine.order_gateway = Mock()
        engine.order_gateway.get_position.return_value = None

        # Mock other components
        engine.event_bus = AsyncMock()
        engine.config_manager = Mock()
        engine.config_manager.trading_config = Mock(leverage=10)
        engine.logger = Mock()

        # Create extracted modules
        engine.position_cache_manager = PositionCacheManager(
            order_gateway=engine.order_gateway,
            config_manager=engine.config_manager,
        )
        engine.event_dispatcher = EventDispatcher(
            strategies=engine.strategies,
            position_cache_manager=engine.position_cache_manager,
            event_bus=engine.event_bus,
            audit_logger=mock_audit_logger,
            order_gateway=engine.order_gateway,
            engine_state_getter=lambda: engine._engine_state,
            event_loop_getter=lambda: engine._event_loop,
        )

        # Create candle
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

        # Process candle - should proceed to analysis
        await engine._on_candle_closed(event)

        # Verify strategy.analyze() WAS called
        engine.strategy.analyze.assert_called_once_with(candle)


class TestIssue110ExtractedModules:
    """Test Issue #110 specific: extracted module integration."""

    def test_engine_state_imported_from_exceptions(self):
        """Verify EngineState is imported from exceptions module."""
        from src.core.exceptions import EngineState as ExceptionsEngineState
        from src.core.trading_engine import EngineState as EngineEngineState

        # Should be the same class (re-exported)
        assert ExceptionsEngineState is EngineEngineState

    def test_on_candle_received_delegates_to_event_dispatcher(self, trading_engine):
        """Verify on_candle_received delegates to EventDispatcher."""
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

        # Mock event_dispatcher.on_candle_received
        trading_engine.event_dispatcher.on_candle_received = Mock()

        trading_engine.on_candle_received(candle)

        trading_engine.event_dispatcher.on_candle_received.assert_called_once_with(candle)

    def test_position_update_delegates_to_position_cache(self, trading_engine):
        """Verify _on_position_update_from_websocket delegates to PositionCacheManager."""
        trading_engine.position_cache_manager.update_from_websocket = Mock()

        mock_updates = [Mock()]
        trading_engine._on_position_update_from_websocket(mock_updates)

        trading_engine.position_cache_manager.update_from_websocket.assert_called_once_with(
            position_updates=mock_updates,
            allowed_symbols=set(trading_engine.strategies.keys()),
        )

    def test_backward_compat_position_cache_property(self, trading_engine):
        """Verify backward-compatible _position_cache property works."""
        # The property should return the position_cache's internal dict
        assert trading_engine._position_cache is trading_engine.position_cache_manager.cache

    def test_backward_compat_position_entry_data_property(self, trading_engine):
        """Verify backward-compatible _position_entry_data property works."""
        # The property should return trade_executor's entry data dict
        assert trading_engine._position_entry_data is trading_engine.trade_coordinator._position_entry_data
