# Emergency Liquidation System Design Summary

## Design Document Location
`.taskmaster/designs/emergency-liquidation-system-design.md`

## Key Components

### New Files to Create
1. `src/execution/liquidation_config.py` - Configuration dataclass
2. `src/execution/liquidation_manager.py` - Main liquidation logic
3. `tests/test_liquidation_manager.py` - Unit tests
4. `tests/test_liquidation_security.py` - Security tests

### Files to Modify
1. `src/core/audit_logger.py` - Add new AuditEventType entries
2. `src/execution/__init__.py` - Export new classes
3. `src/utils/config.py` - Add liquidation config loading
4. `src/main.py` - Integrate LiquidationManager in shutdown

## Core Classes

### LiquidationConfig
- `emergency_liquidation: bool = True` (DEFAULT: enabled for safety)
- `close_positions: bool = True`
- `cancel_orders: bool = True`
- `timeout_seconds: float = 5.0`
- `max_retries: int = 3`
- `retry_delay_seconds: float = 0.5`

### LiquidationState (Enum)
- IDLE, IN_PROGRESS, COMPLETED, PARTIAL, FAILED, SKIPPED

### LiquidationResult
- state, positions_closed, positions_failed, orders_cancelled
- total_realized_pnl, duration_seconds, errors, correlation_id

### LiquidationManager
- `execute_liquidation(trigger: str) -> LiquidationResult`
- Idempotent, fail-safe, comprehensive audit trail

## Security Design Principles
1. Default to capital protection (emergency_liquidation=True)
2. Reverse the risk (opt-out, not opt-in)
3. Never expose API keys in logs
4. Enforce reduceOnly=True for all close orders
5. Timeout enforcement (never block shutdown)
6. Comprehensive audit trail

## New AuditEventType Entries
- LIQUIDATION_STARTED
- LIQUIDATION_SKIPPED
- LIQUIDATION_POSITIONS_QUERIED
- LIQUIDATION_ORDERS_CANCELLED
- LIQUIDATION_POSITION_CLOSED
- LIQUIDATION_POSITION_CLOSE_FAILED
- LIQUIDATION_COMPLETED
- LIQUIDATION_PARTIAL
- LIQUIDATION_FAILED
- LIQUIDATION_TIMEOUT

## Implementation Stages
1. Stage 1 (Week 1): Emergency Mitigation - Basic classes and validation
2. Stage 2 (Week 2): Operational Learning - Retry, timeout, audit
3. Stage 3 (Week 3): Architecture Evolution - Production hardening

## Configuration INI Section
```ini
[liquidation]
emergency_liquidation = true
close_positions = true
cancel_orders = true
timeout_seconds = 5.0
max_retries = 3
retry_delay_seconds = 0.5
```
