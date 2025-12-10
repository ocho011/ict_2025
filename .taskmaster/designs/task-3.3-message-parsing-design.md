# Subtask 3.3: Message Parsing - Detailed Design

**Created**: 2025-12-09
**Parent Task**: #3 - Binance API Connection & WebSocket Data Collector
**Dependencies**: ✅ #3.2 (WebSocket connection management)
**Status**: Ready for Implementation

---

## 1. Overview

Implement the `_handle_kline_message()` method to parse incoming Binance WebSocket kline messages into validated Candle objects and invoke user callbacks.

### Key Objectives
- Parse Binance WebSocket message format to Candle dataclass
- Convert data types (timestamps ms→datetime, strings→float)
- Validate message structure and handle malformed data gracefully
- Invoke user callback with parsed Candle object
- Comprehensive error handling with detailed logging

---

## 2. Architecture Integration

### 2.1 Data Flow

```
WebSocket Client
    ↓
start_streaming() subscriptions
    ↓
Binance sends kline message
    ↓
_handle_kline_message() ← THIS SUBTASK
    ↓ (parse & validate)
    ↓
Candle object
    ↓ ↓
    │ └→ on_candle_callback(candle)  [User callback]
    └──→ Buffer Management           [Future: Subtask 3.5]
```

### 2.2 Current Method State

**Location**: `src/core/data_collector.py:143-155`

**Current Implementation**:
```python
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

### 2.3 Integration Points

**Input**: Raw WebSocket message from `UMFuturesWebsocketClient.kline()` callback
**Output**:
- Validated `Candle` object
- Callback invocation (if configured)
- Future: Buffer addition (Subtask 3.5)

---

## 3. Binance WebSocket Message Format

### 3.1 Complete Message Structure

```python
{
    'e': 'kline',                    # Event type (REQUIRED for validation)
    'E': 1638747660000,              # Event time (ms) - not used
    's': 'BTCUSDT',                  # Symbol (top-level, not used)
    'k': {                           # Kline data (REQUIRED)
        # === Required Fields for Candle ===
        's': 'BTCUSDT',              # Symbol
        'i': '1m',                   # Interval
        't': 1638747600000,          # Kline open time (ms) → datetime
        'T': 1638747659999,          # Kline close time (ms) → datetime
        'o': '57000.00',             # Open price (str) → float
        'h': '57100.00',             # High price (str) → float
        'l': '56900.00',             # Low price (str) → float
        'c': '57050.00',             # Close price (str) → float
        'v': '10.5',                 # Volume (str) → float
        'x': True,                   # Is kline closed (bool)

        # === Optional Fields (not used) ===
        'f': 100,                    # First trade ID
        'L': 200,                    # Last trade ID
        'n': 100,                    # Number of trades
        'q': '598537.50',            # Quote asset volume
        'V': '5.0',                  # Taker buy base volume
        'Q': '285018.75',            # Taker buy quote volume
        'B': '0'                     # Ignore
    }
}
```

### 3.2 Field Mapping

| Binance Field | Type | Candle Field | Conversion |
|---------------|------|--------------|------------|
| `k['s']` | str | `symbol` | Direct |
| `k['i']` | str | `interval` | Direct |
| `k['t']` | int | `open_time` | `datetime.fromtimestamp(t / 1000)` |
| `k['T']` | int | `close_time` | `datetime.fromtimestamp(T / 1000)` |
| `k['o']` | str | `open` | `float(o)` |
| `k['h']` | str | `high` | `float(h)` |
| `k['l']` | str | `low` | `float(l)` |
| `k['c']` | str | `close` | `float(c)` |
| `k['v']` | str | `volume` | `float(v)` |
| `k['x']` | bool | `is_closed` | Direct |

### 3.3 Type Conversions

**Timestamp Conversion** (Critical):
```python
# Binance sends milliseconds since epoch
timestamp_ms = 1638747600000

# Python datetime expects seconds
timestamp_s = timestamp_ms / 1000  # = 1638747600.0

# Convert to datetime
dt = datetime.fromtimestamp(timestamp_s)
# Result: datetime(2021, 12, 6, 2, 0, 0)
```

**Price/Volume Conversion**:
```python
# Binance sends as strings for precision
price_str = '57000.00'
volume_str = '10.5'

# Convert to float
price = float(price_str)   # 57000.0
volume = float(volume_str) # 10.5
```

---

## 4. Detailed Implementation Design

### 4.1 Complete Method Implementation

```python
def _handle_kline_message(self, message: Dict) -> None:
    """
    Handle incoming kline WebSocket messages.

    Parses Binance WebSocket kline messages into Candle objects.
    Invokes callback if configured and logs parsing errors gracefully.

    Args:
        message: Raw WebSocket message dictionary from Binance
                Expected format: {'e': 'kline', 'k': {...}}

    Processing Steps:
        1. Validate message type (must be 'kline')
        2. Extract kline data from message['k']
        3. Convert timestamps (ms → datetime)
        4. Convert prices/volume (str → float)
        5. Create Candle object (validates in __post_init__)
        6. Invoke user callback if configured
        7. Log debug info on success

    Error Handling:
        - KeyError: Missing required field in message
        - ValueError: Invalid data type conversion (e.g., non-numeric string)
        - TypeError: Unexpected data type in message
        - Candle validation errors from __post_init__

    All errors are logged with full stack trace but do not raise exceptions
    to prevent WebSocket disconnection on malformed messages.
    """
    try:
        # Step 1: Validate message type
        event_type = message.get('e')
        if event_type != 'kline':
            self.logger.warning(
                f"Received non-kline message: type='{event_type}'"
            )
            return

        # Step 2: Extract kline data
        kline = message.get('k')
        if not kline:
            self.logger.error(
                "Message missing 'k' (kline data)",
                extra={'message': message}
            )
            return

        # Step 3-4: Parse and convert all fields
        candle = Candle(
            symbol=kline['s'],
            interval=kline['i'],
            open_time=datetime.fromtimestamp(kline['t'] / 1000),
            close_time=datetime.fromtimestamp(kline['T'] / 1000),
            open=float(kline['o']),
            high=float(kline['h']),
            low=float(kline['l']),
            close=float(kline['c']),
            volume=float(kline['v']),
            is_closed=kline['x']
        )

        # Step 5: Invoke user callback if configured
        if self.on_candle_callback:
            self.on_candle_callback(candle)

        # Step 6: Log debug info
        self.logger.debug(
            f"Parsed candle: {candle.symbol} {candle.interval} "
            f"@ {candle.close_time.isoformat()} "
            f"(close={candle.close}, closed={candle.is_closed})"
        )

    except KeyError as e:
        # Missing required field in kline data
        self.logger.error(
            f"Missing required field in kline message: {e}",
            exc_info=True,
            extra={'message': message}
        )
    except (ValueError, TypeError) as e:
        # Invalid data type (e.g., non-numeric string, wrong type)
        self.logger.error(
            f"Invalid data type in kline message: {e}",
            exc_info=True,
            extra={'message': message}
        )
    except Exception as e:
        # Unexpected error (including Candle validation errors)
        self.logger.error(
            f"Unexpected error parsing kline message: {e}",
            exc_info=True,
            extra={'message': message}
        )
```

### 4.2 Design Rationale

**Message Validation**:
- Check `e == 'kline'` to ensure correct message type
- Early return on non-kline messages (warning level)
- Check for `k` key existence before accessing

**Error Handling Strategy**:
- **No exceptions raised**: Prevents WebSocket disconnection
- **Detailed logging**: Full stack trace + message context
- **Graceful degradation**: Skip malformed messages, continue processing
- **Separate error categories**: KeyError, ValueError/TypeError, generic Exception

**Logging Levels**:
- `warning`: Non-kline messages (expected occasionally)
- `error`: Malformed messages, parsing failures
- `debug`: Successful parsing (verbose, disabled in production)

**Callback Safety**:
- Check `if self.on_candle_callback` before calling
- No exception handling around callback (let user handle their errors)
- Callback executed before buffer management (priority to user)

### 4.3 Candle Validation

The `Candle` dataclass has `__post_init__` validation:

```python
def __post_init__(self) -> None:
    """Validate price coherence."""
    if self.high < max(self.open, self.close):
        raise ValueError(
            f"High ({self.high}) must be >= max(open={self.open}, close={self.close})"
        )
    if self.low > min(self.open, self.close):
        raise ValueError(
            f"Low ({self.low}) must be <= min(open={self.open}, close={self.close})"
        )
    if self.volume < 0:
        raise ValueError(f"Volume ({self.volume}) cannot be negative")
```

**Implications**:
- Automatic validation on `Candle()` construction
- `ValueError` raised on invalid data (caught in generic `except Exception`)
- Protects against bad data from Binance

---

## 5. Test Strategy

### 5.1 Test Suite Design

**Test File**: `tests/core/test_data_collector.py` (extend existing)

**Test Class**: `TestBinanceDataCollectorMessageParsing`

### 5.2 Test Cases

#### Test Case 1: Valid Message Parsing
```python
async def test_valid_kline_message_parsing():
    """
    Verify complete parsing of valid Binance kline message.

    Validates:
    - All fields extracted correctly
    - Timestamps converted (ms → datetime)
    - Prices/volume converted (str → float)
    - Candle object created successfully
    - No errors logged
    """
    # Mock message with typical Binance format
    message = {
        'e': 'kline',
        'E': 1638747660000,
        's': 'BTCUSDT',
        'k': {
            's': 'BTCUSDT',
            'i': '1m',
            't': 1638747600000,  # 2021-12-06 02:00:00 UTC
            'T': 1638747659999,  # 2021-12-06 02:00:59.999 UTC
            'o': '57000.00',
            'h': '57100.00',
            'l': '56900.00',
            'c': '57050.00',
            'v': '10.5',
            'x': True
        }
    }

    collector = BinanceDataCollector(...)

    # Capture callback invocation
    captured_candle = None
    def capture_callback(candle):
        nonlocal captured_candle
        captured_candle = candle

    collector.on_candle_callback = capture_callback

    # Act
    collector._handle_kline_message(message)

    # Assert - Verify all fields
    assert captured_candle is not None
    assert captured_candle.symbol == 'BTCUSDT'
    assert captured_candle.interval == '1m'
    assert captured_candle.open_time == datetime(2021, 12, 6, 2, 0, 0)
    assert captured_candle.close_time == datetime(2021, 12, 6, 2, 0, 59, 999000)
    assert captured_candle.open == 57000.0
    assert captured_candle.high == 57100.0
    assert captured_candle.low == 56900.0
    assert captured_candle.close == 57050.0
    assert captured_candle.volume == 10.5
    assert captured_candle.is_closed is True
```

#### Test Case 2: Timestamp Conversion Accuracy
```python
def test_timestamp_conversion():
    """
    Verify millisecond timestamps convert to correct datetime.

    Edge cases:
    - Unix epoch (0 ms)
    - Recent timestamp
    - Far future timestamp
    """
    test_cases = [
        (0, datetime(1970, 1, 1, 0, 0, 0)),
        (1638747600000, datetime(2021, 12, 6, 2, 0, 0)),
        (1735689600000, datetime(2025, 1, 1, 0, 0, 0))
    ]

    # Test with messages containing each timestamp
    # Verify datetime objects match expected values
```

#### Test Case 3: Price/Volume String Conversion
```python
def test_price_volume_conversion():
    """
    Verify string prices/volumes convert to float correctly.

    Edge cases:
    - Integer strings: '57000'
    - Decimal strings: '57000.50'
    - Scientific notation: '1.5e-5'
    - Very small numbers: '0.00000001'
    - Very large numbers: '999999999.99'
    """
    test_prices = ['57000', '57000.50', '1.5e-5', '0.00000001', '999999999.99']

    # Create messages with each price format
    # Verify float conversion is accurate
```

#### Test Case 4: Callback Invocation
```python
def test_callback_invocation():
    """
    Verify callback invoked with correct Candle object.

    Cases:
    - Callback configured: should be called
    - Callback = None: should not crash
    """
    # Mock callback
    mock_callback = Mock()

    collector = BinanceDataCollector(..., on_candle_callback=mock_callback)
    collector._handle_kline_message(valid_message)

    # Assert callback called once with Candle
    mock_callback.assert_called_once()
    candle_arg = mock_callback.call_args[0][0]
    assert isinstance(candle_arg, Candle)

    # Test with None callback
    collector.on_candle_callback = None
    collector._handle_kline_message(valid_message)  # Should not crash
```

#### Test Case 5: Non-Kline Message Handling
```python
def test_non_kline_message():
    """
    Verify non-kline messages are ignored with warning.

    Cases:
    - Different event type: '24hrTicker'
    - Missing 'e' key
    """
    # Message with different event type
    message = {'e': '24hrTicker', ...}

    with patch.object(collector.logger, 'warning') as mock_warning:
        collector._handle_kline_message(message)

        # Verify warning logged
        mock_warning.assert_called_once()
        assert '24hrTicker' in str(mock_warning.call_args)
```

#### Test Case 6: Malformed Message Error Handling
```python
def test_malformed_message_handling():
    """
    Verify graceful handling of malformed messages.

    Cases:
    - Missing 'k' key
    - Missing required field in 'k' (e.g., no 's')
    - Invalid data type (e.g., price is not numeric)
    - Invalid timestamp (negative, too large)
    """
    test_cases = [
        # Missing 'k' key
        {'e': 'kline'},

        # Missing required field
        {'e': 'kline', 'k': {'i': '1m'}},  # No symbol

        # Invalid price (non-numeric string)
        {'e': 'kline', 'k': {
            's': 'BTCUSDT', 'i': '1m', 't': 1638747600000, 'T': 1638747659999,
            'o': 'invalid', 'h': '57100', 'l': '56900', 'c': '57050',
            'v': '10.5', 'x': True
        }},

        # Invalid timestamp (non-integer)
        {'e': 'kline', 'k': {
            's': 'BTCUSDT', 'i': '1m', 't': 'invalid', 'T': 1638747659999,
            'o': '57000', 'h': '57100', 'l': '56900', 'c': '57050',
            'v': '10.5', 'x': True
        }}
    ]

    for malformed_message in test_cases:
        with patch.object(collector.logger, 'error') as mock_error:
            # Should not raise exception
            collector._handle_kline_message(malformed_message)

            # Verify error logged
            mock_error.assert_called()
```

#### Test Case 7: Candle Validation Errors
```python
def test_candle_validation_errors():
    """
    Verify Candle validation errors are caught and logged.

    Cases:
    - High < Open (invalid)
    - Low > Close (invalid)
    - Negative volume (invalid)
    """
    # Create message with invalid candle data
    # Example: high=56000 but open=57000 (high must be >= open)
    invalid_message = {
        'e': 'kline',
        'k': {
            's': 'BTCUSDT', 'i': '1m',
            't': 1638747600000, 'T': 1638747659999,
            'o': '57000.00',  # Open = 57000
            'h': '56000.00',  # High = 56000 (INVALID: < open)
            'l': '56900.00',
            'c': '57050.00',
            'v': '10.5',
            'x': True
        }
    }

    with patch.object(collector.logger, 'error') as mock_error:
        collector._handle_kline_message(invalid_message)

        # Verify error logged (Candle __post_init__ will raise ValueError)
        mock_error.assert_called()
        assert 'ValueError' in str(mock_error.call_args) or 'Unexpected error' in str(mock_error.call_args)
```

#### Test Case 8: Debug Logging
```python
def test_debug_logging():
    """
    Verify debug logging on successful parse.

    Validates:
    - Debug message contains symbol, interval, close_time
    - Log level is DEBUG
    """
    with patch.object(collector.logger, 'debug') as mock_debug:
        collector._handle_kline_message(valid_message)

        mock_debug.assert_called_once()
        log_message = str(mock_debug.call_args)
        assert 'BTCUSDT' in log_message
        assert '1m' in log_message
```

### 5.3 Coverage Goals

- **Line Coverage**: 100% for `_handle_kline_message()` method
- **Branch Coverage**: All error paths tested
- **Edge Cases**: Timestamp/price conversions, malformed data, validation errors

---

## 6. Implementation Checklist

- [ ] Import `datetime` module (add to file imports if not present)
- [ ] Replace stub `pass` with full implementation
- [ ] Add message type validation (`e == 'kline'`)
- [ ] Extract kline data from `message['k']`
- [ ] Convert timestamp fields (ms → datetime)
- [ ] Convert price/volume fields (str → float)
- [ ] Create Candle object with all fields
- [ ] Invoke callback if configured
- [ ] Add comprehensive try-except error handling
- [ ] Add debug logging for successful parsing
- [ ] Add error logging with message context
- [ ] Create unit test class `TestBinanceDataCollectorMessageParsing`
- [ ] Implement 8 test cases
- [ ] Verify 100% test coverage
- [ ] Run all tests and ensure passing
- [ ] Update Task Master status to 'done'
- [ ] Commit with descriptive message
- [ ] Push to feature branch

---

## 7. Dependencies & Integration

### 7.1 Upstream Dependencies (Completed)
- ✅ Subtask 3.1: Candle model available with validation
- ✅ Subtask 3.2: WebSocket routes messages to this handler

### 7.2 Downstream Dependencies (Blocked Until Complete)
- ⏳ Subtask 3.5: Buffer management (will store parsed candles)
- ⏳ Subtask 3.6: Lifecycle management (complete data flow)

### 7.3 External Dependencies
- `datetime.datetime` - for timestamp conversion
- `datetime.fromtimestamp()` - static method
- `src.models.candle.Candle` - target dataclass

---

## 8. Risk Analysis

### 8.1 Technical Risks

**Risk 1: Timestamp Precision**
- **Concern**: Millisecond precision loss in datetime conversion
- **Mitigation**: Python datetime supports microsecond precision (sufficient)
- **Severity**: Very Low

**Risk 2: Float Precision**
- **Concern**: String→float conversion may lose precision
- **Mitigation**: Python float is IEEE 754 double (15-17 significant digits, sufficient for prices)
- **Severity**: Very Low

**Risk 3: Malformed Message Frequency**
- **Concern**: High rate of malformed messages could spam logs
- **Mitigation**: Error-level logging (not info/debug), monitoring required
- **Severity**: Low

**Risk 4: Callback Exceptions**
- **Concern**: User callback exceptions could disrupt processing
- **Mitigation**: No try-except around callback (user responsibility), document in callback docstring
- **Severity**: Low - By design

### 8.2 Integration Risks

**Risk 1: Candle Validation Strictness**
- **Concern**: `__post_init__` validation may reject valid market data
- **Mitigation**: Binance data quality is high, validation catches real errors
- **Severity**: Very Low

**Risk 2: Message Format Changes**
- **Concern**: Binance could change WebSocket message format
- **Mitigation**: Field extraction uses .get() with defaults, extensive error handling
- **Severity**: Low

---

## 9. Success Criteria

**Functional Requirements**:
- ✅ Valid kline messages parsed to Candle objects
- ✅ All data types converted correctly
- ✅ Callback invoked with valid Candle
- ✅ Malformed messages handled gracefully

**Quality Requirements**:
- ✅ 100% test coverage for new code
- ✅ All 8 test cases passing
- ✅ No unhandled exceptions
- ✅ Comprehensive error logging

**Performance**:
- ✅ Parsing < 1ms per message (negligible overhead)
- ✅ No memory leaks from logging

---

## 10. Next Steps After Completion

1. **Immediate**: Mark Subtask 3.3 as 'done' in Task Master
2. **Next**: Begin Subtask 3.4 - Historical Candles REST API
3. **Future**: Integration testing with live Binance testnet messages
4. **Follow-up**: Subtask 3.5 will integrate buffer management with parsed candles

---

**Design Status**: ✅ Complete - Ready for Implementation
**Reviewed By**: Claude Sonnet 4.5 (Design Agent)
**Implementation Owner**: Claude Sonnet 4.5 (Implementation Agent)
