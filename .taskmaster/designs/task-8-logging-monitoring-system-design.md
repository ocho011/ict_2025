# 📐 Logging & Monitoring System Design Specification

**Task ID**: #8
**Task Title**: Logging & Monitoring System
**Design Date**: 2025-12-18
**Status**: Design Complete, Ready for Implementation

---

## 1. System Architecture Overview

### 1.1 Design Goals
- **Centralized Logging**: Single TradingLogger class managing all logging infrastructure
- **Multi-Channel Output**: Console, rotating files, and trade-specific logs
- **Structured Data**: JSON format for trade events enabling easy parsing and analysis
- **Performance Monitoring**: Built-in execution time tracking
- **Thread-Safe**: Support concurrent trading operations
- **Zero Dependencies**: Use Python's stdlib only (no external logging libraries)

### 1.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     TradingLogger                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Configuration Management                  │  │
│  │  - log_level (INFO/DEBUG)                            │  │
│  │  - log_dir (logs/)                                   │  │
│  │  - Console/File handler setup                        │  │
│  └───────────────────────────────────────────────────────┘  │
│                          │                                   │
│        ┌─────────────────┼─────────────────┐               │
│        ▼                 ▼                 ▼               │
│  ┌──────────┐   ┌──────────────┐   ┌────────────┐        │
│  │ Console  │   │ Rotating     │   │ Trade      │        │
│  │ Handler  │   │ File Handler │   │ Handler    │        │
│  │          │   │              │   │            │        │
│  │ INFO+    │   │ DEBUG+       │   │ INFO       │        │
│  │ Stream   │   │ 10MB/5files  │   │ Daily/30d  │        │
│  └──────────┘   └──────────────┘   └────────────┘        │
│       │               │                   │               │
│       ▼               ▼                   ▼               │
│   stdout      logs/trading.log    logs/trades.log        │
└─────────────────────────────────────────────────────────────┘

Additional Utilities:
┌──────────────────────────────────┐
│  log_execution_time()            │
│  Context manager for performance │
│  tracking (DEBUG level)          │
└──────────────────────────────────┘
```

## 2. Component Specifications

### 2.1 TradingLogger Class

**File**: `src/utils/logger.py`

**Responsibilities**:
- Initialize and configure logging infrastructure
- Manage multiple log handlers (console, file, trade-specific)
- Provide static methods for structured trade logging
- Ensure thread-safe logging operations

**Interface Design**:

```python
class TradingLogger:
    """
    Centralized logging system for trading operations

    Features:
    - Multi-handler logging (console, file, trade-specific)
    - Automatic log rotation (size-based and time-based)
    - Structured JSON logging for trade events
    - Performance measurement utilities
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize logging infrastructure

        Args:
            config: Configuration dictionary with keys:
                - log_level: str (DEBUG, INFO, WARNING, ERROR)
                - log_dir: str (directory path for log files)

        Raises:
            OSError: If log directory creation fails
        """

    def _setup_logging(self) -> None:
        """
        Configure root logger with all handlers

        Sets up:
        1. Console handler (INFO+, simple format)
        2. Rotating file handler (DEBUG+, detailed format)
        3. Trade-specific handler (INFO, JSON format, time-based rotation)

        Thread-safe: Uses logging module's built-in thread safety
        """

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
```

### 2.2 Handler Configuration Specifications

#### Console Handler
```python
Handler: StreamHandler(sys.stdout)
Level: INFO
Format: '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
DateFormat: '%Y-%m-%d %H:%M:%S'
Purpose: Real-time monitoring during development/production
```

**Output Example**:
```
2025-12-18 10:30:45 | INFO     | trading.signals      | LONG signal generated for BTCUSDT
2025-12-18 10:30:46 | WARNING  | trading.risk         | Position size exceeds 5% of portfolio
```

#### Rotating File Handler
```python
Handler: RotatingFileHandler
File: logs/trading.log
Level: DEBUG
MaxBytes: 10485760 (10MB)
BackupCount: 5
Format: '%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s'
Purpose: Comprehensive debugging and audit trail
```

**Output Example**:
```
2025-12-18 10:30:45 | DEBUG    | trading.indicators:142 | Calculating SMA for period=20
2025-12-18 10:30:45 | INFO     | trading.signals:87 | LONG signal generated for BTCUSDT
```

**Rotation Behavior**:
- When trading.log reaches 10MB → rename to trading.log.1
- Existing trading.log.1 → trading.log.2 (up to .5)
- trading.log.5 deleted when rotation occurs

#### Trade Log Handler
```python
Handler: TimedRotatingFileHandler
File: logs/trades.log
Level: INFO
When: 'midnight'
BackupCount: 30
Filter: TradeLogFilter (only 'trades' logger)
Format: Raw JSON (no standard formatter)
Purpose: Structured trade data for analysis and reporting
```

**Output Example**:
```json
{"timestamp": "2025-12-18T10:30:45.123456", "action": "SIGNAL_GENERATED", "symbol": "BTCUSDT", "type": "LONG_ENTRY", "entry": 50000.0, "tp": 51000.0, "sl": 49500.0, "strategy": "MockSMA"}
{"timestamp": "2025-12-18T10:30:47.234567", "action": "ORDER_FILLED", "symbol": "BTCUSDT", "order_id": "12345", "side": "BUY", "quantity": 0.1, "price": 50010.0}
```

**Rotation Behavior**:
- Daily rotation at midnight (local time)
- Format: trades.log.2025-12-17, trades.log.2025-12-16, etc.
- Keeps 30 days of history, then auto-deletes oldest

### 2.3 TradeLogFilter

**Purpose**: Ensure trade logs only contain events from the 'trades' logger

```python
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
```

### 2.4 Performance Logging Utility

```python
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
    yield
    elapsed = time.perf_counter() - start
    logging.debug(f"{operation} completed in {elapsed:.3f}s")
```

## 3. Integration Specifications

### 3.1 Configuration Integration

**Update** `src/utils/config.py` to include logging configuration:

```python
@dataclass
class LoggingConfig:
    """Logging system configuration"""
    log_level: str = "INFO"
    log_dir: str = "logs"

    def __post_init__(self):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            raise ConfigurationError(
                f"Invalid log level: {self.log_level}. "
                f"Must be one of {valid_levels}"
            )

class ConfigManager:
    # Add to existing class
    def _load_logging_config(self) -> LoggingConfig:
        """Load logging configuration from INI file"""
        config_file = self.config_dir / "trading_config.ini"

        if not config_file.exists():
            return LoggingConfig()  # Use defaults

        config = ConfigParser()
        config.read(config_file)

        if "logging" not in config:
            return LoggingConfig()  # Use defaults

        logging_section = config["logging"]

        return LoggingConfig(
            log_level=logging_section.get("log_level", "INFO"),
            log_dir=logging_section.get("log_dir", "logs")
        )

    @property
    def logging_config(self) -> LoggingConfig:
        """Get logging configuration"""
        return self._logging_config
```

**Update** `configs/trading_config.ini`:

```ini
[logging]
log_level = INFO
log_dir = logs
```

### 3.2 Application Startup Integration

**Update** `src/main.py`:

```python
from src.utils.logger import TradingLogger
from src.utils.config import ConfigManager

def main():
    # Load configuration
    config_manager = ConfigManager()
    config_manager.validate()

    # Initialize logging system
    logger = TradingLogger({
        'log_level': config_manager.logging_config.log_level,
        'log_dir': config_manager.logging_config.log_dir
    })

    # Get application logger
    app_logger = logging.getLogger('trading.main')
    app_logger.info("Trading system starting...")

    # Rest of application initialization
    ...
```

## 4. Usage Patterns

### 4.1 General Logging

```python
import logging

# Module-level logger
logger = logging.getLogger('trading.signals')

# Usage
logger.debug("Analyzing price action for BTCUSDT")
logger.info("LONG signal generated at 50000.0")
logger.warning("Risk threshold approaching")
logger.error("Failed to fetch market data", exc_info=True)
```

### 4.2 Trade Event Logging

```python
from src.utils.logger import TradingLogger

# Signal generation
TradingLogger.log_trade('SIGNAL_GENERATED', {
    'symbol': 'BTCUSDT',
    'type': 'LONG_ENTRY',
    'entry': 50000.0,
    'tp': 51000.0,
    'sl': 49500.0,
    'strategy': 'MockSMA',
    'risk_reward': 2.0
})

# Order execution
TradingLogger.log_trade('ORDER_PLACED', {
    'symbol': 'BTCUSDT',
    'order_id': 'temp_12345',
    'side': 'BUY',
    'quantity': 0.1,
    'price': 50010.0,
    'order_type': 'LIMIT'
})

# Order filled
TradingLogger.log_trade('ORDER_FILLED', {
    'symbol': 'BTCUSDT',
    'order_id': '12345',
    'side': 'BUY',
    'quantity': 0.1,
    'price': 50010.0,
    'fill_time': datetime.utcnow().isoformat()
})

# Position closed
TradingLogger.log_trade('POSITION_CLOSED', {
    'symbol': 'BTCUSDT',
    'position_id': 'pos_789',
    'entry_price': 50010.0,
    'exit_price': 51000.0,
    'pnl': 99.0,
    'pnl_percent': 1.98,
    'reason': 'TAKE_PROFIT'
})
```

### 4.3 Performance Logging

```python
from src.utils.logger import log_execution_time
import logging

logger = logging.getLogger('trading.indicators')

with log_execution_time('SMA calculation'):
    sma_values = calculate_sma(prices, period=20)

with log_execution_time('Complete signal generation'):
    signals = strategy.generate_signals(df)
```

## 5. Testing Strategy

### 5.1 Unit Tests

**File**: `tests/test_logger.py`

```python
import pytest
import tempfile
from pathlib import Path
from src.utils.logger import TradingLogger, TradeLogFilter
import logging
import json

class TestTradingLogger:
    def test_log_directory_creation(self):
        """Verify log directory is created if it doesn't exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': f'{tmpdir}/logs'}
            logger = TradingLogger(config)
            assert Path(f'{tmpdir}/logs').exists()

    def test_handler_configuration(self):
        """Verify all handlers are configured correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': f'{tmpdir}/logs'}
            logger = TradingLogger(config)

            root_logger = logging.getLogger()
            assert len(root_logger.handlers) == 3  # Console, file, trade

            # Verify handler types and levels
            handlers = {type(h).__name__: h for h in root_logger.handlers}
            assert 'StreamHandler' in handlers
            assert 'RotatingFileHandler' in handlers
            assert 'TimedRotatingFileHandler' in handlers

    def test_log_rotation_size(self):
        """Test rotating file handler triggers at 10MB"""
        # Implementation: Write > 10MB to log, verify rotation
        pass

    def test_trade_log_filter(self):
        """Verify TradeLogFilter only passes 'trades' logger records"""
        filter_obj = TradeLogFilter()

        trade_record = logging.LogRecord(
            name='trades', level=logging.INFO, pathname='', lineno=0,
            msg='test', args=(), exc_info=None
        )
        system_record = logging.LogRecord(
            name='trading.signals', level=logging.INFO, pathname='',
            lineno=0, msg='test', args=(), exc_info=None
        )

        assert filter_obj.filter(trade_record) is True
        assert filter_obj.filter(system_record) is False

    def test_structured_trade_logging(self):
        """Verify trade logs are valid JSON with required fields"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'INFO', 'log_dir': f'{tmpdir}/logs'}
            logger = TradingLogger(config)

            TradingLogger.log_trade('TEST_ACTION', {
                'symbol': 'BTCUSDT',
                'price': 50000.0
            })

            # Read trade log file
            log_file = Path(f'{tmpdir}/logs/trades.log')
            assert log_file.exists()

            with open(log_file) as f:
                log_entry = json.loads(f.readline())

            assert 'timestamp' in log_entry
            assert log_entry['action'] == 'TEST_ACTION'
            assert log_entry['symbol'] == 'BTCUSDT'
            assert log_entry['price'] == 50000.0

    def test_execution_time_logging(self):
        """Verify performance logging accuracy"""
        import time
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {'log_level': 'DEBUG', 'log_dir': f'{tmpdir}/logs'}
            logger = TradingLogger(config)

            from src.utils.logger import log_execution_time

            with log_execution_time('test_operation'):
                time.sleep(0.1)  # 100ms delay

            # Verify log entry exists with timing (~100ms ±10ms tolerance)
            # Implementation: Read log file and verify timing
            pass
```

### 5.2 Integration Tests

```python
def test_logging_in_trading_workflow(self):
    """Test logging throughout complete trading workflow"""
    # Initialize system with logging
    # Generate signal → verify signal logged
    # Place order → verify order logged
    # Fill order → verify fill logged
    # Close position → verify closure logged
    # Verify all logs in correct files with correct formats
    pass
```

## 6. Performance Considerations

### 6.1 Thread Safety
- Python's `logging` module is thread-safe by default
- All handlers use internal locks for concurrent access
- No additional synchronization required

### 6.2 Performance Impact
- **Console logging**: ~10-50 microseconds per log call
- **File logging**: ~50-200 microseconds per log call (buffered I/O)
- **JSON serialization**: ~5-20 microseconds per trade log

**Recommendations**:
- Use appropriate log levels (DEBUG for development, INFO for production)
- Avoid excessive logging in hot paths (e.g., per-tick market data processing)
- Use `log_execution_time` sparingly for performance-critical sections

### 6.3 Disk Space Management

**Estimated disk usage**:
- `trading.log`: 5 rotations × 10MB = 50MB maximum
- `trades.log`: 30 days × ~1-5MB/day = 30-150MB
- **Total**: ~80-200MB for complete log history

**Cleanup strategy**:
- Automatic via `backupCount` parameters
- Manual: Delete old `*.log.*` files if needed

## 7. Migration from Current Implementation

**Current state** (`src/utils/logger.py`):
- Simple `setup_logger()` function
- Basic console + file handler
- No rotation, no trade-specific logging
- No structured logging

**Migration steps**:
1. **Subtask 8.1**: Replace `setup_logger()` with `TradingLogger` class
2. **Subtask 8.2**: Add trade log handler and filter
3. **Subtask 8.3**: Add `log_trade()` static method
4. **Subtask 8.4**: Add `log_execution_time()` utility

**Breaking changes**:
- Applications using `setup_logger()` must update to initialize `TradingLogger`
- Update all logger initialization in existing modules

**Backwards compatibility strategy**:
```python
# Deprecated wrapper for backwards compatibility
def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """
    DEPRECATED: Use TradingLogger class instead

    Temporary wrapper for backwards compatibility
    """
    warnings.warn(
        "setup_logger() is deprecated. Use TradingLogger class.",
        DeprecationWarning,
        stacklevel=2
    )
    return logging.getLogger(name)
```

## 8. Future Enhancements (Out of Scope for Task #8)

- Remote logging (syslog, cloud logging services)
- Log aggregation and centralized monitoring
- Real-time log streaming to dashboard
- Alert notifications based on log patterns (ERROR threshold)
- Log analysis and anomaly detection
- Encrypted logging for sensitive data
- Async logging for ultra-high performance scenarios

---

## Summary

This design provides a **production-ready logging system** that:

✅ Supports multiple output channels (console, files, trade-specific)
✅ Implements proper log rotation (size-based and time-based)
✅ Provides structured JSON logging for trade events
✅ Includes performance measurement utilities
✅ Maintains thread safety for concurrent operations
✅ Integrates cleanly with existing configuration system
✅ Follows Python logging best practices
✅ Zero external dependencies (stdlib only)

The design is ready for implementation following the 4 subtasks outlined in Task #8.

## Implementation Checklist

- [ ] **Subtask 8.1**: TradingLogger class with console and file handlers
  - [ ] Initialize log directory
  - [ ] Configure root logger
  - [ ] Set up console handler (INFO level)
  - [ ] Set up rotating file handler (DEBUG level, 10MB/5 backups)
  - [ ] Test log directory creation
  - [ ] Test handler configuration
  - [ ] Test log rotation at 10MB

- [ ] **Subtask 8.2**: Trade-specific logging with TimedRotatingFileHandler
  - [ ] Implement TradeLogFilter class
  - [ ] Set up timed rotating handler (midnight/30 days)
  - [ ] Apply filter to trade handler
  - [ ] Test filter functionality
  - [ ] Test time-based rotation
  - [ ] Test backup retention

- [ ] **Subtask 8.3**: Structured JSON trade logging
  - [ ] Implement log_trade() static method
  - [ ] Add timestamp to log entries
  - [ ] JSON serialization of trade data
  - [ ] Test JSON format validation
  - [ ] Test various trade action types
  - [ ] Test data dictionary unpacking

- [ ] **Subtask 8.4**: Performance logging utilities
  - [ ] Implement log_execution_time() context manager
  - [ ] Use time.perf_counter() for accuracy
  - [ ] Format elapsed time output
  - [ ] Test timing accuracy (±10ms tolerance)
  - [ ] Test DEBUG level logging
  - [ ] Test exception handling

- [ ] **Configuration Integration**
  - [ ] Add LoggingConfig dataclass to config.py
  - [ ] Add _load_logging_config() method
  - [ ] Update trading_config.ini with [logging] section
  - [ ] Test config loading

- [ ] **Application Integration**
  - [ ] Update main.py to initialize TradingLogger
  - [ ] Test logging in complete workflow
  - [ ] Verify all log files created correctly

- [ ] **Testing**
  - [ ] Write all unit tests from section 5.1
  - [ ] Write integration tests from section 5.2
  - [ ] Verify test coverage > 90%
  - [ ] Run performance benchmarks
