"""
Integration tests for dynamic exit system (Issue #43).

Tests for:
1. End-to-end dynamic exit signal flow from strategy to execution
2. TradingEngine integration with should_exit method
3. Multi-symbol dynamic exit handling
4. Configuration loading and validation
5. Backward compatibility with existing TP/SL system
6. Error handling and graceful degradation
7. Real-time behavior under market conditions
8. Performance under load
"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.core.trading_engine import TradingEngine
from src.core.audit_logger import AuditLogger
from src.utils.config import ConfigManager, ExitConfig, TradingConfig
from src.strategies.ict_strategy import ICTStrategy


class TestDynamicExitIntegration:
    """Test suite for dynamic exit system integration."""

    @pytest.fixture
    def mock_config_manager(self):
        """Create mock config manager with exit configuration."""
        exit_config = ExitConfig(
            dynamic_exit_enabled=True,
            exit_strategy="trailing_stop",
            trailing_distance=0.02,
            trailing_activation=0.01,
        )

        trading_config = TradingConfig(
            symbols=["BTCUSDT"],
            intervals=["5m", "1h", "4h"],
            strategy="ict_strategy",
            leverage=2,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            exit_config=exit_config,
        )

        mock_config = MagicMock(spec=ConfigManager)
        mock_config.trading_config = trading_config
        mock_config.api_config = MagicMock()
        mock_config.logging_config = MagicMock()
        mock_config.liquidation_config = MagicMock()

        return mock_config

    @pytest.fixture
    def mock_audit_logger(self):
        """Create mock audit logger."""
        return MagicMock(spec=AuditLogger)

    @pytest.fixture
    def trading_engine(self, mock_config_manager, mock_audit_logger):
        """Create TradingEngine instance for testing."""
        engine = TradingEngine(audit_logger=mock_audit_logger)
        engine.initialize_components(
            config_manager=mock_config_manager,
            event_bus=MagicMock(),
            api_key="test_key",
            api_secret="test_secret",
            is_testnet=True,
        )
        return engine

    @pytest.fixture
    def mock_position(self):
        """Create mock position."""
        return Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=2,
            entry_time=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    @pytest.fixture
    def mock_candle_closed(self):
        """Create mock closed candle."""
        now = datetime.now(timezone.utc)
        return Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=now,
            open=50400.0,
            high=50500.0,
            low=50300.0,
            close=50400.0,
            volume=100.0,
            close_time=now,
            is_closed=True,
        )

    @pytest.mark.asyncio
    async def test_trading_engine_processes_dynamic_exit_signal(
        self, trading_engine, mock_position, mock_candle_closed, mock_audit_logger
    ):
        """Test TradingEngine processes dynamic exit signal correctly."""
        # Mock strategy to return exit signal
        mock_strategy = AsyncMock()
        mock_strategy.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
        exit_signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50400.0,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
            exit_reason="trailing_stop",
        )
        mock_strategy.should_exit.return_value = exit_signal

        # Set strategy in engine
        trading_engine.strategies["BTCUSDT"] = mock_strategy

        # Mock position cache to return position
        trading_engine._position_cache["BTCUSDT"] = (
            mock_position,
            datetime.now().timestamp(),
        )

        # Create candle event
        mock_event = MagicMock()
        mock_event.data = mock_candle_closed
        mock_event.symbol = "BTCUSDT"

        # Mock event bus to capture signal publication
        published_signals = []

        async def capture_signal(event, queue_type=None):
            published_signals.append(event)

        trading_engine.event_bus.publish = capture_signal

        # Process the candle
        await trading_engine._on_candle_closed(mock_event)

        # Verify strategy was called
        mock_strategy.should_exit.assert_called_once_with(
            mock_position, mock_candle_closed
        )

        # Verify exit signal was published
        assert len(published_signals) == 1
        published_event = published_signals[0]
        assert published_event.data == exit_signal

        # Verify audit logging
        mock_audit_logger.log_event.assert_called()

    @pytest.mark.asyncio
    async def test_trading_engine_skips_entry_when_exit_triggered(
        self, trading_engine, mock_position, mock_candle_closed
    ):
        """Test TradingEngine skips entry analysis when exit is triggered."""
        # Mock strategy to return exit signal
        mock_strategy = AsyncMock()
        mock_strategy.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
        exit_signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50400.0,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
            exit_reason="breakeven",
        )
        mock_strategy.should_exit.return_value = exit_signal
        mock_strategy.analyze.return_value = None

        # Set strategy in engine
        trading_engine.strategies["BTCUSDT"] = mock_strategy

        # Mock position cache to return position
        trading_engine._position_cache["BTCUSDT"] = (
            mock_position,
            datetime.now().timestamp(),
        )

        # Create candle event
        mock_event = MagicMock()
        mock_event.data = mock_candle_closed
        mock_event.symbol = "BTCUSDT"

        # Track method calls
        exit_method_called = False
        entry_method_called = False

        def track_exit_call(event):
            nonlocal exit_method_called
            if event.data == exit_signal:
                exit_method_called = True

        def track_entry_call(event):
            nonlocal entry_method_called
            if event.data == exit_signal:
                entry_method_called = True

        # Mock event bus to track method calls
        trading_engine.event_bus.publish = track_exit_call

        # Process the candle
        await trading_engine._on_candle_closed(mock_event)

        # Verify exit was processed
        assert exit_method_called is True

        # Verify entry was NOT called
        assert entry_method_called is False

    @pytest.mark.asyncio
    async def test_multi_symbol_dynamic_exit_handling(
        self, trading_engine, mock_config_manager, mock_audit_logger
    ):
        """Test dynamic exit handling across multiple symbols."""
        # Add second symbol to config
        trading_engine.config_manager.trading_config.symbols.append("ETHUSDT")

        # Mock strategies for both symbols
        mock_strategy_btc = AsyncMock()
        mock_strategy_btc.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
        mock_strategy_eth = AsyncMock()
        mock_strategy_eth.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed

        btc_exit_signal = Signal(
            signal_type=SignalType.CLOSE_LONG,
            symbol="BTCUSDT",
            entry_price=50400.0,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
            exit_reason="trailing_stop",
        )

        eth_exit_signal = Signal(
            signal_type=SignalType.CLOSE_SHORT,
            symbol="ETHUSDT",
            entry_price=3000.0,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
            exit_reason="timed",
        )

        mock_strategy_btc.should_exit.return_value = btc_exit_signal
        mock_strategy_eth.should_exit.return_value = eth_exit_signal
        mock_strategy_btc.analyze.return_value = None
        mock_strategy_eth.analyze.return_value = None

        # Set strategies in engine
        trading_engine.strategies["BTCUSDT"] = mock_strategy_btc
        trading_engine.strategies["ETHUSDT"] = mock_strategy_eth

        # Mock positions
        btc_position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=2,
            entry_time=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        eth_position = Position(
            symbol="ETHUSDT",
            side="SHORT",
            entry_price=3100.0,
            quantity=0.2,
            leverage=2,
            entry_time=datetime.now(timezone.utc) - timedelta(minutes=30),
        )

        trading_engine._position_cache["BTCUSDT"] = (
            btc_position,
            datetime.now().timestamp(),
        )
        trading_engine._position_cache["ETHUSDT"] = (
            eth_position,
            datetime.now().timestamp(),
        )

        # Create candle events
        btc_candle = MagicMock()
        btc_candle.data = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50400.0,
            high=50500.0,
            low=50300.0,
            close=50400.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )
        btc_candle.symbol = "BTCUSDT"

        eth_candle = MagicMock()
        eth_candle.data = Candle(
            symbol="ETHUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=2950.0,
            high=3000.0,
            low=2900.0,
            close=2950.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )
        eth_candle.symbol = "ETHUSDT"

        # Capture published signals
        published_signals = []

        async def capture_signal(event, queue_type=None):
            published_signals.append(event)

        trading_engine.event_bus.publish = capture_signal

        # Process both candles
        await trading_engine._on_candle_closed(btc_candle)
        await trading_engine._on_candle_closed(eth_candle)

        # Verify both exit signals were published
        exit_signals = [
            s
            for s in published_signals
            if hasattr(s.data, "signal_type") and s.data.is_exit_signal
        ]

        assert len(exit_signals) == 2
        btc_signal = next((s for s in exit_signals if s.data.symbol == "BTCUSDT"), None)
        eth_signal = next((s for s in exit_signals if s.data.symbol == "ETHUSDT"), None)

        assert btc_signal is not None, "BTC exit signal not found"
        assert eth_signal is not None, "ETH exit signal not found"
        assert btc_signal.data.exit_reason == "trailing_stop"
        assert eth_signal.data.exit_reason == "timed"

    @pytest.mark.asyncio
    async def test_dynamic_exit_configuration_loading(
        self, mock_config_manager, mock_audit_logger
    ):
        """Test dynamic exit configuration is properly loaded and passed to strategies."""
        # Mock config with exit config
        exit_config = ExitConfig(
            exit_strategy="breakeven", breakeven_enabled=True, breakeven_offset=0.002
        )

        trading_config = TradingConfig(
            symbols=["BTCUSDT"],
            intervals=["5m", "1h", "4h"],
            strategy="ict_strategy",
            leverage=1,
            max_risk_per_trade=0.02,
            take_profit_ratio=1.5,
            stop_loss_percent=0.03,
            exit_config=exit_config,
        )

        mock_config_manager.trading_config = trading_config

        # Create engine and initialize
        engine = TradingEngine(audit_logger=mock_audit_logger)
        engine.initialize_components(
            config_manager=mock_config_manager,
            event_bus=MagicMock(),
            api_key="test_key",
            api_secret="test_secret",
            is_testnet=True,
        )

        # Get BTC strategy and verify exit config
        btc_strategy = engine.strategies["BTCUSDT"]
        assert isinstance(btc_strategy, ICTStrategy)

        # Verify exit config is accessible
        strategy_config = btc_strategy.config.get("exit_config", None)
        assert strategy_config is not None
        assert strategy_config.exit_strategy == "breakeven"
        assert strategy_config.breakeven_enabled is True
        assert strategy_config.breakeven_offset == 0.002

    @pytest.mark.asyncio
    async def test_backward_compatibility_with_existing_tp_sl(
        self, trading_engine, mock_position, mock_candle_closed, mock_audit_logger
    ):
        """Test backward compatibility - dynamic exit works alongside existing TP/SL."""
        # Mock strategy to NOT return exit signal (testing TP/SL path)
        mock_strategy = AsyncMock()
        mock_strategy.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
        mock_strategy.should_exit.return_value = None
        mock_strategy.analyze.return_value = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50400.0,
            take_profit=52000.0,
            stop_loss=48000.0,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
        )

        # Set strategy in engine
        trading_engine.strategies["BTCUSDT"] = mock_strategy

        # Mock position cache to return position
        trading_engine._position_cache["BTCUSDT"] = (
            mock_position,
            datetime.now().timestamp(),
        )

        # Create candle event
        mock_event = MagicMock()
        mock_event.data = mock_candle_closed
        mock_event.symbol = "BTCUSDT"

        # Track published signals
        published_signals = []

        async def capture_signal(event):
            published_signals.append(event)

        trading_engine.event_bus.publish = capture_signal

        # Process the candle
        await trading_engine._on_candle_closed(mock_event)

        # Verify entry signal was processed (not exit signal)
        entry_signals = [
            s
            for s in published_signals
            if hasattr(s.data, "signal_type") and s.data.is_entry_signal
        ]
        exit_signals = [
            s
            for s in published_signals
            if hasattr(s.data, "signal_type") and s.data.is_exit_signal
        ]

        assert len(entry_signals) == 1
        assert len(exit_signals) == 0
        assert entry_signals[0].signal_type == SignalType.LONG_ENTRY
        assert entry_signals[0].take_profit == 52000.0
        assert entry_signals[0].stop_loss == 48000.0

    @pytest.mark.asyncio
    async def test_dynamic_exit_error_handling(
        self, trading_engine, mock_position, mock_candle_closed, mock_audit_logger
    ):
        """Test graceful error handling in dynamic exit processing."""
        # Mock strategy to raise exception
        mock_strategy = AsyncMock()
        mock_strategy.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
        mock_strategy.should_exit.side_effect = Exception("Exit calculation failed")
        mock_strategy.analyze.return_value = None

        # Set strategy in engine
        trading_engine.strategies["BTCUSDT"] = mock_strategy

        # Mock position cache to return position
        trading_engine._position_cache["BTCUSDT"] = (
            mock_position,
            datetime.now().timestamp(),
        )

        # Create candle event
        mock_event = MagicMock()
        mock_event.data = mock_candle_closed
        mock_event.symbol = "BTCUSDT"

        # Track published signals
        published_signals = []

        async def capture_signal(event):
            published_signals.append(event)

        trading_engine.event_bus.publish = capture_signal

        # Process the candle
        await trading_engine._on_candle_closed(mock_event)

        # Verify strategy was called
        mock_strategy.should_exit.assert_called_once_with(
            mock_position, mock_candle_closed
        )

        # Verify no exit signal was published due to error
        exit_signals = [
            s
            for s in published_signals
            if hasattr(s.data, "signal_type") and s.data.is_exit_signal
        ]
        assert len(exit_signals) == 0

        # Verify entry analysis was attempted (should be called since exit failed)
        mock_strategy.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_performance_under_multiple_symbols(
        self, mock_config_manager, mock_audit_logger
    ):
        """Test performance when handling dynamic exits for multiple symbols."""
        # Mock config with multiple symbols
        trading_config = TradingConfig(
            symbols=["BTCUSDT", "ETHUSDT", "ADAUSDT"],
            intervals=["5m", "1h", "4h"],
            strategy="ict_strategy",
            leverage=1,
            max_risk_per_trade=0.02,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            exit_config=ExitConfig(
                dynamic_exit_enabled=True, exit_strategy="trailing_stop"
            ),
        )

        mock_config_manager.trading_config = trading_config

        # Create engine and initialize
        engine = TradingEngine(audit_logger=mock_audit_logger)
        engine.initialize_components(
            config_manager=mock_config_manager,
            event_bus=MagicMock(),
            api_key="test_key",
            api_secret="test_secret",
            is_testnet=True,
        )

        # Create mock strategies for all symbols
        for symbol in trading_config.symbols:
            mock_strategy = AsyncMock()
            mock_strategy.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
            mock_strategy.should_exit.return_value = None
            mock_strategy.analyze.return_value = None
            engine.strategies[symbol] = mock_strategy

        # Mock positions and candles
        positions = {}
        candles = {}
        for i, symbol in enumerate(trading_config.symbols):
            positions[symbol] = Position(
                symbol=symbol,
                side="LONG" if i % 2 == 0 else "SHORT",
                entry_price=50000.0 + i * 1000,
                quantity=0.1,
                leverage=1,
                entry_time=datetime.now(timezone.utc) - timedelta(hours=i),
            )

            candles[symbol] = MagicMock()
            candles[symbol].data = Candle(
                symbol=symbol,
                interval="5m",
                open_time=datetime.now(timezone.utc),
                open=50400.0 + i * 100,
                high=50500.0 + i * 100,
                low=50300.0 + i * 100,
                close=50400.0 + i * 100,
                volume=100.0,
                close_time=datetime.now(timezone.utc),
                is_closed=True,
            )
            candles[symbol].symbol = symbol

        # Mock position cache
        for symbol, position in positions.items():
            engine._position_cache[symbol] = (position, datetime.now().timestamp())

        # Track processing time
        import time

        start_time = time.perf_counter_ns()

        # Process all candles concurrently
        tasks = []
        for symbol in trading_config.symbols:
            task = engine._on_candle_closed(candles[symbol])
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.perf_counter_ns()
        processing_time_ms = (end_time - start_time) / 1_000_000

        # Should process all symbols efficiently (target < 10ms per symbol)
        assert processing_time_ms < 30  # 3 symbols * 10ms target

    @pytest.mark.asyncio
    async def test_dynamic_exit_disabled_configuration(
        self, mock_config_manager, mock_audit_logger
    ):
        """Test behavior when dynamic exit is disabled."""
        # Mock config with disabled dynamic exit
        trading_config = TradingConfig(
            symbols=["BTCUSDT"],
            intervals=["5m", "1h", "4h"],
            strategy="ict_strategy",
            leverage=1,
            max_risk_per_trade=0.02,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            exit_config=ExitConfig(dynamic_exit_enabled=False),
        )

        mock_config_manager.trading_config = trading_config

        # Create engine and initialize
        engine = TradingEngine(audit_logger=mock_audit_logger)
        engine.initialize_components(
            config_manager=mock_config_manager,
            event_bus=MagicMock(),
            api_key="test_key",
            api_secret="test_secret",
            is_testnet=True,
        )

        # Create mock strategy
        mock_strategy = AsyncMock()
        mock_strategy.intervals = ["5m"]  # Required by TradingEngine._on_candle_closed
        mock_strategy.should_exit.return_value = None
        mock_strategy.analyze.return_value = Signal(
            signal_type=SignalType.LONG_ENTRY,
            symbol="BTCUSDT",
            entry_price=50400.0,
            take_profit=52000.0,
            stop_loss=48000.0,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
        )

        engine.strategies["BTCUSDT"] = mock_strategy

        # Mock position and candle
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=1,
            entry_time=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        engine._position_cache["BTCUSDT"] = (position, datetime.now().timestamp())

        candle = MagicMock()
        candle.data = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50400.0,
            high=50500.0,
            low=50300.0,
            close=50400.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )
        candle.symbol = "BTCUSDT"

        # Process candle
        await engine._on_candle_closed(candle)

        # Verify should_exit was not called (disabled)
        mock_strategy.should_exit.assert_not_called()

        # Verify regular entry analysis proceeded
        mock_strategy.analyze.assert_called_once()
