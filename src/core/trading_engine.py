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
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.main import TradingBot

from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.execution.order_manager import OrderExecutionManager
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.models.order import Order
from src.models.signal import Signal
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.strategies.multi_timeframe import MultiTimeframeStrategy
from src.utils.config import ConfigManager


from enum import Enum


class EngineState(Enum):
    """
    State machine for TradingEngine lifecycle.
    
    State Transitions:
        CREATED → INITIALIZED → RUNNING → STOPPING → STOPPED
        
    States:
        CREATED: Initial state after __init__()
        INITIALIZED: After set_components() called
        RUNNING: Event loop active, run() executing
        STOPPING: Shutdown initiated
        STOPPED: Shutdown complete
    """
    CREATED = "created"
    INITIALIZED = "initialized"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


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

    def __init__(self, audit_logger: "AuditLogger") -> None:
        """
        Initialize TradingEngine with minimal setup.

        Components are injected via set_components() method after construction.
        This allows for better testability and clear separation between
        bootstrap (TradingBot) and execution (TradingEngine).

        Args:
            audit_logger: AuditLogger instance for structured logging

        Attributes:
            logger: Logger instance for engine events
            audit_logger: AuditLogger instance for audit trail
            event_bus: Optional[EventBus] (injected via set_components)
            data_collector: Optional[BinanceDataCollector] (injected via set_components)
            strategy: Optional[BaseStrategy] (injected via set_components)
            order_manager: Optional[OrderExecutionManager] (injected via set_components)
            risk_manager: Optional[RiskManager] (injected via set_components)
            config_manager: Optional[ConfigManager] (injected via set_components)
            _running: Runtime state flag
            _event_loop: Event loop reference (captured in run())
            _engine_state: Current engine lifecycle state
            _ready_event: Synchronization barrier for run() startup
            _event_drop_count: Counter for dropped events (Phase 2.2)

        Process Flow:
            1. Create logger
            2. Inject audit logger
            3. Set component placeholders to None
            4. Initialize state machine (CREATED)
            5. Wait for set_components() call

        Example:
            ```python
            from src.core.audit_logger import AuditLogger
            
            audit_logger = AuditLogger(log_dir="logs/audit")
            engine = TradingEngine(audit_logger=audit_logger)
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

        # Inject audit logger
        self.audit_logger = audit_logger

        # Components (injected via set_components)
        self.event_bus: Optional[EventBus] = None
        self.data_collector: Optional[BinanceDataCollector] = None
        self.strategy: Optional[BaseStrategy] = None
        self.order_manager: Optional[OrderExecutionManager] = None
        self.risk_manager: Optional[RiskManager] = None
        self.config_manager: Optional[ConfigManager] = None

        # Runtime state
        self._running: bool = False
        
        # Event loop management (Phase 2.1)
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._engine_state = EngineState.CREATED
        self._ready_event = asyncio.Event()
        
        # Event handling (Phase 2.2)
        self._event_drop_count = 0

        self.logger.info("TradingEngine initialized (awaiting component injection)")

    def set_components(
        self,
        event_bus: EventBus,
        data_collector: BinanceDataCollector,
        strategy: BaseStrategy,
        order_manager: OrderExecutionManager,
        risk_manager: RiskManager,
        config_manager: ConfigManager,
    ) -> None:
        """
        Inject all required components in one call.

        This method receives all dependencies from TradingBot and:
        1. Stores component references
        2. Registers event handlers
        3. Transitions state to INITIALIZED
        4. Logs successful injection

        Args:
            event_bus: EventBus instance for pub-sub coordination
            data_collector: BinanceDataCollector for WebSocket streaming
            strategy: Trading strategy implementing BaseStrategy
            order_manager: OrderExecutionManager for order execution
            risk_manager: RiskManager for validation and position sizing
            config_manager: ConfigManager for trading configuration

        Notes:
            - Must be called before run()
            - All components required (no None allowed)
            - Automatically registers event handlers after injection
            - Called by TradingBot.initialize() Step 10
            - Transitions state: CREATED → INITIALIZED
            - trading_bot parameter removed to break circular dependency

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
        # self.trading_bot = trading_bot  # REMOVED: Circular dependency eliminated

        # Setup handlers AFTER all components available
        self._setup_event_handlers()

        # State transition: CREATED → INITIALIZED
        self._engine_state = EngineState.INITIALIZED

        self.logger.info("✅ TradingEngine components injected and handlers registered")

    def initialize_strategy_with_backfill(self, limit: int = 100) -> None:
        """
        Initialize strategy with historical data by fetching directly from API.

        Called once during system startup to pre-populate strategy buffers
        before WebSocket streaming begins. This enables strategies to analyze
        immediately when real-time trading starts.

        Args:
            limit: Number of historical candles to fetch per interval (default: 100)

        Behavior:
            1. Validates strategy and data_collector are injected
            2. Detects strategy type (MTF vs single-interval)
            3. Fetches historical candles via data_collector.get_historical_candles()
            4. Initializes strategy buffers with fetched data
            5. Logs initialization status

        Example:
            ```python
            # In TradingBot.initialize()
            self.trading_engine.initialize_strategy_with_backfill(limit=100)
            # Strategy now has 100 candles of historical context
            ```

        Strategy Type Handling:
            For MultiTimeframeStrategy:
                - Fetches candles for each interval independently
                - Calls strategy.initialize_with_historical_data(interval, candles)
                - Example: Fetches 1m, 5m, 1h candles separately

            For Single-Interval Strategy:
                - Fetches candles for first configured interval
                - Calls strategy.initialize_with_historical_data(candles)
                - Uses data_collector's first interval configuration

        Error Handling:
            - Logs warning if strategy or data_collector not injected
            - Logs error if API fetch fails (but continues startup)
            - System continues even if initialization fails

        Notes:
            - Called ONCE during startup (warmup phase)
            - Must be called AFTER set_components()
            - Must be called BEFORE start_streaming()
            - Does NOT trigger signal generation
        """
        if not self.strategy:
            self.logger.warning(
                "[TradingEngine] Strategy not injected, skipping historical data initialization"
            )
            return

        if not self.data_collector:
            self.logger.warning(
                "[TradingEngine] DataCollector not injected, "
                "skipping historical data initialization"
            )
            return

        self.logger.info(
            f"[TradingEngine] Initializing strategy '{self.strategy.__class__.__name__}' "
            f"with {limit} historical candles"
        )

        try:
            symbol = self.strategy.symbol

            # Check if this is a multi-timeframe strategy
            if isinstance(self.strategy, MultiTimeframeStrategy):
                # MTF Strategy: Fetch and initialize each interval separately
                self.logger.info(
                    f"[TradingEngine] Detected MultiTimeframeStrategy, "
                    f"fetching intervals for {symbol}"
                )

                initialized_count = 0
                for interval in self.data_collector.intervals:
                    try:
                        # Fetch historical candles directly from API
                        candles = self.data_collector.get_historical_candles(
                            symbol=symbol, interval=interval, limit=limit
                        )

                        if candles:
                            self.logger.info(
                                f"[TradingEngine] Fetched {len(candles)} candles "
                                f"for {symbol} {interval}"
                            )

                            # Initialize this specific interval
                            self.strategy.initialize_with_historical_data(interval, candles)
                            initialized_count += 1
                        else:
                            self.logger.warning(
                                f"[TradingEngine] No candles returned for {symbol} {interval}"
                            )

                    except Exception as e:
                        self.logger.error(
                            f"[TradingEngine] Failed to fetch {symbol} {interval}: {e}"
                        )

                if initialized_count > 0:
                    self.logger.info(
                        f"[TradingEngine] ✅ MTF Strategy initialization complete: "
                        f"{initialized_count} intervals initialized for {symbol}"
                    )
                else:
                    self.logger.warning(
                        f"[TradingEngine] No intervals initialized for MTF strategy '{symbol}'"
                    )

            else:
                # Single-interval strategy: Use first configured interval
                interval = self.data_collector.intervals[0]

                self.logger.info(
                    f"[TradingEngine] Fetching {limit} candles "
                    f"for single-interval strategy {symbol} {interval}"
                )

                candles = self.data_collector.get_historical_candles(
                    symbol=symbol, interval=interval, limit=limit
                )

                if candles:
                    self.logger.info(
                        f"[TradingEngine] Fetched {len(candles)} candles "
                        f"for {symbol} {interval}"
                    )

                    # Initialize strategy with candles
                    self.strategy.initialize_with_historical_data(candles)

                    self.logger.info(
                        f"[TradingEngine] ✅ Strategy initialization complete: "
                        f"{len(candles)} candles loaded for {symbol} {interval}"
                    )
                else:
                    self.logger.warning(
                        f"[TradingEngine] No candles returned for {symbol} {interval}"
                    )

        except Exception as e:
            self.logger.error(
                f"[TradingEngine] ❌ Failed to initialize strategy with historical data: {e}",
                exc_info=True,
            )

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
            self.logger.error(f"Strategy analysis failed for {candle.symbol}: {e}", exc_info=True)
            return

        # Step 4: If signal exists, publish SIGNAL_GENERATED event
        if signal is not None:
            self.logger.info(
                f"Signal generated: {signal.signal_type.value} "
                f"@ {signal.entry_price} (TP: {signal.take_profit}, "
                f"SL: {signal.stop_loss})"
            )

            # Audit log: signal generated from candle analysis
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.SIGNAL_PROCESSING,
                    operation="candle_analysis",
                    symbol=candle.symbol,
                    additional_data={
                        "interval": candle.interval,
                        "close_price": candle.close,
                        "signal_generated": True,
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                        "take_profit": signal.take_profit,
                        "stop_loss": signal.stop_loss,
                        "strategy_name": signal.strategy_name,
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            # Create event and publish to 'signal' queue
            signal_event = Event(EventType.SIGNAL_GENERATED, signal)
            await self.event_bus.publish(signal_event, queue_name="signal")
        else:
            # Info log for no signal (shows strategy is working)
            self.logger.info(
                f"✓ No signal: {candle.symbol} {candle.interval} " f"(strategy conditions not met)"
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

        self.logger.info(f"Processing signal: {signal.signal_type.value} for {signal.symbol}")

        try:
            # Step 2: Get current position from OrderManager
            current_position = self.order_manager.get_position(signal.symbol)

            # Step 3: Validate signal with RiskManager
            is_valid = self.risk_manager.validate_risk(signal, current_position)

            if not is_valid:
                self.logger.warning(
                    f"Signal rejected by risk validation: {signal.signal_type.value}"
                )

                # Audit log: risk rejection
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.RISK_REJECTION,
                        operation="signal_execution",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "entry_price": signal.entry_price,
                        },
                        error={"reason": "risk_validation_failed"},
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")

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
                symbol_info=None,  # OrderManager will handle rounding internally
            )

            # Step 6: Execute signal via OrderManager
            # Returns (entry_order, [tp_order, sl_order])
            entry_order, tpsl_orders = self.order_manager.execute_signal(
                signal=signal, quantity=quantity
            )

            # Step 7: Log successful trade execution
            self.logger.info(
                f"✅ Trade executed successfully: "
                f"Order ID={entry_order.order_id}, "
                f"Quantity={entry_order.quantity}, "
                f"TP/SL={len(tpsl_orders)}/2 orders"
            )

            # Audit log: trade executed successfully
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.TRADE_EXECUTED,
                    operation="execute_trade",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                        "quantity": quantity,
                        "leverage": self.config_manager.trading_config.leverage,
                    },
                    response={
                        "entry_order_id": entry_order.order_id,
                        "tpsl_count": len(tpsl_orders),
                    },
                )
            except Exception as e:
                self.logger.warning(f"Audit logging failed: {e}")

            # Step 8: Publish ORDER_FILLED event
            order_event = Event(EventType.ORDER_FILLED, entry_order)
            await self.event_bus.publish(order_event, queue_name="order")

        except Exception as e:
            # Step 9: Catch and log execution errors without crashing
            self.logger.error(f"Failed to execute signal for {signal.symbol}: {e}", exc_info=True)

            # Audit log: trade execution failed
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.TRADE_EXECUTION_FAILED,
                    operation="execute_trade",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "entry_price": signal.entry_price,
                    },
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass  # Exception context already logged

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

        # Audit log: order filled confirmation
        try:
            from src.core.audit_logger import AuditEventType

            self.audit_logger.log_event(
                event_type=AuditEventType.ORDER_PLACED,  # Reuse existing event type
                operation="order_confirmation",
                symbol=order.symbol,
                response={
                    "order_id": order.order_id,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "price": order.price,
                    "order_type": order.order_type.value,
                },
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        # Step 3: Update position tracking (future enhancement)
        # For now, OrderManager.get_position() queries Binance API
        # Future: Maintain local position state for faster access

    async def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """
        Wait until TradingEngine has captured its event loop.
        
        Prevents race condition where DataCollector starts sending candles
        before run() has executed and captured the event loop reference.
        
        This method blocks until:
        - run() has executed and set _ready_event, OR
        - timeout is exceeded (raises TimeoutError)
        
        Args:
            timeout: Maximum seconds to wait (default: 5.0)
            
        Returns:
            True if engine became ready within timeout
            
        Raises:
            TimeoutError: If timeout exceeded before engine became ready
            
        Example:
            ```python
            # In TradingBot.run()
            engine_task = asyncio.create_task(self.engine.run())
            
            # Wait for engine to be ready before starting DataCollector
            await self.engine.wait_until_ready(timeout=5.0)
            
            # Now safe to start DataCollector
            await self.data_collector.start_streaming()
            ```
            
        Notes:
            - Called by TradingBot before starting DataCollector
            - Ensures event loop is captured before candles arrive
            - Timeout prevents infinite blocking on engine failure
        """
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            self.logger.info("TradingEngine is ready")
            return True
        except asyncio.TimeoutError:
            self.logger.error(f"TradingEngine failed to become ready within {timeout}s")
            raise TimeoutError(f"Engine not ready after {timeout}s")

    def on_candle_received(self, candle: Candle) -> None:
        """
        Callback from BinanceDataCollector on every candle update.

        Bridges WebSocket thread to EventBus using stored event loop reference.
        Migrated from TradingBot as part of Phase 2.2 circular dependency refactoring.

        Args:
            candle: Candle data from WebSocket stream

        Thread Safety:
            Called from WebSocket thread. Uses stored event loop reference
            with asyncio.run_coroutine_threadsafe() to schedule coroutine
            in main thread's event loop.

        State Handling:
            - RUNNING: Accept and publish event
            - INITIALIZED/STOPPING: Reject with debug log (expected during transitions)
            - CREATED/STOPPED: Reject with warning (unexpected)

        Event Drop Counting:
            Increments _event_drop_count on rejection or publish failure.
            Helps monitor system health and backpressure.

        Event Types:
            - CANDLE_CLOSED: Published when candle.is_closed is True
            - CANDLE_UPDATE: Published for live updates (is_closed is False)

        Performance Considerations:
            - Minimal validation (Hot Path optimization)
            - Direct state check without lock
            - Fast rejection path for non-RUNNING states
            - Thread-safe event loop scheduling
        """

        # Step 1: Check engine state
        if self._engine_state != EngineState.RUNNING:
            self._event_drop_count += 1

            # Log level depends on whether rejection is expected
            if self._engine_state in (EngineState.INITIALIZED, EngineState.STOPPING):
                self.logger.debug(
                    f"Event rejected (state={self._engine_state.name}): "
                    f"{candle.symbol} {candle.interval} @ {candle.close}. "
                    f"Drops: {self._event_drop_count}"
                )
            else:
                self.logger.warning(
                    f"Event rejected in unexpected state ({self._engine_state.name}): "
                    f"{candle.symbol} {candle.interval} @ {candle.close}. "
                    f"Drops: {self._event_drop_count}"
                )
            return

        # Step 2: Verify event loop is available
        if self._event_loop is None:
            self._event_drop_count += 1
            self.logger.error(
                f"Event loop not set! Cannot publish: "
                f"{candle.symbol} {candle.interval} @ {candle.close}. "
                f"Drops: {self._event_drop_count}"
            )
            return

        # Step 3: Determine event type
        event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE

        # Step 4: Create Event wrapper
        event = Event(event_type, candle)

        # Step 5: Publish to EventBus (thread-safe)
        try:
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(event, queue_name="data"), self._event_loop
            )

        except Exception as e:
            self._event_drop_count += 1
            self.logger.error(
                f"Failed to publish event: {e} | "
                f"{candle.symbol} {candle.interval} @ {candle.close}. "
                f"Drops: {self._event_drop_count}",
                exc_info=True,
            )
            return

        # Step 6: Log success
        if candle.is_closed:
            self.logger.info(
                f"📊 Candle closed: {candle.symbol} {candle.interval} "
                f"@ {candle.close} → EventBus"
            )
        else:
            # Heartbeat: log first update per minute
            if candle.open_time.second < 5:
                self.logger.info(
                    f"🔄 Live data: {candle.symbol} {candle.interval} @ {candle.close}"
                )

    async def run(self) -> None:
        """
        Start the trading engine and run until interrupted.

        Main runtime loop that:
        1. Captures event loop reference
        2. Sets state to RUNNING and signals ready
        3. Starts EventBus processors (3 queues)
        4. Starts DataCollector streaming
        5. Runs until interrupted
        6. Triggers graceful shutdown

        Process Flow:
            1. Capture event loop (FIRST - prevents race condition)
            2. Set _engine_state = RUNNING
            3. Signal _ready_event (allows DataCollector to proceed)
            4. Log startup message
            5. Start EventBus and DataCollector concurrently
            6. Block until KeyboardInterrupt or component failure
            7. Trigger shutdown() in finally block

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
            - Event loop captured before any async operations
        """
        # Capture event loop FIRST (Phase 2.1 - prevents race condition)
        self._event_loop = asyncio.get_running_loop()
        self._engine_state = EngineState.RUNNING
        self._ready_event.set()  # Signal ready to DataCollector
        
        self.logger.info(f"TradingEngine event loop captured: {self._event_loop}")
        
        self._running = True
        self.logger.info("Starting TradingEngine")

        try:
            # Start all components concurrently
            tasks = [
                # EventBus always runs
                asyncio.create_task(self.event_bus.start(), name="eventbus")
            ]

            # Add DataCollector (should always be configured)
            if self.data_collector:
                tasks.append(
                    asyncio.create_task(self.data_collector.start_streaming(), name="datacollector")
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
        1. Transition to STOPPING state
        2. Stop DataCollector (no new candle events)
        3. EventBus.shutdown(timeout=10) drains all queues
        4. All pending events processed or timeout logged
        5. Transition to STOPPED state
        6. Clear ready event

        Args:
            None

        Process Flow:
            1. Set _engine_state = STOPPING
            2. Log shutdown start
            3. Stop DataCollector if configured
            4. Wait briefly for final events to publish
            5. Shutdown EventBus with 10s timeout per queue
            6. Set _engine_state = STOPPED
            7. Clear _ready_event
            8. Log shutdown complete

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
            - State transitions: RUNNING → STOPPING → STOPPED
        """
        # Idempotency check - safe to call multiple times
        if not self._running:
            return

        # State transition: RUNNING → STOPPING
        self._engine_state = EngineState.STOPPING
        
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
            # Stop AuditLogger to flush remaining audit logs
            if self.audit_logger:
                self.logger.info("Stopping AuditLogger and flushing audit logs...")
                self.audit_logger.stop()

            # State transition: STOPPING → STOPPED
            self._engine_state = EngineState.STOPPED
            self._ready_event.clear()

            self.logger.info("TradingEngine shutdown complete")
