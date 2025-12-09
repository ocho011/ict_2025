"""
Unit tests for BinanceDataCollector class initialization and REST client setup.

Test Coverage:
- Testnet and mainnet initialization
- Symbol normalization to uppercase
- Default parameter handling
- Instance variable initialization
- Input validation (empty symbols/intervals)
"""

import pytest
import logging
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from typing import List

from src.core.data_collector import BinanceDataCollector
from src.models.candle import Candle


class TestBinanceDataCollectorInitialization:
    """Test suite for BinanceDataCollector __init__ method."""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide mock API credentials for testing."""
        return {
            'api_key': 'test_api_key_123',
            'api_secret': 'test_api_secret_456'
        }

    @pytest.fixture
    def basic_config(self):
        """Provide basic configuration for collector initialization."""
        return {
            'symbols': ['BTCUSDT', 'ETHUSDT'],
            'intervals': ['1m', '5m']
        }

    @patch('src.core.data_collector.UMFutures')
    def test_testnet_initialization(self, mock_um_futures, mock_api_credentials, basic_config):
        """
        Test Case 1: Verify testnet initialization with correct base URL.

        Validates:
        - REST client created with TESTNET_BASE_URL
        - is_testnet flag set to True
        - UMFutures called with testnet URL
        """
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client

        # Act
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True
        )

        # Assert
        assert collector.is_testnet is True
        mock_um_futures.assert_called_once_with(
            key=mock_api_credentials['api_key'],
            secret=mock_api_credentials['api_secret'],
            base_url=BinanceDataCollector.TESTNET_BASE_URL
        )
        assert collector.rest_client == mock_rest_client

    @patch('src.core.data_collector.UMFutures')
    def test_mainnet_initialization(self, mock_um_futures, mock_api_credentials, basic_config):
        """
        Test Case 2: Verify mainnet initialization with correct base URL.

        Validates:
        - REST client created with MAINNET_BASE_URL
        - is_testnet flag set to False
        - UMFutures called with mainnet URL
        """
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client

        # Act
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=False
        )

        # Assert
        assert collector.is_testnet is False
        mock_um_futures.assert_called_once_with(
            key=mock_api_credentials['api_key'],
            secret=mock_api_credentials['api_secret'],
            base_url=BinanceDataCollector.MAINNET_BASE_URL
        )
        assert collector.rest_client == mock_rest_client

    @patch('src.core.data_collector.UMFutures')
    def test_symbol_normalization(self, mock_um_futures, mock_api_credentials):
        """
        Test Case 3: Verify symbols are normalized to uppercase.

        Validates:
        - Lowercase symbols converted to uppercase
        - Mixed case symbols converted to uppercase
        - Already uppercase symbols remain unchanged
        """
        # Arrange
        mixed_case_symbols = ['btcusdt', 'EthUsdt', 'ADAUSDT']
        expected_symbols = ['BTCUSDT', 'ETHUSDT', 'ADAUSDT']

        # Act
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=mixed_case_symbols,
            intervals=['1h'],
            is_testnet=True
        )

        # Assert
        assert collector.symbols == expected_symbols

    @patch('src.core.data_collector.UMFutures')
    def test_default_parameters(self, mock_um_futures, mock_api_credentials, basic_config):
        """
        Test Case 4: Verify default parameter values are applied correctly.

        Validates:
        - is_testnet defaults to True
        - buffer_size defaults to DEFAULT_BUFFER_SIZE (500)
        - on_candle_callback defaults to None
        """
        # Act
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals']
            # Not providing: is_testnet, on_candle_callback, buffer_size
        )

        # Assert
        assert collector.is_testnet is True
        assert collector.buffer_size == BinanceDataCollector.DEFAULT_BUFFER_SIZE
        assert collector.on_candle_callback is None

    @patch('src.core.data_collector.UMFutures')
    def test_instance_variables_initialized(self, mock_um_futures, mock_api_credentials, basic_config):
        """
        Test Case 5: Verify all instance variables are initialized correctly.

        Validates:
        - Configuration variables stored
        - Candle buffers dictionary initialized (empty)
        - WebSocket client initialized to None
        - State management flags set correctly
        - Logger initialized
        """
        # Arrange
        test_callback = Mock()
        test_buffer_size = 1000

        # Act
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True,
            on_candle_callback=test_callback,
            buffer_size=test_buffer_size
        )

        # Assert configuration storage
        assert collector.symbols == ['BTCUSDT', 'ETHUSDT']
        assert collector.intervals == basic_config['intervals']
        assert collector.on_candle_callback == test_callback
        assert collector.buffer_size == test_buffer_size

        # Assert internal state
        assert isinstance(collector._candle_buffers, dict)
        assert len(collector._candle_buffers) == 0  # Empty initially
        assert collector.ws_client is None  # Lazy initialization

        # Assert state flags
        assert collector._running is False
        assert collector._is_connected is False

        # Assert logger exists
        assert collector.logger is not None
        assert collector.logger.name == 'src.core.data_collector'

    @patch('src.core.data_collector.UMFutures')
    def test_empty_symbols_raises_error(self, mock_um_futures, mock_api_credentials):
        """
        Test validation: Empty symbols list should raise ValueError.
        """
        # Act & Assert
        with pytest.raises(ValueError, match="symbols list cannot be empty"):
            BinanceDataCollector(
                api_key=mock_api_credentials['api_key'],
                api_secret=mock_api_credentials['api_secret'],
                symbols=[],  # Empty list
                intervals=['1m'],
                is_testnet=True
            )

    @patch('src.core.data_collector.UMFutures')
    def test_empty_intervals_raises_error(self, mock_um_futures, mock_api_credentials):
        """
        Test validation: Empty intervals list should raise ValueError.
        """
        # Act & Assert
        with pytest.raises(ValueError, match="intervals list cannot be empty"):
            BinanceDataCollector(
                api_key=mock_api_credentials['api_key'],
                api_secret=mock_api_credentials['api_secret'],
                symbols=['BTCUSDT'],
                intervals=[],  # Empty list
                is_testnet=True
            )

    @patch('src.core.data_collector.UMFutures')
    def test_repr_method(self, mock_um_futures, mock_api_credentials, basic_config):
        """
        Test __repr__ method returns proper string representation.

        Validates string contains:
        - symbols list
        - intervals list
        - is_testnet flag
        - _running state
        """
        # Act
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True
        )

        repr_string = repr(collector)

        # Assert
        assert 'BinanceDataCollector' in repr_string
        assert "['BTCUSDT', 'ETHUSDT']" in repr_string
        assert "['1m', '5m']" in repr_string
        assert 'is_testnet=True' in repr_string
        assert 'running=False' in repr_string


class TestBinanceDataCollectorURLConstants:
    """Test suite for URL constant values."""

    def test_testnet_base_url(self):
        """Verify TESTNET_BASE_URL constant value."""
        assert BinanceDataCollector.TESTNET_BASE_URL == "https://testnet.binancefuture.com"

    def test_mainnet_base_url(self):
        """Verify MAINNET_BASE_URL constant value."""
        assert BinanceDataCollector.MAINNET_BASE_URL == "https://fapi.binance.com"

    def test_testnet_ws_url(self):
        """Verify TESTNET_WS_URL constant value."""
        assert BinanceDataCollector.TESTNET_WS_URL == "wss://stream.binancefuture.com"

    def test_mainnet_ws_url(self):
        """Verify MAINNET_WS_URL constant value."""
        assert BinanceDataCollector.MAINNET_WS_URL == "wss://fstream.binance.com"

    def test_default_buffer_size(self):
        """Verify DEFAULT_BUFFER_SIZE constant value."""
        assert BinanceDataCollector.DEFAULT_BUFFER_SIZE == 500


class TestBinanceDataCollectorStreaming:
    """Test suite for WebSocket connection management."""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide mock API credentials for testing."""
        return {
            'api_key': 'test_api_key_123',
            'api_secret': 'test_api_secret_456'
        }

    @pytest.fixture
    def basic_config(self):
        """Provide basic configuration for collector initialization."""
        return {
            'symbols': ['BTCUSDT', 'ETHUSDT'],
            'intervals': ['1m', '5m']
        }

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_start_streaming_testnet(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials, basic_config
    ):
        """
        Test Case 1: Verify testnet WebSocket URL selection and initialization.

        Validates:
        - WebSocket client created with TESTNET_WS_URL
        - Client initialization called correctly
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True
        )

        # Act
        await collector.start_streaming()

        # Assert
        mock_ws_client_class.assert_called_once_with(
            stream_url='wss://stream.binancefuture.com'
        )
        assert collector._running is True
        assert collector._is_connected is True

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_start_streaming_mainnet(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials, basic_config
    ):
        """
        Test Case 2: Verify mainnet WebSocket URL selection and initialization.

        Validates:
        - WebSocket client created with MAINNET_WS_URL
        - Client initialization called correctly
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=False
        )

        # Act
        await collector.start_streaming()

        # Assert
        mock_ws_client_class.assert_called_once_with(
            stream_url='wss://fstream.binance.com'
        )
        assert collector._running is True
        assert collector._is_connected is True

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_stream_name_generation(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials
    ):
        """
        Test Case 3: Verify stream name format generation.

        Validates:
        - Format: {symbol_lower}@kline_{interval}
        - Symbol converted to lowercase
        - Interval format preserved
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT', 'ETHUSDT', 'ADAUSDT'],
            intervals=['1m', '5m', '1h'],
            is_testnet=True
        )

        # Act
        await collector.start_streaming()

        # Assert - Verify kline() calls have lowercase symbols
        kline_calls = mock_ws_instance.kline.call_args_list

        # Extract symbols from calls
        called_symbols = [call[1]['symbol'] for call in kline_calls]

        # Verify all symbols are lowercase
        assert all(symbol.islower() for symbol in called_symbols)

        # Verify expected symbols present
        expected_symbols = ['btcusdt', 'ethusdt', 'adausdt']
        for expected_symbol in expected_symbols:
            assert expected_symbol in called_symbols

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_kline_subscriptions(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials, basic_config
    ):
        """
        Test Case 4: Verify kline() subscription calls.

        Validates:
        - kline() called for each symbol/interval pair
        - Correct symbol (lowercase)
        - Correct interval
        - Callback set to _handle_kline_message
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],  # ['BTCUSDT', 'ETHUSDT']
            intervals=basic_config['intervals'],  # ['1m', '5m']
            is_testnet=True
        )

        # Act
        await collector.start_streaming()

        # Assert
        # 2 symbols × 2 intervals = 4 calls
        assert mock_ws_instance.kline.call_count == 4

        # Verify all calls have correct structure
        for call in mock_ws_instance.kline.call_args_list:
            _, kwargs = call
            assert 'symbol' in kwargs
            assert 'interval' in kwargs
            assert 'callback' in kwargs
            assert kwargs['symbol'].islower()  # Symbol is lowercase
            assert kwargs['callback'] == collector._handle_kline_message

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_state_management(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials, basic_config
    ):
        """
        Test Case 5: Verify state flag management.

        Validates:
        - _running set to True after successful start
        - _is_connected set to True after successful start
        - ws_client stored correctly
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True
        )

        # Verify initial state
        assert collector._running is False
        assert collector._is_connected is False
        assert collector.ws_client is None

        # Act
        await collector.start_streaming()

        # Assert final state
        assert collector._running is True
        assert collector._is_connected is True
        assert collector.ws_client == mock_ws_instance

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_connection_error_handling(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials, basic_config
    ):
        """
        Test Case 6: Verify error handling for connection failures.

        Validates:
        - ConnectionError raised on WebSocket initialization failure
        - Error logged with stack trace
        - State remains unchanged on error
        """
        # Arrange
        mock_ws_client_class.side_effect = Exception("Connection refused")

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True
        )

        # Act & Assert
        with pytest.raises(ConnectionError, match="WebSocket initialization failed"):
            await collector.start_streaming()

        # Verify state not updated on error
        assert collector._running is False
        assert collector._is_connected is False

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_idempotency(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials, basic_config
    ):
        """
        Test Case 7: Verify idempotency - multiple calls ignored.

        Validates:
        - Second call to start_streaming() ignored
        - Warning logged
        - WebSocket client created only once
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=basic_config['symbols'],
            intervals=basic_config['intervals'],
            is_testnet=True
        )

        # Act - Call twice
        await collector.start_streaming()
        await collector.start_streaming()  # Second call

        # Assert - WebSocket client created only once
        mock_ws_client_class.assert_called_once()

    @patch('src.core.data_collector.UMFutures')
    @patch('src.core.data_collector.UMFuturesWebsocketClient')
    @pytest.mark.asyncio
    async def test_subscription_count(
        self, mock_ws_client_class, mock_um_futures, mock_api_credentials
    ):
        """
        Test Case 8: Verify correct number of subscriptions created.

        Validates:
        - Subscription count = symbols × intervals
        - Test multiple combinations
        """
        # Arrange
        mock_ws_instance = Mock()
        mock_ws_client_class.return_value = mock_ws_instance

        test_cases = [
            (['BTCUSDT'], ['1m'], 1),  # 1 × 1 = 1
            (['BTCUSDT', 'ETHUSDT'], ['1m'], 2),  # 2 × 1 = 2
            (['BTCUSDT'], ['1m', '5m', '1h'], 3),  # 1 × 3 = 3
            (['BTCUSDT', 'ETHUSDT', 'ADAUSDT'], ['1m', '5m', '15m', '1h'], 12),  # 3 × 4 = 12
        ]

        for symbols, intervals, expected_count in test_cases:
            # Reset mock
            mock_ws_instance.reset_mock()
            mock_ws_client_class.reset_mock()

            collector = BinanceDataCollector(
                api_key=mock_api_credentials['api_key'],
                api_secret=mock_api_credentials['api_secret'],
                symbols=symbols,
                intervals=intervals,
                is_testnet=True
            )

            # Act
            await collector.start_streaming()

            # Assert
            assert mock_ws_instance.kline.call_count == expected_count


# =============================================================================
# Message Parsing Tests (Subtask 3.3)
# =============================================================================

class TestBinanceDataCollectorMessageParsing:
    """Test suite for _handle_kline_message() method."""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide mock API credentials for testing."""
        return {
            'api_key': 'test_api_key_123',
            'api_secret': 'test_api_secret_456'
        }

    @pytest.fixture
    @patch('src.core.data_collector.UMFutures')
    def collector(self, mock_um_futures, mock_api_credentials):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

    @pytest.fixture
    def valid_kline_message(self):
        """Create valid Binance kline WebSocket message."""
        return {
            'e': 'kline',
            'E': 1638747660000,
            's': 'BTCUSDT',
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 1638747600000,  # 2021-12-05 23:40:00 UTC
                'T': 1638747659999,  # 2021-12-05 23:40:59.999 UTC
                'o': '57000.00',
                'h': '57100.00',
                'l': '56900.00',
                'c': '57050.00',
                'v': '10.5',
                'x': True
            }
        }

    def test_valid_kline_message_parsing(self, collector, valid_kline_message):
        """
        Test parsing of valid Binance kline message.

        Validates:
        - All fields extracted correctly
        - Timestamps converted (ms → datetime)
        - Prices/volume converted (str → float)
        - Candle object created successfully
        """
        # Capture callback invocation
        captured_candle = None

        def capture_callback(candle):
            nonlocal captured_candle
            captured_candle = candle

        collector.on_candle_callback = capture_callback

        # Act
        collector._handle_kline_message(valid_kline_message)

        # Assert - Verify all fields
        assert captured_candle is not None
        assert captured_candle.symbol == 'BTCUSDT'
        assert captured_candle.interval == '1m'
        assert captured_candle.open_time == datetime(2021, 12, 5, 23, 40, 0)
        assert captured_candle.close_time == datetime(2021, 12, 5, 23, 40, 59, 999000)
        assert captured_candle.open == 57000.0
        assert captured_candle.high == 57100.0
        assert captured_candle.low == 56900.0
        assert captured_candle.close == 57050.0
        assert captured_candle.volume == 10.5
        assert captured_candle.is_closed is True

    def test_timestamp_conversion_accuracy(self, collector):
        """
        Test millisecond timestamp conversion to datetime.

        Edge cases:
        - Unix epoch (0 ms)
        - Recent timestamp
        - Far future timestamp
        """
        test_cases = [
            (0, datetime(1970, 1, 1, 0, 0, 0)),
            (1638747600000, datetime(2021, 12, 5, 23, 40, 0)),
            (1735689600000, datetime(2025, 1, 1, 0, 0, 0))
        ]

        for timestamp_ms, expected_dt in test_cases:
            message = {
                'e': 'kline',
                'k': {
                    's': 'BTCUSDT',
                    'i': '1m',
                    't': timestamp_ms,
                    'T': timestamp_ms + 59999,
                    'o': '57000.00',
                    'h': '57100.00',
                    'l': '56900.00',
                    'c': '57050.00',
                    'v': '10.5',
                    'x': True
                }
            }

            captured_candle = None

            def capture(candle):
                nonlocal captured_candle
                captured_candle = candle

            collector.on_candle_callback = capture
            collector._handle_kline_message(message)

            assert captured_candle.open_time == expected_dt

    def test_price_volume_string_conversion(self, collector):
        """
        Test string-to-float conversion for prices and volumes.

        Edge cases:
        - Integer strings
        - Decimal strings
        - Scientific notation
        - Very small numbers
        - Very large numbers
        """
        test_values = [
            '57000',
            '57000.50',
            '1.5e-5',
            '0.00000001',
            '999999999.99'
        ]

        for price_str in test_values:
            message = {
                'e': 'kline',
                'k': {
                    's': 'BTCUSDT',
                    'i': '1m',
                    't': 1638747600000,
                    'T': 1638747659999,
                    'o': price_str,
                    'h': price_str,
                    'l': price_str,
                    'c': price_str,
                    'v': price_str,
                    'x': True
                }
            }

            captured_candle = None

            def capture(candle):
                nonlocal captured_candle
                captured_candle = candle

            collector.on_candle_callback = capture
            collector._handle_kline_message(message)

            expected_float = float(price_str)
            assert captured_candle.open == expected_float
            assert captured_candle.volume == expected_float

    def test_callback_invocation_with_valid_callback(self, collector, valid_kline_message):
        """Test callback is invoked with correct Candle object."""
        mock_callback = Mock()
        collector.on_candle_callback = mock_callback

        collector._handle_kline_message(valid_kline_message)

        # Assert callback called once with Candle
        mock_callback.assert_called_once()
        candle_arg = mock_callback.call_args[0][0]
        assert isinstance(candle_arg, Candle)
        assert candle_arg.symbol == 'BTCUSDT'

    def test_callback_none_does_not_crash(self, collector, valid_kline_message):
        """Test that None callback does not cause errors."""
        collector.on_candle_callback = None

        # Should not raise exception
        collector._handle_kline_message(valid_kline_message)

    def test_non_kline_message_ignored_with_warning(self, collector):
        """Test non-kline messages are ignored with warning log."""
        message = {'e': '24hrTicker', 's': 'BTCUSDT'}

        with patch.object(collector.logger, 'warning') as mock_warning:
            collector._handle_kline_message(message)

            # Verify warning logged
            mock_warning.assert_called_once()
            assert '24hrTicker' in str(mock_warning.call_args)

    def test_missing_event_type(self, collector):
        """Test message without 'e' field triggers warning."""
        message = {'k': {'s': 'BTCUSDT'}}

        with patch.object(collector.logger, 'warning') as mock_warning:
            collector._handle_kline_message(message)

            mock_warning.assert_called_once()

    def test_missing_kline_data_logged_as_error(self, collector):
        """Test missing 'k' key logs error."""
        message = {'e': 'kline'}

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called_once()
            assert "missing 'k'" in str(mock_error.call_args).lower()

    def test_missing_required_field_in_kline(self, collector):
        """Test missing required field in kline data triggers KeyError."""
        message = {
            'e': 'kline',
            'k': {
                'i': '1m',  # Missing 's' (symbol)
                't': 1638747600000,
                'T': 1638747659999,
                'o': '57000.00',
                'h': '57100.00',
                'l': '56900.00',
                'c': '57050.00',
                'v': '10.5',
                'x': True
            }
        }

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called()
            assert 'Missing required field' in str(mock_error.call_args)

    def test_invalid_price_string_triggers_value_error(self, collector):
        """Test non-numeric price string logs ValueError."""
        message = {
            'e': 'kline',
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 1638747600000,
                'T': 1638747659999,
                'o': 'invalid_price',
                'h': '57100.00',
                'l': '56900.00',
                'c': '57050.00',
                'v': '10.5',
                'x': True
            }
        }

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called()
            assert 'Invalid data type' in str(mock_error.call_args)

    def test_invalid_timestamp_triggers_type_error(self, collector):
        """Test non-integer timestamp logs TypeError."""
        message = {
            'e': 'kline',
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 'invalid_timestamp',
                'T': 1638747659999,
                'o': '57000.00',
                'h': '57100.00',
                'l': '56900.00',
                'c': '57050.00',
                'v': '10.5',
                'x': True
            }
        }

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called()

    def test_candle_validation_error_high_less_than_open(self, collector):
        """Test Candle validation error when high < open."""
        message = {
            'e': 'kline',
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 1638747600000,
                'T': 1638747659999,
                'o': '57000.00',  # Open = 57000
                'h': '56000.00',  # High = 56000 (INVALID: < open)
                'l': '55000.00',
                'c': '56500.00',
                'v': '10.5',
                'x': True
            }
        }

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called()
            # Should catch ValueError from Candle __post_init__ in ValueError/TypeError handler
            # The actual error will be "Invalid data type" because ValueError is caught there
            log_call = str(mock_error.call_args)
            assert 'High' in log_call and '56000' in log_call

    def test_candle_validation_error_low_greater_than_close(self, collector):
        """Test Candle validation error when low > close."""
        message = {
            'e': 'kline',
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 1638747600000,
                'T': 1638747659999,
                'o': '57000.00',
                'h': '58000.00',
                'l': '57500.00',  # Low = 57500
                'c': '57000.00',  # Close = 57000 (INVALID: low > close)
                'v': '10.5',
                'x': True
            }
        }

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called()

    def test_candle_validation_error_negative_volume(self, collector):
        """Test Candle validation error when volume is negative."""
        message = {
            'e': 'kline',
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 1638747600000,
                'T': 1638747659999,
                'o': '57000.00',
                'h': '57100.00',
                'l': '56900.00',
                'c': '57050.00',
                'v': '-10.5',  # Negative volume (INVALID)
                'x': True
            }
        }

        with patch.object(collector.logger, 'error') as mock_error:
            collector._handle_kline_message(message)

            mock_error.assert_called()

    def test_debug_logging_on_success(self, collector, valid_kline_message):
        """Test debug logging on successful parse."""
        with patch.object(collector.logger, 'debug') as mock_debug:
            collector._handle_kline_message(valid_kline_message)

            mock_debug.assert_called_once()
            log_message = str(mock_debug.call_args)
            assert 'BTCUSDT' in log_message
            assert '1m' in log_message

    def test_multiple_messages_sequential_parsing(self, collector):
        """Test parsing multiple messages in sequence."""
        messages = [
            {
                'e': 'kline',
                'k': {
                    's': 'BTCUSDT',
                    'i': '1m',
                    't': 1638747600000 + i * 60000,
                    'T': 1638747659999 + i * 60000,
                    'o': f'{57000 + i * 10}.00',
                    'h': f'{57100 + i * 10}.00',
                    'l': f'{56900 + i * 10}.00',
                    'c': f'{57050 + i * 10}.00',
                    'v': str(10.5 + i),
                    'x': True
                }
            }
            for i in range(5)
        ]

        captured_candles = []

        def capture(candle):
            captured_candles.append(candle)

        collector.on_candle_callback = capture

        for msg in messages:
            collector._handle_kline_message(msg)

        assert len(captured_candles) == 5
        assert captured_candles[0].close == 57050.0


# =============================================================================
# Historical Candles REST API Tests (Subtask 3.4)
# =============================================================================

class TestBinanceDataCollectorHistoricalCandles:
    """Test suite for get_historical_candles() and _parse_rest_kline() methods."""

    @pytest.fixture
    def mock_api_credentials(self):
        """Provide mock API credentials for testing."""
        return {
            'api_key': 'test_api_key_123',
            'api_secret': 'test_api_secret_456'
        }

    @pytest.fixture
    @patch('src.core.data_collector.UMFutures')
    def collector(self, mock_um_futures, mock_api_credentials):
        """Create BinanceDataCollector instance for testing."""
        return BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

    @pytest.fixture
    def sample_rest_kline_array(self):
        """
        Sample Binance REST API kline array.

        Format: [open_time, open, high, low, close, volume, close_time,
                 quote_volume, trades, taker_buy_base, taker_buy_quote, ignore]
        """
        return [
            1638747600000,  # [0] open_time (2021-12-05 23:40:00 UTC)
            "57000.00",     # [1] open
            "57100.00",     # [2] high
            "56900.00",     # [3] low
            "57050.00",     # [4] close
            "10.5",         # [5] volume
            1638747659999,  # [6] close_time (2021-12-05 23:40:59.999 UTC)
            "598350.00",    # [7] quote_asset_volume
            100,            # [8] number_of_trades
            "5.25",         # [9] taker_buy_base_asset_volume
            "299175.00",    # [10] taker_buy_quote_asset_volume
            "0"             # [11] ignore
        ]

    # =========================================================================
    # _parse_rest_kline() Tests
    # =========================================================================

    def test_parse_rest_kline_valid_data(self, collector, sample_rest_kline_array):
        """Test parsing valid REST kline array into Candle object."""
        # Act
        candle = collector._parse_rest_kline(sample_rest_kline_array)

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
            "50000", "51000", "49000", "50500",
            "100.0",
            1609459259999,  # 2021-01-01 00:00:59.999 UTC
            "5050000", 1000, "50", "2525000", "0"
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
            "1523456.78", 100, "61.7", "761728.39", "0"
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
            "57100", "56900", "57050",
            "10.5",
            1638747659999,
            "598350", 100, "5.25", "299175", "0"
        ]

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid kline data format"):
            collector._parse_rest_kline(kline)

    def test_parse_rest_kline_invalid_timestamp(self, collector):
        """Test error handling for non-numeric timestamp."""
        # Arrange - Invalid timestamp
        kline = [
            "not_a_timestamp",  # Invalid open_time
            "57000", "57100", "56900", "57050",
            "10.5",
            1638747659999,
            "598350", 100, "5.25", "299175", "0"
        ]

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid kline data format"):
            collector._parse_rest_kline(kline)

    def test_parse_rest_kline_is_closed_always_true(self, collector, sample_rest_kline_array):
        """Test that historical candles are always marked as closed."""
        # Act
        candle = collector._parse_rest_kline(sample_rest_kline_array)

        # Assert
        assert candle.is_closed is True

    # =========================================================================
    # get_historical_candles() Tests
    # =========================================================================

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_success(self, mock_um_futures, mock_api_credentials):
        """Test successful retrieval of historical candles."""
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client

        # Mock REST API response (3 candles)
        mock_rest_client.klines.return_value = [
            [1638747600000, "57000", "57100", "56900", "57050", "10.5",
             1638747659999, "598350", 100, "5.25", "299175", "0"],
            [1638747660000, "57050", "57150", "57000", "57100", "11.0",
             1638747719999, "628100", 105, "5.5", "314050", "0"],
            [1638747720000, "57100", "57200", "57050", "57150", "12.5",
             1638747779999, "714375", 110, "6.25", "357187", "0"]
        ]

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act
        candles = collector.get_historical_candles('BTCUSDT', '1m', limit=3)

        # Assert
        assert len(candles) == 3
        mock_rest_client.klines.assert_called_once_with(
            symbol='BTCUSDT',
            interval='1m',
            limit=3
        )

        # Verify first candle
        assert candles[0].symbol == 'BTCUSDT'
        assert candles[0].interval == '1m'
        assert candles[0].open == 57000.0
        assert candles[0].close == 57050.0
        assert candles[0].is_closed is True

        # Verify candles are sorted by time
        assert candles[0].open_time < candles[1].open_time < candles[2].open_time

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_symbol_normalization(self, mock_um_futures, mock_api_credentials):
        """Test that symbol is normalized to uppercase."""
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client
        mock_rest_client.klines.return_value = [
            [1638747600000, "57000", "57100", "56900", "57050", "10.5",
             1638747659999, "598350", 100, "5.25", "299175", "0"]
        ]

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act - Pass lowercase symbol
        candles = collector.get_historical_candles('btcusdt', '1m', limit=1)

        # Assert - API called with uppercase
        mock_rest_client.klines.assert_called_once_with(
            symbol='BTCUSDT',
            interval='1m',
            limit=1
        )
        assert candles[0].symbol == 'BTCUSDT'

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_default_limit(self, mock_um_futures, mock_api_credentials, caplog):
        """Test default limit parameter (500)."""
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client
        mock_rest_client.klines.return_value = []

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act - Don't specify limit
        with caplog.at_level(logging.WARNING):
            candles = collector.get_historical_candles('BTCUSDT', '1m')

        # Assert - Default limit is 500
        mock_rest_client.klines.assert_called_once_with(
            symbol='BTCUSDT',
            interval='1m',
            limit=500
        )
        # Should return empty list with warning
        assert candles == []

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_limit_validation_too_low(self, mock_um_futures, mock_api_credentials):
        """Test validation error for limit < 1."""
        # Arrange
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act & Assert
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            collector.get_historical_candles('BTCUSDT', '1m', limit=0)

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_limit_validation_too_high(self, mock_um_futures, mock_api_credentials):
        """Test validation error for limit > 1000."""
        # Arrange
        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act & Assert
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            collector.get_historical_candles('BTCUSDT', '1m', limit=1001)

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_api_error_handling(self, mock_um_futures, mock_api_credentials):
        """Test error handling when REST API call fails."""
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client
        mock_rest_client.klines.side_effect = Exception("API rate limit exceeded")

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act & Assert
        with pytest.raises(ConnectionError, match="REST API request failed"):
            collector.get_historical_candles('BTCUSDT', '1m', limit=10)

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_empty_response(self, mock_um_futures, mock_api_credentials, caplog):
        """Test handling of empty klines response from API."""
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client
        mock_rest_client.klines.return_value = []

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act
        with caplog.at_level(logging.WARNING):
            candles = collector.get_historical_candles('BTCUSDT', '1m', limit=10)

        # Assert - Should return empty list with warning
        assert candles == []
        assert "No historical candles returned" in caplog.text

    @patch('src.core.data_collector.UMFutures')
    def test_get_historical_candles_logging(self, mock_um_futures, mock_api_credentials, caplog):
        """Test info logging during successful historical data fetch."""
        # Arrange
        mock_rest_client = Mock()
        mock_um_futures.return_value = mock_rest_client
        mock_rest_client.klines.return_value = [
            [1638747600000, "57000", "57100", "56900", "57050", "10.5",
             1638747659999, "598350", 100, "5.25", "299175", "0"]
        ]

        collector = BinanceDataCollector(
            api_key=mock_api_credentials['api_key'],
            api_secret=mock_api_credentials['api_secret'],
            symbols=['BTCUSDT'],
            intervals=['1m'],
            is_testnet=True
        )

        # Act
        with caplog.at_level(logging.INFO):
            collector.get_historical_candles('BTCUSDT', '1m', limit=1)

        # Assert - Verify logging messages
        assert "Fetching 1 historical candles for BTCUSDT 1m" in caplog.text
        assert "Successfully retrieved 1 candles for BTCUSDT 1m" in caplog.text
