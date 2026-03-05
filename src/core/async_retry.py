"""
Async retry decorator with exponential backoff for Binance API operations.
"""

import asyncio
import logging
from functools import wraps
from typing import Callable, Tuple, Type, Any

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


def async_retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    Async decorator that implements exponential backoff retry logic.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except retryable_exceptions as e:
                    last_exception = e
                    
                    # Log retry attempt
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )

                    if attempt == max_retries:
                        logger.error(
                            f"{func.__name__} failed after {attempt + 1} attempts"
                        )
                        raise

                    await asyncio.sleep(delay)
                    delay *= backoff_factor

            raise last_exception

        return wrapper

    return decorator
