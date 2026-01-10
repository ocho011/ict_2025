"""
Integration tests for Multi-Timeframe strategy (Issue #7 Phase 4).

Tests buffer isolation, interval filtering, and fail-fast validation
in realistic scenarios with ICTStrategy + TradingEngine integration.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from src.core.exceptions import ConfigurationError
from src.core.trading_engine import TradingEngine
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.strategies.ict_strategy import ICTStrategy


@pytest.fixture
def mock_config_manager():
    """Create mock ConfigManager with MTF intervals."""
    mock = Mock()
    mock.trading_config = Mock()
    mock.trading_config.symbol = "BTCUSDT"
    mock.trading_config.intervals = ["5m", "1h", "4h"]  # MTF intervals
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
def trading_engine_with_mtf(mock_config_manager):
    """Create TradingEngine with ICTStrategy configured for MTF."""
    mock_audit_logger = MagicMock()
    engine = TradingEngine(audit_logger=mock_audit_logger)

    # Mock event bus
    engine.event_bus = Mock()
    engine.event_bus.subscribe = Mock()
    engine.event_bus.publish = AsyncMock()

    # Mock config manager
    engine.config_manager = mock_config_manager

    # Create ICTStrategy with MTF config
    strategy_config = {
        "buffer_size": 100,
        "ltf_interval": "5m",
        "mtf_interval": "1h",
        "htf_interval": "4h",
    }
    engine.strategy = ICTStrategy("BTCUSDT", strategy_config)

    # Mock data collector with MTF intervals
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


class TestMTFBufferIsolation:
    """Test that MTF strategy maintains separate buffers per interval."""

    def test_mtf_strategy_has_separate_buffers(self, trading_engine_with_mtf):
        """Verify ICTStrategy creates separate buffers for each interval."""
        strategy = trading_engine_with_mtf.strategy

        # Verify strategy has intervals configured
        assert hasattr(strategy, "intervals")
        assert "5m" in strategy.intervals
        assert "1h" in strategy.intervals
        assert "4h" in strategy.intervals

        # Verify strategy has separate buffers
        assert hasattr(strategy, "buffers")
        assert "5m" in strategy.buffers
        assert "1h" in strategy.buffers
        assert "4h" in strategy.buffers

        # Verify buffers are independent (different objects)
        assert strategy.buffers["5m"] is not strategy.buffers["1h"]
        assert strategy.buffers["1h"] is not strategy.buffers["4h"]
        assert strategy.buffers["5m"] is not strategy.buffers["4h"]

    @pytest.mark.asyncio
    async def test_candles_route_to_correct_buffers(self, trading_engine_with_mtf):
        """Test that candles are routed to the correct interval buffer."""
        strategy = trading_engine_with_mtf.strategy

        # Create candles for different intervals
        candle_5m = Candle(
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

        candle_1h = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc),
            open=50000.0,
            high=51000.0,
            low=49500.0,
            close=50800.0,
            volume=1000.0,
            is_closed=True,
        )

        # Add candles to respective buffers
        strategy.update_buffer(candle_5m)
        strategy.update_buffer(candle_1h)

        # Verify 5m buffer has only 5m candle
        assert len(strategy.buffers["5m"]) == 1
        assert strategy.buffers["5m"][0].interval == "5m"
        assert strategy.buffers["5m"][0].close == 50300.0

        # Verify 1h buffer has only 1h candle
        assert len(strategy.buffers["1h"]) == 1
        assert strategy.buffers["1h"][0].interval == "1h"
        assert strategy.buffers["1h"][0].close == 50800.0

        # Verify 4h buffer is still empty
        assert len(strategy.buffers["4h"]) == 0


class TestMTFFailFastValidation:
    """Test fail-fast validation for strategy-DataCollector compatibility."""

    def test_validation_passes_with_matching_intervals(self):
        """Test validation passes when all strategy intervals are in DataCollector."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Create strategy with ['5m', '1h', '4h']
        strategy_config = {
            "buffer_size": 100,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }
        engine.strategy = ICTStrategy("BTCUSDT", strategy_config)

        # Create DataCollector with matching intervals
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h", "4h"]

        engine.logger = Mock()

        # Validation should pass
        engine._validate_strategy_compatibility()

        # Verify no error raised and info log called
        engine.logger.info.assert_called()
        assert "✅ Strategy-DataCollector compatibility validated" in str(
            engine.logger.info.call_args
        )

    def test_validation_fails_with_missing_intervals(self):
        """Test validation fails when strategy requires intervals not in DataCollector."""
        mock_audit_logger = MagicMock()
        engine = TradingEngine(audit_logger=mock_audit_logger)

        # Create strategy with ['5m', '1h', '4h']
        strategy_config = {
            "buffer_size": 100,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }
        engine.strategy = ICTStrategy("BTCUSDT", strategy_config)

        # Create DataCollector missing '4h' interval
        engine.data_collector = Mock()
        engine.data_collector.intervals = ["5m", "1h"]

        engine.logger = Mock()

        # Validation should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            engine._validate_strategy_compatibility()

        # Verify error message
        assert "'4h'" in str(exc_info.value)
        assert "Missing: ['4h']" in str(exc_info.value)


class TestMTFIntervalFiltering:
    """Test interval filtering in TradingEngine event handlers."""

    @pytest.mark.asyncio
    async def test_processes_required_interval_candles(self, trading_engine_with_mtf):
        """Test that required interval candles are processed."""
        engine = trading_engine_with_mtf
        engine.strategy.analyze = AsyncMock(return_value=None)

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

        # Verify analyze() was called
        engine.strategy.analyze.assert_called_once()

    @pytest.mark.asyncio
    async def test_filters_unrequired_interval_candles(self, trading_engine_with_mtf):
        """Test that unrequired interval candles are filtered."""
        engine = trading_engine_with_mtf
        engine.strategy.analyze = AsyncMock(return_value=None)

        # Modify DataCollector to have extra '15m' interval
        engine.data_collector.intervals = ["5m", "15m", "1h", "4h"]

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

        # Verify debug log
        engine.logger.debug.assert_called()
        assert "Filtering 15m" in str(engine.logger.debug.call_args)


class TestMTFBackfillScenario:
    """Test backfill + real-time streaming scenario."""

    @pytest.mark.asyncio
    async def test_backfill_initializes_all_interval_buffers(self):
        """Test that backfill initializes buffers for all intervals."""
        # Create strategy with MTF config
        strategy_config = {
            "buffer_size": 100,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }
        strategy = ICTStrategy("BTCUSDT", strategy_config)

        # Simulate backfill for each interval
        backfill_5m = [
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
            for i in range(50)
        ]

        backfill_1h = [
            Candle(
                symbol="BTCUSDT",
                interval="1h",
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i * 500,
                high=51000.0 + i * 500,
                low=49500.0 + i * 500,
                close=50800.0 + i * 500,
                volume=1000.0,
                is_closed=True,
            )
            for i in range(50)
        ]

        backfill_4h = [
            Candle(
                symbol="BTCUSDT",
                interval="4h",
                open_time=datetime.now(timezone.utc),
                close_time=datetime.now(timezone.utc),
                open=50000.0 + i * 2000,
                high=52000.0 + i * 2000,
                low=49000.0 + i * 2000,
                close=51500.0 + i * 2000,
                volume=5000.0,
                is_closed=True,
            )
            for i in range(50)
        ]

        # Initialize with historical data
        strategy.initialize_with_historical_data("5m", backfill_5m)
        strategy.initialize_with_historical_data("1h", backfill_1h)
        strategy.initialize_with_historical_data("4h", backfill_4h)

        # Verify all buffers initialized
        assert len(strategy.buffers["5m"]) == 50
        assert len(strategy.buffers["1h"]) == 50
        assert len(strategy.buffers["4h"]) == 50

        # Verify initialization status
        assert strategy.is_ready() is True

        # Verify buffer independence (no cross-contamination)
        assert all(c.interval == "5m" for c in strategy.buffers["5m"])
        assert all(c.interval == "1h" for c in strategy.buffers["1h"])
        assert all(c.interval == "4h" for c in strategy.buffers["4h"])
