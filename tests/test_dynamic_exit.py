"""
Comprehensive unit tests for dynamic exit strategies (Issue #43).

Tests for:
1. ExitConfig validation and parameter validation
2. ICT Strategy trailing stop exit logic
3. ICT Strategy breakeven exit logic
4. ICT Strategy timed exit logic
5. ICT Strategy indicator-based exit logic
6. Integration with ExitConfig and strategy initialization
7. Edge cases and error handling
8. Performance and real-time behavior
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.models.candle import Candle
from src.models.position import Position
from src.models.signal import Signal, SignalType
from src.strategies.ict_strategy import ICTStrategy
from src.utils.config import ExitConfig


class TestExitConfig:
    """Test suite for ExitConfig validation and functionality."""

    def test_default_config_values(self):
        """Test default ExitConfig values are valid."""
        config = ExitConfig()

        assert config.dynamic_exit_enabled is True
        assert config.exit_strategy == "trailing_stop"
        assert config.trailing_distance == 0.02
        assert config.trailing_activation == 0.01
        assert config.breakeven_enabled is True
        assert config.breakeven_offset == 0.001
        assert config.timeout_enabled is False
        assert config.timeout_minutes == 240
        assert config.volatility_enabled is False
        assert config.atr_period == 14
        assert config.atr_multiplier == 2.0

    def test_valid_trailing_stop_config(self):
        """Test valid trailing stop configuration."""
        config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.03,
            trailing_activation=0.02,
        )

        assert config.exit_strategy == "trailing_stop"
        assert config.trailing_distance == 0.03
        assert config.trailing_activation == 0.02

    def test_valid_breakeven_config(self):
        """Test valid breakeven configuration."""
        config = ExitConfig(
            exit_strategy="breakeven", breakeven_enabled=True, breakeven_offset=0.002
        )

        assert config.exit_strategy == "breakeven"
        assert config.breakeven_enabled is True
        assert config.breakeven_offset == 0.002

    def test_valid_timed_config(self):
        """Test valid timed exit configuration."""
        config = ExitConfig(
            exit_strategy="timed", timeout_enabled=True, timeout_minutes=120
        )

        assert config.exit_strategy == "timed"
        assert config.timeout_enabled is True
        assert config.timeout_minutes == 120

    def test_invalid_exit_strategy(self):
        """Test invalid exit strategy raises error."""
        with pytest.raises(ValueError, match="Invalid exit strategy"):
            ExitConfig(exit_strategy="invalid_strategy")

    def test_invalid_trailing_distance(self):
        """Test invalid trailing distance raises error."""
        # Test too small
        with pytest.raises(ValueError, match="trailing_distance must be 0.001-0.1"):
            ExitConfig(trailing_distance=0.0005)

        # Test too large
        with pytest.raises(ValueError, match="trailing_distance must be 0.001-0.1"):
            ExitConfig(trailing_distance=0.2)

    def test_invalid_trailing_activation(self):
        """Test invalid trailing activation raises error."""
        # Test too small
        with pytest.raises(ValueError, match="trailing_activation must be 0.001-0.05"):
            ExitConfig(trailing_activation=0.0005)

        # Test too large
        with pytest.raises(ValueError, match="trailing_activation must be 0.001-0.05"):
            ExitConfig(trailing_activation=0.1)

    def test_invalid_breakeven_offset(self):
        """Test invalid breakeven offset raises error."""
        # Test too small
        with pytest.raises(ValueError, match="breakeven_offset must be 0.0001-0.01"):
            ExitConfig(breakeven_offset=0.00005)

        # Test too large
        with pytest.raises(ValueError, match="breakeven_offset must be 0.0001-0.01"):
            ExitConfig(breakeven_offset=0.02)

    def test_invalid_timeout_minutes(self):
        """Test invalid timeout minutes raises error."""
        # Test too small
        with pytest.raises(ValueError, match="timeout_minutes must be 1-1440"):
            ExitConfig(timeout_minutes=0)

        # Test too large
        with pytest.raises(ValueError, match="timeout_minutes must be 1-1440"):
            ExitConfig(timeout_minutes=2000)

    def test_invalid_atr_period(self):
        """Test invalid ATR period raises error."""
        # Test too small
        with pytest.raises(ValueError, match="atr_period must be 5-100"):
            ExitConfig(atr_period=2)

        # Test too large
        with pytest.raises(ValueError, match="atr_period must be 5-100"):
            ExitConfig(atr_period=200)

    def test_invalid_atr_multiplier(self):
        """Test invalid ATR multiplier raises error."""
        # Test too small
        with pytest.raises(ValueError, match="atr_multiplier must be 0.5-5.0"):
            ExitConfig(atr_multiplier=0.2)

        # Test too large
        with pytest.raises(ValueError, match="atr_multiplier must be 0.5-5.0"):
            ExitConfig(atr_multiplier=10.0)

    def test_inconsistent_trailing_stop_config(self):
        """Test trailing_stop config without distance raises error."""
        with pytest.raises(
            ValueError, match="trailing_stop strategy requires trailing_distance > 0"
        ):
            ExitConfig(exit_strategy="trailing_stop", trailing_distance=0)

    def test_inconsistent_timed_config(self):
        """Test timed config without timeout enabled raises error."""
        with pytest.raises(
            ValueError, match="timed strategy requires timeout_enabled=True"
        ):
            ExitConfig(exit_strategy="timed", timeout_enabled=False)


class TestICTStrategyDynamicExit:
    """Test suite for ICT Strategy dynamic exit logic."""

    @pytest.fixture
    def mock_candle(self):
        """Create mock candle for testing."""
        now = datetime.now(timezone.utc)
        return Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=now,
            open=50000.0,
            high=50500.0,
            low=49500.0,
            close=50200.0,
            volume=100.0,
            close_time=now,
            is_closed=True,
        )

    @pytest.fixture
    def mock_position_long(self):
        """Create mock long position."""
        return Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=10,
            entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    @pytest.fixture
    def mock_position_short(self):
        """Create mock short position."""
        return Position(
            symbol="BTCUSDT",
            side="SHORT",
            entry_price=50000.0,
            quantity=0.1,
            leverage=10,
            entry_time=datetime.now(timezone.utc) - timedelta(hours=2),
        )

    @pytest.fixture
    def ict_strategy_trailing_stop(self):
        """Create ICT strategy with trailing stop configuration."""
        exit_config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.02,
            trailing_activation=0.01,
        )
        return ICTStrategy(
            symbol="BTCUSDT",
            config={
                "exit_config": exit_config,
                "ltf_interval": "5m",
                "mtf_interval": "1h",
                "htf_interval": "4h",
                "swing_lookback": 5,
                "buffer_size": 100,
            },
        )

    @pytest.fixture
    def ict_strategy_breakeven(self):
        """Create ICT strategy with breakeven configuration."""
        exit_config = ExitConfig(
            exit_strategy="breakeven", breakeven_enabled=True, breakeven_offset=0.001
        )
        return ICTStrategy(
            symbol="BTCUSDT",
            config={
                "exit_config": exit_config,
                "ltf_interval": "5m",
                "mtf_interval": "1h",
                "htf_interval": "4h",
                "swing_lookback": 5,
                "buffer_size": 100,
            },
        )

    @pytest.fixture
    def ict_strategy_timed(self):
        """Create ICT strategy with timed exit configuration."""
        exit_config = ExitConfig(
            exit_strategy="timed", timeout_enabled=True, timeout_minutes=60
        )
        return ICTStrategy(
            symbol="BTCUSDT",
            config={
                "exit_config": exit_config,
                "ltf_interval": "5m",
                "mtf_interval": "1h",
                "htf_interval": "4h",
                "swing_lookback": 5,
                "buffer_size": 100,
            },
        )

    @pytest.fixture
    def ict_strategy_indicator_based(self):
        """Create ICT strategy with indicator-based exit configuration."""
        exit_config = ExitConfig(exit_strategy="indicator_based")
        return ICTStrategy(
            symbol="BTCUSDT",
            config={
                "exit_config": exit_config,
                "ltf_interval": "5m",
                "mtf_interval": "1h",
                "htf_interval": "4h",
                "swing_lookback": 5,
                "buffer_size": 100,
            },
        )

    @pytest.fixture
    def ict_strategy_disabled(self):
        """Create ICT strategy with dynamic exit disabled."""
        exit_config = ExitConfig(dynamic_exit_enabled=False)
        return ICTStrategy(
            symbol="BTCUSDT",
            config={
                "exit_config": exit_config,
                "ltf_interval": "5m",
                "mtf_interval": "1h",
                "htf_interval": "4h",
                "swing_lookback": 5,
                "buffer_size": 100,
            },
        )

    @pytest.mark.asyncio
    async def test_trailing_stop_no_exit_long(
        self, ict_strategy_trailing_stop, mock_candle, mock_position_long
    ):
        """Test trailing stop doesn't exit when long position is profitable but below activation."""
        # Price rose 0.4% (above activation threshold of 1%)
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50400.0,  # Up from 50200
            high=50500.0,
            low=50100.0,
            close=50400.0,  # Still below trailing stop
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_long, candle
        )

        assert result is None
        # Should not have moved trailing stop yet (not activated)
        assert result is None

    @pytest.mark.asyncio
    async def test_trailing_stop_activated_long(
        self, ict_strategy_trailing_stop, mock_candle, mock_position_long
    ):
        """Test trailing stop activation and movement for long position."""
        # Price rose 1.5% (above activation threshold of 1%)
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50750.0,  # Up 1.5% - should activate trailing
            high=50800.0,
            low=50600.0,
            close=50750.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_long, candle
        )

        assert result is not None
        assert result.signal_type == SignalType.CLOSE_LONG
        assert result.entry_price == 50750.0
        assert result.exit_reason == "trailing_stop"

    @pytest.mark.asyncio
    async def test_trailing_stop_triggered_long(
        self, ict_strategy_trailing_stop, mock_candle, mock_position_long
    ):
        """Test trailing stop triggered for long position."""
        # Price dropped to hit trailing stop
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=49200.0,  # Below trailing stop (50000 * 0.98 = 49000)
            high=49300.0,
            low=49100.0,
            close=49200.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_long, candle
        )

        assert result is not None
        assert result.signal_type == SignalType.CLOSE_LONG
        assert result.entry_price == 49200.0
        assert result.exit_reason == "trailing_stop"

    @pytest.mark.asyncio
    async def test_trailing_stop_short_position(
        self, ict_strategy_trailing_stop, mock_candle, mock_position_short
    ):
        """Test trailing stop logic for short position."""
        # Price dropped 1.5% (should activate trailing)
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=49500.0,  # Down 1% - should activate trailing
            high=49600.0,
            low=49400.0,
            close=49500.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_short, candle
        )

        assert result is not None
        assert result.signal_type == SignalType.CLOSE_SHORT
        assert result.entry_price == 49500.0
        assert result.exit_reason == "trailing_stop"

    @pytest.mark.asyncio
    async def test_breakeven_activated_long(
        self, ict_strategy_breakeven, mock_candle, mock_position_long
    ):
        """Test breakeven activation for long position."""
        # Price rose above breakeven offset (0.1%)
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50100.0,  # 1% profit (above 0.1% breakeven offset)
            high=50200.0,
            low=50000.0,
            close=50100.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_breakeven.should_exit(mock_position_long, candle)

        assert result is not None
        assert result.signal_type == SignalType.CLOSE_LONG
        assert result.exit_reason == "breakeven"

    @pytest.mark.asyncio
    async def test_breakeven_no_activation_long(
        self, ict_strategy_breakeven, mock_candle, mock_position_long
    ):
        """Test breakeven not activated for long position."""
        # Price rose only 0.05% (below 0.1% breakeven offset)
        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50050.0,  # Only 0.05% profit (below 0.1% breakeven offset)
            high=50100.0,
            low=49950.0,
            close=50050.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_breakeven.should_exit(mock_position_long, candle)

        assert result is None

    @pytest.mark.asyncio
    async def test_timed_exit_triggered(
        self, ict_strategy_timed, mock_candle, mock_position_long
    ):
        """Test timed exit triggered."""
        # Mock position entry time 2 hours ago, timeout is 1 hour
        old_entry_time = datetime.now(timezone.utc) - timedelta(hours=2)
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=10,
            entry_time=old_entry_time,
        )

        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50100.0,
            high=50200.0,
            low=49900.0,
            close=50100.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_timed.should_exit(position, candle)

        assert result is not None
        assert result.signal_type == SignalType.CLOSE_LONG
        assert result.exit_reason == "timed"

    @pytest.mark.asyncio
    async def test_timed_exit_not_triggered(
        self, ict_strategy_timed, mock_candle, mock_position_long
    ):
        """Test timed exit not triggered."""
        # Position entry time 30 minutes ago, timeout is 1 hour
        recent_entry_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        position = Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=50000.0,
            quantity=0.1,
            leverage=10,
            entry_time=recent_entry_time,
        )

        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50100.0,
            high=50200.0,
            low=49900.0,
            close=50100.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_timed.should_exit(position, candle)

        assert result is None

    @pytest.mark.asyncio
    async def test_indicator_based_exit_trend_reversal(
        self, ict_strategy_indicator_based, mock_candle, mock_position_long
    ):
        """Test indicator-based exit on trend reversal."""
        # Mock buffer and indicators to simulate bearish trend reversal
        strategy = ict_strategy_indicator_based

        # Mock indicator cache to return bearish trend
        mock_cache = MagicMock()
        mock_cache.get_market_structure.return_value = type(
            "MockMarketStructure", (), {"trend": "bearish"}
        )()

        with patch.object(strategy, "_indicator_cache", mock_cache):
            # Mock sufficient buffer data
            strategy.buffers[strategy.mtf_interval] = [mock_candle] * 50

            result = await strategy.should_exit(mock_position_long, mock_candle)

            assert result is not None
            assert result.signal_type == SignalType.CLOSE_LONG
            assert result.exit_reason == "htf_trend_reversal"

    @pytest.mark.asyncio
    async def test_disabled_dynamic_exit(
        self, ict_strategy_disabled, mock_candle, mock_position_long
    ):
        """Test dynamic exit disabled returns None."""
        result = await ict_strategy_disabled.should_exit(
            mock_position_long, mock_candle
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_should_exit_ignores_unclosed_candle(
        self, ict_strategy_trailing_stop, mock_position_long
    ):
        """Test should_exit ignores unclosed candles."""
        unclosed_candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=50200.0,
            high=50300.0,
            low=50100.0,
            close=50200.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=False,
        )

        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_long, unclosed_candle
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_should_exit_requires_ready_buffer(
        self, ict_strategy_trailing_stop, mock_position_long
    ):
        """Test should_exit returns None when buffer not ready."""
        strategy = ict_strategy_trailing_stop
        # Mock empty buffer
        strategy.buffers[strategy.ltf_interval].clear()

        result = await strategy.should_exit(mock_position_long, mock_candle)

        assert result is None


class TestExitPerformance:
    """Test suite for dynamic exit performance requirements."""

    @pytest.mark.asyncio
    async def test_exit_evaluation_speed(
        self, ict_strategy_trailing_stop, mock_position_long
    ):
        """Test that exit evaluation meets performance requirements (<1ms)."""
        import time

        candle = Candle(
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

        start_time = time.perf_counter_ns()
        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_long, candle
        )
        end_time = time.perf_counter_ns()

        execution_time_ns = end_time - start_time
        execution_time_ms = execution_time_ns / 1_000_000  # Convert to milliseconds

        # Should complete within 1ms for real-time trading
        assert execution_time_ms < 1.0

    @pytest.mark.asyncio
    async def test_concurrent_exit_calls(
        self, ict_strategy_trailing_stop, mock_position_long
    ):
        """Test that concurrent exit calls are thread-safe."""
        import asyncio

        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=49200.0,  # Hit trailing stop
            high=49300.0,
            low=49100.0,
            close=49200.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        # Create multiple concurrent calls
        tasks = [
            ict_strategy_trailing_stop.should_exit(mock_position_long, candle)
            for _ in range(10)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # All should return the same result
        successful_results = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_results) == 10

        # All successful results should be identical
        first_result = successful_results[0]
        for result in successful_results[1:]:
            assert result.signal_type == first_result.signal_type
            assert result.entry_price == first_result.entry_price
            assert result.exit_reason == first_result.exit_reason


class TestExitIntegration:
    """Test suite for dynamic exit integration with other components."""

    @pytest.mark.asyncio
    async def test_exit_signal_with_risk_validation(
        self, ict_strategy_trailing_stop, mock_position_long, mock_candle
    ):
        """Test exit signal passes risk validation."""
        from src.risk.risk_guard import RiskGuard
        from src.core.audit_logger import AuditLogger

        # Mock risk manager to accept exit signals
        mock_risk_manager = MagicMock(spec=RiskGuard)
        mock_risk_manager.validate_risk.return_value = True

        # Mock audit logger
        mock_audit_logger = MagicMock(spec=AuditLogger)

        candle = Candle(
            symbol="BTCUSDT",
            interval="5m",
            open_time=datetime.now(timezone.utc),
            open=49200.0,  # Hit trailing stop
            high=49300.0,
            low=49100.0,
            close=49200.0,
            volume=100.0,
            close_time=datetime.now(timezone.utc),
            is_closed=True,
        )

        result = await ict_strategy_trailing_stop.should_exit(
            mock_position_long, candle
        )

        assert result is not None
        assert result.is_exit_signal

        # Verify risk validation would accept this signal
        mock_risk_manager.validate_risk.assert_called_once()
        call_args = mock_risk_manager.validate_risk.call_args
        assert call_args[0][0] == result  # signal
        assert call_args[0][1] == mock_position_long  # position

    @pytest.mark.asyncio
    async def test_exit_config_integration(self):
        """Test ExitConfig integration with strategy configuration."""
        exit_config = ExitConfig(
            exit_strategy="trailing_stop",
            trailing_distance=0.015,
            trailing_activation=0.005,
        )

        strategy_config = {
            "exit_config": exit_config,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
        }

        strategy = ICTStrategy("BTCUSDT", strategy_config)

        # Verify config is properly stored
        assert hasattr(strategy, "config")
        assert hasattr(strategy, "exit_config")

        # Verify exit config is accessible
        retrieved_config = getattr(strategy.config, "exit_config", None)
        assert retrieved_config is not None
        assert retrieved_config.exit_strategy == "trailing_stop"
        assert retrieved_config.trailing_distance == 0.015
