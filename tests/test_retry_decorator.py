"""
Unit tests for retry_with_backoff decorator (Task 6.6).
"""
import pytest
from unittest.mock import Mock, patch
from binance.error import ClientError, ServerError
from src.core.retry import retry_with_backoff, RETRYABLE_ERROR_CODES, RETRYABLE_HTTP_STATUS


class TestRetryDecorator:
    """Test cases for @retry_with_backoff decorator."""

    def test_retry_on_rate_limit_429(self):
        """Test retry behavior on HTTP 429 rate limit error."""
        mock_func = Mock()
        mock_func.side_effect = [
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit exceeded", header={}),
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit exceeded", header={}),
            {"orderId": 12345, "status": "NEW"}  # Success on 3rd attempt
        ]

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def api_call():
            return mock_func()

        result = api_call()

        assert result == {"orderId": 12345, "status": "NEW"}
        assert mock_func.call_count == 3

    def test_retry_on_error_code_1003(self):
        """Test retry behavior on Binance error code -1003."""
        mock_func = Mock()
        mock_func.side_effect = [
            ClientError(status_code=418, error_code=-1003, error_message="Way too many requests", header={}),
            {"orderId": 67890}
        ]

        @retry_with_backoff(max_retries=2, initial_delay=0.1)
        def api_call():
            return mock_func()

        result = api_call()

        assert result == {"orderId": 67890}
        assert mock_func.call_count == 2

    def test_no_retry_on_fatal_error_invalid_api_key(self):
        """Test no retry on fatal errors like invalid API key (-2015)."""
        mock_func = Mock()
        mock_func.side_effect = ClientError(
            status_code=401,
            error_code=-2015,
            error_message="Invalid API key",
            header={}
        )

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def api_call():
            return mock_func()

        with pytest.raises(ClientError) as exc_info:
            api_call()

        # Should NOT retry on fatal errors
        assert mock_func.call_count == 1
        assert exc_info.value.error_code == -2015

    def test_no_retry_on_bad_parameter_error(self):
        """Test no retry on invalid parameter errors (-1102)."""
        mock_func = Mock()
        mock_func.side_effect = ClientError(
            status_code=400,
            error_code=-1102,
            error_message="Mandatory parameter 'symbol' was not sent",
            header={}
        )

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def api_call():
            return mock_func()

        with pytest.raises(ClientError):
            api_call()

        # Should fail immediately on parameter errors
        assert mock_func.call_count == 1

    def test_retry_on_server_error_500(self):
        """Test retry on server errors (5xx)."""
        mock_func = Mock()
        mock_func.side_effect = [
            ServerError(status_code=500, message="Internal server error"),
            ServerError(status_code=503, message="Service unavailable"),
            {"orderId": 99999}
        ]

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def api_call():
            return mock_func()

        result = api_call()

        assert result == {"orderId": 99999}
        assert mock_func.call_count == 3

    def test_exponential_backoff_timing(self):
        """Test exponential backoff delay progression."""
        mock_func = Mock()
        mock_func.side_effect = [
            ServerError(status_code=500, message="Internal error"),
            ServerError(status_code=500, message="Internal error"),
            ServerError(status_code=500, message="Internal error"),
            {"orderId": 12345}
        ]

        with patch('time.sleep') as mock_sleep:
            @retry_with_backoff(max_retries=3, initial_delay=1.0, backoff_factor=2.0)
            def api_call():
                return mock_func()

            result = api_call()

            # Verify backoff delays: 1s, 2s, 4s
            assert mock_sleep.call_count == 3
            calls = [call.args[0] for call in mock_sleep.call_args_list]
            assert calls == [1.0, 2.0, 4.0]
            assert result == {"orderId": 12345}

    def test_max_retries_exhausted(self):
        """Test behavior when max retries are exhausted."""
        mock_func = Mock()
        mock_func.side_effect = ServerError(status_code=500, message="Persistent error")

        @retry_with_backoff(max_retries=2, initial_delay=0.1)
        def api_call():
            return mock_func()

        with pytest.raises(ServerError) as exc_info:
            api_call()

        # Should try 3 times total (initial + 2 retries)
        assert mock_func.call_count == 3
        assert exc_info.value.message == "Persistent error"

    def test_success_on_first_attempt(self):
        """Test immediate success without retries."""
        mock_func = Mock(return_value={"orderId": 11111})

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def api_call():
            return mock_func()

        result = api_call()

        assert result == {"orderId": 11111}
        assert mock_func.call_count == 1

    def test_custom_retry_parameters(self):
        """Test decorator with custom parameters."""
        mock_func = Mock()
        mock_func.side_effect = [
            ClientError(status_code=429, error_code=-1003, error_message="Rate limit", header={}),
            {"success": True}
        ]

        @retry_with_backoff(max_retries=5, initial_delay=0.5, backoff_factor=3.0)
        def api_call():
            return mock_func()

        result = api_call()

        assert result == {"success": True}
        assert mock_func.call_count == 2

    def test_decorator_preserves_function_metadata(self):
        """Test that decorator preserves original function metadata."""
        @retry_with_backoff(max_retries=2)
        def my_api_call(symbol: str, quantity: float):
            """Place an order."""
            return {"symbol": symbol, "quantity": quantity}

        assert my_api_call.__name__ == "my_api_call"
        assert "Place an order" in my_api_call.__doc__
