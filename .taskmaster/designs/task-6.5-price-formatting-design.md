# Task 6.5: Price Formatting with Tick Size Design Document

**Task ID**: 6.5
**Dependencies**: Task #1 (Core Infrastructure Setup - COMPLETED), Task #6.1 (Order Execution Manager Base - COMPLETED)
**Status**: Design Phase
**Created**: 2025-12-17

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements Analysis](#requirements-analysis)
3. [API Specification Analysis](#api-specification-analysis)
4. [Current Implementation Analysis](#current-implementation-analysis)
5. [Implementation Design](#implementation-design)
6. [Caching Strategy](#caching-strategy)
7. [Error Handling Strategy](#error-handling-strategy)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)

---

## 1. Overview

### 1.1 Purpose

Replace the hardcoded 2-decimal precision in `_format_price()` method with dynamic precision based on Binance's symbol-specific tick size specifications from `exchange_info()` API.

### 1.2 Problem Statement

**Current Issue**:
```python
def _format_price(self, price: float, symbol: str) -> str:
    # Fixed 2 decimal precision for USDT pairs
    # TODO (6.5): Fetch precision from exchange info API
    return f"{price:.2f}"
```

**Why This Fails**:
- BTCUSDT requires 2 decimals (tickSize=0.01): 50123.46 ✅
- ETHUSDT requires 2 decimals (tickSize=0.01): 2345.67 ✅
- BNBUSDT requires 3 decimals (tickSize=0.001): 492.123 ❌ (gets formatted as 492.12)
- Some pairs require 1 decimal (tickSize=0.1): 12345.7 ❌ (gets formatted as 12345.70)
- Some pairs require 0 decimals (tickSize=1.0): 12345 ❌ (gets formatted as 12345.00)

**Binance Rejection Example**:
```json
{
  "code": -1111,
  "msg": "Precision is over the maximum defined for this asset."
}
```

### 1.3 Scope

**In Scope**:
- Fetch symbol specifications from `client.exchange_info()` API
- Extract `tickSize` from `PRICE_FILTER` in symbol's filters array
- Calculate decimal precision from tick size
- Cache exchange info to avoid redundant API calls
- Implement TTL-based cache expiration
- Handle missing/invalid symbol information

**Out of Scope**:
- Real-time ticker price validation
- Multi-exchange support (Binance only)
- Quantity precision (handled separately by `_format_quantity()`)
- Order validation beyond price formatting

### 1.4 Key Design Decisions

1. **Cache-First Architecture**: Query exchange info once per session, cache with 24h TTL
2. **Lazy Loading**: Only fetch exchange info on first price format call
3. **Tick Size → Decimal Calculation**: Mathematical precision extraction
4. **Graceful Degradation**: Fall back to 2 decimals if symbol not found
5. **Thread-Safe Caching**: Use instance-level dict, assume single-threaded execution context

---

## 2. Requirements Analysis

### 2.1 Functional Requirements

**FR1**: Fetch exchange information using `client.exchange_info()` API
**FR2**: Extract `PRICE_FILTER` from symbol's filters array
**FR3**: Parse `tickSize` value from price filter
**FR4**: Calculate decimal precision from tick size
**FR5**: Format prices using symbol-specific precision
**FR6**: Cache exchange info to minimize API calls
**FR7**: Implement cache expiration with 24-hour TTL
**FR8**: Handle missing symbols gracefully (log warning, use default)

### 2.2 Non-Functional Requirements

**NFR1**: **Performance**: Cache reduces API calls from N (per order) to 1 (per day)
**NFR2**: **Reliability**: Graceful fallback ensures orders still execute
**NFR3**: **Maintainability**: Clear separation of caching logic
**NFR4**: **Observability**: Log cache hits/misses and precision calculations
**NFR5**: **Type Safety**: Maintain type hints for all methods

### 2.3 Precision Calculation Logic

```python
# Tick Size → Decimal Places Mapping
tickSize = 0.01   → decimal_places = 2  # BTCUSDT, ETHUSDT
tickSize = 0.001  → decimal_places = 3  # BNBUSDT
tickSize = 0.1    → decimal_places = 1  # Some pairs
tickSize = 1.0    → decimal_places = 0  # Integer-only pairs
tickSize = 0.0001 → decimal_places = 4  # High-precision pairs

# Formula: decimal_places = -log10(tickSize)
# Implementation: Count zeros after decimal point + 1
```

---

## 3. API Specification Analysis

### 3.1 Binance Exchange Info API

**Endpoint**: `GET /fapi/v1/exchangeInfo` (Futures)
**Purpose**: Retrieves comprehensive exchange metadata including symbol specifications

**Python Client Method**:
```python
response = client.exchange_info()
```

**Response Structure**:
```json
{
  "timezone": "UTC",
  "serverTime": 1672531200000,
  "rateLimits": [...],
  "exchangeFilters": [],
  "symbols": [
    {
      "symbol": "BTCUSDT",
      "pair": "BTCUSDT",
      "contractType": "PERPETUAL",
      "status": "TRADING",
      "baseAsset": "BTC",
      "quoteAsset": "USDT",
      "pricePrecision": 2,
      "quantityPrecision": 3,
      "filters": [
        {
          "filterType": "PRICE_FILTER",
          "minPrice": "0.01",
          "maxPrice": "1000000",
          "tickSize": "0.01"
        },
        {
          "filterType": "LOT_SIZE",
          "minQty": "0.001",
          "maxQty": "1000",
          "stepSize": "0.001"
        },
        ...
      ]
    },
    ...
  ]
}
```

### 3.2 PRICE_FILTER Specification

**Filter Type**: `"PRICE_FILTER"`
**Purpose**: Defines valid price constraints for orders

**Fields**:
- **`minPrice`** (string): Minimum allowed price (e.g., "0.01")
- **`maxPrice`** (string): Maximum allowed price (e.g., "1000000")
- **`tickSize`** (string): Minimum price increment (e.g., "0.01")

**Validation Rule**:
```python
# Price must be:
price >= minPrice
price <= maxPrice
(price - minPrice) % tickSize == 0
```

**Example Tick Sizes** (from live Binance data):
```python
BTCUSDT:  tickSize="0.01"   → 2 decimals  # Bitcoin
ETHUSDT:  tickSize="0.01"   → 2 decimals  # Ethereum
BNBUSDT:  tickSize="0.001"  → 3 decimals  # Binance Coin
ADAUSDT:  tickSize="0.0001" → 4 decimals  # Cardano
1000SHIBUSDT: tickSize="0.000001" → 6 decimals  # Shiba (small price)
```

---

## 4. Current Implementation Analysis

### 4.1 Existing `_format_price()` Method

**Location**: `src/execution/order_manager.py` lines 251-272

**Current Code**:
```python
def _format_price(self, price: float, symbol: str) -> str:
    """
    Format price to appropriate decimal precision for Binance API.

    Args:
        price: Raw price value
        symbol: Trading symbol (e.g., 'BTCUSDT')

    Returns:
        Price formatted as string with 2 decimal places

    Note:
        Subtask 6.5 will implement dynamic precision based on symbol.
        For now, assumes USDT pairs require 2 decimal places.

    Example:
        >>> manager._format_price(50123.456, 'BTCUSDT')
        '50123.46'
    """
    # Fixed 2 decimal precision for USDT pairs
    # TODO (6.5): Fetch precision from exchange info API
    return f"{price:.2f}"
```

**Current Usage** (from `execute_signal()` method):
```python
# Format entry order price
entry_price_str = self._format_price(signal.entry_price, signal.symbol)

# Format TP price
tp_price_str = self._format_price(signal.take_profit, signal.symbol)

# Format SL price
sl_price_str = self._format_price(signal.stop_loss, signal.symbol)
```

### 4.2 Class Structure

**OrderExecutionManager** has:
- `self.client`: `UMFutures` instance (Binance client)
- `self.logger`: Logging instance
- Instance-level state (no threading concerns in current design)

**Suitable for Caching**:
- Add `self._exchange_info_cache: Dict[str, Dict]` for symbol data
- Add `self._cache_timestamp: Optional[datetime]` for TTL tracking
- Initialize in `__init__()`

---

## 5. Implementation Design

### 5.1 Enhanced `_format_price()` Method

**New Signature** (unchanged for compatibility):
```python
def _format_price(self, price: float, symbol: str) -> str:
    """
    Format price according to symbol's tick size specification.

    Fetches tick size from Binance exchange info (cached), calculates
    precision, and formats price to exact decimal places required.

    Args:
        price: Raw price value
        symbol: Trading symbol (e.g., 'BTCUSDT')

    Returns:
        Price formatted as string with symbol-specific precision

    Raises:
        OrderExecutionError: Exchange info fetch fails critically

    Example:
        >>> manager._format_price(50123.456, 'BTCUSDT')
        '50123.46'  # 2 decimals for BTCUSDT

        >>> manager._format_price(492.1234, 'BNBUSDT')
        '492.123'  # 3 decimals for BNBUSDT
    """
```

**Implementation Steps**:

1. **Get Symbol Tick Size** (with caching):
```python
tick_size = self._get_tick_size(symbol)
```

2. **Calculate Decimal Precision**:
```python
decimal_places = self._calculate_precision(tick_size)
```

3. **Format Price**:
```python
formatted = f"{price:.{decimal_places}f}"
return formatted
```

4. **Log Formatting** (debug level):
```python
self.logger.debug(
    f"Formatted price for {symbol}: {price} → {formatted} "
    f"(tick_size={tick_size}, precision={decimal_places})"
)
```

### 5.2 New Helper Method: `_get_tick_size()`

**Purpose**: Retrieve tick size for a symbol with caching

**Signature**:
```python
def _get_tick_size(self, symbol: str) -> float:
    """
    Get tick size for symbol from exchange info (cached).

    Args:
        symbol: Trading symbol (e.g., 'BTCUSDT')

    Returns:
        Tick size as float (e.g., 0.01)

    Raises:
        OrderExecutionError: Exchange info fetch fails

    Note:
        Falls back to 0.01 (2 decimals) if symbol not found
    """
```

**Implementation**:
```python
def _get_tick_size(self, symbol: str) -> float:
    # 1. Check cache validity
    if self._is_cache_expired():
        self._refresh_exchange_info()

    # 2. Look up symbol in cache
    if symbol in self._exchange_info_cache:
        tick_size = self._exchange_info_cache[symbol]['tickSize']
        self.logger.debug(f"Cache hit for {symbol}: tickSize={tick_size}")
        return tick_size

    # 3. Symbol not found - graceful fallback
    self.logger.warning(
        f"Symbol {symbol} not found in exchange info. "
        f"Using default tickSize=0.01 (2 decimals)"
    )
    return 0.01  # Default for USDT pairs
```

### 5.3 New Helper Method: `_calculate_precision()`

**Purpose**: Calculate decimal places from tick size

**Signature**:
```python
def _calculate_precision(self, tick_size: float) -> int:
    """
    Calculate decimal precision from tick size.

    Args:
        tick_size: Minimum price increment (e.g., 0.01)

    Returns:
        Number of decimal places (e.g., 2)

    Example:
        >>> self._calculate_precision(0.01)
        2
        >>> self._calculate_precision(0.001)
        3
        >>> self._calculate_precision(1.0)
        0
    """
```

**Implementation**:
```python
def _calculate_precision(self, tick_size: float) -> int:
    # Convert to string to count decimal places
    tick_str = f"{tick_size:.10f}".rstrip('0')  # Remove trailing zeros

    if '.' not in tick_str:
        return 0  # Integer tick size

    # Count digits after decimal point
    decimal_part = tick_str.split('.')[1]
    precision = len(decimal_part)

    return precision
```

### 5.4 Cache Management Methods

**`_is_cache_expired()`**:
```python
def _is_cache_expired(self) -> bool:
    """Check if exchange info cache has expired."""
    if self._cache_timestamp is None:
        return True  # Never cached

    age = datetime.now() - self._cache_timestamp
    return age > timedelta(hours=24)  # 24-hour TTL
```

**`_refresh_exchange_info()`**:
```python
def _refresh_exchange_info(self) -> None:
    """Fetch and cache exchange information from Binance."""
    self.logger.info("Fetching exchange information from Binance")

    try:
        # 1. Call Binance API
        response = self.client.exchange_info()

        # 2. Parse symbols and extract tick sizes
        for symbol_data in response['symbols']:
            symbol = symbol_data['symbol']

            # Find PRICE_FILTER
            price_filter = None
            for filter_item in symbol_data['filters']:
                if filter_item['filterType'] == 'PRICE_FILTER':
                    price_filter = filter_item
                    break

            if price_filter:
                tick_size = float(price_filter['tickSize'])
                self._exchange_info_cache[symbol] = {
                    'tickSize': tick_size,
                    'minPrice': float(price_filter['minPrice']),
                    'maxPrice': float(price_filter['maxPrice'])
                }

        # 3. Update cache timestamp
        self._cache_timestamp = datetime.now()

        symbols_count = len(self._exchange_info_cache)
        self.logger.info(
            f"Exchange info cached: {symbols_count} symbols loaded"
        )

    except Exception as e:
        self.logger.error(f"Failed to fetch exchange info: {e}")
        raise OrderExecutionError(
            f"Exchange info fetch failed: {e}"
        )
```

### 5.5 Initialization Changes

**Add to `__init__()` method**:
```python
def __init__(self, api_key: str = None, api_secret: str = None, is_testnet: bool = True):
    # ... existing initialization ...

    # Exchange info cache (Task 6.5)
    self._exchange_info_cache: Dict[str, Dict[str, float]] = {}
    self._cache_timestamp: Optional[datetime] = None

    self.logger.info("OrderExecutionManager initialized")
```

---

## 6. Caching Strategy

### 6.1 Cache Design

**Structure**:
```python
self._exchange_info_cache = {
    "BTCUSDT": {
        "tickSize": 0.01,
        "minPrice": 0.01,
        "maxPrice": 1000000.0
    },
    "BNBUSDT": {
        "tickSize": 0.001,
        "minPrice": 0.001,
        "maxPrice": 100000.0
    },
    ...
}
```

**TTL Strategy**:
- **Duration**: 24 hours
- **Rationale**: Binance rarely changes tick sizes; daily refresh is sufficient
- **Timestamp**: `self._cache_timestamp` tracks last fetch time
- **Expiration Check**: On every `_get_tick_size()` call

### 6.2 Cache Invalidation

**Automatic Expiration**:
```python
if datetime.now() - self._cache_timestamp > timedelta(hours=24):
    self._refresh_exchange_info()
```

**Manual Refresh** (optional future enhancement):
```python
def refresh_exchange_info(self) -> None:
    """Manually refresh exchange info cache."""
    self._refresh_exchange_info()
```

### 6.3 Performance Impact

**Without Cache**:
- 1 API call per `_format_price()` invocation
- ~100ms latency per call
- Rate limit consumption: 1 weight per call

**With Cache**:
- 1 API call per 24 hours
- ~0.1ms dictionary lookup
- Rate limit consumption: negligible

**Improvement**: ~1000x faster for repeated price formatting

---

## 7. Error Handling Strategy

### 7.1 Exception Scenarios

| Scenario | Exception | Handling |
|----------|-----------|----------|
| Exchange info fetch fails | OrderExecutionError | Re-raise with context |
| Symbol not in exchange info | None (graceful) | Log warning, use default 0.01 |
| Invalid tick size format | ValueError | Log error, use default 0.01 |
| Cache corruption | Exception | Clear cache, retry fetch |
| API rate limit exceeded | OrderExecutionError | Re-raise with rate limit msg |

### 7.2 Graceful Degradation

**Missing Symbol Handling**:
```python
if symbol not in self._exchange_info_cache:
    self.logger.warning(
        f"Symbol {symbol} not found in exchange info. "
        f"Using default tickSize=0.01 (2 decimals). "
        f"This may cause order rejection for non-standard pairs."
    )
    return 0.01  # Conservative default
```

**Benefits**:
- Orders still execute for major pairs (BTCUSDT, ETHUSDT)
- System doesn't crash on unknown symbols
- Clear logging for debugging

**Risks**:
- May format incorrectly for exotic pairs
- Potential order rejection from Binance

**Mitigation**: Log warnings clearly for manual intervention

### 7.3 Logging Strategy

**Info Level**:
```python
# Cache refresh
self.logger.info("Fetching exchange information from Binance")
self.logger.info(f"Exchange info cached: {symbols_count} symbols loaded")
```

**Warning Level**:
```python
# Missing symbols
self.logger.warning(f"Symbol {symbol} not found in exchange info")
```

**Debug Level**:
```python
# Cache hits and formatting details
self.logger.debug(f"Cache hit for {symbol}: tickSize={tick_size}")
self.logger.debug(f"Formatted price for {symbol}: {price} → {formatted}")
```

**Error Level**:
```python
# Critical failures
self.logger.error(f"Failed to fetch exchange info: {e}")
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

**Test Class**: `TestPriceFormatting` (new class in `tests/test_order_execution.py`)

**Test Coverage**:

1. **`test_format_price_btcusdt_2_decimals`**
   - Mock exchange info with `tickSize=0.01`
   - Format price 50123.456
   - Verify result is "50123.46"

2. **`test_format_price_bnbusdt_3_decimals`**
   - Mock exchange info with `tickSize=0.001`
   - Format price 492.1234
   - Verify result is "492.123"

3. **`test_format_price_integer_tick_size`**
   - Mock exchange info with `tickSize=1.0`
   - Format price 12345.67
   - Verify result is "12346" (rounded)

4. **`test_format_price_high_precision_4_decimals`**
   - Mock exchange info with `tickSize=0.0001`
   - Format price 1.23456
   - Verify result is "1.2346"

5. **`test_calculate_precision_various_tick_sizes`**
   - Test precision calculation for: 0.01 → 2, 0.001 → 3, 0.1 → 1, 1.0 → 0

6. **`test_cache_hit_no_api_call`**
   - Populate cache manually
   - Call `_format_price()` multiple times
   - Verify `client.exchange_info()` called only once

7. **`test_cache_expiration_refresh`**
   - Set cache timestamp to 25 hours ago
   - Call `_format_price()`
   - Verify cache refreshed (new API call)

8. **`test_missing_symbol_fallback`**
   - Mock exchange info without target symbol
   - Call `_format_price()` for missing symbol
   - Verify warning logged
   - Verify default 0.01 tick size used (2 decimals)

9. **`test_exchange_info_api_failure`**
   - Mock `client.exchange_info()` to raise exception
   - Verify `OrderExecutionError` raised
   - Verify error logged

10. **`test_price_filter_extraction`**
    - Mock complex filters array
    - Verify PRICE_FILTER correctly extracted
    - Verify tick size parsed as float

### 8.2 Integration Tests (Testnet)

**Prerequisites**:
- Binance Testnet API keys
- Active network connection

**Test Scenarios**:

1. **Integration: Fetch Real Exchange Info**
   ```python
   manager = OrderExecutionManager(is_testnet=True)
   tick_size = manager._get_tick_size('BTCUSDT')
   assert tick_size == 0.01  # Current Binance spec
   ```

2. **Integration: Format Real Prices**
   ```python
   # BTCUSDT: 2 decimals
   formatted = manager._format_price(50123.456, 'BTCUSDT')
   assert formatted == "50123.46"

   # BNBUSDT: 3 decimals
   formatted = manager._format_price(492.1234, 'BNBUSDT')
   assert formatted == "492.123"
   ```

3. **Integration: Cache Persistence**
   ```python
   # First call
   start = time.time()
   manager._format_price(50000, 'BTCUSDT')
   first_duration = time.time() - start

   # Subsequent call (cached)
   start = time.time()
   manager._format_price(51000, 'BTCUSDT')
   cached_duration = time.time() - start

   assert cached_duration < first_duration * 0.1  # 10x faster
   ```

4. **Integration: Full Order Flow**
   ```python
   # Create signal with various prices
   signal = Signal(
       symbol="BTCUSDT",
       entry_price=50123.456,
       take_profit=55000.123,
       stop_loss=48000.987,
       ...
   )

   # Execute (should format all prices correctly)
   result = manager.execute_signal(signal)

   # Verify order accepted by Binance
   assert result['status'] == 'success'
   ```

### 8.3 Test Data Examples

**Mock Exchange Info Response**:
```python
MOCK_EXCHANGE_INFO = {
    "timezone": "UTC",
    "serverTime": 1672531200000,
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "filters": [
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.01",
                    "maxPrice": "1000000",
                    "tickSize": "0.01"
                },
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "0.001",
                    "maxQty": "1000",
                    "stepSize": "0.001"
                }
            ]
        },
        {
            "symbol": "BNBUSDT",
            "filters": [
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.001",
                    "maxPrice": "100000",
                    "tickSize": "0.001"
                }
            ]
        }
    ]
}
```

**Test Fixtures**:
```python
@pytest.fixture
def mock_exchange_info():
    """Mock exchange_info() response"""
    return MOCK_EXCHANGE_INFO

@pytest.fixture
def manager_with_cached_info(mock_client, mock_exchange_info):
    """Manager with pre-populated cache"""
    mock_client.exchange_info.return_value = mock_exchange_info
    manager = OrderExecutionManager(is_testnet=True)
    manager._refresh_exchange_info()
    return manager
```

---

## 9. Success Criteria

### 9.1 Functional Success

- ✅ `_format_price()` fetches tick size from exchange info
- ✅ Prices formatted with symbol-specific precision
- ✅ BTCUSDT prices formatted with 2 decimals
- ✅ BNBUSDT prices formatted with 3 decimals
- ✅ Cache reduces API calls to 1 per 24 hours
- ✅ Cache expiration triggers refresh correctly
- ✅ Missing symbols fall back to default gracefully

### 9.2 Error Handling Success

- ✅ Exchange info fetch failures raise `OrderExecutionError`
- ✅ Missing symbols log warnings and use default
- ✅ Invalid tick sizes handled gracefully
- ✅ All errors logged with appropriate severity

### 9.3 Testing Success

- ✅ All 10 unit tests pass
- ✅ Code coverage >90% on new/modified methods
- ✅ Integration tests pass on Binance Testnet
- ✅ Real orders execute successfully with formatted prices

### 9.4 Code Quality Success

- ✅ Code follows existing style and conventions
- ✅ Docstrings comprehensive with examples
- ✅ Type hints correct for all new methods
- ✅ Logging informative and actionable
- ✅ Cache implementation efficient and thread-safe
- ✅ No performance regression (<1ms overhead per format)

---

## Appendix A: Tick Size Examples

### Real Binance Futures Pairs (as of 2024)

| Symbol | Tick Size | Decimals | Example Price |
|--------|-----------|----------|---------------|
| BTCUSDT | 0.01 | 2 | 50123.46 |
| ETHUSDT | 0.01 | 2 | 2345.67 |
| BNBUSDT | 0.001 | 3 | 492.123 |
| ADAUSDT | 0.0001 | 4 | 0.5234 |
| DOGEUSDT | 0.00001 | 5 | 0.08765 |
| 1000SHIBUSDT | 0.000001 | 6 | 0.012345 |
| XRPUSDT | 0.0001 | 4 | 0.5678 |
| SOLUSDT | 0.001 | 3 | 123.456 |

### Edge Cases

| Scenario | Tick Size | Handling |
|----------|-----------|----------|
| Very small price | 0.000001 | 6 decimals precision |
| Integer prices | 1.0 | 0 decimals (no decimal point) |
| Missing symbol | N/A | Default to 0.01 (2 decimals) |
| Malformed filter | N/A | Log error, use default |

---

## Appendix B: Implementation Checklist

### Phase 1: Core Implementation
- [ ] Add cache fields to `__init__()`
- [ ] Implement `_get_tick_size()`
- [ ] Implement `_calculate_precision()`
- [ ] Implement `_is_cache_expired()`
- [ ] Implement `_refresh_exchange_info()`
- [ ] Update `_format_price()` to use new methods

### Phase 2: Testing
- [ ] Create `TestPriceFormatting` test class
- [ ] Write 10 unit tests
- [ ] Add test fixtures for exchange info mocking
- [ ] Write 4 integration tests for Testnet
- [ ] Verify coverage >90%

### Phase 3: Validation
- [ ] Run full test suite
- [ ] Test on Binance Testnet with real API
- [ ] Verify no performance regression
- [ ] Review logs for warnings/errors
- [ ] Document any known issues

### Phase 4: Deployment
- [ ] Code review and approval
- [ ] Merge to main branch
- [ ] Update Task 6.5 status to 'done'
- [ ] Monitor production for 24 hours

---

**Design Status**: Ready for Implementation ✅
**Estimated Implementation Time**: 2-3 hours
**Estimated Testing Time**: 1-2 hours
