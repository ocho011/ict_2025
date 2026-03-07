# PDCA Design: Formal Defect Correction

> **Feature Name:** `formal-defect-correction`
> **Status:** Design Phase (Design)
> **Reference Plan:** `docs/01-plan/features/formal-defect-correction.plan.md`
> **Date:** 2026-03-07

## 🏗️ Architecture & Component Changes

### 1. `src/main.py` Changes
- **Standard Library Imports:** 
    - Keep: `asyncio`, `logging`, `signal`, `sys`, `datetime`, `pathlib`
    - Remove: `os`, `platform`
- **Import Reordering:**
    - Move `from enum import Enum, auto` to the top block.
    - Ensure all `src.*` imports are grouped together after standard/third-party libs.

### 2. `src/detectors/` Module Refactoring
- **Wildcard Removal Strategy:**
    - `ict_market_structure.py`: `from ...detectors.market_structure import MarketStructureDetector, ...`
    - `ict_fvg.py`: `from ...detectors.fvg import FVGDetector, ...`
    - (Similar for OrderBlock, Killzones, Liquidity)
- **Rationale:** Wildcard imports hide dependencies and make code navigation difficult.

### 3. `src/detectors/base.py` Type Hinting
- **Change:** `def calculate(self, data: pd.DataFrame) -> Any` -> `-> Dict[str, Any]` (or similar based on actual implementation of sub-classes).

## 🛠️ Implementation Details

### File: `src/main.py`
```python
import asyncio
import logging
import signal
import sys
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Path manipulation if necessary
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.audit_logger import AuditLogger
...
```

### File: `src/detectors/ict_market_structure.py`
```python
# Before
from src.strategies.modules.detectors.market_structure import *  # noqa: F401,F403

# After
from src.strategies.modules.detectors.market_structure import MarketStructureDetector
```

## ✅ Verification Plan
1. **Manual Inspection:** Ensure no runtime errors during `TradingBot` initialization.
2. **Lint Check:** Run `flake8` (if possible) or manual check for unused imports.
3. **Smoke Test:** Start the bot to ensure it reaches `RUNNING` state.
