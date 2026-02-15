"""EventDispatcher: Candle event routing and strategy execution.

Extracted from TradingEngine to separate event dispatch logic from
engine orchestration (Issue #110 Phase 3).

Responsibilities:
- Route candle events to appropriate strategies
- Handle entry/exit strategy analysis
- Publish trading signals with audit logging
- Manage signal cooldown to prevent duplicate entries
- Update exchange stop-loss orders dynamically
- Bridge WebSocket thread to EventBus (on_candle_received)
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional, Dict, Any, Callable

if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.models.position import Position
    from src.core.position_cache_manager import PositionCacheManager

from src.core.exceptions import EngineState
from src.models.candle import Candle
from src.models.event import Event, EventType, QueueType
from src.models.signal import Signal
from src.strategies.base import BaseStrategy


class EventDispatcher:
    """
    Handles candle event routing and strategy execution.

    Extracted from TradingEngine to separate concerns:
    - Event routing (candle -> strategy)
    - Entry/exit analysis
    - Signal publishing with audit trail
    - Dynamic stop-loss updates

    Dependencies:
    - PositionCacheManager: For position state queries
    - EventBus: For signal publishing
    - OrderManager: For stop-loss updates
    - AuditLogger: For compliance logging
    """

    def __init__(
        self,
        strategies: Dict[str, BaseStrategy],
        position_cache_manager: "PositionCacheManager",
        event_bus,
        audit_logger: "AuditLogger",
        order_gateway,
        engine_state_getter: Callable[[], EngineState],
        event_loop_getter: Callable[[], Optional[asyncio.AbstractEventLoop]],
        log_live_data: bool = True,
    ):
        self._strategies = strategies
        self._position_cache_manager = position_cache_manager
        self._event_bus = event_bus
        self._audit_logger = audit_logger
        self._order_gateway = order_gateway
        self._get_engine_state = engine_state_getter
        self._get_event_loop = event_loop_getter
        self._signal_cooldown: float = 300.0  # 5 minutes cooldown
        self._log_live_data = log_live_data
        self._event_drop_count = 0
        self._last_exchange_sl: Dict[str, float] = {}
        self.logger = logging.getLogger(__name__)

    async def on_candle_closed(self, event: Event) -> None:
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
        if candle.symbol not in self._strategies:
            self.logger.error(
                f"❌ Unknown symbol: {candle.symbol}. "
                f"Configured symbols: {list(self._strategies.keys())}"
            )
            return

        # Get strategy for this symbol
        strategy = self._strategies[candle.symbol]

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
        current_position = self._position_cache_manager.get(candle.symbol)

        # Issue #41: Handle uncertain position state.
        # If _position_cache.get returns None, it could be "No Position" or "API Failure".
        # We must skip analysis if the state is uncertain to prevent incorrect entries.
        if current_position is None:
            # Check if cache was actually updated successfully (confirmed None state)
            if candle.symbol not in self._position_cache_manager.cache:
                self.logger.warning(
                    f"Position state unknown for {candle.symbol}, skipping analysis"
                )
                return

            _, cache_time = self._position_cache_manager.cache[candle.symbol]
            if time.time() - cache_time >= self._position_cache_manager._ttl:
                # Cache is stale, meaning _position_cache.get failed to refresh it
                self.logger.warning(
                    f"Position state uncertain for {candle.symbol} (cache expired and refresh failed), "
                    f"skipping analysis to prevent incorrect entry"
                )
                return

        if current_position is not None:
            # Position exists - check exit conditions first (Issue #25)
            await self.process_exit_strategy(candle, strategy, current_position)
            return  # Always skip entry analysis if position exists

        # 3. No position - check entry conditions
        await self.process_entry_strategy(candle, strategy)

    async def process_exit_strategy(
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
            await self.publish_signal_with_audit(
                signal=exit_signal,
                candle=candle,
                operation="exit_analysis",
                audit_data={
                    "position_side": position.side,
                    "position_quantity": position.quantity,
                },
            )
            return True

        # Dynamic SL update: sync exchange SL with strategy trailing level (Issue #104)
        await self.maybe_update_exchange_sl(candle, strategy, position)

        self.logger.debug(
            f"No exit signal for {candle.symbol}, position still open - skipping entry analysis"
        )
        return False

    async def process_entry_strategy(
        self, candle: Candle, strategy: BaseStrategy
    ) -> None:
        """
        Check new entry conditions (Issue #42).
        """
        # Signal cooldown check to prevent multi-interval duplicate entries (Issue #101)
        symbol = candle.symbol
        now = time.time()
        last_signal = self._position_cache_manager._last_signal_time.get(symbol, 0.0)
        if now - last_signal < self._signal_cooldown:
            remaining = self._signal_cooldown - (now - last_signal)
            self.logger.debug(
                f"Signal cooldown active for {symbol}: {remaining:.1f}s remaining"
            )
            return

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
            # Record signal time for cooldown (Issue #101)
            self._position_cache_manager._last_signal_time[symbol] = now
            await self.publish_signal_with_audit(
                signal=signal, candle=candle, operation="candle_analysis"
            )
        else:
            # Info log for no signal (shows strategy is working)
            self.logger.info(
                f"✓ No signal: {candle.symbol} {candle.interval} (strategy conditions not met)"
            )

    async def maybe_update_exchange_sl(
        self, candle: Candle, strategy: BaseStrategy, position: "Position"
    ) -> None:
        """
        Sync exchange SL with strategy's trailing stop level (Issue #104).

        If the strategy implements TrailingLevelProvider and has a persisted
        trailing level that differs from the original SL by more than 0.1%,
        update the exchange SL order.
        """
        try:
            from src.strategies.trailing_level_protocol import TrailingLevelProvider

            # Only applies to strategies implementing TrailingLevelProvider
            if not isinstance(strategy, TrailingLevelProvider):
                return

            trailing_levels = strategy.trailing_levels
            if not trailing_levels:
                return

            trail_key = f"{candle.symbol}_{position.side}"
            current_trailing = trailing_levels.get(trail_key)
            if current_trailing is None:
                return

            # Minimum movement threshold: only update if SL moved by >0.1%
            last_sl = self._last_exchange_sl.get(candle.symbol)
            if last_sl is not None:
                movement = abs(current_trailing - last_sl) / last_sl
                if movement < 0.001:  # 0.1% threshold
                    return

            # Determine SL order side (opposite of position)
            from src.models.order import OrderSide

            sl_side = OrderSide.SELL if position.side == "LONG" else OrderSide.BUY

            # Update exchange SL
            result = self._order_gateway.update_stop_loss(
                symbol=candle.symbol,
                new_stop_price=current_trailing,
                side=sl_side,
            )
            if result:
                self._last_exchange_sl[candle.symbol] = current_trailing
                self.logger.info(
                    f"Exchange SL updated for {candle.symbol}: {current_trailing:.4f}"
                )
        except Exception as e:
            self.logger.warning(
                f"Failed to update exchange SL for {candle.symbol}: {e}"
            )

    async def publish_signal_with_audit(
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

            self._audit_logger.log_event(
                event_type=AuditEventType.SIGNAL_PROCESSING,
                operation=operation,
                symbol=candle.symbol,
                additional_data=full_audit_data,
            )
        except Exception as e:
            self.logger.warning(f"Audit logging failed: {e}")

        # 3. Create event and publish to 'signal' queue
        signal_event = Event(EventType.SIGNAL_GENERATED, signal)
        await self._event_bus.publish(signal_event, queue_type=QueueType.SIGNAL)

    def on_candle_received(self, candle: Candle) -> None:
        """
        Callback from BinanceDataCollector on every candle update.

        Bridges WebSocket thread to EventBus using stored event loop reference.

        Args:
            candle: Candle data from WebSocket stream

        Thread Safety:
            Called from WebSocket thread. Uses stored event loop reference
            with asyncio.run_coroutine_threadsafe() to schedule coroutine
            in main thread's event loop.
        """

        # Step 1: Check engine state
        engine_state = self._get_engine_state()
        if engine_state != EngineState.RUNNING:
            self._event_drop_count += 1

            # Log level depends on whether rejection is expected
            if engine_state in (EngineState.INITIALIZED, EngineState.STOPPING):
                self.logger.debug(
                    f"Event rejected (state={engine_state.name}): "
                    f"{candle.symbol} {candle.interval} @ {candle.close}. "
                    f"Drops: {self._event_drop_count}"
                )
            else:
                self.logger.warning(
                    f"Event rejected in unexpected state ({engine_state.name}): "
                    f"{candle.symbol} {candle.interval} @ {candle.close}. "
                    f"Drops: {self._event_drop_count}"
                )
            return

        # Step 2: Verify event loop is available
        event_loop = self._get_event_loop()
        if event_loop is None:
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
        # Route to separate queues based on event type (Issue #118)
        candle_queue = (
            QueueType.CANDLE_CLOSED if candle.is_closed else QueueType.CANDLE_UPDATE
        )
        try:
            asyncio.run_coroutine_threadsafe(
                self._event_bus.publish(event, queue_type=candle_queue),
                event_loop,
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
