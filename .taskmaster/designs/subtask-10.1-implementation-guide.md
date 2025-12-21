# Subtask 10.1: TradingBot Class Structure & initialize() Implementation Guide

## Overview

Implement the TradingBot class skeleton with proper component initialization sequence. This is the foundation for all other Task 10 subtasks.

## File to Modify

- **Primary**: `src/main.py` - Complete rewrite

## Design Principles

1. **Separation of Concerns**: `__init__()` does minimal setup, `initialize()` performs heavy lifting
2. **Fail Fast**: Configuration validation happens early before component initialization
3. **Clear Error Messages**: All failures provide actionable error information
4. **Logging First**: Setup logging before other components for complete audit trail
5. **Dependency Order**: Components initialized in correct dependency sequence

## Class Structure

```python
class TradingBot:
    """
    Main trading bot orchestrator that manages all system components.

    Lifecycle:
        1. __init__() - Minimal constructor setup
        2. initialize() - 10-step component initialization
        3. run() - Async runtime loop (implemented in Subtask 10.5)
        4. shutdown() - Graceful cleanup (implemented in Subtask 10.4)
    """

    # Component references (all initialized to None in __init__)
    config_manager: Optional[ConfigManager]
    event_bus: Optional[EventBus]
    data_collector: Optional[BinanceDataCollector]
    order_manager: Optional[OrderExecutionManager]
    risk_manager: Optional[RiskManager]
    strategy: Optional[BaseStrategy]
    logger: Optional[logging.Logger]

    # State management
    _running: bool
```

## Required Imports

```python
import asyncio
import signal
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.utils.config import ConfigManager
from src.utils.logger import TradingLogger
from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.strategies import StrategyFactory
from src.execution.order_manager import OrderExecutionManager
from src.risk.manager import RiskManager
from src.models.event import Event, EventType
from src.models.candle import Candle
from src.models.signal import Signal
from src.models.order import Order
```

## Implementation Details

### 1. `__init__()` Method

**Purpose**: Minimal constructor - initialize all components to None

```python
def __init__(self) -> None:
    """
    Constructor - minimal initialization.

    Heavy initialization deferred to initialize() method for better
    error handling and separation of concerns.
    """
    # Components (initialized in initialize())
    self.config_manager: Optional[ConfigManager] = None
    self.event_bus: Optional[EventBus] = None
    self.data_collector: Optional[BinanceDataCollector] = None
    self.order_manager: Optional[OrderExecutionManager] = None
    self.risk_manager: Optional[RiskManager] = None
    self.strategy: Optional[BaseStrategy] = None
    self.logger: Optional[logging.Logger] = None

    # State management
    self._running: bool = False
```

**Key Points**:
- All components explicitly typed as Optional
- No I/O operations or heavy computation
- State flag `_running` initialized to False
- No logging yet (logger not configured)

### 2. `initialize()` Method - 10-Step Sequence

**Purpose**: Initialize all system components in correct dependency order

```python
def initialize(self) -> None:
    """
    Initialize all trading bot components in correct dependency order.

    10-Step Initialization Sequence:
        1. ConfigManager - Load all configurations
        2. Validate - Ensure config is valid before proceeding
        3. TradingLogger - Setup logging infrastructure
        4. Startup Banner - Log environment information
        5. BinanceDataCollector - WebSocket client with callback
        6. OrderExecutionManager - Order execution interface
        7. RiskManager - Risk validation and position sizing
        8. StrategyFactory - Create strategy instance
        9. EventBus - Event coordination system
        10. Leverage Setup - Configure account leverage

    Raises:
        ValueError: If configuration validation fails
        Exception: For any component initialization failure

    Note:
        - Uses testnet by default for safety
        - Logs comprehensive startup information
        - Fails fast on configuration errors
    """
    # Step 1: Load configurations
    self.config_manager = ConfigManager()
    api_config = self.config_manager.api_config
    trading_config = self.config_manager.trading_config
    logging_config = self.config_manager.logging_config

    # Step 2: Validate configuration (fail fast)
    if not self.config_manager.validate():
        raise ValueError(
            "Invalid configuration. Check configs/api_keys.ini and "
            "configs/trading_config.ini for missing or invalid settings."
        )

    # Step 3: Setup logging infrastructure
    TradingLogger(logging_config.__dict__)
    self.logger = logging.getLogger(__name__)

    # Step 4: Log startup banner with environment info
    self.logger.info("=" * 50)
    self.logger.info("ICT Trading Bot Starting...")
    self.logger.info(f"Environment: {'TESTNET' if api_config.is_testnet else 'MAINNET'}")
    self.logger.info(f"Symbol: {trading_config.symbol}")
    self.logger.info(f"Intervals: {', '.join(trading_config.intervals)}")
    self.logger.info(f"Strategy: {trading_config.strategy}")
    self.logger.info(f"Leverage: {trading_config.leverage}x")
    self.logger.info(f"Max Risk per Trade: {trading_config.max_risk_per_trade * 100:.1f}%")
    self.logger.info("=" * 50)

    # Step 5: Initialize BinanceDataCollector with candle callback
    self.logger.info("Initializing BinanceDataCollector...")
    self.data_collector = BinanceDataCollector(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        symbols=[trading_config.symbol],
        intervals=trading_config.intervals,
        is_testnet=api_config.is_testnet,
        on_candle_callback=self._on_candle_received  # Bridge to EventBus (Subtask 10.2)
    )

    # Step 6: Initialize OrderExecutionManager
    self.logger.info("Initializing OrderExecutionManager...")
    self.order_manager = OrderExecutionManager(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        is_testnet=api_config.is_testnet
    )

    # Step 7: Initialize RiskManager
    self.logger.info("Initializing RiskManager...")
    self.risk_manager = RiskManager({
        'max_risk_per_trade': trading_config.max_risk_per_trade,
        'default_leverage': trading_config.leverage,
        'max_leverage': 20,  # Hard limit
        'max_position_size_percent': 0.1  # 10% of account
    })

    # Step 8: Create strategy instance via StrategyFactory
    self.logger.info(f"Creating strategy: {trading_config.strategy}...")
    self.strategy = StrategyFactory.create(
        name=trading_config.strategy,
        symbol=trading_config.symbol,
        config={
            'buffer_size': 100,
            'risk_reward_ratio': trading_config.take_profit_ratio,
            'stop_loss_percent': trading_config.stop_loss_percent
        }
    )

    # Step 9: Initialize EventBus
    self.logger.info("Initializing EventBus...")
    self.event_bus = EventBus()

    # Step 10: Setup event handlers and leverage
    self.logger.info("Setting up event handlers...")
    self._setup_event_handlers()  # Implemented in Subtask 10.2

    self.logger.info("Configuring leverage...")
    success = self.order_manager.set_leverage(
        trading_config.symbol,
        trading_config.leverage
    )
    if not success:
        self.logger.warning(
            f"Failed to set leverage to {trading_config.leverage}x. "
            "Using current account leverage."
        )

    self.logger.info("✅ All components initialized successfully")
```

**Critical Implementation Notes**:

1. **Configuration Access Pattern**:
   ```python
   # Correct: Use properties
   api_config = self.config_manager.api_config
   trading_config = self.config_manager.trading_config

   # Incorrect: Direct access to private attributes
   api_config = self.config_manager._api_config  # Don't do this
   ```

2. **Callback Reference**:
   ```python
   # Pass method reference (not called yet)
   on_candle_callback=self._on_candle_received

   # NOT: on_candle_callback=self._on_candle_received()  # Wrong - calls immediately
   ```

3. **Error Handling**:
   - ConfigManager.validate() returns bool, not raising exception
   - Must manually raise ValueError with clear message
   - Leverage setup failure is logged as warning (non-fatal)

4. **Logging Progression**:
   - Log each major step for debugging
   - Use INFO level for normal operations
   - Startup banner provides complete environment snapshot

## Component Initialization Parameters

### ConfigManager
```python
ConfigManager()  # No parameters - auto-loads from configs/
```
- Loads from `configs/api_keys.ini` and `configs/trading_config.ini`
- Properties: `api_config`, `trading_config`, `logging_config`

### TradingLogger
```python
TradingLogger(logging_config.__dict__)
```
- Expects dict with: `log_level`, `log_dir`, `console_enabled`, `file_enabled`
- Sets up console, file, and trade log handlers

### BinanceDataCollector
```python
BinanceDataCollector(
    api_key=str,
    api_secret=str,
    symbols=List[str],           # e.g., ['BTCUSDT']
    intervals=List[str],          # e.g., ['1m', '5m', '1h']
    is_testnet=bool,
    on_candle_callback=callable  # Signature: (Candle) -> None
)
```
- Constructor does NOT start streaming
- Callback invoked on every candle update
- WebSocket initialized lazily in `start_streaming()`

### OrderExecutionManager
```python
OrderExecutionManager(
    api_key=str,
    api_secret=str,
    is_testnet=bool
)
```
- Can also use environment variables: BINANCE_API_KEY, BINANCE_API_SECRET
- Initializes UMFutures client with weight tracking enabled

### RiskManager
```python
RiskManager(config=dict)
```
- Required keys: `max_risk_per_trade`, `default_leverage`
- Optional: `max_leverage`, `max_position_size_percent`

### StrategyFactory
```python
StrategyFactory.create(
    name=str,        # e.g., 'mock_sma', 'ict_fvg'
    symbol=str,      # e.g., 'BTCUSDT'
    config=dict      # Strategy-specific parameters
)
```
- Raises ValueError if strategy name not registered
- Returns BaseStrategy instance

### EventBus
```python
EventBus()  # No parameters
```
- Creates 3 queues: data(1000), signal(100), order(50)
- Not started yet (started in `run()` method)

## Stub Methods (Implemented in Later Subtasks)

```python
def _setup_event_handlers(self) -> None:
    """
    Wire up event subscriptions. Implemented in Subtask 10.2.
    """
    pass

def _on_candle_received(self, candle: Candle) -> None:
    """
    Callback from BinanceDataCollector. Implemented in Subtask 10.2.

    Args:
        candle: Candle data from WebSocket stream
    """
    pass

async def run(self) -> None:
    """
    Main runtime loop. Implemented in Subtask 10.5.
    """
    pass

async def shutdown(self) -> None:
    """
    Graceful shutdown. Implemented in Subtask 10.4.
    """
    pass
```

## Testing Strategy

### Unit Tests

**Test File**: `tests/test_main_initialization.py`

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from src.main import TradingBot

class TestTradingBotInitialization:

    def test_constructor_initializes_components_to_none(self):
        """Test __init__ sets all components to None."""
        bot = TradingBot()

        assert bot.config_manager is None
        assert bot.event_bus is None
        assert bot.data_collector is None
        assert bot.order_manager is None
        assert bot.risk_manager is None
        assert bot.strategy is None
        assert bot.logger is None
        assert bot._running is False

    @patch('src.main.ConfigManager')
    @patch('src.main.TradingLogger')
    @patch('src.main.BinanceDataCollector')
    @patch('src.main.OrderExecutionManager')
    @patch('src.main.RiskManager')
    @patch('src.main.StrategyFactory')
    @patch('src.main.EventBus')
    def test_initialize_with_valid_config(
        self,
        mock_event_bus,
        mock_strategy_factory,
        mock_risk_manager,
        mock_order_manager,
        mock_data_collector,
        mock_trading_logger,
        mock_config_manager
    ):
        """Test successful initialization with valid config."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(
            api_key='test_key',
            api_secret='test_secret',
            is_testnet=True
        )
        config_instance.trading_config = Mock(
            symbol='BTCUSDT',
            intervals=['1m', '5m'],
            strategy='mock_sma',
            leverage=10,
            max_risk_per_trade=0.01,
            take_profit_ratio=2.0,
            stop_loss_percent=0.01
        )
        config_instance.logging_config = Mock()
        mock_config_manager.return_value = config_instance

        mock_order_instance = Mock()
        mock_order_instance.set_leverage.return_value = True
        mock_order_manager.return_value = mock_order_instance

        # Execute
        bot = TradingBot()
        bot.initialize()

        # Verify initialization order
        assert mock_config_manager.called
        assert config_instance.validate.called
        assert mock_trading_logger.called
        assert mock_data_collector.called
        assert mock_order_manager.called
        assert mock_risk_manager.called
        assert mock_strategy_factory.create.called
        assert mock_event_bus.called

        # Verify components are set
        assert bot.config_manager is not None
        assert bot.event_bus is not None
        assert bot.data_collector is not None
        assert bot.order_manager is not None
        assert bot.risk_manager is not None
        assert bot.strategy is not None

    @patch('src.main.ConfigManager')
    def test_initialize_fails_with_invalid_config(self, mock_config_manager):
        """Test initialize raises ValueError on invalid config."""
        config_instance = Mock()
        config_instance.validate.return_value = False
        mock_config_manager.return_value = config_instance

        bot = TradingBot()

        with pytest.raises(ValueError, match="Invalid configuration"):
            bot.initialize()

    @patch('src.main.ConfigManager')
    @patch('src.main.TradingLogger')
    def test_initialize_logs_startup_banner(
        self,
        mock_trading_logger,
        mock_config_manager
    ):
        """Test initialization logs comprehensive startup information."""
        # Setup mocks
        config_instance = Mock()
        config_instance.validate.return_value = True
        config_instance.api_config = Mock(is_testnet=True)
        config_instance.trading_config = Mock(
            symbol='BTCUSDT',
            intervals=['1m', '5m'],
            strategy='mock_sma',
            leverage=10,
            max_risk_per_trade=0.01
        )
        config_instance.logging_config = Mock()
        mock_config_manager.return_value = config_instance

        # Mock logger
        mock_logger = Mock()
        with patch('logging.getLogger', return_value=mock_logger):
            bot = TradingBot()
            with patch.object(bot, '_setup_event_handlers'):
                bot.initialize()

        # Verify startup banner logged
        assert any('ICT Trading Bot Starting' in str(call)
                  for call in mock_logger.info.call_args_list)
        assert any('TESTNET' in str(call)
                  for call in mock_logger.info.call_args_list)
        assert any('BTCUSDT' in str(call)
                  for call in mock_logger.info.call_args_list)
```

### Manual Testing Checklist

- [ ] Run with valid testnet configuration
- [ ] Verify all startup logs appear in console
- [ ] Check log file created in `logs/` directory
- [ ] Test with missing config file → ValueError
- [ ] Test with invalid API keys → initialization error
- [ ] Verify leverage set successfully in account
- [ ] Check all components are instantiated (add debug breakpoint)

## Common Pitfalls & Solutions

### Pitfall 1: Calling Methods Instead of Passing References

❌ **Wrong**:
```python
on_candle_callback=self._on_candle_received()  # Calls immediately, passes return value
```

✅ **Correct**:
```python
on_candle_callback=self._on_candle_received  # Passes method reference
```

### Pitfall 2: Accessing Private Config Attributes

❌ **Wrong**:
```python
api_config = self.config_manager._api_config
```

✅ **Correct**:
```python
api_config = self.config_manager.api_config  # Use property
```

### Pitfall 3: Not Converting Logging Config to Dict

❌ **Wrong**:
```python
TradingLogger(logging_config)  # Passes LoggingConfig object
```

✅ **Correct**:
```python
TradingLogger(logging_config.__dict__)  # Converts to dict
```

### Pitfall 4: Forgetting to Check validate() Return Value

❌ **Wrong**:
```python
self.config_manager.validate()  # Returns False silently, continues
```

✅ **Correct**:
```python
if not self.config_manager.validate():
    raise ValueError("Invalid configuration")
```

## Integration with Other Subtasks

### Subtask 10.2 Dependencies

```python
def _setup_event_handlers(self) -> None:
    """Called in Step 10 of initialize()."""
    # Implemented in Subtask 10.2
    # Subscribes to EventType.CANDLE_CLOSED, SIGNAL_GENERATED, ORDER_FILLED

def _on_candle_received(self, candle: Candle) -> None:
    """Called by BinanceDataCollector on every candle update."""
    # Implemented in Subtask 10.2
    # Publishes Event to EventBus
```

### Subtask 10.4 Dependencies

```python
async def shutdown(self) -> None:
    """Cleanup all components initialized in initialize()."""
    # Implemented in Subtask 10.4
    # Calls data_collector.stop(), event_bus.shutdown()
```

### Subtask 10.5 Dependencies

```python
async def run(self) -> None:
    """Start all initialized components."""
    # Implemented in Subtask 10.5
    # Calls event_bus.start(), data_collector.start_streaming()
```

## Success Criteria

- ✅ TradingBot class compiles without errors
- ✅ `__init__()` method initializes all components to None
- ✅ `initialize()` completes successfully with valid config
- ✅ Configuration validation fails gracefully with ValueError
- ✅ All 7 components (ConfigManager, TradingLogger, DataCollector, OrderManager, RiskManager, Strategy, EventBus) initialized
- ✅ Startup banner logs environment, symbol, strategy information
- ✅ Leverage set successfully on OrderManager
- ✅ Unit tests pass with >90% coverage
- ✅ Integration ready for Subtask 10.2 (event handlers)

## Next Steps

After completing this subtask:
1. Mark Subtask 10.1 status as `done`
2. Begin Subtask 10.2: Implement event handler setup
3. Wire `_setup_event_handlers()` and `_on_candle_received()` methods
4. Test event flow from WebSocket → EventBus

## Reference Documents

- **Full Design**: `.taskmaster/designs/task-10-main-entry-point-design.md` (Section 4)
- **Quick Reference**: `.taskmaster/designs/TASK-10-QUICK-REFERENCE.md` (Lines 57-123)
- **Architecture**: `.taskmaster/designs/task-10-architecture-diagram.md` (Initialization Sequence)
