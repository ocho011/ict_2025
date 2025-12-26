"""
Logging configuration with multi-handler setup and structured trade logging
"""

import logging
import sys
import json
import time
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Generator


class TradeLogFilter(logging.Filter):
    """
    Filter to isolate trade events from general logging

    Only allows log records with logger name 'trades' to pass through
    to the trade-specific handler, preventing pollution of trade logs
    with system messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Determine if log record should be processed

        Args:
            record: Log record to evaluate

        Returns:
            True if record.name == 'trades', False otherwise
        """
        return record.name == 'trades'


class TradingLogger:
    """
    Centralized logging system for trading operations

    Features:
    - Multi-handler logging (console, file, trade-specific)
    - Automatic log rotation (size-based and time-based)
    - Structured JSON logging for trade events
    - Performance measurement utilities
    """

    def __init__(self, config: dict):
        """
        Initialize logging infrastructure

        Args:
            config: Configuration dictionary with keys:
                - log_level: str (DEBUG, INFO, WARNING, ERROR)
                - log_dir: str (directory path for log files)

        Raises:
            OSError: If log directory creation fails
        """
        self.log_level = config.get('log_level', 'INFO')

        # Always use project root's logs/ directory for consistency
        # regardless of execution location (PyCharm, terminal, background)
        project_root = Path(__file__).resolve().parent.parent.parent
        default_log_dir = project_root / 'logs'

        # If config specifies log_dir, interpret as relative to project root
        # unless it's an absolute path
        config_log_dir = config.get('log_dir', str(default_log_dir))
        self.log_dir = Path(config_log_dir)
        if not self.log_dir.is_absolute():
            self.log_dir = project_root / self.log_dir

        self.log_dir.mkdir(exist_ok=True)
        self._setup_logging()

    def _setup_logging(self) -> None:
        """
        Configure root logger with all handlers

        Sets up:
        1. Console handler (INFO+, simple format)
        2. Rotating file handler (DEBUG+, detailed format)
        3. Trade-specific handler (INFO, JSON format, time-based rotation)

        Thread-safe: Uses logging module's built-in thread safety
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.log_level.upper()))

        # Clear existing handlers to avoid duplicates
        root_logger.handlers.clear()

        # Console Handler - INFO and above
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s'
        )
        console_handler.setFormatter(console_format)
        root_logger.addHandler(console_handler)

        # File Handler - All levels, rotating (10MB max, 5 backups)
        file_handler = RotatingFileHandler(
            self.log_dir / 'trading.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s'
        )
        file_handler.setFormatter(file_format)
        root_logger.addHandler(file_handler)

        # Trade Log - Separate file for trades only (daily rotation, 30-day retention)
        trade_handler = TimedRotatingFileHandler(
            self.log_dir / 'trades.log',
            when='midnight',
            backupCount=30
        )
        trade_handler.setLevel(logging.INFO)
        trade_handler.addFilter(TradeLogFilter())
        root_logger.addHandler(trade_handler)

    @staticmethod
    def log_trade(action: str, data: dict) -> None:
        """
        Log trade events in structured JSON format

        Args:
            action: Trade action type (SIGNAL_GENERATED, ORDER_FILLED, etc.)
            data: Trade-specific data dictionary

        Example:
            TradingLogger.log_trade('SIGNAL_GENERATED', {
                'symbol': 'BTCUSDT',
                'type': 'LONG_ENTRY',
                'entry': 50000.0,
                'tp': 51000.0,
                'sl': 49500.0
            })
        """
        logger = logging.getLogger('trades')
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'action': action,
            **data
        }
        logger.info(json.dumps(log_entry))


@contextmanager
def log_execution_time(operation: str) -> Generator[None, None, None]:
    """
    Context manager for measuring and logging execution time

    Args:
        operation: Human-readable operation description

    Usage:
        with log_execution_time('indicator_calculation'):
            result = calculate_indicators()

    Logs at DEBUG level: "{operation} completed in {elapsed:.3f}s"
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logging.debug(f"{operation} completed in {elapsed:.3f}s")


# Deprecated function for backwards compatibility
def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    DEPRECATED: Use TradingLogger class instead

    Temporary wrapper for backwards compatibility

    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger instance
    """
    import warnings
    warnings.warn(
        "setup_logger() is deprecated. Use TradingLogger class.",
        DeprecationWarning,
        stacklevel=2
    )
    return logging.getLogger(name)
