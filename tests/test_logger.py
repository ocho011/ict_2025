"""
Unit tests for the logging system (TradingLogger, TradeLogFilter, log_execution_time)
"""

import pytest
import tempfile
import logging
import json
import time
from pathlib import Path
from src.utils.logger import TradingLogger, TradeLogFilter, log_execution_time


class TestTradeLogFilter:
    """Test TradeLogFilter class"""

    def test_filter_accepts_trades_logger(self):
        """Verify filter accepts records from 'trades' logger"""
        filter_obj = TradeLogFilter()

        trade_record = logging.LogRecord(
            name='trades',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='test',
            args=(),
            exc_info=None
        )

        assert filter_obj.filter(trade_record) is True

    def test_filter_rejects_other_loggers(self):
        """Verify filter rejects records from non-trades loggers"""
        filter_obj = TradeLogFilter()

        system_record = logging.LogRecord(
            name='trading.signals',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='test',
            args=(),
            exc_info=None
        )

        assert filter_obj.filter(system_record) is False

    def test_filter_rejects_root_logger(self):
        """Verify filter rejects root logger records"""
        filter_obj = TradeLogFilter()

        root_record = logging.LogRecord(
            name='root',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='test',
            args=(),
            exc_info=None
        )

        assert filter_obj.filter(root_record) is False


class TestTradingLogger:
    """Test TradingLogger class"""

    def teardown_method(self):
        """Clean up logging handlers after each test"""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

    def test_log_directory_creation(self):
        """Verify log directory is created if it doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / 'test_logs'
            config = {'log_level': 'INFO', 'log_dir': str(log_dir)}

            logger = TradingLogger(config)

            assert log_dir.exists()
            assert log_dir.is_dir()

    def test_log_directory_exists_already(self):
        """Verify logger handles pre-existing log directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / 'existing_logs'
            log_dir.mkdir()

            config = {'log_level': 'INFO', 'log_dir': str(log_dir)}
            logger = TradingLogger(config)

            assert log_dir.exists()

    def test_handler_configuration_count(self):
        """Verify correct number of handlers are configured"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            # Should have 3 handlers: console, rotating file, trade log
            assert len(root_logger.handlers) == 3

    def test_handler_types(self):
        """Verify all expected handler types are present"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            handler_types = [type(h).__name__ for h in root_logger.handlers]

            assert 'StreamHandler' in handler_types
            assert 'RotatingFileHandler' in handler_types
            assert 'TimedRotatingFileHandler' in handler_types

    def test_log_levels_configuration(self):
        """Verify handler log levels are configured correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            handlers = {type(h).__name__: h for h in root_logger.handlers}

            # Console handler should be INFO
            assert handlers['StreamHandler'].level == logging.INFO

            # Rotating file handler should be DEBUG
            assert handlers['RotatingFileHandler'].level == logging.DEBUG

            # Trade log handler should be INFO
            assert handlers['TimedRotatingFileHandler'].level == logging.INFO

    def test_root_logger_level(self):
        """Verify root logger level matches configuration"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

    def test_log_files_created(self):
        """Verify log files are created"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            # Trigger some logging
            test_logger = logging.getLogger('test')
            test_logger.info("Test message")

            trading_log = Path(tmpdir) / 'trading.log'
            trades_log = Path(tmpdir) / 'trades.log'

            # trading.log should exist (general log file)
            assert trading_log.exists()

            # trades.log should exist (created by handler even if empty)
            assert trades_log.exists()

    def test_console_log_format(self):
        """Verify console handler uses correct format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            console_handler = next(h for h in root_logger.handlers
                                  if type(h).__name__ == 'StreamHandler')

            # Check format contains expected fields
            format_str = console_handler.formatter._fmt
            assert '%(asctime)s' in format_str
            assert '%(levelname)' in format_str
            assert '%(name)' in format_str
            assert '%(message)s' in format_str

    def test_file_log_format(self):
        """Verify file handler uses correct format with line numbers"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            file_handler = next(h for h in root_logger.handlers
                               if type(h).__name__ == 'RotatingFileHandler')

            # Check format contains line number
            format_str = file_handler.formatter._fmt
            assert '%(lineno)d' in format_str

    def test_rotating_file_handler_max_bytes(self):
        """Verify rotating file handler has correct maxBytes setting"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            file_handler = next(h for h in root_logger.handlers
                               if type(h).__name__ == 'RotatingFileHandler')

            assert file_handler.maxBytes == 10 * 1024 * 1024  # 10MB

    def test_rotating_file_handler_backup_count(self):
        """Verify rotating file handler has correct backup count"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            file_handler = next(h for h in root_logger.handlers
                               if type(h).__name__ == 'RotatingFileHandler')

            assert file_handler.backupCount == 5

    def test_trade_handler_backup_count(self):
        """Verify trade handler has 30-day backup retention"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            trade_handler = next(h for h in root_logger.handlers
                                if type(h).__name__ == 'TimedRotatingFileHandler')

            assert trade_handler.backupCount == 30

    def test_trade_handler_has_filter(self):
        """Verify trade handler has TradeLogFilter attached"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            trade_handler = next(h for h in root_logger.handlers
                                if type(h).__name__ == 'TimedRotatingFileHandler')

            # Check that filter is present and is TradeLogFilter
            assert len(trade_handler.filters) > 0
            assert isinstance(trade_handler.filters[0], TradeLogFilter)

    def test_handler_clearing(self):
        """Verify existing handlers are cleared on initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create logger with initial handlers
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger1 = TradingLogger(config)

            # Create second logger (should clear previous handlers)
            logger2 = TradingLogger(config)

            root_logger = logging.getLogger()
            # Should still have only 3 handlers, not 6
            assert len(root_logger.handlers) == 3

    def test_default_log_level(self):
        """Verify default log level is INFO when not specified"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_dir': tmpdir}  # No log_level specified
            logger = TradingLogger(config)

            assert logger.log_level == 'INFO'

    def test_default_log_dir(self):
        """Verify default log directory is 'logs' when not specified"""
        config = {}  # No log_dir specified
        logger = TradingLogger(config)

        assert logger.log_dir == Path('logs')

        # Clean up default logs directory if created
        if Path('logs').exists() and not any(Path('logs').iterdir()):
            Path('logs').rmdir()


class TestLogTrade:
    """Test TradingLogger.log_trade() static method"""

    def teardown_method(self):
        """Clean up logging handlers after each test"""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

    def test_log_trade_creates_json_entry(self):
        """Verify log_trade creates valid JSON entries"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            TradingLogger.log_trade('TEST_ACTION', {
                'symbol': 'BTCUSDT',
                'price': 50000.0
            })

            # Read trade log file
            log_file = Path(tmpdir) / 'trades.log'
            assert log_file.exists()

            with open(log_file) as f:
                log_line = f.readline().strip()

            # Parse JSON
            log_entry = json.loads(log_line)

            assert log_entry['action'] == 'TEST_ACTION'
            assert log_entry['symbol'] == 'BTCUSDT'
            assert log_entry['price'] == 50000.0

    def test_log_trade_includes_timestamp(self):
        """Verify log_trade includes ISO timestamp"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            TradingLogger.log_trade('SIGNAL_GENERATED', {'symbol': 'ETHUSDT'})

            log_file = Path(tmpdir) / 'trades.log'
            with open(log_file) as f:
                log_entry = json.loads(f.readline())

            assert 'timestamp' in log_entry
            # Verify ISO format (basic check)
            assert 'T' in log_entry['timestamp']

    def test_log_trade_unpacks_data_dict(self):
        """Verify log_trade correctly unpacks data dictionary"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            trade_data = {
                'symbol': 'BTCUSDT',
                'entry': 50000.0,
                'tp': 51000.0,
                'sl': 49500.0,
                'strategy': 'MockSMA'
            }

            TradingLogger.log_trade('SIGNAL_GENERATED', trade_data)

            log_file = Path(tmpdir) / 'trades.log'
            with open(log_file) as f:
                log_entry = json.loads(f.readline())

            # All data fields should be present
            assert log_entry['symbol'] == 'BTCUSDT'
            assert log_entry['entry'] == 50000.0
            assert log_entry['tp'] == 51000.0
            assert log_entry['sl'] == 49500.0
            assert log_entry['strategy'] == 'MockSMA'

    def test_log_trade_multiple_entries(self):
        """Verify multiple trade log entries are appended"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            TradingLogger.log_trade('ORDER_PLACED', {'order_id': '123'})
            TradingLogger.log_trade('ORDER_FILLED', {'order_id': '123'})
            TradingLogger.log_trade('POSITION_CLOSED', {'pnl': 100.0})

            log_file = Path(tmpdir) / 'trades.log'
            with open(log_file) as f:
                lines = f.readlines()

            assert len(lines) == 3

            # Verify each entry
            entries = [json.loads(line) for line in lines]
            assert entries[0]['action'] == 'ORDER_PLACED'
            assert entries[1]['action'] == 'ORDER_FILLED'
            assert entries[2]['action'] == 'POSITION_CLOSED'

    def test_log_trade_appears_in_both_logs(self):
        """Verify trade logs appear in both trading.log and trades.log"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            TradingLogger.log_trade('ORDER_FILLED', {'order_id': '456'})

            # Check trades.log has the JSON entry
            trades_log = Path(tmpdir) / 'trades.log'
            with open(trades_log) as f:
                trades_content = f.read()

            assert 'ORDER_FILLED' in trades_content
            assert '{"timestamp"' in trades_content

            # Check trading.log ALSO has the entry (formatted)
            trading_log = Path(tmpdir) / 'trading.log'
            with open(trading_log) as f:
                trading_content = f.read()

            # Trade logs appear in both files (trades.log via filter, trading.log via general handler)
            assert 'ORDER_FILLED' in trading_content


class TestLogExecutionTime:
    """Test log_execution_time context manager"""

    def teardown_method(self):
        """Clean up logging handlers after each test"""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

    def test_execution_time_logging(self):
        """Verify execution time is logged"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            with log_execution_time('test_operation'):
                time.sleep(0.05)  # 50ms

            # Read log file
            log_file = Path(tmpdir) / 'trading.log'
            with open(log_file) as f:
                content = f.read()

            assert 'test_operation completed in' in content
            assert 's' in content  # Should have time in seconds

    def test_execution_time_accuracy(self):
        """Verify execution time measurement is reasonably accurate"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            with log_execution_time('timed_operation'):
                time.sleep(0.1)  # 100ms

            # Read log and extract time
            log_file = Path(tmpdir) / 'trading.log'
            with open(log_file) as f:
                content = f.read()

            # Extract the timing (rough parsing)
            # Format: "timed_operation completed in 0.100s"
            import re
            match = re.search(r'completed in ([\d.]+)s', content)
            assert match is not None

            elapsed = float(match.group(1))
            # Should be approximately 100ms (±20ms tolerance)
            assert 0.08 <= elapsed <= 0.12

    def test_execution_time_format(self):
        """Verify execution time is formatted to 3 decimal places"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            with log_execution_time('format_test'):
                time.sleep(0.01)

            log_file = Path(tmpdir) / 'trading.log'
            with open(log_file) as f:
                content = f.read()

            # Should have 3 decimal places
            import re
            match = re.search(r'completed in (\d+\.\d{3})s', content)
            assert match is not None

    def test_execution_time_with_exception(self):
        """Verify execution time is logged even when exception occurs"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            # Test that exceptions propagate through the context manager
            # The logging still happens in finally block (__exit__)
            try:
                with log_execution_time('exception_test'):
                    time.sleep(0.01)  # Small delay to ensure measurable time
                    raise ValueError("Test exception")
            except ValueError:
                pass  # Expected exception

            # Execution time should be logged even though exception occurred
            # (The __exit__ method runs after yield regardless of exception)
            log_file = Path(tmpdir) / 'trading.log'

            # Small delay to ensure log is flushed
            time.sleep(0.01)

            with open(log_file) as f:
                content = f.read()

            # Context manager's finally block ensures timing is logged
            assert 'exception_test completed in' in content

    def test_execution_time_debug_level(self):
        """Verify execution time logs at DEBUG level (appears in file handler)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set root logger to DEBUG so DEBUG messages are processed
            config = {'log_level': 'DEBUG', 'log_dir': tmpdir}
            logger = TradingLogger(config)

            with log_execution_time('debug_message_test'):
                time.sleep(0.01)

            # Check that DEBUG message appears in trading.log
            # (File handler is set to DEBUG level)
            log_file = Path(tmpdir) / 'trading.log'
            with open(log_file) as f:
                content = f.read()

            # Should appear in trading.log at DEBUG level
            assert 'debug_message_test completed in' in content
            assert 'DEBUG' in content  # Should have DEBUG level marker
