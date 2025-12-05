# System Design: Data Models & Core Types (Task #2)

## 🎯 Design Overview

**Objective**: Define robust, type-safe data models for the ICT 2025 trading system using Python dataclasses with comprehensive validation and Binance API compatibility.

**Design Philosophy**:
- **Type Safety First**: Strict type hints with mypy validation
- **Immutability Where Possible**: Use frozen dataclasses for value objects
- **API Compatibility**: Enum values must match Binance USDT-M Futures API
- **Validation on Construction**: Fail fast with clear error messages
- **Computed Properties**: Encapsulate derived calculations
- **Event-Driven Ready**: Models support event-based architecture

---

## 📊 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Models Layer                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐            │
│  │  Candle  │────▶│  Signal  │────▶│  Order   │            │
│  │  (OHLCV) │     │ (Entry/  │     │ (Binance │            │
│  │          │     │  TP/SL)  │     │   API)   │            │
│  └──────────┘     └──────────┘     └──────────┘            │
│       │                 │                 │                  │
│       │                 │                 │                  │
│       ▼                 ▼                 ▼                  │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐            │
│  │  Event   │     │ Position │     │   Enum   │            │
│  │ (Event-  │     │ (Active  │     │  Types   │            │
│  │  Driven) │     │  Trade)  │     │          │            │
│  └──────────┘     └──────────┘     └──────────┘            │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 📝 Model Specifications

### 1. Candle Dataclass (`src/models/candle.py`)

#### Purpose
Represent OHLCV (Open, High, Low, Close, Volume) candlestick data from Binance WebSocket streams.

#### Design Decisions
- **Frozen**: NO (fields like `is_closed` need updates)
- **Validation**: Post-init validation for price coherence
- **Properties**: Computed technical analysis values

#### Implementation Spec

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Candle:
    """
    OHLCV candlestick data from Binance futures market.

    Attributes:
        symbol: Trading pair (e.g., 'BTCUSDT')
        interval: Timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        open_time: Candle opening timestamp (UTC)
        open: Opening price
        high: Highest price in period
        low: Lowest price in period
        close: Closing/current price
        volume: Trading volume in base asset
        close_time: Candle closing timestamp (UTC)
        is_closed: Whether candle period has ended
    """
    symbol: str
    interval: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: datetime
    is_closed: bool = False

    def __post_init__(self) -> None:
        """Validate price coherence."""
        if self.high < max(self.open, self.close):
            raise ValueError(
                f"High ({self.high}) must be >= max(open, close)"
            )
        if self.low > min(self.open, self.close):
            raise ValueError(
                f"Low ({self.low}) must be <= min(open, close)"
            )
        if self.volume < 0:
            raise ValueError(f"Volume ({self.volume}) cannot be negative")

    @property
    def body_size(self) -> float:
        """Absolute size of candle body (close - open)."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """True if closing price > opening price."""
        return self.close > self.open

    @property
    def upper_wick(self) -> float:
        """Upper shadow/wick size."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Lower shadow/wick size."""
        return min(self.open, self.close) - self.low

    @property
    def total_range(self) -> float:
        """Total price range (high - low)."""
        return self.high - self.low
```

#### Validation Rules
1. ✅ `high >= max(open, close)` - High must be highest point
2. ✅ `low <= min(open, close)` - Low must be lowest point
3. ✅ `volume >= 0` - Volume cannot be negative
4. ✅ `open_time < close_time` - Time ordering (future enhancement)

#### Test Strategy
```python
# test_candle.py
def test_valid_bullish_candle():
    candle = Candle(
        symbol="BTCUSDT",
        interval="5m",
        open_time=datetime(2025, 1, 1, 0, 0),
        open=50000.0,
        high=51000.0,
        low=49500.0,
        close=50800.0,
        volume=100.5,
        close_time=datetime(2025, 1, 1, 0, 5),
        is_closed=True
    )
    assert candle.is_bullish is True
    assert candle.body_size == 800.0
    assert candle.upper_wick == 200.0
    assert candle.lower_wick == 500.0

def test_invalid_high_raises_error():
    with pytest.raises(ValueError, match="High.*must be"):
        Candle(..., high=49000.0, close=50000.0)
```

---

### 2. Signal Dataclass (`src/models/signal.py`)

#### Purpose
Represent trade entry/exit signals generated by ICT strategies with precise entry, take-profit, and stop-loss levels.

#### Design Decisions
- **Frozen**: YES (signals are immutable once generated)
- **Enum**: SignalType for type safety
- **Metadata**: Flexible dict for strategy-specific data

#### Implementation Spec

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any

class SignalType(Enum):
    """Trading signal types."""
    LONG_ENTRY = "long_entry"
    SHORT_ENTRY = "short_entry"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"

@dataclass(frozen=True)
class Signal:
    """
    Trading signal with entry/exit parameters.

    Attributes:
        signal_type: Type of signal (entry/exit, long/short)
        symbol: Trading pair
        entry_price: Intended entry price
        take_profit: Target profit price
        stop_loss: Maximum loss price
        strategy_name: Name of strategy that generated signal
        timestamp: Signal generation time (UTC)
        confidence: Signal strength (0.0-1.0, default 1.0)
        metadata: Additional strategy-specific data
    """
    signal_type: SignalType
    symbol: str
    entry_price: float
    take_profit: float
    stop_loss: float
    strategy_name: str
    timestamp: datetime
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate signal parameters."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be 0.0-1.0, got {self.confidence}"
            )

        # Validate price logic based on signal type
        if self.signal_type == SignalType.LONG_ENTRY:
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    "LONG: take_profit must be > entry_price"
                )
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    "LONG: stop_loss must be < entry_price"
                )
        elif self.signal_type == SignalType.SHORT_ENTRY:
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    "SHORT: take_profit must be < entry_price"
                )
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    "SHORT: stop_loss must be > entry_price"
                )

    @property
    def risk_amount(self) -> float:
        """Risk per unit (entry - stop_loss)."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_amount(self) -> float:
        """Reward per unit (take_profit - entry)."""
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        """Risk-to-reward ratio (reward / risk)."""
        if self.risk_amount == 0:
            return 0.0
        return self.reward_amount / self.risk_amount
```

#### Validation Rules
1. ✅ `0.0 <= confidence <= 1.0` - Valid confidence range
2. ✅ LONG signals: `take_profit > entry_price > stop_loss`
3. ✅ SHORT signals: `stop_loss > entry_price > take_profit`
4. ✅ Risk-reward ratio calculated correctly

---

### 3. Order Dataclass (`src/models/order.py`)

#### Purpose
Represent Binance USDT-M Futures orders with API-compatible enum values.

#### Design Decisions
- **Binance API Compliance**: Enum values MUST match exactly
- **Mutable**: Order status updates after creation
- **Optional Fields**: Some fields populated after submission

#### Implementation Spec

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class OrderType(Enum):
    """Binance order types (EXACT API values)."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"

class OrderSide(Enum):
    """Binance order sides (EXACT API values)."""
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(Enum):
    """Binance order statuses (EXACT API values)."""
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

@dataclass
class Order:
    """
    Binance futures order representation.

    Attributes:
        symbol: Trading pair
        side: BUY or SELL
        order_type: Order type (MARKET, LIMIT, etc.)
        quantity: Order size in base asset
        price: Limit price (required for LIMIT orders)
        stop_price: Trigger price (required for STOP orders)
        order_id: Binance order ID (set after submission)
        client_order_id: Client-defined ID (optional)
        status: Current order status
        timestamp: Order creation/update time
    """
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.NEW
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Validate order parameters."""
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be > 0, got {self.quantity}")

        # LIMIT orders require price
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("LIMIT orders require price")

        # STOP orders require stop_price
        if self.order_type in (OrderType.STOP_MARKET,
                               OrderType.TAKE_PROFIT_MARKET):
            if self.stop_price is None:
                raise ValueError(
                    f"{self.order_type.value} requires stop_price"
                )
```

#### Binance API Reference
🔗 **CRITICAL**: Verify enum values against official docs:
- https://binance-docs.github.io/apidocs/futures/en/#new-order-trade

#### Test Strategy
```python
def test_order_enum_values_match_binance():
    """Verify enum values match Binance API exactly."""
    assert OrderType.MARKET.value == "MARKET"
    assert OrderSide.BUY.value == "BUY"
    assert OrderStatus.FILLED.value == "FILLED"

def test_limit_order_requires_price():
    with pytest.raises(ValueError, match="LIMIT orders require price"):
        Order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.001,
            # Missing price
        )
```

---

### 4. Position & Event Dataclasses

#### Position (`src/models/position.py`)

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Position:
    """
    Active futures position.

    Attributes:
        symbol: Trading pair
        side: 'LONG' or 'SHORT'
        entry_price: Average entry price
        quantity: Position size (contracts)
        leverage: Leverage multiplier
        unrealized_pnl: Current profit/loss
        liquidation_price: Liquidation price (if available)
        entry_time: Position open time
    """
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
        if self.side not in ('LONG', 'SHORT'):
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

#### Event (`src/models/event.py`)

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

class EventType(Enum):
    """Event types for event-driven architecture."""
    CANDLE_UPDATE = "candle_update"
    CANDLE_CLOSED = "candle_closed"
    SIGNAL_GENERATED = "signal_generated"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"

@dataclass
class Event:
    """
    System event for event-driven architecture.

    Attributes:
        event_type: Type of event
        data: Event payload (Candle, Signal, Order, etc.)
        timestamp: Event occurrence time (UTC)
        source: Component that generated event
    """
    event_type: EventType
    data: Any
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: Optional[str] = None
```

---

## 🔒 Validation & Safety

### Type Checking (mypy)
```bash
# Must pass with zero errors
mypy src/models/
```

### Unit Testing Coverage
- Minimum 90% coverage for `src/models/`
- Test all validation paths
- Test all computed properties
- Test Binance API enum compatibility

### Integration Points
```python
# models/__init__.py - Complete exports
from .candle import Candle
from .signal import Signal, SignalType
from .order import Order, OrderType, OrderSide, OrderStatus
from .position import Position
from .event import Event, EventType

__all__ = [
    "Candle",
    "Signal",
    "SignalType",
    "Order",
    "OrderType",
    "OrderSide",
    "OrderStatus",
    "Position",
    "Event",
    "EventType",
]
```

---

## 📈 Implementation Roadmap

### Phase 1: Candle Model (Subtask 2.1)
1. Implement `Candle` dataclass
2. Add validation in `__post_init__`
3. Implement computed properties
4. Write unit tests
5. Export from `__init__.py`

### Phase 2: Signal Model (Subtask 2.2)
1. Implement `SignalType` enum
2. Implement `Signal` dataclass with frozen=True
3. Add signal-specific validation
4. Implement risk-reward calculations
5. Write unit tests

### Phase 3: Order Model (Subtask 2.3)
1. Implement all Binance-compatible enums
2. Implement `Order` dataclass
3. Add order-type specific validation
4. Cross-reference with Binance API docs
5. Write comprehensive tests

### Phase 4: Position & Event (Subtask 2.4)
1. Implement `Position` dataclass
2. Implement `EventType` enum
3. Implement `Event` dataclass
4. Update complete `__init__.py` exports
5. Integration testing

---

## ✅ Acceptance Criteria

- [ ] All models use dataclasses with type hints
- [ ] mypy type checking passes with zero errors
- [ ] All validation rules implemented in `__post_init__`
- [ ] Computed properties are @property methods
- [ ] Binance API enum values verified against official docs
- [ ] Unit test coverage >90% for models/
- [ ] All models exported from `models/__init__.py`
- [ ] No circular import dependencies
- [ ] Code formatted with Black (line-length=100)
- [ ] Imports sorted with isort

---

## 🎓 Design Patterns Used

1. **Value Objects**: Frozen dataclasses for immutable data (Signal)
2. **Validation on Construction**: Fail-fast with `__post_init__`
3. **Computed Properties**: Encapsulate derived calculations
4. **Type Safety**: Enums for limited value sets
5. **API Compatibility**: Exact enum matching for external APIs
6. **Event Sourcing Ready**: Event dataclass for event-driven architecture

---

## 📚 References

- **Binance Futures API**: https://binance-docs.github.io/apidocs/futures/en/
- **Python Dataclasses**: https://docs.python.org/3/library/dataclasses.html
- **mypy Type Checking**: https://mypy.readthedocs.io/
- **ICT Trading Concepts**: (User's proprietary knowledge)

---

**Design Status**: ✅ **APPROVED - Ready for Implementation**

**Next Step**: Begin Subtask 2.1 - Implement Candle dataclass

---

*Design Document Version: 1.0*
*Last Updated: 2025-12-06*
*Designer: Claude Code with Serena MCP*
