# Emergency Liquidation - Troubleshooting Guide

**Purpose**: Common issues and resolution procedures
**Last Updated**: 2026-01-02

---

## Common Issues

### Issue 1: Re-entrant Call Blocked

**Symptom**:
```
LiquidationResult(
    state=FAILED,
    error_message="Liquidation already in progress"
)
```

**Cause**:
- Second shutdown called while first liquidation still executing
- State stuck in IN_PROGRESS from previous hung execution

**Resolution**:

1. **Check if liquidation is actually running**:
```bash
# Check recent liquidation events
grep "LIQUIDATION" logs/audit.jsonl | tail -10

# Look for IN_PROGRESS without matching COMPLETE/FAILED
```

2. **If legitimately in progress**:
   - Wait for execution to complete (max `timeout_seconds`, default 5s)
   - Monitor with: `tail -f logs/audit.jsonl | grep LIQUIDATION`

3. **If hung in IN_PROGRESS state**:
```bash
# Restart trading bot (state resets to IDLE on init)
kill -SIGTERM $(pidof python)
python src/main.py
```

4. **Verify state reset**:
```python
from src.main import TradingBot
bot = TradingBot()
bot.initialize()
print(bot.liquidation_manager._state)  # Should be IDLE
```

---

### Issue 2: Timeout Exceeded

**Symptom**:
```
Operations take longer than timeout_seconds
Total duration: 7.5s (timeout: 5.0s)
Some positions may not be closed
```

**Cause**:
- Network latency to exchange API
- Slow API responses
- Large number of positions requiring serial processing
- Rate limiting delays

**Resolution**:

1. **Increase timeout** (short-term):
```python
# In configuration
config = LiquidationConfig(
    timeout_seconds=10.0  # Increase from default 5.0s
)
```

2. **Increase retries** (if intermittent failures):
```python
config = LiquidationConfig(
    max_retries=5,  # Increase from default 3
    retry_delay_seconds=1.0  # Longer delays
)
```

3. **Check network connectivity**:
```bash
# Test API latency
time curl -X GET "https://fapi.binance.com/fapi/v1/ping"

# Should respond in < 100ms typically
```

4. **Review API rate limits**:
```bash
# Check recent API errors
grep "rate limit" logs/trading.log

# Review exchange API limits
# Binance Futures: 1200 requests/minute
```

5. **Optimize position count** (long-term):
   - Reduce number of active positions
   - Consolidate positions across fewer symbols
   - Consider parallel processing optimization

---

### Issue 3: Partial Liquidation

**Symptom**:
```
state=PARTIAL
positions_closed=2
positions_failed=1
```

**Cause**:
- API failures for specific symbols
- Insufficient margin for position closure
- Position locked by exchange
- Symbol delisted or trading halted

**Resolution**:

1. **Review audit logs for specific failures**:
```bash
# Find failed position closures
jq 'select(.event_type == "ORDER_REJECTED")' logs/audit.jsonl | tail -5

# Look for error details
```

2. **Manual position closure for failed symbols**:
```bash
# Via Binance web interface:
# 1. Navigate to Futures > Positions
# 2. Find failed position
# 3. Click "Market Close"
# 4. Confirm closure
```

3. **Check exchange status**:
```bash
# Verify symbol is trading
curl "https://fapi.binance.com/fapi/v1/exchangeInfo" | jq '.symbols[] | select(.symbol == "BTCUSDT")'

# Check for trading restrictions
```

4. **Verify account permissions**:
```bash
# Test API connectivity with position query
curl -X GET "https://fapi.binance.com/fapi/v2/positionRisk" \
  -H "X-MBX-APIKEY: your_api_key"

# Should return 200 OK with position data
```

5. **Document incident**:
```markdown
# Incident Report Template
**Date**: 2026-01-02
**Type**: Partial Liquidation
**Affected Symbols**: ETHUSDT
**Positions Closed**: 2/3
**Failed Positions**: ETHUSDT (1.5 ETH LONG)
**Error**: "Insufficient margin"
**Resolution**: Manual closure via web interface
**Root Cause**: Margin depleted during market volatility
**Prevention**: Monitor margin ratio, set margin alerts
```

---

### Issue 4: Configuration Error

**Symptom**:
```python
ConfigurationError: timeout_seconds must be between 1.0 and 30.0, got 0.5
```

**Cause**:
- Invalid parameter types (string instead of float)
- Out-of-range values
- Logical inconsistencies in configuration

**Resolution**:

1. **Check timeout_seconds range**: 1.0-30.0
```python
config = LiquidationConfig(timeout_seconds=5.0)  # Valid
# config = LiquidationConfig(timeout_seconds=0.5)  # ❌ Too low
# config = LiquidationConfig(timeout_seconds=60.0)  # ❌ Too high
```

2. **Check max_retries range**: 0-10
```python
config = LiquidationConfig(max_retries=3)  # Valid
# config = LiquidationConfig(max_retries=-1)  # ❌ Negative
# config = LiquidationConfig(max_retries=20)  # ❌ Too high
```

3. **Check retry_delay_seconds range**: 0.1-5.0
```python
config = LiquidationConfig(retry_delay_seconds=0.5)  # Valid
# config = LiquidationConfig(retry_delay_seconds=0.01)  # ❌ Too low
# config = LiquidationConfig(retry_delay_seconds=10.0)  # ❌ Too high
```

4. **Verify consistency** (emergency_liquidation logic):
```python
# ✅ Valid combinations
config = LiquidationConfig(
    emergency_liquidation=True,
    close_positions=True,
    cancel_orders=True
)

config = LiquidationConfig(
    emergency_liquidation=False,
    close_positions=False,
    cancel_orders=False
)

# ❌ Invalid - inconsistent
# config = LiquidationConfig(
#     emergency_liquidation=False,
#     close_positions=True,  # Inconsistent!
#     cancel_orders=True
# )
```

5. **Use validation script**:
```bash
python scripts/validate_liquidation_config.py --env=production
# Will show specific configuration errors
```

---

### Issue 5: Missing Audit Logs

**Symptom**:
```
No liquidation events in audit.jsonl
Liquidation executed but no log entries
```

**Cause**:
- AuditLogger not initialized
- Log directory not writable
- Incorrect audit logger configuration
- Logger not passed to LiquidationManager

**Resolution**:

1. **Verify audit_logger initialization** (src/main.py):
```python
from src.core.audit_logger import AuditLogger

# Initialize audit logger
self.audit_logger = AuditLogger(log_dir="logs")

# Pass to liquidation manager
self.liquidation_manager = LiquidationManager(
    config=config,
    order_manager=self.order_manager,
    audit_logger=self.audit_logger  # Must be provided
)
```

2. **Check logs directory permissions**:
```bash
# Verify directory exists
mkdir -p logs

# Check writable
touch logs/test.txt && rm logs/test.txt

# If permission denied:
chmod 755 logs
```

3. **Review audit logger configuration** (src/core/audit_logger.py):
```python
class AuditLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)  # Create if missing
        self.log_file = self.log_dir / "audit.jsonl"
```

4. **Test audit logging manually**:
```python
from src.core.audit_logger import AuditLogger, AuditEventType

logger = AuditLogger(log_dir="logs")
logger.log_event(
    event_type=AuditEventType.LIQUIDATION_START,
    correlation_id="test_123",
    details={"test": True}
)

# Check file created
# cat logs/audit.jsonl
```

5. **Verify log entries**:
```bash
# Check if audit.jsonl exists
ls -lh logs/audit.jsonl

# View recent entries
tail -10 logs/audit.jsonl | jq '.'

# Search for liquidation events
grep LIQUIDATION logs/audit.jsonl | jq '.event_type'
```

---

### Issue 6: Positions Not Closing

**Symptom**:
```
state=COMPLETED
But positions still open on exchange
```

**Cause**:
- `close_positions=False` in configuration
- `reduceOnly` flag not working (rare)
- Position side determination incorrect (LONG/SHORT)
- API response indicates success but order not executed

**Resolution**:

1. **Verify close_positions=True**:
```python
from src.main import TradingBot
bot = TradingBot()
bot.initialize()
config = bot.liquidation_manager.config
print(f"close_positions: {config.close_positions}")  # Must be True
```

2. **Check position side determination** (src/execution/liquidation_manager.py:140):
```python
# Logic should be:
# LONG position (positionAmt > 0) → SELL order
# SHORT position (positionAmt < 0) → BUY order

side = "SELL" if float(position.get("positionAmt", 0)) > 0 else "BUY"
```

3. **Manual close via exchange interface**:
```bash
# Binance Futures UI:
# 1. Go to Positions tab
# 2. Find open position
# 3. Click "Market Close" button
# 4. Confirm order
# 5. Verify position closed
```

4. **Review API response logs**:
```bash
# Check execute_market_close responses
grep "execute_market_close" logs/trading.log | tail -5

# Look for success=True but position still open
# This indicates API or exchange issue
```

5. **Test position closure manually**:
```python
from src.execution.order_manager import OrderExecutionManager

order_mgr = OrderExecutionManager()
result = await order_mgr.execute_market_close(
    symbol="BTCUSDT",
    side="SELL",  # For LONG position
    quantity=0.001
)
print(result)  # Check success and order_id
```

---

## Debugging Commands

### Check Current Configuration
```bash
python -c "from src.main import TradingBot; \
           bot = TradingBot(); \
           bot.initialize(); \
           config = bot.liquidation_manager.config; \
           import json; \
           print(json.dumps({ \
               'emergency_liquidation': config.emergency_liquidation, \
               'close_positions': config.close_positions, \
               'cancel_orders': config.cancel_orders, \
               'timeout_seconds': config.timeout_seconds, \
               'max_retries': config.max_retries \
           }, indent=2))"
```

### View Metrics
```bash
python -c "from src.main import TradingBot; \
           bot = TradingBot(); \
           bot.initialize(); \
           import json; \
           metrics = bot.liquidation_manager.get_metrics(); \
           print(json.dumps(metrics, indent=2, default=str))"
```

### Tail Audit Logs (Real-time)
```bash
# All liquidation events
tail -f logs/audit.jsonl | jq 'select(.event_type | contains("LIQUIDATION"))'

# Specific correlation ID
tail -f logs/audit.jsonl | jq 'select(.correlation_id == "liq_20260102_103000_abc123")'

# Failed events only
tail -f logs/audit.jsonl | jq 'select(.event_type == "ORDER_REJECTED" or .event_type == "LIQUIDATION_FAILED")'
```

### Run Validation
```bash
# Standard validation
python scripts/validate_liquidation_config.py --env=production

# Strict mode (fail on warnings)
python scripts/validate_liquidation_config.py --env=production --strict

# Testnet validation
python scripts/validate_liquidation_config.py --env=testnet
```

### Test with Mock (Dry Run)
```bash
# Run integration tests with mocks
pytest tests/test_liquidation_integration.py -v

# Specific test scenario
pytest tests/test_liquidation_integration.py::TestLiquidationWorkflow::test_normal_shutdown -v

# With output
pytest tests/test_liquidation_integration.py -v -s
```

---

## Emergency Procedures

### Manual Position Closure

If automated liquidation fails completely:

1. **Access exchange web interface**
   - Navigate to: https://www.binance.com/en/futures
   - Login with credentials

2. **Navigate to Positions**
   - Click "Positions" tab
   - View all open positions

3. **Market close each position**
   - Click "Market Close" button for each position
   - Confirm quantity and direction
   - Submit order

4. **Verify closure**
   - Refresh positions view
   - Confirm all positions closed
   - Check realized PnL

5. **Document in incident log**:
```markdown
**Incident**: Manual Position Closure Required
**Date**: 2026-01-02 10:30:00 UTC
**Reason**: Automated liquidation failed due to [reason]
**Positions Manually Closed**:
- BTCUSDT: 0.5 BTC LONG → Closed at $50,000
- ETHUSDT: 2.0 ETH SHORT → Closed at $3,000
**Total PnL**: +$150.00
**Incident Ticket**: INC-2026-001
```

---

### Force Reset State

If liquidation manager stuck in IN_PROGRESS:

1. **Stop trading bot**:
```bash
kill -SIGTERM $(pidof python)
```

2. **Check logs for root cause**:
```bash
# Find last liquidation event
grep LIQUIDATION logs/audit.jsonl | tail -20

# Look for errors
grep -i error logs/trading.log | grep -i liquidation | tail -10
```

3. **Restart trading bot** (state resets to IDLE on init):
```bash
python src/main.py --enable-liquidation
```

4. **Verify state reset**:
```python
from src.main import TradingBot
bot = TradingBot()
bot.initialize()

# Check state
assert bot.liquidation_manager._state == "IDLE"
print("✓ State reset successful")
```

5. **File bug report with logs**:
```markdown
**Bug**: Liquidation Manager Stuck in IN_PROGRESS

**Environment**: Production
**Date**: 2026-01-02
**Duration**: 30 seconds before manual intervention

**Symptoms**:
- State stuck in IN_PROGRESS
- No LIQUIDATION_COMPLETE or LIQUIDATION_FAILED event
- Timeout not enforced

**Logs Attached**:
- audit.jsonl (last 100 lines)
- trading.log (liquidation section)

**Resolution**:
- Manual restart required
- State reset to IDLE

**Investigation Needed**:
- Timeout enforcement mechanism
- Asyncio task cancellation
- State transition logic
```

---

## Diagnostic Workflow

When encountering liquidation issues, follow this systematic approach:

### Step 1: Gather Information
```bash
# Collect recent logs
tail -100 logs/audit.jsonl > audit_recent.log
tail -100 logs/trading.log > trading_recent.log

# Check current state
python -c "from src.main import TradingBot; \
           bot = TradingBot(); \
           bot.initialize(); \
           print('State:', bot.liquidation_manager._state); \
           print('Metrics:', bot.liquidation_manager.get_metrics())"

# Check configuration
python scripts/validate_liquidation_config.py --env=production
```

### Step 2: Identify Issue Category
- Configuration error → Issue 4
- Timeout → Issue 2
- Partial closure → Issue 3
- Re-entry blocked → Issue 1
- No logs → Issue 5
- Positions not closing → Issue 6

### Step 3: Apply Resolution
- Follow specific issue resolution steps
- Test fix on testnet if possible
- Verify resolution in production

### Step 4: Document
- Record issue in incident log
- Update monitoring if needed
- Consider preventive measures

### Step 5: Follow-up
- Monitor for recurrence
- Review logs for patterns
- Update documentation if new issue type

---

## Support Escalation

If issue cannot be resolved using this guide:

1. **Gather diagnostic bundle**:
```bash
# Create diagnostic package
tar -czf liquidation_diagnostic_$(date +%Y%m%d_%H%M%S).tar.gz \
  logs/audit.jsonl \
  logs/trading.log \
  src/execution/liquidation_config.py \
  src/execution/liquidation_manager.py \
  .env.example
```

2. **Document issue**:
   - Symptoms observed
   - Steps attempted
   - Configuration used
   - Environment (testnet/production)
   - Frequency (one-time/recurring)

3. **Contact support**:
   - Internal: DevOps team, Trading operations
   - External: Binance API support (if exchange-related)

4. **Provide logs and context**:
   - Upload diagnostic bundle
   - Share incident timeline
   - Describe business impact

---

**Document Version**: 1.0
**Last Updated**: 2026-01-02
**Maintenance**: Update when new issues discovered
**Related Docs**:
- Operations Guide: `claudedocs/liquidation_operations_guide.md`
- Deployment Checklist: `claudedocs/liquidation_deployment_checklist.md`
