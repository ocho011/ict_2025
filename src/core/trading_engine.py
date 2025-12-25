"""
TradingEngine: Main orchestrator for automated trading system.

Coordinates:
- Real-time data collection from Binance
- Strategy-based signal generation
- Order execution and position management
- Event-driven async pipeline with graceful shutdown
"""

import asyncio
import logging
from typing import Any, Optional

from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.execution.order_manager import OrderExecutionManager
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.utils.config import ConfigManager
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.models.signal import Signal
from src.models.order import Order


class TradingEngine:
    """
    Main application orchestrator for event-driven trading system.

    Responsibilities:
    1. Component lifecycle management (EventBus, DataCollector, Strategy, OrderManager)
    2. Event handler registration for trading pipeline
    3. Event routing: CANDLE_CLOSED → SIGNAL_GENERATED → ORDER_PLACED → ORDER_FILLED
    4. Graceful startup and shutdown with pending event processing
    5. Error isolation and logging

    Architecture:
        - Uses dependency injection for all components (testability)
        - Event-driven async pipeline prevents blocking
        - Error handlers prevent cascade failures
        - Graceful shutdown ensures order queue drains

    Lifecycle:
        ```python
        engine = TradingEngine(config)
        engine.set_data_collector(collector)
        engine.set_strategy(strategy)
        engine.set_order_manager(manager)

        await engine.run()  # Blocks until KeyboardInterrupt
        # Automatic shutdown with pending event processing
        ```

    Event Handlers:
        - _on_candle_closed: Candle → Strategy → Signal
        - _on_signal: Signal → OrderManager → Order
        - _on_order_filled: Order → Position update (future)
    """

    def __init__(self) -> None:
        """
        Initialize TradingEngine with minimal setup.

        Components are injected via set_components() method after construction.
        This allows for better testability and clear separation between
        bootstrap (TradingBot) and execution (TradingEngine).

        Attributes:
            logger: Logger instance for engine events
            event_bus: Optional[EventBus] (injected via set_components)
            data_collector: Optional[BinanceDataCollector] (injected via set_components)
            strategy: Optional[BaseStrategy] (injected via set_components)
            order_manager: Optional[OrderExecutionManager] (injected via set_components)
            risk_manager: Optional[RiskManager] (injected via set_components)
            config_manager: Optional[ConfigManager] (injected via set_components)
            _running: Runtime state flag

        Process Flow:
            1. Create logger
            2. Set component placeholders to None
            3. Wait for set_components() call

        Example:
            ```python
            engine = TradingEngine()
            engine.set_components(
                event_bus=event_bus,
                data_collector=collector,
                strategy=strategy,
                order_manager=order_manager,
                risk_manager=risk_manager,
                config_manager=config_manager
            )
            await engine.run()
            ```
        """
        self.logger = logging.getLogger(__name__)

        # Components (injected via set_components)
        self.event_bus: Optional[EventBus] = None
        self.data_collector: Optional[BinanceDataCollector] = None
        self.strategy: Optional[BaseStrategy] = None
        self.order_manager: Optional[OrderExecutionManager] = None
        self.risk_manager: Optional[RiskManager] = None
        self.config_manager: Optional[ConfigManager] = None

        # Runtime state
        self._running: bool = False

        self.logger.info("TradingEngine initialized (awaiting component injection)")

    def set_components(
        self,
        event_bus: EventBus,
        data_collector: BinanceDataCollector,
        strategy: BaseStrategy,
        order_manager: OrderExecutionManager,
        risk_manager: RiskManager,
        config_manager: ConfigManager,
        trading_bot: 'TradingBot'
    ) -> None:
        """
        Inject all required components in one call.

        This method receives all dependencies from TradingBot and:
        1. Stores component references
        2. Registers event handlers
        3. Logs successful injection

        Args:
            event_bus: EventBus instance for pub-sub coordination
            data_collector: BinanceDataCollector for WebSocket streaming
            strategy: Trading strategy implementing BaseStrategy
            order_manager: OrderExecutionManager for order execution
            risk_manager: RiskManager for validation and position sizing
            config_manager: ConfigManager for trading configuration
            trading_bot: TradingBot instance for event loop reference

        Notes:
            - Must be called before run()
            - All components required (no None allowed)
            - Automatically registers event handlers after injection
            - Called by TradingBot.initialize() Step 9

        Example:
            ```python
            engine = TradingEngine()
            engine.set_components(
                event_bus=self.event_bus,
                data_collector=self.data_collector,
                strategy=self.strategy,
                order_manager=self.order_manager,
                risk_manager=self.risk_manager,
                config_manager=self.config_manager
            )
            ```
        """
        self.event_bus = event_bus
        self.data_collector = data_collector
        self.strategy = strategy
        self.order_manager = order_manager
        self.risk_manager = risk_manager
        self.config_manager = config_manager
        self.trading_bot = trading_bot

        # Setup handlers AFTER all components available
        self._setup_event_handlers()

        self.logger.info("✅ TradingEngine components injected and handlers registered")

    def _setup_event_handlers(self) -> None:
        """
        Register event subscriptions with EventBus.

        Subscribes handlers to EventBus for:
        - CANDLE_CLOSED → _on_candle_closed: Trigger strategy analysis
        - SIGNAL_GENERATED → _on_signal_generated: Risk validation and order execution
        - ORDER_FILLED → _on_order_filled: Position tracking

        Handler Routing:
            - All handlers are async methods
            - Handlers execute sequentially per event type
            - Errors isolated (one fails → others continue)
            - Logging at each pipeline stage

        Notes:
            - Called automatically by set_components()
            - Requires event_bus to be injected first
            - Private method (internal setup only)

        Event Flow:
            CANDLE_CLOSED → _on_candle_closed → Strategy
                         ↓
            SIGNAL_GENERATED → _on_signal_generated → RiskManager → OrderManager
                             ↓
            ORDER_FILLED → _on_order_filled → Position
        """
        self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal_generated)
        self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)

        self.logger.info("✅ Event handlers registered:")
        self.logger.info("  - CANDLE_CLOSED → _on_candle_closed")
        self.logger.info("  - SIGNAL_GENERATED → _on_signal_generated")
        self.logger.info("  - ORDER_FILLED → _on_order_filled")

    async def _on_candle_closed(self, event: Event) -> None:
        """
        Handle closed candle event - run strategy analysis.

        This handler is called when a candle fully closes (is_closed=True).
        It runs the trading strategy analysis and publishes signals if conditions are met.

        Args:
            event: Event containing closed Candle data
        """
        # Step 1: Extract candle from event data
        candle: Candle = event.data

        # Step 2: Log candle received (info level)
        self.logger.info(
            f"Analyzing closed candle: {candle.symbol} {candle.interval} "
            f"@ {candle.close} (vol: {candle.volume})"
        )

        # Step 3: Call strategy.analyze() to generate signal
        try:
            signal = await self.strategy.analyze(candle)
        except Exception as e:
            # Don't crash on strategy errors
            self.logger.error(
                f"Strategy analysis failed for {candle.symbol}: {e}",
                exc_info=True
            )
            return

        # Step 4: If signal exists, publish SIGNAL_GENERATED event
        if signal is not None:
            self.logger.info(
                f"Signal generated: {signal.signal_type.value} "
                f"@ {signal.entry_price} (TP: {signal.take_profit}, "
                f"SL: {signal.stop_loss})"
            )

            # Create event and publish to 'signal' queue
            signal_event = Event(EventType.SIGNAL_GENERATED, signal)
            await self.event_bus.publish(signal_event, queue_name='signal')
        else:
            # Info log for no signal (shows strategy is working)
            self.logger.info(
                f"✓ No signal: {candle.symbol} {candle.interval} "
                f"(strategy conditions not met)"
            )

    async def _on_signal_generated(self, event: Event) -> None:
        """
        Handle generated signal - validate and execute order.

        This is the critical trading logic that:
        1. Validates signal with RiskManager
        2. Calculates position size
        3. Executes market order with TP/SL

        Args:
            event: Event containing Signal data
        """
        # Step 1: Extract signal from event data
        signal: Signal = event.data

        self.logger.info(
            f"Processing signal: {signal.signal_type.value} for {signal.symbol}"
        )

        try:
            # Step 2: Get current position from OrderManager
            current_position = self.order_manager.get_position(signal.symbol)

            # Step 3: Validate signal with RiskManager
            is_valid = self.risk_manager.validate_risk(signal, current_position)

            if not is_valid:
                self.logger.warning(
                    f"Signal rejected by risk validation: {signal.signal_type.value}"
                )
                return

            # Step 4: Get account balance
            account_balance = self.order_manager.get_account_balance()

            if account_balance <= 0:
                self.logger.error(
                    f"Invalid account balance: {account_balance}, cannot execute signal"
                )
                return

            # Step 5: Calculate position size using RiskManager
            quantity = self.risk_manager.calculate_position_size(
                account_balance=account_balance,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                leverage=self.config_manager.trading_config.leverage,
                symbol_info=None  # OrderManager will handle rounding internally
            )

            # Step 6: Execute signal via OrderManager
            # Returns (entry_order, [tp_order, sl_order])
            entry_order, tpsl_orders = self.order_manager.execute_signal(
                signal=signal,
                quantity=quantity
            )

            # Step 7: Log successful trade execution
            self.logger.info(
                f"✅ Trade executed successfully: "
                f"Order ID={entry_order.order_id}, "
                f"Quantity={entry_order.quantity}, "
                f"TP/SL={len(tpsl_orders)}/2 orders"
            )

            # Step 8: Publish ORDER_FILLED event
            order_event = Event(EventType.ORDER_FILLED, entry_order)
            await self.event_bus.publish(order_event, queue_name='order')

        except Exception as e:
            # Step 9: Catch and log execution errors without crashing
            self.logger.error(
                f"Failed to execute signal for {signal.symbol}: {e}",
                exc_info=True
            )
            # Don't re-raise - system should continue running

    async def _on_order_filled(self, event: Event) -> None:
        """
        Handle order fill notification.

        Logs order fills for tracking and monitoring.
        In future iterations, will update position tracking.

        Args:
            event: Event containing Order data
        """
        # Step 1: Extract order from event data
        order: Order = event.data

        # Step 2: Log order fill confirmation
        self.logger.info(
            f"Order filled: ID={order.order_id}, "
            f"Symbol={order.symbol}, "
            f"Side={order.side.value}, "
            f"Quantity={order.quantity}, "
            f"Price={order.price}"
        )

        # Step 3: Update position tracking (future enhancement)
        # For now, OrderManager.get_position() queries Binance API
        # Future: Maintain local position state for faster access

    async def run(self) -> None:
        """
        Start the trading engine and run until interrupted.

        Main runtime loop that:
        1. Sets _running flag to True
        2. Starts EventBus processors (3 queues)
        3. Starts DataCollector streaming
        4. Runs until interrupted
        5. Triggers graceful shutdown

        Process Flow:
            1. Set _running = True
            2. Log startup message
            3. Start EventBus and DataCollector concurrently
            4. Block until KeyboardInterrupt or component failure
            5. Trigger shutdown() in finally block

        Error Handling:
            - KeyboardInterrupt: Graceful shutdown
            - Component failure: Log error, trigger shutdown
            - asyncio.gather with return_exceptions=True

        Example:
            ```python
            engine = TradingEngine()
            engine.set_components(...)
            await engine.run()  # Blocks until interrupted
            ```

        Notes:
            - Blocks until stopped (main loop)
            - Always calls shutdown() (even on errors)
            - EventBus and DataCollector run concurrently
        """
        # Capture event loop and pass to TradingBot
        loop = asyncio.get_running_loop()
        self.trading_bot.set_event_loop(loop)
        self.logger.debug(f"Event loop passed to TradingBot: {loop}")

        self._running = True
        self.logger.info("Starting TradingEngine")

        try:
            # Start all components concurrently
            tasks = [
                # EventBus always runs
                asyncio.create_task(
                    self.event_bus.start(),
                    name='eventbus'
                )
            ]

            # Add DataCollector (should always be configured)
            if self.data_collector:
                tasks.append(
                    asyncio.create_task(
                        self.data_collector.start_streaming(),
                        name='datacollector'
                    )
                )
                self.logger.info("DataCollector streaming enabled")

            # Run until interrupted
            # return_exceptions=True prevents one task error from cancelling others
            await asyncio.gather(*tasks, return_exceptions=True)

        except asyncio.CancelledError:
            self.logger.info("Shutdown requested (CancelledError)")

        except Exception as e:
            self.logger.error(f"Unexpected error in run(): {e}", exc_info=True)

        finally:
            # Always shutdown gracefully
            await self.shutdown()

    async def shutdown(self) -> None:
        """
        Gracefully shutdown all components with pending event processing.

        Shutdown Sequence:
        1. Stop DataCollector (no new candle events)
        2. EventBus.shutdown(timeout=10) drains all queues
        3. All pending events processed or timeout logged

        Args:
            None

        Process Flow:
            1. Log shutdown start
            2. Stop DataCollector if configured
            3. Wait briefly for final events to publish
            4. Shutdown EventBus with 10s timeout per queue
            5. Log shutdown complete

        Error Handling:
            - DataCollector stop error: Log, continue
            - EventBus shutdown error: Log, continue
            - All errors logged, shutdown proceeds

        Timeout Strategy:
            - 10s per queue (30s max total for EventBus)
            - Critical for order queue (ensure orders processed)
            - Data queue can drop (less critical)

        Example:
            ```python
            # Automatic via run()
            await engine.run()  # Calls shutdown() on exit

            # Manual shutdown
            await engine.shutdown()
            ```

        Notes:
            - Safe to call multiple times (idempotent)
            - Always called from run() finally block
            - Blocks until shutdown complete
            - Order events MUST be processed (critical)
        """
        # Idempotency check - safe to call multiple times
        if not self._running:
            return

        self._running = False
        self.logger.info("Shutting down TradingEngine")

        try:
            # Stop data collector first (no new events)
            if self.data_collector:
                self.logger.info("Stopping DataCollector")
                await self.data_collector.stop()

            # Wait briefly for final events to publish
            await asyncio.sleep(0.5)

            # Shutdown EventBus (drains all queues)
            self.logger.info("Shutting down EventBus")
            await self.event_bus.shutdown(timeout=10.0)

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}", exc_info=True)

        finally:
            self.logger.info("TradingEngine shutdown complete")
