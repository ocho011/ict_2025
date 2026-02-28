"""
Tests for DynamicAssembler — YAML-driven strategy assembly.

Tests:
1. Assembly with full modules spec
2. Legacy fallback when no modules
3. Default module substitution
4. Interval derivation from requirements
"""

import importlib
import pytest

from src.config.symbol_config import SymbolConfig
from src.pricing.base import StrategyModuleConfig
from src.strategies.dynamic_assembler import DynamicAssembler
from src.strategies.module_registry import ModuleRegistry


def _populate_registry():
    """Force re-registration of modules into current singleton."""
    import src.entry.sma_entry as m1
    import src.entry.always_entry as m2
    import src.pricing.stop_loss.percentage as m3
    import src.pricing.take_profit.risk_reward as m4
    import src.exit.base as m5

    for m in [m1, m2, m3, m4, m5]:
        importlib.reload(m)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry and re-populate before each test."""
    ModuleRegistry._instance = None
    _populate_registry()
    yield
    ModuleRegistry._instance = None


class TestDynamicAssemblerWithModules:
    """Tests for assembly with modules spec."""

    def test_assemble_with_full_spec(self):
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="mock_sma",
            modules={
                "entry": {"type": "sma_entry", "params": {}},
                "stop_loss": {"type": "percentage_sl", "params": {}},
                "take_profit": {"type": "rr_take_profit", "params": {}},
                "exit": {"type": "null_exit", "params": {}},
            },
        )
        assembler = DynamicAssembler()
        module_config, intervals, min_rr = assembler.assemble_for_symbol(config)

        assert isinstance(module_config, StrategyModuleConfig)
        assert module_config.entry_determiner is not None
        assert module_config.stop_loss_determiner is not None
        assert module_config.take_profit_determiner is not None
        assert module_config.exit_determiner is not None

    def test_assemble_partial_spec_uses_defaults(self):
        """When only entry is specified, others use defaults."""
        config = SymbolConfig(
            symbol="ETHUSDT",
            strategy="mock_sma",
            modules={
                "entry": {"type": "sma_entry", "params": {}},
            },
        )
        assembler = DynamicAssembler()
        module_config, intervals, min_rr = assembler.assemble_for_symbol(config)

        assert isinstance(module_config, StrategyModuleConfig)
        assert module_config.entry_determiner is not None
        assert module_config.stop_loss_determiner is not None
        assert module_config.take_profit_determiner is not None
        assert module_config.exit_determiner is not None

    def test_min_rr_ratio_from_tp_params(self):
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="mock_sma",
            modules={
                "entry": {"type": "sma_entry", "params": {}},
                "take_profit": {
                    "type": "rr_take_profit",
                    "params": {"risk_reward_ratio": 3.0},
                },
            },
        )
        assembler = DynamicAssembler()
        _, _, min_rr = assembler.assemble_for_symbol(config)
        assert min_rr == 3.0


class TestDynamicAssemblerLegacyFallback:
    """Tests for legacy fallback when no modules spec."""

    def test_empty_modules_triggers_fallback(self):
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="mock_sma",
            modules={},
        )
        assembler = DynamicAssembler()
        module_config, intervals, min_rr = assembler.assemble_for_symbol(config)

        assert isinstance(module_config, StrategyModuleConfig)

    def test_no_modules_field_triggers_fallback(self):
        config = SymbolConfig(
            symbol="BTCUSDT",
            strategy="mock_sma",
        )
        assembler = DynamicAssembler()
        module_config, intervals, min_rr = assembler.assemble_for_symbol(config)

        assert isinstance(module_config, StrategyModuleConfig)
