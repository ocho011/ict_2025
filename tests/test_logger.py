"""
Unit tests for the logging system (TradingLogger, log_execution_time)

NOTE: This test file needs updating to match current QueueHandler-based implementation.
Many tests are outdated and test the old multi-handler architecture.
"""

import logging
import tempfile
import time
from pathlib import Path

from src.utils.logger import TradingLogger, log_execution_time


class TestTradingLogger:
    """Test TradingLogger class"""

    def teardown_method(self):
        """Clean up logging handlers after each test"""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

    def test_log_directory_creation(self):
        """Verify log directory is created if it doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "test_logs"
            config = {"log_level": "INFO", "log_dir": str(log_dir)}

            TradingLogger(config)

            assert log_dir.exists()
            assert log_dir.is_dir()

    def test_log_directory_exists_already(self):
        """Verify logger handles pre-existing log directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "existing_logs"
            log_dir.mkdir()

            config = {"log_level": "INFO", "log_dir": str(log_dir)}
            TradingLogger(config)

            assert log_dir.exists()

    def test_handler_configuration_count(self):
        """Verify correct number of handlers are configured"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            # Should have 3 handlers: console, rotating file, trade log
            assert len(root_logger.handlers) == 3

    def test_handler_types(self):
        """Verify all expected handler types are present"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            handler_types = [type(h).__name__ for h in root_logger.handlers]

            assert "StreamHandler" in handler_types
            assert "RotatingFileHandler" in handler_types
            assert "TimedRotatingFileHandler" in handler_types

    def test_log_levels_configuration(self):
        """Verify handler log levels are configured correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            handlers = {type(h).__name__: h for h in root_logger.handlers}

            # Console handler should be INFO
            assert handlers["StreamHandler"].level == logging.INFO

            # Rotating file handler should be DEBUG
            assert handlers["RotatingFileHandler"].level == logging.DEBUG

            # Trade log handler should be INFO
            assert handlers["TimedRotatingFileHandler"].level == logging.INFO

    def test_root_logger_level(self):
        """Verify root logger level matches configuration"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

    def test_log_files_created(self):
        """Verify log files are created"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            # Trigger some logging
            test_logger = logging.getLogger("test")
            test_logger.info("Test message")

            trading_log = Path(tmpdir) / "trading.log"
            trades_log = Path(tmpdir) / "trades.log"

            # trading.log should exist (general log file)
            assert trading_log.exists()

            # trades.log should exist (created by handler even if empty)
            assert trades_log.exists()

    def test_console_log_format(self):
        """Verify console handler uses correct format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            console_handler = next(
                h for h in root_logger.handlers if type(h).__name__ == "StreamHandler"
            )

            # Check format contains expected fields
            format_str = console_handler.formatter._fmt
            assert "%(asctime)s" in format_str
            assert "%(levelname)" in format_str
            assert "%(name)" in format_str
            assert "%(message)s" in format_str

    def test_file_log_format(self):
        """Verify file handler uses correct format with line numbers"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            file_handler = next(
                h for h in root_logger.handlers if type(h).__name__ == "RotatingFileHandler"
            )

            # Check format contains line number
            format_str = file_handler.formatter._fmt
            assert "%(lineno)d" in format_str

    def test_rotating_file_handler_max_bytes(self):
        """Verify rotating file handler has correct maxBytes setting"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            file_handler = next(
                h for h in root_logger.handlers if type(h).__name__ == "RotatingFileHandler"
            )

            assert file_handler.maxBytes == 10 * 1024 * 1024  # 10MB

    def test_rotating_file_handler_backup_count(self):
        """Verify rotating file handler has correct backup count"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            file_handler = next(
                h for h in root_logger.handlers if type(h).__name__ == "RotatingFileHandler"
            )

            assert file_handler.backupCount == 5

    def test_trade_handler_backup_count(self):
        """Verify trade handler has 30-day backup retention"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            root_logger = logging.getLogger()
            trade_handler = next(
                h for h in root_logger.handlers if type(h).__name__ == "TimedRotatingFileHandler"
            )

            assert trade_handler.backupCount == 30

    def test_handler_clearing(self):
        """Verify existing handlers are cleared on initialization"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create logger with initial handlers
            config = {"log_level": "INFO", "log_dir": tmpdir}
            TradingLogger(config)

            # Create second logger (should clear previous handlers)
            TradingLogger(config)

            root_logger = logging.getLogger()
            # Should still have only 3 handlers, not 6
            assert len(root_logger.handlers) == 3

    def test_default_log_level(self):
        """Verify default log level is INFO when not specified"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_dir": tmpdir}  # No log_level specified
            logger = TradingLogger(config)

            assert logger.log_level == "INFO"

    def test_default_log_dir(self):
        """Verify default log directory is 'logs' when not specified"""
        config = {}  # No log_dir specified
        logger = TradingLogger(config)

        # Logger now returns absolute path, check directory name
        assert logger.log_dir.name == "logs"

        # Clean up default logs directory if created
        if Path("logs").exists() and not any(Path("logs").iterdir()):
            Path("logs").rmdir()


class TestLogExecutionTime:
    """Test log_execution_time context manager"""

    def teardown_method(self):
        """Clean up logging handlers after each test"""
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

    def test_execution_time_logging(self):
        """Verify execution time is logged"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            with log_execution_time("test_operation"):
                time.sleep(0.05)  # 50ms

            # Read log file
            log_file = Path(tmpdir) / "trading.log"
            with open(log_file) as f:
                content = f.read()

            assert "test_operation completed in" in content
            assert "s" in content  # Should have time in seconds

    def test_execution_time_accuracy(self):
        """Verify execution time measurement is reasonably accurate"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            with log_execution_time("timed_operation"):
                time.sleep(0.1)  # 100ms

            # Read log and extract time
            log_file = Path(tmpdir) / "trading.log"
            with open(log_file) as f:
                content = f.read()

            # Extract the timing (rough parsing)
            # Format: "timed_operation completed in 0.100s"
            import re

            match = re.search(r"completed in ([\d.]+)s", content)
            assert match is not None

            elapsed = float(match.group(1))
            # Should be approximately 100ms (±20ms tolerance)
            assert 0.08 <= elapsed <= 0.12

    def test_execution_time_format(self):
        """Verify execution time is formatted to 3 decimal places"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            with log_execution_time("format_test"):
                time.sleep(0.01)

            log_file = Path(tmpdir) / "trading.log"
            with open(log_file) as f:
                content = f.read()

            # Should have 3 decimal places
            import re

            match = re.search(r"completed in (\d+\.\d{3})s", content)
            assert match is not None

    def test_execution_time_with_exception(self):
        """Verify execution time is logged even when exception occurs"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            # Test that exceptions propagate through the context manager
            # The logging still happens in finally block (__exit__)
            try:
                with log_execution_time("exception_test"):
                    time.sleep(0.01)  # Small delay to ensure measurable time
                    raise ValueError("Test exception")
            except ValueError:
                pass  # Expected exception

            # Execution time should be logged even though exception occurred
            # (The __exit__ method runs after yield regardless of exception)
            log_file = Path(tmpdir) / "trading.log"

            # Small delay to ensure log is flushed
            time.sleep(0.01)

            with open(log_file) as f:
                content = f.read()

            # Context manager's finally block ensures timing is logged
            assert "exception_test completed in" in content

    def test_execution_time_debug_level(self):
        """Verify execution time logs at DEBUG level (appears in file handler)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set root logger to DEBUG so DEBUG messages are processed
            config = {"log_level": "DEBUG", "log_dir": tmpdir}
            TradingLogger(config)

            with log_execution_time("debug_message_test"):
                time.sleep(0.01)

            # Check that DEBUG message appears in trading.log
            # (File handler is set to DEBUG level)
            log_file = Path(tmpdir) / "trading.log"
            with open(log_file) as f:
                content = f.read()

            # Should appear in trading.log at DEBUG level
            assert "debug_message_test completed in" in content
            assert "DEBUG" in content  # Should have DEBUG level marker
