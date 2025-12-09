# Task #3: BinanceDataCollector - Detailed Design Specification

**Created**: 2025-12-09
**Status**: Design Complete - Ready for Implementation
**Complexity**: 7/10

---

## 1. Executive Summary

The `BinanceDataCollector` is a focused, production-ready component responsible for real-time market data acquisition from Binance USDT-M Futures markets. It provides dual data access: (1) WebSocket streaming for real-time candle updates, and (2) REST API for historical candle retrieval.

### Key Design Principles
- **Single Responsibility**: Data collection only - no strategy logic or event bus integration
- **Async-First**: Built on asyncio for non-blocking operations
- **Thread-Safe**: Uses `asyncio.Queue` for concurrent access safety
- **Resilient**: Graceful error handling and automatic reconnection via library
- **Testable**: Clean interfaces for mocking and unit testing

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  BinanceDataCollector                        │
│                                                              │
│  ┌─────────────┐         ┌──────────────┐                  │
│  │ REST Client │────────▶│  Historical  │                  │
│  │ (UMFutures) │         │    Candles   │                  │
│  └─────────────┘         └──────────────┘                  │
│                                                              │
│  ┌─────────────┐         ┌──────────────┐                  │
│  │ WebSocket   │────────▶│  Real-time   │                  │
│  │   Client    │         │   Streaming  │                  │
│  └─────────────┘         └──────────────┘                  │
│                                 │                            │
│                                 ▼                            │
│                     _handle_kline_message()                 │
│                                 │                            │
│                                 ▼                            │
│                          Parse to Candle                    │
│                                 │                            │
│                    ┌────────────┴────────────┐              │
│                    │                         │              │
│                    ▼                         ▼              │
│            on_candle_callback()      Buffer Management      │
│             (Event Bus Hook)         (asyncio.Queue)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Component Interface Design

### 3.1 Class Signature

```python
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from typing import Callable, Dict, List, Optional
from datetime import datetime
import asyncio
import logging

from src.models.candle import Candle
```

### 3.2 Constants

```python
class BinanceDataCollector:
    # URL Configuration
    TESTNET_BASE_URL = "https://testnet.binancefuture.com"
    MAINNET_BASE_URL = "https://fapi.binance.com"
    TESTNET_WS_URL = "wss://stream.binancefuture.com"
    MAINNET_WS_URL = "wss://fstream.binance.com"

    # Buffer Configuration
    DEFAULT_BUFFER_SIZE = 500  # ~8.3 hours for 1m interval
    MAX_BUFFER_SIZE = 1000
```

### 3.3 Constructor

```python
def __init__(
    self,
    api_key: str,
    api_secret: str,
    symbols: List[str],
    intervals: List[str],
    is_testnet: bool = True,
    on_candle_callback: Optional[Callable[[Candle], None]] = None,
    buffer_size: int = DEFAULT_BUFFER_SIZE
) -> None:
    """
    Initialize BinanceDataCollector.

    Args:
        api_key: Binance API key
        api_secret: Binance API secret
        symbols: List of trading pairs (e.g., ['BTCUSDT', 'ETHUSDT'])
        intervals: List of timeframes (e.g., ['1m', '5m', '1h'])
        is_testnet: Use testnet (True) or mainnet (False)
        on_candle_callback: Callback function invoked on new candles
        buffer_size: Maximum candles to buffer per symbol/interval

    Design Notes:
        - Normalizes symbols to uppercase for consistency
        - Does NOT start streaming in constructor (lazy initialization)
        - Initializes REST client immediately for historical data access
    """
```

**State Initialization**:
```python
self.is_testnet = is_testnet
self.symbols = [s.upper() for s in symbols]
self.intervals = intervals
self.on_candle_callback = on_candle_callback
self.buffer_size = buffer_size

# Candle buffers: {'{SYMBOL}_{INTERVAL}': asyncio.Queue}
self._candle_buffers: Dict[str, asyncio.Queue] = {}

# REST client (synchronous)
base_url = self.TESTNET_BASE_URL if is_testnet else self.MAINNET_BASE_URL
self.rest_client = UMFutures(
    key=api_key,
    secret=api_secret,
    base_url=base_url
)

# WebSocket client (async)
self.ws_client: Optional[UMFuturesWebsocketClient] = None

# State management
self._running = False
self._is_connected = False

# Logging
self.logger = logging.getLogger(__name__)
```

---

## 4. Public API Methods

### 4.1 `async start_streaming()`

**Purpose**: Initialize WebSocket connections and begin real-time data streaming.

**Algorithm**:
```python
async def start_streaming(self) -> None:
    """
    Start WebSocket streaming for all configured symbols and intervals.

    Process:
        1. Generate stream names for each symbol/interval pair
        2. Initialize UMFuturesWebsocketClient with correct URL
        3. Subscribe to kline streams for each pair
        4. Set connection state to active

    Raises:
        ConnectionError: If WebSocket initialization fails
    """
    if self._running:
        self.logger.warning("Streaming already active")
        return

    # Generate stream names: 'btcusdt@kline_1m', 'btcusdt@kline_5m', ...
    streams = []
    for symbol in self.symbols:
        for interval in self.intervals:
            stream_name = f"{symbol.lower()}@kline_{interval}"
            streams.append(stream_name)

    self.logger.info(f"Subscribing to {len(streams)} streams: {streams}")

    # Select WebSocket URL
    ws_url = self.TESTNET_WS_URL if self.is_testnet else self.MAINNET_WS_URL

    # Initialize WebSocket client
    try:
        self.ws_client = UMFuturesWebsocketClient(
            stream_url=ws_url,
            on_message=self._handle_kline_message,
            on_error=self._handle_ws_error,
            on_close=self._handle_ws_close
        )

        # Subscribe to each stream
        for stream in streams:
            symbol_upper = stream.split('@')[0].upper()
            interval = stream.split('_')[1]
            self.ws_client.kline(symbol=symbol_upper, interval=interval)

        self._running = True
        self._is_connected = True
        self.logger.info("WebSocket streaming started successfully")

    except Exception as e:
        self.logger.error(f"Failed to start streaming: {e}", exc_info=True)
        raise ConnectionError(f"WebSocket initialization failed: {e}")
```

**Design Rationale**:
- **Stream Naming**: Follows Binance convention `{symbol_lower}@kline_{interval}`
- **Individual Subscriptions**: Subscribe per stream for clarity (not combined streams)
- **Error Handling**: Connection failures raise `ConnectionError` for caller handling
- **Idempotency**: Check `_running` flag to prevent duplicate subscriptions

---

### 4.2 `get_historical_candles()`

**Purpose**: Fetch historical candle data via REST API for buffer pre-population.

**Algorithm**:
```python
def get_historical_candles(
    self,
    symbol: str,
    interval: str,
    limit: int = 500
) -> List[Candle]:
    """
    Retrieve historical candles from Binance REST API.

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')
        interval: Timeframe (e.g., '1h', '15m')
        limit: Number of candles (max 1500, default 500)

    Returns:
        List of Candle objects sorted by open_time (oldest first)

    Raises:
        ValueError: Invalid symbol or interval
        requests.exceptions.HTTPError: API error (rate limit, etc.)

    Design Notes:
        - Synchronous method (uses REST client)
        - Can be called before start_streaming() for buffer init
        - Rate limits: 1200 requests/minute (weight 1 per request)
    """
    try:
        self.logger.debug(
            f"Fetching {limit} historical candles for {symbol} {interval}"
        )

        # Call Binance REST API
        klines = self.rest_client.klines(
            symbol=symbol.upper(),
            interval=interval,
            limit=min(limit, 1500)  # Binance max
        )

        # Parse REST response
        candles = [
            self._parse_rest_kline(kline, symbol, interval)
            for kline in klines
        ]

        self.logger.info(f"Retrieved {len(candles)} historical candles")
        return candles

    except Exception as e:
        self.logger.error(f"Historical candle fetch failed: {e}", exc_info=True)
        raise
```

**REST Response Format** (array per candle):
```python
[
    [
        1499040000000,      # 0: Open time (ms)
        "0.01634000",       # 1: Open price
        "0.80000000",       # 2: High price
        "0.01575800",       # 3: Low price
        "0.01577100",       # 4: Close price
        "148976.11427815",  # 5: Volume
        1499644799999,      # 6: Close time (ms)
        "2434.19055334",    # 7: Quote asset volume
        308,                # 8: Number of trades
        "1756.87402397",    # 9: Taker buy base volume
        "28.46694368",      # 10: Taker buy quote volume
        "0"                 # 11: Ignore
    ]
]
```

---

### 4.3 `stop()`

**Purpose**: Graceful shutdown of WebSocket connections and resource cleanup.

**Algorithm**:
```python
def stop(self) -> None:
    """
    Stop WebSocket streaming and cleanup resources.

    Process:
        1. Set _running flag to False
        2. Close WebSocket client
        3. Log shutdown event

    Design Notes:
        - Synchronous method for simple shutdown
        - Does NOT flush buffers (caller responsibility)
        - Safe to call multiple times (idempotent)
    """
    if not self._running:
        return

    self.logger.info("Stopping data collector...")
    self._running = False

    if self.ws_client:
        try:
            self.ws_client.stop()
            self._is_connected = False
            self.logger.info("WebSocket client stopped")
        except Exception as e:
            self.logger.error(f"Error during WebSocket shutdown: {e}")

    self.logger.info("Data collector stopped successfully")
```

---

### 4.4 Buffer Management Methods

```python
def add_candle_to_buffer(self, candle: Candle) -> None:
    """
    Add candle to the appropriate buffer (symbol + interval).

    Args:
        candle: Candle object to buffer

    Design Notes:
        - Creates buffer on first access (lazy initialization)
        - Drops oldest candle if buffer full (FIFO)
        - Thread-safe via asyncio.Queue
    """
    buffer_key = f"{candle.symbol}_{candle.interval}"

    # Lazy buffer creation
    if buffer_key not in self._candle_buffers:
        self._candle_buffers[buffer_key] = asyncio.Queue(maxsize=self.buffer_size)

    buffer = self._candle_buffers[buffer_key]

    # Add to buffer (non-blocking check)
    if buffer.full():
        # Drop oldest candle (get without blocking)
        try:
            buffer.get_nowait()
        except asyncio.QueueEmpty:
            pass

    # Add new candle
    try:
        buffer.put_nowait(candle)
    except asyncio.QueueFull:
        self.logger.warning(f"Buffer overflow for {buffer_key}, dropping candle")


def get_candle_buffer(
    self,
    symbol: str,
    interval: str
) -> List[Candle]:
    """
    Retrieve all buffered candles for a symbol/interval.

    Args:
        symbol: Trading pair
        interval: Timeframe

    Returns:
        List of candles (oldest to newest), empty if no buffer

    Design Notes:
        - Non-destructive read (candles remain in buffer)
        - Returns copy to prevent external modification
    """
    buffer_key = f"{symbol.upper()}_{interval}"

    if buffer_key not in self._candle_buffers:
        return []

    buffer = self._candle_buffers[buffer_key]

    # Convert Queue to list (non-destructive)
    candles = list(buffer._queue)  # Access internal deque
    return candles.copy()
```

---

## 5. Private Implementation Methods

### 5.1 `_handle_kline_message()`

**Purpose**: WebSocket message callback for kline data parsing.

```python
def _handle_kline_message(self, message: dict) -> None:
    """
    Process incoming WebSocket kline message.

    Args:
        message: Raw WebSocket message dict

    Message Structure:
        {
            'e': 'kline',
            'E': 1638747660000,  # Event time
            's': 'BTCUSDT',      # Symbol
            'k': {
                's': 'BTCUSDT',
                'i': '1m',
                't': 1638747600000,  # Open time (ms)
                'T': 1638747659999,  # Close time (ms)
                'o': '57000.00',     # Open
                'h': '57100.00',     # High
                'l': '56900.00',     # Low
                'c': '57050.00',     # Close
                'v': '123.456',      # Volume
                'x': false           # Is closed
            }
        }

    Design Notes:
        - Validates message type before processing
        - Handles parsing errors gracefully (logs but doesn't crash)
        - Invokes callback asynchronously if configured
        - Adds to buffer automatically
    """
    try:
        # Validate message type
        if 'e' not in message or message['e'] != 'kline':
            self.logger.debug(f"Ignoring non-kline message: {message.get('e')}")
            return

        # Extract kline data
        kline = message['k']

        # Parse to Candle object
        candle = Candle(
            symbol=kline['s'],
            interval=kline['i'],
            open_time=datetime.fromtimestamp(kline['t'] / 1000),
            open=float(kline['o']),
            high=float(kline['h']),
            low=float(kline['l']),
            close=float(kline['c']),
            volume=float(kline['v']),
            close_time=datetime.fromtimestamp(kline['T'] / 1000),
            is_closed=kline['x']
        )

        # Add to buffer
        self.add_candle_to_buffer(candle)

        # Invoke callback if configured
        if self.on_candle_callback:
            try:
                self.on_candle_callback(candle)
            except Exception as callback_error:
                self.logger.error(
                    f"Callback error: {callback_error}",
                    exc_info=True
                )

    except KeyError as e:
        self.logger.error(f"Malformed kline message (missing key: {e}): {message}")
    except ValueError as e:
        self.logger.error(f"Invalid kline data (value error: {e}): {message}")
    except Exception as e:
        self.logger.error(
            f"Unexpected error in kline handler: {e}",
            exc_info=True
        )
```

**Error Handling Strategy**:
- `KeyError`: Missing required fields → log and skip
- `ValueError`: Invalid price/volume data → log and skip
- `Exception`: Candle validation errors (from `__post_init__`) → log and skip
- **Never crash the message handler** - data flow continues

---

### 5.2 `_parse_rest_kline()`

**Purpose**: Convert REST API kline array to Candle object.

```python
def _parse_rest_kline(
    self,
    kline: list,
    symbol: str,
    interval: str
) -> Candle:
    """
    Parse REST API kline array into Candle object.

    Args:
        kline: Array from Binance REST API
        symbol: Trading pair (for Candle creation)
        interval: Timeframe (for Candle creation)

    Returns:
        Candle object

    Array Indices:
        0: Open time (ms)
        1: Open (str)
        2: High (str)
        3: Low (str)
        4: Close (str)
        5: Volume (str)
        6: Close time (ms)
        11: Ignore
    """
    return Candle(
        symbol=symbol.upper(),
        interval=interval,
        open_time=datetime.fromtimestamp(kline[0] / 1000),
        open=float(kline[1]),
        high=float(kline[2]),
        low=float(kline[3]),
        close=float(kline[4]),
        volume=float(kline[5]),
        close_time=datetime.fromtimestamp(kline[6] / 1000),
        is_closed=True  # Historical candles are always closed
    )
```

---

### 5.3 Connection Health Callbacks

```python
def _handle_ws_error(self, error: Exception) -> None:
    """Log WebSocket errors."""
    self.logger.error(f"WebSocket error: {error}", exc_info=True)


def _handle_ws_close(self) -> None:
    """Handle WebSocket connection close."""
    self._is_connected = False
    self.logger.warning("WebSocket connection closed")
    # Note: binance-futures-connector handles auto-reconnection
```

---

## 6. Async Context Manager Support

```python
async def __aenter__(self) -> 'BinanceDataCollector':
    """Async context manager entry."""
    await self.start_streaming()
    return self


async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    """Async context manager exit."""
    self.stop()
```

**Usage Pattern**:
```python
async with BinanceDataCollector(...) as collector:
    # Streaming active
    candles = collector.get_historical_candles('BTCUSDT', '1h')
    # Auto-cleanup on exit
```

---

## 7. Integration Patterns

### 7.1 Event-Driven Architecture Integration

```python
# In main.py or event_handler.py
def on_candle_received(candle: Candle) -> None:
    """Callback invoked by BinanceDataCollector."""
    event = Event(
        event_type=EventType.CANDLE_UPDATE if not candle.is_closed
                   else EventType.CANDLE_CLOSED,
        data=candle
    )
    event_bus.publish(event, queue_name='data')

# Initialize collector
collector = BinanceDataCollector(
    api_key=config.api_key,
    api_secret=config.api_secret,
    symbols=['BTCUSDT'],
    intervals=['1h', '4h'],
    on_candle_callback=on_candle_received
)
```

### 7.2 Buffer Pre-Population Pattern

```python
async def initialize_with_history():
    """Pre-load buffers before streaming."""
    collector = BinanceDataCollector(...)

    # Fetch historical data
    for symbol in collector.symbols:
        for interval in collector.intervals:
            candles = collector.get_historical_candles(symbol, interval, limit=500)

            # Add to buffer
            for candle in candles:
                collector.add_candle_to_buffer(candle)

    # Start real-time streaming
    await collector.start_streaming()
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

**Test File**: `tests/core/test_data_collector.py`

```python
# Mock WebSocket message
MOCK_KLINE_MESSAGE = {
    'e': 'kline',
    'k': {
        's': 'BTCUSDT',
        'i': '1m',
        't': 1638747600000,
        'T': 1638747659999,
        'o': '57000.00',
        'h': '57100.00',
        'l': '56900.00',
        'c': '57050.00',
        'v': '123.456',
        'x': True
    }
}

@pytest.mark.asyncio
async def test_kline_message_parsing():
    """Test WebSocket message parsing to Candle."""
    collector = BinanceDataCollector(
        api_key='test',
        api_secret='test',
        symbols=['BTCUSDT'],
        intervals=['1m']
    )

    # Mock callback
    received_candles = []
    collector.on_candle_callback = lambda c: received_candles.append(c)

    # Process message
    collector._handle_kline_message(MOCK_KLINE_MESSAGE)

    # Assertions
    assert len(received_candles) == 1
    candle = received_candles[0]
    assert candle.symbol == 'BTCUSDT'
    assert candle.open == 57000.0
    assert candle.is_closed == True


def test_buffer_overflow():
    """Test buffer FIFO behavior when full."""
    collector = BinanceDataCollector(
        api_key='test',
        api_secret='test',
        symbols=['BTCUSDT'],
        intervals=['1m'],
        buffer_size=3  # Small buffer for testing
    )

    # Add 5 candles (buffer size 3)
    for i in range(5):
        candle = Candle(
            symbol='BTCUSDT',
            interval='1m',
            open_time=datetime.now(),
            open=50000.0 + i,
            high=50100.0 + i,
            low=49900.0 + i,
            close=50050.0 + i,
            volume=100.0,
            close_time=datetime.now(),
            is_closed=True
        )
        collector.add_candle_to_buffer(candle)

    # Should only have last 3 candles
    buffer = collector.get_candle_buffer('BTCUSDT', '1m')
    assert len(buffer) == 3
    assert buffer[0].open == 50002.0  # 3rd candle (oldest in buffer)
    assert buffer[-1].open == 50004.0  # 5th candle (newest)
```

### 8.2 Integration Tests (Testnet)

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_historical_candles_testnet():
    """Test REST API historical data fetch on testnet."""
    from dotenv import load_dotenv
    import os

    load_dotenv()

    collector = BinanceDataCollector(
        api_key=os.getenv('BINANCE_TESTNET_API_KEY'),
        api_secret=os.getenv('BINANCE_TESTNET_API_SECRET'),
        symbols=['BTCUSDT'],
        intervals=['1h'],
        is_testnet=True
    )

    # Fetch historical data
    candles = collector.get_historical_candles('BTCUSDT', '1h', limit=100)

    # Assertions
    assert len(candles) > 0
    assert len(candles) <= 100
    assert all(isinstance(c, Candle) for c in candles)
    assert all(c.symbol == 'BTCUSDT' for c in candles)
    assert all(c.is_closed for c in candles)  # Historical = closed


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_streaming_testnet():
    """Test WebSocket streaming on testnet (run for 30 seconds)."""
    from dotenv import load_dotenv
    import os

    load_dotenv()

    received_candles = []

    collector = BinanceDataCollector(
        api_key=os.getenv('BINANCE_TESTNET_API_KEY'),
        api_secret=os.getenv('BINANCE_TESTNET_API_SECRET'),
        symbols=['BTCUSDT'],
        intervals=['1m'],
        is_testnet=True,
        on_candle_callback=lambda c: received_candles.append(c)
    )

    # Start streaming
    await collector.start_streaming()

    # Wait for data
    await asyncio.sleep(30)

    # Stop
    collector.stop()

    # Assertions
    assert len(received_candles) > 0
    assert all(c.symbol == 'BTCUSDT' for c in received_candles)
```

---

## 9. Performance Considerations

### 9.1 Throughput

**Target**: Handle 100+ messages per second without lag

**Optimization Strategies**:
1. **Non-blocking Buffer Operations**: Use `put_nowait()` / `get_nowait()`
2. **Callback Isolation**: Wrap callback in try/except to prevent blocking
3. **Logging Levels**: Use DEBUG for verbose, INFO for important events
4. **Queue Sizing**: 500 candles = ~4KB memory per buffer (minimal)

### 9.2 Memory Management

**Per-Symbol-Interval Buffer**:
- 500 candles × ~80 bytes/candle = ~40KB per buffer
- 10 symbols × 3 intervals = 30 buffers × 40KB = **~1.2MB total**

**Scaling**: For 100 symbols × 5 intervals = 500 buffers = **~20MB** (acceptable)

---

## 10. Error Scenarios & Handling

| Error Type | Handling Strategy | Recovery |
|------------|-------------------|----------|
| **Network Failure** | Log error, library auto-reconnects | Automatic |
| **Malformed Message** | Log warning, skip message, continue | Skip & continue |
| **API Rate Limit** | Catch HTTPError, log, retry with backoff | Manual retry |
| **Invalid Credentials** | Raise exception during init | Fatal (user fix) |
| **Callback Exception** | Log error, continue processing | Continue streaming |
| **Buffer Overflow** | Drop oldest candle (FIFO), log warning | Automatic |

---

## 11. Implementation Checklist

- [ ] **Subtask 3.1**: Class skeleton with REST client init
- [ ] **Subtask 3.2**: WebSocket connection management
- [ ] **Subtask 3.3**: `_handle_kline_message()` implementation
- [ ] **Subtask 3.4**: `get_historical_candles()` method
- [ ] **Subtask 3.5**: Buffer management (add/get methods)
- [ ] **Subtask 3.6**: Lifecycle management (start/stop/context manager)
- [ ] **Unit Tests**: Message parsing, buffer overflow, error handling
- [ ] **Integration Tests**: Testnet streaming, historical data fetch
- [ ] **Documentation**: Docstrings, inline comments, examples

---

## 12. Next Steps for Implementation

### Phase 1: Foundation (Subtask 3.1)
1. Create class skeleton in `src/core/data_collector.py`
2. Implement `__init__()` with REST client
3. Define constants and type hints
4. Write unit tests for initialization

### Phase 2: WebSocket Streaming (Subtasks 3.2-3.3)
1. Implement `start_streaming()` async method
2. Implement `_handle_kline_message()` parsing
3. Add WebSocket error/close callbacks
4. Test with mock WebSocket messages

### Phase 3: Historical Data (Subtask 3.4)
1. Implement `get_historical_candles()`
2. Implement `_parse_rest_kline()` helper
3. Add error handling for API calls
4. Integration test on testnet

### Phase 4: Buffer Management (Subtask 3.5)
1. Implement `add_candle_to_buffer()`
2. Implement `get_candle_buffer()`
3. Test buffer overflow (FIFO)
4. Verify thread safety with concurrent access

### Phase 5: Lifecycle & Cleanup (Subtask 3.6)
1. Implement `stop()` method
2. Add async context manager support
3. Implement connection health callbacks
4. Final integration testing

---

## 13. Dependencies & Integration Points

### Upstream Dependencies (Must Be Complete)
- ✅ **Task #1**: Project structure, requirements.txt with `binance-futures-connector>=4.1.0`
- ✅ **Task #2**: `Candle` dataclass in `src/models/candle.py`

### Downstream Consumers (Blocked Until Complete)
- ⏳ **Task #4**: Event-driven architecture needs `on_candle_callback` integration
- ⏳ **Task #5**: Mock strategy consumes candle buffers for analysis

### Integration Code Example
```python
# In src/main.py (future)
from src.core.data_collector import BinanceDataCollector
from src.core.event_handler import EventBus
from src.models.event import Event, EventType

def on_candle(candle: Candle):
    event = Event(
        event_type=EventType.CANDLE_CLOSED if candle.is_closed else EventType.CANDLE_UPDATE,
        data=candle
    )
    event_bus.publish(event, queue_name='data')

collector = BinanceDataCollector(
    api_key=config.api_key,
    api_secret=config.api_secret,
    symbols=['BTCUSDT'],
    intervals=['1h', '4h'],
    on_candle_callback=on_candle,
    is_testnet=True
)

await collector.start_streaming()
```

---

**Design Status**: ✅ Complete - Ready for Implementation
**Estimated Implementation Time**: 8-12 hours (with testing)
**Risk Level**: Low (well-defined interfaces, library handles reconnection)
