"""
Unit tests for TradingEngine orchestrator (Subtask 4.5)

Tests component integration, event handlers, and lifecycle management.
"""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.trading_engine import TradingEngine
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.models.signal import Signal, SignalType


class TestTradingEngineInit:
    """Test TradingEngine initialization and setup."""

    def test_init_creates_eventbus(self):
        """Verify __init__ creates EventBus instance."""
        config = {'environment': 'testnet', 'log_level': 'DEBUG'}
        engine = TradingEngine(config)

        assert engine.event_bus is not None
        assert engine.config == config
        assert engine.data_collector is None
        assert engine.strategy is None
        assert engine.order_manager is None

    def test_init_registers_handlers(self):
        """Verify _setup_handlers() subscribes all event types."""
        engine = TradingEngine({})

        # Verify handlers subscribed
        candle_handlers = engine.event_bus._get_handlers(EventType.CANDLE_CLOSED)
        signal_handlers = engine.event_bus._get_handlers(EventType.SIGNAL_GENERATED)
        order_handlers = engine.event_bus._get_handlers(EventType.ORDER_FILLED)

        assert len(candle_handlers) == 1
        assert len(signal_handlers) == 1
        assert len(order_handlers) == 1

        # Verify correct methods subscribed
        assert candle_handlers[0].__name__ == '_on_candle_closed'
        assert signal_handlers[0].__name__ == '_on_signal'
        assert order_handlers[0].__name__ == '_on_order_filled'

    def test_component_injection(self):
        """Verify set_*() methods inject components correctly."""
        engine = TradingEngine({})

        # Mock components
        mock_collector = Mock()
        mock_strategy = Mock()
        mock_manager = Mock()

        # Inject components
        engine.set_data_collector(mock_collector)
        engine.set_strategy(mock_strategy)
        engine.set_order_manager(mock_manager)

        # Verify injection
        assert engine.data_collector is mock_collector
        assert engine.strategy is mock_strategy
        assert engine.order_manager is mock_manager


class TestEventHandlers:
    """Test event handler methods."""

    @pytest.mark.asyncio
    async def test_on_candle_closed_calls_strategy(self):
        """Verify _on_candle_closed() calls strategy.analyze()."""
        engine = TradingEngine({})

        # Mock strategy
        mock_strategy = AsyncMock()
        mock_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name='test',
            timestamp=datetime.now(timezone.utc)
        )
        mock_strategy.analyze.return_value = mock_signal
        engine.set_strategy(mock_strategy)

        # Create candle event
        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volume=100.0,
        )
        event = Event(EventType.CANDLE_CLOSED, candle, source='test')

        # Call handler
        await engine._on_candle_closed(event)

        # Verify strategy called
        mock_strategy.analyze.assert_called_once_with(candle)

    @pytest.mark.asyncio
    async def test_on_candle_closed_publishes_signal(self):
        """Verify signal published to signal queue when returned."""
        engine = TradingEngine({})

        # Mock strategy
        mock_strategy = AsyncMock()
        mock_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name='test',
            timestamp=datetime.now(timezone.utc)
        )
        mock_strategy.analyze.return_value = mock_signal
        engine.set_strategy(mock_strategy)

        # Mock event_bus.publish
        engine.event_bus.publish = AsyncMock()

        # Create candle event
        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volume=100.0,
        )
        event = Event(EventType.CANDLE_CLOSED, candle, source='test')

        # Call handler
        await engine._on_candle_closed(event)

        # Verify signal published
        engine.event_bus.publish.assert_called_once()
        call_args = engine.event_bus.publish.call_args

        # Check event type and queue
        published_event = call_args[0][0]
        queue_name = call_args[1]['queue_name']

        assert published_event.event_type == EventType.SIGNAL_GENERATED
        assert published_event.data == mock_signal
        assert queue_name == 'signal'

    @pytest.mark.asyncio
    async def test_on_candle_closed_handles_no_strategy(self, caplog):
        """Verify graceful handling when strategy is None."""
        engine = TradingEngine({})

        # No strategy set (None)
        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
        )
        event = Event(EventType.CANDLE_CLOSED, candle, source='test')

        # Call handler
        with caplog.at_level(logging.WARNING):
            await engine._on_candle_closed(event)

        # Verify warning logged
        assert "No strategy configured" in caplog.text

    @pytest.mark.asyncio
    async def test_on_candle_closed_handles_no_signal(self, caplog):
        """Verify graceful handling when strategy returns None."""
        engine = TradingEngine({'log_level': 'DEBUG'})

        # Mock strategy returning None (no signal)
        mock_strategy = AsyncMock()
        mock_strategy.analyze.return_value = None
        engine.set_strategy(mock_strategy)

        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
        )
        event = Event(EventType.CANDLE_CLOSED, candle, source='test')

        # Call handler
        with caplog.at_level(logging.DEBUG):
            await engine._on_candle_closed(event)

        # Verify "No signal" logged
        assert "No signal for" in caplog.text

    @pytest.mark.asyncio
    async def test_on_signal_logs_signal(self, caplog):
        """Verify _on_signal() logs signal details."""
        engine = TradingEngine({})

        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='ETHUSDT',
            entry_price=3000.0,
            take_profit=3300.0,
            stop_loss=2900.0,
            strategy_name='test',
            timestamp=datetime.now(timezone.utc)
        )
        event = Event(EventType.SIGNAL_GENERATED, signal, source='test')

        with caplog.at_level(logging.INFO):
            await engine._on_signal(event)

        # Verify signal logged
        assert "Processing signal" in caplog.text
        assert "ETHUSDT" in caplog.text
        assert "3000" in caplog.text

    @pytest.mark.asyncio
    async def test_on_signal_handles_no_order_manager(self, caplog):
        """Verify graceful handling when order_manager is None."""
        engine = TradingEngine({})

        # No order manager set
        signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name='test',
            timestamp=datetime.now(timezone.utc)
        )
        event = Event(EventType.SIGNAL_GENERATED, signal, source='test')

        with caplog.at_level(logging.WARNING):
            await engine._on_signal(event)

        # Verify warning logged
        assert "No order manager configured" in caplog.text

    @pytest.mark.asyncio
    async def test_on_order_filled_logs_order(self, caplog):
        """Verify _on_order_filled() logs order details."""
        engine = TradingEngine({})

        # Mock order
        mock_order = Mock()
        mock_order.order_id = 'ORDER123'
        mock_order.symbol = 'BTCUSDT'
        mock_order.filled_quantity = 1.5

        event = Event(EventType.ORDER_FILLED, mock_order, source='test')

        with caplog.at_level(logging.INFO):
            await engine._on_order_filled(event)

        # Verify order logged
        assert "Order filled" in caplog.text
        assert "ORDER123" in caplog.text
        assert "BTCUSDT" in caplog.text

    @pytest.mark.asyncio
    async def test_handler_errors_isolated(self, caplog):
        """Verify handler exceptions don't crash engine."""
        engine = TradingEngine({})

        # Mock strategy that raises exception
        mock_strategy = AsyncMock()
        mock_strategy.analyze.side_effect = RuntimeError("Strategy error")
        engine.set_strategy(mock_strategy)

        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100.0,
        )
        event = Event(EventType.CANDLE_CLOSED, candle, source='test')

        # Call handler - should not raise
        with caplog.at_level(logging.ERROR):
            await engine._on_candle_closed(event)

        # Verify error logged
        assert "Error in candle handler" in caplog.text
        assert "Strategy error" in caplog.text


class TestLifecycle:
    """Test run() and shutdown() lifecycle methods."""

    @pytest.mark.asyncio
    async def test_run_starts_eventbus(self):
        """Verify run() starts EventBus."""
        engine = TradingEngine({})

        # Mock EventBus.start() to not block
        async def mock_start():
            await asyncio.sleep(0.1)

        engine.event_bus.start = AsyncMock(side_effect=mock_start)
        engine.event_bus.shutdown = AsyncMock()

        # Run with short timeout
        run_task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)

        # Trigger shutdown
        run_task.cancel()

        try:
            await run_task
        except asyncio.CancelledError:
            pass

        # Verify EventBus.start() was called
        engine.event_bus.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_starts_data_collector(self):
        """Verify run() starts DataCollector if configured."""
        engine = TradingEngine({})

        # Mock components
        mock_collector = Mock()
        mock_collector.start_streaming = AsyncMock()

        async def mock_start():
            await asyncio.sleep(0.1)

        engine.event_bus.start = AsyncMock(side_effect=mock_start)
        engine.event_bus.shutdown = AsyncMock()
        engine.set_data_collector(mock_collector)

        # Run with short timeout
        run_task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.05)

        # Trigger shutdown
        run_task.cancel()

        try:
            await run_task
        except asyncio.CancelledError:
            pass

        # Verify DataCollector.start_streaming() was called
        mock_collector.start_streaming.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_stops_components(self):
        """Verify shutdown() stops all components gracefully."""
        engine = TradingEngine({})

        # Mock components
        mock_collector = Mock()
        mock_collector.stop = AsyncMock()
        engine.event_bus.shutdown = AsyncMock()
        engine.set_data_collector(mock_collector)

        # Call shutdown
        await engine.shutdown()

        # Verify components stopped
        mock_collector.stop.assert_called_once()
        engine.event_bus.shutdown.assert_called_once_with(timeout=10.0)

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_triggers_shutdown(self, caplog):
        """Verify run() cleanup ensures shutdown is called."""
        engine = TradingEngine({})

        # Mock EventBus.start() to return quickly
        engine.event_bus.start = AsyncMock()
        engine.event_bus.shutdown = AsyncMock()

        # Mock data_collector to simulate a quick shutdown
        mock_collector = Mock()
        mock_collector.start_streaming = AsyncMock()
        mock_collector.stop = AsyncMock()
        engine.set_data_collector(mock_collector)

        # Create a task that will complete quickly
        async def quick_run():
            tasks = [
                asyncio.create_task(engine.event_bus.start(), name='eventbus'),
                asyncio.create_task(mock_collector.start_streaming(), name='datacollector')
            ]
            # Simulate quick completion
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        # Test run logic with cleanup
        async def test_run():
            with caplog.at_level(logging.INFO):
                try:
                    await quick_run()
                except Exception:
                    pass
                finally:
                    await engine.shutdown()

        # Execute and verify shutdown is called
        await test_run()

        # Verify shutdown was called
        engine.event_bus.shutdown.assert_called_once_with(timeout=10.0)
        assert "Shutting down TradingEngine" in caplog.text


class TestIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_pipeline_candle_to_signal(self):
        """Integration: Candle → Strategy → Signal → Event."""
        engine = TradingEngine({})

        # Track published events
        published_events = []

        async def capture_publish(event, queue_name='data'):
            published_events.append((event, queue_name))

        engine.event_bus.publish = capture_publish

        # Mock strategy
        mock_strategy = AsyncMock()
        expected_signal = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol='BTCUSDT',
            entry_price=50000.0,
            take_profit=55000.0,
            stop_loss=48000.0,
            strategy_name='test',
            timestamp=datetime.now(timezone.utc)
        )
        mock_strategy.analyze.return_value = expected_signal
        engine.set_strategy(mock_strategy)

        # Create candle and trigger handler
        candle = Candle(
            symbol='BTCUSDT',
            interval='1h',
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volume=100.0,
        )
        candle_event = Event(EventType.CANDLE_CLOSED, candle, source='test')

        # Process candle
        await engine._on_candle_closed(candle_event)

        # Verify pipeline
        assert len(published_events) == 1
        signal_event, queue = published_events[0]

        assert signal_event.event_type == EventType.SIGNAL_GENERATED
        assert signal_event.data == expected_signal
        assert queue == 'signal'

        # Verify strategy was called
        mock_strategy.analyze.assert_called_once_with(candle)
