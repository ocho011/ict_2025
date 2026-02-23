"""
TradingEngine: Main orchestrator for automated trading system.

Coordinates:
- Real-time data collection from Binance
- Strategy-based signal generation
- Order execution and position management
- Event-driven async pipeline with graceful shutdown

Refactored (Issue #110): Delegates to specialized modules:
- PositionCacheManager: Position state caching with TTL
- TradeCoordinator: Signal validation and order execution
- EventDispatcher: Candle routing and strategy analysis
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional, Dict

# Imports for type hinting only; prevents circular dependency at runtime
if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.main import TradingBot

from src.core.data_collector import BinanceDataCollector
from src.core.event_bus import EventBus
from src.core.exceptions import EngineState
from src.core.position_cache_manager import PositionCacheManager
from src.core.event_dispatcher import EventDispatcher
from src.execution.order_gateway import OrderGateway
from src.execution.trade_coordinator import TradeCoordinator
from src.models.candle import Candle
from src.models.event import Event, EventType, QueueType
from src.risk.risk_guard import RiskGuard
from src.strategies.base import BaseStrategy
from src.utils.config_manager import ConfigManager


class TradingEngine:
    """
    Main application orchestrator for event-driven trading system.

    Responsibilities (after Issue #110 refactor):
    1. Component lifecycle management (EventBus, DataCollector, Strategy, OrderGateway)
    2. Delegate event handling to specialized modules
    3. WebSocket callback bridging (_on_order_fill_from_websocket, _on_order_update_from_websocket)
    4. Graceful startup and shutdown with pending event processing

    Delegates to:
    - PositionCacheManager: Position state caching and WebSocket updates
    - TradeCoordinator: Signal-to-order execution coordination
    - EventDispatcher: Candle event routing and strategy execution
    """

    def __init__(self, audit_logger: Optional["AuditLogger"] = None) -> None:
        """
        Initialize TradingEngine with minimal setup.

        Components are created via initialize_components() method after construction.
        """
        self.logger = logging.getLogger(__name__)

        # Get audit logger (from parameter or singleton)
        if audit_logger is None:
            from src.core.audit_logger import AuditLogger
            self.audit_logger = AuditLogger.get_instance()
            self.logger.info("Using AuditLogger singleton instance")
        else:
            self.audit_logger = audit_logger
            self.logger.info("Using injected AuditLogger instance")

        # Components (created via initialize_components)
        self.event_bus: Optional[EventBus] = None
        self.data_collector: Optional[BinanceDataCollector] = None
        self.strategies: dict[str, BaseStrategy] = {}  # Issue #8: Multi-coin support
        self.order_gateway: Optional[OrderGateway] = None
        self.risk_guard: Optional[RiskGuard] = None
        self.config_manager: Optional[ConfigManager] = None

        # Extracted modules (Issue #110)
        self.position_cache_manager: Optional[PositionCacheManager] = None
        self.trade_coordinator: Optional[TradeCoordinator] = None
        self.event_dispatcher: Optional[EventDispatcher] = None

        # Runtime state
        self._running: bool = False

        # Event loop management (Phase 2.1)
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._engine_state = EngineState.CREATED
        self._ready_event = asyncio.Event()

        # Event handling (Phase 2.2)
        self._event_drop_count = 0
        self._heartbeat_gap_logged = False

        # Store logging config for conditional live data logging
        self._log_live_data = True

        self.logger.info("TradingEngine initialized (awaiting component injection)")

    def initialize_components(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        api_key: str,
        api_secret: str,
        is_testnet: bool,
    ) -> None:
        """
        Initialize all trading components (Issue #5, #110 Refactoring).

        Component Creation Order:
            1. ConfigManager injection
            2. EventBus injection
            3. OrderGateway
            4. RiskGuard
            5. Strategy (via StrategyFactory)
            6. BinanceDataCollector
            7. PositionCacheManager (Issue #110 Phase 1)
            8. TradeCoordinator (Issue #110 Phase 2)
            9. EventDispatcher (Issue #110 Phase 3)
            10. Strategy-DataCollector compatibility validation (Issue #24)
            11. Event handler registration
            12. Leverage and margin type configuration (API calls)

        State Transition:
            CREATED → INITIALIZED
        """
        self.logger.info("Initializing TradingEngine components...")

        # Step 1: Store config and event bus
        self.config_manager = config_manager
        self.event_bus = event_bus
        trading_config = config_manager.trading_config

        # Store logging config for conditional live data logging
        self._log_live_data = getattr(
            config_manager.logging_config, "log_live_data", True
        )

        # Step 1.5: Initialize BinanceServiceClient
        self.logger.info("Creating BinanceServiceClient...")
        from src.core.binance_service import BinanceServiceClient

        self.binance_service = BinanceServiceClient(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=is_testnet,
        )

        # Step 2: Initialize OrderGateway
        self.logger.info("Creating OrderGateway...")
        from src.execution.order_gateway import OrderGateway

        self.order_gateway = OrderGateway(
            audit_logger=self.audit_logger,
            binance_service=self.binance_service,
        )

        # Step 3: Initialize RiskGuard
        self.logger.info("Creating RiskGuard...")
        from src.risk.risk_guard import RiskGuard

        self.risk_guard = RiskGuard(
            config={
                "max_risk_per_trade": trading_config.max_risk_per_trade,
                "default_leverage": trading_config.leverage,
                "max_leverage": 20,  # Hard limit
                "max_position_size_percent": 0.1,  # 10% of account
            },
            audit_logger=self.audit_logger,
        )

        # Step 4: Create strategy instance via StrategyFactory
        self.logger.info(f"Creating strategy: {trading_config.strategy}...")
        from src.strategies import StrategyFactory

        strategy_config = {
            "buffer_size": 100,
            "risk_reward_ratio": trading_config.take_profit_ratio,
            "stop_loss_percent": trading_config.stop_loss_percent,
        }

        # Merge strategy-specific configuration
        if trading_config.strategy_config:
            strategy_config.update(trading_config.strategy_config)
            self.logger.info(
                f"Strategy configuration loaded: "
                f"{list(trading_config.strategy_config.keys())}"
            )

        # Add exit configuration if available (Issue #43)
        if trading_config.exit_config is not None:
            strategy_config["exit_config"] = trading_config.exit_config
            self.logger.info(
                f"Dynamic exit configuration loaded: "
                f"enabled={trading_config.exit_config.dynamic_exit_enabled}, "
                f"strategy={trading_config.exit_config.exit_strategy}"
            )

        # Step 4.5: Create composable strategy instances per symbol
        from src.strategies.module_config_builder import build_module_config

        self.logger.info(
            f"Creating {len(trading_config.symbols)} composable strategy instances..."
        )
        self.strategies = {}
        for symbol in trading_config.symbols:
            module_config, intervals_override, min_rr_ratio = build_module_config(
                strategy_name=trading_config.strategy,
                strategy_config=strategy_config,
                exit_config=trading_config.exit_config,
            )
            self.strategies[symbol] = StrategyFactory.create_composed(
                symbol=symbol,
                config=strategy_config,
                module_config=module_config,
                intervals=intervals_override,
                min_rr_ratio=min_rr_ratio,
            )
            self.logger.info(f"  ✅ Strategy created for {symbol}")

        # Step 5: Initialize BinanceDataCollector with composition pattern (Issue #57)
        self.logger.info("Creating data collection components...")

        # Step 5a: Create PublicMarketStreamer for kline WebSocket
        from src.core.public_market_streamer import PublicMarketStreamer

        self.logger.info("  Creating PublicMarketStreamer...")
        market_streamer = PublicMarketStreamer(
            symbols=trading_config.symbols,
            intervals=trading_config.intervals,
            is_testnet=is_testnet,
            on_candle_callback=self.on_candle_received,
        )

        # Step 5b: Create PrivateUserStreamer for order updates
        from src.core.private_user_streamer import PrivateUserStreamer

        self.logger.info("  Creating PrivateUserStreamer...")
        user_streamer = PrivateUserStreamer(
            binance_service=self.binance_service,
            is_testnet=is_testnet,
        )

        # Step 5c: Create BinanceDataCollector facade with injected streamers
        from src.core.data_collector import BinanceDataCollector

        self.logger.info("  Creating BinanceDataCollector facade...")
        self.data_collector = BinanceDataCollector(
            binance_service=self.binance_service,
            market_streamer=market_streamer,
            user_streamer=user_streamer,
        )

        # Step 6: Create extracted modules (Issue #110)
        self.logger.info("Creating extracted modules (Issue #110)...")

        # Phase 1: PositionCacheManager
        self.position_cache_manager = PositionCacheManager(
            order_gateway=self.order_gateway,
            config_manager=self.config_manager,
        )

        # Phase 2: TradeCoordinator
        self.trade_coordinator = TradeCoordinator(
            order_gateway=self.order_gateway,
            risk_guard=self.risk_guard,
            config_manager=self.config_manager,
            audit_logger=self.audit_logger,
            position_cache_manager=self.position_cache_manager,
        )

        # Phase 3: EventDispatcher
        self.event_dispatcher = EventDispatcher(
            strategies=self.strategies,
            position_cache_manager=self.position_cache_manager,
            event_bus=self.event_bus,
            audit_logger=self.audit_logger,
            order_gateway=self.order_gateway,
            engine_state_getter=lambda: self._engine_state,
            event_loop_getter=lambda: self._event_loop,
            log_live_data=self._log_live_data,
        )

        # Step 6.5: Validate strategy-DataCollector compatibility (Issue #24)
        # Moved BEFORE event handlers and API calls to follow fail-fast principle
        self._validate_strategy_compatibility()

        # Step 7: Setup event handlers
        self._setup_event_handlers()

        # Step 8: Configure leverage and margin type for each symbol (Issue #8)
        self.logger.info("Configuring leverage and margin type...")
        for symbol in trading_config.symbols:
            success = self.order_gateway.set_leverage(symbol, trading_config.leverage)
            if not success:
                self.logger.warning(
                    f"Failed to set leverage to {trading_config.leverage}x for {symbol}. "
                    "Using current account leverage."
                )

            success = self.order_gateway.set_margin_type(
                symbol, trading_config.margin_type
            )
            if not success:
                self.logger.warning(
                    f"Failed to set margin type to {trading_config.margin_type} for {symbol}. "
                    "Using current margin type."
                )

        # Step 9: State transition
        self._engine_state = EngineState.INITIALIZED

        self.logger.info("✅ TradingEngine components initialized successfully")

    async def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """
        Wait until TradingEngine has captured its event loop.

        Prevents race condition where DataCollector starts sending candles
        before run() has executed and captured the event loop reference.
        """
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            self.logger.info("TradingEngine is ready")
            return True
        except asyncio.TimeoutError:
            self.logger.error(f"TradingEngine failed to become ready within {timeout}s")
            raise TimeoutError(f"Engine not ready after {timeout}s")

    async def run(self) -> None:
        """
        Start the trading engine and run until interrupted.

        Process Flow:
            1. Capture event loop
            2. Set _engine_state = RUNNING
            3. Signal _ready_event
            4. Start EventBus and DataCollector concurrently
            5. Run until interrupted
            6. Trigger graceful shutdown
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
                    asyncio.create_task(
                        self.data_collector.start_streaming(), name="datacollector"
                    )
                )
                self.logger.info("DataCollector streaming enabled")

                # Start User Data Stream for real-time order updates (Issue #54, #107)
                try:
                    await self.data_collector.start_user_streaming(
                        position_update_callback=self._on_position_update_from_websocket,
                        order_update_callback=self._on_order_update_from_websocket,
                        order_fill_callback=self._on_order_fill_from_websocket,
                    )
                    self.logger.info(
                        "User Data Stream enabled for order updates, position cache, and order cache"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to start User Data Stream: {e}. "
                        f"TP/SL orphan prevention will NOT work.",
                        exc_info=True,
                    )

            # Run until interrupted
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

    def _validate_strategy_compatibility(self) -> None:
        """
        Validate strategy-DataCollector interval compatibility (Issue #7 Phase 2, #8 Phase 2).

        Ensures each strategy's required intervals are available from DataCollector.
        Fails fast at initialization time rather than silently dropping events.
        """
        from src.core.exceptions import ConfigurationError

        available_intervals = set(self.data_collector.intervals)

        for symbol, strategy in self.strategies.items():
            required_intervals = set(strategy.intervals)
            missing_intervals = required_intervals - available_intervals

            if missing_intervals:
                error_msg = (
                    f"Strategy for {symbol} requires intervals {sorted(required_intervals)} "
                    f"but DataCollector only provides {sorted(available_intervals)}. "
                    f"Missing: {sorted(missing_intervals)}. "
                    f"Update config.trading.intervals to include all required intervals."
                )
                self.logger.error(error_msg)
                raise ConfigurationError(error_msg)

            # Log validation success
            if len(required_intervals) > 1:
                self.logger.info(
                    f"✅ Strategy-DataCollector compatibility validated for {symbol}: "
                    f"Strategy requires {sorted(required_intervals)}, "
                    f"DataCollector provides {sorted(available_intervals)}"
                )
            else:
                self.logger.info(
                    f"✅ Strategy-DataCollector compatibility validated for {symbol}: "
                    f"Single-interval strategy with {list(required_intervals)[0]}"
                )

    async def initialize_strategy_with_backfill(self, default_limit: int = 100) -> None:
        """
        Initialize strategy with historical data by fetching directly from API.

        Called once during system startup to pre-populate strategy buffers
        before WebSocket streaming begins.

        Uses per-interval backfill limits from strategy.data_requirements
        when available, falling back to default_limit.
        """
        if not self.strategies:
            self.logger.warning(
                "No strategies initialized, skipping historical data initialization"
            )
            return

        if not self.data_collector:
            self.logger.warning(
                "DataCollector not injected, "
                "skipping historical data initialization"
            )
            return

        self.logger.info(
            f"Initializing {len(self.strategies)} strategies "
            f"with default {default_limit} historical candles per interval (sequential to avoid rate limits)"
        )

        # Initialize each symbol's strategy sequentially (Issue #8 Phase 3)
        symbol_count = 0
        for symbol, strategy in self.strategies.items():
            symbol_count += 1
            try:
                self.logger.info(
                    f"[{symbol_count}/{len(self.strategies)}] "
                    f"Initializing strategy for {symbol}..."
                )

                self.logger.info(
                    f"Initializing strategy intervals: "
                    f"{strategy.intervals} for {symbol}"
                )

                # Use per-interval backfill limits from module requirements
                requirements = strategy.data_requirements

                initialized_count = 0
                for interval in strategy.intervals:
                    try:
                        limit = requirements.min_candles.get(interval, default_limit)
                        candles = self.data_collector.get_historical_candles(
                            symbol=symbol, interval=interval, limit=limit
                        )

                        if candles:
                            self.logger.info(
                                f"Fetched {len(candles)} candles "
                                f"for {symbol} {interval}"
                            )

                            strategy.initialize_with_historical_data(
                                candles, interval=interval
                            )
                            initialized_count += 1
                        else:
                            self.logger.warning(
                                f"No candles returned for {symbol} {interval}"
                            )

                    except Exception as e:
                        self.logger.error(
                            f"Failed to fetch {symbol} {interval}: {e}"
                        )

                if initialized_count > 0:
                    self.logger.info(
                        f"✅ Strategy initialization complete: "
                        f"{initialized_count}/{len(strategy.intervals)} intervals "
                        f"initialized for {symbol}"
                    )
                else:
                    self.logger.warning(
                        f"No intervals initialized for strategy '{symbol}'"
                    )

            except Exception as e:
                self.logger.error(
                    f"❌ Failed to initialize strategy for {symbol}: {e}",
                    exc_info=True,
                )

            # Rate limit protection: Wait between symbols (Issue #8 Phase 3)
            if symbol_count < len(self.strategies):
                delay = 0.5
                self.logger.debug(
                    f"Waiting {delay}s before next symbol "
                    f"(rate limit protection)..."
                )
                await asyncio.sleep(delay)

    def _setup_event_handlers(self) -> None:
        """
        Register event subscriptions with EventBus.

        Delegates to extracted modules (Issue #110):
        - CANDLE_CLOSED → EventDispatcher.on_candle_closed
        - SIGNAL_GENERATED → TradeCoordinator.on_signal_generated
        - ORDER_FILLED → TradeCoordinator.on_order_filled
        - ORDER_PARTIALLY_FILLED → TradeCoordinator.on_order_partially_filled
        """
        self.event_bus.subscribe(EventType.CANDLE_CLOSED, self.event_dispatcher.on_candle_closed)
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self.trade_coordinator.on_signal_generated)
        self.event_bus.subscribe(EventType.ORDER_FILLED, self.trade_coordinator.on_order_filled)
        self.event_bus.subscribe(EventType.ORDER_PARTIALLY_FILLED, self.trade_coordinator.on_order_partially_filled)

        self.logger.info("✅ Event handlers registered (Issue #110 - delegated):")
        self.logger.info("  - CANDLE_CLOSED → EventDispatcher.on_candle_closed")
        self.logger.info("  - SIGNAL_GENERATED → TradeCoordinator.on_signal_generated")
        self.logger.info("  - ORDER_FILLED → TradeCoordinator.on_order_filled")
        self.logger.info("  - ORDER_PARTIALLY_FILLED → TradeCoordinator.on_order_partially_filled")

    def on_candle_received(self, candle: Candle) -> None:
        """
        Callback from BinanceDataCollector on every candle update.

        Delegates to EventDispatcher.on_candle_received() (Issue #110 Phase 3).
        """
        self.event_dispatcher.on_candle_received(candle)

    def _on_order_update_from_websocket(
        self, symbol: str, order_id: str, order_status: str, order_data: dict
    ) -> None:
        """
        Handle order updates from WebSocket ORDER_TRADE_UPDATE events.

        Updates order cache in order_gateway directly from WebSocket data.
        """
        if self.order_gateway is None:
            return

        try:
            self.order_gateway.update_order_cache_from_websocket(
                symbol=symbol,
                order_id=order_id,
                order_status=order_status,
                order_data=order_data,
            )
        except Exception as e:
            self.logger.warning(f"Failed to update order cache from WebSocket: {e}")

    def _on_order_fill_from_websocket(self, order_data: dict) -> None:
        """
        Handle order fill events from WebSocket ORDER_TRADE_UPDATE via callback.

        Creates Order and Event objects from raw WebSocket data and publishes
        to EventBus (Issue #107).

        Thread Safety:
            Called from WebSocket thread. Uses asyncio.run_coroutine_threadsafe()
            to publish to EventBus in the main event loop.
        """
        from src.models.order import Order, OrderType, OrderStatus, OrderSide

        order_status = order_data.get("X")
        order_type = order_data.get("ot")
        symbol = order_data.get("s")
        order_id = str(order_data.get("i", ""))

        # Extract callback_rate for TRAILING_STOP_MARKET orders
        callback_rate = None
        if order_type == "TRAILING_STOP_MARKET":
            callback_rate = float(order_data.get("cr", 0)) if order_data.get("cr") else 1.0

        is_filled = order_status == "FILLED"

        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=OrderSide(order_data.get("S")),
            order_type=OrderType(order_type),
            quantity=float(order_data.get("q", 0)),
            price=float(order_data.get("ap", 0)),
            stop_price=float(order_data.get("sp", 0)) if order_data.get("sp") else None,
            callback_rate=callback_rate,
            status=OrderStatus.FILLED if is_filled else OrderStatus.PARTIALLY_FILLED,
            filled_quantity=float(order_data.get("z", 0)),
        )

        event = Event(
            event_type=EventType.ORDER_FILLED if is_filled else EventType.ORDER_PARTIALLY_FILLED,
            data=order,
            source="user_data_stream",
        )

        # Publish to EventBus (thread-safe via run_coroutine_threadsafe)
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(event, queue_type=QueueType.ORDER),
                self._event_loop,
            )
            self.logger.info(
                f"Published {event.event_type.value.upper()} event for "
                f"{symbol} {order_type} "
                f"(filled: {order.filled_quantity}/{order.quantity})"
            )
        else:
            self.logger.warning(
                f"Cannot publish {event.event_type.value.upper()} event: "
                f"Event loop not available"
            )

    def _on_position_update_from_websocket(self, position_updates: list) -> None:
        """
        Handle position updates from WebSocket ACCOUNT_UPDATE events.

        Delegates to PositionCacheManager (Issue #110 Phase 1).
        """
        if self.position_cache_manager is not None:
            self.position_cache_manager.update_from_websocket(
                position_updates=position_updates,
                allowed_symbols=set(self.strategies.keys()),
            )
