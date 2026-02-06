"""
Tests for BinanceDataCollector facade (Issue #57 Refactoring).

The BinanceDataCollector is now a facade that coordinates:
- PublicMarketStreamer: for kline WebSocket streaming
- PrivateUserStreamer: for user data stream (order updates)

Note: Message parsing tests have moved to test_public_market_streamer.py
since that logic is now in PublicMarketStreamer.
"""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch
import pytest

from src.core.data_collector import BinanceDataCollector
from src.core.public_market_streamer import PublicMarketStreamer
from src.core.private_user_streamer import PrivateUserStreamer
from src.core.binance_service import BinanceServiceClient
from src.models.candle import Candle


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_binance_service():
    """Provide mock BinanceServiceClient for testing."""
    service = Mock(spec=BinanceServiceClient)
    service.is_testnet = True
    service.klines = Mock()
    return service


@pytest.fixture
def mock_market_streamer():
    """Provide mock PublicMarketStreamer for testing."""
    streamer = Mock(spec=PublicMarketStreamer)
    streamer.symbols = ["BTCUSDT", "ETHUSDT"]
    streamer.intervals = ["1m", "5m"]
    streamer.is_connected = False
    streamer.on_candle_callback = None
    streamer.start = AsyncMock()
    streamer.stop = AsyncMock()
    return streamer


@pytest.fixture
def mock_user_streamer():
    """Provide mock PrivateUserStreamer for testing."""
    streamer = Mock(spec=PrivateUserStreamer)
    streamer.is_connected = False
    streamer.start = AsyncMock()
    streamer.stop = AsyncMock()
    streamer.set_order_fill_callback = Mock()
    streamer.set_position_update_callback = Mock()
    streamer.set_order_update_callback = Mock()
    return streamer


@pytest.fixture
def basic_config():
    """Provide basic configuration for collector initialization."""
    return {"symbols": ["BTCUSDT", "ETHUSDT"], "intervals": ["1m", "5m"]}


# =============================================================================
# Initialization Tests
# =============================================================================


class TestBinanceDataCollectorInitialization:
    """Test suite for BinanceDataCollector __init__ method."""

    def test_initialization_success(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Test Case: Verify successful initialization with injected components.
        """
        # Act
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert
        assert collector.binance_service == mock_binance_service
        assert collector.market_streamer == mock_market_streamer
        assert collector.user_streamer == mock_user_streamer
        assert collector.is_testnet is True

    def test_initialization_without_user_streamer(
        self, mock_binance_service, mock_market_streamer
    ):
        """
        Test Case: Verify initialization works without user_streamer (optional).
        """
        # Act
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )

        # Assert
        assert collector.user_streamer is None
        assert collector.market_streamer == mock_market_streamer

    def test_symbols_from_market_streamer(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Test Case: Verify symbols are exposed from market_streamer for backward compatibility.
        """
        # Arrange
        mock_market_streamer.symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]

        # Act
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert
        assert collector.symbols == ["BTCUSDT", "ETHUSDT", "ADAUSDT"]

    def test_intervals_from_market_streamer(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Test Case: Verify intervals are exposed from market_streamer for backward compatibility.
        """
        # Arrange
        mock_market_streamer.intervals = ["1m", "5m", "1h"]

        # Act
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert
        assert collector.intervals == ["1m", "5m", "1h"]

    def test_instance_variables_initialized(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Test Case: Verify all instance variables are initialized correctly.
        """
        # Arrange
        test_callback = Mock()
        mock_market_streamer.on_candle_callback = test_callback

        # Act
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert configuration storage
        assert collector.symbols == mock_market_streamer.symbols
        assert collector.intervals == mock_market_streamer.intervals
        assert collector.on_candle_callback == test_callback

        # Assert state flags
        assert collector._running is False

        # Assert logger exists
        assert collector.logger is not None
        assert collector.logger.name == "src.core.data_collector"

    def test_repr_method(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Test __repr__ method returns proper string representation.
        """
        # Arrange
        mock_market_streamer.is_connected = False

        # Act
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        repr_string = repr(collector)

        # Assert
        assert "BinanceDataCollector" in repr_string
        assert "['BTCUSDT', 'ETHUSDT']" in repr_string
        assert "['1m', '5m']" in repr_string
        assert "is_testnet=True" in repr_string
        assert "running=False" in repr_string


# =============================================================================
# Streaming Tests
# =============================================================================


class TestBinanceDataCollectorStreaming:
    """Test suite for WebSocket connection management."""

    @pytest.mark.asyncio
    async def test_start_streaming_delegates_to_market_streamer(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that start_streaming() delegates to market_streamer.start()."""
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Act
        await collector.start_streaming()

        # Assert
        mock_market_streamer.start.assert_called_once()
        assert collector._running is True

    @pytest.mark.asyncio
    async def test_start_streaming_idempotency(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that start_streaming() is idempotent."""
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Act - Call twice
        await collector.start_streaming()
        await collector.start_streaming()

        # Assert - Only called once
        mock_market_streamer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_streaming_error_handling(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test error handling when market_streamer.start() fails."""
        # Arrange
        mock_market_streamer.start.side_effect = Exception("Connection refused")

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Act & Assert
        with pytest.raises(ConnectionError, match="WebSocket initialization failed"):
            await collector.start_streaming()

        assert collector._running is False

    @pytest.mark.asyncio
    async def test_stop_delegates_to_streamers(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that stop() delegates to both streamers."""
        # Arrange
        mock_market_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        collector._running = True

        # Act
        await collector.stop()

        # Assert
        mock_market_streamer.stop.assert_called_once()
        mock_user_streamer.stop.assert_called_once()
        assert collector._running is False

    @pytest.mark.asyncio
    async def test_stop_idempotency(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that stop() is idempotent."""
        # Arrange
        mock_market_streamer.is_connected = False

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        collector._running = False

        # Act
        await collector.stop()

        # Assert - Not called when already stopped
        mock_market_streamer.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_without_user_streamer(
        self, mock_binance_service, mock_market_streamer
    ):
        """Test that stop() works when user_streamer is None."""
        # Arrange
        mock_market_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )
        collector._running = True

        # Act - Should not raise
        await collector.stop()

        # Assert
        mock_market_streamer.stop.assert_called_once()


# =============================================================================
# Connection Status Tests
# =============================================================================


class TestBinanceDataCollectorConnectionStatus:
    """Test suite for connection status properties (Issue #58)."""

    # =========================================================================
    # Issue #58: is_connected must check both market AND user stream
    # =========================================================================

    def test_is_connected_true_when_both_streamers_connected(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Issue #58 - AC1: is_connected returns True only when BOTH
        market streamer AND user streamer (if configured) are connected.
        """
        # Arrange - Both streamers connected
        mock_market_streamer.is_connected = True
        mock_user_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert
        assert collector.is_connected is True

    def test_is_connected_false_when_user_streamer_disconnected(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Issue #58 - AC2: is_connected returns False if user streamer
        exists but is disconnected, even if market streamer is connected.

        This is the CRITICAL fix - prevents silent failure mode where system
        reports "Connected" while TP/SL orphan prevention is broken.
        """
        # Arrange - Market connected, but User stream disconnected
        mock_market_streamer.is_connected = True
        mock_user_streamer.is_connected = False  # <-- Silent failure scenario

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert - MUST return False
        assert collector.is_connected is False

    def test_is_connected_false_when_market_streamer_disconnected(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Issue #58: is_connected returns False if market streamer
        is disconnected, regardless of user streamer status.
        """
        # Arrange - Market disconnected
        mock_market_streamer.is_connected = False
        mock_user_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert
        assert collector.is_connected is False

    def test_is_connected_backward_compatible_without_user_streamer(
        self, mock_binance_service, mock_market_streamer
    ):
        """
        Issue #58 - AC3: is_connected still works correctly when
        user_streamer is None (backward compatibility).

        When user_streamer is not configured, is_connected should
        only depend on market_streamer status.
        """
        # Arrange - No user streamer configured
        mock_market_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,  # <-- No user stream
        )

        # Assert - Should return True (market is connected)
        assert collector.is_connected is True

        # Change market_streamer status
        mock_market_streamer.is_connected = False
        assert collector.is_connected is False

    def test_is_connected_false_when_market_streamer_none(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """
        Edge case: is_connected returns False when market_streamer is None.
        """
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        collector.market_streamer = None  # Force None state

        # Assert
        assert collector.is_connected is False

    def test_on_candle_callback_returns_market_streamer_callback(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that on_candle_callback delegates to market_streamer."""
        # Arrange
        test_callback = Mock()
        mock_market_streamer.on_candle_callback = test_callback

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Assert
        assert collector.on_candle_callback == test_callback


# =============================================================================
# User Data Stream Tests
# =============================================================================


class TestBinanceDataCollectorListenKeyService:
    """Test suite for listen key service methods."""

    @pytest.mark.asyncio
    async def test_start_listen_key_service_delegates(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that start_listen_key_service() delegates to user_streamer."""
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Act
        await collector.start_listen_key_service(order_fill_callback=lambda d: None)

        # Assert
        mock_user_streamer.set_order_fill_callback.assert_called_once()
        mock_user_streamer.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_listen_key_service_without_user_streamer(
        self, mock_binance_service, mock_market_streamer, caplog
    ):
        """Test that start_listen_key_service() logs warning when user_streamer is None."""
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )

        # Act
        with caplog.at_level(logging.WARNING):
            await collector.start_listen_key_service()

        # Assert
        assert "PrivateUserStreamer not configured" in caplog.text

    @pytest.mark.asyncio
    async def test_stop_listen_key_service_delegates(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that stop_listen_key_service() delegates to user_streamer."""
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Act
        await collector.stop_listen_key_service()

        # Assert
        mock_user_streamer.stop.assert_called_once()


# =============================================================================
# Async Context Manager Tests
# =============================================================================


class TestBinanceDataCollectorContextManager:
    """Test suite for async context manager support."""

    @pytest.mark.asyncio
    async def test_aenter_returns_self(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that __aenter__ returns the collector instance."""
        # Arrange
        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )

        # Act
        result = await collector.__aenter__()

        # Assert
        assert result is collector

    @pytest.mark.asyncio
    async def test_aexit_calls_stop(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test that __aexit__ calls stop()."""
        # Arrange
        mock_market_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        collector._running = True

        # Act
        await collector.__aexit__(None, None, None)

        # Assert
        mock_market_streamer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_usage(
        self, mock_binance_service, mock_market_streamer, mock_user_streamer
    ):
        """Test async with statement usage."""
        # Arrange
        mock_market_streamer.is_connected = True

        collector = BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=mock_user_streamer,
        )
        collector._running = True

        # Act
        async with collector as c:
            assert c is collector

        # Assert - stop() called on exit
        mock_market_streamer.stop.assert_called_once()


# =============================================================================
# Historical Candles REST API Tests
# =============================================================================


class TestBinanceDataCollectorHistoricalCandles:
    """Test suite for get_historical_candles() and _parse_rest_kline() methods."""

    @pytest.fixture
    def collector(self, mock_binance_service, mock_market_streamer):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            binance_service=mock_binance_service,
            market_streamer=mock_market_streamer,
            user_streamer=None,
        )

    @pytest.fixture
    def sample_rest_kline(self):
        """
        Sample Binance REST API kline.

        Format: [open_time, open, high, low, close, volume, close_time,
                 quote_volume, trades, taker_buy_base, taker_buy_quote, ignore]
        """
        return [
            1638747600000,  # [0] open_time (2021-12-05 23:40:00 UTC)
            "57000.00",  # [1] open
            "57100.00",  # [2] high
            "56900.00",  # [3] low
            "57050.00",  # [4] close
            "10.5",  # [5] volume
            1638747659999,  # [6] close_time (2021-12-05 23:40:59.999 UTC)
            "598350.00",  # [7] quote_asset_volume
            100,  # [8] number_of_trades
            "5.25",  # [9] taker_buy_base_asset_volume
            "299175.00",  # [10] taker_buy_quote_asset_volume
            "0",  # [11] ignore
        ]

    # =========================================================================
    # _parse_rest_kline() Tests
    # =========================================================================

    def test_parse_rest_kline_valid_data(self, collector, sample_rest_kline):
        """Test parsing valid REST kline array into Candle object."""
        # Act
        candle = collector._parse_rest_kline(sample_rest_kline)

        # Assert - Verify all fields parsed correctly
        assert candle.open_time == datetime(2021, 12, 5, 23, 40, 0)
        assert candle.close_time == datetime(2021, 12, 5, 23, 40, 59, 999000)
        assert candle.open == 57000.0
        assert candle.high == 57100.0
        assert candle.low == 56900.0
        assert candle.close == 57050.0
        assert candle.volume == 10.5
        assert candle.is_closed is True
        # Symbol and interval should be empty (set by caller)
        assert candle.symbol == ""
        assert candle.interval == ""

    def test_parse_rest_kline_timestamp_conversion(self, collector):
        """Test accurate timestamp conversion from milliseconds to datetime."""
        # Arrange - Known timestamp
        kline = [
            1609459200000,  # 2021-01-01 00:00:00 UTC
            "50000",
            "51000",
            "49000",
            "50500",
            "100.0",
            1609459259999,  # 2021-01-01 00:00:59.999 UTC
            "5050000",
            1000,
            "50",
            "2525000",
            "0",
        ]

        # Act
        candle = collector._parse_rest_kline(kline)

        # Assert
        assert candle.open_time == datetime(2021, 1, 1, 0, 0, 0)
        assert candle.close_time == datetime(2021, 1, 1, 0, 0, 59, 999000)

    def test_parse_rest_kline_string_to_float_conversion(self, collector):
        """Test conversion of string prices/volumes to float."""
        # Arrange - String values
        kline = [
            1638747600000,
            "12345.6789",  # open with many decimals
            "12350.1234",  # high
            "12340.5678",  # low
            "12345.9999",  # close
            "123.456789",  # volume
            1638747659999,
            "1523456.78",
            100,
            "61.7",
            "761728.39",
            "0",
        ]

        # Act
        candle = collector._parse_rest_kline(kline)

        # Assert - Verify float precision
        assert candle.open == 12345.6789
        assert candle.high == 12350.1234
        assert candle.low == 12340.5678
        assert candle.close == 12345.9999
        assert candle.volume == 123.456789

    def test_parse_rest_kline_missing_array_elements(self, collector):
        """Test error handling for kline array with missing elements."""
        # Arrange - Incomplete array (only 5 elements)
        incomplete_kline = [1638747600000, "57000", "57100", "56900", "57050"]

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid kline data format"):
            collector._parse_rest_kline(incomplete_kline)

    def test_parse_rest_kline_invalid_price_string(self, collector):
        """Test error handling for non-numeric price strings."""
        # Arrange - Invalid price string
        kline = [
            1638747600000,
            "not_a_number",  # Invalid open price
            "57100",
            "56900",
            "57050",
            "10.5",
            1638747659999,
            "598350",
            100,
            "5.25",
            "299175",
            "0",
        ]

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid kline data format"):
            collector._parse_rest_kline(kline)

    def test_parse_rest_kline_invalid_timestamp(self, collector):
        """Test error handling for non-numeric timestamp."""
        # Arrange - Invalid timestamp
        kline = [
            "not_a_timestamp",  # Invalid open_time
            "57000",
            "57100",
            "56900",
            "57050",
            "10.5",
            1638747659999,
            "598350",
            100,
            "5.25",
            "299175",
            "0",
        ]

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid kline data format"):
            collector._parse_rest_kline(kline)

    def test_parse_rest_kline_is_closed_always_true(
        self, collector, sample_rest_kline
    ):
        """Test that historical candles are always marked as closed."""
        # Act
        candle = collector._parse_rest_kline(sample_rest_kline)

        # Assert
        assert candle.is_closed is True

    # =========================================================================
    # get_historical_candles() Tests
    # =========================================================================

    def test_get_historical_candles_success(self, collector, mock_binance_service):
        """Test successful retrieval of historical candles."""
        # Arrange
        mock_binance_service.klines.return_value = [
            [
                1638747600000,
                "57000",
                "57100",
                "56900",
                "57050",
                "10.5",
                1638747659999,
                "598350",
                100,
                "5.25",
                "299175",
                "0",
            ],
            [
                1638747660000,
                "57050",
                "57150",
                "57000",
                "57100",
                "11.0",
                1638747719999,
                "628100",
                105,
                "5.5",
                "314050",
                "0",
            ],
            [
                1638747720000,
                "57100",
                "57200",
                "57050",
                "57150",
                "12.5",
                1638747779999,
                "714375",
                110,
                "6.25",
                "357187",
                "0",
            ],
        ]

        # Act
        candles = collector.get_historical_candles("BTCUSDT", "1m", limit=3)

        # Assert
        assert len(candles) == 3
        mock_binance_service.klines.assert_called_once_with(
            symbol="BTCUSDT", interval="1m", limit=3
        )

        # Verify first candle
        assert candles[0].symbol == "BTCUSDT"
        assert candles[0].interval == "1m"
        assert candles[0].open == 57000.0
        assert candles[0].is_closed is True

    def test_get_historical_candles_symbol_normalization(
        self, collector, mock_binance_service
    ):
        """Test that symbol is normalized to uppercase."""
        # Arrange
        mock_binance_service.klines.return_value = [
            [
                1638747600000,
                "57000",
                "57100",
                "56900",
                "57050",
                "10.5",
                1638747659999,
                "598350",
                100,
                "5.25",
                "299175",
                "0",
            ]
        ]

        # Act - Pass lowercase symbol
        candles = collector.get_historical_candles("btcusdt", "1m", limit=1)

        # Assert - API called with uppercase
        mock_binance_service.klines.assert_called_once_with(
            symbol="BTCUSDT", interval="1m", limit=1
        )
        assert candles[0].symbol == "BTCUSDT"

    def test_get_historical_candles_default_limit(
        self, collector, mock_binance_service, caplog
    ):
        """Test default limit parameter (500)."""
        # Arrange
        mock_binance_service.klines.return_value = []

        # Act - Don't specify limit
        with caplog.at_level(logging.WARNING):
            candles = collector.get_historical_candles("BTCUSDT", "1m")

        # Assert - Default limit is 500
        mock_binance_service.klines.assert_called_once_with(
            symbol="BTCUSDT", interval="1m", limit=500
        )
        assert candles == []

    def test_get_historical_candles_limit_validation_too_low(self, collector):
        """Test validation error for limit < 1."""
        # Act & Assert
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            collector.get_historical_candles("BTCUSDT", "1m", limit=0)

    def test_get_historical_candles_limit_validation_too_high(self, collector):
        """Test validation error for limit > 1000."""
        # Act & Assert
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            collector.get_historical_candles("BTCUSDT", "1m", limit=1001)

    def test_get_historical_candles_api_error_handling(
        self, collector, mock_binance_service
    ):
        """Test error handling when REST API call fails."""
        # Arrange
        mock_binance_service.klines.side_effect = Exception("API rate limit exceeded")

        # Act & Assert
        with pytest.raises(ConnectionError, match="REST API request failed"):
            collector.get_historical_candles("BTCUSDT", "1m", limit=10)

    def test_get_historical_candles_empty_response(
        self, collector, mock_binance_service, caplog
    ):
        """Test handling of empty klines response from API."""
        # Arrange
        mock_binance_service.klines.return_value = []

        # Act
        with caplog.at_level(logging.WARNING):
            candles = collector.get_historical_candles("BTCUSDT", "1m", limit=10)

        # Assert
        assert candles == []
        assert "No historical candles returned" in caplog.text

    def test_get_historical_candles_logging(
        self, collector, mock_binance_service, caplog
    ):
        """Test info logging during successful historical data fetch."""
        # Arrange
        mock_binance_service.klines.return_value = [
            [
                1638747600000,
                "57000",
                "57100",
                "56900",
                "57050",
                "10.5",
                1638747659999,
                "598350",
                100,
                "5.25",
                "299175",
                "0",
            ]
        ]

        # Act
        with caplog.at_level(logging.INFO):
            collector.get_historical_candles("BTCUSDT", "1m", limit=1)

        # Assert
        assert "Fetching 1 historical candles" in caplog.text
        assert "Successfully retrieved 1 candles" in caplog.text
        assert "Fetching 1 historical candles for BTCUSDT 1m" in caplog.text
        assert "Successfully retrieved 1 candles for BTCUSDT 1m" in caplog.text
