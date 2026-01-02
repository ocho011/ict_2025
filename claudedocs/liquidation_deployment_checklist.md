# Emergency Liquidation - Deployment Checklist

**Purpose**: Step-by-step deployment validation procedures
**Last Updated**: 2026-01-02

---

## Pre-Deployment

### Configuration Validation

- [ ] **Type validation passes**
  ```bash
  python scripts/validate_liquidation_config.py --env=production
  ```
  - All parameter types correct (bool, float, int)
  - No type errors in configuration

- [ ] **Range validation passes**
  - `timeout_seconds`: 1.0-30.0 ✓
  - `max_retries`: 0-10 ✓
  - `retry_delay_seconds`: 0.1-5.0 ✓

- [ ] **Consistency check passes**
  - If `emergency_liquidation=False`, both `close_positions=False` and `cancel_orders=False`
  - No logical contradictions in configuration

- [ ] **Security review completed**
  - No CRITICAL warnings in validation output
  - `emergency_liquidation=True` for production
  - `close_positions=True` for production
  - `cancel_orders=True` for production

- [ ] **Defaults appropriate for environment**
  - Production: 5s timeout, 3 retries recommended
  - High-latency networks: Consider 10-15s timeout, 5 retries

### Dependency Verification

- [ ] **OrderExecutionManager initialized**
  - Component exists in trading bot
  - Properly connected to exchange API

- [ ] **Required methods available**
  - [ ] `async def get_all_positions(symbols: List[str]) -> List[Dict]`
  - [ ] `def cancel_all_orders(symbol: str) -> int`
  - [ ] `async def execute_market_close(symbol: str, side: str, quantity: float) -> Dict`

- [ ] **AuditLogger initialized**
  - Logger instance created
  - Configured with proper event types

- [ ] **Audit trail directory writable**
  ```bash
  # Check logs directory exists and is writable
  mkdir -p logs
  touch logs/test.txt && rm logs/test.txt
  ```

### Testing Validation

- [ ] **All unit tests pass**
  ```bash
  pytest tests/test_liquidation_config.py -v
  pytest tests/test_liquidation_manager.py -v
  pytest tests/test_config_validator.py -v
  ```
  - Expected: 109 tests passing

- [ ] **Integration tests pass**
  ```bash
  pytest tests/test_liquidation_integration.py -v
  pytest tests/test_e2e_liquidation.py -v
  ```
  - All integration scenarios successful

- [ ] **Mock order manager tests pass**
  - Position closure logic validated
  - Order cancellation logic validated
  - Error handling verified

- [ ] **Timeout enforcement verified**
  ```bash
  pytest tests/test_liquidation_manager.py::TestLiquidationTimeout -v
  ```
  - Timeout triggers correctly
  - No hung states

- [ ] **Retry logic verified**
  ```bash
  pytest tests/test_liquidation_manager.py::TestRetryLogic -v
  ```
  - Exponential backoff working
  - Max retries respected

---

## Deployment Steps

### 1. Testnet Deployment

#### Environment Setup
```bash
# Set testnet environment
export TRADING_ENV=testnet
export BINANCE_TESTNET_API_KEY="your_testnet_key"
export BINANCE_TESTNET_API_SECRET="your_testnet_secret"
```

#### Configuration Validation
```bash
# Validate configuration for testnet
python scripts/validate_liquidation_config.py --env=testnet

# Expected output:
# ✓ Valid: True
# ✓ Ready: True
# ⚠️ [WARNING] Testnet environment - proceed with testing
```

#### Integration Tests
```bash
# Run integration tests against testnet
pytest tests/test_liquidation_integration.py -v --testnet

# Verify all scenarios pass
```

#### Monitor First Execution
```bash
# Start trading bot with liquidation enabled
python src/main.py --enable-liquidation &

# Tail audit logs in separate terminal
tail -f logs/audit.jsonl | grep -i liquidation

# Expected events:
# - LIQUIDATION_START
# - ORDER_CANCELLED (per symbol)
# - ORDER_PLACED (per position)
# - LIQUIDATION_COMPLETE
```

#### Testnet Verification Scenarios

**Scenario 1: Normal Shutdown with Positions**
```bash
# 1. Open 2-3 small test positions (BTCUSDT, ETHUSDT)
# 2. Place 1-2 pending limit orders
# 3. Execute shutdown
kill -SIGTERM $(pidof python)

# Expected results:
# - All positions closed within timeout (check exchange)
# - All orders cancelled (check exchange)
# - state=COMPLETED in logs
# - Correlation ID present in all log entries
```

**Verification Commands**:
```bash
# Check final state
grep "LIQUIDATION_COMPLETE" logs/audit.jsonl | tail -1 | jq '.'

# Verify positions closed
# (Manual check on Binance Testnet UI)

# Verify orders cancelled
# (Manual check on Binance Testnet UI)
```

**Scenario 2: Emergency Disabled (Config Test)**
```bash
# 1. Set emergency_liquidation=False in config
# 2. Set close_positions=False, cancel_orders=False
# 3. Open test positions
# 4. Execute shutdown

# Expected results:
# - state=SKIPPED in logs
# - CRITICAL warning logged
# - Positions remain open (verify on exchange)
# - No position close attempts
```

**Scenario 3: Timeout Enforcement**
```bash
# 1. Set timeout_seconds=1.0 (very short)
# 2. Open 5-10 positions
# 3. Execute shutdown

# Expected results:
# - Operation completes within ~1-3 seconds
# - May return state=PARTIAL if not all complete
# - No hung state
# - total_duration_seconds < 3.0
```

**Scenario 4: Partial Failure Simulation**
```bash
# 1. Open 3 positions
# 2. Manually lock one position on exchange (or use invalid symbol)
# 3. Execute shutdown

# Expected results:
# - Some positions close successfully (positions_closed > 0)
# - Some fail (positions_failed > 0)
# - state=PARTIAL
# - Both ORDER_PLACED and ORDER_REJECTED events in logs
```

#### Testnet Success Criteria

- [ ] All 4 scenarios executed successfully
- [ ] No unhandled exceptions during shutdown
- [ ] Audit trail complete for all scenarios
- [ ] Metrics updated correctly (check `get_metrics()`)
- [ ] No memory leaks (monitor process memory)
- [ ] Correlation IDs link all related events

---

### 2. Production Deployment

⚠️ **WARNING**: Only deploy to production after successful testnet verification

#### Pre-Production Checklist

- [ ] **All testnet scenarios passed**
- [ ] **Code review completed**
- [ ] **Security review completed**
- [ ] **Stakeholder approval obtained**

#### Environment Setup
```bash
# Set production environment
export TRADING_ENV=production
export BINANCE_API_KEY="your_production_key"
export BINANCE_API_SECRET="your_production_secret"
```

#### Final Configuration Validation
```bash
# Validate with strict mode
python scripts/validate_liquidation_config.py --env=production --strict

# Expected output:
# ✓ Valid: True
# ✓ Ready: True
# ✅ Configuration validated successfully
```

#### Security Verification
```bash
# Verify emergency liquidation enabled
python -c "from src.execution.liquidation_config import LiquidationConfig; \
           config = LiquidationConfig(); \
           assert config.emergency_liquidation == True, 'Emergency liquidation must be enabled'; \
           print('✓ Security check passed')"
```

#### Deployment with Monitoring
```bash
# Start trading bot with enhanced logging
python src/main.py --enable-liquidation --log-level=INFO

# Monitor in separate terminals:
# Terminal 1: Audit logs
tail -f logs/audit.jsonl | jq 'select(.event_type | contains("LIQUIDATION"))'

# Terminal 2: Application logs
tail -f logs/trading.log | grep -i liquidation

# Terminal 3: System metrics
watch -n 5 'ps aux | grep python | grep -v grep'
```

#### Smoke Test (Non-Disruptive)
```bash
# Check liquidation manager initialized
python -c "from src.main import TradingBot; \
           bot = TradingBot(); \
           bot.initialize(); \
           assert bot.liquidation_manager is not None; \
           print('✓ Liquidation manager initialized')"

# Check configuration loaded
python -c "from src.main import TradingBot; \
           bot = TradingBot(); \
           bot.initialize(); \
           config = bot.liquidation_manager.config; \
           print(f'Config: emergency={config.emergency_liquidation}, timeout={config.timeout_seconds}s')"
```

---

## Post-Deployment

### Verification Steps

- [ ] **Liquidation manager initialized successfully**
  - No initialization errors in logs
  - Component shows as active in bot status

- [ ] **Metrics collection working**
  ```bash
  python -c "from src.main import TradingBot; \
             bot = TradingBot(); \
             bot.initialize(); \
             metrics = bot.liquidation_manager.get_metrics(); \
             print(metrics)"
  ```
  - Metrics returned successfully
  - All fields present and valid

- [ ] **Audit logs being written**
  ```bash
  # Check audit log file exists and is recent
  ls -lh logs/audit.jsonl
  # File should be recent (within deployment time)
  ```

- [ ] **No CRITICAL warnings in logs**
  ```bash
  grep -i critical logs/trading.log
  # Should return empty or only expected warnings
  ```

- [ ] **Test shutdown on testnet** (if possible)
  - Execute controlled shutdown on testnet environment
  - Verify positions closed correctly
  - Verify orders cancelled correctly

- [ ] **Verify positions closed** (testnet only)
  - Check exchange UI for open positions
  - All positions should be closed

- [ ] **Verify orders cancelled** (testnet only)
  - Check exchange UI for pending orders
  - All orders should be cancelled

### Monitoring Setup

- [ ] **Alert on execution_time > 4s**
  - Threshold: 80% of default 5s timeout
  - Action: Investigate latency, consider timeout increase

- [ ] **Alert on IN_PROGRESS state > 5s**
  - Indicates potential hung state
  - Action: Check logs, verify timeout enforcement

- [ ] **Alert on FAILED state**
  - Any liquidation failure requires investigation
  - Action: Review error logs, check API connectivity

- [ ] **Alert on positions_failed > 0**
  - Indicates partial liquidation
  - Action: Manual position closure may be required

- [ ] **Dashboard for liquidation metrics**
  - Total executions
  - Average execution time
  - Success rate (COMPLETED vs PARTIAL/FAILED)
  - Position closure success rate

### Monitoring Commands

```bash
# Real-time liquidation events
tail -f logs/audit.jsonl | jq 'select(.event_type | contains("LIQUIDATION"))'

# Check execution metrics
python -c "from src.main import TradingBot; \
           bot = TradingBot(); \
           bot.initialize(); \
           import json; \
           print(json.dumps(bot.liquidation_manager.get_metrics(), indent=2))"

# Count liquidation events by type
jq -r '.event_type' logs/audit.jsonl | grep LIQUIDATION | sort | uniq -c

# Average execution time
jq -r 'select(.event_type == "LIQUIDATION_COMPLETE") | .details.duration_seconds' logs/audit.jsonl | \
  awk '{sum+=$1; count+=1} END {if(count>0) print "Avg:", sum/count, "seconds"}'
```

---

## Rollback Plan

If deployment issues occur:

### Step 1: Immediate Action
```bash
# Temporarily disable liquidation (emergency only)
# Edit config or set environment variable
export EMERGENCY_LIQUIDATION_DISABLED=true

# Restart trading bot
kill -SIGTERM $(pidof python)
python src/main.py
```

### Step 2: Investigate Issue
```bash
# Collect logs
tar -czf liquidation_logs_$(date +%Y%m%d_%H%M%S).tar.gz logs/

# Review recent liquidation events
grep -i liquidation logs/audit.jsonl | tail -50

# Check for errors
grep -i error logs/trading.log | grep -i liquidation
```

### Step 3: Fix Configuration
```bash
# Identify configuration issue
python scripts/validate_liquidation_config.py --env=production

# Fix configuration in code or config file
# Re-validate
python scripts/validate_liquidation_config.py --env=production --strict
```

### Step 4: Re-Deploy with Testing
```bash
# Test on testnet first
export TRADING_ENV=testnet
python src/main.py --enable-liquidation

# Execute test shutdown
# Verify success

# Deploy to production after verification
export TRADING_ENV=production
python src/main.py --enable-liquidation
```

### Rollback Decision Matrix

| Issue | Severity | Rollback? | Action |
|-------|----------|-----------|--------|
| Configuration validation fails | High | Yes | Fix config, re-validate |
| Liquidation timeout (but succeeds) | Medium | No | Increase timeout, monitor |
| Partial liquidation (some fail) | Medium | No | Investigate failures, may need manual intervention |
| Complete liquidation failure | High | Yes | Investigate, fix, re-test on testnet |
| Shutdown hangs | Critical | Yes | Kill process, investigate timeout enforcement |
| No audit logs | Medium | No | Fix logging, verify audit directory writable |

---

## Deployment Validation Report Template

```markdown
# Liquidation System Deployment Report

**Date**: 2026-01-02
**Environment**: Production
**Deployed By**: [Name]
**Version**: 1.0

## Pre-Deployment Checklist
- [x] Configuration validated
- [x] Dependencies verified
- [x] Tests passing (109/109)
- [x] Testnet verification complete

## Testnet Verification Results
- Scenario 1 (Normal): ✅ PASSED
- Scenario 2 (Disabled): ✅ PASSED
- Scenario 3 (Timeout): ✅ PASSED
- Scenario 4 (Partial): ✅ PASSED

## Production Deployment
- Deployment Time: 2026-01-02 10:00:00 UTC
- Configuration: emergency_liquidation=True, timeout=5s, retries=3
- Initial Status: ✅ Healthy

## Post-Deployment Verification
- [x] Manager initialized
- [x] Metrics collection working
- [x] Audit logs writing
- [x] No critical warnings
- [x] Monitoring alerts configured

## Issues Encountered
None / [Describe any issues]

## Rollback Executed
No / [If yes, describe rollback reason and outcome]

## Sign-Off
- Technical Lead: [Name] ✅
- Operations: [Name] ✅
- Date: 2026-01-02
```

---

**Document Version**: 1.0
**Next Review**: After first production liquidation event
**Related Docs**:
- Operations Guide: `claudedocs/liquidation_operations_guide.md`
- Troubleshooting: `claudedocs/liquidation_troubleshooting.md`
