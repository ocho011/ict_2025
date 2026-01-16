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

from src.core.audit_logger import AuditLogger
from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.core.trading_engine import TradingEngine
from src.execution.liquidation_manager import LiquidationManager
from src.utils.config import ConfigManager, LiquidationConfig
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
        _stop_event: Event to trigger graceful shutdown (Method 1)
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
        self.trading_engine: Optional[TradingEngine] = None
        self.liquidation_manager: Optional[LiquidationManager] = None
        self.logger: Optional[logging.Logger] = None
        self.trading_logger: Optional[TradingLogger] = None  # For cleanup

        # State management
        self._running: bool = False
        self._stop_event: Optional[asyncio.Event] = None  # Signal for synchronized shutdown wait

        # Lifecycle state
        self._lifecycle_state: LifecycleState = LifecycleState.INITIALIZING

    async def initialize(self) -> None:
        """
        Initialize trading bot components with simplified responsibility (Issue #5 Refactoring).

        TradingBot now handles only lifecycle and common utilities:
        1. ConfigManager - Load all configurations
        2. Validate - Ensure config is valid before proceeding
        3. TradingLogger - Setup logging infrastructure
        4. AuditLogger - Initialize audit logging system
        5. EventBus - Event coordination system
        6. TradingEngine - Delegate component creation to engine
        7. Backfill - Initialize strategy with historical data
        8. LiquidationManager - Emergency shutdown handler

        TradingEngine now owns:
        - OrderExecutionManager creation
        - RiskManager creation
        - Strategy creation
        - DataCollector creation
        - Leverage configuration
        - Component wiring

        Raises:
            ValueError: If configuration validation fails
            Exception: For any component initialization failure

        Note:
            - Simplified from 150+ lines to ~50 lines
            - Clear separation: Bot = lifecycle, Engine = trading logic
            - AuditLogger created at Bot level and injected to Engine
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
        self.logger.info("ICT Trading Bot Starting (Issue #5 Refactored)...")
        self.logger.info(f"Environment: {'TESTNET' if api_config.is_testnet else 'MAINNET'}")
        self.logger.info(f"Symbols: {', '.join(trading_config.symbols)}")
        self.logger.info(f"Intervals: {', '.join(trading_config.intervals)}")
        self.logger.info(f"Strategy: {trading_config.strategy}")
        self.logger.info(f"Leverage: {trading_config.leverage}x")
        self.logger.info(f"Margin Type: {trading_config.margin_type}")
        self.logger.info(f"Max Risk per Trade: {trading_config.max_risk_per_trade * 100:.1f}%")
        self.logger.info("=" * 50)

        # Step 5: Initialize AuditLogger (shared by all components)
        self.logger.info("Initializing AuditLogger...")
        self.audit_logger = AuditLogger(log_dir="logs/audit")

        # Step 6: Initialize EventBus
        self.logger.info("Initializing EventBus...")
        self.event_bus = EventBus()

        # Step 7: Initialize TradingEngine and delegate component creation
        self.logger.info("Initializing TradingEngine...")
        self.trading_engine = TradingEngine(audit_logger=self.audit_logger)

        self.logger.info("Delegating component initialization to TradingEngine...")
        self.trading_engine.initialize_components(
            config_manager=self.config_manager,
            event_bus=self.event_bus,
            api_key=api_config.api_key,
            api_secret=api_config.api_secret,
            is_testnet=api_config.is_testnet,
        )

        # Get references to components created by TradingEngine
        self.order_manager = self.trading_engine.order_manager
        self.data_collector = self.trading_engine.data_collector
        self.risk_manager = self.trading_engine.risk_manager

        # Step 8: Initialize strategy with historical data (if backfill enabled)
        self._backfill_limit = trading_config.backfill_limit
        if self._backfill_limit > 0:
            self.logger.info(
                f"Backfill configured: {trading_config.backfill_limit} candles per interval"
            )
            self.logger.info("Initializing strategy with historical data...")
            await self.trading_engine.initialize_strategy_with_backfill(limit=self._backfill_limit)
            self.logger.info("✅ Strategy initialized with historical data")
        else:
            self.logger.info("Backfilling disabled (backfill_limit=0)")

        # Step 9: Initialize LiquidationManager
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
            audit_logger=self.audit_logger,
            config=liquidation_config,
        )

        self.logger.info("✅ All components initialized successfully")
        self.logger.debug(f"Lifecycle state: {self._lifecycle_state.name}")

    async def run(self) -> None:
        """
        Start trading system - delegate to TradingEngine.

        This method delegates the runtime loop to TradingEngine, which:
        1. Sets _running flag to True
        2. Starts EventBus and DataCollector concurrently
        3. Handles CancelledError for graceful shutdown
        4. Ensures shutdown() is called in finally block
        """
        # Set lifecycle state to RUNNING (previously done in set_event_loop)
        self._lifecycle_state = LifecycleState.RUNNING
        self._stop_event = asyncio.Event()
        self.logger.info(f"✅ TradingBot lifecycle state: {self._lifecycle_state.name}")
        
        self.logger.info("Starting trading system...")

        # Create tasks with explicit references for proper cleanup (Issue #23)
        engine_task = asyncio.create_task(self.trading_engine.run())
        stop_signal_task = asyncio.create_task(self._stop_event.wait())

        try:
            # Wait for either engine to finish or stop event to trigger
            done, pending = await asyncio.wait(
                [engine_task, stop_signal_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # If the engine task is still running (stop event triggered first),
            # it will be stopped gracefully by the subsequent shutdown() call
            # which sets engine._running = False.

        finally:
            # Cancel pending stop_signal_task to prevent zombie tasks (Issue #23)
            if not stop_signal_task.done():
                stop_signal_task.cancel()
                try:
                    await stop_signal_task
                except asyncio.CancelledError:
                    pass  # Expected when cancelling

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
                    symbols=self.config_manager.trading_config.symbols
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

        # Log shutdown completion
        self.logger.info(f"Shutdown complete (state={self._lifecycle_state.name})")


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

    # Setup signal handlers for graceful shutdown using Event
    def signal_handler(_sig, _frame):
        if bot._stop_event:
            # Graceful shutdown during run loop (Issue #22)
            bot._stop_event.set()
        else:
            # Immediate exit during initialization (Issue #22)
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize all components (this sets up logging)
        asyncio.run(bot.initialize())

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

        # FINAL STEP: Stop QueueListener to flush remaining logs
        if bot.trading_logger:
            # Use root logger directly for final message as QueueListener might be stopping
            bot.logger.info("Shutting down logging system...")
            bot.trading_logger.stop()


if __name__ == "__main__":
    main()
