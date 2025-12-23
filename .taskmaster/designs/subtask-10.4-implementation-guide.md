# Subtask 10.4 Implementation Guide: Graceful Shutdown

## Overview

Implement graceful shutdown mechanism that ensures all components are cleanly stopped without resource leaks.

**Files to Modify**:
- `src/main.py` - Implement `shutdown()` method

**Dependencies**:
- Subtask 10.1 (Initialization) - ✅ Complete
- Component interfaces: BinanceDataCollector, EventBus

---

## Implementation: shutdown() Method

### Purpose
Gracefully stop all trading bot components in the correct order, ensuring no resource leaks.

### Signature
```python
async def shutdown(self) -> None:
    """
    Graceful shutdown - cleanup all components.

    Performs orderly shutdown:
    1. Idempotency check (safe to call multiple times)
    2. Set _running flag to False
    3. Log shutdown initiation
    4. Stop DataCollector (close WebSocket with 5s timeout)
    5. Stop EventBus (drain queues and stop workers with 5s timeout)
    6. Log shutdown completion

    Features:
    - Idempotent (multiple calls safe)
    - Timeout handling for cleanup operations
    - No exceptions propagated (logs errors instead)
    - Clean resource cleanup

    Note:
    - Called from run() method's finally block
    - Triggered by SIGINT/SIGTERM signals
    - Safe to call even if components not fully initialized
    """
```

### Implementation

```python
async def shutdown(self) -> None:
    """
    Graceful shutdown - cleanup all components.

    This method:
    1. Sets _running flag to False
    2. Stops DataCollector (closes WebSocket)
    3. Stops EventBus (drains queues and stops workers)
    4. Logs shutdown completion
    """
    # Step 1: Idempotency check
    if not self._running:
        return

    # Step 2: Set flag
    self._running = False
    self.logger.info("Shutting down...")

    # Step 3: Stop DataCollector with timeout
    await self.data_collector.stop(timeout=5.0)

    # Step 4: Stop EventBus with timeout
    await self.event_bus.shutdown(timeout=5.0)

    # Step 5: Completion log
    self.logger.info("Shutdown complete")
```

---

## Component Interface Reference

### BinanceDataCollector.stop()
```python
async def stop(self, timeout: float = 5.0) -> None:
    """
    Gracefully stop data collection and cleanup resources.

    Execution Order:
    1. Check if already stopped (idempotency)
    2. Set state flags to prevent new operations
    3. Stop WebSocket client with timeout
    4. Close REST API client session
    5. Log final buffer states
    6. Clear state flags

    Args:
        timeout: Maximum time in seconds to wait for cleanup (default: 5.0)

    Raises:
        asyncio.TimeoutError: If cleanup exceeds timeout (logged as warning)

    Features:
    - Idempotent (safe to call multiple times)
    - Does not raise exceptions on cleanup failures
    - Logs warnings if cleanup exceeds timeout
    """
```

**Behavior:**
- ✅ Idempotent
- ✅ Timeout handling (logs warnings, doesn't raise)
- ✅ Closes WebSocket connections
- ✅ Preserves candle buffers

### EventBus.shutdown()
```python
async def shutdown(self, timeout: float = 5.0) -> None:
    """
    Gracefully shutdown EventBus with pending event processing.

    Performs graceful shutdown sequence:
    1. Wait for queues to drain (all events processed)
    2. Stop processors (set _running=False)
    3. Cancel processor tasks if needed

    Args:
        timeout: Max seconds to wait per queue for pending events (default: 5.0)

    Process Flow:
    1. For each queue, wait for queue.join() with timeout
    2. If timeout: log warning, continue to next queue
    3. Call stop() to signal processors
    4. Wait briefly for processors to exit gracefully
    5. Cancel processor tasks if still running

    Error Handling:
    - TimeoutError per queue: logged as warning, continues
    - Task cancellation: always attempted (defensive)
    - Pending events logged if timeout exceeded

    Critical for Trading:
    - Order queue events MUST be processed or logged
    - Timeout prevents indefinite hanging
    - Cancellation as last resort

    Features:
    - Drains queues BEFORE stopping processors
    - Timeout applies PER QUEUE (total time = 3 * timeout)
    - 0.5s grace period for processor exit
    """
```

**Behavior:**
- ✅ Drains queues before stopping (processes pending events)
- ✅ Per-queue timeout (total ~15s for 3 queues with 5s timeout)
- ✅ Graceful processor exit with cancellation fallback
- ✅ Critical for order events

---

## Shutdown Order Rationale

**1. DataCollector First**
- Stops new candle events from arriving
- Prevents new signals from being generated
- Closes external WebSocket connection

**2. EventBus Second**
- Processes remaining events in queues
- Ensures pending orders/signals are handled
- Stops worker tasks cleanly

**Why this order?**
- Stops event **production** before event **consumption**
- Allows EventBus to drain existing events
- Clean separation of concerns

---

## Error Handling Strategy

### No Exception Propagation
Both `DataCollector.stop()` and `EventBus.shutdown()` handle their own errors:
- Log warnings for timeouts
- Log errors for unexpected failures
- Don't raise exceptions

**Result:** `shutdown()` can be simple and clean - just call both methods.

### Idempotency
```python
if not self._running:
    return  # Already shut down, safe to exit
```

This ensures:
- Multiple calls safe (e.g., signal handler + finally block)
- No duplicate cleanup operations
- Clear state tracking

---

## Testing Strategy

### Unit Tests

**Test File**: `tests/test_main_shutdown.py`

```python
@pytest.mark.asyncio
async def test_shutdown_sets_running_flag():
    """Test shutdown sets _running to False."""

@pytest.mark.asyncio
async def test_shutdown_is_idempotent():
    """Test multiple shutdown calls safe."""

@pytest.mark.asyncio
async def test_shutdown_stops_data_collector():
    """Test DataCollector.stop() called with correct timeout."""

@pytest.mark.asyncio
async def test_shutdown_stops_event_bus():
    """Test EventBus.shutdown() called with correct timeout."""

@pytest.mark.asyncio
async def test_shutdown_correct_order():
    """Test DataCollector stopped before EventBus."""

@pytest.mark.asyncio
async def test_shutdown_when_not_running():
    """Test shutdown when _running=False (no-op)."""

@pytest.mark.asyncio
async def test_shutdown_logs_correctly():
    """Test shutdown logs initiation and completion."""
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_shutdown_with_initialized_bot():
    """Test shutdown after full initialization."""
    # Setup: Initialize bot with real components
    # Execute: Call shutdown()
    # Verify: All components stopped, no errors

@pytest.mark.asyncio
async def test_shutdown_with_partial_initialization():
    """Test shutdown if initialization incomplete."""
    # Edge case: What if some components are None?
    # Current implementation assumes initialize() was called
```

---

## Common Pitfalls

### 1. Not Checking _running Flag
```python
# ❌ Wrong - no idempotency check
async def shutdown(self) -> None:
    self._running = False
    # Will run cleanup even if already shut down

# ✅ Correct
async def shutdown(self) -> None:
    if not self._running:
        return
    self._running = False
```

### 2. Wrong Shutdown Order
```python
# ❌ Wrong - EventBus first
await self.event_bus.shutdown(timeout=5.0)
await self.data_collector.stop(timeout=5.0)
# New events might arrive after EventBus stopped

# ✅ Correct - DataCollector first
await self.data_collector.stop(timeout=5.0)
await self.event_bus.shutdown(timeout=5.0)
```

### 3. Forgetting Timeouts
```python
# ❌ Wrong - no timeout (might hang forever)
await self.data_collector.stop()
await self.event_bus.shutdown()

# ✅ Correct - explicit timeouts
await self.data_collector.stop(timeout=5.0)
await self.event_bus.shutdown(timeout=5.0)
```

### 4. Not Awaiting Async Methods
```python
# ❌ Wrong - not awaiting (won't actually stop)
self.data_collector.stop(timeout=5.0)
self.event_bus.shutdown(timeout=5.0)

# ✅ Correct
await self.data_collector.stop(timeout=5.0)
await self.event_bus.shutdown(timeout=5.0)
```

---

## Implementation Checklist

### Code Changes
- [ ] Implement `shutdown()` method in `src/main.py`
- [ ] Add idempotency check (`if not self._running: return`)
- [ ] Set `_running = False`
- [ ] Call `data_collector.stop(timeout=5.0)`
- [ ] Call `event_bus.shutdown(timeout=5.0)`
- [ ] Add logging (shutdown initiation and completion)

### Testing
- [ ] Create `tests/test_main_shutdown.py`
- [ ] Test idempotency (multiple calls safe)
- [ ] Test _running flag management
- [ ] Test component stop calls with correct timeouts
- [ ] Test shutdown order (DataCollector → EventBus)
- [ ] Test logging messages
- [ ] Run all tests and achieve >85% coverage on shutdown()

### Verification
- [ ] No import errors
- [ ] No syntax errors
- [ ] All tests passing
- [ ] Proper async/await usage
- [ ] Idempotency verified
- [ ] Logging clear and informative

---

## Integration with Subtask 10.5

**Note**: Signal handler registration happens in Subtask 10.5 (`main()` function):

```python
def main() -> None:
    bot = TradingBot()
    loop = asyncio.new_event_loop()

    # Signal handlers (Subtask 10.5)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(bot.shutdown())
        )

    # ... rest of main()
```

**This subtask (10.4)** only implements the `shutdown()` method itself.

---

## Expected Behavior

### Normal Shutdown
```
INFO: Shutting down...
INFO: Initiating graceful shutdown... (DataCollector)
INFO: WebSocket client stopped successfully (DataCollector)
DEBUG: REST API client cleanup complete (DataCollector)
INFO: Graceful shutdown complete (DataCollector)
INFO: Shutting down EventBus gracefully (EventBus)
DEBUG: Queue data drained successfully (EventBus)
DEBUG: Queue signal drained successfully (EventBus)
DEBUG: Queue order drained successfully (EventBus)
INFO: EventBus shutdown complete (EventBus)
INFO: Shutdown complete
```

### Timeout Scenario
```
INFO: Shutting down...
WARNING: WebSocket stop exceeded 5s timeout, forcing cleanup (DataCollector)
WARNING: Queue data didn't drain in 5s (3 events remaining). Proceeding... (EventBus)
INFO: Shutdown complete
```

---

## Next Steps After Implementation

1. **Run Tests**: `python3 -m pytest tests/test_main_shutdown.py -v`
2. **Check Coverage**: Verify coverage on shutdown() method
3. **Commit**: Commit with comprehensive message
4. **Move to Subtask 10.5**: Implement main() entry point and run() method

---

## References

- Subtask 10.1: TradingBot initialization (Complete)
- BinanceDataCollector interface: `src/core/data_collector.py:608-687`
- EventBus interface: `src/core/event_handler.py:509-588`
- Quick Reference: `.taskmaster/designs/TASK-10-QUICK-REFERENCE.md` lines 191-217
