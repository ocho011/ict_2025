"""
Main entry point for the ICT 2025 Trading System.

This module implements the TradingBot class that orchestrates all system components
including data collection, strategy execution, risk management, and order execution.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

# Add project root to Python path for imports
# This allows running main.py from any directory (PyCharm, terminal, etc.)
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from enum import Enum, auto

from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.core.trading_engine import TradingEngine
from src.execution.liquidation_config import LiquidationConfig
from src.execution.liquidation_manager import LiquidationManager
from src.execution.order_manager import OrderExecutionManager
from src.models.candle import Candle
from src.models.event import Event, EventType
from src.risk.manager import RiskManager
from src.strategies import StrategyFactory
from src.strategies.base import BaseStrategy
from src.utils.config import ConfigManager
from src.utils.logger import TradingLogger


class LifecycleState(Enum):
    """Trading bot lifecycle states for event handling control."""

    INITIALIZING = auto()  # __init__ phase
    STARTING = auto()  # initialize() in progress
    RUNNING = auto()  # Fully operational
    STOPPING = auto()  # shutdown() in progress
    STOPPED = auto()  # Shutdown complete


class TradingBot:
    """
    Main trading bot orchestrator that manages all system components.

    Lifecycle:
        1. __init__() - Minimal constructor setup
        2. initialize() - Component initialization
        3. run() - Asynchronous runtime loop
        4. shutdown() - Graceful cleanup

    Attributes:
        config_manager: Configuration management system
        event_bus: Event coordination and pub-sub system
        data_collector: WebSocket data collection from Binance
        order_manager: Order execution and position management
        risk_manager: Risk validation and position sizing
        strategy: Trading strategy implementation
        logger: Application logger
        _running: Bot runtime state flag
    """

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
        self.trading_engine: Optional[TradingEngine] = None
        self.liquidation_manager: Optional[LiquidationManager] = None
        self.logger: Optional[logging.Logger] = None
        self.trading_logger: Optional[TradingLogger] = None  # For cleanup

        # State management
        self._running: bool = False

        # Event loop reference and lifecycle state
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._lifecycle_state: LifecycleState = LifecycleState.INITIALIZING
        self._event_drop_count: int = 0  # Monitor rejected events

    def initialize(self) -> None:
        """
        Initialize all trading bot components in correct dependency order.

        Initialization Sequence:
            1. ConfigManager - Load all configurations
            2. Validate - Ensure config is valid before proceeding
            3. TradingLogger - Setup logging infrastructure
            4. Startup Banner - Log environment information
            5. BinanceDataCollector - WebSocket client with callback
            5.5. Backfill Historical Data - Pre-populate candle buffers
            6. OrderExecutionManager - Order execution interface
            7. RiskManager - Risk validation and position sizing
            8. StrategyFactory - Create strategy instance
            9. EventBus - Event coordination system
            10. Event Handlers + Leverage Setup

        Raises:
            ValueError: If configuration validation fails
            Exception: For any component initialization failure

        Note:
            - Uses testnet by default for safety
            - Logs comprehensive startup information
            - Fails fast on configuration errors
        """
        # Transition to STARTING state
        self._lifecycle_state = LifecycleState.STARTING

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
        self.trading_logger = TradingLogger(logging_config.__dict__)
        self.logger = logging.getLogger(__name__)

        # Step 4: Log startup banner with environment info
        self.logger.info("=" * 50)
        self.logger.info("ICT Trading Bot Starting...")
        self.logger.info(f"Environment: {'TESTNET' if api_config.is_testnet else 'MAINNET'}")
        self.logger.info(f"Symbol: {trading_config.symbol}")
        self.logger.info(f"Intervals: {', '.join(trading_config.intervals)}")
        self.logger.info(f"Strategy: {trading_config.strategy}")
        self.logger.info(f"Leverage: {trading_config.leverage}x")
        self.logger.info(f"Margin Type: {trading_config.margin_type}")
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
            on_candle_callback=self._on_candle_received,  # Bridge to EventBus
        )

        # Step 5.5: Store backfill limit for TradingEngine initialization
        # Historical data fetching is now delegated to TradingEngine during strategy init
        self._backfill_limit = trading_config.backfill_limit
        if trading_config.backfill_limit > 0:
            self.logger.info(
                f"Backfill configured: {trading_config.backfill_limit} candles per interval"
            )
        else:
            self.logger.info("Backfilling disabled (backfill_limit=0)")

        # Step 6: Initialize OrderExecutionManager
        self.logger.info("Initializing OrderExecutionManager...")
        self.order_manager = OrderExecutionManager(
            api_key=api_config.api_key,
            api_secret=api_config.api_secret,
            is_testnet=api_config.is_testnet,
        )

        # Step 7: Initialize RiskManager
        self.logger.info("Initializing RiskManager...")
        self.risk_manager = RiskManager(
            config={
                "max_risk_per_trade": trading_config.max_risk_per_trade,
                "default_leverage": trading_config.leverage,
                "max_leverage": 20,  # Hard limit
                "max_position_size_percent": 0.1,  # 10% of account
            },
            audit_logger=self.order_manager.audit_logger,  # Share audit logger instance
        )

        # Step 8: Create strategy instance via StrategyFactory
        self.logger.info(f"Creating strategy: {trading_config.strategy}...")

        # Build strategy configuration
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

        self.strategy = StrategyFactory.create(
            name=trading_config.strategy, symbol=trading_config.symbol, config=strategy_config
        )

        # Step 9: Initialize EventBus and TradingEngine
        self.logger.info("Initializing EventBus...")
        self.event_bus = EventBus()

        self.logger.info("Initializing TradingEngine...")
        self.trading_engine = TradingEngine(
            audit_logger=self.order_manager.audit_logger  # Share audit logger instance
        )
        self.trading_engine.set_components(
            event_bus=self.event_bus,
            data_collector=self.data_collector,
            strategy=self.strategy,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            config_manager=self.config_manager,
            trading_bot=self,
        )

        # Step 9.5: Initialize strategy with historical data (if backfill enabled)
        if self._backfill_limit > 0:
            self.logger.info("Initializing strategy with historical data...")
            self.trading_engine.initialize_strategy_with_backfill(limit=self._backfill_limit)
            self.logger.info("✅ Strategy initialized with historical data")
        else:
            self.logger.info("No historical data to initialize (backfill disabled)")

        # Step 10: Configure leverage and margin type

        self.logger.info("Configuring leverage...")
        success = self.order_manager.set_leverage(trading_config.symbol, trading_config.leverage)
        if not success:
            self.logger.warning(
                f"Failed to set leverage to {trading_config.leverage}x. "
                "Using current account leverage."
            )

        # Configure margin type (ISOLATED by default for risk management)
        self.logger.info(f"Configuring margin type to {trading_config.margin_type}...")
        success = self.order_manager.set_margin_type(
            trading_config.symbol, trading_config.margin_type
        )
        if not success:
            self.logger.warning(
                f"Failed to set margin type to {trading_config.margin_type} for "
                f"{trading_config.symbol}. Using current margin type."
            )

        # Step 11: Initialize LiquidationManager with security-first defaults
        self.logger.info("Initializing LiquidationManager...")
        liquidation_config = LiquidationConfig(
            emergency_liquidation=True,  # Enable emergency liquidation by default
            close_positions=True,        # Close all positions on shutdown
            cancel_orders=True,          # Cancel all orders on shutdown
            timeout_seconds=5.0,         # 5 second timeout for liquidation
            max_retries=3,               # 3 retry attempts
            retry_delay_seconds=0.5,     # 0.5 second base delay for exponential backoff
        )

        self.liquidation_manager = LiquidationManager(
            order_manager=self.order_manager,
            audit_logger=self.order_manager.audit_logger,  # Share audit logger
            config=liquidation_config,
        )

        self.logger.info("✅ All components initialized successfully")
        self.logger.debug(f"Lifecycle state: {self._lifecycle_state.name}")

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Set event loop reference from TradingEngine.

        Called by TradingEngine.run() to provide the main thread's event loop
        reference for thread-safe event publishing from WebSocket callbacks.

        Args:
            loop: Event loop from asyncio.get_running_loop()
        """
        self._event_loop = loop
        self._lifecycle_state = LifecycleState.RUNNING

        self.logger.info(f"✅ Event loop registered, lifecycle state: {self._lifecycle_state.name}")

    def _on_candle_received(self, candle: Candle) -> None:
        """
        Callback from BinanceDataCollector on every candle update.

        Bridges WebSocket thread to EventBus using stored event loop reference.

        Args:
            candle: Candle data from WebSocket stream

        Thread Safety:
            Called from WebSocket thread. Uses stored event loop reference
            with asyncio.run_coroutine_threadsafe() to schedule coroutine
            in main thread's event loop.

        State Handling:
            - RUNNING: Accept and publish event
            - STARTING/STOPPING: Reject with debug log (expected)
            - INITIALIZING/STOPPED: Reject with warning (unexpected)
        """

        # Step 1: Check lifecycle state
        if self._lifecycle_state != LifecycleState.RUNNING:
            self._event_drop_count += 1

            # Log level depends on whether rejection is expected
            if self._lifecycle_state in (LifecycleState.STARTING, LifecycleState.STOPPING):
                self.logger.debug(
                    f"Event rejected (state={self._lifecycle_state.name}): "
                    f"{candle.symbol} {candle.interval} @ {candle.close}. "
                    f"Drops: {self._event_drop_count}"
                )
            else:
                self.logger.warning(
                    f"Event rejected in unexpected state ({self._lifecycle_state.name}): "
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
        Start trading system - delegate to TradingEngine.

        This method delegates the runtime loop to TradingEngine, which:
        1. Sets _running flag to True
        2. Starts EventBus and DataCollector concurrently
        3. Handles CancelledError for graceful shutdown
        4. Ensures shutdown() is called in finally block
        """
        self.logger.info("Starting trading system...")
        try:
            await self.trading_engine.run()
        finally:
            # Ensure TradingBot cleanup executes (QueueListener, lifecycle state, etc.)
            await self.shutdown()

    async def shutdown(self) -> None:
        """
        Graceful shutdown with emergency liquidation.

        Shutdown Sequence:
        1. Execute emergency liquidation (if enabled)
        2. Delegate to TradingEngine.shutdown()
        3. Flush audit logs
        4. Stop QueueListener

        Fail-Safe Guarantee:
        - Liquidation errors are logged but do NOT block shutdown
        - Shutdown ALWAYS continues regardless of liquidation outcome
        - Partial liquidation success is acceptable (logged for manual cleanup)
        """
        # Idempotency check - safe to call multiple times
        if self._lifecycle_state in (LifecycleState.STOPPING, LifecycleState.STOPPED):
            return

        # Transition to STOPPING state
        self._lifecycle_state = LifecycleState.STOPPING
        self.logger.info(f"Initiating shutdown with liquidation (state={self._lifecycle_state.name})...")

        # Step 1: Execute emergency liquidation (fail-safe: never blocks shutdown)
        if self.liquidation_manager:
            try:
                self.logger.info("Executing emergency liquidation...")
                liquidation_result = await self.liquidation_manager.execute_liquidation(
                    symbols=[self.config_manager.trading_config.symbol]
                )

                # Log liquidation outcome
                if liquidation_result.is_success():
                    self.logger.info(
                        f"✅ Liquidation completed successfully: "
                        f"{liquidation_result.positions_closed} positions closed, "
                        f"{liquidation_result.orders_cancelled} orders cancelled "
                        f"in {liquidation_result.total_duration_seconds:.2f}s"
                    )
                elif liquidation_result.is_partial():
                    self.logger.warning(
                        f"⚠️  Partial liquidation: "
                        f"{liquidation_result.positions_closed}/{liquidation_result.positions_closed + liquidation_result.positions_failed} positions closed, "
                        f"{liquidation_result.orders_cancelled}/{liquidation_result.orders_cancelled + liquidation_result.orders_failed} orders cancelled. "
                        f"Manual cleanup may be required. Error: {liquidation_result.error_message}"
                    )
                else:
                    self.logger.error(
                        f"❌ Liquidation failed: {liquidation_result.error_message}. "
                        f"Manual position closure required on exchange."
                    )

            except Exception as e:
                # CRITICAL: Never let liquidation errors block shutdown
                self.logger.error(
                    f"Emergency liquidation error (continuing shutdown anyway): {e}",
                    exc_info=True,
                )
        else:
            self.logger.warning("LiquidationManager not initialized, skipping emergency liquidation")

        # Step 2: Delegate to TradingEngine shutdown
        await self.trading_engine.shutdown()

        # Transition to STOPPED state
        self._lifecycle_state = LifecycleState.STOPPED

        # Log final statistics
        self.logger.info(
            f"Shutdown complete (state={self._lifecycle_state.name}). "
            f"Total events dropped: {self._event_drop_count}"
        )

        # Stop QueueListener to flush remaining logs
        if self.trading_logger:
            self.logger.info("Stopping QueueListener and flushing logs...")
            self.trading_logger.stop()
            # Note: Cannot log after stop() because QueueListener is shut down


def main() -> None:
    """
    Application entry point with signal handling.

    This function:
    1. Logs session start with system information
    2. Creates TradingBot instance
    3. Initializes all components
    4. Sets up signal handlers for graceful shutdown
    5. Runs the trading system in asyncio event loop
    6. Handles errors and cleanup
    7. Logs session end with summary
    """
    import platform
    from datetime import datetime

    # Record session start time
    session_start = datetime.now()

    bot = TradingBot()

    # Setup signal handlers for graceful shutdown
    def signal_handler(_sig, _frame):
        asyncio.create_task(bot.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize all components (this sets up logging)
        bot.initialize()

        # Log session start with system information AFTER logger is initialized
        logger = logging.getLogger(__name__)
        logger.info("=" * 80)
        logger.info("🚀 TRADING BOT SESSION START")
        logger.info("=" * 80)
        logger.info(f"Session Start Time: {session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Python Version: {platform.python_version()}")
        logger.info(f"Platform: {platform.system()} {platform.release()}")
        logger.info(f"Working Directory: {os.getcwd()}")
        logger.info("=" * 80)

        # Run trading system
        asyncio.run(bot.run())

    except KeyboardInterrupt:
        logger = logging.getLogger(__name__)
        logger.info("Received keyboard interrupt (Ctrl+C)")

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        # Log session end summary
        session_end = datetime.now()
        session_duration = session_end - session_start

        logger = logging.getLogger(__name__)
        logger.info("=" * 80)
        logger.info("🛑 TRADING BOT SESSION END")
        logger.info("=" * 80)
        logger.info(f"Session End Time: {session_end.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Session Duration: {session_duration}")
        logger.info("=" * 80)


if __name__ == "__main__":
    main()
