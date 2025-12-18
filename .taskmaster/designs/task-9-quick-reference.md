# Task 9: Configuration Management - Quick Reference

**Status**: 90% Complete | **Priority**: Medium | **Complexity**: 4/10

## TL;DR

✅ **Existing implementation is EXCELLENT** - already exceeds task requirements
⚠️ **Remaining work**: Complete validation rules for Subtask 9.4 (~2-3 hours)

---

## Current Implementation Status

### ✅ Completed (Subtasks 9.1-9.3)

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| APIConfig dataclass | `src/utils/config.py:13-24` | ✅ DONE | With validation |
| TradingConfig dataclass | `src/utils/config.py:26-46` | ✅ DONE | With validation |
| LoggingConfig dataclass | `src/utils/config.py:48-61` | ✅ BONUS | Not in spec |
| ConfigManager class | `src/utils/config.py:63-239` | ✅ DONE | Full implementation |
| Environment override | `src/utils/config.py:91-104` | ✅ DONE | Priority system |
| INI file parsing | `src/utils/config.py:107-183` | ✅ DONE | With env selection |

### ⚠️ Partial (Subtask 9.4 - Validation)

| Validation Rule | Current | Required | Status |
|----------------|---------|----------|--------|
| Leverage (1-125) | ✅ Line 39-40 | ✅ | DONE |
| Risk (0-10%) | ✅ Line 42-45 | ✅ | DONE |
| Take profit > 0 | ❌ | ✅ | TODO |
| Stop loss (0-50%) | ❌ | ✅ | TODO |
| Symbol format | ❌ | ✅ | TODO |
| Intervals format | ❌ | ✅ | TODO |
| Error accumulation | ❌ | ✅ | TODO |
| Validation logging | ❌ | ✅ | TODO |
| Return bool | ❌ (returns None) | ✅ | TODO |

---

## What Needs to Be Done

### 1. Add Missing Validation Rules

**File**: `src/utils/config.py`, TradingConfig class

**Add to `__post_init__` (after line 45)**:

```python
# Validate take_profit_ratio
if self.take_profit_ratio <= 0:
    raise ConfigurationError(
        f"Take profit ratio must be positive, got {self.take_profit_ratio}"
    )

# Validate stop_loss_percent
if self.stop_loss_percent <= 0 or self.stop_loss_percent > 0.5:
    raise ConfigurationError(
        f"Stop loss percent must be 0-50%, got {self.stop_loss_percent}"
    )

# Validate symbol format
if not self.symbol or not self.symbol.endswith('USDT'):
    raise ConfigurationError(
        f"Invalid symbol format: {self.symbol}. Must end with 'USDT'"
    )

# Validate intervals
valid_intervals = {'1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h',
                   '6h', '8h', '12h', '1d', '3d', '1w'}
for interval in self.intervals:
    if interval not in valid_intervals:
        raise ConfigurationError(
            f"Invalid interval: {interval}. "
            f"Must be one of {sorted(valid_intervals)}"
        )
```

### 2. Enhance validate() Method

**File**: `src/utils/config.py`, ConfigManager class

**Replace validate() method (lines 184-198)**:

```python
def validate(self) -> bool:
    """
    Validate all configurations

    Returns:
        bool: True if all validations pass, False otherwise

    Note: All validation errors are logged before returning
    """
    import logging
    logger = logging.getLogger(__name__)
    errors = []

    # API and Trading config validation already done in __post_init__

    # Cross-config validation warnings
    if self._trading_config.leverage > 1 and self._api_config.is_testnet:
        logger.warning(
            f"Using {self._trading_config.leverage}x leverage in testnet mode"
        )

    # Log environment mode
    if self._api_config.is_testnet:
        logger.info("⚠️  Running in TESTNET mode")
    else:
        logger.warning("⚠️  Running in PRODUCTION mode with real funds!")

    # Log accumulated errors
    for error in errors:
        logger.error(error)

    return len(errors) == 0
```

### 3. Create Comprehensive Tests

**File**: `tests/test_config_validation.py` (NEW)

```python
import pytest
from src.utils.config import TradingConfig
from src.core.exceptions import ConfigurationError


class TestTradingConfigValidation:
    """Test all validation rules"""

    def test_valid_config(self):
        """Valid configuration should not raise"""
        config = TradingConfig(
            symbol="BTCUSDT", intervals=["1m"], strategy="test",
            leverage=10, max_risk_per_trade=0.01,
            take_profit_ratio=2.0, stop_loss_percent=0.02
        )
        assert config.leverage == 10

    def test_invalid_take_profit_raises(self):
        """Zero or negative TP should raise"""
        with pytest.raises(ConfigurationError, match="Take profit ratio"):
            TradingConfig(
                symbol="BTCUSDT", intervals=["1m"], strategy="test",
                leverage=1, max_risk_per_trade=0.01,
                take_profit_ratio=0.0, stop_loss_percent=0.02
            )

    def test_invalid_stop_loss_raises(self):
        """SL out of range should raise"""
        with pytest.raises(ConfigurationError, match="Stop loss percent"):
            TradingConfig(
                symbol="BTCUSDT", intervals=["1m"], strategy="test",
                leverage=1, max_risk_per_trade=0.01,
                take_profit_ratio=2.0, stop_loss_percent=0.6
            )

    def test_invalid_symbol_raises(self):
        """Symbol not ending with USDT should raise"""
        with pytest.raises(ConfigurationError, match="Invalid symbol"):
            TradingConfig(
                symbol="BTCBUSD", intervals=["1m"], strategy="test",
                leverage=1, max_risk_per_trade=0.01,
                take_profit_ratio=2.0, stop_loss_percent=0.02
            )

    def test_invalid_interval_raises(self):
        """Invalid interval should raise"""
        with pytest.raises(ConfigurationError, match="Invalid interval"):
            TradingConfig(
                symbol="BTCUSDT", intervals=["1x"], strategy="test",
                leverage=1, max_risk_per_trade=0.01,
                take_profit_ratio=2.0, stop_loss_percent=0.02
            )
```

### 4. Update Documentation

**Add to class docstring**:

```python
@dataclass
class TradingConfig:
    """
    Trading strategy configuration

    Validation Rules:
        - leverage: 1-125 (Binance futures limits)
        - max_risk_per_trade: 0 < value ≤ 0.1 (0-10%)
        - take_profit_ratio: must be positive
        - stop_loss_percent: 0 < value ≤ 0.5 (0-50%)
        - symbol: must end with 'USDT'
        - intervals: must be valid Binance interval formats
    """
```

---

## Implementation Checklist

- [ ] Add take_profit_ratio > 0 validation to TradingConfig
- [ ] Add stop_loss_percent (0-50%) validation to TradingConfig
- [ ] Add symbol format validation (ends with USDT) to TradingConfig
- [ ] Add intervals format validation to TradingConfig
- [ ] Enhance ConfigManager.validate() with error accumulation
- [ ] Make validate() return bool instead of None
- [ ] Add validation logging to validate() method
- [ ] Update TradingConfig docstring with validation rules
- [ ] Create tests/test_config_validation.py with all test cases
- [ ] Run tests: `pytest tests/test_config*.py -v --cov=src.utils.config`
- [ ] Verify 100% test coverage
- [ ] Mark Task 9 as DONE

---

## Validation Rules Reference

| Parameter | Rule | Example Valid | Example Invalid |
|-----------|------|---------------|-----------------|
| leverage | 1-125 | 10, 20, 125 | 0, 126, -5 |
| max_risk_per_trade | 0 < x ≤ 0.1 | 0.01, 0.05, 0.1 | 0, 0.11, -0.01 |
| take_profit_ratio | > 0 | 1.5, 2.0, 3.0 | 0, -1.0 |
| stop_loss_percent | 0 < x ≤ 0.5 | 0.01, 0.02, 0.5 | 0, 0.51, -0.01 |
| symbol | ends with 'USDT' | BTCUSDT, ETHUSDT | BTCBUSD, btcusdt |
| intervals | valid Binance | 1m, 5m, 1h, 4h | 1x, 2min, 3hr |

**Valid Intervals**: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w`

---

## Testing Commands

```bash
# Run all config tests
pytest tests/test_config*.py -v

# Check coverage
pytest tests/test_config*.py --cov=src.utils.config --cov-report=term-missing

# Type checking
mypy src/utils/config.py --strict

# Full test suite
pytest tests/ -v --cov=src --cov-report=html
```

---

## Configuration Files

### api_keys.ini
```ini
[binance]
use_testnet = true

[binance.testnet]
api_key = your_testnet_key
api_secret = your_testnet_secret

[binance.mainnet]
api_key = your_mainnet_key
api_secret = your_mainnet_secret
```

### trading_config.ini
```ini
[trading]
symbol = BTCUSDT
intervals = 1m,5m,15m
strategy = MockStrategy
leverage = 1
max_risk_per_trade = 0.01
take_profit_ratio = 2.0
stop_loss_percent = 0.02

[logging]
log_level = INFO
log_dir = logs
```

---

## Environment Variables

```bash
# Override API credentials
export BINANCE_API_KEY="your_key"
export BINANCE_API_SECRET="your_secret"

# Override environment selection
export BINANCE_USE_TESTNET="true"  # or "false" for mainnet
```

**Priority**: ENV vars → INI file → defaults

---

## Common Issues & Solutions

### Issue: "API configuration not found"
**Solution**: Copy `configs/api_keys.ini.example` to `configs/api_keys.ini` and fill in credentials

### Issue: "Invalid API key in [binance.testnet]"
**Solution**: Replace placeholder `your_testnet_api_key_here` with actual API key

### Issue: "Leverage must be between 1-125"
**Solution**: Set leverage value between 1 and 125 in trading_config.ini

### Issue: ConfigurationError on startup
**Solution**: Check validation rules above and ensure all values are within valid ranges

---

## Related Documents

- **Full Design**: `claudedocs/task-9-configuration-design.md` (45 pages)
- **Architecture Diagrams**: `claudedocs/task-9-architecture-diagram.md`
- **Memory**: Serena memory `task-9-config-design-analysis`

---

**Estimated Time to Complete**: 2-3 hours
**Quality**: Production-ready foundation, minor enhancements needed
**Status**: Ready for implementation

---

Last Updated: 2025-12-18
