# Task 3.6: Lifecycle Management & Graceful Shutdown - Design Specification

**Status**: 📝 Design Phase
**Date**: 2025-12-10
**Type**: Pre-Implementation Design Document

---

## 📋 Purpose

Implement comprehensive lifecycle management for `BinanceDataCollector` including:
- Connection state tracking and health monitoring
- Graceful shutdown with timeout handling
- Async context manager support for Pythonic resource management
- Proper cleanup of WebSocket, REST API, and buffer resources

---

## 🎯 Requirements

### Functional Requirements
1. **Connection State Management**
   - Track WebSocket connection state (`_is_connected` property)
   - Log connection lifecycle events (connected, disconnected)
   - Expose connection state for monitoring

2. **Graceful Shutdown**
   - Implement `stop()` method for explicit shutdown
   - Close WebSocket connections cleanly
   - Close REST API client sessions
   - Maximum 5-second timeout for cleanup operations
   - Cancel all async tasks properly

3. **Async Context Manager**
   - Implement `__aenter__` for resource initialization
   - Implement `__aexit__` for automatic cleanup
   - Support `async with` usage pattern

4. **Resource Cleanup**
   - Flush/preserve buffered candles (non-destructive)
   - Log cleanup progress and warnings
   - Handle cleanup failures gracefully

### Non-Functional Requirements
- **Idempotency**: Multiple `stop()` calls are safe
- **Thread Safety**: Cleanup works with concurrent operations
- **Timeout Handling**: Never hang indefinitely on cleanup
- **Logging**: Clear visibility into lifecycle events
- **Backward Compatibility**: Existing code continues to work

---

## 📐 Architecture Design

### Current State Analysis

**Existing Components** (from `src/core/data_collector.py`):
```python
class BinanceDataCollector:
    # Endpoints
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"
    MAINNET_BASE_URL = "https://fapi.binance.com"
    TESTNET_WS_URL = "wss://stream.binancefuture.com"
    MAINNET_WS_URL = "wss://fstream.binance.com"

    # State flags (lines 125-126)
    self._running = False  # Indicates if streaming is active
    self._is_connected = False  # Tracks WebSocket connection state

    # Resources to manage
    self.rest_client = UMFutures(...)  # REST API client
    self.ws_client: Optional[UMFuturesWebsocketClient] = None  # WebSocket client
    self._candle_buffers: Dict[str, asyncio.Queue] = {}  # Candle buffers
```

**Key Insights**:
1. `_running` and `_is_connected` flags already exist (lines 125-126)
2. `ws_client` is optional and initialized lazily in `start_streaming()`
3. `rest_client` is always initialized in `__init__`
4. Buffers are `asyncio.Queue` instances (thread-safe)
5. Library provides `ws_client.stop()` method for WebSocket cleanup

### New Components to Add

#### 1. Connection State Property
```python
@property
def is_connected(self) -> bool:
    """
    Check if WebSocket connection is active.

    Returns:
        True if WebSocket is connected and streaming, False otherwise
    """
```

#### 2. Graceful Shutdown Method
```python
async def stop(self, timeout: float = 5.0) -> None:
    """
    Gracefully stop data collection and cleanup resources.

    Execution Order:
        1. Check if already stopped (idempotency)
        2. Set state flags to prevent new operations
        3. Stop WebSocket client with timeout
        4. Close REST API client session
        5. Log final buffer states (non-destructive)
        6. Clear state flags

    Args:
        timeout: Maximum time in seconds to wait for cleanup (default: 5.0)

    Note:
        - Method is idempotent - safe to call multiple times
        - Buffers are preserved (use get_candle_buffer() to access)
        - Logs warnings if cleanup exceeds timeout
    """
```

#### 3. Async Context Manager
```python
async def __aenter__(self) -> "BinanceDataCollector":
    """
    Async context manager entry.

    Returns:
        Self instance for use in async with statement

    Example:
        async with BinanceDataCollector(...) as collector:
            await collector.start_streaming()
            # ... use collector ...
        # Automatic cleanup on exit
    """

async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    """
    Async context manager exit with automatic cleanup.

    Args:
        exc_type: Exception type if exception occurred
        exc_val: Exception value if exception occurred
        exc_tb: Exception traceback if exception occurred

    Note:
        - Calls stop() automatically
        - Handles exceptions during cleanup
        - Does not suppress context exceptions
    """
```

---

## 🔄 Detailed Implementation Plan

### Phase 1: Connection State Property

**Location**: After `__repr__()` method (around line 140)

**Implementation**:
```python
@property
def is_connected(self) -> bool:
    """
    Check if WebSocket connection is active.

    Returns:
        True if WebSocket is connected and streaming, False otherwise

    Note:
        - Returns False if WebSocket client not initialized
        - Returns internal _is_connected flag state
    """
    return self._is_connected and self.ws_client is not None
```

**Rationale**:
- Simple property access pattern
- Checks both flag and client existence
- No side effects, pure getter

---

### Phase 2: Graceful Shutdown Method

**Location**: After `get_candle_buffer()` method (around line 600)

**Implementation Strategy**:

```python
async def stop(self, timeout: float = 5.0) -> None:
    """
    Gracefully stop data collection and cleanup resources.

    Execution Order:
        1. Check if already stopped (idempotency)
        2. Set state flags to prevent new operations
        3. Stop WebSocket client with timeout
        4. Close REST API client session
        5. Log final buffer states (non-destructive)
        6. Clear state flags

    Args:
        timeout: Maximum time in seconds to wait for cleanup (default: 5.0)

    Raises:
        asyncio.TimeoutError: If cleanup exceeds timeout (logged as warning)

    Note:
        - Method is idempotent - safe to call multiple times
        - Buffers are preserved (use get_candle_buffer() to access)
        - Logs warnings if cleanup exceeds timeout
        - Does not raise exceptions on cleanup failures
    """
    # Step 1: Idempotency check
    if not self._running and not self._is_connected:
        self.logger.debug("Collector already stopped, ignoring stop request")
        return

    self.logger.info("Initiating graceful shutdown...")

    # Step 2: Set flags to prevent new operations
    self._running = False
    self._is_connected = False

    try:
        # Step 3: Stop WebSocket client with timeout
        if self.ws_client is not None:
            self.logger.debug("Stopping WebSocket client...")
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.ws_client.stop),
                    timeout=timeout
                )
                self.logger.info("WebSocket client stopped successfully")
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"WebSocket stop exceeded {timeout}s timeout, forcing cleanup"
                )
            except Exception as e:
                self.logger.error(f"Error stopping WebSocket client: {e}", exc_info=True)

        # Step 4: Close REST API client (if it has a close method)
        # Note: UMFutures uses requests.Session internally, which doesn't require explicit close
        # But we log for completeness
        self.logger.debug("REST API client cleanup complete")

        # Step 5: Log buffer states (non-destructive)
        buffer_summary = []
        for key, queue in self._candle_buffers.items():
            buffer_summary.append(f"{key}: {queue.qsize()} candles")

        if buffer_summary:
            self.logger.info(
                f"Buffer states at shutdown: {', '.join(buffer_summary)}"
            )
        else:
            self.logger.debug("No buffered candles at shutdown")

        # Step 6: Final state
        self.logger.info("Graceful shutdown complete")

    except Exception as e:
        self.logger.error(f"Unexpected error during shutdown: {e}", exc_info=True)
        # Don't re-raise - best effort cleanup
```

**Key Design Decisions**:

1. **Idempotency**: Check flags first, return early if already stopped
2. **Timeout Handling**: Use `asyncio.wait_for()` with timeout parameter
3. **Error Handling**: Log errors but don't raise (best-effort cleanup)
4. **Buffer Preservation**: Log buffer states but don't clear queues
5. **Thread Safety**: Use `asyncio.to_thread()` for synchronous `ws_client.stop()`

---

### Phase 3: Async Context Manager

**Location**: After `stop()` method

**Implementation**:

```python
async def __aenter__(self) -> "BinanceDataCollector":
    """
    Async context manager entry.

    Returns:
        Self instance for use in async with statement

    Example:
        async with BinanceDataCollector(...) as collector:
            await collector.start_streaming()
            # ... use collector ...
        # Automatic cleanup on exit

    Note:
        - Does NOT automatically call start_streaming()
        - User must explicitly start streaming within context
        - Provides automatic cleanup on context exit
    """
    self.logger.debug("Entering async context manager")
    return self

async def __aexit__(
    self,
    exc_type: Optional[type],
    exc_val: Optional[BaseException],
    exc_tb: Optional[object]
) -> None:
    """
    Async context manager exit with automatic cleanup.

    Args:
        exc_type: Exception type if exception occurred
        exc_val: Exception value if exception occurred
        exc_tb: Exception traceback if exception occurred

    Note:
        - Calls stop() automatically
        - Handles exceptions during cleanup
        - Does not suppress context exceptions (returns None)
        - Logs context exceptions for debugging
    """
    if exc_type is not None:
        self.logger.warning(
            f"Exiting context with exception: {exc_type.__name__}: {exc_val}"
        )
    else:
        self.logger.debug("Exiting async context manager normally")

    # Always attempt cleanup
    try:
        await self.stop()
    except Exception as e:
        self.logger.error(
            f"Error during context manager cleanup: {e}",
            exc_info=True
        )

    # Don't suppress exceptions from the context
    return None
```

**Key Design Decisions**:

1. **No Auto-Start**: `__aenter__` doesn't call `start_streaming()` automatically
   - Gives user control over when streaming starts
   - Allows for additional setup within context

2. **Exception Handling**: Log context exceptions but don't suppress
   - Return `None` (falsy) to propagate exceptions
   - Cleanup still runs even if context raised

3. **Best-Effort Cleanup**: Catch cleanup exceptions to prevent masking context exceptions

---

## 🧪 Test Strategy

### Unit Tests

#### Test Suite 1: Connection State Property (3 tests)
```python
def test_is_connected_false_when_not_started(data_collector):
    """Verify is_connected returns False before start_streaming()"""

def test_is_connected_true_after_start(data_collector):
    """Verify is_connected returns True after successful start_streaming()"""

def test_is_connected_false_after_stop(data_collector):
    """Verify is_connected returns False after stop()"""
```

#### Test Suite 2: stop() Method (8 tests)
```python
def test_stop_idempotency(data_collector):
    """Verify multiple stop() calls are safe"""

def test_stop_closes_websocket(data_collector):
    """Verify WebSocket client stop() is called"""

def test_stop_preserves_buffers(data_collector):
    """Verify buffers remain accessible after stop()"""

def test_stop_timeout_handling(data_collector):
    """Verify timeout parameter works correctly"""

def test_stop_without_websocket(data_collector):
    """Verify stop() works when ws_client is None"""

def test_stop_logs_buffer_states(data_collector, caplog):
    """Verify buffer states are logged during shutdown"""

def test_stop_handles_websocket_errors(data_collector):
    """Verify cleanup continues if WebSocket stop() raises"""

def test_stop_updates_state_flags(data_collector):
    """Verify _running and _is_connected are set to False"""
```

#### Test Suite 3: Async Context Manager (5 tests)
```python
async def test_context_manager_enter_returns_self(data_collector):
    """Verify __aenter__ returns collector instance"""

async def test_context_manager_exit_calls_stop(data_collector):
    """Verify __aexit__ calls stop() automatically"""

async def test_context_manager_with_exception(data_collector):
    """Verify cleanup runs even with context exception"""

async def test_context_manager_does_not_suppress_exceptions(data_collector):
    """Verify context exceptions propagate correctly"""

async def test_context_manager_full_lifecycle(data_collector):
    """Integration: async with → start_streaming → use → cleanup"""
```

#### Test Suite 4: Integration Tests (3 tests)
```python
async def test_start_and_stop_lifecycle(data_collector):
    """Full lifecycle: start → stop → verify cleanup"""

async def test_stop_with_active_buffers(data_collector):
    """Stop with candles in buffer, verify accessible afterward"""

async def test_context_manager_usage_pattern(data_collector):
    """Real-world usage pattern with context manager"""
```

**Total Tests**: 19 comprehensive unit tests

---

## 🔗 Integration Points

### Existing Methods to Update

#### 1. `start_streaming()` - Line State Updates
**Current** (line 295):
```python
# Update state flags
self._running = True
self._is_connected = True
```

**After Implementation**: No changes needed
- Already sets `_is_connected = True` on successful connection
- `stop()` will set it back to `False`

#### 2. Error Handling in `start_streaming()`
**Current** (lines 298-303):
```python
except Exception as e:
    self.logger.error(
        f"Failed to start WebSocket streaming: {e}",
        exc_info=True
    )
    raise ConnectionError(f"WebSocket initialization failed: {e}")
```

**Enhancement** (optional):
```python
except Exception as e:
    self._running = False
    self._is_connected = False  # Ensure flags reflect failure
    self.logger.error(...)
    raise ConnectionError(...)
```

---

## 📊 State Transition Diagram

```
┌─────────────────┐
│  Initialized    │ ← __init__()
│  _running=False │
│  _connected=F   │
└────────┬────────┘
         │
         │ start_streaming()
         ↓
┌─────────────────┐
│   Streaming     │
│  _running=True  │
│  _connected=T   │
└────────┬────────┘
         │
         │ stop() or __aexit__()
         ↓
┌─────────────────┐
│    Stopped      │
│  _running=False │
│  _connected=F   │
└─────────────────┘
         ↑
         │
         └──────── (can restart)
```

---

## ⚠️ Error Handling Strategy

### Timeout Scenarios

**Problem**: WebSocket `stop()` hangs or takes too long

**Solution**:
```python
await asyncio.wait_for(
    asyncio.to_thread(self.ws_client.stop),
    timeout=timeout
)
```
- Wrap in `asyncio.wait_for()` with timeout
- Log warning if timeout exceeded
- Continue with rest of cleanup

### WebSocket Stop Errors

**Problem**: `ws_client.stop()` raises exception

**Solution**:
```python
try:
    await asyncio.wait_for(...)
except asyncio.TimeoutError:
    self.logger.warning("WebSocket stop timeout")
except Exception as e:
    self.logger.error(f"Error stopping WebSocket: {e}", exc_info=True)
```
- Catch and log all exceptions
- Don't re-raise (best-effort cleanup)
- Continue with remaining cleanup steps

### Context Manager Cleanup Errors

**Problem**: `stop()` fails during `__aexit__`

**Solution**:
```python
try:
    await self.stop()
except Exception as e:
    self.logger.error(f"Cleanup error: {e}", exc_info=True)
```
- Catch cleanup exceptions to prevent masking context exceptions
- Return `None` to propagate original context exception

---

## 🎯 Design Decisions & Trade-offs

### 1. Buffer Preservation vs. Cleanup
**Decision**: Preserve buffers, don't clear them in `stop()`

**Rationale**:
- Users may want to access buffered data after shutdown
- Clearing loses potentially valuable data
- Can call `get_candle_buffer()` after `stop()` to retrieve

**Trade-off**: Memory not released until GC, but safer behavior

---

### 2. Timeout Default Value
**Decision**: 5-second timeout for cleanup

**Rationale**:
- Binance WebSocket typically disconnects in <1 second
- 5 seconds provides generous buffer
- Matches task requirements

**Trade-off**: May be too aggressive for slow networks, but prevents hangs

---

### 3. Context Manager Auto-Start
**Decision**: Don't call `start_streaming()` in `__aenter__`

**Rationale**:
- User may need to configure additional state before streaming
- Explicit is better than implicit (Zen of Python)
- Allows for setup within context before streaming

**Trade-off**: Less "magical" but more flexible and predictable

---

### 4. Idempotency
**Decision**: `stop()` is idempotent - safe to call multiple times

**Rationale**:
- Common pattern in resource management
- Prevents errors in complex cleanup scenarios
- Matches `start_streaming()` idempotency

**Trade-off**: None - strictly better behavior

---

### 5. Thread Safety for ws_client.stop()
**Decision**: Use `asyncio.to_thread()` wrapper

**Rationale**:
- `ws_client.stop()` is synchronous (blocking)
- Calling from async context can block event loop
- `asyncio.to_thread()` runs in thread pool

**Trade-off**: Slight overhead, but prevents event loop blocking

---

## 📝 Documentation Updates

### Class Docstring Update
**Current** (lines 31-41):
```python
Example:
    >>> collector = BinanceDataCollector(...)
    >>> await collector.start_streaming()
    >>> # ... data collection active ...
    >>> collector.stop()
```

**Updated**:
```python
Example:
    >>> # Explicit lifecycle management
    >>> collector = BinanceDataCollector(...)
    >>> await collector.start_streaming()
    >>> # ... data collection active ...
    >>> await collector.stop()

    >>> # Or use async context manager (recommended)
    >>> async with BinanceDataCollector(...) as collector:
    ...     await collector.start_streaming()
    ...     # ... data collection active ...
    >>> # Automatic cleanup on exit
```

---

## ✅ Implementation Checklist

### Phase 1: Core Implementation
- [ ] Add `is_connected` property after `__repr__()`
- [ ] Implement `stop()` method after `get_candle_buffer()`
- [ ] Implement `__aenter__` and `__aexit__` methods
- [ ] Update class docstring with context manager example
- [ ] Add type hints and docstrings

### Phase 2: Testing
- [ ] Write 3 tests for `is_connected` property
- [ ] Write 8 tests for `stop()` method
- [ ] Write 5 tests for context manager
- [ ] Write 3 integration tests
- [ ] Verify all 19 tests pass

### Phase 3: Documentation
- [ ] Update class docstring example
- [ ] Add usage examples to README (if exists)
- [ ] Document cleanup behavior
- [ ] Note buffer preservation in docstrings

### Phase 4: Validation
- [ ] Run full test suite
- [ ] Test on actual Binance Testnet
- [ ] Verify no resource leaks (memory, connections)
- [ ] Check timeout handling with slow connections

---

## 🔗 Related Files

### Implementation
- `src/core/data_collector.py` - Main implementation file

### Tests
- `tests/core/test_data_collector.py` - Test suite location

### Documentation
- `.taskmaster/designs/task-3-design-spec.md` - Overall Task #3 architecture
- `.taskmaster/designs/task-3.6-lifecycle-management-design.md` - This document

---

## 📌 Notes

### Library Behavior
- `binance-futures-connector` handles automatic reconnection internally
- `ws_client.stop()` is synchronous (blocking call)
- `UMFutures` REST client doesn't require explicit cleanup (uses requests.Session)

### Future Enhancements
- Add connection health monitoring (ping/pong heartbeat)
- Add reconnection event callbacks
- Add connection state change notifications
- Consider graceful buffer flush option (save to disk)

---

**Implementation Status**: 📝 **DESIGN COMPLETE** - Ready for implementation

**Next Step**: Implement `is_connected` property, `stop()` method, and context manager
