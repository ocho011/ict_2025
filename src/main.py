"""
Main entry point for the ICT 2025 Trading System.

This module implements the TradingBot class that orchestrates all system components
including data collection, strategy execution, risk management, and order execution.
"""

import asyncio
import signal
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add project root to Python path for imports
# This allows running main.py from any directory (PyCharm, terminal, etc.)
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.config import ConfigManager
from src.utils.logger import TradingLogger
from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.core.trading_engine import TradingEngine
from src.strategies import StrategyFactory
from src.strategies.base import BaseStrategy
from src.execution.order_manager import OrderExecutionManager
from src.risk.manager import RiskManager
from src.models.event import Event, EventType
from src.models.candle import Candle
from src.models.signal import Signal
from src.models.order import Order


class TradingBot:
    """
    Main trading bot orchestrator that manages all system components.

    Lifecycle:
        1. __init__() - Minimal constructor setup
        2. initialize() - 10-step component initialization
        3. run() - Async runtime loop (implemented in Subtask 10.5)
        4. shutdown() - Graceful cleanup (implemented in Subtask 10.4)

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
        self.logger: Optional[logging.Logger] = None

        # State management
        self._running: bool = False

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
            10. Event Handlers + Leverage Setup

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

        # Step 9: Initialize EventBus and TradingEngine
        self.logger.info("Initializing EventBus...")
        self.event_bus = EventBus()

        self.logger.info("Initializing TradingEngine...")
        self.trading_engine = TradingEngine()
        self.trading_engine.set_components(
            event_bus=self.event_bus,
            data_collector=self.data_collector,
            strategy=self.strategy,
            order_manager=self.order_manager,
            risk_manager=self.risk_manager,
            config_manager=self.config_manager
        )

        # Step 10: Configure leverage

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

    def _on_candle_received(self, candle: Candle) -> None:
        """
        Callback from BinanceDataCollector on every candle update.

        This method bridges the WebSocket data stream to the EventBus by:
        1. Determining event type based on candle.is_closed
        2. Creating an Event wrapper
        3. Publishing the Event to the EventBus 'data' queue (thread-safe)

        Args:
            candle: Candle data from WebSocket stream

        Note:
            This is called from WebSocket thread, so we need thread-safe async scheduling.
            Using asyncio.run_coroutine_threadsafe() to schedule coroutine in event loop.
        """
        # Determine event type based on candle state
        event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE

        # Create Event wrapper
        event = Event(event_type, candle)

        # Publish to EventBus asynchronously (thread-safe)
        # WebSocket callbacks run in different thread, so we need run_coroutine_threadsafe
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(event, queue_name='data'),
                loop
            )
        except RuntimeError:
            # No running loop yet - system is shutting down or not started
            pass

        # Log candle events (closed candles at INFO level for visibility)
        if candle.is_closed:
            self.logger.info(
                f"📊 Candle closed: {candle.symbol} {candle.interval} "
                f"@ {candle.close} → EventBus"
            )
        else:
            # Log first update per minute to show connection is alive
            # This provides heartbeat without log spam
            if candle.open_time.second < 5:  # Log once per minute in first 5 seconds
                self.logger.info(
                    f"🔄 Live data: {candle.symbol} {candle.interval} "
                    f"@ {candle.close}"
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
        await self.trading_engine.run()

    async def shutdown(self) -> None:
        """
        Graceful shutdown - delegate to TradingEngine.

        This method delegates shutdown to TradingEngine, which:
        1. Checks idempotency (_running flag)
        2. Sets _running flag to False
        3. Stops DataCollector (closes WebSocket)
        4. Stops EventBus (drains queues and stops workers)
        5. Logs shutdown completion
        """
        self.logger.info("Initiating shutdown...")
        await self.trading_engine.shutdown()
        self.logger.info("Shutdown complete")


def main() -> None:
    """
    Application entry point with signal handling.

    This function:
    1. Creates TradingBot instance
    2. Initializes all components
    3. Sets up signal handlers for graceful shutdown
    4. Runs the trading system in asyncio event loop
    5. Handles errors and cleanup
    """
    bot = TradingBot()

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        asyncio.create_task(bot.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize all components
        bot.initialize()

        # Run trading system
        asyncio.run(bot.run())

    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
