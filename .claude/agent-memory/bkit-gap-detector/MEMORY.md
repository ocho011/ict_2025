# Gap Detector Memory

## Project: ict_2025 (Real-time Trading System)

### Key Architecture Facts
- Python async trading system with Binance integration
- Uses ComposableStrategy pattern with 4 module types: entry, stop_loss, take_profit, exit
- Single config path: YAML only (base.yaml + api_keys.ini for secrets)
- Hot path compliance: dataclass in trading loop, Pydantic only in Cold Path
- Singleton patterns: ModuleRegistry, AuditLogger

### Analysis History
- **2026-03-03**: trailing-stop-logging-optimization -- 96% match rate
  - Report: `docs/03-analysis/features/trailing-stop-logging-optimization.analysis.md`
  - 5 gaps (G1-G5): slots=True missing, __all__ export, DI pattern diff, missing TRADE_CLOSED test, test path
  - All 9 PositionMetrics fields match; all 9 ratchet event data fields match
  - POSITION_CLOSED and TRADE_CLOSED enriched with 8 metrics fields each
  - Hot path < 100ns/candle verified; backward compat preserved
  - 9/10 design test cases implemented; missing async TRADE_CLOSED test (G4 MEDIUM)
- **2026-03-02**: logging-cost-tracking -- 97% match rate
  - Report: `docs/03-analysis/features/logging-cost-tracking.analysis.md`
  - All 9 gaps (G1-G9) resolved; 20/20 POSITION_CLOSED schema fields match
  - Funding fee sign convention: `total_funding -= funding_fee` (negate Binance sign)
  - Net PnL: `gross - commission - total_funding` verified correct
  - 26 tests in `tests/execution/test_logging_cost_tracking.py`
  - Only minor gaps: unused enum comments (G7 LOW), BALANCE_SNAPSHOT periodic (Nice-to-Have)
- **2026-03-01**: dynamic-strategy-config-interface -- 94% match rate
  - Report: `docs/03-analysis/features/dynamic-strategy-config-interface.analysis.md`
  - Key gap: TradingEngine missing `position_closer` injection into StrategyHotReloader (line ~218)
  - 9 modules decorated, all tests passing, backward compat preserved
- **2026-03-01**: ini-to-yaml-migration -- 96% match rate
  - Report: `docs/03-analysis/features/ini-to-yaml-migration.analysis.md`
  - All functional requirements matched; only 3 stale docstrings referencing INI remain
  - 1196 tests passed, trading_config.ini fully removed, ConfigParser isolated to api_keys only

### Key File Paths
- Design docs: `docs/02-design/features/`
- Analysis reports: `docs/03-analysis/features/`
- Module registry: `src/strategies/module_registry.py`
- Dynamic assembler: `src/strategies/dynamic_assembler.py`
- Trading engine: `src/core/trading_engine.py`
- Symbol config: `src/config/symbol_config.py`
