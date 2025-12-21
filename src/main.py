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

from src.utils.config import ConfigManager
from src.utils.logger import TradingLogger
from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
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

    def _setup_event_handlers(self) -> None:
        """
        Wire up event subscriptions between components.

        This method subscribes to:
        - EventType.CANDLE_CLOSED -> _on_candle_closed
        - EventType.SIGNAL_GENERATED -> _on_signal_generated
        - EventType.ORDER_FILLED -> _on_order_filled
        """
        # Subscribe to candle closed events (trigger strategy analysis)
        self.event_bus.subscribe(EventType.CANDLE_CLOSED, self._on_candle_closed)

        # Subscribe to signal generated events (trigger risk validation and order execution)
        self.event_bus.subscribe(EventType.SIGNAL_GENERATED, self._on_signal_generated)

        # Subscribe to order filled events (trigger position tracking)
        self.event_bus.subscribe(EventType.ORDER_FILLED, self._on_order_filled)

        self.logger.info("✅ Event handlers registered successfully")

    def _on_candle_received(self, candle: Candle) -> None:
        """
        Callback from BinanceDataCollector on every candle update.

        This method bridges the WebSocket data stream to the EventBus by:
        1. Determining event type based on candle.is_closed
        2. Creating an Event wrapper
        3. Publishing the Event to the EventBus 'data' queue (non-blocking)

        Args:
            candle: Candle data from WebSocket stream
        """
        # Determine event type based on candle state
        event_type = EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE

        # Create Event wrapper
        event = Event(event_type, candle)

        # Publish to EventBus asynchronously (non-blocking)
        # Using create_task to avoid blocking the WebSocket thread
        asyncio.create_task(
            self.event_bus.publish(event, queue_name='data')
        )

        # Debug logging for closed candles only (avoid spam from updates)
        if candle.is_closed:
            self.logger.debug(
                f"Candle closed: {candle.symbol} {candle.interval} "
                f"@ {candle.close} (published to EventBus)"
            )

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
            # Debug log for no signal (avoid spam)
            self.logger.debug(
                f"No signal generated for {candle.symbol} {candle.interval}"
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
            # Note: This simulates the fill event (in production, would come from WebSocket)
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
        Main runtime loop - start all components.

        Implemented in Subtask 10.5.

        This method:
        1. Sets _running flag to True
        2. Starts EventBus and DataCollector concurrently
        3. Handles CancelledError for graceful shutdown
        4. Ensures shutdown() is called in finally block
        """
        pass

    async def shutdown(self) -> None:
        """
        Graceful shutdown - cleanup all components.

        Implemented in Subtask 10.4.

        This method:
        1. Sets _running flag to False
        2. Stops DataCollector (closes WebSocket)
        3. Stops EventBus (drains queues and stops workers)
        4. Logs shutdown completion
        """
        pass


def main() -> None:
    """
    Main entry point - setup event loop and run bot.

    Implemented in Subtask 10.5.

    This function:
    1. Creates TradingBot instance
    2. Sets up asyncio event loop
    3. Registers SIGINT/SIGTERM signal handlers
    4. Calls bot.initialize()
    5. Runs bot.run() in event loop
    6. Handles errors and cleanup
    """
    pass


if __name__ == '__main__':
    main()
