# Log Structure Analysis

**Analysis Date**: 2025-12-31
**Purpose**: Diagnose and organize logging system

## Current Log Structure

### 1. `trading.log` (Main Application Log)
- **Purpose**: All application events, debug information, system lifecycle
- **Handler**: RotatingFileHandler
- **Rotation**: Size-based (10MB max, 5 backups)
- **Current Size**: 4.2M
- **Format**: `%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s`
- **Status**: ✅ **Properly configured and in use**

**Sample Content**:
```
2025-12-30 21:21:00,827 | INFO     | src.execution.order_manager:1156 | Entry order executed: ID=1052635090, status=FILLED, filled=0.926 @ 538.69
2025-12-30 21:21:00,889 | INFO     | src.core.event_handler:123 | Event published: CANDLE_CLOSED
```

### 2. `trades.log` (Unused)
- **Purpose**: Intended for trade-specific events only
- **Handler**: TimedRotatingFileHandler
- **Rotation**: Daily at midnight (30-day retention)
- **Current Size**: 0 bytes (empty)
- **Filter**: TradeLogFilter (only logs from logger named 'trades')
- **Status**: ⚠️ **Configured but never used**

**Issue**: No code in the system uses `logging.getLogger('trades')`, so this handler receives no log entries.

### 3. `logs/audit/` (Structured Trade Events)
- **Purpose**: Compliance and audit trail for all trading operations
- **Format**: Daily JSONL files (`audit_YYYYMMDD.jsonl`)
- **Current Files**:
  - `audit_20251226.jsonl` - 3.9K
  - `audit_20251227.jsonl` - 13K
  - `audit_20251228.jsonl` - 30K
  - `audit_20251229.jsonl` - 148K
  - `audit_20251230.jsonl` - 299K (peak trading day)
  - `audit_20251231.jsonl` - 35K
- **Status**: ✅ **Properly configured and actively used**

**Event Types Logged**:
- `balance_query` - Account balance checks
- `leverage_set` - Leverage configuration
- `margin_type_set` - Margin type configuration
- `order_placed` - TP/SL order placement
- `position_query` - Position status checks
- `position_size_calculated` - Risk management calculations
- `position_size_capped` - Position size limits applied
- `risk_rejection` - Rejected signals due to risk validation
- `risk_validation` - Risk validation results
- `signal_processing` - Strategy signal generation
- `trade_executed` - Actual trade executions
- `order_cancelled` - Order cancellation events

**Sample JSONL Entry**:
```json
{
  "timestamp": "2025-12-30T21:21:00.889529",
  "event_type": "trade_executed",
  "order_data": {
    "signal_type": "short_entry",
    "entry_price": 538.69,
    "quantity": 0.926,
    "take_profit": 533.95,
    "stop_loss": 540.61869
  }
}
```

## Log Rotation Policies

| File | Rotation Type | Trigger | Retention |
|------|--------------|---------|-----------|
| trading.log | Size-based | 10MB | 5 backups (~50MB total) |
| trades.log | Time-based | Daily midnight | 30 days |
| audit/*.jsonl | Daily | Midnight (implicit) | Unlimited |

## Recommendations

### 1. Remove Unused `trades.log` Handler
**Rationale**:
- The trades.log handler is configured but never receives any events
- Trade events are already comprehensively logged to `logs/audit/` in JSONL format
- JSONL format is superior for structured data analysis and compliance
- Removes unnecessary file I/O overhead

**Action**: Remove trade_handler from logger.py (lines 117-125)

### 2. Implement Audit Log Retention Policy
**Rationale**:
- Audit logs currently have unlimited retention
- Can grow indefinitely over time
- Should match or exceed trades.log retention (30 days)

**Suggested Policy**:
- Retain 90 days of audit logs for compliance
- Implement automated cleanup script

### 3. Add Log Rotation Monitoring
**Rationale**:
- Large trading.log files (approaching 10MB) indicate high activity
- Should monitor log size growth to detect issues early

**Action**: Add log size monitoring to system health checks

### 4. Document Log Structure
**Status**: ✅ This document serves as the documentation

## Log File Cleanup

### Safe to Delete:
- `trades.log` - 0 bytes, never used
- Old audit logs > 90 days (once retention policy implemented)
- Old trading.log backups (trading.log.1, trading.log.2, etc.) if disk space needed

### Must Keep:
- Current `trading.log`
- Recent `audit/*.jsonl` files (last 30-90 days)
- Any audit files needed for tax/compliance reporting

## Implementation Notes

### Audit Logger Architecture
- Implemented in `src/core/audit_logger.py`
- Singleton pattern with daily file rotation
- Thread-safe for concurrent logging
- Used by OrderExecutionManager, RiskManager, TradingEngine

### Trade Event Flow
```
Signal Generated (Strategy)
    ↓
Risk Validation (RiskManager) → audit log: risk_validation
    ↓
Position Sizing (RiskManager) → audit log: position_size_calculated
    ↓
Order Execution (OrderManager) → audit log: order_placed, trade_executed
    ↓
TP/SL Placement (OrderManager) → audit log: order_placed (2x)
```

## Conclusion

The logging system is well-designed with proper rotation and structured audit trails. The only issue is the unused `trades.log` handler, which should be removed to eliminate unnecessary overhead. Audit logs provide comprehensive trade tracking in a format optimized for analysis and compliance.
