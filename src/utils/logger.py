"""
Logging configuration with multi-handler setup and structured trade logging

Performance optimizations:
- QueueHandler + QueueListener pattern for async logging
- Non-blocking I/O for hot path operations
- Thread-safe queue-based architecture
"""

import logging
import queue
import sys
import time
from contextlib import contextmanager
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Generator, Optional


class ColorFormatter(logging.Formatter):
    """
    Custom formatter providing ANSI color codes for console output.
    """

    # ANSI escape sequences for colors
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    CYAN = "\x1b[36;20m"
    RESET = "\x1b[0m"
    GREEN = "\x1b[32;20m"

    # Base format string
    LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"

    FORMATS = {
        logging.DEBUG: CYAN + LOG_FORMAT + RESET,
        logging.INFO: GREEN + LOG_FORMAT + RESET,
        logging.WARNING: YELLOW + LOG_FORMAT + RESET,
        logging.ERROR: RED + LOG_FORMAT + RESET,
        logging.CRITICAL: BOLD_RED + LOG_FORMAT + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.LOG_FORMAT)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


class TradingLogger:
    """
    Centralized logging system for trading operations with async I/O

    Features:
    - Multi-handler logging (console, file, trade-specific)
    - Automatic log rotation (size-based and time-based)
    - Structured JSON logging for trade events
    - Performance measurement utilities
    - QueueHandler + QueueListener for non-blocking I/O

    Performance:
    - Hot path logging is non-blocking via QueueHandler
    - Actual I/O happens in separate thread via QueueListener
    - Prevents event loop blocking and disk I/O latency
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
        self.log_level = config.get("log_level", "INFO")

        # Always use project root's logs/ directory for consistency
        # regardless of execution location (PyCharm, terminal, background)
        project_root = Path(__file__).resolve().parent.parent.parent
        default_log_dir = project_root / "logs"

        # If config specifies log_dir, interpret as relative to project root
        # unless it's an absolute path
        config_log_dir = config.get("log_dir", str(default_log_dir))
        self.log_dir = Path(config_log_dir)
        if not self.log_dir.is_absolute():
            self.log_dir = project_root / self.log_dir

        self.log_dir.mkdir(exist_ok=True)

        # QueueListener for async logging (must be stored for cleanup)
        self.queue_listener: Optional[QueueListener] = None

        self._setup_logging()

    def _setup_logging(self) -> None:
        """
        Configure root logger with QueueHandler + QueueListener pattern

        Architecture:
        1. QueueHandler attached to root logger (fast, non-blocking)
        2. QueueListener with actual I/O handlers (runs in separate thread)
        3. Console handler (INFO+, simple format)
        4. Rotating file handler (DEBUG+, detailed format)

        Performance benefits:
        - Hot path: O(1) queue.put() - microseconds
        - I/O thread: Handles disk/console writes asynchronously
        - No blocking on event loop or main thread

        Thread-safe: Queue is thread-safe, listener runs in dedicated thread
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.log_level.upper()))

        # Clear existing handlers to avoid duplicates
        root_logger.handlers.clear()

        # Step 1: Create queue for async logging
        log_queue = queue.Queue(maxsize=-1)  # Unlimited queue size

        # Step 2: Create actual I/O handlers (will run in listener thread)
        # Console Handler - INFO and above
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.log_level.upper()))
        console_handler.setFormatter(ColorFormatter())

        # File Handler - All levels, rotating (10MB max, 5 backups)
        file_handler = RotatingFileHandler(
            self.log_dir / "trading.log", maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
        )
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
        )
        file_handler.setFormatter(file_format)

        # Step 3: Create QueueListener with I/O handlers
        # Listener will process queue in separate thread
        self.queue_listener = QueueListener(
            log_queue,
            console_handler,
            file_handler,
            respect_handler_level=True,  # Honor each handler's level
        )
        self.queue_listener.start()

        # Step 4: Attach QueueHandler to root logger
        # All log calls now go to queue (fast, non-blocking)
        queue_handler = QueueHandler(log_queue)
        root_logger.addHandler(queue_handler)

        # Step 5: Silence external library noise (e.g. websocket closing warnings)
        logging.getLogger("binance").setLevel(logging.ERROR)
        logging.getLogger("urllib3").setLevel(logging.ERROR)

        # Note: Trade events are logged to logs/audit/*.jsonl via AuditLogger
        # for structured compliance logging and analysis

    def stop(self) -> None:
        """
        Stop QueueListener and flush remaining logs

        Call this during shutdown to ensure all queued logs are written.
        The listener will process remaining queue items before stopping.
        """
        if self.queue_listener:
            self.queue_listener.stop()
            self.queue_listener = None


@contextmanager
def log_execution_time(operation: str) -> Generator[None, None, None]:
    """
    Context manager for measuring and logging execution time

    Args:
        operation: Human-readable operation description

    Usage:
        with log_execution_time('detector_calculation'):
            result = calculate_detectors()

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
        "setup_logger() is deprecated. Use TradingLogger class.", DeprecationWarning, stacklevel=2
    )
    return logging.getLogger(name)
