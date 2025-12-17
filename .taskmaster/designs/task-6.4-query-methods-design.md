# Task 6.4: Position and Account Query Methods Design Document

**Task ID**: 6.4
**Dependencies**: Task #1 (Core Infrastructure Setup - COMPLETED)
**Status**: Design Phase
**Created**: 2025-12-17

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements Analysis](#requirements-analysis)
3. [API Specification Analysis](#api-specification-analysis)
4. [Model Analysis](#model-analysis)
5. [Implementation Design](#implementation-design)
6. [Error Handling Strategy](#error-handling-strategy)
7. [Testing Strategy](#testing-strategy)
8. [Success Criteria](#success-criteria)

---

## 1. Overview

### 1.1 Purpose

Implement three query and management methods in `OrderExecutionManager` to enable position tracking, account balance monitoring, and emergency order cancellation capabilities:

1. **`get_position(symbol)`** - Query current position information
2. **`get_account_balance()`** - Query USDT wallet balance
3. **`cancel_all_orders(symbol)`** - Cancel all open orders for risk management

### 1.2 Scope

**In Scope**:
- Implement `get_position()` using Binance `get_position_risk()` API
- Implement `get_account_balance()` using Binance `account()` API
- Implement `cancel_all_orders()` using Binance `cancel_open_orders()` API
- Parse API responses into our domain models (`Position` object)
- Handle zero-position cases (return `None`)
- Comprehensive error handling with typed exceptions
- Unit tests with mocked API responses
- Integration tests on Binance Testnet

**Out of Scope**:
- Multiple position tracking (position aggregation across symbols)
- Historical position data retrieval
- Account balance for assets other than USDT
- Conditional order cancellation (cancel only specific order types)
- Position modification (leverage changes, margin adjustments)
- Real-time position updates via WebSocket

### 1.3 Key Design Decisions

1. **Return `None` for Zero Positions**: When `positionAmt == 0`, return `None` instead of a `Position` object with zero quantity
2. **USDT-Only Balance**: Focus on USDT balance only (most common margin asset for USDT-M futures)
3. **Simple Cancellation**: Cancel all orders for a symbol (not selective by order type or side)
4. **Position Side Determination**: Use `positionAmt` sign to determine LONG (positive) vs SHORT (negative)
5. **Error Transparency**: Distinguish between API errors (network, authentication) and business logic errors (no position)

---

## 2. Requirements Analysis

### 2.1 Functional Requirements

**FR1**: `get_position(symbol)` retrieves current position information for a specific symbol
**FR2**: Return `Position` object with fields: symbol, side, entry_price, quantity, leverage, unrealized_pnl, liquidation_price
**FR3**: Return `None` when position size is zero (`positionAmt == 0`)
**FR4**: Determine position side from `positionAmt` sign (positive = LONG, negative = SHORT)
**FR5**: `get_account_balance()` returns USDT wallet balance as `float`
**FR6**: Extract balance from `assets` array in account data
**FR7**: `cancel_all_orders(symbol)` cancels all open orders for a symbol
**FR8**: Return count of cancelled orders as `int`

### 2.2 Non-Functional Requirements

**NFR1**: **Reliability**: Handle API failures gracefully with appropriate exceptions
**NFR2**: **Observability**: Log all API calls with request parameters and response summaries
**NFR3**: **Maintainability**: Use consistent error handling patterns across all methods
**NFR4**: **Performance**: Single API call per method (no redundant queries)
**NFR5**: **Type Safety**: Use type hints for all method signatures and return types

### 2.3 Position Side Mapping

```python
# Position Amount Sign → Position Side
positionAmt > 0  → side="LONG"   # Long position (bought contracts)
positionAmt < 0  → side="SHORT"  # Short position (sold contracts)
positionAmt == 0 → return None   # No position
```

---

## 3. API Specification Analysis

### 3.1 Binance Position Risk API

**Endpoint**: `GET /fapi/v2/positionRisk`
**Purpose**: Retrieves current position information including risk and margin details

**Required Parameters**:
```python
{
    "symbol": "BTCUSDT",      # Trading pair (optional - if omitted, returns all symbols)
    "recvWindow": 5000        # Optional - request validity window (max 60000ms)
}
```

**Response Structure** (SUCCESS - 200):
```json
[
  {
    "symbol": "BTCUSDT",
    "positionAmt": "0.00200000",        # Position size (+ LONG, - SHORT, 0 = no position)
    "entryPrice": "50000.00",           # Average entry price
    "unRealizedProfit": "10.00",        # Current unrealized P&L
    "leverage": "20",                   # Current leverage
    "isolated": true,                   # Margin mode (true=isolated, false=cross)
    "isolatedWallet": "100.00",         # Isolated margin wallet balance
    "positionSide": "BOTH",             # Position side mode (BOTH/LONG/SHORT)
    "notional": "100.00",               # Notional value of position
    "isolatedMargin": "5.00",           # Isolated position margin
    "maintMargin": "0.50",              # Maintenance margin
    "initialMargin": "5.00",            # Initial margin
    "liquidationPrice": "45000.00",     # Liquidation price
    "markPrice": "50500.00",            # Current mark price
    "maxNotionalValue": "1000000.00",   # Maximum notional value
    "updateTime": 1678886400000         # Last update timestamp
  }
]
```

**Key Fields for Position Model**:
- `symbol`: Trading pair
- `positionAmt`: Use sign to determine side, absolute value for quantity
- `entryPrice`: Average entry price
- `leverage`: Current leverage (string → int conversion)
- `unRealizedProfit`: Current unrealized P&L
- `liquidationPrice`: Liquidation price (if applicable)

**API Error Responses**:
```python
# Invalid symbol
{
  "code": -1121,
  "msg": "Invalid symbol."
}

# Invalid API key/signature
{
  "code": -2015,
  "msg": "Invalid API-key, IP, or permissions for action."
}
```

### 3.2 Binance Account API

**Endpoint**: `GET /fapi/v2/account`
**Purpose**: Retrieves comprehensive account information including balances and positions

**Required Parameters**:
```python
{
    "recvWindow": 5000  # Optional - request validity window
}
```

**Response Structure** (SUCCESS - 200):
```json
{
  "feeTier": 0,
  "canTrade": true,
  "canDeposit": true,
  "canWithdraw": true,
  "updateTime": 1678886400000,
  "totalInitialMargin": "0.00000000",
  "totalMaintMargin": "0.00000000",
  "totalWalletBalance": "12.12345678",
  "totalUnrealizedProfit": "0.00000000",
  "totalMarginBalance": "12.12345678",
  "assets": [
    {
      "asset": "USDT",                    # Asset symbol
      "walletBalance": "100.50",          # Wallet balance (target field)
      "unrealizedProfit": "10.25",        # Unrealized P&L
      "marginBalance": "110.75",          # Total margin balance
      "maintMargin": "5.00",              # Maintenance margin
      "initialMargin": "10.00",           # Initial margin
      "availableBalance": "105.75",       # Available balance
      "updateTime": 1678886400000
    },
    {
      "asset": "BTC",
      "walletBalance": "0.001",
      ...
    }
  ],
  "positions": [...]  # Position data (not needed for balance query)
}
```

**Key Fields for Balance Extraction**:
- `assets`: Array of asset balances
- `asset`: Asset symbol (filter for "USDT")
- `walletBalance`: Target field for USDT balance

**Edge Cases**:
1. **USDT Not Found**: If user has no USDT balance, `assets` array may not contain USDT entry
2. **Empty Assets**: If account is brand new, `assets` array may be empty
3. **Multiple Assets**: Always iterate through array to find USDT specifically

### 3.3 Binance Cancel All Orders API

**Endpoint**: `DELETE /fapi/v1/allOpenOrders`
**Purpose**: Cancels all open orders for a specified symbol

**Required Parameters**:
```python
{
    "symbol": "BTCUSDT",     # Trading symbol (required)
    "recvWindow": 5000       # Optional
}
```

**Response Structure** (SUCCESS - 200):
```json
{
  "code": 200,
  "msg": "The operation of cancel all open order is done."
}
```

**Alternative Response** (List of Cancelled Orders):
```json
[
  {
    "orderId": 123456789,
    "symbol": "BTCUSDT",
    "status": "CANCELED",
    "clientOrderId": "abc123",
    "price": "50000.00",
    "origQty": "0.001",
    "type": "LIMIT",
    "side": "BUY",
    "updateTime": 1678886400000
  }
]
```

**API Error Responses**:
```python
# Invalid symbol
{
  "code": -1121,
  "msg": "Invalid symbol."
}

# No open orders to cancel
{
  "code": 200,
  "msg": "The operation of cancel all open order is done."
}
```

**Return Value Logic**:
- If response is a list → return `len(response)` (count of cancelled orders)
- If response is a dict with `code: 200` → return `0` (no orders were cancelled)
- If error occurs → raise appropriate exception

---

## 4. Model Analysis

### 4.1 Existing Position Model

**File**: `src/models/position.py`

**Current Structure**:
```python
@dataclass
class Position:
    """Active futures position."""

    symbol: str
    side: str  # 'LONG' or 'SHORT'
    entry_price: float
    quantity: float
    leverage: int
    unrealized_pnl: float = 0.0
    liquidation_price: Optional[float] = None
    entry_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate position parameters."""
        if self.side not in ("LONG", "SHORT"):
            raise ValueError(f"Side must be 'LONG' or 'SHORT', got {self.side}")
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be > 0, got {self.quantity}")
        if self.leverage < 1:
            raise ValueError(f"Leverage must be >= 1, got {self.leverage}")

    @property
    def notional_value(self) -> float:
        """Total position value (quantity * entry_price)."""
        return self.quantity * self.entry_price

    @property
    def margin_used(self) -> float:
        """Margin used for position (notional / leverage)."""
        return self.notional_value / self.leverage
```

**API Response → Position Mapping**:

| API Field | Position Field | Transformation |
|-----------|---------------|----------------|
| `symbol` | `symbol` | Direct copy |
| `positionAmt` | `side` | Sign → "LONG" or "SHORT" |
| `positionAmt` | `quantity` | `abs(positionAmt)` |
| `entryPrice` | `entry_price` | `float(entryPrice)` |
| `leverage` | `leverage` | `int(leverage)` |
| `unRealizedProfit` | `unrealized_pnl` | `float(unRealizedProfit)` |
| `liquidationPrice` | `liquidation_price` | `float(liquidationPrice)` or `None` |
| `updateTime` | `entry_time` | Not directly available (use `updateTime` as proxy) |

**Model Compatibility**: ✅ Existing `Position` model is fully compatible with API response

---

## 5. Implementation Design

### 5.1 Method: `get_position(symbol: str) -> Optional[Position]`

**Purpose**: Query current position information for a symbol

**Signature**:
```python
def get_position(self, symbol: str) -> Optional[Position]:
    """
    Query current position information for a symbol.

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')

    Returns:
        Position object if position exists, None if no position

    Raises:
        OrderExecutionError: API call fails or response parsing error
        ValidationError: Invalid symbol format

    Example:
        >>> position = manager.get_position('BTCUSDT')
        >>> if position:
        ...     print(f"{position.side} position: {position.quantity} @ {position.entry_price}")
        ... else:
        ...     print("No position")
    """
```

**Implementation Steps**:

1. **Validate Input**:
```python
if not symbol or not isinstance(symbol, str):
    raise ValidationError(f"Invalid symbol: {symbol}")
```

2. **Log API Call**:
```python
self.logger.info(f"Querying position for {symbol}")
```

3. **Call Binance API**:
```python
try:
    response = self.client.get_position_risk(symbol=symbol)
except ClientError as e:
    # Handle Binance API errors
    ...
```

4. **Parse Response**:
```python
# Response is a list (even for single symbol query)
if not response or len(response) == 0:
    self.logger.warning(f"No position data returned for {symbol}")
    return None

position_data = response[0]  # First element
position_amt = float(position_data["positionAmt"])

# Check if position exists
if position_amt == 0:
    self.logger.info(f"No active position for {symbol}")
    return None
```

5. **Determine Position Side**:
```python
side = "LONG" if position_amt > 0 else "SHORT"
quantity = abs(position_amt)
```

6. **Extract Required Fields**:
```python
entry_price = float(position_data["entryPrice"])
leverage = int(position_data["leverage"])
unrealized_pnl = float(position_data["unRealizedProfit"])

# Optional fields
liquidation_price = None
if "liquidationPrice" in position_data:
    liq_price_str = position_data["liquidationPrice"]
    if liq_price_str and liq_price_str != "0":
        liquidation_price = float(liq_price_str)
```

7. **Create Position Object**:
```python
position = Position(
    symbol=symbol,
    side=side,
    entry_price=entry_price,
    quantity=quantity,
    leverage=leverage,
    unrealized_pnl=unrealized_pnl,
    liquidation_price=liquidation_price
)

self.logger.info(
    f"Position retrieved: {side} {quantity} {symbol} @ {entry_price}, "
    f"PnL: {unrealized_pnl}"
)

return position
```

8. **Error Handling**:
```python
except ClientError as e:
    if e.error_code == -1121:
        raise ValidationError(f"Invalid symbol: {symbol}")
    elif e.error_code == -2015:
        raise OrderExecutionError(f"API authentication failed: {e.error_message}")
    else:
        raise OrderExecutionError(
            f"Position query failed: code={e.error_code}, msg={e.error_message}"
        )
except (KeyError, ValueError) as e:
    raise OrderExecutionError(f"Failed to parse position data: {e}")
```

### 5.2 Method: `get_account_balance() -> float`

**Purpose**: Query USDT wallet balance

**Signature**:
```python
def get_account_balance(self) -> float:
    """
    Query USDT wallet balance.

    Returns:
        USDT wallet balance as float

    Raises:
        OrderExecutionError: API call fails or USDT balance not found

    Example:
        >>> balance = manager.get_account_balance()
        >>> print(f"Available USDT: {balance:.2f}")
    """
```

**Implementation Steps**:

1. **Log API Call**:
```python
self.logger.info("Querying account balance")
```

2. **Call Binance API**:
```python
try:
    response = self.client.account()
except ClientError as e:
    # Handle API errors
    ...
```

3. **Extract Assets Array**:
```python
if "assets" not in response:
    raise OrderExecutionError("Account response missing 'assets' field")

assets = response["assets"]
```

4. **Find USDT Balance**:
```python
usdt_balance = None

for asset in assets:
    if asset.get("asset") == "USDT":
        usdt_balance = float(asset["walletBalance"])
        break

if usdt_balance is None:
    # USDT not found in assets array
    self.logger.warning("USDT not found in account assets, returning 0.0")
    return 0.0
```

5. **Log and Return**:
```python
self.logger.info(f"USDT balance: {usdt_balance:.2f}")
return usdt_balance
```

6. **Error Handling**:
```python
except ClientError as e:
    if e.error_code == -2015:
        raise OrderExecutionError(f"API authentication failed: {e.error_message}")
    else:
        raise OrderExecutionError(
            f"Balance query failed: code={e.error_code}, msg={e.error_message}"
        )
except (KeyError, ValueError, TypeError) as e:
    raise OrderExecutionError(f"Failed to parse account data: {e}")
```

### 5.3 Method: `cancel_all_orders(symbol: str) -> int`

**Purpose**: Cancel all open orders for a symbol

**Signature**:
```python
def cancel_all_orders(self, symbol: str) -> int:
    """
    Cancel all open orders for a symbol.

    Args:
        symbol: Trading pair (e.g., 'BTCUSDT')

    Returns:
        Number of orders cancelled

    Raises:
        OrderExecutionError: API call fails
        ValidationError: Invalid symbol format

    Example:
        >>> cancelled_count = manager.cancel_all_orders('BTCUSDT')
        >>> print(f"Cancelled {cancelled_count} orders")
    """
```

**Implementation Steps**:

1. **Validate Input**:
```python
if not symbol or not isinstance(symbol, str):
    raise ValidationError(f"Invalid symbol: {symbol}")
```

2. **Log API Call**:
```python
self.logger.info(f"Cancelling all orders for {symbol}")
```

3. **Call Binance API**:
```python
try:
    response = self.client.cancel_open_orders(symbol=symbol)
except ClientError as e:
    # Handle API errors
    ...
```

4. **Parse Response**:
```python
# Response can be either a list of cancelled orders or a success message dict
cancelled_count = 0

if isinstance(response, list):
    # Response is a list of cancelled order objects
    cancelled_count = len(response)
    self.logger.info(f"Cancelled {cancelled_count} orders for {symbol}")
elif isinstance(response, dict) and response.get("code") == 200:
    # Response is a success message (no orders to cancel)
    cancelled_count = 0
    self.logger.info(f"No open orders to cancel for {symbol}")
else:
    # Unexpected response format
    self.logger.warning(f"Unexpected response format: {response}")
    cancelled_count = 0

return cancelled_count
```

5. **Error Handling**:
```python
except ClientError as e:
    if e.error_code == -1121:
        raise ValidationError(f"Invalid symbol: {symbol}")
    elif e.error_code == -2015:
        raise OrderExecutionError(f"API authentication failed: {e.error_message}")
    else:
        raise OrderExecutionError(
            f"Order cancellation failed: code={e.error_code}, msg={e.error_message}"
        )
except Exception as e:
    raise OrderExecutionError(f"Unexpected error during order cancellation: {e}")
```

---

## 6. Error Handling Strategy

### 6.1 Exception Hierarchy

```python
TradingSystemError
├── OrderExecutionError         # API failures, parsing errors
│   ├── ValidationError        # Invalid input parameters
│   ├── RateLimitError        # API rate limit exceeded
│   └── OrderRejectedError    # Binance rejected operation
```

### 6.2 Error Mapping

| Binance Error Code | Exception Type | Message |
|-------------------|---------------|---------|
| -1121 | ValidationError | "Invalid symbol: {symbol}" |
| -2015 | OrderExecutionError | "API authentication failed" |
| -1003 | RateLimitError | "Rate limit exceeded" |
| -2010 | OrderExecutionError | "Insufficient balance" |
| Network errors | OrderExecutionError | "Network error: {details}" |
| Parsing errors | OrderExecutionError | "Failed to parse response: {details}" |

### 6.3 Logging Strategy

**Success Cases**:
```python
# get_position - found
self.logger.info(f"Position retrieved: LONG 0.001 BTCUSDT @ 50000.0, PnL: 10.25")

# get_position - not found
self.logger.info(f"No active position for BTCUSDT")

# get_account_balance - success
self.logger.info(f"USDT balance: 1234.56")

# get_account_balance - USDT not found
self.logger.warning("USDT not found in account assets, returning 0.0")

# cancel_all_orders - orders cancelled
self.logger.info(f"Cancelled 5 orders for BTCUSDT")

# cancel_all_orders - no orders
self.logger.info(f"No open orders to cancel for BTCUSDT")
```

**Error Cases**:
```python
# API errors
self.logger.error(f"Position query failed: code=-1121, msg=Invalid symbol")
self.logger.error(f"Balance query failed: code=-2015, msg=Authentication failed")
self.logger.error(f"Order cancellation failed: code=-1003, msg=Rate limit")

# Parsing errors
self.logger.error(f"Failed to parse position data: KeyError('positionAmt')")
self.logger.error(f"Failed to parse account data: TypeError(walletBalance)")
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

**Test File**: `tests/test_order_execution.py`
**Test Class**: `TestQueryMethods`

**Test Coverage**:

1. **`test_get_position_long_success`**
   - Mock API response with positive `positionAmt`
   - Verify `Position` object created with `side="LONG"`
   - Verify `quantity = abs(positionAmt)`
   - Verify all fields correctly populated

2. **`test_get_position_short_success`**
   - Mock API response with negative `positionAmt`
   - Verify `Position` object created with `side="SHORT"`
   - Verify `quantity = abs(positionAmt)`

3. **`test_get_position_no_position`**
   - Mock API response with `positionAmt=0`
   - Verify method returns `None`
   - Verify appropriate log message

4. **`test_get_position_invalid_symbol`**
   - Mock API error with code `-1121`
   - Verify `ValidationError` raised
   - Verify error message contains symbol

5. **`test_get_position_api_error`**
   - Mock API error with code `-2015`
   - Verify `OrderExecutionError` raised
   - Verify error logged

6. **`test_get_account_balance_success`**
   - Mock API response with USDT in assets
   - Verify correct balance returned
   - Verify log message

7. **`test_get_account_balance_usdt_not_found`**
   - Mock API response without USDT
   - Verify `0.0` returned
   - Verify warning logged

8. **`test_get_account_balance_api_error`**
   - Mock API authentication error
   - Verify `OrderExecutionError` raised

9. **`test_cancel_all_orders_success_with_orders`**
   - Mock API response as list of 3 cancelled orders
   - Verify return value is `3`
   - Verify log message

10. **`test_cancel_all_orders_success_no_orders`**
    - Mock API response as `{"code": 200, "msg": "..."}`
    - Verify return value is `0`
    - Verify log message

11. **`test_cancel_all_orders_invalid_symbol`**
    - Mock API error with code `-1121`
    - Verify `ValidationError` raised

12. **`test_cancel_all_orders_api_error`**
    - Mock network error
    - Verify `OrderExecutionError` raised

### 7.2 Integration Tests (Testnet)

**Prerequisites**:
- Binance Testnet account with API keys
- Small USDT balance for testing
- Test position opened manually or via API

**Test Scenarios**:

1. **Integration: Get Position (Active Position)**
   ```python
   # Manually open a small long position on Testnet
   position = manager.get_position('BTCUSDT')
   assert position is not None
   assert position.side == "LONG"
   assert position.quantity > 0
   assert position.entry_price > 0
   ```

2. **Integration: Get Position (No Position)**
   ```python
   # Ensure no position exists for a symbol
   position = manager.get_position('ETHUSDT')
   assert position is None
   ```

3. **Integration: Get Account Balance**
   ```python
   balance = manager.get_account_balance()
   assert isinstance(balance, float)
   assert balance >= 0
   ```

4. **Integration: Cancel All Orders**
   ```python
   # Place 2 test limit orders
   # Then cancel all
   cancelled = manager.cancel_all_orders('BTCUSDT')
   assert cancelled == 2

   # Verify orders are cancelled
   cancelled_again = manager.cancel_all_orders('BTCUSDT')
   assert cancelled_again == 0
   ```

### 7.3 Test Data Examples

**Mock Position Response (LONG)**:
```python
MOCK_POSITION_LONG = [{
    "symbol": "BTCUSDT",
    "positionAmt": "0.001",
    "entryPrice": "50000.00",
    "unRealizedProfit": "10.25",
    "leverage": "20",
    "isolated": True,
    "isolatedWallet": "100.00",
    "positionSide": "BOTH",
    "liquidationPrice": "45000.00",
    "markPrice": "50500.00",
    "updateTime": 1678886400000
}]
```

**Mock Position Response (SHORT)**:
```python
MOCK_POSITION_SHORT = [{
    "symbol": "BTCUSDT",
    "positionAmt": "-0.001",
    "entryPrice": "50000.00",
    "unRealizedProfit": "-5.50",
    "leverage": "10",
    "liquidationPrice": "55000.00",
    ...
}]
```

**Mock Account Response**:
```python
MOCK_ACCOUNT = {
    "feeTier": 0,
    "canTrade": True,
    "assets": [
        {
            "asset": "USDT",
            "walletBalance": "1234.56",
            "unrealizedProfit": "10.25",
            ...
        },
        {
            "asset": "BTC",
            "walletBalance": "0.001",
            ...
        }
    ],
    "positions": [...]
}
```

**Mock Cancel Orders Response (With Orders)**:
```python
MOCK_CANCEL_WITH_ORDERS = [
    {
        "orderId": 123456,
        "symbol": "BTCUSDT",
        "status": "CANCELED",
        "clientOrderId": "order1",
        ...
    },
    {
        "orderId": 123457,
        "symbol": "BTCUSDT",
        "status": "CANCELED",
        "clientOrderId": "order2",
        ...
    }
]
```

**Mock Cancel Orders Response (No Orders)**:
```python
MOCK_CANCEL_NO_ORDERS = {
    "code": 200,
    "msg": "The operation of cancel all open order is done."
}
```

---

## 8. Success Criteria

### 8.1 Functional Success

- ✅ `get_position()` retrieves and parses position data correctly
- ✅ `get_position()` returns `None` for zero positions
- ✅ Position side correctly determined from `positionAmt` sign
- ✅ `get_account_balance()` extracts USDT balance from assets array
- ✅ `get_account_balance()` returns `0.0` when USDT not found
- ✅ `cancel_all_orders()` cancels all open orders for symbol
- ✅ `cancel_all_orders()` returns correct count of cancelled orders

### 8.2 Error Handling Success

- ✅ Invalid symbols raise `ValidationError`
- ✅ API authentication failures raise `OrderExecutionError`
- ✅ Network errors raise `OrderExecutionError`
- ✅ Parsing errors raise `OrderExecutionError` with details
- ✅ All errors are logged with appropriate severity

### 8.3 Testing Success

- ✅ All 12 unit tests pass
- ✅ Code coverage >90% on new methods
- ✅ Integration tests pass on Binance Testnet
- ✅ All test scenarios documented and reproducible

### 8.4 Code Quality Success

- ✅ Code follows existing style and conventions
- ✅ Docstrings are comprehensive with examples
- ✅ Type hints are correct for all signatures
- ✅ Logging is informative and actionable
- ✅ No code duplication (DRY principle)
- ✅ Consistent error handling across all methods

---

## Appendix A: API Call Examples

### Example 1: Query LONG Position

**Request**:
```python
response = client.get_position_risk(symbol="BTCUSDT")
```

**Response**:
```json
[{
  "symbol": "BTCUSDT",
  "positionAmt": "0.001",
  "entryPrice": "50000.00",
  "unRealizedProfit": "10.25",
  "leverage": "20",
  "liquidationPrice": "45000.00",
  ...
}]
```

**Parsed Position**:
```python
Position(
    symbol="BTCUSDT",
    side="LONG",
    entry_price=50000.0,
    quantity=0.001,
    leverage=20,
    unrealized_pnl=10.25,
    liquidation_price=45000.0
)
```

### Example 2: Query Account Balance

**Request**:
```python
response = client.account()
```

**Response** (simplified):
```json
{
  "assets": [
    {"asset": "USDT", "walletBalance": "1234.56"},
    {"asset": "BTC", "walletBalance": "0.001"}
  ]
}
```

**Extracted Balance**:
```python
balance = 1234.56  # USDT walletBalance
```

### Example 3: Cancel All Orders

**Request**:
```python
response = client.cancel_open_orders(symbol="BTCUSDT")
```

**Response Option 1** (orders cancelled):
```json
[
  {"orderId": 123456, "symbol": "BTCUSDT", "status": "CANCELED"},
  {"orderId": 123457, "symbol": "BTCUSDT", "status": "CANCELED"}
]
```

**Response Option 2** (no orders):
```json
{
  "code": 200,
  "msg": "The operation of cancel all open order is done."
}
```

**Return Values**:
- Option 1: `2` (count of cancelled orders)
- Option 2: `0` (no orders to cancel)

---

## Appendix B: Code Structure

```
src/execution/order_manager.py
├── get_position(symbol: str) -> Optional[Position]
│   ├── Validate input
│   ├── Call client.get_position_risk()
│   ├── Parse response
│   ├── Determine side from positionAmt sign
│   ├── Create Position object or return None
│   └── Error handling
│
├── get_account_balance() -> float
│   ├── Call client.account()
│   ├── Extract assets array
│   ├── Find USDT in assets
│   ├── Return walletBalance or 0.0
│   └── Error handling
│
└── cancel_all_orders(symbol: str) -> int
    ├── Validate input
    ├── Call client.cancel_open_orders()
    ├── Parse response (list or dict)
    ├── Return count of cancelled orders
    └── Error handling

tests/test_order_execution.py
└── TestQueryMethods
    ├── test_get_position_long_success
    ├── test_get_position_short_success
    ├── test_get_position_no_position
    ├── test_get_position_invalid_symbol
    ├── test_get_position_api_error
    ├── test_get_account_balance_success
    ├── test_get_account_balance_usdt_not_found
    ├── test_get_account_balance_api_error
    ├── test_cancel_all_orders_success_with_orders
    ├── test_cancel_all_orders_success_no_orders
    ├── test_cancel_all_orders_invalid_symbol
    └── test_cancel_all_orders_api_error
```

---

**End of Design Document**
