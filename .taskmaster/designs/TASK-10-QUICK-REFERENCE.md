# Task 10: Quick Implementation Reference

## Files to Create/Modify

### Primary File
- `src/main.py` - Complete rewrite with TradingBot class

## Class Structure

```python
class TradingBot:
    # Components (initialized in initialize())
    config_manager: ConfigManager
    event_bus: EventBus
    data_collector: BinanceDataCollector
    order_manager: OrderExecutionManager
    risk_manager: RiskManager
    strategy: BaseStrategy
    logger: logging.Logger
    _running: bool

    def __init__(self) -> None
    def initialize(self) -> None
    async def run(self) -> None
    async def shutdown(self) -> None

    def _setup_event_handlers(self) -> None
    def _on_candle_received(self, candle: Candle) -> None
    async def _on_candle_closed(self, event: Event) -> None
    async def _on_signal_generated(self, event: Event) -> None
    async def _on_order_filled(self, event: Event) -> None
```

## Required Imports

```python
import asyncio
import signal
import sys
import logging
from pathlib import Path
from datetime import datetime

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

## Initialization Sequence (10 Steps)

```python
def initialize(self) -> None:
    # 1. ConfigManager
    self.config_manager = ConfigManager()
    api_config = self.config_manager.api_config
    trading_config = self.config_manager.trading_config

    if not self.config_manager.validate():
        raise ValueError("Invalid configuration")

    # 2. TradingLogger
    TradingLogger(self.config_manager.logging_config.__dict__)
    self.logger = logging.getLogger(__name__)

    # 3. Startup Banner
    self.logger.info("=" * 50)
    self.logger.info("ICT Trading Bot Starting...")
    self.logger.info(f"Environment: {'TESTNET' if api_config.is_testnet else 'MAINNET'}")
    self.logger.info(f"Symbol: {trading_config.symbol}")
    self.logger.info(f"Strategy: {trading_config.strategy}")
    self.logger.info("=" * 50)

    # 4. BinanceDataCollector
    self.data_collector = BinanceDataCollector(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        symbols=[trading_config.symbol],
        intervals=trading_config.intervals,
        is_testnet=api_config.is_testnet,
        on_candle_callback=self._on_candle_received
    )

    # 5. OrderExecutionManager
    self.order_manager = OrderExecutionManager(
        api_key=api_config.api_key,
        api_secret=api_config.api_secret,
        is_testnet=api_config.is_testnet
    )

    # 6. RiskManager
    self.risk_manager = RiskManager({
        'max_risk_per_trade': trading_config.max_risk_per_trade,
        'default_leverage': trading_config.leverage
    })

    # 7. StrategyFactory
    self.strategy = StrategyFactory.create(
        name=trading_config.strategy,
        symbol=trading_config.symbol,
        config={
            'buffer_size': 100,
            'risk_reward_ratio': trading_config.take_profit_ratio,
            'stop_loss_percent': trading_config.stop_loss_percent
        }
    )

    # 8. EventBus
    self.event_bus = EventBus()

    # 9. Setup event handlers
    self._setup_event_handlers()

    # 10. Set leverage
    self.order_manager.set_leverage(trading_config.symbol, trading_config.leverage)
```

## Event Handler Wiring

```python
def _setup_event_handlers(self) -> None:
    self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
    self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal_generated)
    self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)
```

## Candle Callback

```python
def _on_candle_received(self, candle: Candle) -> None:
    event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE
    event = Event(event_type, candle)
    asyncio.create_task(self.event_bus.publish(event, queue_name='data'))
```

## Signal Processing Pipeline

```python
async def _on_candle_closed(self, event: Event) -> None:
    candle = event.data
    self.logger.debug(f"Candle closed: {candle.symbol} {candle.close}")

    signal = await self.strategy.analyze(candle)
    if signal:
        await self.event_bus.publish(
            Event(EventType.SIGNAL_GENERATED, signal),
            queue_name='signal'
        )

async def _on_signal_generated(self, event: Event) -> None:
    signal = event.data
    self.logger.info(f"Signal: {signal.signal_type.value} at {signal.entry_price}")

    # Validate
    current_position = self.order_manager.get_position(signal.symbol)
    if not self.risk_manager.validate_signal(signal, current_position):
        return

    # Calculate position size
    balance = self.order_manager.get_account_balance()
    quantity = self.risk_manager.calculate_position_size(
        account_balance=balance,
        entry_price=signal.entry_price,
        stop_loss_price=signal.stop_loss,
        leverage=self.config_manager.trading_config.leverage
    )

    # Execute
    try:
        entry_order, tpsl_orders = self.order_manager.execute_signal(signal, quantity)
        TradingLogger.log_trade('ORDER_EXECUTED', {
            'signal': signal.signal_type.value,
            'entry_order_id': entry_order.order_id,
            'quantity': quantity
        })
    except Exception as e:
        self.logger.error(f"Order execution failed: {e}")

async def _on_order_filled(self, event: Event) -> None:
    order = event.data
    self.logger.info(f"Order filled: {order.order_id}")
```

## Runtime & Shutdown

```python
async def run(self) -> None:
    self._running = True
    try:
        await asyncio.gather(
            self.event_bus.start(),
            self.data_collector.start_streaming()
        )
    except asyncio.CancelledError:
        self.logger.info("Shutdown requested...")
    finally:
        await self.shutdown()

async def shutdown(self) -> None:
    if not self._running:
        return

    self._running = False
    self.logger.info("Shutting down...")

    await self.data_collector.stop(timeout=5.0)
    await self.event_bus.shutdown(timeout=5.0)

    self.logger.info("Shutdown complete")
```

## Main Entry Point

```python
def main() -> None:
    bot = TradingBot()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.shutdown()))

    try:
        bot.initialize()
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        loop.close()

if __name__ == '__main__':
    main()
```

## Testing Checklist

### Unit Tests
- [ ] test_initialization_with_valid_config
- [ ] test_initialization_fails_with_missing_config
- [ ] test_shutdown_is_idempotent
- [ ] test_candle_callback_publishes_event

### Integration Tests
- [ ] test_full_candle_to_signal_flow
- [ ] test_graceful_shutdown_on_sigint
- [ ] test_event_bus_drains_queues_on_shutdown

### Manual Tests
- [ ] Start with testnet credentials
- [ ] Verify WebSocket connection
- [ ] Observe candle updates in logs
- [ ] Test Ctrl+C shutdown
- [ ] Check log files created
- [ ] Verify no resource leaks

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Import errors | Ensure all Task 3-9 components are implemented |
| Config not found | Check `configs/` directory exists with INI files |
| WebSocket fails | Verify API credentials and testnet flag |
| Shutdown hangs | Check timeout values (default 5s) |
| Memory leaks | Verify `stop()` called on all components |
| Signal not received | Check strategy returns Signal object |

## Documentation References

- Full Design: `.taskmaster/docs/review&memo/task-10-main-entry-point-design.md`
- Architecture: `.taskmaster/docs/review&memo/task-10-architecture-diagram.md`
- Memory: Serena memory `task-10-main-integration-design`
