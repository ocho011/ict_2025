# Gap Detector Memory

## Project: ict_2025 (Real-time Trading System)

### Key Architecture Facts
- Python async trading system with Binance integration
- Uses ComposableStrategy pattern with 4 module types: entry, stop_loss, take_profit, exit
- Two config paths: legacy INI (flat) and hierarchical YAML (per-symbol)
- Hot path compliance: dataclass in trading loop, Pydantic only in Cold Path
- Singleton patterns: ModuleRegistry, AuditLogger

### Analysis History
- **2026-03-01**: dynamic-strategy-config-interface -- 94% match rate
  - Report: `docs/03-analysis/features/dynamic-strategy-config-interface.analysis.md`
  - Key gap: TradingEngine missing `position_closer` injection into StrategyHotReloader (line ~218)
  - 9 modules decorated, all tests passing, backward compat preserved

### Key File Paths
- Design docs: `docs/02-design/features/`
- Analysis reports: `docs/03-analysis/features/`
- Module registry: `src/strategies/module_registry.py`
- Dynamic assembler: `src/strategies/dynamic_assembler.py`
- Trading engine: `src/core/trading_engine.py`
- Symbol config: `src/config/symbol_config.py`
