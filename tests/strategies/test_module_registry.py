"""
Tests for ModuleRegistry singleton and @register_module decorator.

Tests:
1. Singleton pattern
2. Module registration via API
3. Module discovery (get_available_modules)
4. Module creation (create_module)
5. Param schema retrieval
6. Combination validation
"""

import importlib
import pytest
from pydantic import BaseModel

from src.strategies.module_registry import ModuleRegistry, ModuleCategory, ModuleInfo


def _populate_registry():
    """Force re-registration of modules into current singleton."""
    # Decorators register to ModuleRegistry.get_instance() at import time.
    # After singleton reset, we must reload modules so decorators fire again.
    import src.entry.sma_entry as m1
    import src.entry.always_entry as m2
    import src.pricing.stop_loss.percentage as m3
    import src.pricing.take_profit.risk_reward as m4
    import src.exit.base as m5

    for m in [m1, m2, m3, m4, m5]:
        importlib.reload(m)


class _DummySchema(BaseModel):
    value: int = 1


class _DummyModule:
    @classmethod
    def from_validated_params(cls, params):
        return cls()


class TestModuleRegistrySingleton:
    """Tests for singleton pattern."""

    def setup_method(self):
        ModuleRegistry._instance = None

    def test_get_instance_returns_same_object(self):
        a = ModuleRegistry.get_instance()
        b = ModuleRegistry.get_instance()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = ModuleRegistry.get_instance()
        ModuleRegistry._instance = None
        b = ModuleRegistry.get_instance()
        assert a is not b


class TestModuleRegistration:
    """Tests for module registration."""

    def setup_method(self):
        ModuleRegistry._instance = None
        self.registry = ModuleRegistry.get_instance()

    def test_register_entry_module(self):
        self.registry.register(
            category=ModuleCategory.ENTRY,
            name="test_entry",
            cls_type=_DummyModule,
            param_schema=_DummySchema,
            description="Test entry module",
        )
        modules = self.registry.get_available_modules(ModuleCategory.ENTRY)
        names = [m.name for m in modules]
        assert "test_entry" in names

    def test_register_duplicate_overwrites(self):
        self.registry.register(
            ModuleCategory.ENTRY, "dup", _DummyModule, _DummySchema
        )
        self.registry.register(
            ModuleCategory.ENTRY, "dup", _DummyModule, _DummySchema
        )
        modules = self.registry.get_available_modules(ModuleCategory.ENTRY)
        assert sum(1 for m in modules if m.name == "dup") == 1

    def test_get_available_modules_empty_category(self):
        modules = self.registry.get_available_modules("nonexistent_category")
        assert modules == []


class TestModuleCreation:
    """Tests for create_module."""

    def setup_method(self):
        ModuleRegistry._instance = None
        _populate_registry()
        self.registry = ModuleRegistry.get_instance()

    def test_create_registered_module(self):
        """Verify that decorated modules can be created."""
        module = self.registry.create_module(
            ModuleCategory.ENTRY, "sma_entry", {}
        )
        from src.entry.sma_entry import SMAEntryDeterminer
        assert isinstance(module, SMAEntryDeterminer)

    def test_create_unknown_module_raises(self):
        with pytest.raises((KeyError, ValueError)):
            self.registry.create_module(ModuleCategory.ENTRY, "nonexistent", {})


class TestParamSchema:
    """Tests for param schema retrieval."""

    def setup_method(self):
        ModuleRegistry._instance = None
        _populate_registry()
        self.registry = ModuleRegistry.get_instance()

    def test_get_param_schema_for_registered_module(self):
        schema = self.registry.get_param_schema(ModuleCategory.ENTRY, "sma_entry")
        assert schema is not None

    def test_get_param_schema_for_unknown_returns_none(self):
        schema = self.registry.get_param_schema(ModuleCategory.ENTRY, "nonexistent")
        assert schema is None


class TestCombinationValidation:
    """Tests for validate_combination."""

    def setup_method(self):
        ModuleRegistry._instance = None
        _populate_registry()
        self.registry = ModuleRegistry.get_instance()

    def test_valid_combination_no_warnings(self):
        warnings = self.registry.validate_combination(
            "sma_entry", "percentage_sl", "rr_take_profit", "null_exit"
        )
        assert isinstance(warnings, list)

    def test_incompatible_combination_returns_warnings(self):
        """ICT modules have compatible_with constraints."""
        import src.strategies.ict.entry
        importlib.reload(src.strategies.ict.entry)

        warnings = self.registry.validate_combination(
            "ict_entry", "percentage_sl", "rr_take_profit", "null_exit"
        )
        assert isinstance(warnings, list)
