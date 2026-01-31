"""
Integration tests for Multi-coin trading support (Issue #8 Phase 4).

Tests symbol isolation, unknown symbol validation, max_symbols enforcement,
and multi-strategy management in realistic scenarios with TradingEngine integration.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.core.exceptions import ConfigurationError
from src.core.trading_engine import TradingEngine
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.strategies.ict_strategy import ICTStrategy


@pytest.fixture
def mock_config_manager_multi_symbol():
    """Create mock ConfigManager with multiple symbols."""
    mock = Mock()
    mock.trading_config = Mock()
    mock.trading_config.symbols = ["BTCUSDT", "ETHUSDT"]  # Multi-coin support
    mock.trading_config.intervals = ["5m", "1h", "4h"]
    mock.trading_config.strategy = "ict_strategy"
    mock.trading_config.leverage = 10
    mock.trading_config.margin_type = "CROSSED"
    mock.trading_config.max_risk_per_trade = 0.01
    mock.trading_config.take_profit_ratio = 2.0
    mock.trading_config.stop_loss_percent = 0.02
    mock.trading_config.ict_config = {
        "ltf_interval": "5m",
        "mtf_interval": "1h",
        "htf_interval": "4h",
    }
    return mock


@pytest.fixture
def trading_engine_multi_coin(mock_config_manager_multi_symbol):
    """Create TradingEngine with multiple symbols configured."""
    mock_audit_logger = MagicMock()
    engine = TradingEngine(audit_logger=mock_audit_logger)

    # Mock event bus
    engine.event_bus = Mock()
    engine.event_bus.subscribe = Mock()
    engine.event_bus.publish = AsyncMock()

    # Mock config manager
    engine.config_manager = mock_config_manager_multi_symbol

    # Create strategies for each symbol (simulating initialize_components behavior)
    strategy_config = {
        "buffer_size": 100,
        "ltf_interval": "5m",
        "mtf_interval": "1h",
        "htf_interval": "4h",
    }
    engine.strategies = {
        "BTCUSDT": ICTStrategy("BTCUSDT", strategy_config),
        "ETHUSDT": ICTStrategy("ETHUSDT", strategy_config),
    }

    # Mock data collector with multi-symbol support
    engine.data_collector = Mock()
    engine.data_collector.intervals = ["5m", "1h", "4h"]

    # Mock order manager and risk manager
    engine.order_manager = Mock()
    engine.order_manager.get_position = Mock(return_value=None)
    engine.order_manager.get_account_balance = Mock(return_value=1000.0)

    engine.risk_manager = Mock()
    engine.risk_manager.validate_risk = Mock(return_value=True)

    engine.logger = Mock()

    return engine


class TestMultiSymbolIsolation:
    """Test that each symbol has independent strategy instance and buffers."""

    def test_each_symbol_has_own_strategy_instance(self, trading_engine_multi_coin):
        """Verify each symbol gets its own strategy instance."""
        engine = trading_engine_multi_coin

        # Verify strategies dict has 2 entries
        assert len(engine.strategies) == 2
        assert "BTCUSDT" in engine.strategies
        assert "ETHUSDT" in engine.strategies

        # Verify they are different instances
        assert engine.strategies["BTCUSDT"] is not engine.strategies["ETHUSDT"]

        # Verify each strategy has correct symbol
        assert engine.strategies["BTCUSDT"].symbol == "BTCUSDT"
        assert engine.strategies["ETHUSDT"].symbol == "ETHUSDT"

    def test_each_symbol_has_independent_buffers(self, trading_engine_multi_coin):
        """Verify buffers are completely isolated between symbols."""
        engine = trading_engine_multi_coin

        # Get strategy instances
        btc_strategy = engine.strategies["BTCUSDT"]
        eth_strategy = engine.strategies["ETHUSDT"]

        # Verify each strategy has its own buffers
        assert hasattr(btc_strategy, "buffers")
        assert hasattr(eth_strategy, "buffers")

        # Verify buffers are different objects
        assert btc_strategy.buffers is not eth_strategy.buffers

        # Verify buffer independence for each interval
        for interval in ["5m", "1h", "4h"]:
            assert btc_strategy.buffers[interval] is not eth_strategy.buffers[interval]

    @pytest.mark.asyncio
    async def test_candles_route_to_correct_symbol_buffer(
        self, trading_engine_multi_coin
    ):
        """Test that candles are routed to the correct symbol's buffer."""
        engine = trading_engine_multi_coin

        # Create BTC candle
        btc_candle = Candle(
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

        # Create ETH candle
        eth_candle = Candle(
            symbol="ETHUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=3000.0,
            high=3050.0,
            low=2980.0,
            close=3020.0,
            volume=500.0,
            is_closed=True,
        )

        # Add candles to respective buffers
        # Issue #27: update_buffer() now routes by candle.interval automatically
        engine.strategies["BTCUSDT"].update_buffer(btc_candle)
        engine.strategies["ETHUSDT"].update_buffer(eth_candle)

        # Verify BTC buffer has only BTC candle
        btc_buffer = engine.strategies["BTCUSDT"].buffers["5m"]
        assert len(btc_buffer) == 1
        assert btc_buffer[0].symbol == "BTCUSDT"
        assert btc_buffer[0].close == 50300.0

        # Verify ETH buffer has only ETH candle
        eth_buffer = engine.strategies["ETHUSDT"].buffers["5m"]
        assert len(eth_buffer) == 1
        assert eth_buffer[0].symbol == "ETHUSDT"
        assert eth_buffer[0].close == 3020.0

        # Verify no cross-contamination
        assert btc_buffer[0] is not eth_buffer[0]


class TestUnknownSymbolValidation:
    """Test fail-fast validation for unknown symbols."""

    @pytest.mark.asyncio
    async def test_rejects_unknown_symbol_candle(self, trading_engine_multi_coin):
        """Test that candles from unknown symbols are rejected."""
        engine = trading_engine_multi_coin

        # Create candle for unknown symbol
        unknown_candle = Candle(
            symbol="BNBUSDT",  # Not configured
            interval="5m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=400.0,
            high=410.0,
            low=395.0,
            close=405.0,
            volume=200.0,
            is_closed=True,
        )

        event = Event(EventType.CANDLE_CLOSED, unknown_candle)

        # Process candle (should be rejected)
        await engine._on_candle_closed(event)

        # Verify error log was called
        engine.logger.error.assert_called()
        error_msg = str(engine.logger.error.call_args)
        assert "Unknown symbol" in error_msg
        assert "BNBUSDT" in error_msg

    @pytest.mark.asyncio
    async def test_processes_configured_symbol_candle(self, trading_engine_multi_coin):
        """Test that candles from configured symbols are processed."""
        engine = trading_engine_multi_coin
        engine.strategies["BTCUSDT"].analyze = AsyncMock(return_value=None)

        # Create candle for configured symbol
        btc_candle = Candle(
            symbol="BTCUSDT",  # Configured
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

        event = Event(EventType.CANDLE_CLOSED, btc_candle)

        # Process candle (should be accepted)
        await engine._on_candle_closed(event)

        # Verify analyze() was called on correct strategy
        engine.strategies["BTCUSDT"].analyze.assert_called_once()


class TestMaxSymbolsEnforcement:
    """Test max_symbols limit enforcement (configurable, default=10)."""

    def test_rejects_more_than_10_symbols(self):
        """Test that >10 symbols raises ConfigurationError."""
        from src.utils.config import TradingConfig, ConfigurationError

        # Create config with 11 symbols
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

    def test_accepts_exactly_10_symbols(self):
        """Test that exactly 10 symbols is accepted (boundary case)."""
        from src.utils.config import TradingConfig

        # Create config with 10 symbols
        symbols = [f"SYM{i}USDT" for i in range(10)]

        config = TradingConfig(
            symbols=symbols,
            intervals=["5m"],
            strategy="ict_strategy",
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.02,
            max_symbols=10,  # Default value
        )

        assert len(config.symbols) == 10


class TestMultiStrategyValidation:
    """Test strategy-DataCollector compatibility validation for multi-symbol."""

    def test_validation_passes_with_matching_intervals_multi_symbol(self):
        """Test validation passes when all strategy intervals match DataCollector."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Create strategies for multiple symbols
        strategy_config = {
            "buffer_size": 100,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }
        engine.strategies = {
            "BTCUSDT": ICTStrategy("BTCUSDT", strategy_config),
            "ETHUSDT": ICTStrategy("ETHUSDT", strategy_config),
        }

        # Create DataCollector with matching intervals
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h", "4h"]

        engine.logger = Mock()

        # Validation should pass for all strategies
        engine._validate_strategy_compatibility()

        # Verify info log called
        engine.logger.info.assert_called()
        assert "✅ Strategy-DataCollector compatibility validated" in str(
            engine.logger.info.call_args
        )

    def test_validation_fails_with_missing_intervals_any_symbol(self):
        """Test validation fails if any strategy requires missing intervals."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Create strategies for multiple symbols
        strategy_config = {
            "buffer_size": 100,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }
        engine.strategies = {
            "BTCUSDT": ICTStrategy("BTCUSDT", strategy_config),
            "ETHUSDT": ICTStrategy("ETHUSDT", strategy_config),
        }

        # Create DataCollector missing '4h' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h"]

        engine.logger = Mock()

        # Validation should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            engine._validate_strategy_compatibility()

        # Verify error message includes symbol
        assert "'4h'" in str(exc_info.value)
        assert "Missing: ['4h']" in str(exc_info.value)


class TestMultiCoinBackfillScenario:
    """Test sequential backfill scenario for multiple symbols."""

    @pytest.mark.asyncio
    async def test_backfill_initializes_all_symbols(self):
        """Test that backfill initializes strategies for all symbols."""
        # Create strategies for multiple symbols
        strategy_config = {
            "buffer_size": 100,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }
        btc_strategy = ICTStrategy("BTCUSDT", strategy_config)
        eth_strategy = ICTStrategy("ETHUSDT", strategy_config)

        # Simulate backfill for BTC
        btc_backfill_5m = [
            Candle(
                symbol="BTCUSDT",
                interval="5m",
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i * 100,
                high=50500.0 + i * 100,
                low=49800.0 + i * 100,
                close=50300.0 + i * 100,
                volume=100.0,
                is_closed=True,
            )
            for i in range(20)
        ]

        # Simulate backfill for ETH
        eth_backfill_5m = [
            Candle(
                symbol="ETHUSDT",
                interval="5m",
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=3000.0 + i * 10,
                high=3050.0 + i * 10,
                low=2980.0 + i * 10,
                close=3020.0 + i * 10,
                volume=500.0,
                is_closed=True,
            )
            for i in range(20)
        ]

        # Initialize with historical data
        # Issue #27: Unified signature - initialize_with_historical_data(candles, interval=...)
        btc_strategy.initialize_with_historical_data(btc_backfill_5m, interval="5m")
        eth_strategy.initialize_with_historical_data(eth_backfill_5m, interval="5m")

        # Verify BTC buffers initialized
        assert len(btc_strategy.buffers["5m"]) == 20
        assert all(c.symbol == "BTCUSDT" for c in btc_strategy.buffers["5m"])

        # Verify ETH buffers initialized
        assert len(eth_strategy.buffers["5m"]) == 20
        assert all(c.symbol == "ETHUSDT" for c in eth_strategy.buffers["5m"])

        # Verify buffer independence (no cross-contamination)
        assert (
            btc_strategy.buffers["5m"][0].close != eth_strategy.buffers["5m"][0].close
        )
        assert (
            btc_strategy.buffers["5m"][0].symbol != eth_strategy.buffers["5m"][0].symbol
        )


class TestMultiCoinEventRouting:
    """Test event routing to correct strategy based on symbol."""

    @pytest.mark.asyncio
    async def test_candles_route_to_correct_strategy(self, trading_engine_multi_coin):
        """Test that candles are routed to the correct strategy instance."""
        engine = trading_engine_multi_coin

        # Mock analyze() for both strategies
        engine.strategies["BTCUSDT"].analyze = AsyncMock(return_value=None)
        engine.strategies["ETHUSDT"].analyze = AsyncMock(return_value=None)

        # Create BTC candle
        btc_candle = Candle(
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

        # Create ETH candle
        eth_candle = Candle(
            symbol="ETHUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=3000.0,
            high=3050.0,
            low=2980.0,
            close=3020.0,
            volume=500.0,
            is_closed=True,
        )

        # Process BTC candle
        btc_event = Event(EventType.CANDLE_CLOSED, btc_candle)
        await engine._on_candle_closed(btc_event)

        # Verify only BTC strategy analyze() was called
        engine.strategies["BTCUSDT"].analyze.assert_called_once()
        engine.strategies["ETHUSDT"].analyze.assert_not_called()

        # Reset mocks
        engine.strategies["BTCUSDT"].analyze.reset_mock()
        engine.strategies["ETHUSDT"].analyze.reset_mock()

        # Process ETH candle
        eth_event = Event(EventType.CANDLE_CLOSED, eth_candle)
        await engine._on_candle_closed(eth_event)

        # Verify only ETH strategy analyze() was called
        engine.strategies["ETHUSDT"].analyze.assert_called_once()
        engine.strategies["BTCUSDT"].analyze.assert_not_called()
