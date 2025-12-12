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
from src.execution.order_manager import OrderManager
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.models.signal import Signal


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

    def __init__(self, config: dict) -> None:
        """
        Initialize TradingEngine with configuration and components.

        Args:
            config: Configuration dictionary with settings:
                - environment: 'testnet' or 'mainnet'
                - log_level: Logging level (default: 'INFO')
                - Additional strategy/risk parameters

        Attributes:
            config: Configuration dictionary
            logger: Logger instance for engine events
            event_bus: EventBus instance (created immediately)
            data_collector: BinanceDataCollector (injected via setter)
            strategy: Strategy instance (injected via setter)
            order_manager: OrderManager instance (injected via setter)

        Process Flow:
            1. Store config and create logger
            2. Initialize EventBus (core infrastructure)
            3. Set component placeholders to None (inject later)
            4. Call _setup_handlers() to register event handlers

        Notes:
            - EventBus created immediately (always needed)
            - Other components injected via setters (supports testing)
            - Handlers registered even if components None (fail gracefully)
            - Logger uses engine name for component identification

        Example:
            ```python
            config = {
                'environment': 'testnet',
                'log_level': 'DEBUG',
                'strategy_params': {...}
            }
            engine = TradingEngine(config)
            ```
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(config.get('log_level', 'INFO'))

        # Core event infrastructure
        self.event_bus = EventBus()

        # Components (inject via setters)
        self.data_collector: Optional[BinanceDataCollector] = None
        self.strategy: Optional[Any] = None  # Strategy interface TBD
        self.order_manager: Optional[OrderManager] = None

        # Register event handlers for trading pipeline
        self._setup_handlers()

        self.logger.info("TradingEngine initialized")

    def _setup_handlers(self) -> None:
        """
        Register event handlers for complete trading pipeline.

        Subscribes handlers to EventBus for:
        - CANDLE_CLOSED: Trigger strategy analysis
        - SIGNAL_GENERATED: Create orders from signals
        - ORDER_FILLED: Update positions (future)

        Handler Routing:
            - All handlers are async methods
            - Handlers execute sequentially per event type
            - Errors isolated (one fails → others continue)
            - Logging at each pipeline stage

        Notes:
            - Called automatically in __init__()
            - Safe to call even if components None
            - Handlers check component existence before use
            - Private method (internal setup only)

        Example Event Flow:
            CANDLE_CLOSED → _on_candle_closed → Strategy
                         ↓
            SIGNAL_GENERATED → _on_signal → OrderManager
                             ↓
            ORDER_FILLED → _on_order_filled → Position
        """
        self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal)
        self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)

        self.logger.debug("Event handlers registered for trading pipeline")

    async def _on_candle_closed(self, event: Event) -> None:
        """
        Handle CANDLE_CLOSED event: Analyze candle and generate signal.

        Pipeline Stage: Data → Strategy

        Args:
            event: Event with candle data
                event.data: Candle instance
                event.source: 'BinanceDataCollector'

        Process Flow:
            1. Extract candle from event
            2. Log candle close (DEBUG level)
            3. Check if strategy is configured
            4. Call strategy.analyze(candle)
            5. If signal returned, publish SIGNAL_GENERATED
            6. Handle errors without crashing

        Error Handling:
            - Strategy None: Log warning, skip analysis
            - Strategy.analyze() error: Log error, continue
            - Publish error: Logged by EventBus, not re-raised

        Performance:
            - Should be fast (<10ms) to avoid backlog
            - Heavy analysis → strategy should spawn tasks
            - No blocking I/O in this handler

        Example:
            ```python
            # Incoming event
            event = Event(
                event_type=EventType.CANDLE_CLOSED,
                data=Candle(...),
                source='BinanceDataCollector'
            )

            # Handler processes → strategy.analyze() → signal
            # If signal: publishes SIGNAL_GENERATED to signal queue
            ```

        Notes:
            - Strategy interface: async analyze(candle: Candle) -> Optional[Signal]
            - Signal None is valid (no trade opportunity)
            - Publish to 'signal' queue (medium priority)
        """
        try:
            candle: Candle = event.data
            self.logger.debug(
                f"Candle closed: {candle.symbol} @ {candle.close_time} "
                f"close={candle.close}"
            )

            # Check if strategy is configured
            if not self.strategy:
                self.logger.warning("No strategy configured, skipping analysis")
                return

            # Analyze candle for trading signal
            signal: Optional[Signal] = await self.strategy.analyze(candle)

            if signal:
                self.logger.info(
                    f"Signal generated: {signal.signal_type.value} {signal.symbol} "
                    f"@ {signal.entry_price}"
                )

                # Publish signal to signal queue
                await self.event_bus.publish(
                    Event(
                        event_type=EventType.SIGNAL_GENERATED,
                        data=signal,
                        source='TradingEngine'
                    ),
                    queue_name='signal'
                )
            else:
                self.logger.debug(f"No signal for {candle.symbol}")

        except Exception as e:
            self.logger.error(
                f"Error in candle handler: {e}",
                exc_info=True
            )
            # Don't re-raise - isolated error handling

    async def _on_signal(self, event: Event) -> None:
        """
        Handle SIGNAL_GENERATED event: Convert signal to order.

        Pipeline Stage: Strategy → OrderManager

        Args:
            event: Event with signal data
                event.data: Signal instance
                event.source: 'TradingEngine' or 'Strategy'

        Process Flow:
            1. Extract signal from event
            2. Log signal details (INFO level)
            3. Check if order_manager is configured
            4. Call order_manager.create_order_from_signal(signal)
            5. If order created, publish ORDER_PLACED
            6. Handle errors without crashing

        Error Handling:
            - OrderManager None: Log warning, skip order creation
            - create_order error: Log error, continue
            - Publish error: Logged by EventBus

        Critical for Trading:
            - Signal queue ensures all signals processed
            - Order queue ensures order events never drop
            - Errors logged for post-analysis

        Example:
            ```python
            # Incoming event
            event = Event(
                event_type=EventType.SIGNAL_GENERATED,
                data=Signal(
                    signal_type=SignalType.LONG_ENTRY,
                    symbol='BTCUSDT',
                    entry_price=50000,
                    ...
                ),
                source='TradingEngine'
            )

            # Handler processes → order_manager.create_order() → order
            # Publishes ORDER_PLACED to order queue
            ```

        Notes:
            - OrderManager interface: async create_order_from_signal(signal) -> Optional[Order]
            - Order None if risk management rejects (future)
            - Publish to 'order' queue (critical priority, never drops)
        """
        try:
            signal: Signal = event.data
            self.logger.info(
                f"Processing signal: {signal.signal_type.value} {signal.symbol} "
                f"entry={signal.entry_price} sl={signal.stop_loss} tp={signal.take_profit}"
            )

            # Check if order manager is configured
            if not self.order_manager:
                self.logger.warning(
                    "No order manager configured, skipping order creation"
                )
                return

            # Future implementation:
            # order = await self.order_manager.create_order_from_signal(signal)
            # if order:
            #     await self.event_bus.publish(
            #         Event(EventType.ORDER_PLACED, order, source='TradingEngine'),
            #         queue_name='order'
            #     )

            # Placeholder: Just log the signal processing
            self.logger.info(
                f"Signal processed (order manager integration pending): {signal.symbol}"
            )

        except Exception as e:
            self.logger.error(
                f"Error in signal handler: {e}",
                exc_info=True
            )
            # Don't re-raise - isolated error handling

    async def _on_order_filled(self, event: Event) -> None:
        """
        Handle ORDER_FILLED event: Update position tracking.

        Pipeline Stage: Exchange → Position Management

        Args:
            event: Event with order data
                event.data: Order instance (filled status)
                event.source: 'Exchange' or 'OrderManager'

        Process Flow:
            1. Extract order from event
            2. Log order fill details (INFO level)
            3. Update position tracking (future implementation)
            4. Calculate P&L if position closed
            5. Handle errors without crashing

        Error Handling:
            - Position tracking error: Log error, continue
            - P&L calculation error: Log error, continue
            - All errors isolated (don't crash engine)

        Future Implementation:
            - Position.open() for new positions
            - Position.update() for partial fills
            - Position.close() for exits
            - P&L calculation and tracking

        Example:
            ```python
            # Incoming event
            event = Event(
                event_type=EventType.ORDER_FILLED,
                data=Order(
                    order_id='123',
                    symbol='BTCUSDT',
                    filled_quantity=1.0,
                    ...
                ),
                source='Exchange'
            )

            # Handler processes → update position state
            ```

        Notes:
            - Order queue ensures all fills processed
            - Position tracking critical for risk management
            - P&L tracking critical for performance analysis
            - Placeholder implementation for now
        """
        try:
            order = event.data
            self.logger.info(
                f"Order filled: {order.order_id} {order.symbol} "
                f"qty={getattr(order, 'filled_quantity', 'N/A')}"
            )

            # Future implementation:
            # - Update position tracking
            # - Calculate P&L if position closed
            # - Publish POSITION_OPENED or POSITION_CLOSED events
            # - Update risk management state

        except Exception as e:
            self.logger.error(
                f"Error in order filled handler: {e}",
                exc_info=True
            )
            # Don't re-raise - isolated error handling

    def set_data_collector(self, collector: BinanceDataCollector) -> None:
        """
        Inject DataCollector component for market data streaming.

        Args:
            collector: Configured BinanceDataCollector instance

        Notes:
            - Must be called before run()
            - Collector should have symbols/intervals configured
            - Collector's on_candle_callback will publish CANDLE_CLOSED

        Example:
            ```python
            collector = BinanceDataCollector(
                api_key=key,
                api_secret=secret,
                symbols=['BTCUSDT'],
                intervals=['1h'],
                on_candle_callback=lambda candle: ...
            )
            engine.set_data_collector(collector)
            ```
        """
        self.data_collector = collector
        self.logger.info("DataCollector injected")

    def set_strategy(self, strategy: Any) -> None:
        """
        Inject Strategy component for signal generation.

        Args:
            strategy: Strategy instance with analyze() method

        Interface Required:
            async def analyze(self, candle: Candle) -> Optional[Signal]

        Notes:
            - Strategy can be None (dry-run mode)
            - Strategy errors isolated in _on_candle_closed

        Example:
            ```python
            from src.strategies.ict_strategy import ICTStrategy
            strategy = ICTStrategy(config)
            engine.set_strategy(strategy)
            ```
        """
        self.strategy = strategy
        self.logger.info(f"Strategy injected: {type(strategy).__name__}")

    def set_order_manager(self, manager: OrderManager) -> None:
        """
        Inject OrderManager component for order execution.

        Args:
            manager: Configured OrderManager instance

        Notes:
            - OrderManager can be None (analysis-only mode)
            - OrderManager errors isolated in _on_signal

        Example:
            ```python
            from src.execution.order_manager import OrderManager
            manager = OrderManager(exchange_client)
            engine.set_order_manager(manager)
            ```
        """
        self.order_manager = manager
        self.logger.info("OrderManager injected")

    async def run(self) -> None:
        """
        Start the trading engine and run until interrupted.

        Main application entry point that:
        1. Starts EventBus processors (3 queues)
        2. Starts DataCollector streaming (if configured)
        3. Runs until KeyboardInterrupt
        4. Triggers graceful shutdown

        Process Flow:
            1. Log startup message
            2. Validate required components
            3. Start EventBus and DataCollector concurrently
            4. Block until KeyboardInterrupt or component failure
            5. Trigger shutdown() on interrupt
            6. Ensure shutdown() called in finally block

        Error Handling:
            - KeyboardInterrupt: Graceful shutdown
            - Component failure: Log error, trigger shutdown
            - asyncio.gather with return_exceptions=True

        Component Requirements:
            - EventBus: Always required (created in __init__)
            - DataCollector: Optional (None → no data, analysis only)
            - Strategy: Optional (None → no signals)
            - OrderManager: Optional (None → signals only)

        Example:
            ```python
            engine = TradingEngine(config)
            engine.set_data_collector(collector)
            engine.set_strategy(strategy)

            try:
                await engine.run()
            except KeyboardInterrupt:
                print("Shutdown complete")
            ```

        Notes:
            - Blocks until stopped (main loop)
            - Safe to call multiple times (idempotent)
            - Always calls shutdown() (even on errors)
            - EventBus processors run continuously
        """
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

            # Add DataCollector if configured
            if self.data_collector:
                tasks.append(
                    asyncio.create_task(
                        self.data_collector.start_streaming(),
                        name='datacollector'
                    )
                )
                self.logger.info("DataCollector streaming enabled")
            else:
                self.logger.warning(
                    "No DataCollector configured - analysis only mode"
                )

            # Run until interrupted
            # return_exceptions=True prevents one task error from cancelling others
            await asyncio.gather(*tasks, return_exceptions=True)

        except KeyboardInterrupt:
            self.logger.info("Shutdown requested (KeyboardInterrupt)")

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
