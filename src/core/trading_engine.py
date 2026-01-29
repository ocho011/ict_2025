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
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any

# Imports for type hinting only; prevents circular dependency at runtime
# Only imported during static analysis (e.g., mypy, IDE)
if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.main import TradingBot
    from src.models.position import Position

from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.execution.order_manager import OrderExecutionManager
from src.models.candle import Candle
from src.models.event import Event, EventType, QueueType
from src.models.order import Order
from src.models.signal import Signal
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.utils.config import ConfigManager


from enum import Enum


class EngineState(Enum):
    """
    State machine for TradingEngine lifecycle.

    State Transitions:
        CREATED → INITIALIZED → RUNNING → STOPPING → STOPPED

    States:
        CREATED: Initial state after __init__()
        INITIALIZED: After initialize_components() called
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

        Components are created via initialize_components() method after construction.
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
            5. Wait for initialize_components() call

        Example:
            ```python
            from src.core.audit_logger import AuditLogger

            audit_logger = AuditLogger(log_dir="logs/audit")
            engine = TradingEngine(audit_logger=audit_logger)
            engine.initialize_components(
                config_manager=config_manager,
                event_bus=event_bus,
                api_key="...",
                api_secret="...",
                is_testnet=True
            )
            await engine.run()
            ```
        """
        self.logger = logging.getLogger(__name__)

        # Inject audit logger
        self.audit_logger = audit_logger

        # Components (created via initialize_components)
        self.event_bus: Optional[EventBus] = None
        self.data_collector: Optional[BinanceDataCollector] = None
        self.strategies: dict[str, BaseStrategy] = {}  # Issue #8: Multi-coin support
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
        self._heartbeat_gap_logged = False

        # Position cache for exit signal handling (Issue #25)
        # Cache structure: {symbol: (position, timestamp)}
        # TTL of 5 seconds to reduce API rate limit pressure
        self._position_cache: dict[str, tuple[Optional["Position"], float]] = {}
        self._position_cache_ttl: float = 5.0  # seconds

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
        Initialize all trading components (Step 1-1: Issue #5 Refactoring).

        TradingEngine now owns the responsibility of creating and assembling
        trading-specific components (Strategy, DataCollector, OrderManager, RiskManager).
        This simplifies TradingBot to only handle lifecycle and common utilities.

        Args:
            config_manager: Configuration management system
            event_bus: EventBus instance for pub-sub coordination
            api_key: Binance API key
            api_secret: Binance API secret
            is_testnet: Whether to use testnet

        Component Creation Order:
            1. ConfigManager injection
            2. EventBus injection
            3. OrderExecutionManager
            4. RiskManager
            5. Strategy (via StrategyFactory)
            6. BinanceDataCollector
            7. **Strategy-DataCollector compatibility validation (Issue #24)**
            8. Event handler registration
            9. Leverage and margin type configuration (API calls)

        State Transition:
            CREATED → INITIALIZED

        Notes:
            - Must be called before run()
            - Components are created internally, not injected
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

        # Step 2: Initialize OrderExecutionManager
        self.logger.info("Creating OrderExecutionManager...")
        from src.execution.order_manager import OrderExecutionManager

        self.order_manager = OrderExecutionManager(
            audit_logger=self.audit_logger,
            binance_service=self.binance_service,
        )

        # Step 3: Initialize RiskManager
        self.logger.info("Creating RiskManager...")
        from src.risk.manager import RiskManager

        self.risk_manager = RiskManager(
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

        # Add ICT-specific configuration if available
        if trading_config.ict_config is not None:
            strategy_config.update(trading_config.ict_config)
            self.logger.info(
                f"ICT configuration loaded: "
                f"use_killzones={trading_config.ict_config.get('use_killzones', True)}"
            )

        # Add exit configuration if available (Issue #43)
        if trading_config.exit_config is not None:
            strategy_config["exit_config"] = trading_config.exit_config
            self.logger.info(
                f"Dynamic exit configuration loaded: "
                f"enabled={trading_config.exit_config.dynamic_exit_enabled}, "
                f"strategy={trading_config.exit_config.exit_strategy}"
            )

        # Step 4.5: Create strategy instances per symbol (Issue #8 Phase 2)
        MAX_SYMBOLS = 10
        if len(trading_config.symbols) > MAX_SYMBOLS:
            from src.core.exceptions import ConfigurationError

            raise ConfigurationError(
                f"Maximum {MAX_SYMBOLS} symbols allowed, got {len(trading_config.symbols)}"
            )

        self.logger.info(
            f"Creating {len(trading_config.symbols)} strategy instances..."
        )
        self.strategies = {}
        for symbol in trading_config.symbols:
            self.strategies[symbol] = StrategyFactory.create(
                name=trading_config.strategy, symbol=symbol, config=strategy_config
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

        # Step 5.5: Validate strategy-DataCollector compatibility (Issue #24)
        # Moved BEFORE event handlers and API calls to follow fail-fast principle
        self._validate_strategy_compatibility()

        # Step 6: Setup event handlers
        self._setup_event_handlers()

        # Step 7: Configure leverage and margin type for each symbol (Issue #8)
        self.logger.info("Configuring leverage and margin type...")
        for symbol in trading_config.symbols:
            success = self.order_manager.set_leverage(symbol, trading_config.leverage)
            if not success:
                self.logger.warning(
                    f"Failed to set leverage to {trading_config.leverage}x for {symbol}. "
                    "Using current account leverage."
                )

            success = self.order_manager.set_margin_type(
                symbol, trading_config.margin_type
            )
            if not success:
                self.logger.warning(
                    f"Failed to set margin type to {trading_config.margin_type} for {symbol}. "
                    "Using current margin type."
                )

        # Step 8: State transition
        self._engine_state = EngineState.INITIALIZED

        self.logger.info("✅ TradingEngine components initialized successfully")

    def _validate_strategy_compatibility(self) -> None:
        """
        Validate strategy-DataCollector interval compatibility (Issue #7 Phase 2, #8 Phase 2).

        Ensures each strategy's required intervals are available from DataCollector.
        Fails fast at initialization time rather than silently dropping events.

        Validation Rules:
            1. MultiTimeframeStrategy: All strategy.intervals MUST be in data_collector.intervals
            2. BaseStrategy (single-interval): Warning if data_collector has multiple intervals

        Raises:
            ConfigurationError: If any strategy's intervals not satisfied
        """
        from src.core.exceptions import ConfigurationError

        # Validate each strategy instance (Issue #8: Multi-coin support)
        # Issue #27: Unified buffer structure - all strategies have .intervals
        available_intervals = set(self.data_collector.intervals)

        for symbol, strategy in self.strategies.items():
            # Issue #27: All strategies now have intervals attribute (unified interface)
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

    async def initialize_strategy_with_backfill(self, limit: int = 100) -> None:
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
            - Must be called AFTER initialize_components()
            - Must be called BEFORE start_streaming()
            - Does NOT trigger signal generation
        """
        if not self.strategies:
            self.logger.warning(
                "[TradingEngine] No strategies initialized, skipping historical data initialization"
            )
            return

        if not self.data_collector:
            self.logger.warning(
                "[TradingEngine] DataCollector not injected, "
                "skipping historical data initialization"
            )
            return

        self.logger.info(
            f"[TradingEngine] Initializing {len(self.strategies)} strategies "
            f"with {limit} historical candles per interval (sequential to avoid rate limits)"
        )

        # Initialize each symbol's strategy sequentially (Issue #8 Phase 3)
        # Use asyncio.sleep() between symbols to avoid API rate limit
        symbol_count = 0
        for symbol, strategy in self.strategies.items():
            symbol_count += 1
            try:
                self.logger.info(
                    f"[TradingEngine] [{symbol_count}/{len(self.strategies)}] "
                    f"Initializing strategy for {symbol}..."
                )

                # Issue #27: Unified initialization - all strategies have intervals attribute
                # Fetch and initialize each interval the strategy needs
                self.logger.info(
                    f"[TradingEngine] Initializing strategy intervals: "
                    f"{strategy.intervals} for {symbol}"
                )

                initialized_count = 0
                for interval in strategy.intervals:
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

                            # Issue #27: Unified call signature (candles, interval=interval)
                            strategy.initialize_with_historical_data(
                                candles, interval=interval
                            )
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
                        f"[TradingEngine] ✅ Strategy initialization complete: "
                        f"{initialized_count}/{len(strategy.intervals)} intervals "
                        f"initialized for {symbol}"
                    )
                else:
                    self.logger.warning(
                        f"[TradingEngine] No intervals initialized for strategy '{symbol}'"
                    )

            except Exception as e:
                self.logger.error(
                    f"[TradingEngine] ❌ Failed to initialize strategy for {symbol}: {e}",
                    exc_info=True,
                )

            # Rate limit protection: Wait between symbols (Issue #8 Phase 3)
            # Skip delay after last symbol
            if symbol_count < len(self.strategies):
                delay = 0.5  # 500ms delay to avoid API rate limit
                self.logger.debug(
                    f"[TradingEngine] Waiting {delay}s before next symbol "
                    f"(rate limit protection)..."
                )
                await asyncio.sleep(delay)

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
            - Called automatically by initialize_components()
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

    def _get_cached_position(self, symbol: str) -> Optional["Position"]:
        """
        Get cached position for symbol, refreshing if TTL expired.

        Uses cached position to reduce API rate limit pressure.
        Cache TTL is 5 seconds by default.

        Args:
            symbol: Trading pair to get position for

        Returns:
            Position if exists and cache valid, None otherwise
            (Returns None on API failure to prevent using stale/uncertain data - Issue #41)
        """
        current_time = time.time()

        # Check if cache exists and is still valid
        if symbol in self._position_cache:
            cached_position, cache_time = self._position_cache[symbol]
            if current_time - cache_time < self._position_cache_ttl:
                return cached_position

        # Cache expired or missing - refresh from API
        try:
            position = self.order_manager.get_position(symbol)
            self._position_cache[symbol] = (position, current_time)
            return position
        except Exception as e:
            self.logger.error(
                f"Failed to refresh position cache for {symbol}: {e}. "
                f"Returning None to indicate uncertain state (Issue #41)."
            )
            # CRITICAL: Do NOT update self._position_cache[symbol] here.
            # This allows callers to distinguish between success (None in cache)
            # and failure (expired data in cache).
            return None

    def _invalidate_position_cache(self, symbol: str) -> None:
        """
        Invalidate position cache for symbol.

        Called after order execution to ensure fresh position data
        is fetched on next check.

        Args:
            symbol: Trading pair to invalidate cache for
        """
        if symbol in self._position_cache:
            del self._position_cache[symbol]
            self.logger.debug(f"Position cache invalidated for {symbol}")

    async def _on_candle_closed(self, event: Event) -> None:
        """
        Handle closed candle event - run strategy analysis (Issue #7 Phase 3, #42 Refactor).

        This handler is called when a candle fully closes (is_closed=True).
        It runs the trading strategy analysis and publishes signals if conditions are met.

        Args:
            event: Event containing closed Candle data
        """
        # 1. Validation (Guard Clauses)
        candle: Candle = event.data

        # Unknown symbol validation (Issue #8 Phase 2 - Fail-fast)
        if candle.symbol not in self.strategies:
            self.logger.error(
                f"❌ Unknown symbol: {candle.symbol}. "
                f"Configured symbols: {list(self.strategies.keys())}"
            )
            return

        # Get strategy for this symbol
        strategy = self.strategies[candle.symbol]

        # Filter intervals based on strategy configuration (Issue #27 unified)
        if candle.interval not in strategy.intervals:
            self.logger.debug(
                f"Filtering {candle.interval} candle for {candle.symbol} "
                f"(strategy expects {strategy.intervals})"
            )
            return

        # Log candle received (info level)
        self.logger.info(
            f"Analyzing closed candle: {candle.symbol} {candle.interval} "
            f"@ {candle.close} (vol: {candle.volume})"
        )

        # 2. Routing (Issue #42)
        current_position = self._get_cached_position(candle.symbol)

        # Issue #41: Handle uncertain position state.
        # If _get_cached_position returns None, it could be "No Position" or "API Failure".
        # We must skip analysis if the state is uncertain to prevent incorrect entries.
        if current_position is None:
            # Check if cache was actually updated successfully (confirmed None state)
            if candle.symbol not in self._position_cache:
                self.logger.warning(
                    f"Position state unknown for {candle.symbol}, skipping analysis"
                )
                return

            _, cache_time = self._position_cache[candle.symbol]
            if time.time() - cache_time >= self._position_cache_ttl:
                # Cache is stale, meaning _get_cached_position failed to refresh it
                self.logger.warning(
                    f"Position state uncertain for {candle.symbol} (cache expired and refresh failed), "
                    f"skipping analysis to prevent incorrect entry"
                )
                return

        if current_position is not None:
            # Position exists - check exit conditions first (Issue #25)
            await self._process_exit_strategy(candle, strategy, current_position)
            return  # Always skip entry analysis if position exists

        # 3. No position - check entry conditions
        await self._process_entry_strategy(candle, strategy)

    async def _process_exit_strategy(
        self, candle: Candle, strategy: BaseStrategy, position: "Position"
    ) -> bool:
        """
        Check exit conditions for existing position (Issue #42).

        Returns:
            True if exit signal was generated and published, False otherwise.
        """
        self.logger.debug(
            f"Position exists for {candle.symbol}: {position.side} "
            f"@ {position.entry_price}, checking exit conditions"
        )

        try:
            exit_signal = await strategy.should_exit(position, candle)
        except Exception as e:
            self.logger.error(
                f"Strategy should_exit failed for {candle.symbol}: {e}", exc_info=True
            )
            exit_signal = None

        if exit_signal is not None:
            await self._publish_signal_with_audit(
                signal=exit_signal,
                candle=candle,
                operation="exit_analysis",
                audit_data={
                    "position_side": position.side,
                    "position_quantity": position.quantity,
                },
            )
            return True

        self.logger.debug(
            f"No exit signal for {candle.symbol}, position still open - skipping entry analysis"
        )
        return False

    async def _process_entry_strategy(
        self, candle: Candle, strategy: BaseStrategy
    ) -> None:
        """
        Check new entry conditions (Issue #42).
        """
        try:
            signal = await strategy.analyze(candle)
        except Exception as e:
            # Don't crash on strategy errors
            self.logger.error(
                f"Strategy analysis failed for {candle.symbol}: {e}", exc_info=True
            )
            return

        # If signal exists, publish SIGNAL_GENERATED event
        if signal is not None:
            await self._publish_signal_with_audit(
                signal=signal, candle=candle, operation="candle_analysis"
            )
        else:
            # Info log for no signal (shows strategy is working)
            self.logger.info(
                f"✓ No signal: {candle.symbol} {candle.interval} (strategy conditions not met)"
            )

    async def _publish_signal_with_audit(
        self,
        signal: Signal,
        candle: Candle,
        operation: str,
        audit_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Common handling for audit log recording and EventBus publication (Issue #42).
        """
        # 1. Log generation status
        if signal.is_exit_signal:
            self.logger.info(
                f"Exit signal generated: {signal.signal_type.value} "
                f"@ {signal.entry_price} (reason: {signal.exit_reason})"
            )
        else:
            self.logger.info(
                f"Entry signal generated: {signal.signal_type.value} "
                f"@ {signal.entry_price} (TP: {signal.take_profit}, "
                f"SL: {signal.stop_loss})"
            )

        # 2. Audit log: signal generated
        try:
            from src.core.audit_logger import AuditEventType

            full_audit_data = {
                "interval": candle.interval,
                "close_price": candle.close,
                "signal_generated": True,
                "signal_type": signal.signal_type.value,
                "strategy_name": signal.strategy_name,
            }

            if signal.is_exit_signal:
                full_audit_data.update(
                    {
                        "exit_price": signal.entry_price,
                        "exit_reason": signal.exit_reason,
                    }
                )
            else:
                full_audit_data.update(
                    {
                        "entry_price": signal.entry_price,
                        "take_profit": signal.take_profit,
                        "stop_loss": signal.stop_loss,
                    }
                )

            # Add any additional audit data passed in
            if audit_data:
                full_audit_data.update(audit_data)

            self.audit_logger.log_event(
                event_type=AuditEventType.SIGNAL_PROCESSING,
                operation=operation,
                symbol=candle.symbol,
                additional_data=full_audit_data,
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        # 3. Create event and publish to 'signal' queue
        signal_event = Event(EventType.SIGNAL_GENERATED, signal)
        await self.event_bus.publish(signal_event, queue_type=QueueType.SIGNAL)

    async def _on_signal_generated(self, event: Event) -> None:
        """
        Handle generated signal - validate and execute order.

        This is the critical trading logic that:
        1. Validates signal with RiskManager
        2. For entry signals: Calculates position size and executes with TP/SL
        3. For exit signals: Uses position quantity and executes with reduce_only

        Args:
            event: Event containing Signal data
        """
        # Step 1: Extract signal from event data
        signal: Signal = event.data

        self.logger.info(
            f"Processing signal: {signal.signal_type.value} for {signal.symbol}"
        )

        try:
            # Step 2: Get current position from OrderManager (fresh query for execution)
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

            # Step 4: Handle exit vs entry signals differently (Issue #25)
            if signal.is_exit_signal:
                # Exit signal: use position quantity and reduce_only
                await self._execute_exit_signal(signal, current_position)
                return

            # Entry signal: calculate position size and execute with TP/SL
            # Step 5: Get account balance
            account_balance = self.order_manager.get_account_balance()

            if account_balance <= 0:
                self.logger.error(
                    f"Invalid account balance: {account_balance}, cannot execute signal"
                )
                return

            # Step 6: Calculate position size using RiskManager
            quantity = self.risk_manager.calculate_position_size(
                account_balance=account_balance,
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                leverage=self.config_manager.trading_config.leverage,
                symbol_info=None,  # OrderManager will handle rounding internally
            )

            # Step 7: Execute signal via OrderManager
            # Returns (entry_order, [tp_order, sl_order])
            entry_order, tpsl_orders = self.order_manager.execute_signal(
                signal=signal, quantity=quantity
            )

            # Invalidate position cache after order execution
            self._invalidate_position_cache(signal.symbol)

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
            await self.event_bus.publish(order_event, queue_type=QueueType.ORDER)

        except Exception as e:
            # Step 9: Catch and log execution errors without crashing
            self.logger.error(
                f"Failed to execute signal for {signal.symbol}: {e}", exc_info=True
            )

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

    async def _execute_exit_signal(self, signal: Signal, position: "Position") -> None:
        """
        Execute an exit signal to close a position.

        Uses position quantity and executes with reduce_only to prevent
        accidentally opening a new position in the opposite direction.

        Args:
            signal: Exit signal (CLOSE_LONG or CLOSE_SHORT)
            position: Current position to close

        Process:
            1. Cancel any existing TP/SL orders
            2. Execute market order with reduce_only=True
            3. Invalidate position cache
            4. Log execution and audit trail
        """
        from src.models.signal import SignalType

        try:
            self.logger.info(
                f"Executing exit signal: {signal.signal_type.value} for {signal.symbol} "
                f"(qty: {position.quantity}, reason: {signal.exit_reason})"
            )

            # Step 1: Cancel any existing TP/SL orders first
            try:
                cancelled_count = self.order_manager.cancel_all_orders(signal.symbol)
                if cancelled_count > 0:
                    self.logger.info(
                        f"Cancelled {cancelled_count} existing orders before exit"
                    )
            except Exception as e:
                self.logger.warning(f"Failed to cancel existing orders: {e}")

            # Step 2: Execute close order using position quantity
            # Determine side based on signal type (SELL to close LONG, BUY to close SHORT)
            close_side = (
                "SELL" if signal.signal_type == SignalType.CLOSE_LONG else "BUY"
            )

            # Execute close order with reduce_only via async method
            result = await self.order_manager.execute_market_close(
                symbol=signal.symbol,
                position_amt=position.quantity,
                side=close_side,
                reduce_only=True,
            )

            # Step 3: Invalidate position cache
            self._invalidate_position_cache(signal.symbol)

            # Step 4: Check result and log
            if result.get("success"):
                order_id = result.get("order_id")
                exit_price = result.get("avg_price", 0.0)
                executed_qty = result.get("executed_qty", position.quantity)

                # Calculate realized PnL
                # LONG: (exit_price - entry_price) * quantity
                # SHORT: (entry_price - exit_price) * quantity
                if position.side == "LONG":
                    realized_pnl = (exit_price - position.entry_price) * executed_qty
                else:
                    realized_pnl = (position.entry_price - exit_price) * executed_qty

                # Calculate duration if entry_time is available
                duration_seconds = None
                if position.entry_time:
                    from datetime import datetime, timezone

                    duration = (
                        datetime.now(timezone.utc)
                        - position.entry_time.replace(tzinfo=timezone.utc)
                        if position.entry_time.tzinfo is None
                        else datetime.now(timezone.utc) - position.entry_time
                    )
                    duration_seconds = duration.total_seconds()

                self.logger.info(
                    f"✅ Position closed successfully: "
                    f"Order ID={order_id}, "
                    f"Quantity={executed_qty}, "
                    f"Exit price={exit_price}, "
                    f"Realized PnL={realized_pnl:.4f}, "
                    f"Exit reason={signal.exit_reason}"
                )

                # Audit log: trade_closed event with full exit details
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.TRADE_CLOSED,
                        operation="execute_exit",
                        symbol=signal.symbol,
                        data={
                            "exit_price": exit_price,
                            "realized_pnl": realized_pnl,
                            "exit_reason": signal.exit_reason,
                            "duration_seconds": duration_seconds,
                            "entry_price": position.entry_price,
                            "quantity": executed_qty,
                            "position_side": position.side,
                            "leverage": position.leverage,
                            "signal_type": signal.signal_type.value,
                        },
                        response={
                            "close_order_id": order_id,
                            "status": result.get("status"),
                        },
                    )
                except Exception as e:
                    self.logger.warning(f"Audit logging failed: {e}")
            else:
                error_msg = result.get("error", "Unknown error")
                self.logger.error(
                    f"Failed to close position for {signal.symbol}: {error_msg}"
                )

                # Audit log: exit execution failed
                try:
                    from src.core.audit_logger import AuditEventType

                    self.audit_logger.log_event(
                        event_type=AuditEventType.TRADE_EXECUTION_FAILED,
                        operation="execute_exit",
                        symbol=signal.symbol,
                        order_data={
                            "signal_type": signal.signal_type.value,
                            "exit_price": signal.entry_price,
                            "exit_reason": signal.exit_reason,
                        },
                        error={"reason": error_msg},
                    )
                except Exception:
                    pass

        except Exception as e:
            self.logger.error(
                f"Failed to execute exit signal for {signal.symbol}: {e}", exc_info=True
            )

            # Audit log: exit execution failed
            try:
                from src.core.audit_logger import AuditEventType

                self.audit_logger.log_event(
                    event_type=AuditEventType.TRADE_EXECUTION_FAILED,
                    operation="execute_exit",
                    symbol=signal.symbol,
                    order_data={
                        "signal_type": signal.signal_type.value,
                        "exit_price": signal.entry_price,
                        "exit_reason": signal.exit_reason,
                    },
                    error={"error_type": type(e).__name__, "error_message": str(e)},
                )
            except Exception:
                pass

    async def _on_order_filled(self, event: Event) -> None:
        """
        Handle order fill notification (Issue #9: Enhanced with orphan order prevention).

        Logs order fills for tracking and monitoring. When a TP/SL order is filled,
        automatically cancels any remaining orders for the symbol to prevent orphaned orders.

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
            f"Type={order.order_type.value}, "
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

        # Step 3: Handle TP/SL fills - cancel remaining orders (Issue #9)
        from src.models.order import OrderType

        if order.order_type in (
            OrderType.STOP_MARKET,
            OrderType.TAKE_PROFIT_MARKET,
            OrderType.STOP,
            OrderType.TAKE_PROFIT,
            OrderType.TRAILING_STOP_MARKET,
        ):
            # TP or SL was hit - position is closed
            # Cancel any remaining orders (the other TP/SL) to prevent orphaned orders
            self.logger.info(
                f"{order.order_type.value} filled for {order.symbol} - "
                f"cancelling remaining orders to prevent orphans"
            )

            try:
                cancelled_count = self.order_manager.cancel_all_orders(order.symbol)
                if cancelled_count > 0:
                    self.logger.info(
                        f"TP/SL hit: cancelled {cancelled_count} remaining orders "
                        f"for {order.symbol}"
                    )
                else:
                    self.logger.info(
                        f"TP/SL hit: no remaining orders to cancel for {order.symbol}"
                    )
            except Exception as e:
                # Log error but don't crash - orphaned orders are a data issue, not a critical failure
                self.logger.error(
                    f"Failed to cancel remaining orders after TP/SL fill: {e}. "
                    f"Manual cleanup may be required for {order.symbol}."
                )

        # Step 4: Update position tracking (future enhancement)
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
        event_type = (
            EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE
        )

        # Step 4: Create Event wrapper
        event = Event(event_type, candle)

        # Step 5: Publish to EventBus (thread-safe)
        try:
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(event, queue_type=QueueType.DATA),
                self._event_loop,
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
            # Log continuous live data updates (configurable via log_live_data)
            if self._log_live_data:
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
                    asyncio.create_task(
                        self.data_collector.start_streaming(), name="datacollector"
                    )
                )
                self.logger.info("DataCollector streaming enabled")

                # Start User Data Stream for real-time order updates (Issue #54)
                # This enables TP/SL fill detection to prevent orphaned orders
                try:
                    await self.data_collector.start_user_data_stream(self.event_bus)
                    self.logger.info("User Data Stream enabled for order updates")
                except Exception as e:
                    self.logger.error(
                        f"Failed to start User Data Stream: {e}. "
                        f"TP/SL orphan prevention will NOT work.",
                        exc_info=True,
                    )

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
