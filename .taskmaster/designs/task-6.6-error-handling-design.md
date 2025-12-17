# Task 6.6: Error Handling with Retry Logic - Design Document

## 1. Overview

### 1.1 Purpose
Implement comprehensive error handling with retry logic for all Binance API operations in the OrderExecutionManager. This enhancement will make the system resilient to transient API failures, rate limits, and network issues while maintaining audit trails of all errors.

### 1.2 Scope
- Implement `@retry_with_backoff` decorator with exponential backoff
- Enhance all API operation error handling
- Implement rate limit detection and automatic retry
- Add request weight tracking to prevent rate limit violations
- Implement structured audit logging for all errors and retries

### 1.3 Success Criteria
- All API operations wrapped with retry logic
- Rate limit errors (HTTP 429, error code -1003) automatically handled
- Audit logs capture all errors with full context
- Request weight tracked to prevent hitting limits
- No breaking changes to existing method signatures
- All existing tests pass with enhanced error handling

## 2. Current State Analysis

### 2.1 Existing Error Handling Pattern
**Location**: `src/execution/order_manager.py`

Current implementation has basic try/except blocks:
```python
except ClientError as e:
    # Binance API errors (4xx status codes)
    self.logger.error(
        f"Entry order rejected by Binance: "
        f"code={e.error_code}, msg={e.error_message}"
    )
    raise OrderRejectedError(
        f"Binance rejected order: {e.error_message}"
    ) from e

except Exception as e:
    # Unexpected errors (network, parsing, etc.)
    self.logger.error(
        f"Entry order execution failed: {type(e).__name__}: {e}"
    )
    raise OrderExecutionError(
        f"Failed to execute order: {e}"
    ) from e
```

### 2.2 Methods Requiring Enhancement
All methods making Binance API calls (9+ methods identified):
1. `set_leverage()` - Lines 172-178
2. `set_margin_type()` - Lines 234-247 (special case: "No need to change")
3. `_refresh_exchange_info()` - Lines 371-378
4. `execute_signal()` - Lines 801-818
5. `_place_tp_order()` - Lines 623-636
6. `_place_sl_order()` - Lines 700-713
7. `get_position()` - Lines 938-949
8. `get_account_balance()` - Lines 998-1007
9. `cancel_all_orders()` - Lines 1059+

### 2.3 Binance Error Types
**Source**: Binance futures connector documentation

```python
from binance.error import ClientError, ServerError

# ClientError (4xx HTTP status codes)
# Attributes: status_code, error_code, error_message, header
except ClientError as error:
    logging.error(
        "Status: {}, Error Code: {}, Message: {}".format(
            error.status_code,
            error.error_code,
            error.error_message
        )
    )

# ServerError (5xx HTTP status codes)
# Attributes: status_code, message
except ServerError as error:
    logging.error(
        "Status: {}, Message: {}".format(
            error.status_code,
            error.message
        )
    )
```

### 2.4 Key Error Codes
- `-1003`: Rate limit exceeded (CRITICAL - requires retry with backoff)
- `-2015`: Invalid API key/permissions (FATAL - do not retry)
- `-1102`: Unrecognized parameter (FATAL - do not retry)
- `-2010`: Order would immediately trigger (BUSINESS LOGIC - do not retry)
- `429`: HTTP status for rate limiting

### 2.5 Rate Limit Information
- **API Limit**: 2400 requests/minute for order operations
- **Weight Tracking**: Available via `show_limit_usage=True` in client initialization
- **Response Headers**: Weight usage provided in each response header

## 3. Proposed Solution

### 3.1 Retry Decorator Design

**Location**: New file `src/core/retry.py`

```python
"""
Retry decorator with exponential backoff for Binance API operations.
"""
import time
import logging
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
    429,    # Too many requests
    500,    # Internal server error
    502,    # Bad gateway
    503,    # Service unavailable
    504,    # Gateway timeout
}


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (ClientError, ServerError),
):
    """
    Decorator that implements exponential backoff retry logic for API operations.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds before first retry (default: 1.0)
        backoff_factor: Multiplier for delay after each retry (default: 2.0)
        retryable_exceptions: Tuple of exception types to retry (default: ClientError, ServerError)

    Retry Logic:
        - Delay sequence: 1s, 2s, 4s (for default parameters)
        - Only retries on retryable error codes and HTTP status codes
        - Does NOT retry on fatal errors (invalid API key, bad parameters)
        - Logs each retry attempt with error details

    Usage:
        @retry_with_backoff(max_retries=3, initial_delay=1.0)
        def place_order(self, symbol: str, side: str, ...):
            return self.client.new_order(...)
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
                            'status_code': e.status_code,
                            'error_code': e.error_code,
                            'error_message': e.error_message
                        }

                        # Retry only on retryable error codes or HTTP status
                        should_retry = (
                            e.error_code in RETRYABLE_ERROR_CODES or
                            e.status_code in RETRYABLE_HTTP_STATUS
                        )

                    elif isinstance(e, ServerError):
                        error_info = {
                            'status_code': e.status_code,
                            'message': e.message
                        }

                        # Retry on all server errors (5xx)
                        should_retry = True

                    # If this is the last attempt or error is not retryable, re-raise
                    if attempt == max_retries or not should_retry:
                        logger.error(
                            f"{func.__name__} failed after {attempt + 1} attempts: "
                            f"{error_info}"
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
```

### 3.2 Audit Logging System Design

**Location**: New file `src/core/audit_logger.py`

```python
"""
Audit logging system for tracking all API operations, errors, and retries.
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum


class AuditEventType(Enum):
    """Types of audit events."""
    ORDER_PLACED = "order_placed"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"
    POSITION_QUERY = "position_query"
    BALANCE_QUERY = "balance_query"
    LEVERAGE_SET = "leverage_set"
    MARGIN_TYPE_SET = "margin_type_set"
    API_ERROR = "api_error"
    RETRY_ATTEMPT = "retry_attempt"
    RATE_LIMIT = "rate_limit"


class AuditLogger:
    """
    Structured audit logger for trading operations.

    Logs are written in JSON Lines format (one JSON object per line)
    for easy parsing and analysis.
    """

    def __init__(self, log_dir: str = "logs/audit"):
        """
        Initialize audit logger.

        Args:
            log_dir: Directory for audit log files (default: logs/audit)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create daily log file
        self.log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"

        # Setup logger
        self.logger = logging.getLogger("audit")
        self.logger.setLevel(logging.INFO)

        # Add file handler if not already present
        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)

    def log_event(
        self,
        event_type: AuditEventType,
        operation: str,
        symbol: Optional[str] = None,
        order_data: Optional[Dict[str, Any]] = None,
        response: Optional[Dict[str, Any]] = None,
        error: Optional[Dict[str, Any]] = None,
        retry_attempt: Optional[int] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log an audit event in JSON format.

        Args:
            event_type: Type of audit event
            operation: Operation name (e.g., "place_order", "set_leverage")
            symbol: Trading symbol if applicable
            order_data: Order parameters if applicable
            response: API response data if available
            error: Error details if error occurred
            retry_attempt: Retry attempt number if applicable
            additional_data: Any additional context data
        """
        event = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type.value,
            'operation': operation,
        }

        if symbol:
            event['symbol'] = symbol
        if order_data:
            event['order_data'] = order_data
        if response:
            event['response'] = response
        if error:
            event['error'] = error
        if retry_attempt is not None:
            event['retry_attempt'] = retry_attempt
        if additional_data:
            event['additional_data'] = additional_data

        # Write as single-line JSON
        self.logger.info(json.dumps(event))

    def log_order_placed(self, symbol: str, order_data: Dict[str, Any], response: Dict[str, Any]):
        """Log successful order placement."""
        self.log_event(
            event_type=AuditEventType.ORDER_PLACED,
            operation="place_order",
            symbol=symbol,
            order_data=order_data,
            response=response
        )

    def log_order_rejected(self, symbol: str, order_data: Dict[str, Any], error: Dict[str, Any]):
        """Log order rejection."""
        self.log_event(
            event_type=AuditEventType.ORDER_REJECTED,
            operation="place_order",
            symbol=symbol,
            order_data=order_data,
            error=error
        )

    def log_retry_attempt(
        self,
        operation: str,
        attempt: int,
        max_retries: int,
        error: Dict[str, Any],
        delay: float
    ):
        """Log retry attempt."""
        self.log_event(
            event_type=AuditEventType.RETRY_ATTEMPT,
            operation=operation,
            error=error,
            retry_attempt=attempt,
            additional_data={
                'max_retries': max_retries,
                'delay_seconds': delay
            }
        )

    def log_rate_limit(self, operation: str, error: Dict[str, Any], weight_info: Optional[Dict] = None):
        """Log rate limit error."""
        self.log_event(
            event_type=AuditEventType.RATE_LIMIT,
            operation=operation,
            error=error,
            additional_data={'weight_info': weight_info} if weight_info else None
        )
```

### 3.3 Request Weight Tracking Design

**Location**: Enhancement to `src/execution/order_manager.py`

```python
class RequestWeightTracker:
    """
    Tracks API request weight to prevent rate limit violations.

    Binance provides weight usage in response headers when client is initialized
    with show_limit_usage=True.
    """

    def __init__(self):
        """Initialize weight tracker."""
        self.current_weight = 0
        self.weight_limit = 2400  # Binance limit: 2400 requests/minute
        self.last_reset = datetime.now()
        self.logger = logging.getLogger(__name__)

    def update_from_response(self, response_headers: Optional[Dict] = None):
        """
        Update weight tracking from API response headers.

        Binance returns weight information in headers:
        - 'X-MBX-USED-WEIGHT-1M': Current weight used in 1-minute window

        Args:
            response_headers: Response headers from Binance API
        """
        if not response_headers:
            return

        # Extract weight from headers
        weight_str = response_headers.get('X-MBX-USED-WEIGHT-1M')
        if weight_str:
            try:
                self.current_weight = int(weight_str)

                # Log warning if approaching limit (80% threshold)
                if self.current_weight > self.weight_limit * 0.8:
                    self.logger.warning(
                        f"Approaching rate limit: {self.current_weight}/{self.weight_limit} "
                        f"({self.current_weight / self.weight_limit * 100:.1f}%)"
                    )
            except ValueError:
                self.logger.error(f"Invalid weight value in header: {weight_str}")

    def check_limit(self) -> bool:
        """
        Check if we're approaching rate limit.

        Returns:
            True if safe to proceed, False if should wait
        """
        # Allow up to 90% of limit
        return self.current_weight < self.weight_limit * 0.9

    def get_status(self) -> Dict[str, Any]:
        """
        Get current weight tracking status.

        Returns:
            Dictionary with weight usage information
        """
        return {
            'current_weight': self.current_weight,
            'weight_limit': self.weight_limit,
            'usage_percent': (self.current_weight / self.weight_limit * 100),
            'safe_to_proceed': self.check_limit()
        }
```

### 3.4 OrderExecutionManager Integration

**Location**: `src/execution/order_manager.py`

**Changes Required**:

1. **Import new modules** (add to existing imports around line 16):
```python
from src.core.retry import retry_with_backoff
from src.core.audit_logger import AuditLogger, AuditEventType
from binance.error import ServerError  # Add ServerError to existing ClientError import
```

2. **Initialize in `__init__` method** (around line 150):
```python
def __init__(
    self,
    client,
    config: Dict[str, Any],
    logger: logging.Logger
):
    self.client = client
    self.config = config
    self.logger = logger

    # NEW: Initialize audit logger
    self.audit_logger = AuditLogger(log_dir=config.get('audit_log_dir', 'logs/audit'))

    # NEW: Initialize weight tracker
    self.weight_tracker = RequestWeightTracker()

    # Existing initialization continues...
```

3. **Enhance client initialization** (in main.py or wherever client is created):
```python
# Enable weight usage tracking in response headers
client = UMFutures(
    key=api_key,
    secret=api_secret,
    show_limit_usage=True  # NEW: Enable weight tracking
)
```

4. **Apply decorator to all API methods**:

Example for `set_leverage()`:
```python
@retry_with_backoff(max_retries=3, initial_delay=1.0)
def set_leverage(self, symbol: str, leverage: int) -> None:
    """Set leverage for a trading pair with retry logic."""
    try:
        response = self.client.change_leverage(symbol=symbol, leverage=leverage)

        # NEW: Update weight tracker
        if hasattr(response, 'headers'):
            self.weight_tracker.update_from_response(response.headers)

        # NEW: Audit log success
        self.audit_logger.log_event(
            event_type=AuditEventType.LEVERAGE_SET,
            operation="set_leverage",
            symbol=symbol,
            response={'leverage': leverage, 'status': 'success'}
        )

        self.logger.info(f"Leverage set to {leverage}x for {symbol}")

    except ClientError as e:
        # NEW: Audit log error
        self.audit_logger.log_event(
            event_type=AuditEventType.API_ERROR,
            operation="set_leverage",
            symbol=symbol,
            error={
                'status_code': e.status_code,
                'error_code': e.error_code,
                'error_message': e.error_message
            }
        )

        self.logger.error(
            f"Failed to set leverage: code={e.error_code}, msg={e.error_message}"
        )
        raise OrderExecutionError(f"Failed to set leverage: {e.error_message}") from e
```

Example for `execute_signal()`:
```python
@retry_with_backoff(max_retries=3, initial_delay=1.0)
def execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
    """Execute trading signal with comprehensive error handling."""
    symbol = signal['symbol']

    try:
        # Prepare order data
        order_params = self._prepare_order_params(signal)

        # Place order
        response = self.client.new_order(**order_params)

        # NEW: Update weight tracker
        if hasattr(response, 'headers'):
            self.weight_tracker.update_from_response(response.headers)

        # NEW: Audit log successful order
        self.audit_logger.log_order_placed(
            symbol=symbol,
            order_data=order_params,
            response=response
        )

        return response

    except ClientError as e:
        # NEW: Audit log rejection
        self.audit_logger.log_order_rejected(
            symbol=symbol,
            order_data=order_params,
            error={
                'status_code': e.status_code,
                'error_code': e.error_code,
                'error_message': e.error_message
            }
        )

        # Existing error handling
        self.logger.error(
            f"Entry order rejected by Binance: "
            f"code={e.error_code}, msg={e.error_message}"
        )
        raise OrderRejectedError(
            f"Binance rejected order: {e.error_message}"
        ) from e

    except ServerError as e:
        # NEW: Handle server errors (will be retried by decorator)
        self.audit_logger.log_event(
            event_type=AuditEventType.API_ERROR,
            operation="execute_signal",
            symbol=symbol,
            error={
                'status_code': e.status_code,
                'message': e.message
            }
        )

        self.logger.error(
            f"Binance server error: status={e.status_code}, msg={e.message}"
        )
        raise OrderExecutionError(
            f"Binance server error: {e.message}"
        ) from e
```

## 4. Testing Strategy

### 4.1 Unit Tests
**Location**: `tests/test_retry_decorator.py`

```python
"""
Test cases for retry_with_backoff decorator.
"""
import pytest
from unittest.mock import Mock, patch
from binance.error import ClientError, ServerError
from src.core.retry import retry_with_backoff


def test_retry_on_rate_limit():
    """Test retry behavior on rate limit error (429)."""
    mock_func = Mock()
    mock_func.side_effect = [
        ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
        ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
        {"orderId": 12345}  # Success on 3rd attempt
    ]

    @retry_with_backoff(max_retries=3, initial_delay=0.1)
    def api_call():
        return mock_func()

    result = api_call()
    assert result == {"orderId": 12345}
    assert mock_func.call_count == 3


def test_no_retry_on_fatal_error():
    """Test no retry on fatal errors like invalid API key."""
    mock_func = Mock()
    mock_func.side_effect = ClientError(
        status_code=401,
        error_code=-2015,
        error_message="Invalid API key"
    )

    @retry_with_backoff(max_retries=3, initial_delay=0.1)
    def api_call():
        return mock_func()

    with pytest.raises(ClientError):
        api_call()

    # Should NOT retry on fatal errors
    assert mock_func.call_count == 1


def test_exponential_backoff_timing():
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
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)
```

### 4.2 Integration Tests
**Location**: `tests/test_order_execution.py` (enhance existing tests)

```python
def test_order_execution_with_retry():
    """Test order execution with transient failure and retry."""
    # Mock client to fail twice then succeed
    mock_client = Mock()
    mock_client.new_order.side_effect = [
        ClientError(status_code=429, error_code=-1003, error_message="Rate limit"),
        ClientError(status_code=503, error_code=-1001, error_message="Internal error"),
        {
            'orderId': 12345,
            'symbol': 'BTCUSDT',
            'status': 'NEW'
        }
    ]

    manager = OrderExecutionManager(mock_client, config, logger)
    signal = create_test_signal()

    result = manager.execute_signal(signal)

    assert result['orderId'] == 12345
    assert mock_client.new_order.call_count == 3  # 2 failures + 1 success
```

### 4.3 Audit Log Verification
```python
def test_audit_logging():
    """Test audit logs are written correctly."""
    audit_logger = AuditLogger(log_dir="test_logs")

    audit_logger.log_order_placed(
        symbol="BTCUSDT",
        order_data={"side": "BUY", "quantity": 0.001},
        response={"orderId": 12345}
    )

    # Verify log file exists
    log_file = Path(f"test_logs/audit_{datetime.now().strftime('%Y%m%d')}.jsonl")
    assert log_file.exists()

    # Verify log content
    with open(log_file) as f:
        log_entry = json.loads(f.readline())
        assert log_entry['event_type'] == 'order_placed'
        assert log_entry['symbol'] == 'BTCUSDT'
        assert log_entry['response']['orderId'] == 12345
```

## 5. Implementation Plan

### 5.1 Phase 1: Core Infrastructure
1. Create `src/core/retry.py` with `@retry_with_backoff` decorator
2. Create `src/core/audit_logger.py` with `AuditLogger` class
3. Add `RequestWeightTracker` class to `order_manager.py`
4. Write unit tests for decorator and audit logger

### 5.2 Phase 2: Integration
1. Update `order_manager.py` imports
2. Initialize audit logger and weight tracker in `__init__`
3. Apply `@retry_with_backoff` decorator to all API methods
4. Add audit logging to all API methods
5. Update client initialization with `show_limit_usage=True`

### 5.3 Phase 3: Testing & Validation
1. Run all existing unit tests to ensure no breaking changes
2. Add new integration tests for retry scenarios
3. Test audit log writing and parsing
4. Test rate limit handling in controlled environment
5. Verify weight tracking accuracy

### 5.4 Phase 4: Documentation
1. Update docstrings for all enhanced methods
2. Document retry parameters and behavior
3. Document audit log format and analysis
4. Add troubleshooting guide for common errors

## 6. Risk Analysis

### 6.1 Risks
1. **Infinite retry loops**: Mitigated by max_retries limit
2. **Increased latency**: Acceptable trade-off for reliability
3. **Audit log disk space**: Mitigated by daily rotation
4. **Breaking changes**: Mitigated by decorator pattern (no signature changes)

### 6.2 Rollback Strategy
If issues arise:
1. Remove `@retry_with_backoff` decorators (revert to basic error handling)
2. Disable audit logging by commenting initialization
3. All existing error handling remains functional
4. No database or state changes required

## 7. Configuration

### 7.1 Retry Parameters
```python
# config/trading_config.py
RETRY_CONFIG = {
    'max_retries': 3,
    'initial_delay': 1.0,
    'backoff_factor': 2.0
}
```

### 7.2 Audit Log Configuration
```python
# config/trading_config.py
AUDIT_CONFIG = {
    'log_dir': 'logs/audit',
    'rotation': 'daily',
    'retention_days': 30
}
```

### 7.3 Rate Limit Configuration
```python
# config/trading_config.py
RATE_LIMIT_CONFIG = {
    'weight_limit': 2400,
    'warning_threshold': 0.8,  # 80%
    'hard_limit_threshold': 0.9  # 90%
}
```

## 8. Success Metrics

### 8.1 Operational Metrics
- **Retry Success Rate**: % of operations that succeed after retry
- **Average Retry Count**: Average number of retries per operation
- **Rate Limit Hit Rate**: Frequency of rate limit errors
- **Weight Usage**: Current and peak weight usage

### 8.2 Quality Metrics
- **Test Coverage**: Maintain >80% coverage
- **Zero Breaking Changes**: All existing tests pass
- **Audit Log Completeness**: 100% of API operations logged
- **Error Recovery Rate**: % of transient errors recovered

## 9. Future Enhancements

### 9.1 Potential Improvements
1. **Adaptive backoff**: Adjust delays based on error patterns
2. **Circuit breaker**: Stop retrying after consecutive failures
3. **Metrics dashboard**: Real-time visualization of retry/error metrics
4. **Alert system**: Notify on high error rates or rate limit approaches
5. **Log analysis tools**: Automated parsing and reporting of audit logs

### 9.2 Performance Optimization
1. **Async retry**: Non-blocking retry for non-critical operations
2. **Request batching**: Combine multiple operations to reduce weight
3. **Predictive rate limiting**: Proactively slow down before hitting limits

## 10. References

### 10.1 Documentation
- Binance Futures API Error Codes: [Official Documentation]
- Binance futures-connector-python: `/binance/binance-futures-connector-python`
- Python retry patterns: PEP 380, functools.wraps

### 10.2 Related Tasks
- Task 6.1: OrderExecutionManager Initialization
- Task 6.5: Price Formatting Enhancement
- Future: Task 7.x - Performance Monitoring

---

**Document Status**: FINAL
**Version**: 1.0
**Date**: 2025-12-17
**Author**: Claude (Task Master AI)
