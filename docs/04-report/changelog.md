# Changelog

All notable changes to this project are documented here.

## [2025-02-23] - Module Data Requirements Interface Complete

### Added
- **ModuleRequirements dataclass** (`src/models/module_requirements.py`)
  - Immutable declaration of module data dependencies (timeframes, min_candles)
  - frozen=True + MappingProxyType for true immutability
  - merge() static method for aggregating multiple requirements
  - empty() factory for modules with no special data needs

- **requirements property on strategy modules** (4 ABC classes)
  - EntryDeterminer.requirements (base.py)
  - ExitDeterminer.requirements (base.py)
  - StopLossDeterminer.requirements (base.py)
  - TakeProfitDeterminer.requirements (base.py)
  - Default: ModuleRequirements.empty() for zero-overhead adoption

- **Aggregation layer** (src/pricing/base.py)
  - StrategyModuleConfig.aggregated_requirements property
  - Merges all 4 determiners' requirements (union timeframes, max min_candles)

- **Integration with strategy system**
  - BaseStrategy.data_requirements property (default: empty())
  - ComposableStrategy.data_requirements override (aggregates from module_config)
  - TradingEngine per-interval backfill using min_candles

- **Module-specific implementations**
  - ICTEntryDeterminer.requirements: 3 timeframes, min_periods per timeframe
  - ICTExitDeterminer.requirements: 2 timeframes, min_candles validation

- **Comprehensive test coverage** (36 new tests)
  - test_module_requirements.py: 15 unit tests (creation, immutability, validation, merge)
  - test_requirements_integration.py: 21 integration tests (determiners, aggregation, strategies, builder)

### Changed
- **module_config_builder.py refactor**
  - Added _interval_to_minutes() utility for interval sorting
  - Builder functions now derive intervals from aggregated_requirements instead of hardcoding
  - _build_ict_config: intervals = sorted(agg.timeframes) if agg.timeframes else None
  - _build_sma_config: intervals = None (empty requirements inherited)
  - _build_always_signal_config: intervals = None (empty requirements inherited)

- **TradingEngine backfill logic** (initialize_strategy_with_backfill)
  - Per-interval backfill using strategy.data_requirements.min_candles
  - Falls back to default_limit if min_candles not specified for interval
  - Removed hardcoded global backfill_limit dependency

- **ComposableStrategy initialization**
  - Added buffer_size vs max(min_candles) validation warning
  - Alerts developers if buffer_size < max_needed (prevents data truncation)

### Fixed
- **Import layer compliance**
  - ModuleRequirements placed in src/models/ (shared type layer)
  - Respects import direction: entry/exit/pricing → models

- **Immutability guarantee**
  - MappingProxyType wrapping prevents min_candles mutations
  - Test: req.min_candles["5m"] = 9999 raises TypeError

- **Validation completeness**
  - __post_init__ validates min_candles keys are subset of timeframes
  - Prevents invalid requirement declarations

### Verified
- ✅ All existing tests pass (ICT, SMA, AlwaysSignal strategies)
- ✅ 36 new tests covering ModuleRequirements and integration
- ✅ Zero hot-path performance impact (init-time only)
- ✅ Backward compatible (property defaults eliminate breaking changes)
- ✅ Critic feedback fully addressed (5 critical/minor issues resolved)

### Metrics
- Total lines added: ~536
- New files: 3 (ModuleRequirements, 2 test files)
- Modified files: 10 (ABCs, strategies, builders, engine)
- Unchanged files: 6+ (SMA, AlwaysSignal, simple determiners)
- Test coverage: 36 new tests, 1015+ total passing
- Design match rate: 98% (one minor deviation noted and documented)

---

## [2024-12] - Strategy Abstraction Redesign Complete
(Previous PDCA cycle - see docs/04-report/strategy-abstraction-redesign-completion.md)
