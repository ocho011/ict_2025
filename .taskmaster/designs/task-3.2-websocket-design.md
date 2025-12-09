# Subtask 3.2: WebSocket Connection Management - Detailed Design

**Created**: 2025-12-09
**Parent Task**: #3 - Binance API Connection & WebSocket Data Collector
**Dependencies**: ✅ #3.1 (BinanceDataCollector class skeleton)
**Status**: Ready for Implementation

---

## 1. Overview

Implement the `start_streaming()` async method to establish WebSocket connections and subscribe to real-time kline (candlestick) streams from Binance USDT-M Futures.

### Key Objectives
- Establish WebSocket connection using `UMFuturesWebsocketClient`
- Subscribe to kline streams for all configured symbol/interval pairs
- Handle connection initialization and errors gracefully
- Set up message routing to handler method (stub for now)
- Update internal state flags appropriately

---

## 2. Architecture Integration

### 2.1 Current Class State (from Subtask 3.1)

```python
class BinanceDataCollector:
    # Constants (already defined)
    TESTNET_WS_URL = "wss://stream.binancefuture.com"
    MAINNET_WS_URL = "wss://fstream.binance.com"

    # Instance variables (already initialized in __init__)
    self.is_testnet: bool
    self.symbols: List[str]  # Already normalized to uppercase
    self.intervals: List[str]
    self.ws_client: Optional[UMFuturesWebsocketClient] = None
    self._running: bool = False
    self._is_connected: bool = False
    self.logger: logging.Logger
```

### 2.2 Method Placement

Insert after `__repr__` method at line 140 in `src/core/data_collector.py`

---

## 3. Detailed Design

### 3.1 Stream Name Format

Binance uses a specific format for stream names in WebSocket subscriptions:

**Format**: `{symbol_lower}@kline_{interval}`

**Examples**:
- `btcusdt@kline_1m` - BTCUSDT 1-minute klines
- `ethusdt@kline_5m` - ETHUSDT 5-minute klines
- `btcusdt@kline_1h` - BTCUSDT 1-hour klines

**Generation Logic**:
```python
streams = [
    f"{symbol.lower()}@kline_{interval}"
    for symbol in self.symbols
    for interval in self.intervals
]
```

**Important**:
- Symbols must be lowercase for WebSocket (different from REST API)
- `self.symbols` already normalized to uppercase in constructor
- Apply `.lower()` during stream name generation

### 3.2 WebSocket Client Initialization

**Library**: `binance-futures-connector` v4.1.0+
**Class**: `UMFuturesWebsocketClient`

**Initialization**:
```python
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

stream_url = self.TESTNET_WS_URL if self.is_testnet else self.MAINNET_WS_URL
self.ws_client = UMFuturesWebsocketClient(stream_url=stream_url)
```

**URL Selection Logic**:
- `is_testnet=True` → `TESTNET_WS_URL` = `"wss://stream.binancefuture.com"`
- `is_testnet=False` → `MAINNET_WS_URL` = `"wss://fstream.binance.com"`

### 3.3 Kline Stream Subscription

**Method**: `ws_client.kline(symbol, interval, callback)`

**Subscription Pattern**:
```python
for symbol in self.symbols:
    for interval in self.intervals:
        self.ws_client.kline(
            symbol=symbol.lower(),  # Lowercase required
            interval=interval,
            callback=self._handle_kline_message  # Message handler
        )
```

**Key Details**:
- Subscribe individually for each symbol/interval pair
- Symbol must be lowercase for WebSocket API
- Interval uses standard format: '1m', '5m', '15m', '1h', '4h', etc.
- Callback receives raw WebSocket messages

### 3.4 Message Handler Stub

Since Subtask 3.3 implements the actual message parsing, create a placeholder stub:

```python
def _handle_kline_message(self, message: Dict) -> None:
    """
    Handle incoming kline WebSocket messages.

    Args:
        message: Raw WebSocket message from Binance

    Note:
        Implementation in Subtask 3.3
    """
    pass  # Will be implemented in Subtask 3.3
```

### 3.5 State Management

**State Flags to Update**:
- `_running`: Indicates collector is actively streaming
- `_is_connected`: Indicates WebSocket connection established

**Update Logic**:
```python
# On successful connection
self._running = True
self._is_connected = True
```

**Purpose**:
- `_running`: Used by `stop()` method to check if shutdown needed
- `_is_connected`: Used for status monitoring and diagnostics

### 3.6 Error Handling Strategy

**Error Categories**:
1. **Connection Errors**: Network issues, invalid credentials, URL problems
2. **Subscription Errors**: Invalid symbol/interval, rate limiting
3. **WebSocket Library Errors**: Unexpected library behavior

**Handling Approach**:
```python
try:
    # Connection and subscription logic
    ...
    self._running = True
    self._is_connected = True
    self.logger.info(
        f"Started streaming {len(self.symbols) * len(self.intervals)} streams"
    )
except Exception as e:
    self.logger.error(f"Failed to start streaming: {e}", exc_info=True)
    raise ConnectionError(f"WebSocket initialization failed: {e}")
```

**Design Rationale**:
- Log full exception with stack trace (`exc_info=True`)
- Raise `ConnectionError` with context for caller to handle
- Don't swallow exceptions - fail fast and loud

### 3.7 Idempotency Check

**Protection Against Duplicate Calls**:
```python
if self._running:
    self.logger.warning("Streaming already active, ignoring start request")
    return
```

**Placement**: At the beginning of `start_streaming()` method

**Purpose**: Prevent duplicate WebSocket subscriptions if method called multiple times

---

## 4. Complete Method Implementation

```python
async def start_streaming(self) -> None:
    """
    Start WebSocket streaming for all configured symbol/interval pairs.

    Establishes WebSocket connection and subscribes to kline streams for each
    combination of symbols and intervals configured in the constructor.

    Raises:
        ConnectionError: If WebSocket connection fails

    Example:
        >>> collector = BinanceDataCollector(...)
        >>> await collector.start_streaming()
        >>> # Now receiving real-time kline updates

    Note:
        - Method is idempotent - multiple calls are ignored
        - Connection is automatic via binance-futures-connector library
        - Messages routed to _handle_kline_message() callback
    """
    # Idempotency check
    if self._running:
        self.logger.warning("Streaming already active, ignoring start request")
        return

    try:
        # Select WebSocket URL based on environment
        stream_url = self.TESTNET_WS_URL if self.is_testnet else self.MAINNET_WS_URL

        self.logger.info(
            f"Initializing WebSocket connection to {stream_url}"
        )

        # Initialize WebSocket client
        self.ws_client = UMFuturesWebsocketClient(stream_url=stream_url)

        # Subscribe to kline streams for all symbol/interval combinations
        stream_count = 0
        for symbol in self.symbols:
            for interval in self.intervals:
                stream_name = f"{symbol.lower()}@kline_{interval}"
                self.logger.debug(f"Subscribing to stream: {stream_name}")

                self.ws_client.kline(
                    symbol=symbol.lower(),
                    interval=interval,
                    callback=self._handle_kline_message
                )
                stream_count += 1

        # Update state flags
        self._running = True
        self._is_connected = True

        self.logger.info(
            f"Successfully started streaming {stream_count} streams "
            f"({len(self.symbols)} symbols × {len(self.intervals)} intervals)"
        )

    except Exception as e:
        self.logger.error(
            f"Failed to start WebSocket streaming: {e}",
            exc_info=True
        )
        raise ConnectionError(f"WebSocket initialization failed: {e}")


def _handle_kline_message(self, message: Dict) -> None:
    """
    Handle incoming kline WebSocket messages.

    Args:
        message: Raw WebSocket message dictionary from Binance

    Note:
        Full implementation in Subtask 3.3 - Message Parsing.
        This stub allows Subtask 3.2 (WebSocket connection) to be
        implemented and tested independently.
    """
    pass  # Implementation in Subtask 3.3
```

---

## 5. Test Strategy

### 5.1 Unit Tests with Mocking

**Test File**: `tests/core/test_data_collector.py` (extend existing)

**Mock Approach**:
```python
from unittest.mock import Mock, patch, call

@patch('src.core.data_collector.UMFuturesWebsocketClient')
async def test_start_streaming_testnet(mock_ws_client_class):
    """Test WebSocket initialization with testnet URL"""
    # Mock WebSocket client instance
    mock_ws_instance = Mock()
    mock_ws_client_class.return_value = mock_ws_instance

    # Create collector
    collector = BinanceDataCollector(
        api_key='test_key',
        api_secret='test_secret',
        symbols=['BTCUSDT', 'ETHUSDT'],
        intervals=['1m', '5m'],
        is_testnet=True
    )

    # Start streaming
    await collector.start_streaming()

    # Verify WebSocket client created with testnet URL
    mock_ws_client_class.assert_called_once_with(
        stream_url='wss://stream.binancefuture.com'
    )

    # Verify kline subscriptions (2 symbols × 2 intervals = 4 calls)
    assert mock_ws_instance.kline.call_count == 4

    # Verify state flags
    assert collector._running is True
    assert collector._is_connected is True
```

### 5.2 Test Cases

**Test Suite**: `TestBinanceDataCollectorStreaming`

1. ✅ **test_start_streaming_testnet**
   - Verify testnet WebSocket URL used
   - Verify client initialization

2. ✅ **test_start_streaming_mainnet**
   - Verify mainnet WebSocket URL used
   - Verify client initialization

3. ✅ **test_stream_name_generation**
   - Verify format: `{symbol_lower}@kline_{interval}`
   - Test multiple symbols and intervals
   - Verify lowercase symbol conversion

4. ✅ **test_kline_subscriptions**
   - Verify `kline()` called for each symbol/interval
   - Verify correct symbol (lowercase)
   - Verify correct interval
   - Verify callback set to `_handle_kline_message`

5. ✅ **test_state_management**
   - Verify `_running` set to True
   - Verify `_is_connected` set to True
   - Verify `ws_client` stored

6. ✅ **test_connection_error_handling**
   - Mock WebSocket initialization failure
   - Verify `ConnectionError` raised
   - Verify error logged with stack trace

7. ✅ **test_idempotency**
   - Call `start_streaming()` twice
   - Verify second call ignored
   - Verify warning logged

8. ✅ **test_subscription_count**
   - Test with various symbol/interval combinations
   - Verify correct number of subscriptions
   - Example: 3 symbols × 4 intervals = 12 subscriptions

### 5.3 Coverage Goals

- **Line Coverage**: 100% for `start_streaming()` method
- **Branch Coverage**: All error paths tested
- **Integration**: Verify interaction with WebSocket client

---

## 6. Implementation Checklist

- [ ] Add `_handle_kline_message()` stub method
- [ ] Implement `start_streaming()` async method
- [ ] Add comprehensive docstrings
- [ ] Add debug logging for troubleshooting
- [ ] Create unit test file (extend existing)
- [ ] Implement 8 test cases
- [ ] Verify 100% test coverage
- [ ] Run tests and ensure all pass
- [ ] Update Task Master status to 'done'
- [ ] Commit with descriptive message
- [ ] Push to feature branch

---

## 7. Dependencies & Integration

### 7.1 Upstream Dependencies (Completed)
- ✅ Subtask 3.1: Class skeleton with `ws_client` variable initialized

### 7.2 Downstream Dependencies (Blocked Until Complete)
- ⏳ Subtask 3.3: Message parsing implementation
- ⏳ Subtask 3.5: Buffer management (uses message handler)
- ⏳ Subtask 3.6: Lifecycle management (`stop()` method)

### 7.3 External Dependencies
- `binance-futures-connector` >= 4.1.0
- `asyncio` (Python standard library)
- `logging` (Python standard library)

---

## 8. Risk Analysis

### 8.1 Technical Risks

**Risk 1: WebSocket Library Behavior**
- **Concern**: `UMFuturesWebsocketClient` behavior may differ from documentation
- **Mitigation**: Extensive mocking in tests, integration testing on testnet
- **Severity**: Medium

**Risk 2: Stream Name Format**
- **Concern**: Incorrect stream name format may fail silently
- **Mitigation**: Explicit format validation in tests, documented examples
- **Severity**: Low

**Risk 3: Connection State Management**
- **Concern**: State flags may become inconsistent on errors
- **Mitigation**: Atomic state updates, comprehensive error handling tests
- **Severity**: Low

### 8.2 Integration Risks

**Risk 1: Message Handler Dependency**
- **Concern**: Stub handler may cause issues if messages arrive before 3.3
- **Mitigation**: No-op stub is safe, messages simply ignored until implemented
- **Severity**: Very Low

**Risk 2: Async/Sync Interaction**
- **Concern**: `start_streaming()` is async but WebSocket library may be sync
- **Mitigation**: Review library docs, test async behavior explicitly
- **Severity**: Medium

---

## 9. Success Criteria

**Functional Requirements**:
- ✅ WebSocket client initialized with correct URL
- ✅ Kline subscriptions created for all symbol/interval pairs
- ✅ State flags updated appropriately
- ✅ Errors handled gracefully with logging

**Quality Requirements**:
- ✅ 100% test coverage for new code
- ✅ All 8 test cases passing
- ✅ No linting errors
- ✅ Comprehensive docstrings

**Documentation**:
- ✅ Method docstring with examples
- ✅ Implementation notes for future developers
- ✅ Test strategy documented

---

## 10. Next Steps After Completion

1. **Immediate**: Mark Subtask 3.2 as 'done' in Task Master
2. **Next**: Begin Subtask 3.3 - Implement `_handle_kline_message()`
3. **Follow-up**: Integration testing on Binance testnet
4. **Future**: Performance testing with multiple streams

---

**Design Status**: ✅ Complete - Ready for Implementation
**Reviewed By**: Claude Sonnet 4.5 (Design Agent)
**Implementation Owner**: Claude Sonnet 4.5 (Implementation Agent)
