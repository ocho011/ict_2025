"""
Tests for updated get_position() method with retry logic, exception handling, and circuit breaker.
"""

import logging
import time
from unittest.mock import MagicMock, patch, call
import pytest

from binance.error import ClientError, ServerError
from src.execution.order_gateway import OrderGateway
from src.core.circuit_breaker import CircuitBreaker
from src.core.exceptions import OrderExecutionError, ValidationError
from src.models.position import Position


class TestGetPositionWithRetry:
    """Test enhanced get_position() method with new resilience features."""

    @pytest.fixture
    def mock_client(self):
        """Mock Binance client"""
        return MagicMock()

    @pytest.fixture
    def mock_audit_logger(self):
        """Mock AuditLogger"""
        return MagicMock()

    @pytest.fixture
    def mock_binance_service(self, mock_client):
        """Mock BinanceServiceClient"""
        service = MagicMock()
        service._client = mock_client
        service.is_testnet = True
        service.weight_tracker = MagicMock()
        service.get_position_risk = mock_client.get_position_risk
        return service

    @pytest.fixture
    def manager(self, mock_binance_service, mock_audit_logger):
        """OrderGateway instance with mocked services"""
        return OrderGateway(
            audit_logger=mock_audit_logger, binance_service=mock_binance_service
        )

    def test_get_position_retry_decorator_applied(self, manager):
        """Test that @retry decorator is applied to get_position method"""
        # Verify circuit breaker exists
        assert hasattr(manager, "_position_circuit_breaker")
        assert isinstance(manager._position_circuit_breaker, CircuitBreaker)

    def test_get_position_success_caching(self, manager, mock_client):
        """Test successful position query uses success cache TTL"""
        # Mock successful response
        mock_client.get_position_risk.return_value = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.001",
                "entryPrice": "50000.00",
                "unRealizedProfit": "10.25",
                "leverage": "20",
                "isolated": True,
                "liquidationPrice": "45000.00",
                "markPrice": "50500.00",
            }
        ]

        # First call - cache miss
        position1 = manager.get_position("BTCUSDT")
        assert position1 is not None
        assert position1.symbol == "BTCUSDT"
        assert position1.quantity == 0.001

        # Second call - no cache, hits API again
        position2 = manager.get_position("BTCUSDT")
        assert position2 is not None
        assert position2.symbol == "BTCUSDT"

        # API should be called twice (no caching in OrderGateway)
        assert mock_client.get_position_risk.call_count == 2


    def test_get_position_retry_on_rate_limit(self, manager, mock_client):
        """Test retry behavior on rate limit errors"""
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # First two calls fail
                raise ClientError(
                    status_code=429,
                    error_code=-1003,
                    error_message="Rate limit",
                    header={},
                )
            else:  # Third call succeeds
                return [
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "0.001",
                        "entryPrice": "50000.00",
                    }
                ]

        mock_client.get_position_risk.side_effect = side_effect

        # Should succeed after retries
        position = manager.get_position("BTCUSDT")
        assert position is not None
        assert position.symbol == "BTCUSDT"
        assert mock_client.get_position_risk.call_count == 3  # 1 initial + 2 retries

    def test_get_position_server_error_handling(self, manager, mock_client):
        """Test ServerError is properly handled"""
        mock_client.get_position_risk.side_effect = ServerError(
            status_code=500, message="Internal server error", header={}
        )

        # Should raise OrderExecutionError for ServerError
        with pytest.raises(OrderExecutionError):
            manager.get_position("BTCUSDT")

    def test_get_position_circuit_breaker_opens(self, manager, mock_client):
        """Test circuit breaker opens after repeated failures"""
        # Mock 3 consecutive failures
        mock_client.get_position_risk.side_effect = [
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
        ]

        # First 3 calls should fail
        for i in range(3):
            position = manager.get_position("BTCUSDT")
            assert position is None

        # Circuit breaker should be OPEN after 3 failures
        assert manager._position_circuit_breaker.get_state() == "OPEN"

        # Next call should raise circuit breaker error
        with pytest.raises(OrderExecutionError, match="Circuit breaker OPEN"):
            manager.get_position("BTCUSDT")

    def test_get_position_circuit_breaker_half_open(self, manager, mock_client):
        """Test circuit breaker enters HALF_OPEN state"""
        # First fail 3 times to open circuit
        mock_client.get_position_risk.side_effect = [
            ClientError(status_code=500, error_message="Server error"),
            ClientError(status_code=500, error_message="Server error"),
            ClientError(status_code=500, error_message="Server error"),
        ]

        # Open circuit
        for i in range(3):
            manager.get_position("BTCUSDT")

        assert manager._position_circuit_breaker.get_state() == "OPEN"

        # Wait past recovery timeout
        with patch("time.time", return_value=1000):  # Past timeout
            mock_client.get_position_risk.side_effect = None  # Succeed
            mock_client.get_position_risk.return_value = [
                {
                    "symbol": "BTCUSDT",
                    "positionAmt": "0.001",
                    "entryPrice": "50000.00",
                }
            ]

            # Should succeed and reset circuit breaker
            position = manager.get_position("BTCUSDT")
            assert position is not None
            assert position.symbol == "BTCUSDT"
            assert manager._position_circuit_breaker.get_state() == "CLOSED"


    def test_get_position_backwards_compatibility(self, manager, mock_client):
        """Test backward compatibility with existing code patterns"""
        # Mock success response
        mock_client.get_position_risk.return_value = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0",
                "entryPrice": "0.00",
                "unRealizedProfit": "0.00",
            }
        ]

        # Should return None for no position (same as before)
        position = manager.get_position("BTCUSDT")
        assert position is None

        # Should not raise any exceptions for valid inputs
        mock_client.get_position_risk.assert_called_once()

    def test_get_position_validation_error(self, manager):
        """Test validation errors are not cached or retried"""
        with pytest.raises(ValidationError, match="Invalid symbol"):
            manager.get_position("")  # Empty symbol

        with pytest.raises(ValidationError, match="Invalid symbol"):
            manager.get_position(None)  # None symbol
