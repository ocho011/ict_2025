"""BacktestEngine: Historical event replay for strategy backtesting.

Connects HistoricalDataProvider + MockExchange to replay candles through
the strategy pipeline with synchronous per-candle processing.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.data.historical import HistoricalDataProvider
from src.execution.mock_exchange import MockExchange
from src.models.candle import Candle
from src.models.order import OrderType
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy


@dataclass
class BacktestConfig:
    """Configuration for backtesting."""

    initial_balance: float = 10000.0
    fee_rate: float = 0.0004  # 0.04% taker fee
    slippage_bps: float = 1.0  # 1 basis point slippage
    leverage: int = 10
    risk_per_trade: float = 0.02  # 2% risk per trade
    backfill_limit: int = 100  # Historical candles for strategy init


@dataclass
class TradeRecord:
    """Record of a single completed trade."""

    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    exit_price: float
    quantity: float
    realized_pnl: float
    fee: float
    entry_candle_index: int
    exit_candle_index: int
    exit_reason: str  # "take_profit", "stop_loss", "strategy_exit"


@dataclass
class BacktestResult:
    """Results from a backtest run."""

    # Summary
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    max_drawdown: float = 0.0
    final_balance: float = 0.0
    initial_balance: float = 0.0

    # Detailed records
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    # Performance
    candles_processed: int = 0
    elapsed_seconds: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def return_pct(self) -> float:
        if self.initial_balance == 0:
            return 0.0
        return (self.final_balance - self.initial_balance) / self.initial_balance * 100

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.realized_pnl for t in self.trades if t.realized_pnl > 0)
        gross_loss = abs(
            sum(t.realized_pnl for t in self.trades if t.realized_pnl < 0)
        )
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss


class BacktestEngine:
    """Orchestrates backtesting by replaying historical candles through strategies.

    Connects:
    - HistoricalDataProvider: candle data source
    - MockExchange: simulated order execution
    - Strategy instances: signal generation

    Uses synchronous per-candle processing for deterministic results:
    1. Feed candle to strategy buffer
    2. Run entry/exit analysis on closed candles
    3. Execute signals via MockExchange
    4. Check TP/SL triggers at candle high/low prices
    5. Record trade results
    """

    def __init__(
        self,
        strategies: Dict[str, BaseStrategy],
        data_provider: HistoricalDataProvider,
        config: Optional[BacktestConfig] = None,
    ) -> None:
        self._strategies = strategies
        self._data_provider = data_provider
        self._config = config or BacktestConfig()
        self._exchange: Optional[MockExchange] = None
        self._trades: List[TradeRecord] = []
        self._equity_curve: List[float] = []
        self._candle_index = 0
        self._entry_indices: Dict[str, int] = {}  # symbol -> candle index at entry
        self._peak_balance = self._config.initial_balance
        self._max_drawdown = 0.0
        self.logger = logging.getLogger(__name__)

    @property
    def exchange(self) -> Optional[MockExchange]:
        """Access the MockExchange instance (available after run())."""
        return self._exchange

    async def run(self) -> BacktestResult:
        """Execute the backtest and return results."""
        start_time = time.monotonic()

        # 1. Create MockExchange
        self._exchange = MockExchange(
            initial_balance=self._config.initial_balance,
            fee_rate=self._config.fee_rate,
            slippage_bps=self._config.slippage_bps,
        )

        # Set leverage for all symbols
        for symbol in self._strategies:
            self._exchange.set_leverage(symbol, self._config.leverage)

        # 2. Initialize strategies with historical backfill
        self._initialize_strategies()

        # 3. Replay remaining candles
        candles_processed = await self._replay_candles()

        # 4. Build result
        elapsed = time.monotonic() - start_time

        result = BacktestResult(
            total_trades=len(self._trades),
            winning_trades=sum(1 for t in self._trades if t.realized_pnl > 0),
            losing_trades=sum(1 for t in self._trades if t.realized_pnl <= 0),
            total_pnl=self._exchange.realized_pnl,
            total_fees=self._exchange.total_fees,
            max_drawdown=self._max_drawdown,
            final_balance=self._exchange.get_account_balance(),
            initial_balance=self._config.initial_balance,
            trades=self._trades,
            equity_curve=self._equity_curve,
            candles_processed=candles_processed,
            elapsed_seconds=elapsed,
        )

        self.logger.info(
            "Backtest complete: %d trades, PnL=%.2f, Win rate=%.1f%%, "
            "Max DD=%.2f%%, Duration=%.2fs, Candles=%d",
            result.total_trades,
            result.total_pnl,
            result.win_rate * 100,
            result.max_drawdown * 100,
            result.elapsed_seconds,
            result.candles_processed,
        )

        return result

    def _initialize_strategies(self) -> None:
        """Feed initial historical window to strategies for buffer warmup."""
        for symbol, strategy in self._strategies.items():
            for interval in strategy.intervals:
                candles = self._data_provider.get_historical_candles(
                    symbol=symbol,
                    interval=interval,
                    limit=self._config.backfill_limit,
                )
                if candles:
                    strategy.initialize_with_historical_data(
                        candles, interval=interval
                    )
                    self.logger.info(
                        "Initialized %s/%s with %d candles",
                        symbol,
                        interval,
                        len(candles),
                    )

    async def _replay_candles(self) -> int:
        """Replay remaining candles through the strategy pipeline.

        Returns:
            Number of candles processed.
        """
        count = 0

        # Collect all remaining candles across symbols/intervals
        # and replay in chronological order
        replay_queue: List[Candle] = []

        for symbol, intervals in self._data_provider._data.items():
            for interval, candles in intervals.items():
                skip = self._data_provider._init_counts.get(symbol, {}).get(
                    interval, 0
                )
                replay_queue.extend(candles[skip:])

        # Sort by close_time for chronological replay
        replay_queue.sort(key=lambda c: c.close_time)

        total = len(replay_queue)
        self.logger.info("Replaying %d candles...", total)

        for candle in replay_queue:
            await self._process_candle(candle)
            count += 1
            self._candle_index += 1

            # Track equity curve periodically (every 100 candles)
            if count % 100 == 0:
                balance = self._exchange.get_account_balance()
                self._equity_curve.append(balance)
                self._update_drawdown(balance)

            # Progress logging every 10000 candles
            if count % 10000 == 0:
                self.logger.info(
                    "Progress: %d/%d candles (%.1f%%)",
                    count,
                    total,
                    count / total * 100,
                )

        # Final equity point
        final_balance = self._exchange.get_account_balance()
        self._equity_curve.append(final_balance)
        self._update_drawdown(final_balance)

        return count

    async def _process_candle(self, candle: Candle) -> None:
        """Process a single candle through the strategy pipeline.

        Flow:
        1. Check TP/SL triggers at candle high and low
        2. Update strategy buffer
        3. If closed candle: run entry/exit analysis
        4. Execute any generated signals
        """
        symbol = candle.symbol
        strategy = self._strategies.get(symbol)
        if strategy is None:
            return

        # Check interval matches strategy
        if candle.interval not in strategy.intervals:
            return

        # Step 1: Check pending TP/SL orders with candle high/low
        self._check_tp_sl(symbol, candle)

        # Step 2: Update strategy buffer with this candle
        strategy.update_buffer(candle)

        # Step 3: Only analyze on closed candles
        if not candle.is_closed:
            return

        # Step 4: Route to entry or exit analysis
        position = self._exchange.get_position(symbol)

        if position is not None:
            # Has position -> check exit
            await self._process_exit(candle, strategy, position)
        else:
            # No position -> check entry
            await self._process_entry(candle, strategy)

    def _check_tp_sl(self, symbol: str, candle: Candle) -> None:
        """Check if pending TP/SL orders trigger within this candle's range."""
        position = self._exchange.get_position(symbol)
        if position is None:
            return

        # Check at low price first (catches SL for longs)
        filled_at_low = self._exchange.check_pending_orders(symbol, candle.low)
        if filled_at_low:
            self._record_tp_sl_fill(symbol, filled_at_low, candle)
            return  # Position closed

        # Check at high price (catches TP for longs, SL for shorts)
        filled_at_high = self._exchange.check_pending_orders(symbol, candle.high)
        if filled_at_high:
            self._record_tp_sl_fill(symbol, filled_at_high, candle)

    def _record_tp_sl_fill(
        self, symbol: str, filled_orders: List, candle: Candle
    ) -> None:
        """Record trade from TP/SL fill."""
        for order in filled_orders:
            if order.order_type == OrderType.TAKE_PROFIT_MARKET:
                exit_reason = "take_profit"
            else:
                exit_reason = "stop_loss"

            entry_idx = self._entry_indices.pop(symbol, 0)

            # Determine side from close direction (reverse of closing order side)
            side = "LONG" if order.side.value == "SELL" else "SHORT"

            # Find entry price from filled orders history
            entry_price = order.price  # fallback
            for prev_order in self._exchange.filled_orders:
                if (
                    prev_order.symbol == symbol
                    and prev_order.order_type == OrderType.MARKET
                    and prev_order != order
                ):
                    entry_price = prev_order.price

            # Calculate PnL
            if side == "LONG":
                pnl = (order.price - entry_price) * order.quantity
            else:
                pnl = (entry_price - order.price) * order.quantity

            self._trades.append(
                TradeRecord(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    exit_price=order.price,
                    quantity=order.quantity,
                    realized_pnl=pnl,
                    fee=0.0,  # fees tracked globally in MockExchange
                    entry_candle_index=entry_idx,
                    exit_candle_index=self._candle_index,
                    exit_reason=exit_reason,
                )
            )

    async def _process_entry(
        self, candle: Candle, strategy: BaseStrategy
    ) -> None:
        """Run entry analysis and execute signal if generated."""
        # Check if strategy buffers are ready (use buffer_size as min_candles)
        if not strategy.is_buffer_ready(strategy.buffer_size):
            return

        try:
            signal = await strategy.analyze(candle)
        except Exception as e:
            self.logger.warning(
                "Strategy analyze failed for %s: %s", candle.symbol, e
            )
            return

        if signal is None:
            return

        # Execute entry via MockExchange
        self._execute_entry(signal)

    async def _process_exit(
        self, candle: Candle, strategy: BaseStrategy, position
    ) -> None:
        """Run exit analysis and execute if signal generated."""
        try:
            signal = await strategy.should_exit(position, candle)
        except Exception as e:
            self.logger.warning(
                "Strategy should_exit failed for %s: %s", candle.symbol, e
            )
            return

        if signal is None:
            return

        # Execute exit via MockExchange
        await self._execute_exit(signal, position, candle)

    def _execute_entry(self, signal: Signal) -> None:
        """Execute an entry signal via MockExchange."""
        balance = self._exchange.get_account_balance()
        risk_amount = balance * self._config.risk_per_trade
        risk_per_unit = signal.risk_amount

        if risk_per_unit <= 0:
            self.logger.warning(
                "Invalid risk amount for %s, skipping", signal.symbol
            )
            return

        # Position sizing: cap quantity so loss at SL = risk_amount
        quantity = risk_amount / risk_per_unit

        if quantity <= 0:
            return

        entry_order, tpsl_orders = self._exchange.execute_signal(signal, quantity)
        self._entry_indices[signal.symbol] = self._candle_index

        self.logger.debug(
            "Entry: %s %s @ %.2f qty=%.4f TP=%.2f SL=%.2f",
            signal.symbol,
            signal.signal_type.value,
            entry_order.price,
            quantity,
            signal.take_profit or 0,
            signal.stop_loss or 0,
        )

    async def _execute_exit(
        self, signal: Signal, position, candle: Candle
    ) -> None:
        """Execute an exit signal via MockExchange."""
        # Cancel pending orders
        self._exchange.cancel_all_orders(signal.symbol)

        # Close position
        close_side = (
            "SELL" if signal.signal_type == SignalType.CLOSE_LONG else "BUY"
        )

        try:
            result = await self._exchange.execute_market_close(
                symbol=signal.symbol,
                position_amt=position.quantity,
                side=close_side,
                reduce_only=True,
            )
        except Exception as e:
            self.logger.warning(
                "Exit execution failed for %s: %s", signal.symbol, e
            )
            return

        if result.get("success"):
            exit_price = result.get("avg_price", candle.close)
            entry_idx = self._entry_indices.pop(signal.symbol, 0)

            if position.side == "LONG":
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity

            self._trades.append(
                TradeRecord(
                    symbol=signal.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    quantity=position.quantity,
                    realized_pnl=pnl,
                    fee=0.0,
                    entry_candle_index=entry_idx,
                    exit_candle_index=self._candle_index,
                    exit_reason=signal.exit_reason or "strategy_exit",
                )
            )

    def _update_drawdown(self, balance: float) -> None:
        """Track maximum drawdown."""
        if balance > self._peak_balance:
            self._peak_balance = balance

        if self._peak_balance > 0:
            drawdown = (self._peak_balance - balance) / self._peak_balance
            if drawdown > self._max_drawdown:
                self._max_drawdown = drawdown
