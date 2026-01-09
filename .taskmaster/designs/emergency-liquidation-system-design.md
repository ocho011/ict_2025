# Emergency Position Liquidation System Design

## Executive Summary

This document defines a comprehensive emergency position liquidation system for the ICT 2025 Trading Bot. The design follows principles from the business panel analysis (Taleb's paranoia, Meadows' systems thinking, Collins' disciplined execution) to create a fail-safe, auditable, and configuration-driven liquidation mechanism.

**Core Design Philosophy:**
- Security First: Default to capital protection (emergency_liquidation = true)
- Reverse the Risk: Make danger the conscious choice (opt-out, not opt-in)
- Comprehensive Audit: Full audit trail for all liquidation decisions
- Fail-Safe Design: Continue shutdown even if liquidation fails

---

## 1. Architecture Design

### 1.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TradingBot                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐│
│  │ConfigManager│  │TradingEngine│  │ EventBus     │  │ TradingLogger       ││
│  └──────┬──────┘  └──────┬──────┘  └──────────────┘  └─────────────────────┘│
│         │                │                                                   │
│         │    ┌───────────┴───────────┐                                      │
│         │    │                       │                                      │
│         ▼    ▼                       ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                        LiquidationManager                                ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  ││
│  │  │LiquidationConfig│  │LiquidationState │  │LiquidationAuditExtension│  ││
│  │  │- emergency_liq  │  │- IDLE           │  │- log_liq_started        │  ││
│  │  │- close_positions│  │- IN_PROGRESS    │  │- log_position_closed    │  ││
│  │  │- cancel_orders  │  │- COMPLETED      │  │- log_liq_completed      │  ││
│  │  │- timeout_seconds│  │- FAILED         │  │- log_liq_failed         │  ││
│  │  │- max_retries    │  │- PARTIAL        │  └─────────────────────────┘  ││
│  │  └─────────────────┘  └─────────────────┘                                ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                    │                    │                                    │
│                    │                    ▼                                    │
│                    │           ┌─────────────────┐                          │
│                    │           │  AuditLogger    │                          │
│                    │           │  (JSON Lines)   │                          │
│                    │           └─────────────────┘                          │
│                    ▼                                                         │
│           ┌─────────────────────────────────────────┐                       │
│           │         OrderExecutionManager           │                       │
│           │  - get_position()                       │                       │
│           │  - cancel_all_orders()                  │                       │
│           │  - execute_market_close() [NEW]         │                       │
│           │  - get_all_positions() [NEW]            │                       │
│           └─────────────────────────────────────────┘                       │
│                              │                                               │
│                              ▼                                               │
│                     ┌─────────────────┐                                     │
│                     │  Binance API    │                                     │
│                     │  (UMFutures)    │                                     │
│                     └─────────────────┘                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Integration Points

| Component | Integration Type | Purpose |
|-----------|-----------------|---------|
| TradingBot | Composition | Holds LiquidationManager instance |
| ConfigManager | Dependency Injection | Provides LiquidationConfig |
| OrderExecutionManager | Delegation | Executes liquidation orders |
| AuditLogger | Extension | Logs all liquidation events |
| TradingEngine | Coordination | Shutdown orchestration |

### 1.3 Shutdown Flow Sequence Diagram

#### 1.3.1 Emergency Shutdown (Default)

```
User/System          TradingBot           LiquidationManager      OrderManager         AuditLogger
     │                    │                      │                     │                    │
     │  SIGINT/SIGTERM    │                      │                     │                    │
     │───────────────────>│                      │                     │                    │
     │                    │                      │                     │                    │
     │                    │ shutdown()           │                     │                    │
     │                    │─────────────────────>│                     │                    │
     │                    │                      │ log_liquidation_started()              │
     │                    │                      │────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │                    │                      │ 1. Query all positions                 │
     │                    │                      │────────────────────>│                    │
     │                    │                      │<────────────────────│                    │
     │                    │                      │                     │                    │
     │                    │                      │ log_positions_queried()                │
     │                    │                      │────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │                    │                      │ 2. Cancel pending orders (per symbol)  │
     │                    │                      │────────────────────>│                    │
     │                    │                      │<────────────────────│                    │
     │                    │                      │                     │                    │
     │                    │                      │ log_orders_cancelled()                 │
     │                    │                      │────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │                    │                      │ 3. Close positions with market orders  │
     │                    │                      │    (reduceOnly=True)                   │
     │                    │                      │────────────────────>│                    │
     │                    │                      │<────────────────────│                    │
     │                    │                      │                     │                    │
     │                    │                      │ log_position_closed()                  │
     │                    │                      │────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │                    │ LiquidationResult    │                     │                    │
     │                    │<─────────────────────│                     │                    │
     │                    │                      │                     │                    │
     │                    │ continue_shutdown()  │                     │                    │
     │                    │───────────────────────────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │  Shutdown Complete │                      │                     │                    │
     │<───────────────────│                      │                     │                    │
```

#### 1.3.2 Safe Shutdown (No Liquidation)

```
User/System          TradingBot           LiquidationManager      OrderManager         AuditLogger
     │                    │                      │                     │                    │
     │  SIGINT/SIGTERM    │                      │                     │                    │
     │───────────────────>│                      │                     │                    │
     │                    │                      │                     │                    │
     │                    │ shutdown()           │                     │                    │
     │                    │─────────────────────>│                     │                    │
     │                    │                      │                     │                    │
     │                    │                      │ [Config: emergency_liquidation=false]  │
     │                    │                      │                     │                    │
     │                    │                      │ log_liquidation_skipped()              │
     │                    │                      │────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │                    │ LiquidationResult    │                     │                    │
     │                    │   (SKIPPED)          │                     │                    │
     │                    │<─────────────────────│                     │                    │
     │                    │                      │                     │                    │
     │                    │ continue_shutdown()  │                     │                    │
     │                    │───────────────────────────────────────────────────────────────>│
     │                    │                      │                     │                    │
     │  Shutdown Complete │                      │                     │                    │
     │<───────────────────│                      │                     │                    │
```

### 1.4 Liquidation State Machine

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
              ┌──────────┐                                    │
              │   IDLE   │◄───────────────────────────────────┤
              └────┬─────┘                                    │
                   │                                          │
                   │ execute_liquidation()                    │
                   │                                          │
                   ▼                                          │
           ┌───────────────┐                                  │
           │  IN_PROGRESS  │                                  │
           └───────┬───────┘                                  │
                   │                                          │
        ┌──────────┼──────────┐                               │
        │          │          │                               │
        ▼          ▼          ▼                               │
  ┌──────────┐ ┌───────┐ ┌─────────┐                         │
  │ COMPLETED│ │PARTIAL│ │ FAILED  │                         │
  └────┬─────┘ └───┬───┘ └────┬────┘                         │
       │           │          │                               │
       │           │          │ [retry < max_retries]         │
       │           │          └───────────────────────────────┘
       │           │
       │           │ [all positions attempted]
       │           ▼
       │    ┌──────────────┐
       │    │PARTIAL_CLOSED│
       │    └──────────────┘
       │           │
       ▼           ▼
   ┌───────────────────────────────────────┐
   │        Shutdown Continues             │
   │   (Fail-safe: never blocks shutdown)  │
   └───────────────────────────────────────┘
```

### 1.5 State Transitions

| From State | Event | To State | Condition |
|------------|-------|----------|-----------|
| IDLE | execute_liquidation() | IN_PROGRESS | Config allows liquidation |
| IDLE | execute_liquidation() | SKIPPED | Config disables liquidation |
| IN_PROGRESS | all_closed() | COMPLETED | All positions closed successfully |
| IN_PROGRESS | some_closed() | PARTIAL | Some positions closed, some failed |
| IN_PROGRESS | timeout() | FAILED | Timeout exceeded |
| IN_PROGRESS | api_error() | FAILED | Unrecoverable API error |
| FAILED | retry() | IN_PROGRESS | retry_count < max_retries |
| FAILED | max_retries_exceeded() | PARTIAL | Best-effort completion |
| * | shutdown_forced() | (continue) | Fail-safe, never blocks |

---

## 2. Security Architecture

### 2.1 Threat Model

#### 2.1.1 Threat Categories

| Threat ID | Category | Description | Severity | Likelihood |
|-----------|----------|-------------|----------|------------|
| T1 | Accidental Liquidation | Unintended position closure due to misconfiguration | HIGH | MEDIUM |
| T2 | Configuration Error | Invalid config causing unexpected behavior | HIGH | MEDIUM |
| T3 | API Key Exposure | API credentials leaked in logs | CRITICAL | LOW |
| T4 | Incomplete Liquidation | Partial closure leaving orphan positions | MEDIUM | MEDIUM |
| T5 | Retry Storm | Excessive API calls during failure recovery | HIGH | LOW |
| T6 | Audit Gap | Missing audit trail for compliance | MEDIUM | LOW |
| T7 | Race Condition | Concurrent shutdown calls causing issues | LOW | LOW |
| T8 | Denial of Service | Liquidation blocking shutdown indefinitely | HIGH | LOW |

#### 2.1.2 Attack Surface

```
┌─────────────────────────────────────────────────────────────────┐
│                     Attack Surface Analysis                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Configuration Files                                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  trading_config.ini                                       │   │
│  │  └─ [liquidation] section                                 │   │
│  │     └─ emergency_liquidation = true (DEFAULT)             │   │
│  │     └─ RISK: Manual edit could disable protection         │   │
│  │     └─ MITIGATION: Validate on load, log all changes      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  API Credentials                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  BINANCE_API_KEY / BINANCE_API_SECRET                     │   │
│  │  └─ RISK: Exposure in error messages or logs              │   │
│  │  └─ MITIGATION: Never log credentials, mask in errors     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Runtime Behavior                                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Concurrent shutdown() calls                              │   │
│  │  └─ RISK: Race condition in state transitions             │   │
│  │  └─ MITIGATION: Idempotent operations, atomic states      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Defense-in-Depth Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 1: Configuration Defense                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • emergency_liquidation = true (DEFAULT)                 │  │
│  │  • Explicit opt-out required to disable                   │  │
│  │  • Configuration validation on load                       │  │
│  │  • Log CRITICAL warning when disabled                     │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 2: State Machine Defense                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Idempotent operations (safe to call multiple times)    │  │
│  │  • Explicit state transitions with validation             │  │
│  │  • No state allowed to block shutdown indefinitely        │  │
│  │  • Timeout enforcement at every step                      │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 3: API Call Defense                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Rate limit tracking (RequestWeightTracker)             │  │
│  │  • Retry with exponential backoff                         │  │
│  │  • Maximum retry limit (default: 3)                       │  │
│  │  • Timeout per operation (default: 5 seconds)             │  │
│  │  • reduceOnly=True enforced for all close orders          │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 4: Audit Trail Defense                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Every liquidation decision logged                      │  │
│  │  • Success and failure paths both logged                  │  │
│  │  • API responses captured (credentials masked)            │  │
│  │  • Timestamps with microsecond precision                  │  │
│  │  • Correlation IDs for request tracing                    │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│                    Layer 5: Fail-Safe Defense                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Shutdown NEVER blocked by liquidation failure          │  │
│  │  • Best-effort completion with timeout                    │  │
│  │  • Graceful degradation on partial failures               │  │
│  │  • Final state always reported in audit log               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Security Controls Matrix

| Control | Threat Mitigated | Implementation |
|---------|------------------|----------------|
| Default emergency_liquidation=true | T1: Accidental skip | Config default + validation |
| Configuration validation | T2: Config errors | __post_init__ checks |
| Credential masking | T3: API key exposure | Never log full credentials |
| reduceOnly=True | T1: Accidental new positions | Forced in all close orders |
| Retry limit | T5: Retry storm | max_retries config (default: 3) |
| Timeout enforcement | T8: DoS | timeout_seconds config (default: 5) |
| Idempotent operations | T7: Race conditions | State checks before actions |
| Comprehensive audit | T6: Audit gaps | AuditEventType extensions |
| Fail-safe shutdown | T8: DoS | try/except with continue |

### 2.4 Audit Logging Strategy

#### 2.4.1 New AuditEventType Additions

```python
class AuditEventType(Enum):
    # ... existing events ...

    # Liquidation events (NEW)
    LIQUIDATION_STARTED = "liquidation_started"
    LIQUIDATION_SKIPPED = "liquidation_skipped"
    LIQUIDATION_POSITIONS_QUERIED = "liquidation_positions_queried"
    LIQUIDATION_ORDERS_CANCELLED = "liquidation_orders_cancelled"
    LIQUIDATION_POSITION_CLOSED = "liquidation_position_closed"
    LIQUIDATION_POSITION_CLOSE_FAILED = "liquidation_position_close_failed"
    LIQUIDATION_COMPLETED = "liquidation_completed"
    LIQUIDATION_PARTIAL = "liquidation_partial"
    LIQUIDATION_FAILED = "liquidation_failed"
    LIQUIDATION_TIMEOUT = "liquidation_timeout"
```

#### 2.4.2 Audit Event Schema

```json
{
  "timestamp": "2025-01-02T10:30:45.123456",
  "event_type": "liquidation_started",
  "operation": "execute_emergency_liquidation",
  "correlation_id": "liq_20250102_103045_abc123",
  "config": {
    "emergency_liquidation": true,
    "close_positions": true,
    "cancel_orders": true,
    "timeout_seconds": 5.0,
    "max_retries": 3
  },
  "trigger": "SIGTERM",
  "additional_data": {
    "lifecycle_state": "STOPPING",
    "positions_count_expected": 2
  }
}
```

#### 2.4.3 Audit Event Examples by Scenario

**Successful Liquidation:**
```json
{"timestamp": "...", "event_type": "liquidation_started", "correlation_id": "liq_001", ...}
{"timestamp": "...", "event_type": "liquidation_positions_queried", "correlation_id": "liq_001", "positions": [{"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.1}]}
{"timestamp": "...", "event_type": "liquidation_orders_cancelled", "correlation_id": "liq_001", "symbol": "BTCUSDT", "cancelled_count": 2}
{"timestamp": "...", "event_type": "liquidation_position_closed", "correlation_id": "liq_001", "symbol": "BTCUSDT", "quantity": 0.1, "realized_pnl": 50.0}
{"timestamp": "...", "event_type": "liquidation_completed", "correlation_id": "liq_001", "positions_closed": 1, "total_realized_pnl": 50.0}
```

**Partial Liquidation (with failures):**
```json
{"timestamp": "...", "event_type": "liquidation_started", "correlation_id": "liq_002", ...}
{"timestamp": "...", "event_type": "liquidation_positions_queried", "correlation_id": "liq_002", "positions": [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}]}
{"timestamp": "...", "event_type": "liquidation_position_closed", "correlation_id": "liq_002", "symbol": "BTCUSDT", "quantity": 0.1}
{"timestamp": "...", "event_type": "liquidation_position_close_failed", "correlation_id": "liq_002", "symbol": "ETHUSDT", "error": "Insufficient balance"}
{"timestamp": "...", "event_type": "liquidation_partial", "correlation_id": "liq_002", "closed": 1, "failed": 1}
```

**Liquidation Skipped:**
```json
{"timestamp": "...", "event_type": "liquidation_skipped", "correlation_id": "liq_003", "reason": "emergency_liquidation=false", "config": {...}}
```

---

## 3. API Design

### 3.1 LiquidationConfig (Configuration Schema)

```python
@dataclass
class LiquidationConfig:
    """
    Configuration for emergency position liquidation.

    Security Design:
    - emergency_liquidation defaults to True (opt-out, not opt-in)
    - Making danger (keeping positions) the conscious choice

    Attributes:
        emergency_liquidation: Whether to liquidate on shutdown (default: True)
        close_positions: Whether to close open positions (default: True)
        cancel_orders: Whether to cancel pending orders (default: True)
        timeout_seconds: Maximum time for liquidation process (default: 5.0)
        max_retries: Maximum retry attempts per operation (default: 3)
        retry_delay_seconds: Base delay between retries (default: 0.5)

    Example INI configuration:
        [liquidation]
        emergency_liquidation = true
        close_positions = true
        cancel_orders = true
        timeout_seconds = 5.0
        max_retries = 3
        retry_delay_seconds = 0.5
    """

    emergency_liquidation: bool = True  # DEFAULT: Protect capital
    close_positions: bool = True
    cancel_orders: bool = True
    timeout_seconds: float = 5.0
    max_retries: int = 3
    retry_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        """Validate configuration on creation."""
        # Log CRITICAL warning if liquidation is disabled
        if not self.emergency_liquidation:
            import logging
            logger = logging.getLogger(__name__)
            logger.critical(
                "SECURITY WARNING: emergency_liquidation is DISABLED. "
                "Positions will NOT be closed on shutdown. "
                "This is a HIGH-RISK configuration."
            )

        # Validate timeout
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ConfigurationError(
                f"timeout_seconds must be 0 < value <= 60, got {self.timeout_seconds}"
            )

        # Validate retries
        if self.max_retries < 0 or self.max_retries > 10:
            raise ConfigurationError(
                f"max_retries must be 0-10, got {self.max_retries}"
            )

        # Validate retry delay
        if self.retry_delay_seconds < 0 or self.retry_delay_seconds > 5:
            raise ConfigurationError(
                f"retry_delay_seconds must be 0-5, got {self.retry_delay_seconds}"
            )
```

### 3.2 LiquidationState (Enum)

```python
class LiquidationState(Enum):
    """
    State machine states for liquidation process.

    State Transitions:
        IDLE -> IN_PROGRESS: execute_liquidation() called
        IDLE -> SKIPPED: config.emergency_liquidation is False
        IN_PROGRESS -> COMPLETED: all positions closed successfully
        IN_PROGRESS -> PARTIAL: some positions closed, some failed
        IN_PROGRESS -> FAILED: timeout or unrecoverable error
        FAILED -> IN_PROGRESS: retry initiated (if retries remaining)
    """

    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
```

### 3.3 LiquidationResult (Data Class)

```python
@dataclass
class LiquidationResult:
    """
    Result of a liquidation operation.

    Attributes:
        state: Final state of liquidation
        positions_closed: Number of positions successfully closed
        positions_failed: Number of positions that failed to close
        orders_cancelled: Total number of orders cancelled
        total_realized_pnl: Sum of realized PnL from closed positions
        duration_seconds: Time taken for liquidation process
        errors: List of error messages encountered
        correlation_id: Unique ID for audit trail correlation
    """

    state: LiquidationState
    positions_closed: int = 0
    positions_failed: int = 0
    orders_cancelled: int = 0
    total_realized_pnl: float = 0.0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    correlation_id: str = ""

    @property
    def success(self) -> bool:
        """True if all positions were closed successfully."""
        return self.state == LiquidationState.COMPLETED

    @property
    def partial_success(self) -> bool:
        """True if some (but not all) positions were closed."""
        return self.state == LiquidationState.PARTIAL

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "state": self.state.value,
            "positions_closed": self.positions_closed,
            "positions_failed": self.positions_failed,
            "orders_cancelled": self.orders_cancelled,
            "total_realized_pnl": self.total_realized_pnl,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors,
            "correlation_id": self.correlation_id,
        }
```

### 3.4 LiquidationManager Class Interface

```python
class LiquidationManager:
    """
    Emergency position liquidation manager.

    Responsible for safely closing all positions during shutdown.
    Follows fail-safe design: shutdown continues even if liquidation fails.

    Design Principles:
    1. Security First: Default to capital protection (emergency_liquidation=True)
    2. Idempotent: Safe to call multiple times
    3. Fail-Safe: Never blocks shutdown
    4. Comprehensive Audit: Full audit trail for all decisions

    Usage:
        >>> config = LiquidationConfig()
        >>> manager = LiquidationManager(
        ...     config=config,
        ...     order_manager=order_manager,
        ...     audit_logger=audit_logger,
        ... )
        >>> result = await manager.execute_liquidation(trigger="SIGTERM")
        >>> print(f"Closed {result.positions_closed} positions")

    Attributes:
        config: LiquidationConfig instance
        order_manager: OrderExecutionManager for API calls
        audit_logger: AuditLogger for compliance logging
        state: Current LiquidationState
    """

    def __init__(
        self,
        config: LiquidationConfig,
        order_manager: OrderExecutionManager,
        audit_logger: AuditLogger,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize LiquidationManager.

        Args:
            config: Liquidation configuration
            order_manager: Order execution manager instance
            audit_logger: Audit logger for compliance
            logger: Optional logger (creates default if None)
        """
        ...

    @property
    def state(self) -> LiquidationState:
        """Get current liquidation state."""
        ...

    async def execute_liquidation(
        self,
        trigger: str = "unknown",
    ) -> LiquidationResult:
        """
        Execute emergency position liquidation.

        This method is idempotent - safe to call multiple times.
        Returns immediately if already in progress or completed.

        Process:
        1. Check if liquidation is enabled (config.emergency_liquidation)
        2. Query all open positions
        3. Cancel all pending orders (per symbol)
        4. Close positions with market orders (reduceOnly=True)
        5. Log results to audit trail

        Args:
            trigger: Description of what triggered liquidation
                     (e.g., "SIGTERM", "SIGINT", "manual", "error")

        Returns:
            LiquidationResult with final state and statistics

        Note:
            This method never raises exceptions. All errors are caught,
            logged, and returned in the LiquidationResult.
        """
        ...

    async def _query_all_positions(self) -> List[Position]:
        """
        Query all open positions from exchange.

        Returns:
            List of Position objects with non-zero quantity

        Note:
            Uses get_account_positions() which returns all positions,
            then filters to only those with quantity != 0.
        """
        ...

    async def _cancel_orders_for_symbol(self, symbol: str) -> int:
        """
        Cancel all pending orders for a symbol.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")

        Returns:
            Number of orders cancelled

        Note:
            Uses cancel_all_orders() from OrderExecutionManager.
            Catches and logs errors but does not re-raise.
        """
        ...

    async def _close_position(self, position: Position) -> Tuple[bool, float]:
        """
        Close a single position with market order.

        Args:
            position: Position to close

        Returns:
            Tuple of (success: bool, realized_pnl: float)

        Note:
            Uses execute_market_close() with reduceOnly=True.
            Retries up to max_retries on transient failures.
        """
        ...

    def _generate_correlation_id(self) -> str:
        """
        Generate unique correlation ID for audit trail.

        Format: liq_{YYYYMMDD}_{HHMMSS}_{random_hex}
        Example: liq_20250102_103045_abc123
        """
        ...
```

### 3.5 OrderExecutionManager Extensions

```python
class OrderExecutionManager:
    # ... existing methods ...

    async def get_all_positions(self) -> List[Position]:
        """
        Query all positions across all symbols.

        Returns:
            List of Position objects for symbols with non-zero positionAmt

        Note:
            Uses /fapi/v2/positionRisk endpoint without symbol parameter
            to get all positions at once (more efficient than per-symbol).

        Raises:
            OrderExecutionError: API call fails
        """
        ...

    async def execute_market_close(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reduce_only: bool = True,
    ) -> Tuple[bool, float]:
        """
        Close a position with a market order.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "BUY" to close SHORT, "SELL" to close LONG
            quantity: Position quantity to close
            reduce_only: If True, only reduces position (default: True)

        Returns:
            Tuple of (success: bool, realized_pnl: float)

        Security:
            reduce_only=True is enforced to prevent accidental new positions.

        Raises:
            ValidationError: Invalid parameters
            OrderExecutionError: API call fails (after retries)
        """
        ...
```

### 3.6 Configuration INI Schema

```ini
# trading_config.ini

[liquidation]
# Emergency liquidation settings
# SECURITY: emergency_liquidation defaults to true if not specified
# Setting to false is HIGH-RISK and will log a CRITICAL warning

# Whether to liquidate positions on shutdown (default: true)
emergency_liquidation = true

# Whether to close open positions (default: true)
close_positions = true

# Whether to cancel pending orders (default: true)
cancel_orders = true

# Maximum time for entire liquidation process in seconds (default: 5.0)
timeout_seconds = 5.0

# Maximum retry attempts per operation (default: 3)
max_retries = 3

# Base delay between retries in seconds (default: 0.5)
retry_delay_seconds = 0.5
```

---

## 4. Data Flow Design

### 4.1 Position Query -> Order Cancellation -> Position Closure Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Liquidation Data Flow                                │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐
│ execute_liquidation()
│ trigger: SIGTERM │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 1: Configuration Check                                                  │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ IF config.emergency_liquidation == False:                                ││
│ │   log_event(LIQUIDATION_SKIPPED, reason="disabled by config")            ││
│ │   return LiquidationResult(state=SKIPPED)                                ││
│ │ ELSE:                                                                    ││
│ │   log_event(LIQUIDATION_STARTED, trigger=trigger)                        ││
│ │   state = IN_PROGRESS                                                    ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 2: Query All Positions                                                  │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ positions = await order_manager.get_all_positions()                      ││
│ │ log_event(LIQUIDATION_POSITIONS_QUERIED, positions=positions)            ││
│ │                                                                          ││
│ │ IF positions is empty:                                                   ││
│ │   log_event(LIQUIDATION_COMPLETED, positions_closed=0)                   ││
│ │   return LiquidationResult(state=COMPLETED)                              ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 3: Process Each Position                                                │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ FOR position IN positions:                                               ││
│ │   ┌────────────────────────────────────────────────────────────────────┐ ││
│ │   │ 3a. Cancel Pending Orders                                          │ ││
│ │   │ cancelled = await order_manager.cancel_all_orders(symbol)          │ ││
│ │   │ log_event(LIQUIDATION_ORDERS_CANCELLED, symbol, cancelled)         │ ││
│ │   └────────────────────────────────────────────────────────────────────┘ ││
│ │                                                                          ││
│ │   ┌────────────────────────────────────────────────────────────────────┐ ││
│ │   │ 3b. Close Position                                                 │ ││
│ │   │ close_side = "SELL" if position.side == "LONG" else "BUY"          │ ││
│ │   │ success, pnl = await order_manager.execute_market_close(           │ ││
│ │   │     symbol=position.symbol,                                        │ ││
│ │   │     side=close_side,                                               │ ││
│ │   │     quantity=position.quantity,                                    │ ││
│ │   │     reduce_only=True  # SECURITY: Always reduce only               │ ││
│ │   │ )                                                                  │ ││
│ │   │                                                                    │ ││
│ │   │ IF success:                                                        │ ││
│ │   │   log_event(LIQUIDATION_POSITION_CLOSED, symbol, pnl)              │ ││
│ │   │   positions_closed += 1                                            │ ││
│ │   │   total_pnl += pnl                                                 │ ││
│ │   │ ELSE:                                                              │ ││
│ │   │   log_event(LIQUIDATION_POSITION_CLOSE_FAILED, symbol, error)      │ ││
│ │   │   positions_failed += 1                                            │ ││
│ │   │   errors.append(error)                                             │ ││
│ │   └────────────────────────────────────────────────────────────────────┘ ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 4: Determine Final State                                                │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ IF positions_failed == 0:                                                ││
│ │   state = COMPLETED                                                      ││
│ │   log_event(LIQUIDATION_COMPLETED, closed=positions_closed, pnl=total)   ││
│ │ ELIF positions_closed > 0:                                               ││
│ │   state = PARTIAL                                                        ││
│ │   log_event(LIQUIDATION_PARTIAL, closed=positions_closed,                ││
│ │             failed=positions_failed, errors=errors)                      ││
│ │ ELSE:                                                                    ││
│ │   state = FAILED                                                         ││
│ │   log_event(LIQUIDATION_FAILED, errors=errors)                           ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 5: Return Result (ALWAYS - never blocks)                                │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ return LiquidationResult(                                                ││
│ │     state=state,                                                         ││
│ │     positions_closed=positions_closed,                                   ││
│ │     positions_failed=positions_failed,                                   ││
│ │     orders_cancelled=orders_cancelled,                                   ││
│ │     total_realized_pnl=total_pnl,                                        ││
│ │     duration_seconds=elapsed_time,                                       ││
│ │     errors=errors,                                                       ││
│ │     correlation_id=correlation_id,                                       ││
│ │ )                                                                        ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Error Propagation Paths

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Error Propagation Strategy                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Error Category: Configuration Errors                                         │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ Source: LiquidationConfig.__post_init__                                  ││
│ │ Examples: invalid timeout, invalid max_retries                           ││
│ │ Handling: ConfigurationError raised during initialization                ││
│ │ Propagation: Bubbles up to TradingBot.initialize()                       ││
│ │ Recovery: Bot fails to start (fail-fast)                                 ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Error Category: API Errors (Transient)                                       │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ Source: OrderExecutionManager API calls                                  ││
│ │ Examples: network timeout, rate limit, temporary API outage              ││
│ │ Handling:                                                                ││
│ │   1. Log warning with error details                                      ││
│ │   2. Retry with exponential backoff                                      ││
│ │   3. If max_retries exceeded: log error, continue to next position       ││
│ │ Propagation: Caught inside LiquidationManager, added to errors list      ││
│ │ Recovery: Best-effort completion, result.state may be PARTIAL            ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Error Category: API Errors (Fatal)                                           │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ Source: OrderExecutionManager API calls                                  ││
│ │ Examples: invalid API key, account suspended                             ││
│ │ Handling:                                                                ││
│ │   1. Log CRITICAL error                                                  ││
│ │   2. Do NOT retry (futile)                                               ││
│ │   3. Add to errors list                                                  ││
│ │   4. Continue to remaining positions (best-effort)                       ││
│ │ Propagation: Caught, logged, shutdown continues                          ││
│ │ Recovery: result.state = FAILED, errors contain details                  ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Error Category: Timeout                                                       │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ Source: asyncio.wait_for in execute_liquidation                          ││
│ │ Trigger: config.timeout_seconds exceeded                                 ││
│ │ Handling:                                                                ││
│ │   1. Log LIQUIDATION_TIMEOUT event                                       ││
│ │   2. Record partial results                                              ││
│ │   3. Return immediately (fail-safe)                                      ││
│ │ Propagation: Caught, result.state = PARTIAL or FAILED                    ││
│ │ Recovery: Shutdown continues, positions may remain open                  ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ Error Category: Unexpected Exceptions                                        │
│ ┌──────────────────────────────────────────────────────────────────────────┐│
│ │ Source: Any code path                                                    ││
│ │ Examples: AttributeError, TypeError, unexpected API response             ││
│ │ Handling:                                                                ││
│ │   1. Catch with broad except Exception                                   ││
│ │   2. Log CRITICAL with full traceback                                    ││
│ │   3. Add to errors list                                                  ││
│ │   4. Return immediately (fail-safe)                                      ││
│ │ Propagation: NEVER propagate - shutdown must continue                    ││
│ │ Recovery: result.state = FAILED, shutdown continues                      ││
│ └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Audit Logging Insertion Points

```python
# Insertion points marked with [AUDIT] comments

async def execute_liquidation(self, trigger: str = "unknown") -> LiquidationResult:
    correlation_id = self._generate_correlation_id()
    start_time = time.monotonic()

    # [AUDIT] Point 1: Liquidation decision
    if not self.config.emergency_liquidation:
        self.audit_logger.log_event(
            event_type=AuditEventType.LIQUIDATION_SKIPPED,
            operation="execute_liquidation",
            additional_data={
                "correlation_id": correlation_id,
                "reason": "emergency_liquidation=false",
                "config": self.config.__dict__,
            },
        )
        return LiquidationResult(state=LiquidationState.SKIPPED)

    # [AUDIT] Point 2: Liquidation started
    self.audit_logger.log_event(
        event_type=AuditEventType.LIQUIDATION_STARTED,
        operation="execute_liquidation",
        additional_data={
            "correlation_id": correlation_id,
            "trigger": trigger,
            "config": self.config.__dict__,
        },
    )

    try:
        # [AUDIT] Point 3: Positions queried
        positions = await self._query_all_positions()
        self.audit_logger.log_event(
            event_type=AuditEventType.LIQUIDATION_POSITIONS_QUERIED,
            operation="query_positions",
            additional_data={
                "correlation_id": correlation_id,
                "positions": [p.__dict__ for p in positions],
            },
        )

        for position in positions:
            # [AUDIT] Point 4: Orders cancelled
            cancelled = await self._cancel_orders_for_symbol(position.symbol)
            self.audit_logger.log_event(
                event_type=AuditEventType.LIQUIDATION_ORDERS_CANCELLED,
                operation="cancel_orders",
                symbol=position.symbol,
                additional_data={
                    "correlation_id": correlation_id,
                    "cancelled_count": cancelled,
                },
            )

            # [AUDIT] Point 5: Position closed (success or failure)
            success, pnl = await self._close_position(position)
            if success:
                self.audit_logger.log_event(
                    event_type=AuditEventType.LIQUIDATION_POSITION_CLOSED,
                    operation="close_position",
                    symbol=position.symbol,
                    additional_data={
                        "correlation_id": correlation_id,
                        "quantity": position.quantity,
                        "realized_pnl": pnl,
                    },
                )
            else:
                self.audit_logger.log_event(
                    event_type=AuditEventType.LIQUIDATION_POSITION_CLOSE_FAILED,
                    operation="close_position",
                    symbol=position.symbol,
                    error={"message": "Failed to close position"},
                    additional_data={"correlation_id": correlation_id},
                )

    except asyncio.TimeoutError:
        # [AUDIT] Point 6: Timeout
        self.audit_logger.log_event(
            event_type=AuditEventType.LIQUIDATION_TIMEOUT,
            operation="execute_liquidation",
            error={"message": f"Timeout after {self.config.timeout_seconds}s"},
            additional_data={"correlation_id": correlation_id},
        )

    except Exception as e:
        # [AUDIT] Point 7: Unexpected error
        self.audit_logger.log_event(
            event_type=AuditEventType.LIQUIDATION_FAILED,
            operation="execute_liquidation",
            error={"message": str(e), "type": type(e).__name__},
            additional_data={"correlation_id": correlation_id},
        )

    finally:
        # [AUDIT] Point 8: Final result
        duration = time.monotonic() - start_time
        self.audit_logger.log_event(
            event_type=self._determine_final_event_type(),
            operation="execute_liquidation",
            additional_data={
                "correlation_id": correlation_id,
                "duration_seconds": duration,
                "positions_closed": positions_closed,
                "positions_failed": positions_failed,
                "total_realized_pnl": total_pnl,
            },
        )
```

---

## 5. Testing Strategy

### 5.1 Unit Test Scenarios

#### 5.1.1 LiquidationConfig Tests

```python
class TestLiquidationConfig:
    """Unit tests for LiquidationConfig validation."""

    def test_default_config_enables_liquidation(self):
        """Default config should have emergency_liquidation=True."""
        config = LiquidationConfig()
        assert config.emergency_liquidation is True

    def test_explicit_disable_logs_critical_warning(self, caplog):
        """Disabling liquidation should log CRITICAL warning."""
        with caplog.at_level(logging.CRITICAL):
            config = LiquidationConfig(emergency_liquidation=False)
        assert "SECURITY WARNING" in caplog.text
        assert "HIGH-RISK" in caplog.text

    def test_invalid_timeout_raises_error(self):
        """Invalid timeout should raise ConfigurationError."""
        with pytest.raises(ConfigurationError):
            LiquidationConfig(timeout_seconds=0)
        with pytest.raises(ConfigurationError):
            LiquidationConfig(timeout_seconds=100)

    def test_invalid_max_retries_raises_error(self):
        """Invalid max_retries should raise ConfigurationError."""
        with pytest.raises(ConfigurationError):
            LiquidationConfig(max_retries=-1)
        with pytest.raises(ConfigurationError):
            LiquidationConfig(max_retries=20)
```

#### 5.1.2 LiquidationManager Unit Tests

```python
class TestLiquidationManager:
    """Unit tests for LiquidationManager."""

    @pytest.fixture
    def mock_order_manager(self):
        """Create mock OrderExecutionManager."""
        manager = Mock(spec=OrderExecutionManager)
        manager.get_all_positions = AsyncMock(return_value=[])
        manager.cancel_all_orders = Mock(return_value=0)
        manager.execute_market_close = AsyncMock(return_value=(True, 0.0))
        return manager

    @pytest.fixture
    def mock_audit_logger(self):
        """Create mock AuditLogger."""
        return Mock(spec=AuditLogger)

    def test_idempotent_execution(self, mock_order_manager, mock_audit_logger):
        """Multiple calls should only execute once."""
        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        # First call
        result1 = asyncio.run(manager.execute_liquidation())
        # Second call (should return immediately)
        result2 = asyncio.run(manager.execute_liquidation())

        assert result1.state == result2.state
        # API should only be called once
        mock_order_manager.get_all_positions.assert_called_once()

    def test_disabled_liquidation_returns_skipped(self, mock_order_manager, mock_audit_logger):
        """Disabled config should return SKIPPED state."""
        config = LiquidationConfig(emergency_liquidation=False)
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.SKIPPED
        mock_order_manager.get_all_positions.assert_not_called()

    def test_no_positions_returns_completed(self, mock_order_manager, mock_audit_logger):
        """No positions should return COMPLETED state."""
        mock_order_manager.get_all_positions = AsyncMock(return_value=[])
        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.COMPLETED
        assert result.positions_closed == 0

    def test_successful_close_single_position(self, mock_order_manager, mock_audit_logger):
        """Successfully closing one position."""
        position = Position(symbol="BTCUSDT", side="LONG", entry_price=50000, quantity=0.1)
        mock_order_manager.get_all_positions = AsyncMock(return_value=[position])
        mock_order_manager.execute_market_close = AsyncMock(return_value=(True, 100.0))

        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.COMPLETED
        assert result.positions_closed == 1
        assert result.total_realized_pnl == 100.0

    def test_partial_failure(self, mock_order_manager, mock_audit_logger):
        """One success and one failure should return PARTIAL."""
        positions = [
            Position(symbol="BTCUSDT", side="LONG", entry_price=50000, quantity=0.1),
            Position(symbol="ETHUSDT", side="SHORT", entry_price=3000, quantity=1.0),
        ]
        mock_order_manager.get_all_positions = AsyncMock(return_value=positions)
        mock_order_manager.execute_market_close = AsyncMock(
            side_effect=[(True, 50.0), (False, 0.0)]
        )

        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.PARTIAL
        assert result.positions_closed == 1
        assert result.positions_failed == 1

    def test_correlation_id_format(self, mock_order_manager, mock_audit_logger):
        """Correlation ID should follow expected format."""
        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.correlation_id.startswith("liq_")
        assert len(result.correlation_id) > 20  # liq_ + date + time + random
```

### 5.2 Integration Test Scenarios

```python
class TestLiquidationIntegration:
    """Integration tests with mock Binance API."""

    @pytest.fixture
    def testnet_order_manager(self):
        """Create real OrderExecutionManager with testnet."""
        return OrderExecutionManager(
            api_key=os.getenv("BINANCE_TESTNET_API_KEY"),
            api_secret=os.getenv("BINANCE_TESTNET_API_SECRET"),
            is_testnet=True,
        )

    @pytest.mark.integration
    async def test_full_liquidation_flow_testnet(self, testnet_order_manager):
        """Full liquidation flow on testnet."""
        # Setup: Create a small position on testnet
        # This test requires manual position setup or a fixture that creates one

        audit_logger = AuditLogger(log_dir="logs/test_audit")
        config = LiquidationConfig()
        manager = LiquidationManager(config, testnet_order_manager, audit_logger)

        result = await manager.execute_liquidation(trigger="integration_test")

        # Verify result structure
        assert result.correlation_id is not None
        assert result.duration_seconds > 0
        assert result.state in (
            LiquidationState.COMPLETED,
            LiquidationState.PARTIAL,
            LiquidationState.SKIPPED,  # If no positions
        )

    @pytest.mark.integration
    async def test_audit_log_created(self, testnet_order_manager, tmp_path):
        """Verify audit log files are created."""
        audit_dir = tmp_path / "audit"
        audit_logger = AuditLogger(log_dir=str(audit_dir))
        config = LiquidationConfig()
        manager = LiquidationManager(config, testnet_order_manager, audit_logger)

        await manager.execute_liquidation()
        audit_logger.stop()  # Flush logs

        # Check audit log exists
        audit_files = list(audit_dir.glob("audit_*.jsonl"))
        assert len(audit_files) >= 1

        # Check log content
        with open(audit_files[0]) as f:
            lines = f.readlines()
            assert any("liquidation_" in line for line in lines)
```

### 5.3 Security Test Cases

```python
class TestLiquidationSecurity:
    """Security-focused tests."""

    def test_api_keys_not_in_logs(self, caplog, mock_order_manager, mock_audit_logger):
        """API keys should never appear in logs."""
        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        # Simulate API error that might include key
        mock_order_manager.get_all_positions = AsyncMock(
            side_effect=Exception("API Error with key=abc123secret")
        )

        with caplog.at_level(logging.DEBUG):
            asyncio.run(manager.execute_liquidation())

        # Verify no API key patterns in logs
        for record in caplog.records:
            assert "api_key" not in record.message.lower()
            assert "api_secret" not in record.message.lower()
            assert "abc123secret" not in record.message

    def test_reduce_only_enforced(self, mock_order_manager, mock_audit_logger):
        """All close orders must have reduceOnly=True."""
        position = Position(symbol="BTCUSDT", side="LONG", entry_price=50000, quantity=0.1)
        mock_order_manager.get_all_positions = AsyncMock(return_value=[position])

        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        asyncio.run(manager.execute_liquidation())

        # Verify reduceOnly=True was passed
        mock_order_manager.execute_market_close.assert_called_with(
            symbol="BTCUSDT",
            side="SELL",  # Opposite of LONG
            quantity=0.1,
            reduce_only=True,  # MUST be True
        )

    def test_timeout_prevents_blocking(self, mock_order_manager, mock_audit_logger):
        """Timeout should prevent indefinite blocking."""
        async def slow_api_call():
            await asyncio.sleep(10)  # Simulate slow API
            return []

        mock_order_manager.get_all_positions = slow_api_call
        config = LiquidationConfig(timeout_seconds=0.1)  # Fast timeout
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        start = time.monotonic()
        result = asyncio.run(manager.execute_liquidation())
        duration = time.monotonic() - start

        assert duration < 1.0  # Should not take 10 seconds
        assert result.state in (LiquidationState.FAILED, LiquidationState.PARTIAL)
```

### 5.4 Failure Scenario Testing

```python
class TestLiquidationFailureScenarios:
    """Tests for various failure scenarios."""

    def test_api_rate_limit_handled(self, mock_order_manager, mock_audit_logger):
        """Rate limit errors should be retried."""
        from binance.error import ClientError

        # First call fails with rate limit, second succeeds
        mock_order_manager.get_all_positions = AsyncMock(
            side_effect=[
                ClientError(status_code=429, error_code=-1015, error_message="Rate limit"),
                [],
            ]
        )

        config = LiquidationConfig(max_retries=2)
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.COMPLETED
        assert mock_order_manager.get_all_positions.call_count == 2

    def test_network_error_handled(self, mock_order_manager, mock_audit_logger):
        """Network errors should be retried."""
        import aiohttp

        mock_order_manager.get_all_positions = AsyncMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )

        config = LiquidationConfig(max_retries=3)
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.FAILED
        assert "Connection refused" in str(result.errors)

    def test_invalid_api_key_no_retry(self, mock_order_manager, mock_audit_logger):
        """Invalid API key should not be retried."""
        from binance.error import ClientError

        mock_order_manager.get_all_positions = AsyncMock(
            side_effect=ClientError(
                status_code=401, error_code=-2015, error_message="Invalid API-key"
            )
        )

        config = LiquidationConfig(max_retries=3)
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.FAILED
        # Should NOT retry auth errors
        assert mock_order_manager.get_all_positions.call_count == 1

    def test_shutdown_continues_after_failure(self, mock_order_manager, mock_audit_logger):
        """Shutdown should continue even after liquidation failure."""
        mock_order_manager.get_all_positions = AsyncMock(
            side_effect=Exception("Catastrophic failure")
        )

        config = LiquidationConfig()
        manager = LiquidationManager(config, mock_order_manager, mock_audit_logger)

        # This should NOT raise an exception
        result = asyncio.run(manager.execute_liquidation())

        assert result.state == LiquidationState.FAILED
        # Shutdown can continue
```

---

## 6. Implementation Guidance

### 6.1 File Structure

```
src/
├── core/
│   ├── __init__.py
│   ├── audit_logger.py          # Existing - add new event types
│   ├── exceptions.py             # Existing - no changes needed
│   └── ...
├── execution/
│   ├── __init__.py               # Export new classes
│   ├── order_manager.py          # Existing - add new methods
│   ├── liquidation_manager.py    # NEW - main liquidation logic
│   └── liquidation_config.py     # NEW - configuration dataclass
├── utils/
│   ├── __init__.py
│   ├── config.py                 # Existing - add LiquidationConfig loading
│   └── ...
└── main.py                       # Existing - integrate LiquidationManager

tests/
├── test_liquidation_manager.py   # NEW - unit tests
├── test_liquidation_config.py    # NEW - config validation tests
├── test_liquidation_security.py  # NEW - security tests
└── integration/
    └── test_liquidation_e2e.py   # NEW - end-to-end tests
```

### 6.2 Code Organization Patterns

#### 6.2.1 Module Exports

```python
# src/execution/__init__.py
from src.execution.order_manager import OrderExecutionManager, RequestWeightTracker
from src.execution.liquidation_manager import LiquidationManager
from src.execution.liquidation_config import LiquidationConfig, LiquidationState, LiquidationResult

__all__ = [
    "OrderExecutionManager",
    "RequestWeightTracker",
    "LiquidationManager",
    "LiquidationConfig",
    "LiquidationState",
    "LiquidationResult",
]
```

#### 6.2.2 Type Hints Pattern

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.execution.order_manager import OrderExecutionManager
    from src.models.position import Position
```

### 6.3 Dependencies and Imports

```python
# liquidation_manager.py

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.core.audit_logger import AuditEventType, AuditLogger
from src.core.exceptions import ConfigurationError
from src.execution.liquidation_config import LiquidationConfig, LiquidationResult, LiquidationState
from src.execution.order_manager import OrderExecutionManager
from src.models.position import Position
```

### 6.4 Configuration Integration

#### 6.4.1 ConfigManager Extension

```python
# In src/utils/config.py

from src.execution.liquidation_config import LiquidationConfig

class ConfigManager:
    # ... existing code ...

    def _load_liquidation_config(self) -> LiquidationConfig:
        """Load liquidation configuration from INI file."""
        section = "liquidation"

        # Use safe defaults if section missing
        if section not in self._trading_parser.sections():
            self.logger.warning(
                "No [liquidation] section in config. Using safe defaults "
                "(emergency_liquidation=true)"
            )
            return LiquidationConfig()

        return LiquidationConfig(
            emergency_liquidation=self._trading_parser.getboolean(
                section, "emergency_liquidation", fallback=True
            ),
            close_positions=self._trading_parser.getboolean(
                section, "close_positions", fallback=True
            ),
            cancel_orders=self._trading_parser.getboolean(
                section, "cancel_orders", fallback=True
            ),
            timeout_seconds=self._trading_parser.getfloat(
                section, "timeout_seconds", fallback=5.0
            ),
            max_retries=self._trading_parser.getint(
                section, "max_retries", fallback=3
            ),
            retry_delay_seconds=self._trading_parser.getfloat(
                section, "retry_delay_seconds", fallback=0.5
            ),
        )

    @property
    def liquidation_config(self) -> LiquidationConfig:
        """Get liquidation configuration."""
        if self._liquidation_config is None:
            self._liquidation_config = self._load_liquidation_config()
        return self._liquidation_config
```

#### 6.4.2 TradingBot Integration

```python
# In src/main.py

class TradingBot:
    def __init__(self) -> None:
        # ... existing init ...
        self.liquidation_manager: Optional[LiquidationManager] = None

    async def initialize(self) -> None:
        # ... existing initialization ...

        # Initialize LiquidationManager
        liquidation_config = self.config_manager.liquidation_config
        self.liquidation_manager = LiquidationManager(
            config=liquidation_config,
            order_manager=self.order_manager,
            audit_logger=self.order_manager.audit_logger,  # Share audit logger
            logger=self.logger,
        )

        self.logger.info(
            f"LiquidationManager initialized "
            f"(emergency_liquidation={liquidation_config.emergency_liquidation})"
        )

    async def shutdown(self) -> None:
        """Graceful shutdown with liquidation."""
        if self._lifecycle_state in (LifecycleState.STOPPING, LifecycleState.STOPPED):
            return

        self._lifecycle_state = LifecycleState.STOPPING
        self.logger.info("Initiating shutdown...")

        # Execute emergency liquidation FIRST
        if self.liquidation_manager:
            try:
                result = await self.liquidation_manager.execute_liquidation(
                    trigger="shutdown"
                )
                self.logger.info(
                    f"Liquidation complete: state={result.state.value}, "
                    f"closed={result.positions_closed}, pnl={result.total_realized_pnl}"
                )
            except Exception as e:
                # Fail-safe: never block shutdown
                self.logger.critical(f"Liquidation error (continuing shutdown): {e}")

        # Continue with normal shutdown
        await self.trading_engine.shutdown()

        self._lifecycle_state = LifecycleState.STOPPED
        self.logger.info("Shutdown complete")
```

### 6.5 Example INI Configuration

```ini
# configs/trading_config.ini

[trading]
symbol = BTCUSDT
intervals = 15m,1h
strategy = ict_silver_bullet
leverage = 10
max_risk_per_trade = 0.02
take_profit_ratio = 2.0
stop_loss_percent = 0.01

[liquidation]
# Emergency liquidation on shutdown
# WARNING: Setting to false leaves positions open on shutdown
emergency_liquidation = true

# Close all open positions
close_positions = true

# Cancel all pending orders
cancel_orders = true

# Maximum time for liquidation (seconds)
timeout_seconds = 5.0

# Retry attempts per operation
max_retries = 3

# Delay between retries (seconds)
retry_delay_seconds = 0.5
```

---

## 7. Staged Implementation Plan

### Stage 1: Emergency Mitigation (Week 1)

**Objective**: Implement basic emergency liquidation with safety defaults

**Deliverables**:
1. `LiquidationConfig` dataclass with validation
2. `LiquidationState` enum
3. `LiquidationResult` dataclass
4. `LiquidationManager` with basic `execute_liquidation()`
5. New `AuditEventType` entries for liquidation
6. Unit tests for config validation and basic flow

**Success Criteria**:
- Emergency liquidation enabled by default
- Config validation prevents invalid settings
- Basic audit trail for liquidation events
- Unit tests passing

### Stage 2: Operational Learning (Week 2)

**Objective**: Add retry logic, timeout handling, and comprehensive audit

**Deliverables**:
1. Retry with exponential backoff
2. Timeout enforcement with `asyncio.wait_for`
3. Correlation ID for audit trail
4. Integration with `TradingBot.shutdown()`
5. Integration tests on testnet
6. Security tests for API key protection

**Success Criteria**:
- Graceful handling of transient failures
- Timeout prevents blocking shutdown
- Full audit trail for compliance
- Testnet validation passing

### Stage 3: Architecture Evolution (Week 3)

**Objective**: Production hardening and documentation

**Deliverables**:
1. `OrderExecutionManager.get_all_positions()` implementation
2. `OrderExecutionManager.execute_market_close()` implementation
3. ConfigManager integration for `[liquidation]` section
4. Comprehensive documentation
5. Performance optimization (< 5 second shutdown)
6. Production deployment checklist

**Success Criteria**:
- All positions closed within timeout
- Zero shutdown blocking
- Complete documentation
- Production ready

---

## 8. Risk Assessment and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Accidental liquidation disabled | Low | High | Default true, CRITICAL warning |
| API key exposure in logs | Low | Critical | Never log credentials |
| Timeout too short | Medium | Medium | Configurable with sensible default |
| Retry storm on failure | Low | Medium | Max retry limit, exponential backoff |
| Race condition in concurrent shutdown | Low | Low | Idempotent state machine |
| Audit log corruption | Low | Medium | Async I/O with flush on stop |
| Incomplete position closure | Medium | High | Best-effort with partial state |

---

## 9. Appendix: Quick Reference

### 9.1 Configuration Defaults

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| emergency_liquidation | true | boolean | Enable liquidation on shutdown |
| close_positions | true | boolean | Close open positions |
| cancel_orders | true | boolean | Cancel pending orders |
| timeout_seconds | 5.0 | 0-60 | Max liquidation time |
| max_retries | 3 | 0-10 | Retry attempts |
| retry_delay_seconds | 0.5 | 0-5 | Base retry delay |

### 9.2 State Transition Summary

```
IDLE ──[config.enabled]──> IN_PROGRESS ──[success]──> COMPLETED
  │                              │
  │                              ├──[partial]──> PARTIAL
  │                              │
  └──[config.disabled]──> SKIPPED └──[failure]──> FAILED
```

### 9.3 Audit Event Types

| Event Type | When Logged |
|------------|-------------|
| LIQUIDATION_STARTED | Liquidation begins |
| LIQUIDATION_SKIPPED | Config disabled liquidation |
| LIQUIDATION_POSITIONS_QUERIED | Positions retrieved |
| LIQUIDATION_ORDERS_CANCELLED | Orders cancelled for symbol |
| LIQUIDATION_POSITION_CLOSED | Position closed successfully |
| LIQUIDATION_POSITION_CLOSE_FAILED | Position close failed |
| LIQUIDATION_COMPLETED | All positions closed |
| LIQUIDATION_PARTIAL | Some positions failed |
| LIQUIDATION_FAILED | Liquidation failed completely |
| LIQUIDATION_TIMEOUT | Timeout exceeded |

---

*Document Version: 1.0*
*Created: 2025-01-02*
*Author: System Architect (Claude Code)*
*Review Status: Design Complete, Implementation Pending*
