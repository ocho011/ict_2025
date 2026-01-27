"""
Tests for PublicMarketStreamer (Issue #57 Refactoring).

PublicMarketStreamer handles:
- WebSocket connection management (one per symbol)
- Kline message parsing and Candle object creation
- Heartbeat monitoring
"""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch
import pytest

from src.core.public_market_streamer import PublicMarketStreamer
from src.models.candle import Candle


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def basic_config():
    """Provide basic configuration for streamer initialization."""
    return {"symbols": ["BTCUSDT", "ETHUSDT"], "intervals": ["1m", "5m"]}


@pytest.fixture
def valid_kline_message():
    """Create valid Binance kline WebSocket message."""
    return {
        "e": "kline",
        "E": 1638747660000,
        "s": "BTCUSDT",
        "k": {
            "s": "BTCUSDT",
            "i": "1m",
            "t": 1638747600000,  # 2021-12-05 23:40:00 UTC
            "T": 1638747659999,  # 2021-12-05 23:40:59.999 UTC
            "o": "57000.00",
            "h": "57100.00",
            "l": "56900.00",
            "c": "57050.00",
            "v": "10.5",
            "x": True,
        },
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestPublicMarketStreamerInitialization:
    """Test suite for PublicMarketStreamer __init__ method."""

    def test_initialization_success(self, basic_config):
        """Test successful initialization with basic config."""
        # Act
        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        # Assert
        assert streamer.symbols == ["BTCUSDT", "ETHUSDT"]
        assert streamer.intervals == ["1m", "5m"]
        assert streamer.is_testnet is True
        assert streamer.on_candle_callback is None

    def test_symbol_normalization(self):
        """Test that symbols are normalized to uppercase."""
        # Arrange
        mixed_case_symbols = ["btcusdt", "EthUsdt", "ADAUSDT"]

        # Act
        streamer = PublicMarketStreamer(
            symbols=mixed_case_symbols,
            intervals=["1h"],
            is_testnet=True,
        )

        # Assert
        assert streamer.symbols == ["BTCUSDT", "ETHUSDT", "ADAUSDT"]

    def test_empty_symbols_raises_error(self):
        """Test validation: Empty symbols list should raise ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="symbols list cannot be empty"):
            PublicMarketStreamer(
                symbols=[],
                intervals=["1m"],
                is_testnet=True,
            )

    def test_empty_intervals_raises_error(self):
        """Test validation: Empty intervals list should raise ValueError."""
        # Act & Assert
        with pytest.raises(ValueError, match="intervals list cannot be empty"):
            PublicMarketStreamer(
                symbols=["BTCUSDT"],
                intervals=[],
                is_testnet=True,
            )

    def test_instance_variables_initialized(self, basic_config):
        """Test all instance variables are initialized correctly."""
        # Arrange
        test_callback = Mock()

        # Act
        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
            on_candle_callback=test_callback,
        )

        # Assert
        assert streamer.symbols == ["BTCUSDT", "ETHUSDT"]
        assert streamer.intervals == basic_config["intervals"]
        assert streamer.on_candle_callback == test_callback
        assert streamer.ws_clients == {}
        assert streamer._running is False
        assert streamer._is_connected is False
        assert streamer.logger is not None


# =============================================================================
# URL Constants Tests
# =============================================================================


class TestPublicMarketStreamerURLConstants:
    """Test suite for URL constant values."""

    def test_testnet_ws_url(self):
        """Verify TESTNET_WS_URL constant value."""
        assert (
            PublicMarketStreamer.TESTNET_WS_URL == "wss://stream.binancefuture.com"
        )

    def test_mainnet_ws_url(self):
        """Verify MAINNET_WS_URL constant value."""
        assert PublicMarketStreamer.MAINNET_WS_URL == "wss://fstream.binance.com"


# =============================================================================
# Streaming Tests
# =============================================================================


class TestPublicMarketStreamerStreaming:
    """Test suite for WebSocket connection management."""

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_start_streaming_testnet(self, mock_ws_client_class, basic_config):
        """Test WebSocket connection to testnet."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        await streamer.start()

        assert len(streamer.ws_clients) == 2
        assert mock_ws_client_class.call_count == 2

        first_call_args = mock_ws_client_class.call_args_list[0]
        assert first_call_args[1]["stream_url"] == "wss://stream.binancefuture.com"
        assert first_call_args[1]["on_message"] == streamer._handle_kline_message
        assert streamer._running is True
        assert streamer._is_connected is True

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_start_streaming_mainnet(self, mock_ws_client_class, basic_config):
        """Test WebSocket connection to mainnet."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=False,
        )

        await streamer.start()

        assert len(streamer.ws_clients) == 2

        first_call_args = mock_ws_client_class.call_args_list[0]
        assert first_call_args[1]["stream_url"] == "wss://fstream.binance.com"

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_stream_name_generation(self, mock_ws_client_class):
        """Test stream names are generated correctly."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=["BTCUSDT", "ETHUSDT", "ADAUSDT"],
            intervals=["1m", "5m", "1h"],
            is_testnet=True,
        )

        await streamer.start()

        kline_calls = mock_ws_instance.kline.call_args_list
        called_symbols = [call[1]["symbol"] for call in kline_calls]
        assert all(symbol.islower() for symbol in called_symbols)

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_kline_subscriptions(self, mock_ws_client_class, basic_config):
        """Test correct number of kline subscriptions."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        await streamer.start()

        # 2 symbols × 2 intervals = 4 subscriptions
        assert mock_ws_instance.kline.call_count == 4

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_idempotency(self, mock_ws_client_class, basic_config):
        """Test that start() is idempotent."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        await streamer.start()
        await streamer.start()

        # Only called once per symbol
        assert mock_ws_client_class.call_count == 2

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_connection_error_handling(self, mock_ws_client_class, basic_config):
        """Test error handling when WebSocket connection fails."""
        mock_ws_client_class.side_effect = Exception("Connection refused")

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        with pytest.raises(ConnectionError, match="WebSocket initialization failed"):
            await streamer.start()

        assert streamer._running is False
        assert streamer._is_connected is False


# =============================================================================
# Stop Tests
# =============================================================================


class TestPublicMarketStreamerStop:
    """Test suite for stop() method."""

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_stop_closes_connections(self, mock_ws_client_class, basic_config):
        """Test that stop() closes all WebSocket connections."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        await streamer.start()
        await streamer.stop()

        assert streamer._running is False
        assert streamer._is_connected is False
        assert len(streamer.ws_clients) == 0

    @pytest.mark.asyncio
    async def test_stop_idempotency(self, basic_config):
        """Test that stop() is idempotent."""
        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        # Stop without starting - should not raise
        await streamer.stop()

        assert streamer._running is False


# =============================================================================
# Message Parsing Tests
# =============================================================================


class TestPublicMarketStreamerMessageParsing:
    """Test suite for _handle_kline_message() method."""

    @pytest.fixture
    def streamer(self):
        """Create PublicMarketStreamer instance for testing."""
        return PublicMarketStreamer(
            symbols=["BTCUSDT"],
            intervals=["1m"],
            is_testnet=True,
        )

    def test_valid_kline_message_parsing(self, streamer, valid_kline_message):
        """Test parsing of valid Binance kline message."""
        # Capture callback invocation
        captured_candle = None

        def capture_callback(candle):
            nonlocal captured_candle
            captured_candle = candle

        streamer.on_candle_callback = capture_callback

        # Act
        streamer._handle_kline_message(None, valid_kline_message)

        # Assert - Verify all fields
        assert captured_candle is not None
        assert captured_candle.symbol == "BTCUSDT"
        assert captured_candle.interval == "1m"
        assert captured_candle.open_time == datetime(2021, 12, 5, 23, 40, 0)
        assert captured_candle.close_time == datetime(2021, 12, 5, 23, 40, 59, 999000)
        assert captured_candle.open == 57000.0
        assert captured_candle.high == 57100.0
        assert captured_candle.low == 56900.0
        assert captured_candle.close == 57050.0
        assert captured_candle.volume == 10.5
        assert captured_candle.is_closed is True

    def test_timestamp_conversion_accuracy(self, streamer):
        """Test millisecond timestamp conversion to datetime."""
        test_cases = [
            (0, datetime(1970, 1, 1, 0, 0, 0)),
            (1638747600000, datetime(2021, 12, 5, 23, 40, 0)),
            (1735689600000, datetime(2025, 1, 1, 0, 0, 0)),
        ]

        for timestamp_ms, expected_dt in test_cases:
            message = {
                "e": "kline",
                "k": {
                    "s": "BTCUSDT",
                    "i": "1m",
                    "t": timestamp_ms,
                    "T": timestamp_ms + 59999,
                    "o": "57000.00",
                    "h": "57100.00",
                    "l": "56900.00",
                    "c": "57050.00",
                    "v": "10.5",
                    "x": True,
                },
            }

            captured_candle = None

            def capture(candle):
                nonlocal captured_candle
                captured_candle = candle

            streamer.on_candle_callback = capture
            streamer._handle_kline_message(None, message)

            assert captured_candle.open_time == expected_dt

    def test_price_volume_string_conversion(self, streamer):
        """Test string-to-float conversion for prices and volumes."""
        test_values = ["57000", "57000.50", "1.5e-5", "0.00000001", "999999999.99"]

        for price_str in test_values:
            message = {
                "e": "kline",
                "k": {
                    "s": "BTCUSDT",
                    "i": "1m",
                    "t": 1638747600000,
                    "T": 1638747659999,
                    "o": price_str,
                    "h": price_str,
                    "l": price_str,
                    "c": price_str,
                    "v": price_str,
                    "x": True,
                },
            }

            captured_candle = None

            def capture(candle):
                nonlocal captured_candle
                captured_candle = candle

            streamer.on_candle_callback = capture
            streamer._handle_kline_message(None, message)

            expected_float = float(price_str)
            assert captured_candle.open == expected_float
            assert captured_candle.volume == expected_float

    def test_callback_invocation_with_valid_callback(
        self, streamer, valid_kline_message
    ):
        """Test callback is invoked with correct Candle object."""
        mock_callback = Mock()
        streamer.on_candle_callback = mock_callback

        streamer._handle_kline_message(None, valid_kline_message)

        # Assert callback called once with Candle
        mock_callback.assert_called_once()
        candle_arg = mock_callback.call_args[0][0]
        assert isinstance(candle_arg, Candle)
        assert candle_arg.symbol == "BTCUSDT"

    def test_callback_none_does_not_crash(self, streamer, valid_kline_message):
        """Test that None callback does not cause errors."""
        streamer.on_candle_callback = None

        # Should not raise exception
        streamer._handle_kline_message(None, valid_kline_message)

    def test_non_kline_message_ignored(self, streamer):
        """Test non-kline messages are ignored."""
        message = {"e": "24hrTicker", "s": "BTCUSDT"}

        mock_callback = Mock()
        streamer.on_candle_callback = mock_callback

        streamer._handle_kline_message(None, message)

        # Callback should not be called
        mock_callback.assert_not_called()

    def test_missing_kline_data_logged_as_error(self, streamer):
        """Test missing 'k' key logs error."""
        message = {"e": "kline"}

        with patch.object(streamer.logger, "error") as mock_error:
            streamer._handle_kline_message(None, message)

            mock_error.assert_called_once()
            assert "missing 'k'" in str(mock_error.call_args).lower()

    def test_missing_required_field_in_kline(self, streamer):
        """Test missing required field in kline data triggers KeyError."""
        message = {
            "e": "kline",
            "k": {
                "i": "1m",  # Missing 's' (symbol)
                "t": 1638747600000,
                "T": 1638747659999,
                "o": "57000.00",
                "h": "57100.00",
                "l": "56900.00",
                "c": "57050.00",
                "v": "10.5",
                "x": True,
            },
        }

        with patch.object(streamer.logger, "error") as mock_error:
            streamer._handle_kline_message(None, message)

            mock_error.assert_called()
            assert "Missing required field" in str(mock_error.call_args)

    def test_invalid_price_string_triggers_value_error(self, streamer):
        """Test non-numeric price string logs ValueError."""
        message = {
            "e": "kline",
            "k": {
                "s": "BTCUSDT",
                "i": "1m",
                "t": 1638747600000,
                "T": 1638747659999,
                "o": "invalid_price",
                "h": "57100.00",
                "l": "56900.00",
                "c": "57050.00",
                "v": "10.5",
                "x": True,
            },
        }

        with patch.object(streamer.logger, "error") as mock_error:
            streamer._handle_kline_message(None, message)

            mock_error.assert_called()
            assert "Invalid data type" in str(mock_error.call_args)

    def test_multiple_messages_sequential_parsing(self, streamer):
        """Test parsing multiple messages in sequence."""
        messages = [
            {
                "e": "kline",
                "k": {
                    "s": "BTCUSDT",
                    "i": "1m",
                    "t": 1638747600000 + i * 60000,
                    "T": 1638747659999 + i * 60000,
                    "o": f"{57000 + i * 10}.00",
                    "h": f"{57100 + i * 10}.00",
                    "l": f"{56900 + i * 10}.00",
                    "c": f"{57050 + i * 10}.00",
                    "v": str(10.5 + i),
                    "x": True,
                },
            }
            for i in range(5)
        ]

        captured_candles = []

        def capture(candle):
            captured_candles.append(candle)

        streamer.on_candle_callback = capture

        for msg in messages:
            streamer._handle_kline_message(None, msg)

        assert len(captured_candles) == 5
        assert captured_candles[0].close == 57050.0

    def test_json_string_message_parsing(self, streamer, valid_kline_message):
        """Test parsing JSON string message (not dict)."""
        import json

        json_message = json.dumps(valid_kline_message)

        captured_candle = None

        def capture(candle):
            nonlocal captured_candle
            captured_candle = candle

        streamer.on_candle_callback = capture
        streamer._handle_kline_message(None, json_message)

        assert captured_candle is not None
        assert captured_candle.symbol == "BTCUSDT"


# =============================================================================
# Connection Status Tests
# =============================================================================


class TestPublicMarketStreamerConnectionStatus:
    """Test suite for is_connected property."""

    def test_is_connected_false_when_no_clients(self, basic_config):
        """Test is_connected returns False when no clients."""
        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        assert streamer.is_connected is False

    @patch("src.core.public_market_streamer.UMFuturesWebsocketClient")
    @pytest.mark.asyncio
    async def test_is_connected_true_when_clients_exist(
        self, mock_ws_client_class, basic_config
    ):
        """Test is_connected returns True when all clients exist."""
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        streamer = PublicMarketStreamer(
            symbols=basic_config["symbols"],
            intervals=basic_config["intervals"],
            is_testnet=True,
        )

        await streamer.start()

        assert streamer.is_connected is True
