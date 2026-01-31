# ICT Strategy Tuning Design

**Date**: 2026-01-03
**Branch**: feature/ict-strategy-tuning
**Status**: Design Phase

---

## Executive Summary

**Problem**: ICT strategy generates 1-2 signals per week due to strict AND logic requiring all 5 conditions simultaneously.

**Goal**: Increase signal frequency to 5-20 signals per week while maintaining quality.

**Approach**: 3-Tier progressive tuning system with debug-first methodology.

---

## Current State Analysis

### Signal Generation Logic (src/strategies/ict_strategy.py:218, 270)

**LONG Entry (all 3 must be true)**:
```python
if recent_inducement and recent_displacement and (nearest_fvg or nearest_ob):
    return Signal(...)
```

**SHORT Entry (all 3 must be true)**:
```python
if recent_inducement and recent_displacement and (nearest_fvg or nearest_ob):
    return Signal(...)
```

### Current Parameters (configs/trading_config.ini)

```ini
swing_lookback = 5           # Conservative trend detection
displacement_ratio = 1.5     # Strict displacement threshold
fvg_min_gap_percent = 0.001  # Very strict (0.1% gap)
ob_min_strength = 1.5        # Conservative OB filtering
liquidity_tolerance = 0.001  # Very strict (0.1%)
use_killzones = false        # Testing mode (currently disabled)
```

### Bottleneck Analysis

Based on diagnostic document (2025-12-31_1057-1107_ict_strategy_log_analysis.md):

**5 Conditions Required**:
1. ✅ Trend (bullish/bearish) - Usually available
2. ✅ Premium/Discount zone - Usually available
3. ⚠️ **FVG or OB** - Moderately rare
4. ⚠️ **Inducement** - Moderately rare
5. ⚠️ **Displacement** - Moderately rare

**Simultaneous Occurrence**: Very rare → 0 signals in 10 minutes (expected behavior)

**Hypothesis**: Inducement + Displacement timing is the primary bottleneck.

---

## 3-Tier Tuning Strategy

### Tier 1: Debug Logging System (Priority: HIGH)

**Purpose**: Identify which conditions fail most frequently.

**Implementation**:

1. **Enhanced Condition Logging**
```python
# In ict_strategy.py generate_signal() method
condition_states = {
    "timestamp": candle.open_time,
    "trend": trend,
    "in_zone": is_in_discount(...) or is_in_premium(...),
    "fvg_present": bool(nearest_fvg),
    "ob_present": bool(nearest_ob),
    "inducement": recent_inducement,
    "displacement": recent_displacement,
    "signal_generated": False  # Updated if signal created
}

# Log at DEBUG level
logger.debug(f"ICT Conditions: {condition_states}")
```

2. **Condition Stats Accumulator**
```python
# Track condition success rates
self.condition_stats = {
    "total_checks": 0,
    "trend_ok": 0,
    "zone_ok": 0,
    "fvg_ob_ok": 0,
    "inducement_ok": 0,
    "displacement_ok": 0,
    "all_conditions_ok": 0
}
```

3. **Log Analysis Utility**
```bash
# New script: scripts/analyze_ict_conditions.py
# Parse logs and generate report showing:
# - Which condition fails most often
# - Time distribution of failures
# - Near-miss scenarios (4/5 conditions met)
```

**Expected Outcome**:
- Identify bottleneck condition(s)
- Data-driven parameter tuning decisions
- Baseline metrics for before/after comparison

**Deliverables**:
- Modified `src/strategies/ict_strategy.py` with enhanced logging
- New `scripts/analyze_ict_conditions.py` utility
- Sample condition report

---

### Tier 2: Parameter Tuning Profiles (Priority: HIGH)

**Purpose**: Create pre-tested parameter profiles for different signal frequencies.

**Approach**: Multi-profile configuration system.

**3 Configuration Profiles**:

#### Profile 1: Strict (Current Baseline)
```ini
# Expected: 1-2 signals/week
swing_lookback = 5
displacement_ratio = 1.5
fvg_min_gap_percent = 0.001
ob_min_strength = 1.5
liquidity_tolerance = 0.001
```

#### Profile 2: Balanced (Recommended)
```ini
# Target: 5-10 signals/week (2-3x increase)
swing_lookback = 7           # +2 (more swing detection)
displacement_ratio = 1.3     # -0.2 (more displacements detected)
fvg_min_gap_percent = 0.002  # 2x relaxed (0.2% gap)
ob_min_strength = 1.3        # -0.2 (more OBs qualify)
liquidity_tolerance = 0.002  # 2x relaxed (0.2%)
```

#### Profile 3: Relaxed (Testing Only)
```ini
# Target: 15-20 signals/week (10x increase)
swing_lookback = 10          # +5 (maximum swing detection)
displacement_ratio = 1.2     # -0.3 (easier displacement)
fvg_min_gap_percent = 0.005  # 5x relaxed (0.5% gap)
ob_min_strength = 1.2        # -0.3 (more OBs)
liquidity_tolerance = 0.005  # 5x relaxed (0.5%)
```

**Parameter Selection Rationale**:

| Parameter | Strict | Balanced | Relaxed | Reasoning |
|-----------|--------|----------|---------|-----------|
| swing_lookback | 5 | 7 | 10 | More lookback = more swings detected |
| displacement_ratio | 1.5 | 1.3 | 1.2 | Lower threshold = more displacements |
| fvg_min_gap_percent | 0.001 | 0.002 | 0.005 | Wider gap = more FVGs |
| ob_min_strength | 1.5 | 1.3 | 1.2 | Lower strength = more OBs |
| liquidity_tolerance | 0.001 | 0.002 | 0.005 | Wider tolerance = more liquidity levels |

**Implementation**:

1. **Profile Configuration System**
```python
# New file: src/config/ict_profiles.py
class ICTProfile(Enum):
    STRICT = "strict"
    BALANCED = "balanced"
    RELAXED = "relaxed"

def load_profile(profile: ICTProfile) -> Dict[str, float]:
    """Load parameter profile."""
    profiles = {
        ICTProfile.STRICT: {...},
        ICTProfile.BALANCED: {...},
        ICTProfile.RELAXED: {...}
    }
    return profiles[profile]
```

2. **Config File Integration**
```ini
# In trading_config.ini - add new parameter
[ict_strategy]
# Active profile selection
active_profile = balanced   # Options: strict, balanced, relaxed

# Profile-specific parameters (auto-loaded from active_profile)
# ... existing parameters ...
```

3. **Runtime Profile Switching**
```python
# Support dynamic profile switching for testing
strategy.switch_profile(ICTProfile.BALANCED)
```

**Validation**:
- Unit tests for each profile
- Backtesting on historical data
- Signal frequency metrics

**Deliverables**:
- New `src/config/ict_profiles.py` module
- Modified `configs/trading_config.ini` with profile selection
- Profile validation tests
- Backtesting results comparison

---

### Tier 3: Adaptive Logic System (Priority: LOW - Optional)

**Purpose**: Dynamic condition adjustment based on market regime.

**Status**: Deferred - only implement if Tier 1 + Tier 2 insufficient.

**Approaches** (from diagnostic document):

#### Option A: Weighted Scoring System
```python
# Replace strict AND with score-based threshold
score = 0
score += 2 if trend else 0           # Trend most important
score += 2 if in_zone else 0         # Zone second most important
score += 1 if fvg_or_ob else 0       # Entry structure
score += 1 if inducement else 0      # Confirmation
score += 1 if displacement else 0    # Confirmation

# Signal if score >= 5 (flexible threshold)
if score >= 5:
    return Signal(...)
```

#### Option B: Conditional OR Logic
```python
# Core conditions (required)
core_conditions = trend and in_zone and fvg_or_ob

# Confirmation conditions (at least 1 of 2)
confirmation = inducement or displacement

if core_conditions and confirmation:
    return Signal(...)
```

#### Option C: Time-of-Day Adaptation
```python
# Relax conditions during kill zones
if is_killzone_active():
    required_score = 4  # Lower threshold
else:
    required_score = 5  # Standard threshold
```

**Decision Criteria for Tier 3**:
- Only implement if Tier 2 (Balanced profile) generates < 5 signals/week
- Requires extensive backtesting and paper trading validation
- Higher risk of false signals

---

## Implementation Plan

### Phase 1: Tier 1 Implementation (Debug Logging)

**Tasks**:
1. Add enhanced condition logging to `ict_strategy.py`
2. Implement condition stats accumulator
3. Create log analysis utility script
4. Run with live data for 24-48 hours
5. Generate condition bottleneck report

**Time Estimate**: 2-3 hours

### Phase 2: Tier 2 Implementation (Parameter Profiles)

**Tasks**:
1. Create `ict_profiles.py` module with 3 profiles
2. Modify config loading to support profiles
3. Update `ict_strategy.py` to use profile parameters
4. Create profile validation tests
5. Backtest each profile and document results
6. Select recommended profile (likely Balanced)

**Time Estimate**: 3-4 hours

### Phase 3: Testing & Validation

**Tasks**:
1. Unit tests for new logging functionality
2. Unit tests for profile system
3. Integration tests with real market data
4. 24-hour paper trading with Balanced profile
5. Compare signal frequency: Strict vs Balanced vs Relaxed

**Time Estimate**: 2-3 hours

### Phase 4: Documentation

**Tasks**:
1. Update strategy documentation
2. Create operator guide for profile selection
3. Document tuning results and recommendations
4. Create troubleshooting guide

**Time Estimate**: 1-2 hours

---

## Success Metrics

### Quantitative Metrics

| Metric | Strict (Baseline) | Balanced (Target) | Relaxed (Max) |
|--------|-------------------|-------------------|---------------|
| Signals per week | 1-2 | 5-10 | 15-20 |
| Win rate | ~70% | ≥60% | ≥50% |
| Avg R:R | 2.5:1 | ≥2:1 | ≥1.5:1 |

### Qualitative Metrics

- ✅ Condition bottleneck identified via logging
- ✅ Profile selection documented and tested
- ✅ Signal quality maintained (no excessive false signals)
- ✅ Operator can easily switch profiles

---

## Risk Mitigation

### Risk 1: Over-Optimization
**Mitigation**: Use forward testing (paper trading) for 1 week before live deployment.

### Risk 2: False Signal Increase
**Mitigation**: Implement signal quality scoring system, monitor win rate closely.

### Risk 3: Parameter Sensitivity
**Mitigation**: Small incremental changes (Balanced profile), avoid aggressive jumps.

### Risk 4: Market Regime Shift
**Mitigation**: Maintain multiple profiles for different market conditions.

---

## Rollback Plan

If tuned strategy underperforms:

1. **Immediate**: Revert to Strict profile (1-line config change)
2. **Short-term**: Analyze logs to identify failure mode
3. **Long-term**: Create hybrid profile or adjust Balanced parameters

---

## Decision Points

**After Tier 1 (Debug Logging)**:
- If inducement/displacement are bottlenecks → Proceed to Tier 2
- If FVG/OB are bottlenecks → Adjust those parameters first

**After Tier 2 (Parameter Profiles)**:
- If Balanced profile meets 5-10 signals/week target → Production ready
- If < 5 signals/week → Consider Relaxed profile or Tier 3
- If > 20 signals/week → Tighten Balanced parameters

**Tier 3 Decision**:
- Only proceed if Tier 2 insufficient AND backtesting shows promise
- Requires business approval due to logic changes

---

## Appendix: File Changes Summary

### New Files
- `src/config/ict_profiles.py` - Profile management system
- `scripts/analyze_ict_conditions.py` - Log analysis utility
- `tests/test_ict_profiles.py` - Profile validation tests

### Modified Files
- `src/strategies/ict_strategy.py` - Enhanced logging + profile support
- `configs/trading_config.ini` - Profile selection parameter
- Documentation files

---

**Document Version**: 1.0
**Next Steps**: Implement Tier 1 (Debug Logging)
