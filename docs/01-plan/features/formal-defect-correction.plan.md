# PDCA Plan: Formal Defect Correction

> **Feature Name:** `formal-defect-correction`
> **Status:** Plan Phase (Plan)
> **Date:** 2026-03-07
> **Priority:** Medium

## 🎯 Objectives
프로젝트 내의 형식적인 코드 품질 결함(미사용 임포트, 스타일 위반, 불명확한 타입 힌트)을 포괄적으로 정리하여 코드 가독성과 유지보수성을 향상시킴.

## 📋 Task List

### Phase 1: Main Module Cleanup (Priority 1)
- [ ] **[T1.1] Remove Unused Imports in `src/main.py`**
    - Remove `platform`, `os`, and verify `datetime` usage.
- [ ] **[T1.2] Optimize Import Order in `src/main.py`**
    - Align with PEP 8 (Standard -> Third-party -> Local).
    - Consolidate imports moved after `sys.path` manipulation.

### Phase 2: Detectors Refactoring (Priority 2)
- [ ] **[T2.1] Replace Wildcard Imports in Detectors**
    - Files: `ict_market_structure.py`, `ict_fvg.py`, `ict_order_block.py`, `ict_killzones.py`, `ict_liquidity.py`.
    - Replace `from ... import *` with explicit class/function imports.
- [ ] **[T2.2] Improve Type Hints in `BaseDetector`**
    - Replace `Any` return type in `calculate()` with a more specific type if possible.

### Phase 3: Verification (Priority 3)
- [ ] **[T3.1] Run Static Analysis**
    - Verify no regression in functionality.
    - Check if any other obvious style issues exist.

## 📈 Success Metrics
- 미사용 임포트 0개 (핵심 모듈 기준)
- 와일드카드 임포트 제거 (detectors 모듈 기준)
- 모든 수정 파일의 린트 체크 통과

## 🔗 Dependencies
- None
