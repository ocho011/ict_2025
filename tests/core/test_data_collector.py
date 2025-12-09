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
