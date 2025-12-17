# Task 6.3: TP/SL Order Placement Design Document

**Task ID**: 6.3
**Dependencies**: Subtask 6.2 (execute_signal - COMPLETED)
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

Extend the `OrderExecutionManager.execute_signal()` method to automatically place Take Profit (TP) and Stop Loss (SL) orders after successful market entry execution. This implements automated risk management by placing conditional exit orders that trigger at predetermined price levels.

### 1.2 Scope

- **In Scope**:
  - Place TAKE_PROFIT_MARKET order using `signal.take_profit` price
  - Place STOP_MARKET order using `signal.stop_loss` price
  - Use `closePosition=True` parameter for automatic position closure
  - Use `workingType='MARK_PRICE'` to prevent price manipulation
  - Implement `_format_price()` helper for Binance price precision
  - Change return type from `Order` to `tuple[Order, list[Order]]`
  - Handle partial failures (entry success, TP/SL failure)
  - Log all TP/SL placement attempts and results

- **Out of Scope**:
  - Trailing stop loss (deferred to future enhancement)
  - Partial TP/SL (multiple take profit levels)
  - Dynamic TP/SL adjustment
  - Position sizing based on risk (handled by caller)
  - Symbol-specific precision fetching from exchange info

### 1.3 Key Design Decisions

1. **closePosition=True**: Automatically closes entire position when triggered, eliminating need for quantity calculation
2. **workingType='MARK_PRICE'**: Uses mark price instead of last price to prevent manipulation via low-liquidity trading
3. **Separate API calls**: Place TP and SL as individual orders (not batch) for simpler error handling
4. **Fail-safe approach**: If entry succeeds but TP/SL fails, log error but don't raise exception (position is still opened)
5. **Return tuple**: `(entry_order, [tp_order, sl_order])` to provide complete execution details
6. **Fixed precision**: Use 2 decimal places for USDT prices (defer dynamic precision to Subtask 6.5)

---

## 2. Requirements Analysis

### 2.1 Functional Requirements

**FR1**: After successful market entry order execution, automatically place TP and SL orders
**FR2**: TP order must use TAKE_PROFIT_MARKET order type with `stopPrice=signal.take_profit`
**FR3**: SL order must use STOP_MARKET order type with `stopPrice=signal.stop_loss`
**FR4**: Both TP and SL orders must use `closePosition=True` parameter
**FR5**: Both TP and SL orders must use `workingType='MARK_PRICE'`
**FR6**: Return tuple containing entry order and list of TP/SL orders
**FR7**: Format prices to 2 decimal precision using `_format_price()` helper
**FR8**: Handle entry-only signals (CLOSE_LONG, CLOSE_SHORT) by skipping TP/SL placement

### 2.2 Non-Functional Requirements

**NFR1**: **Reliability**: Entry order must succeed even if TP/SL placement fails
**NFR2**: **Observability**: Log all TP/SL placement attempts with order IDs and prices
**NFR3**: **Maintainability**: Separate TP and SL placement into dedicated helper methods
**NFR4**: **Performance**: Place TP and SL orders sequentially (not critical path for latency)
**NFR5**: **Error Transparency**: Distinguish between entry failures (raise exception) and TP/SL failures (log warning)

### 2.3 Signal Type Mapping for TP/SL

```python
TP/SL Required:
- SignalType.LONG_ENTRY  → Place TP (BUY to close) and SL (SELL to close)
- SignalType.SHORT_ENTRY → Place TP (SELL to close) and SL (BUY to close)

TP/SL NOT Required:
- SignalType.CLOSE_LONG  → No TP/SL (already exiting position)
- SignalType.CLOSE_SHORT → No TP/SL (already exiting position)
```

**Correction**: For TP/SL orders with `closePosition=True`, we don't specify `side` - Binance automatically determines the side to close the position. However, we still need to know the position direction to validate price logic.

---

## 3. API Specification Analysis

### 3.1 Binance TAKE_PROFIT_MARKET Order

**Endpoint**: `POST /fapi/v1/order`
**Purpose**: Places a conditional order that executes as a MARKET order when mark price reaches `stopPrice`

**Required Parameters**:
```python
{
    "symbol": "BTCUSDT",           # Trading pair
    "side": "BUY" or "SELL",       # Order side to close position
    "type": "TAKE_PROFIT_MARKET",  # Order type
    "stopPrice": 52000.0,          # Trigger price (take profit level)
    "closePosition": "true",       # Close entire position (no quantity needed)
    "workingType": "MARK_PRICE"    # Use mark price for trigger
}
```

**Optional Parameters**:
- `priceProtect`: "TRUE" or "FALSE" (default: FALSE) - enables price protection
- `newClientOrderId`: Custom client order ID
- `recvWindow`: Request validity window (max 60000ms)

**Response Structure** (SUCCESS - 200):
```json
{
  "orderId": 123456790,
  "symbol": "BTCUSDT",
  "status": "NEW",                    # Order placed, waiting for trigger
  "clientOrderId": "xxxxx",
  "price": "0.00000000",              # Not applicable for MARKET orders
  "avgPrice": "0.00000000",           # Will be set when triggered
  "origQty": "0.00000000",            # Not applicable with closePosition
  "executedQty": "0.00000000",
  "cumQuote": "0.00000000",
  "timeInForce": "GTE_GTC",           # Good-Til-Expired
  "type": "TAKE_PROFIT_MARKET",
  "reduceOnly": false,
  "closePosition": true,
  "side": "SELL",
  "positionSide": "BOTH",
  "stopPrice": "52000.00",            # Trigger price
  "workingType": "MARK_PRICE",
  "priceProtect": false,
  "origType": "TAKE_PROFIT_MARKET",
  "time": 1678886401000,
  "updateTime": 1678886401000
}
```

### 3.2 Binance STOP_MARKET Order

**Endpoint**: `POST /fapi/v1/order`
**Purpose**: Places a stop-loss order that executes as a MARKET order when mark price reaches `stopPrice`

**Required Parameters**:
```python
{
    "symbol": "BTCUSDT",
    "side": "SELL",                # Order side to close position
    "type": "STOP_MARKET",         # Order type
    "stopPrice": 49000.0,          # Trigger price (stop loss level)
    "closePosition": "true",       # Close entire position
    "workingType": "MARK_PRICE"    # Use mark price for trigger
}
```

**Response Structure**: Same as TAKE_PROFIT_MARKET (status: "NEW", waiting for trigger)

### 3.3 Key API Parameters Explained

**closePosition** (`"true"` or `"false"`):
- When `"true"`, Binance automatically closes the entire position when triggered
- Eliminates need to specify `quantity` parameter
- Works with STOP_MARKET and TAKE_PROFIT_MARKET order types only
- Automatically determines the correct quantity to close the position

**workingType** (`"MARK_PRICE"` or `"CONTRACT_PRICE"`):
- `"MARK_PRICE"` (recommended): Uses Binance's fair price mark, less susceptible to manipulation
- `"CONTRACT_PRICE"`: Uses last traded price, can be manipulated in low-liquidity conditions
- Default is `"CONTRACT_PRICE"` if not specified

**Side Determination for TP/SL**:
```python
# For LONG positions (entry via BUY):
TAKE_PROFIT_MARKET: side="SELL" (close long at profit)
STOP_MARKET: side="SELL" (close long at loss)

# For SHORT positions (entry via SELL):
TAKE_PROFIT_MARKET: side="BUY" (close short at profit)
STOP_MARKET: side="BUY" (close short at loss)
```

### 3.4 API Error Responses

**Common Errors**:
```python
# Invalid stopPrice (too close to current price)
{
  "code": -2010,
  "msg": "Order would immediately trigger."
}

# Invalid parameters
{
  "code": -1102,
  "msg": "Mandatory parameter 'stopPrice' was not sent."
}

# Insufficient margin
{
  "code": -2019,
  "msg": "Margin is insufficient."
}
```

---

## 4. Model Analysis

### 4.1 Signal Model (src/models/signal.py)

**Relevant Fields**:
```python
@dataclass(frozen=True)
class Signal:
    signal_type: SignalType          # LONG_ENTRY, SHORT_ENTRY, CLOSE_LONG, CLOSE_SHORT
    symbol: str                      # Trading pair (e.g., "BTCUSDT")
    entry_price: float               # Expected entry price (for reference)
    take_profit: float               # TP trigger price
    stop_loss: float                 # SL trigger price
    strategy_name: str
    timestamp: datetime
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Validation Logic** (from `__post_init__`):
```python
# For LONG_ENTRY:
if self.signal_type == SignalType.LONG_ENTRY:
    if self.take_profit <= self.entry_price:
        raise ValueError("LONG: take_profit must be > entry_price")
    if self.stop_loss >= self.entry_price:
        raise ValueError("LONG: stop_loss must be < entry_price")

# For SHORT_ENTRY:
elif self.signal_type == SignalType.SHORT_ENTRY:
    if self.take_profit >= self.entry_price:
        raise ValueError("SHORT: take_profit must be < entry_price")
    if self.stop_loss <= self.entry_price:
        raise ValueError("SHORT: stop_loss must be > entry_price")
```

**Key Insight**: Signal validation ensures TP/SL prices are already correct relative to entry direction.

### 4.2 Order Model (src/models/order.py)

**Relevant Fields**:
```python
@dataclass
class Order:
    symbol: str
    side: OrderSide                  # BUY or SELL
    order_type: OrderType            # MARKET, STOP_MARKET, TAKE_PROFIT_MARKET
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None  # Required for STOP/TP orders
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    timestamp: Optional[datetime] = None
```

**Validation Logic** (from `__post_init__`):
```python
# STOP orders require stop_price
if self.order_type in (OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET):
    if self.stop_price is None:
        raise ValueError(f"{self.order_type.value} requires stop_price")
```

### 4.3 OrderType Enum

**Current Values**:
```python
class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    # ... other types
```

**Key Insight**: `STOP_MARKET` and `TAKE_PROFIT_MARKET` are already defined - no enum additions needed.

### 4.4 OrderSide Enum

```python
class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
```

**TP/SL Side Logic**:
```python
# For LONG positions (SignalType.LONG_ENTRY):
TP side: SELL (close long position at profit)
SL side: SELL (close long position at loss)

# For SHORT positions (SignalType.SHORT_ENTRY):
TP side: BUY (close short position at profit)
SL side: BUY (close short position at loss)

# Pattern: TP and SL have SAME side (opposite of entry side)
```

---

## 5. Implementation Design

### 5.1 Method Signature Change

**Current Signature** (Subtask 6.2):
```python
def execute_signal(
    self,
    signal: Signal,
    quantity: float,
    reduce_only: bool = False
) -> Order:
    """Execute signal by placing market order"""
```

**New Signature** (Subtask 6.3):
```python
def execute_signal(
    self,
    signal: Signal,
    quantity: float,
    reduce_only: bool = False
) -> tuple[Order, list[Order]]:
    """
    Execute signal by placing market order with TP/SL orders.

    Returns:
        tuple[Order, list[Order]]: (entry_order, [tp_order, sl_order])
        - For LONG_ENTRY/SHORT_ENTRY: list contains 2 orders [TP, SL]
        - For CLOSE_LONG/CLOSE_SHORT: list is empty []
    """
```

### 5.2 Helper Method: _format_price()

**Purpose**: Format price to Binance-compatible precision (2 decimal places for USDT pairs)

**Signature**:
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

**Implementation**:
```python
def _format_price(self, price: float, symbol: str) -> str:
    """Format price to appropriate decimal precision."""
    # Fixed 2 decimal precision for USDT pairs
    # Subtask 6.5 will implement dynamic precision
    return f"{price:.2f}"
```

### 5.3 Helper Method: _place_tp_order()

**Purpose**: Place TAKE_PROFIT_MARKET order after successful entry

**Signature**:
```python
def _place_tp_order(
    self,
    signal: Signal,
    side: OrderSide
) -> Optional[Order]:
    """
    Place TAKE_PROFIT_MARKET order for position exit.

    Args:
        signal: Trading signal with take_profit price
        side: Order side to close position (opposite of entry)

    Returns:
        Order object if successful, None if placement fails

    Note:
        Failures are logged but not raised to avoid failing the entire trade.
    """
```

**Implementation**:
```python
def _place_tp_order(
    self,
    signal: Signal,
    side: OrderSide
) -> Optional[Order]:
    """Place TAKE_PROFIT_MARKET order."""
    try:
        # Format stop price to Binance precision
        stop_price_str = self._format_price(signal.take_profit, signal.symbol)

        # Log TP order intent
        self.logger.info(
            f"Placing TP order: {signal.symbol} {side.value} "
            f"@ {stop_price_str} (close position)"
        )

        # Place TAKE_PROFIT_MARKET order via Binance API
        response = self.client.new_order(
            symbol=signal.symbol,
            side=side.value,                      # SELL for long, BUY for short
            type=OrderType.TAKE_PROFIT_MARKET.value,  # "TAKE_PROFIT_MARKET"
            stopPrice=stop_price_str,             # Trigger price (formatted)
            closePosition="true",                 # Close entire position
            workingType="MARK_PRICE"              # Use mark price for trigger
        )

        # Parse API response into Order object
        order = self._parse_order_response(
            response=response,
            symbol=signal.symbol,
            side=side
        )

        # Override order_type (response parsing sets it to MARKET)
        order.order_type = OrderType.TAKE_PROFIT_MARKET
        order.stop_price = signal.take_profit

        # Log successful placement
        self.logger.info(
            f"TP order placed: ID={order.order_id}, "
            f"stopPrice={stop_price_str}"
        )

        return order

    except ClientError as e:
        # Binance API error (4xx) - log but don't raise
        self.logger.error(
            f"TP order rejected: code={e.error_code}, "
            f"msg={e.error_message}"
        )
        return None

    except Exception as e:
        # Unexpected error - log but don't raise
        self.logger.error(
            f"TP order placement failed: {type(e).__name__}: {e}"
        )
        return None
```

### 5.4 Helper Method: _place_sl_order()

**Purpose**: Place STOP_MARKET order after successful entry

**Signature**:
```python
def _place_sl_order(
    self,
    signal: Signal,
    side: OrderSide
) -> Optional[Order]:
    """
    Place STOP_MARKET order for position exit.

    Args:
        signal: Trading signal with stop_loss price
        side: Order side to close position (opposite of entry)

    Returns:
        Order object if successful, None if placement fails

    Note:
        Failures are logged but not raised to avoid failing the entire trade.
    """
```

**Implementation**:
```python
def _place_sl_order(
    self,
    signal: Signal,
    side: OrderSide
) -> Optional[Order]:
    """Place STOP_MARKET order."""
    try:
        # Format stop price to Binance precision
        stop_price_str = self._format_price(signal.stop_loss, signal.symbol)

        # Log SL order intent
        self.logger.info(
            f"Placing SL order: {signal.symbol} {side.value} "
            f"@ {stop_price_str} (close position)"
        )

        # Place STOP_MARKET order via Binance API
        response = self.client.new_order(
            symbol=signal.symbol,
            side=side.value,                      # SELL for long, BUY for short
            type=OrderType.STOP_MARKET.value,     # "STOP_MARKET"
            stopPrice=stop_price_str,             # Trigger price (formatted)
            closePosition="true",                 # Close entire position
            workingType="MARK_PRICE"              # Use mark price for trigger
        )

        # Parse API response into Order object
        order = self._parse_order_response(
            response=response,
            symbol=signal.symbol,
            side=side
        )

        # Override order_type and stop_price
        order.order_type = OrderType.STOP_MARKET
        order.stop_price = signal.stop_loss

        # Log successful placement
        self.logger.info(
            f"SL order placed: ID={order.order_id}, "
            f"stopPrice={stop_price_str}"
        )

        return order

    except ClientError as e:
        # Binance API error - log but don't raise
        self.logger.error(
            f"SL order rejected: code={e.error_code}, "
            f"msg={e.error_message}"
        )
        return None

    except Exception as e:
        # Unexpected error - log but don't raise
        self.logger.error(
            f"SL order placement failed: {type(e).__name__}: {e}"
        )
        return None
```

### 5.5 Updated execute_signal() Implementation

**High-Level Flow**:
```
1. Validate inputs (quantity > 0)
2. Determine order side from signal type
3. Log order intent
4. Place MARKET entry order (existing logic from 6.2)
5. Parse entry order response
6. Log successful entry

7. Check if TP/SL needed (only for LONG_ENTRY, SHORT_ENTRY)
8. If needed:
   a. Determine TP/SL side (opposite of entry side)
   b. Place TP order via _place_tp_order()
   c. Place SL order via _place_sl_order()
   d. Collect successful orders into list
   e. Log TP/SL placement summary

9. Return (entry_order, [tp_order, sl_order])
```

**Implementation**:
```python
def execute_signal(
    self,
    signal: Signal,
    quantity: float,
    reduce_only: bool = False
) -> tuple[Order, list[Order]]:
    """
    Execute trading signal by placing market order with TP/SL orders.

    Translates Signal objects into Binance market orders, handling order side
    determination, API submission, and response parsing. For entry signals
    (LONG_ENTRY, SHORT_ENTRY), automatically places TP and SL orders.

    Args:
        signal: Trading signal containing entry parameters
        quantity: Order size in base asset (e.g., BTC for BTCUSDT)
        reduce_only: If True, order only reduces existing position

    Returns:
        tuple[Order, list[Order]]: (entry_order, [tp_order, sl_order])
        - For LONG_ENTRY/SHORT_ENTRY: list contains 2 orders [TP, SL]
        - For CLOSE_LONG/CLOSE_SHORT: list is empty []

    Raises:
        ValidationError: Invalid signal type or quantity <= 0
        OrderRejectedError: Binance rejected the entry order
        OrderExecutionError: Entry order API call failed

    Note:
        TP/SL placement failures are logged but don't raise exceptions.
        Entry order must succeed; TP/SL failures result in partial execution.

    Example:
        >>> signal = Signal(
        ...     signal_type=SignalType.LONG_ENTRY,
        ...     symbol='BTCUSDT',
        ...     entry_price=50000.0,
        ...     take_profit=52000.0,
        ...     stop_loss=49000.0,
        ...     strategy_name='SMA_Crossover',
        ...     timestamp=datetime.now(timezone.utc)
        ... )
        >>> entry_order, tpsl_orders = manager.execute_signal(signal, quantity=0.001)
        >>> print(f"Entry ID: {entry_order.order_id}")
        >>> print(f"TP/SL placed: {len(tpsl_orders)}")
        Entry ID: 123456789
        TP/SL placed: 2
    """
    # 1. Validate inputs
    if quantity <= 0:
        raise ValidationError(f"Quantity must be > 0, got {quantity}")

    # 2. Determine order side from signal type
    side = self._determine_order_side(signal)

    # 3. Log order intent
    self.logger.info(
        f"Executing {signal.signal_type.value} signal: "
        f"{signal.symbol} {side.value} {quantity} "
        f"(strategy: {signal.strategy_name})"
    )

    # 4-6. Place market entry order (existing logic from 6.2)
    try:
        response = self.client.new_order(
            symbol=signal.symbol,
            side=side.value,           # "BUY" or "SELL"
            type=OrderType.MARKET.value,  # "MARKET"
            quantity=quantity,
            reduceOnly=reduce_only
        )

        # Parse API response into Order object
        entry_order = self._parse_order_response(
            response=response,
            symbol=signal.symbol,
            side=side
        )

        # Log successful execution
        self.logger.info(
            f"Entry order executed: ID={entry_order.order_id}, "
            f"status={entry_order.status.value}, "
            f"filled={entry_order.quantity} @ {entry_order.price}"
        )

    except ClientError as e:
        # Binance API errors (4xx status codes)
        self.logger.error(
            f"Entry order rejected by Binance: "
            f"code={e.error_code}, msg={e.error_message}"
        )
        raise OrderRejectedError(
            f"Binance rejected order: {e.error_message}"
        ) from e

    except Exception as e:
        # Unexpected errors (network, parsing, etc.)
        self.logger.error(
            f"Entry order execution failed: {type(e).__name__}: {e}"
        )
        raise OrderExecutionError(
            f"Failed to execute order: {e}"
        ) from e

    # 7. Check if TP/SL orders are needed
    tpsl_orders: list[Order] = []

    # Only place TP/SL for entry signals (not for close signals)
    if signal.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
        # 8a. Determine TP/SL side (opposite of entry side)
        # For LONG_ENTRY: entry is BUY → TP/SL are SELL
        # For SHORT_ENTRY: entry is SELL → TP/SL are BUY
        tpsl_side = (
            OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        )

        # 8b. Place TP order
        tp_order = self._place_tp_order(signal, tpsl_side)
        if tp_order:
            tpsl_orders.append(tp_order)

        # 8c. Place SL order
        sl_order = self._place_sl_order(signal, tpsl_side)
        if sl_order:
            tpsl_orders.append(sl_order)

        # 8e. Log TP/SL summary
        self.logger.info(
            f"TP/SL placement complete: {len(tpsl_orders)}/2 orders placed"
        )

        if len(tpsl_orders) < 2:
            self.logger.warning(
                f"Partial TP/SL placement: entry filled but "
                f"only {len(tpsl_orders)}/2 exit orders placed"
            )

    # 9. Return entry order and TP/SL orders
    return (entry_order, tpsl_orders)
```

### 5.6 Updated _parse_order_response()

**Note**: The existing `_parse_order_response()` needs a minor update to handle TP/SL order responses:

```python
def _parse_order_response(
    self,
    response: Dict[str, Any],
    symbol: str,
    side: OrderSide
) -> Order:
    """
    Parse Binance API response into Order object.

    Handles responses for MARKET, STOP_MARKET, and TAKE_PROFIT_MARKET orders.
    """
    try:
        # Extract required fields
        order_id = str(response["orderId"])
        status_str = response["status"]

        # For MARKET orders: origQty is filled quantity
        # For STOP/TP orders: origQty may be "0" when using closePosition
        quantity = float(response.get("origQty", "0"))

        # Parse execution price (avgPrice for market orders)
        avg_price = float(response.get("avgPrice", "0"))

        # Convert timestamp (milliseconds → datetime)
        timestamp_ms = response["updateTime"]
        timestamp = datetime.fromtimestamp(
            timestamp_ms / 1000,
            tz=timezone.utc
        )

        # Map Binance status string to OrderStatus enum
        status = OrderStatus[status_str]  # Raises KeyError if invalid

        # Determine order type from response
        order_type_str = response.get("type", "MARKET")
        order_type = OrderType[order_type_str]

        # Extract stop price for STOP/TP orders
        stop_price = None
        if "stopPrice" in response and response["stopPrice"]:
            stop_price = float(response["stopPrice"])

        # Create Order object
        return Order(
            symbol=symbol,
            side=side,
            order_type=order_type,  # Will be MARKET, STOP_MARKET, or TAKE_PROFIT_MARKET
            quantity=quantity,
            price=avg_price if avg_price > 0 else None,
            stop_price=stop_price,
            order_id=order_id,
            client_order_id=response.get("clientOrderId"),
            status=status,
            timestamp=timestamp
        )

    except KeyError as e:
        raise OrderExecutionError(
            f"Missing required field in API response: {e}"
        )
    except (ValueError, TypeError) as e:
        raise OrderExecutionError(
            f"Invalid data type in API response: {e}"
        )
```

---

## 6. Error Handling Strategy

### 6.1 Error Categories

**Category 1: Entry Order Failures** (CRITICAL - Raise Exception)
- Validation errors (quantity <= 0, invalid signal type)
- Binance API rejections (insufficient margin, invalid parameters)
- Network failures during entry order placement
- **Action**: Raise exception, abort entire operation

**Category 2: TP/SL Order Failures** (WARNING - Log and Continue)
- Binance API rejections for TP/SL orders
- Network failures during TP/SL placement
- Invalid stopPrice (too close to current price)
- **Action**: Log error, return partial result (entry order succeeded)

### 6.2 Failure Scenarios

**Scenario 1: Entry order fails**
```python
Result: Raise OrderRejectedError or OrderExecutionError
Cleanup: None needed (no orders placed)
User Action: Fix issue and retry
```

**Scenario 2: Entry succeeds, TP order fails, SL succeeds**
```python
Result: Return (entry_order, [sl_order])
Logging: ERROR for TP failure, INFO for successful orders
User Action: Manually place TP order or monitor position
```

**Scenario 3: Entry succeeds, both TP and SL fail**
```python
Result: Return (entry_order, [])
Logging: ERROR for both TP and SL failures
Warning: "Partial TP/SL placement: entry filled but only 0/2 exit orders placed"
User Action: Manually place TP/SL orders or close position
```

**Scenario 4: Entry succeeds, TP succeeds, SL fails**
```python
Result: Return (entry_order, [tp_order])
Logging: ERROR for SL failure, INFO for successful orders
User Action: Manually place SL order for risk management
```

### 6.3 Logging Strategy

**Entry Order Logging**:
```python
# Intent
INFO: "Executing LONG_ENTRY signal: BTCUSDT BUY 0.001 (strategy: SMA_Crossover)"

# Success
INFO: "Entry order executed: ID=123456789, status=FILLED, filled=0.001 @ 50123.45"

# Failure
ERROR: "Entry order rejected by Binance: code=-2019, msg=Margin is insufficient"
ERROR: "Entry order execution failed: ConnectionError: Connection timeout"
```

**TP/SL Order Logging**:
```python
# Intent
INFO: "Placing TP order: BTCUSDT SELL @ 52000.00 (close position)"
INFO: "Placing SL order: BTCUSDT SELL @ 49000.00 (close position)"

# Success
INFO: "TP order placed: ID=123456790, stopPrice=52000.00"
INFO: "SL order placed: ID=123456791, stopPrice=49000.00"
INFO: "TP/SL placement complete: 2/2 orders placed"

# Partial Failure
ERROR: "TP order rejected: code=-2010, msg=Order would immediately trigger"
INFO: "SL order placed: ID=123456791, stopPrice=49000.00"
WARNING: "Partial TP/SL placement: entry filled but only 1/2 exit orders placed"

# Complete Failure
ERROR: "TP order rejected: code=-2010, msg=Order would immediately trigger"
ERROR: "SL order placement failed: ConnectionError: Connection timeout"
WARNING: "Partial TP/SL placement: entry filled but only 0/2 exit orders placed"
```

---

## 7. Testing Strategy

### 7.1 Unit Test Structure

**Test Class**: `TestTPSLPlacement` (extends existing TestExecuteSignal)

**Test Coverage**:
1. Helper method tests (3 tests)
2. TP order placement tests (4 tests)
3. SL order placement tests (4 tests)
4. Integration tests (6 tests)
5. Error handling tests (5 tests)

**Total**: 22 new tests

### 7.2 Test Cases

#### 7.2.1 Helper Method Tests

**test_format_price_rounds_correctly**:
```python
def test_format_price_rounds_correctly(self, manager):
    """Test price formatting with 2 decimal precision"""
    assert manager._format_price(50123.456, 'BTCUSDT') == '50123.46'
    assert manager._format_price(50123.444, 'BTCUSDT') == '50123.44'
    assert manager._format_price(50123.0, 'BTCUSDT') == '50123.00'
```

**test_format_price_handles_edge_cases**:
```python
def test_format_price_handles_edge_cases(self, manager):
    """Test price formatting edge cases"""
    assert manager._format_price(0.01, 'BTCUSDT') == '0.01'
    assert manager._format_price(99999.99, 'BTCUSDT') == '99999.99'
```

#### 7.2.2 TP Order Placement Tests

**test_place_tp_order_long_success**:
```python
def test_place_tp_order_long_success(self, manager, mock_client, long_entry_signal):
    """Test successful TP order placement for LONG position"""
    # Mock Binance API response
    mock_client.new_order.return_value = {
        "orderId": 987654321,
        "symbol": "BTCUSDT",
        "status": "NEW",
        "type": "TAKE_PROFIT_MARKET",
        "side": "SELL",
        "stopPrice": "52000.00",
        "closePosition": True,
        "workingType": "MARK_PRICE",
        "updateTime": 1678886401000,
        "origQty": "0.000",
        "avgPrice": "0.00"
    }

    # Place TP order
    tp_order = manager._place_tp_order(long_entry_signal, OrderSide.SELL)

    # Assertions
    assert tp_order is not None
    assert tp_order.order_id == "987654321"
    assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == 52000.0
    assert tp_order.side == OrderSide.SELL

    # Verify API call
    mock_client.new_order.assert_called_once_with(
        symbol="BTCUSDT",
        side="SELL",
        type="TAKE_PROFIT_MARKET",
        stopPrice="52000.00",
        closePosition="true",
        workingType="MARK_PRICE"
    )
```

**test_place_tp_order_short_success**:
```python
def test_place_tp_order_short_success(self, manager, mock_client, short_entry_signal):
    """Test successful TP order placement for SHORT position"""
    # Mock response for SHORT (side=BUY to close)
    mock_client.new_order.return_value = {
        "orderId": 987654322,
        "symbol": "BTCUSDT",
        "status": "NEW",
        "type": "TAKE_PROFIT_MARKET",
        "side": "BUY",
        "stopPrice": "48000.00",
        "updateTime": 1678886401000,
        "origQty": "0.000",
        "avgPrice": "0.00"
    }

    tp_order = manager._place_tp_order(short_entry_signal, OrderSide.BUY)

    assert tp_order is not None
    assert tp_order.side == OrderSide.BUY
    assert tp_order.stop_price == 48000.0
```

**test_place_tp_order_api_error_returns_none**:
```python
def test_place_tp_order_api_error_returns_none(self, manager, mock_client, long_entry_signal):
    """Test TP order returns None on API error"""
    from binance.error import ClientError

    # Mock API error
    mock_client.new_order.side_effect = ClientError(
        status_code=400,
        error_code=-2010,
        error_message="Order would immediately trigger"
    )

    tp_order = manager._place_tp_order(long_entry_signal, OrderSide.SELL)

    assert tp_order is None  # Should return None, not raise
```

#### 7.2.3 SL Order Placement Tests

**test_place_sl_order_long_success**:
```python
def test_place_sl_order_long_success(self, manager, mock_client, long_entry_signal):
    """Test successful SL order placement for LONG position"""
    mock_client.new_order.return_value = {
        "orderId": 987654323,
        "symbol": "BTCUSDT",
        "status": "NEW",
        "type": "STOP_MARKET",
        "side": "SELL",
        "stopPrice": "49000.00",
        "closePosition": True,
        "workingType": "MARK_PRICE",
        "updateTime": 1678886402000,
        "origQty": "0.000",
        "avgPrice": "0.00"
    }

    sl_order = manager._place_sl_order(long_entry_signal, OrderSide.SELL)

    assert sl_order is not None
    assert sl_order.order_type == OrderType.STOP_MARKET
    assert sl_order.stop_price == 49000.0
```

**test_place_sl_order_short_success**:
```python
def test_place_sl_order_short_success(self, manager, mock_client, short_entry_signal):
    """Test successful SL order placement for SHORT position"""
    # Implementation similar to TP test for SHORT
    pass
```

**test_place_sl_order_network_error_returns_none**:
```python
def test_place_sl_order_network_error_returns_none(self, manager, mock_client, long_entry_signal):
    """Test SL order returns None on network error"""
    mock_client.new_order.side_effect = ConnectionError("Network timeout")

    sl_order = manager._place_sl_order(long_entry_signal, OrderSide.SELL)

    assert sl_order is None  # Should not raise exception
```

#### 7.2.4 Integration Tests

**test_execute_signal_long_entry_with_tpsl_success**:
```python
def test_execute_signal_long_entry_with_tpsl_success(
    self, manager, mock_client, long_entry_signal
):
    """Test complete LONG entry with TP and SL placement"""
    # Mock entry order response
    mock_client.new_order.side_effect = [
        # Entry order (MARKET)
        {
            "orderId": 123456789,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "type": "MARKET",
            "side": "BUY",
            "avgPrice": "50123.45",
            "origQty": "0.001",
            "executedQty": "0.001",
            "updateTime": 1678886400000
        },
        # TP order (TAKE_PROFIT_MARKET)
        {
            "orderId": 123456790,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "TAKE_PROFIT_MARKET",
            "side": "SELL",
            "stopPrice": "52000.00",
            "updateTime": 1678886401000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        },
        # SL order (STOP_MARKET)
        {
            "orderId": 123456791,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "STOP_MARKET",
            "side": "SELL",
            "stopPrice": "49000.00",
            "updateTime": 1678886402000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        }
    ]

    # Execute signal
    entry_order, tpsl_orders = manager.execute_signal(
        long_entry_signal,
        quantity=0.001
    )

    # Assertions - Entry order
    assert entry_order.order_id == "123456789"
    assert entry_order.order_type == OrderType.MARKET
    assert entry_order.side == OrderSide.BUY
    assert entry_order.status == OrderStatus.FILLED

    # Assertions - TP/SL orders
    assert len(tpsl_orders) == 2

    tp_order = tpsl_orders[0]
    assert tp_order.order_type == OrderType.TAKE_PROFIT_MARKET
    assert tp_order.stop_price == 52000.0
    assert tp_order.side == OrderSide.SELL

    sl_order = tpsl_orders[1]
    assert sl_order.order_type == OrderType.STOP_MARKET
    assert sl_order.stop_price == 49000.0
    assert sl_order.side == OrderSide.SELL

    # Verify API calls
    assert mock_client.new_order.call_count == 3
```

**test_execute_signal_short_entry_with_tpsl_success**:
```python
def test_execute_signal_short_entry_with_tpsl_success(
    self, manager, mock_client, short_entry_signal
):
    """Test complete SHORT entry with TP and SL placement"""
    # Similar to LONG test but with SHORT signal and BUY for TP/SL
    pass
```

**test_execute_signal_close_long_no_tpsl**:
```python
def test_execute_signal_close_long_no_tpsl(
    self, manager, mock_client, close_long_signal
):
    """Test CLOSE_LONG signal doesn't place TP/SL orders"""
    # Mock only entry order (no TP/SL)
    mock_client.new_order.return_value = {
        "orderId": 123456789,
        "symbol": "BTCUSDT",
        "status": "FILLED",
        "type": "MARKET",
        "side": "SELL",
        "avgPrice": "51000.00",
        "origQty": "0.001",
        "executedQty": "0.001",
        "updateTime": 1678886400000
    }

    entry_order, tpsl_orders = manager.execute_signal(
        close_long_signal,
        quantity=0.001
    )

    # Assertions
    assert entry_order.side == OrderSide.SELL
    assert len(tpsl_orders) == 0  # No TP/SL for close signals
    assert mock_client.new_order.call_count == 1  # Only entry order
```

**test_execute_signal_close_short_no_tpsl**:
```python
def test_execute_signal_close_short_no_tpsl(
    self, manager, mock_client, close_short_signal
):
    """Test CLOSE_SHORT signal doesn't place TP/SL orders"""
    # Similar to CLOSE_LONG test
    pass
```

#### 7.2.5 Error Handling Tests

**test_execute_signal_entry_fails_raises_exception**:
```python
def test_execute_signal_entry_fails_raises_exception(
    self, manager, mock_client, long_entry_signal
):
    """Test entry failure raises exception (no TP/SL attempted)"""
    from binance.error import ClientError

    mock_client.new_order.side_effect = ClientError(
        status_code=400,
        error_code=-2019,
        error_message="Margin is insufficient"
    )

    with pytest.raises(OrderRejectedError, match="Margin is insufficient"):
        manager.execute_signal(long_entry_signal, quantity=0.001)

    # Verify only entry order was attempted (no TP/SL calls)
    assert mock_client.new_order.call_count == 1
```

**test_execute_signal_entry_success_tp_fails_sl_success**:
```python
def test_execute_signal_entry_success_tp_fails_sl_success(
    self, manager, mock_client, long_entry_signal
):
    """Test partial TP/SL: entry OK, TP fails, SL OK"""
    from binance.error import ClientError

    mock_client.new_order.side_effect = [
        # Entry order succeeds
        {
            "orderId": 123456789,
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "type": "MARKET",
            "side": "BUY",
            "avgPrice": "50123.45",
            "origQty": "0.001",
            "updateTime": 1678886400000
        },
        # TP order fails
        ClientError(
            status_code=400,
            error_code=-2010,
            error_message="Order would immediately trigger"
        ),
        # SL order succeeds
        {
            "orderId": 123456791,
            "symbol": "BTCUSDT",
            "status": "NEW",
            "type": "STOP_MARKET",
            "side": "SELL",
            "stopPrice": "49000.00",
            "updateTime": 1678886402000,
            "origQty": "0.000",
            "avgPrice": "0.00"
        }
    ]

    entry_order, tpsl_orders = manager.execute_signal(
        long_entry_signal,
        quantity=0.001
    )

    # Entry succeeded
    assert entry_order.status == OrderStatus.FILLED

    # Only SL order placed (TP failed)
    assert len(tpsl_orders) == 1
    assert tpsl_orders[0].order_type == OrderType.STOP_MARKET
```

**test_execute_signal_entry_success_both_tpsl_fail**:
```python
def test_execute_signal_entry_success_both_tpsl_fail(
    self, manager, mock_client, long_entry_signal
):
    """Test entry succeeds but both TP and SL fail"""
    from binance.error import ClientError

    mock_client.new_order.side_effect = [
        # Entry succeeds
        {...},  # Entry order response
        # TP fails
        ClientError(status_code=400, error_code=-2010, error_message="TP error"),
        # SL fails
        ClientError(status_code=400, error_code=-2010, error_message="SL error")
    ]

    entry_order, tpsl_orders = manager.execute_signal(
        long_entry_signal,
        quantity=0.001
    )

    # Entry succeeded, no TP/SL orders
    assert entry_order.status == OrderStatus.FILLED
    assert len(tpsl_orders) == 0
```

### 7.3 Test Fixtures

**Add new fixtures** to `tests/conftest.py`:

```python
@pytest.fixture
def short_entry_signal():
    """Create SHORT_ENTRY signal for testing"""
    return Signal(
        signal_type=SignalType.SHORT_ENTRY,
        symbol='BTCUSDT',
        entry_price=50000.0,
        take_profit=48000.0,  # Below entry (profit for short)
        stop_loss=51000.0,    # Above entry (loss for short)
        strategy_name='Test_Strategy',
        timestamp=datetime.now(timezone.utc)
    )

@pytest.fixture
def close_long_signal():
    """Create CLOSE_LONG signal for testing"""
    return Signal(
        signal_type=SignalType.CLOSE_LONG,
        symbol='BTCUSDT',
        entry_price=51000.0,
        take_profit=52000.0,  # Not used for close signals
        stop_loss=49000.0,    # Not used for close signals
        strategy_name='Test_Strategy',
        timestamp=datetime.now(timezone.utc)
    )

@pytest.fixture
def close_short_signal():
    """Create CLOSE_SHORT signal for testing"""
    return Signal(
        signal_type=SignalType.CLOSE_SHORT,
        symbol='BTCUSDT',
        entry_price=49000.0,
        take_profit=48000.0,  # Not used
        stop_loss=51000.0,    # Not used
        strategy_name='Test_Strategy',
        timestamp=datetime.now(timezone.utc)
    )
```

### 7.4 Coverage Expectations

**Target Coverage**: >90% for order_manager.py

**Expected Coverage by Method**:
- `_format_price()`: 100%
- `_place_tp_order()`: >95%
- `_place_sl_order()`: >95%
- `execute_signal()`: >95%

**Coverage Report Command**:
```bash
pytest tests/test_order_execution.py::TestTPSLPlacement -v --cov=src/execution/order_manager --cov-report=term-missing
```

---

## 8. Success Criteria

### 8.1 Functional Success

- [ ] `_format_price()` formats prices to 2 decimal places correctly
- [ ] `_place_tp_order()` places TAKE_PROFIT_MARKET orders with correct parameters
- [ ] `_place_sl_order()` places STOP_MARKET orders with correct parameters
- [ ] `execute_signal()` returns tuple `(entry_order, [tp_order, sl_order])` for entry signals
- [ ] `execute_signal()` returns tuple `(entry_order, [])` for close signals
- [ ] TP/SL orders use `closePosition="true"` parameter
- [ ] TP/SL orders use `workingType="MARK_PRICE"` parameter
- [ ] TP/SL side is correctly determined (opposite of entry side)

### 8.2 Error Handling Success

- [ ] Entry order failures raise appropriate exceptions (ValidationError, OrderRejectedError, OrderExecutionError)
- [ ] TP/SL failures are logged but don't raise exceptions
- [ ] Partial TP/SL failures result in partial order list
- [ ] All failures are logged with appropriate severity (ERROR, WARNING)

### 8.3 Testing Success

- [ ] All 22 new unit tests pass
- [ ] Code coverage remains >90% on order_manager.py
- [ ] Integration tests cover all signal types (LONG_ENTRY, SHORT_ENTRY, CLOSE_LONG, CLOSE_SHORT)
- [ ] Error scenarios are comprehensively tested (entry failures, partial TP/SL failures, complete failures)

### 8.4 Code Quality Success

- [ ] Code follows existing style and conventions
- [ ] Docstrings are comprehensive and accurate
- [ ] Type hints are correct for new return type `tuple[Order, list[Order]]`
- [ ] Logging is informative and actionable
- [ ] No code duplication between `_place_tp_order()` and `_place_sl_order()`

---

## Appendix A: API Call Examples

### Example 1: LONG Entry with TP/SL

**Entry Order (MARKET)**:
```python
client.new_order(
    symbol="BTCUSDT",
    side="BUY",
    type="MARKET",
    quantity=0.001
)
# Response: orderId=123456789, status=FILLED, avgPrice=50123.45
```

**TP Order (TAKE_PROFIT_MARKET)**:
```python
client.new_order(
    symbol="BTCUSDT",
    side="SELL",
    type="TAKE_PROFIT_MARKET",
    stopPrice="52000.00",
    closePosition="true",
    workingType="MARK_PRICE"
)
# Response: orderId=123456790, status=NEW, stopPrice=52000.00
```

**SL Order (STOP_MARKET)**:
```python
client.new_order(
    symbol="BTCUSDT",
    side="SELL",
    type="STOP_MARKET",
    stopPrice="49000.00",
    closePosition="true",
    workingType="MARK_PRICE"
)
# Response: orderId=123456791, status=NEW, stopPrice=49000.00
```

### Example 2: SHORT Entry with TP/SL

**Entry Order (MARKET)**:
```python
client.new_order(
    symbol="BTCUSDT",
    side="SELL",
    type="MARKET",
    quantity=0.001
)
# Response: orderId=123456800, status=FILLED, avgPrice=50000.00
```

**TP Order (BUY to close SHORT)**:
```python
client.new_order(
    symbol="BTCUSDT",
    side="BUY",
    type="TAKE_PROFIT_MARKET",
    stopPrice="48000.00",  # Profit when price drops
    closePosition="true",
    workingType="MARK_PRICE"
)
# Response: orderId=123456801, status=NEW
```

**SL Order (BUY to close SHORT)**:
```python
client.new_order(
    symbol="BTCUSDT",
    side="BUY",
    type="STOP_MARKET",
    stopPrice="51000.00",  # Loss when price rises
    closePosition="true",
    workingType="MARK_PRICE"
)
# Response: orderId=123456802, status=NEW
```

---

## Appendix B: Implementation Checklist

### Phase 1: Helper Methods
- [ ] Implement `_format_price(price, symbol)` with 2-decimal precision
- [ ] Add docstring with note about Subtask 6.5 (dynamic precision)
- [ ] Write unit tests for `_format_price()` (2 tests)

### Phase 2: TP Order Placement
- [ ] Implement `_place_tp_order(signal, side)` method
- [ ] Format stopPrice using `_format_price()`
- [ ] Use `closePosition="true"` and `workingType="MARK_PRICE"`
- [ ] Add try-except for ClientError and Exception
- [ ] Log intent, success, and failures
- [ ] Return Order or None on failure
- [ ] Write unit tests for `_place_tp_order()` (4 tests)

### Phase 3: SL Order Placement
- [ ] Implement `_place_sl_order(signal, side)` method
- [ ] Follow same pattern as TP order
- [ ] Write unit tests for `_place_sl_order()` (4 tests)

### Phase 4: Update execute_signal()
- [ ] Change return type to `tuple[Order, list[Order]]`
- [ ] Add TP/SL placement logic after entry order success
- [ ] Determine TP/SL side (opposite of entry side)
- [ ] Call `_place_tp_order()` and `_place_sl_order()`
- [ ] Collect successful orders into list
- [ ] Log TP/SL placement summary
- [ ] Return `(entry_order, tpsl_orders)`
- [ ] Update docstring with new return type

### Phase 5: Update _parse_order_response()
- [ ] Handle `type` field for STOP_MARKET and TAKE_PROFIT_MARKET
- [ ] Extract `stopPrice` from response
- [ ] Handle quantity=0 for orders with closePosition=true
- [ ] Update docstring

### Phase 6: Testing
- [ ] Add new fixtures (short_entry_signal, close_long_signal, close_short_signal)
- [ ] Write helper method tests (3 tests)
- [ ] Write TP order tests (4 tests)
- [ ] Write SL order tests (4 tests)
- [ ] Write integration tests (6 tests)
- [ ] Write error handling tests (5 tests)
- [ ] Run pytest with coverage
- [ ] Verify >90% coverage on order_manager.py

### Phase 7: Documentation
- [ ] Update method docstrings
- [ ] Add code examples in docstrings
- [ ] Update design document with implementation notes
- [ ] Review all logging messages for clarity

---

**Design Document Version**: 1.0
**Last Updated**: 2025-12-17
**Next Steps**: Implementation (Subtask 6.3)
