# Task 3.5: Candle Buffer Management - Design Specification

**Status**: 📐 Design Phase
**Date**: 2025-12-10
**Type**: Pre-Implementation Design
**Complexity**: Medium-High

---

## 📋 Purpose

Implement **thread-safe candle buffer storage** using `asyncio.Queue` to maintain recent candles for each symbol/interval pair, enabling efficient access to historical data without repeated API calls.

---

## 🎯 Requirements

### Functional Requirements

1. **Buffer Storage Management**
   - Store candles per symbol/interval pair
   - Maintain configurable buffer size (default: 500 candles)
   - Automatic FIFO overflow handling (remove oldest when full)
   - Thread-safe concurrent access

2. **Buffer Operations**
   - Add candle to appropriate buffer
   - Retrieve all candles from buffer (non-destructive read)
   - Pre-populate buffer from historical data
   - Auto-buffer real-time candles from WebSocket

3. **Integration Points**
   - Integrate with `_handle_kline_message()` for real-time buffering
   - Integrate with `get_historical_candles()` for initial population
   - Provide clean API for external buffer access

### Non-Functional Requirements

- **Thread Safety**: `asyncio.Queue` ensures safe concurrent operations
- **Memory Efficiency**: Bounded buffer size prevents unbounded growth
- **Performance**: O(1) add operations, O(n) retrieval (where n = buffer size)
- **Maintainability**: Clear separation of concerns, well-documented code

---

## 🏗️ Architecture

### Data Structure Design

```python
# Class attribute (already exists in __init__)
_candle_buffers: Dict[str, asyncio.Queue]
```

**Key Design**:
- Format: `"{SYMBOL}_{INTERVAL}"` (e.g., `"BTCUSDT_1m"`)
- Normalization: Symbol always uppercase
- Example keys: `"BTCUSDT_1m"`, `"ETHUSDT_5m"`, `"BNBUSDT_1h"`

**Value**: `asyncio.Queue[Candle]`
- Max size: `self.buffer_size` (default: 500)
- FIFO semantics: Oldest candle removed first on overflow
- Thread-safe: Built-in locking for concurrent access

### Buffer State Diagram

```
┌─────────────────────────────────────────────────────────┐
│  BinanceDataCollector                                   │
├─────────────────────────────────────────────────────────┤
│  _candle_buffers: Dict[str, asyncio.Queue]              │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ "BTCUSDT_1m" │  │ "BTCUSDT_5m" │  │ "ETHUSDT_1m" │ │
│  │   Queue(500) │  │   Queue(500) │  │   Queue(500) │ │
│  │              │  │              │  │              │ │
│  │  [Candle]    │  │  [Candle]    │  │  [Candle]    │ │
│  │  [Candle]    │  │  [Candle]    │  │  [Candle]    │ │
│  │    ...       │  │    ...       │  │    ...       │ │
│  │  [Candle]    │  │  [Candle]    │  │  [Candle]    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## 📐 API Specification

### 1. Helper Method: `_get_buffer_key()`

```python
def _get_buffer_key(self, symbol: str, interval: str) -> str:
    """
    Generate standardized buffer key for symbol/interval pair.

    Args:
        symbol: Trading pair (e.g., "BTCUSDT", "btcusdt")
        interval: Timeframe (e.g., "1m", "5m", "1h")

    Returns:
        Standardized key: "{SYMBOL}_{INTERVAL}" (e.g., "BTCUSDT_1m")

    Note:
        - Symbol is automatically normalized to uppercase
        - Interval is used as-is (already validated by Binance API)

    Example:
        >>> self._get_buffer_key("btcusdt", "1m")
        "BTCUSDT_1m"
    """
```

**Implementation Strategy**:
```python
return f"{symbol.upper()}_{interval}"
```

---

### 2. Core Method: `add_candle_to_buffer()`

```python
def add_candle_to_buffer(self, candle: Candle) -> None:
    """
    Add candle to appropriate buffer with automatic overflow handling.

    Args:
        candle: Candle object to buffer

    Behavior:
        1. Generate buffer key from candle.symbol and candle.interval
        2. Create new queue if buffer doesn't exist for this pair
        3. If buffer is full (size >= self.buffer_size):
           - Remove oldest candle (FIFO)
           - Add new candle
        4. If buffer has space:
           - Add new candle directly
        5. Log buffer operation for debugging

    Thread Safety:
        - asyncio.Queue handles concurrent access safely
        - No explicit locking required

    Error Handling:
        - Logs errors but does not raise exceptions
        - Prevents buffer operation failures from stopping WebSocket

    Example:
        >>> candle = Candle(symbol="BTCUSDT", interval="1m", ...)
        >>> collector.add_candle_to_buffer(candle)
        # Candle added to _candle_buffers["BTCUSDT_1m"]
    """
```

**Implementation Logic**:
1. Get buffer key: `key = self._get_buffer_key(candle.symbol, candle.interval)`
2. Initialize buffer if needed:
   ```python
   if key not in self._candle_buffers:
       self._candle_buffers[key] = asyncio.Queue(maxsize=self.buffer_size)
   ```
3. Handle overflow:
   ```python
   if self._candle_buffers[key].full():
       try:
           self._candle_buffers[key].get_nowait()  # Remove oldest
       except asyncio.QueueEmpty:
           pass  # Shouldn't happen, but handle safely
   ```
4. Add candle:
   ```python
   try:
       self._candle_buffers[key].put_nowait(candle)
   except asyncio.QueueFull:
       self.logger.error(f"Buffer full for {key}, candle dropped")
   ```

---

### 3. Retrieval Method: `get_candle_buffer()`

```python
def get_candle_buffer(self, symbol: str, interval: str) -> List[Candle]:
    """
    Retrieve all candles from buffer without removing them.

    Args:
        symbol: Trading pair (e.g., "BTCUSDT")
        interval: Timeframe (e.g., "1m", "5m")

    Returns:
        List of candles sorted by open_time (oldest to newest)
        Empty list if buffer doesn't exist or is empty

    Behavior:
        1. Generate buffer key
        2. If buffer doesn't exist → return []
        3. If buffer exists but empty → return []
        4. Extract all candles (non-destructive)
        5. Sort by open_time ascending
        6. Return as List[Candle]

    Non-Destructive Read:
        - Candles remain in queue after retrieval
        - Uses temporary list to preserve queue contents

    Thread Safety:
        - Safe for concurrent reads/writes
        - Queue state remains consistent

    Example:
        >>> candles = collector.get_candle_buffer("BTCUSDT", "1m")
        >>> print(f"Retrieved {len(candles)} candles")
        Retrieved 350 candles
    """
```

**Implementation Strategy**:
```python
key = self._get_buffer_key(symbol, interval)

# Return empty if buffer doesn't exist
if key not in self._candle_buffers:
    return []

queue = self._candle_buffers[key]

# Return empty if queue is empty
if queue.empty():
    return []

# Extract all candles without removing
candles = []
temp_storage = []

# Drain queue into temporary storage
try:
    while not queue.empty():
        candle = queue.get_nowait()
        candles.append(candle)
        temp_storage.append(candle)
except asyncio.QueueEmpty:
    pass

# Restore queue contents
for candle in temp_storage:
    try:
        queue.put_nowait(candle)
    except asyncio.QueueFull:
        self.logger.warning(f"Queue full during restore for {key}")

# Sort by open_time and return
return sorted(candles, key=lambda c: c.open_time)
```

**Alternative Implementation** (More Efficient):
```python
# Use internal queue's _queue deque (Python implementation detail)
# Warning: This accesses private attribute, less portable
if hasattr(queue, '_queue'):
    candles = list(queue._queue)
    return sorted(candles, key=lambda c: c.open_time)
```

**Recommended**: Use the safer drain-and-restore approach for production.

---

## 🔗 Integration Points

### Integration 1: WebSocket → Buffer

**Location**: `_handle_kline_message()` (src/core/data_collector.py:144-232)

**Modification**:
```python
def _handle_kline_message(self, message: Dict) -> None:
    """Handle incoming kline WebSocket messages."""
    try:
        # ... existing parsing code ...

        candle = Candle(
            symbol=kline['s'],
            interval=kline['i'],
            # ... all fields ...
        )

        # NEW: Add candle to buffer
        self.add_candle_to_buffer(candle)

        # Invoke user callback if configured
        if self.on_candle_callback:
            self.on_candle_callback(candle)

        # ... existing logging code ...
```

**Impact**: Every WebSocket candle automatically buffered.

---

### Integration 2: Historical Data → Buffer Pre-population

**Location**: `get_historical_candles()` (src/core/data_collector.py:303-424)

**Modification**:
```python
def get_historical_candles(
    self,
    symbol: str,
    interval: str,
    limit: int = 500
) -> List[Candle]:
    """Fetch historical kline data via Binance REST API."""
    # ... existing implementation ...

    try:
        klines_data = self.rest_client.klines(...)
        candles = []

        for kline_array in klines_data:
            candle = self._parse_rest_kline(kline_array)
            candle.symbol = symbol
            candle.interval = interval
            candles.append(candle)

            # NEW: Pre-populate buffer with historical candles
            self.add_candle_to_buffer(candle)

        # ... existing logging and return ...
```

**Impact**: Buffer pre-populated before WebSocket starts, providing immediate historical context.

---

## 🧪 Test Strategy

### Unit Tests

#### Test Suite 1: Buffer Key Generation
```python
def test_get_buffer_key_uppercase_normalization():
    """Verify symbol is normalized to uppercase"""
    collector = BinanceDataCollector(...)
    assert collector._get_buffer_key("btcusdt", "1m") == "BTCUSDT_1m"
    assert collector._get_buffer_key("ETHUSDT", "5m") == "ETHUSDT_5m"

def test_get_buffer_key_format():
    """Verify key format is consistent"""
    collector = BinanceDataCollector(...)
    key = collector._get_buffer_key("BTCUSDT", "1m")
    assert key == "BTCUSDT_1m"
    assert "_" in key
```

#### Test Suite 2: Add Candle to Buffer
```python
def test_add_candle_creates_buffer_if_not_exists():
    """Verify buffer is created on first add"""
    collector = BinanceDataCollector(...)
    candle = Candle(symbol="BTCUSDT", interval="1m", ...)

    assert "BTCUSDT_1m" not in collector._candle_buffers
    collector.add_candle_to_buffer(candle)
    assert "BTCUSDT_1m" in collector._candle_buffers

def test_add_candle_multiple_to_same_buffer():
    """Verify multiple candles accumulate in buffer"""
    collector = BinanceDataCollector(...)

    for i in range(10):
        candle = Candle(symbol="BTCUSDT", interval="1m", ...)
        collector.add_candle_to_buffer(candle)

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert len(buffer) == 10

def test_add_candle_overflow_removes_oldest():
    """Verify FIFO behavior on buffer overflow"""
    collector = BinanceDataCollector(..., buffer_size=3)

    candle1 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 0), ...)
    candle2 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 1), ...)
    candle3 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 2), ...)
    candle4 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 3), ...)

    collector.add_candle_to_buffer(candle1)
    collector.add_candle_to_buffer(candle2)
    collector.add_candle_to_buffer(candle3)
    collector.add_candle_to_buffer(candle4)  # Should remove candle1

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert len(buffer) == 3
    assert buffer[0] == candle2  # candle1 removed
    assert buffer[2] == candle4

def test_add_candle_separate_buffers_per_pair():
    """Verify different symbol/interval pairs use separate buffers"""
    collector = BinanceDataCollector(...)

    candle1 = Candle(symbol="BTCUSDT", interval="1m", ...)
    candle2 = Candle(symbol="BTCUSDT", interval="5m", ...)
    candle3 = Candle(symbol="ETHUSDT", interval="1m", ...)

    collector.add_candle_to_buffer(candle1)
    collector.add_candle_to_buffer(candle2)
    collector.add_candle_to_buffer(candle3)

    assert len(collector._candle_buffers) == 3
    assert "BTCUSDT_1m" in collector._candle_buffers
    assert "BTCUSDT_5m" in collector._candle_buffers
    assert "ETHUSDT_1m" in collector._candle_buffers
```

#### Test Suite 3: Get Candle Buffer
```python
def test_get_candle_buffer_nonexistent_returns_empty():
    """Verify empty list returned for non-existent buffer"""
    collector = BinanceDataCollector(...)
    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert buffer == []

def test_get_candle_buffer_empty_buffer_returns_empty():
    """Verify empty list returned for empty buffer"""
    collector = BinanceDataCollector(...)
    # Create empty buffer
    collector._candle_buffers["BTCUSDT_1m"] = asyncio.Queue(maxsize=500)

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert buffer == []

def test_get_candle_buffer_returns_sorted_by_time():
    """Verify candles are sorted by open_time"""
    collector = BinanceDataCollector(...)

    # Add candles in reverse order
    candle3 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 2), ...)
    candle1 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 0), ...)
    candle2 = Candle(symbol="BTCUSDT", interval="1m", open_time=datetime(2025, 1, 1, 0, 1), ...)

    collector.add_candle_to_buffer(candle3)
    collector.add_candle_to_buffer(candle1)
    collector.add_candle_to_buffer(candle2)

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert buffer[0].open_time < buffer[1].open_time < buffer[2].open_time

def test_get_candle_buffer_nondestructive_read():
    """Verify candles remain in buffer after retrieval"""
    collector = BinanceDataCollector(...)

    candle = Candle(symbol="BTCUSDT", interval="1m", ...)
    collector.add_candle_to_buffer(candle)

    buffer1 = collector.get_candle_buffer("BTCUSDT", "1m")
    buffer2 = collector.get_candle_buffer("BTCUSDT", "1m")

    assert len(buffer1) == 1
    assert len(buffer2) == 1  # Still there
    assert buffer1[0] == buffer2[0]
```

#### Test Suite 4: Thread Safety
```python
def test_concurrent_adds_to_same_buffer():
    """Verify thread-safe concurrent adds"""
    collector = BinanceDataCollector(...)

    async def add_candles():
        for i in range(100):
            candle = Candle(symbol="BTCUSDT", interval="1m", ...)
            collector.add_candle_to_buffer(candle)

    # Run multiple concurrent adds
    await asyncio.gather(*[add_candles() for _ in range(10)])

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert len(buffer) <= collector.buffer_size  # No corruption

def test_concurrent_add_and_read():
    """Verify safe concurrent add and read operations"""
    collector = BinanceDataCollector(...)

    async def add_candles():
        for i in range(50):
            candle = Candle(symbol="BTCUSDT", interval="1m", ...)
            collector.add_candle_to_buffer(candle)
            await asyncio.sleep(0.001)

    async def read_buffer():
        for i in range(50):
            buffer = collector.get_candle_buffer("BTCUSDT", "1m")
            await asyncio.sleep(0.001)

    # Run concurrent add and read
    await asyncio.gather(add_candles(), read_buffer())

    # Verify no crashes, data consistent
    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert len(buffer) > 0
```

#### Test Suite 5: Integration Tests
```python
def test_websocket_integration_auto_buffers():
    """Verify WebSocket candles are automatically buffered"""
    collector = BinanceDataCollector(...)

    # Simulate WebSocket message
    message = {
        'e': 'kline',
        'k': {
            's': 'BTCUSDT',
            'i': '1m',
            't': 1609459200000,  # 2021-01-01 00:00:00
            # ... all required fields ...
        }
    }

    collector._handle_kline_message(message)

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert len(buffer) == 1

def test_historical_data_prepopulates_buffer():
    """Verify historical data pre-populates buffer"""
    collector = BinanceDataCollector(...)

    # Mock REST API response
    with patch.object(collector.rest_client, 'klines', return_value=[...]):
        candles = collector.get_historical_candles("BTCUSDT", "1m", limit=100)

    buffer = collector.get_candle_buffer("BTCUSDT", "1m")
    assert len(buffer) == 100
    assert buffer == candles  # Same candles
```

---

## ⚙️ Implementation Checklist

### Phase 1: Core Methods
- [ ] Implement `_get_buffer_key(symbol, interval) -> str`
- [ ] Implement `add_candle_to_buffer(candle)`
  - [ ] Buffer creation logic
  - [ ] Overflow handling (FIFO)
  - [ ] Error handling and logging
- [ ] Implement `get_candle_buffer(symbol, interval) -> List[Candle]`
  - [ ] Non-destructive read
  - [ ] Sorting by open_time
  - [ ] Empty buffer handling

### Phase 2: Integration
- [ ] Modify `_handle_kline_message()` to call `add_candle_to_buffer()`
- [ ] Modify `get_historical_candles()` to pre-populate buffer
- [ ] Verify `__init__` already has `_candle_buffers` initialization

### Phase 3: Testing
- [ ] Write 3 tests for `_get_buffer_key()`
- [ ] Write 5 tests for `add_candle_to_buffer()`
- [ ] Write 5 tests for `get_candle_buffer()`
- [ ] Write 2 thread safety tests
- [ ] Write 2 integration tests
- [ ] Verify all 17 tests pass

### Phase 4: Documentation
- [ ] Add docstrings to all new methods
- [ ] Update class docstring with buffer information
- [ ] Add inline comments for complex logic

---

## 📊 Performance Analysis

### Memory Footprint
```python
# Per Candle: ~200 bytes (8 fields, mostly floats and datetimes)
# Buffer size: 500 candles × 200 bytes = 100 KB per buffer

# Example: 5 symbols × 4 intervals = 20 buffers
# Total memory: 20 × 100 KB = 2 MB (negligible)
```

### Time Complexity
- **Add candle**: O(1) - Direct queue put
- **Get buffer**: O(n) - Drain/restore queue + sort (n = buffer size)
- **Overflow removal**: O(1) - Queue get

### Optimization Opportunities
1. **Faster Retrieval**: Use `queue._queue` deque access (less portable)
2. **Lazy Sorting**: Only sort when user requests specific order
3. **Buffer Snapshots**: Cache sorted list, invalidate on add

---

## 🔧 Design Decisions & Trade-offs

### Decision 1: `asyncio.Queue` vs `collections.deque`
**Chosen**: `asyncio.Queue`

**Rationale**:
- ✅ Built-in thread safety for async code
- ✅ Async-friendly (put/get with await)
- ✅ Bounded size with `maxsize` parameter
- ❌ Slower than raw `deque` (locking overhead)

**Alternative**: `collections.deque`
- ✅ Faster raw performance
- ❌ No thread safety (need manual locking)
- ❌ No async support

**Conclusion**: Thread safety > raw speed for this use case.

---

### Decision 2: Non-Destructive Read vs Destructive Pop
**Chosen**: Non-destructive read

**Rationale**:
- ✅ Multiple consumers can access same data
- ✅ Simpler buffer lifecycle (no need to repopulate)
- ✅ WebSocket and user queries don't interfere
- ❌ Slightly slower (drain/restore overhead)

**Alternative**: Destructive pop
- ✅ Faster (single get operation)
- ❌ Buffer emptied after read
- ❌ Requires repopulation logic

**Conclusion**: Non-destructive read provides better UX.

---

### Decision 3: Buffer Size Default (500 candles)
**Chosen**: 500 candles

**Rationale**:
- 1m interval: ~8.3 hours of data
- 5m interval: ~41.7 hours of data
- 1h interval: ~20.8 days of data
- Balances memory usage (~100KB per buffer) vs data availability

**Configurable**: User can override via `buffer_size` parameter in constructor.

---

## 🚨 Edge Cases & Error Handling

### Edge Case 1: Buffer Doesn't Exist
**Scenario**: User calls `get_candle_buffer()` for never-seen symbol/interval

**Handling**: Return empty list `[]`

**Logging**: Info-level log (not an error)

---

### Edge Case 2: Queue Full During Add
**Scenario**: Concurrent adds cause queue to fill despite overflow check

**Handling**: Catch `asyncio.QueueFull`, log error, drop candle

**Impact**: Graceful degradation, doesn't crash WebSocket

---

### Edge Case 3: Empty Queue During Drain
**Scenario**: Queue emptied between empty check and drain

**Handling**: Catch `asyncio.QueueEmpty`, return accumulated candles

**Impact**: Partial data returned (better than crash)

---

## 🔗 Dependencies

### Requires
- ✅ **Task 3.1**: `BinanceDataCollector.__init__()` (buffer dict initialization)
- ✅ **Task 3.3**: `_handle_kline_message()` (WebSocket integration)
- ✅ **Task 3.4**: `get_historical_candles()` (pre-population)

### Blocks
- ⏳ **Task 3.6**: Lifecycle management (buffer cleanup on shutdown)

---

## 📝 Implementation Notes

### Existing Code Review

**Current `__init__` (src/core/data_collector.py:59-131)**:
```python
# Line 105-107 (already implemented!)
# Initialize candle buffers (lazy initialization per symbol/interval)
# Key format: '{SYMBOL}_{INTERVAL}' -> asyncio.Queue
self._candle_buffers: Dict[str, asyncio.Queue] = {}
```
✅ Buffer dict already exists in constructor!

**Current `_handle_kline_message` (src/core/data_collector.py:144-232)**:
- Parses WebSocket message into `Candle` object (line 189-199)
- Invokes user callback (line 201-202)
- ✅ Ready for buffer integration after line 199

**Current `get_historical_candles` (src/core/data_collector.py:303-424)**:
- Fetches REST API data (line 332)
- Parses into `Candle` objects (line 334-341)
- ✅ Ready for buffer integration in loop (line 337-341)

---

## ✅ Success Criteria

- [ ] All 17 unit tests pass (100% coverage)
- [ ] Integration tests verify WebSocket → buffer flow
- [ ] Integration tests verify historical data pre-population
- [ ] Thread safety tests pass with concurrent operations
- [ ] Buffer overflow correctly removes oldest candles
- [ ] Non-destructive reads preserve buffer contents
- [ ] Separate buffers maintained per symbol/interval pair
- [ ] Code follows project conventions (type hints, docstrings)
- [ ] No performance regressions in WebSocket handling

---

**Status**: 📐 **Design Complete - Ready for Implementation**
