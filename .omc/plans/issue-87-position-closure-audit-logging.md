# Work Plan: Issue #87 - Position Closure Audit Logging

**Issue:** Improve Position Closure Audit Logging - Track TP/SL Order Fills
**Scope:** Full implementation (P0 + P1 + P2) with unit tests
**Branch:** `issue-87`

---

## Summary

Add comprehensive audit logging when positions close via Take Profit (TP) or Stop Loss (SL) order fills. Track entry prices, timestamps, calculate holding duration and realized PnL.

---

## Implementation Tasks

### Phase 1: Core Infrastructure (P0)

#### Task 1.1: Add POSITION_CLOSED to AuditEventType
**File:** `src/core/audit_logger.py`
**Changes:**
- Add `POSITION_CLOSED = "position_closed"` to `AuditEventType` enum (after line 53)
- This provides semantic clarity vs reusing `TRADE_CLOSED` (used by LiquidationManager)

#### Task 1.2: Add AuditLogger integration to PrivateUserStreamer
**File:** `src/core/private_user_streamer.py`
**Changes:**
- Add `_audit_logger: Optional[AuditLogger] = None` instance variable
- Add `set_audit_logger(self, audit_logger: AuditLogger)` method (similar to `set_event_bus()`)
- Import `AuditLogger` and `AuditEventType` from `src/core/audit_logger`

#### Task 1.3: Log position closure in _handle_order_trade_update()
**File:** `src/core/private_user_streamer.py`
**Changes:**
- In `_handle_order_trade_update()`, after publishing ORDER_FILLED event
- Add audit logging for TP/SL fills with:
  - `close_reason`: TAKE_PROFIT, STOP_LOSS, or TRAILING_STOP
  - `exit_price`: from `order_data.get("ap")`
  - `exit_quantity`: from `order_data.get("z")`
  - `exit_side`: from `order_data.get("S")`
  - `order_id`, `order_type`

### Phase 2: Entry Data Tracking (P1)

#### Task 2.1: Add position state tracking
**File:** `src/core/private_user_streamer.py`
**Changes:**
- Add `_position_entry_data: Dict[str, PositionEntryData]` dictionary
- Create `PositionEntryData` dataclass with `entry_price`, `entry_time`, `quantity`, `side`
- Initialize in `__init__`

#### Task 2.2: Track entry data on position open
**File:** `src/core/private_user_streamer.py`
**Changes:**
- In `_handle_order_trade_update()`, when a MARKET/LIMIT order is FILLED (not TP/SL)
- Store entry data: `{symbol: PositionEntryData(price, timestamp, qty, side)}`
- Consider: Also handle `_handle_account_update()` for position sync

#### Task 2.3: Wire up AuditLogger in application startup
**File:** `src/main.py` or wherever PrivateUserStreamer is instantiated
**Changes:**
- Call `private_user_streamer.set_audit_logger(audit_logger)` during initialization
- Ensure audit_logger is created before private_user_streamer setup

### Phase 3: Metrics Calculation (P2)

#### Task 3.1: Calculate holding duration
**File:** `src/core/private_user_streamer.py`
**Changes:**
- In `_handle_order_trade_update()` for TP/SL fills:
  - Look up entry_time from `_position_entry_data[symbol]`
  - Calculate `held_duration_seconds = (now - entry_time).total_seconds()`
  - Include in audit log data

#### Task 3.2: Calculate realized PnL
**File:** `src/core/private_user_streamer.py`
**Changes:**
- In `_handle_order_trade_update()` for TP/SL fills:
  - Look up entry_price from `_position_entry_data[symbol]`
  - Calculate PnL based on position side:
    - LONG: `(exit_price - entry_price) * quantity`
    - SHORT: `(entry_price - exit_price) * quantity`
  - Include in audit log data

#### Task 3.3: Clean up position state after closure
**File:** `src/core/private_user_streamer.py`
**Changes:**
- After logging TP/SL fill, remove entry from `_position_entry_data`
- Prevents memory leak for long-running sessions

### Phase 4: Testing

#### Task 4.1: Unit tests for PrivateUserStreamer audit logging
**File:** `tests/test_private_user_streamer.py` (new file)
**Tests:**
- `test_tp_order_fill_logs_position_closed()` - TP fill triggers audit log
- `test_sl_order_fill_logs_position_closed()` - SL fill triggers audit log
- `test_trailing_stop_fill_logs_position_closed()` - Trailing stop triggers audit log
- `test_position_entry_data_tracked()` - Entry data stored on position open
- `test_realized_pnl_calculation_long()` - Correct PnL for long positions
- `test_realized_pnl_calculation_short()` - Correct PnL for short positions
- `test_holding_duration_calculation()` - Duration calculated correctly
- `test_position_state_cleanup_after_closure()` - Memory cleaned up

#### Task 4.2: Integration test for full trade lifecycle
**File:** `tests/test_private_user_streamer.py`
**Tests:**
- `test_full_trade_lifecycle_audit_trail()` - Open → TP/SL → Closed logged correctly

---

## File Changes Summary

| File | Type | Changes |
|------|------|---------|
| `src/core/audit_logger.py` | Edit | Add POSITION_CLOSED to AuditEventType |
| `src/core/private_user_streamer.py` | Edit | Add audit logging, entry tracking, calculations |
| `src/main.py` | Edit | Wire audit_logger to PrivateUserStreamer |
| `tests/test_private_user_streamer.py` | New | Unit tests for audit logging |

---

## Expected Audit Log Output

```json
{
    "timestamp": "2026-02-01T01:12:34.567890",
    "event_type": "position_closed",
    "operation": "tp_sl_order_filled",
    "symbol": "ZECUSDT",
    "data": {
        "close_reason": "TAKE_PROFIT",
        "exit_price": 309.00,
        "exit_quantity": 1.416,
        "exit_side": "BUY",
        "entry_price": 312.48,
        "realized_pnl": -4.93,
        "held_duration_seconds": 454.14,
        "order_id": "1000000008633681",
        "order_type": "TAKE_PROFIT_MARKET"
    }
}
```

---

## Dependencies

- No external dependencies required
- Uses existing AuditLogger infrastructure
- Uses existing EventBus patterns

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Memory leak from untracked positions | Task 3.3 cleans up state after closure |
| Entry data not available (position opened before restart) | Log with `entry_price: null`, gracefully degrade |
| Hot path latency | Memory tracking (no API calls), minimal overhead |

---

## Verification Checklist

- [ ] TP order fill logs `POSITION_CLOSED` with `close_reason: "TAKE_PROFIT"`
- [ ] SL order fill logs `POSITION_CLOSED` with `close_reason: "STOP_LOSS"`
- [ ] Trailing stop fill logs `POSITION_CLOSED` with `close_reason: "TRAILING_STOP"`
- [ ] Entry price and exit price recorded correctly
- [ ] Realized PnL calculated accurately
- [ ] Holding duration calculated correctly
- [ ] Audit logs written to daily JSONL file
- [ ] No duplicate events for same closure
- [ ] All unit tests pass
- [ ] No memory leaks (state cleaned up)

---

## Execution Order

1. Task 1.1 → Task 1.2 → Task 1.3 (P0 - Core)
2. Task 2.1 → Task 2.2 → Task 2.3 (P1 - Entry Tracking)
3. Task 3.1 → Task 3.2 → Task 3.3 (P2 - Calculations)
4. Task 4.1 → Task 4.2 (Testing)

---

**Ready for implementation approval.**
