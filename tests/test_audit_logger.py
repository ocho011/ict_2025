"""
Unit tests for AuditLogger (Task 6.6).
"""
import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from src.core.audit_logger import AuditLogger, AuditEventType


class TestAuditLogger:
    """Test cases for AuditLogger class."""

    @pytest.fixture
    def temp_log_dir(self):
        """Create temporary log directory for tests."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def audit_logger(self, temp_log_dir):
        """Create AuditLogger instance for tests."""
        return AuditLogger(log_dir=temp_log_dir)

    def test_audit_logger_initialization(self, temp_log_dir):
        """Test audit logger creates log directory and file."""
        logger = AuditLogger(log_dir=temp_log_dir)

        assert Path(temp_log_dir).exists()
        assert logger.log_file.exists()
        assert logger.log_file.name.startswith("audit_")
        assert logger.log_file.suffix == ".jsonl"

    def test_log_event_basic(self, audit_logger):
        """Test basic event logging."""
        audit_logger.log_event(
            event_type=AuditEventType.ORDER_PLACED,
            operation="test_operation",
            symbol="BTCUSDT"
        )

        # Read log file
        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        assert log_entry['event_type'] == 'order_placed'
        assert log_entry['operation'] == 'test_operation'
        assert log_entry['symbol'] == 'BTCUSDT'
        assert 'timestamp' in log_entry

    def test_log_order_placed(self, audit_logger):
        """Test logging successful order placement."""
        order_data = {
            'symbol': 'ETHUSDT',
            'side': 'BUY',
            'type': 'MARKET',
            'quantity': 0.1
        }
        response = {
            'orderId': 123456,
            'status': 'FILLED',
            'price': '2000.0'
        }

        audit_logger.log_order_placed(
            symbol="ETHUSDT",
            order_data=order_data,
            response=response
        )

        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        assert log_entry['event_type'] == 'order_placed'
        assert log_entry['symbol'] == 'ETHUSDT'
        assert log_entry['order_data'] == order_data
        assert log_entry['response'] == response

    def test_log_order_rejected(self, audit_logger):
        """Test logging order rejection."""
        order_data = {'symbol': 'BTCUSDT', 'side': 'SELL', 'quantity': 0.001}
        error = {
            'status_code': 400,
            'error_code': -2010,
            'error_message': 'Order would trigger immediately'
        }

        audit_logger.log_order_rejected(
            symbol="BTCUSDT",
            order_data=order_data,
            error=error
        )

        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        assert log_entry['event_type'] == 'order_rejected'
        assert log_entry['error'] == error

    def test_log_retry_attempt(self, audit_logger):
        """Test logging retry attempts."""
        error = {
            'status_code': 429,
            'error_code': -1003,
            'error_message': 'Rate limit exceeded'
        }

        audit_logger.log_retry_attempt(
            operation="execute_signal",
            attempt=2,
            max_retries=3,
            error=error,
            delay=2.0
        )

        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        assert log_entry['event_type'] == 'retry_attempt'
        assert log_entry['retry_attempt'] == 2
        assert log_entry['additional_data']['max_retries'] == 3
        assert log_entry['additional_data']['delay_seconds'] == 2.0

    def test_log_rate_limit(self, audit_logger):
        """Test logging rate limit errors."""
        error = {
            'status_code': 429,
            'error_code': -1003,
            'error_message': 'Too many requests'
        }
        weight_info = {
            'current_weight': 2100,
            'weight_limit': 2400
        }

        audit_logger.log_rate_limit(
            operation="get_position",
            error=error,
            weight_info=weight_info
        )

        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        assert log_entry['event_type'] == 'rate_limit'
        assert log_entry['additional_data']['weight_info'] == weight_info

    def test_multiple_log_entries(self, audit_logger):
        """Test multiple log entries are written correctly."""
        # Log 3 different events
        audit_logger.log_event(
            event_type=AuditEventType.LEVERAGE_SET,
            operation="set_leverage",
            symbol="BTCUSDT"
        )

        audit_logger.log_event(
            event_type=AuditEventType.MARGIN_TYPE_SET,
            operation="set_margin_type",
            symbol="ETHUSDT"
        )

        audit_logger.log_event(
            event_type=AuditEventType.POSITION_QUERY,
            operation="get_position",
            symbol="BTCUSDT"
        )

        # Read all entries
        with open(audit_logger.log_file) as f:
            entries = [json.loads(line) for line in f]

        assert len(entries) == 3
        assert entries[0]['event_type'] == 'leverage_set'
        assert entries[1]['event_type'] == 'margin_type_set'
        assert entries[2]['event_type'] == 'position_query'

    def test_json_lines_format(self, audit_logger):
        """Test logs are in JSON Lines format (one JSON per line)."""
        # Log multiple events
        for i in range(5):
            audit_logger.log_event(
                event_type=AuditEventType.ORDER_PLACED,
                operation=f"order_{i}",
                symbol="BTCUSDT"
            )

        # Verify each line is valid JSON
        with open(audit_logger.log_file) as f:
            for line in f:
                entry = json.loads(line)  # Should not raise exception
                assert 'timestamp' in entry
                assert 'event_type' in entry
                assert 'operation' in entry

    def test_timestamp_format(self, audit_logger):
        """Test timestamp is in ISO format."""
        audit_logger.log_event(
            event_type=AuditEventType.API_ERROR,
            operation="test"
        )

        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        # Verify timestamp is valid ISO format
        timestamp_str = log_entry['timestamp']
        datetime.fromisoformat(timestamp_str)  # Should not raise exception

    def test_optional_fields_omitted(self, audit_logger):
        """Test optional fields are omitted when not provided."""
        audit_logger.log_event(
            event_type=AuditEventType.BALANCE_QUERY,
            operation="get_balance"
            # No symbol, order_data, response, error, etc.
        )

        with open(audit_logger.log_file) as f:
            log_entry = json.loads(f.readline())

        assert 'timestamp' in log_entry
        assert 'event_type' in log_entry
        assert 'operation' in log_entry
        assert 'symbol' not in log_entry
        assert 'order_data' not in log_entry
        assert 'response' not in log_entry
        assert 'error' not in log_entry
