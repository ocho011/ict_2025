"""
Retry decorator with exponential backoff for Binance API operations.

This module provides a decorator for implementing retry logic with exponential
backoff for API operations that may fail due to transient errors like rate
limits or temporary server issues.
"""

import logging
import time
from functools import wraps
from typing import Callable, Tuple, Type

from binance.error import ClientError, ServerError

# Error codes that should trigger retry
RETRYABLE_ERROR_CODES = {
    -1003,  # Rate limit exceeded
    -1001,  # Internal error
}

# HTTP status codes that should trigger retry
RETRYABLE_HTTP_STATUS = {
    429,  # Too many requests
    500,  # Internal server error
    502,  # Bad gateway
    503,  # Service unavailable
    504,  # Gateway timeout
}


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (ClientError, ServerError),
):
    """
    Decorator that implements exponential backoff retry logic for API operations.

    This decorator will retry failed API calls with exponentially increasing delays
    between attempts. It intelligently distinguishes between retryable errors
    (rate limits, server errors) and fatal errors (invalid API key, bad parameters).

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds before first retry (default: 1.0)
        backoff_factor: Multiplier for delay after each retry (default: 2.0)
        retryable_exceptions: Tuple of exception types to retry (default: ClientError, ServerError)

    Retry Logic:
        - Delay sequence with defaults: 1s, 2s, 4s
        - Only retries on retryable error codes and HTTP status codes
        - Does NOT retry on fatal errors (invalid API key, bad parameters)
        - Logs each retry attempt with error details

    Usage:
        @retry_with_backoff(max_retries=3, initial_delay=1.0)
        def place_order(self, symbol: str, side: str, ...):
            return self.client.new_order(...)

    Example:
        >>> @retry_with_backoff(max_retries=2, initial_delay=0.5)
        ... def api_call():
        ...     return client.get_position()
        ...
        >>> # Will retry up to 2 times with 0.5s, 1.0s delays
        >>> result = api_call()
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except retryable_exceptions as e:
                    last_exception = e

                    # Check if this error should be retried
                    should_retry = False
                    error_info = {}

                    if isinstance(e, ClientError):
                        error_info = {
                            "status_code": e.status_code,
                            "error_code": e.error_code,
                            "error_message": e.error_message,
                        }

                        # Retry only on retryable error codes or HTTP status
                        should_retry = (
                            e.error_code in RETRYABLE_ERROR_CODES
                            or e.status_code in RETRYABLE_HTTP_STATUS
                        )

                    elif isinstance(e, ServerError):
                        error_info = {"status_code": e.status_code, "message": e.message}

                        # Retry on all server errors (5xx)
                        should_retry = True

                    # If this is the last attempt or error is not retryable, re-raise
                    if attempt == max_retries or not should_retry:
                        logger.error(
                            f"{func.__name__} failed after {attempt + 1} attempts: " f"{error_info}"
                        )
                        raise

                    # Log retry attempt
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed: "
                        f"{error_info}. Retrying in {delay}s..."
                    )

                    # Wait before retry
                    time.sleep(delay)
                    delay *= backoff_factor

            # This should never be reached, but just in case
            raise last_exception

        return wrapper

    return decorator
