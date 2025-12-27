"""
Audit logging system for tracking all API operations, errors, and retries.

This module provides structured logging in JSON Lines format for comprehensive
audit trails of trading operations, errors, and system events.
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum


class AuditEventType(Enum):
    """Types of audit events that can be logged."""
    # Order events
    ORDER_PLACED = "order_placed"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"

    # Query events
    POSITION_QUERY = "position_query"
    BALANCE_QUERY = "balance_query"

    # Configuration events
    LEVERAGE_SET = "leverage_set"
    MARGIN_TYPE_SET = "margin_type_set"

    # Error events
    API_ERROR = "api_error"
    RETRY_ATTEMPT = "retry_attempt"
    RATE_LIMIT = "rate_limit"

    # Risk management events
    RISK_VALIDATION = "risk_validation"
    RISK_REJECTION = "risk_rejection"
    POSITION_SIZE_CALCULATED = "position_size_calculated"
    POSITION_SIZE_CAPPED = "position_size_capped"

    # Trading flow events
    SIGNAL_PROCESSING = "signal_processing"
    TRADE_EXECUTED = "trade_executed"
    TRADE_EXECUTION_FAILED = "trade_execution_failed"


class AuditLogger:
    """
    Structured audit logger for trading operations.

    Logs are written in JSON Lines format (one JSON object per line)
    for easy parsing and analysis with tools like jq, grep, or log
    aggregation systems.

    Example log entry:
        {
            "timestamp": "2025-12-17T10:30:45.123456",
            "event_type": "order_placed",
            "operation": "execute_signal",
            "symbol": "BTCUSDT",
            "order_data": {"side": "BUY", "quantity": 0.001},
            "response": {"orderId": 12345, "status": "NEW"}
        }
    """

    def __init__(self, log_dir: str = "logs/audit"):
        """
        Initialize audit logger.

        Args:
            log_dir: Directory for audit log files (default: logs/audit)
                    Daily log files are created in this directory.
        """
        # Always use project root's logs directory for consistency
        project_root = Path(__file__).resolve().parent.parent.parent
        
        # If log_dir is relative, make it relative to project root
        self.log_dir = Path(log_dir)
        if not self.log_dir.is_absolute():
            self.log_dir = project_root / self.log_dir
            
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create daily log file
        self.log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"

        # Setup logger
        self.logger = logging.getLogger(f"audit_{id(self)}")  # Unique logger per instance
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False  # Don't propagate to root logger

        # Always create new file handler for this instance
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
            event_type: Type of audit event (from AuditEventType enum)
            operation: Operation name (e.g., "place_order", "set_leverage")
            symbol: Trading symbol if applicable (e.g., "BTCUSDT")
            order_data: Order parameters if applicable
            response: API response data if available
            error: Error details if error occurred
            retry_attempt: Retry attempt number if applicable
            additional_data: Any additional context data

        Example:
            >>> logger.log_event(
            ...     event_type=AuditEventType.ORDER_PLACED,
            ...     operation="execute_signal",
            ...     symbol="BTCUSDT",
            ...     order_data={"side": "BUY", "quantity": 0.001},
            ...     response={"orderId": 12345}
            ... )
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
        """
        Log successful order placement.

        Args:
            symbol: Trading symbol
            order_data: Order parameters used
            response: API response with order details
        """
        self.log_event(
            event_type=AuditEventType.ORDER_PLACED,
            operation="place_order",
            symbol=symbol,
            order_data=order_data,
            response=response
        )

    def log_order_rejected(self, symbol: str, order_data: Dict[str, Any], error: Dict[str, Any]):
        """
        Log order rejection.

        Args:
            symbol: Trading symbol
            order_data: Order parameters that were rejected
            error: Error details from API
        """
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
        """
        Log retry attempt.

        Args:
            operation: Operation being retried
            attempt: Current attempt number
            max_retries: Maximum retry attempts
            error: Error that triggered retry
            delay: Delay in seconds before retry
        """
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

    def log_rate_limit(
        self,
        operation: str,
        error: Dict[str, Any],
        weight_info: Optional[Dict] = None
    ):
        """
        Log rate limit error.

        Args:
            operation: Operation that hit rate limit
            error: Rate limit error details
            weight_info: Current weight usage information if available
        """
        self.log_event(
            event_type=AuditEventType.RATE_LIMIT,
            operation=operation,
            error=error,
            additional_data={'weight_info': weight_info} if weight_info else None
        )
