# Subtask 10.3 Implementation Guide: Signal Processing Pipeline

## Overview

Implement three async event handlers that process the complete trading flow from candle analysis through order execution.

**Files to Modify**:
- `src/main.py` - Replace stub methods for `_on_candle_closed()`, `_on_signal_generated()`, `_on_order_filled()`

**Dependencies**:
- Subtask 10.2 (Event Handler Setup) - ✅ Complete
- Component interfaces: BaseStrategy, RiskManager, OrderExecutionManager

---

## Handler 1: _on_candle_closed()

### Purpose
Process closed candles and generate trading signals.

### Signature
```python
async def _on_candle_closed(self, event: Event) -> None:
    """
    Handle closed candle event - run strategy analysis.

    This handler is called when a candle fully closes (is_closed=True).
    It runs the trading strategy analysis and publishes signals if conditions are met.

    Args:
        event: Event containing closed Candle data
    """
```

### Implementation Flow

```python
async def _on_candle_closed(self, event: Event) -> None:
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
```

### Key Points

1. **Async Method**: Must be async since `strategy.analyze()` is async
2. **Error Handling**: Catch strategy exceptions to prevent system crash
3. **Queue Routing**: Publish signals to 'signal' queue (not 'data')
4. **Logging Levels**:
   - Info: Candle received, signal generated
   - Debug: No signal (reduces noise)
   - Error: Strategy failures

---

## Handler 2: _on_signal_generated()

### Purpose
Validate signals and execute orders (core trading logic).

### Signature
```python
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
```

### Implementation Flow

```python
async def _on_signal_generated(self, event: Event) -> None:
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
```

### Key Points

1. **Complete Error Handling**: Wrap entire flow in try-except
2. **Multi-Step Validation**:
   - Risk validation (existing position, TP/SL logic)
   - Account balance check
   - Position size calculation
3. **Logging Strategy**:
   - Info: Signal processing, successful execution
   - Warning: Risk rejections
   - Error: Execution failures with stack trace
4. **Queue Routing**: Publish order events to 'order' queue
5. **Non-Blocking Errors**: Log and continue (don't crash system)

---

## Handler 3: _on_order_filled()

### Purpose
Track order fills and log confirmations.

### Signature
```python
async def _on_order_filled(self, event: Event) -> None:
    """
    Handle order fill notification.

    Logs order fills for tracking and monitoring.
    In future iterations, will update position tracking.

    Args:
        event: Event containing Order data
    """
```

### Implementation Flow

```python
async def _on_order_filled(self, event: Event) -> None:
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
```

### Key Points

1. **Simple Logging**: Primary purpose is order fill confirmation
2. **Future Enhancement**: Position tracking logic (Task 10 followup)
3. **Async Signature**: Matches event handler pattern (even if not using async operations)

---

## Component Interface Reference

### BaseStrategy.analyze()
```python
async def analyze(self, candle: Candle) -> Optional[Signal]:
    """
    Returns Signal if trading opportunity detected, None otherwise.
    """
```

### RiskManager.validate_risk()
```python
def validate_risk(self, signal: Signal, position: Optional[Position]) -> bool:
    """
    Validates:
    - No existing conflicting position
    - LONG: TP > entry, SL < entry
    - SHORT: TP < entry, SL > entry

    Returns True if valid, False if rejected (logs warnings internally).
    """
```

### RiskManager.calculate_position_size()
```python
def calculate_position_size(
    self,
    account_balance: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: int,
    symbol_info: Optional[dict] = None
) -> float:
    """
    Calculates position size based on:
    - Max risk per trade (e.g., 1% of account)
    - SL distance percentage
    - Leverage multiplier
    - Maximum position size limit

    Returns quantity in base asset units (e.g., BTC for BTCUSDT).

    Raises ValueError for invalid inputs.
    """
```

### OrderExecutionManager.get_position()
```python
def get_position(self, symbol: str) -> Optional[Position]:
    """
    Returns current position for symbol or None if no position.
    Queries Binance API.
    """
```

### OrderExecutionManager.get_account_balance()
```python
def get_account_balance(self) -> float:
    """
    Returns total USDT balance in futures account.
    Queries Binance API.
    """
```

### OrderExecutionManager.execute_signal()
```python
def execute_signal(
    self,
    signal: Signal,
    quantity: float,
    reduce_only: bool = False
) -> tuple[Order, list[Order]]:
    """
    Places market entry order with TP/SL orders.

    Returns:
    - For LONG_ENTRY/SHORT_ENTRY: (entry_order, [tp_order, sl_order])
    - For CLOSE_LONG/CLOSE_SHORT: (entry_order, [])

    Raises:
    - ValidationError: Invalid quantity or signal
    - OrderRejectedError: Binance rejected order
    - OrderExecutionError: API call failed
    """
```

---

## Error Handling Strategy

### _on_candle_closed()
```python
try:
    signal = await self.strategy.analyze(candle)
except Exception as e:
    # Log strategy errors, don't crash
    self.logger.error(f"Strategy analysis failed: {e}", exc_info=True)
    return
```

### _on_signal_generated()
```python
try:
    # Complete trading flow
    ...
except Exception as e:
    # Log execution errors, don't crash
    self.logger.error(f"Failed to execute signal: {e}", exc_info=True)
    # Don't re-raise - system continues running
```

### _on_order_filled()
```python
# Simple logging - minimal error potential
# If order data is invalid, log will show it
```

---

## Testing Strategy

### Unit Tests

**Test File**: `tests/test_main_signal_processing.py`

#### Test _on_candle_closed()
```python
@pytest.mark.asyncio
async def test_on_candle_closed_with_signal():
    """Test signal generation and publishing."""
    # Setup: Mock strategy.analyze() to return signal
    # Verify: SIGNAL_GENERATED event published to 'signal' queue

@pytest.mark.asyncio
async def test_on_candle_closed_no_signal():
    """Test when strategy returns None."""
    # Setup: Mock strategy.analyze() returns None
    # Verify: No event published, debug log only

@pytest.mark.asyncio
async def test_on_candle_closed_strategy_error():
    """Test strategy exception handling."""
    # Setup: Mock strategy.analyze() raises exception
    # Verify: Error logged, no crash, no event published
```

#### Test _on_signal_generated()
```python
@pytest.mark.asyncio
async def test_on_signal_generated_success():
    """Test complete trading flow success."""
    # Setup: Mock all components (no position, valid balance, successful execution)
    # Verify: Order executed, ORDER_FILLED event published

@pytest.mark.asyncio
async def test_on_signal_generated_risk_rejection():
    """Test risk validation rejection."""
    # Setup: Mock validate_risk() returns False
    # Verify: Warning logged, no execution

@pytest.mark.asyncio
async def test_on_signal_generated_existing_position():
    """Test rejection due to existing position."""
    # Setup: Mock get_position() returns existing position
    # Verify: Rejected by risk validation

@pytest.mark.asyncio
async def test_on_signal_generated_execution_error():
    """Test order execution failure."""
    # Setup: Mock execute_signal() raises OrderExecutionError
    # Verify: Error logged, no crash, no ORDER_FILLED event
```

#### Test _on_order_filled()
```python
@pytest.mark.asyncio
async def test_on_order_filled():
    """Test order fill logging."""
    # Setup: Create Order object
    # Verify: Info log contains order details
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_complete_trading_flow():
    """Test full flow from candle to order."""
    # Setup: Real EventBus, mocked external dependencies
    # Flow:
    #   1. Publish CANDLE_CLOSED event
    #   2. Verify _on_candle_closed called
    #   3. Verify SIGNAL_GENERATED published
    #   4. Verify _on_signal_generated called
    #   5. Verify ORDER_FILLED published
    #   6. Verify _on_order_filled called
```

---

## Common Pitfalls

### 1. Forgetting Async/Await
```python
# ❌ Wrong
signal = self.strategy.analyze(candle)

# ✅ Correct
signal = await self.strategy.analyze(candle)
```

### 2. Wrong Queue Names
```python
# ❌ Wrong - signals go to 'data' queue
await self.event_bus.publish(signal_event, queue_name='data')

# ✅ Correct - signals go to 'signal' queue
await self.event_bus.publish(signal_event, queue_name='signal')
```

### 3. Re-Raising Exceptions
```python
# ❌ Wrong - crashes system
except Exception as e:
    self.logger.error(f"Failed: {e}")
    raise

# ✅ Correct - log and continue
except Exception as e:
    self.logger.error(f"Failed: {e}", exc_info=True)
    # Don't re-raise
```

### 4. Missing Error Context
```python
# ❌ Wrong - loses stack trace
except Exception as e:
    self.logger.error(f"Failed: {e}")

# ✅ Correct - includes stack trace
except Exception as e:
    self.logger.error(f"Failed: {e}", exc_info=True)
```

### 5. Not Checking Signal is Not None
```python
# ❌ Wrong - might crash if signal is None
signal = await self.strategy.analyze(candle)
self.logger.info(f"Signal: {signal.signal_type.value}")

# ✅ Correct - check for None
signal = await self.strategy.analyze(candle)
if signal is not None:
    self.logger.info(f"Signal: {signal.signal_type.value}")
```

---

## Implementation Checklist

### Code Changes
- [ ] Implement `_on_candle_closed()` with strategy analysis
- [ ] Implement `_on_signal_generated()` with complete trading flow
- [ ] Implement `_on_order_filled()` with order logging
- [ ] Add proper error handling to all handlers
- [ ] Use correct queue names ('signal', 'order')
- [ ] Add comprehensive logging at all levels

### Testing
- [ ] Create `tests/test_main_signal_processing.py`
- [ ] Test _on_candle_closed() success path
- [ ] Test _on_candle_closed() no signal case
- [ ] Test _on_candle_closed() strategy error
- [ ] Test _on_signal_generated() success path
- [ ] Test _on_signal_generated() risk rejection
- [ ] Test _on_signal_generated() execution error
- [ ] Test _on_order_filled() logging
- [ ] Run all tests and achieve >85% coverage

### Verification
- [ ] No import errors
- [ ] No syntax errors
- [ ] All tests passing
- [ ] Proper async/await usage
- [ ] Error handling doesn't crash system
- [ ] Logging levels appropriate (info/debug/error)

---

## Next Steps After Implementation

1. **Run Tests**: `python3 -m pytest tests/test_main_signal_processing.py -v`
2. **Check Coverage**: Verify coverage on signal processing handlers
3. **Integration Test**: Test with mocked EventBus for full flow
4. **Commit**: Commit with comprehensive message
5. **Move to Subtask 10.4**: Graceful shutdown implementation

---

## References

- Subtask 10.1: TradingBot initialization (Complete)
- Subtask 10.2: Event handler setup (Complete)
- Task 5: Strategy implementation (BaseStrategy interface)
- Task 6: Order execution (OrderExecutionManager interface)
- Task 7: Risk management (RiskManager interface)
- Quick Reference: `.taskmaster/designs/TASK-10-QUICK-REFERENCE.md` lines 125-189
