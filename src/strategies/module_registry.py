"""
Module Registry — Singleton registry for strategy module discovery and creation.

Provides:
- ModuleCategory: Category constants (entry, stop_loss, take_profit, exit)
- ModuleInfo: Registered module metadata
- ModuleRegistry: Singleton for module registration, discovery, and instantiation

Design Principles:
- Registration happens at import time via @register_module decorator (single-threaded)
- Queries are read-only dict lookups (thread-safe)
- Pydantic validation only in create_module() — Cold Path only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel


class ModuleCategory:
    """Module category constants."""
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    EXIT = "exit"

    ALL = [ENTRY, STOP_LOSS, TAKE_PROFIT, EXIT]


@dataclass(frozen=True)
class ModuleInfo:
    """Registered module metadata."""
    name: str
    category: str
    cls: Type
    param_schema: Type[BaseModel]
    description: str = ""
    compatible_with: Dict[str, List[str]] = field(default_factory=dict)


class ModuleRegistry:
    """
    Singleton module registry.

    Modules self-register via @register_module decorator at import time.
    UI queries available modules, schemas, and creates instances.

    Thread Safety:
    - Registration: import-time only (single-threaded)
    - Queries: read-only dict lookups (safe)
    """
    _instance: Optional[ModuleRegistry] = None

    def __init__(self):
        self._modules: Dict[str, Dict[str, ModuleInfo]] = {
            cat: {} for cat in ModuleCategory.ALL
        }

    @classmethod
    def get_instance(cls) -> ModuleRegistry:
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing."""
        cls._instance = None

    def register(
        self,
        category: str,
        name: str,
        cls_type: Type,
        param_schema: Type[BaseModel],
        description: str = "",
        compatible_with: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Register a module. Overwrites if duplicate."""
        if category not in ModuleCategory.ALL:
            raise ValueError(
                f"Invalid category: {category}. Must be one of {ModuleCategory.ALL}"
            )
        info = ModuleInfo(
            name=name,
            category=category,
            cls=cls_type,
            param_schema=param_schema,
            description=description,
            compatible_with=compatible_with or {},
        )
        self._modules[category][name] = info

    def get_available_modules(self, category: str) -> List[ModuleInfo]:
        """List available modules for a category."""
        return list(self._modules.get(category, {}).values())

    def get_module_info(self, category: str, name: str) -> Optional[ModuleInfo]:
        """Get module info by category and name."""
        return self._modules.get(category, {}).get(name)

    def get_param_schema(self, category: str, name: str) -> Optional[Type[BaseModel]]:
        """Get Pydantic param schema for a module."""
        info = self.get_module_info(category, name)
        return info.param_schema if info else None

    def create_module(self, category: str, name: str, params: dict) -> Any:
        """
        Create module instance with Pydantic-validated params.

        Cold Path only — called during strategy assembly, not in hot trading loop.

        Args:
            category: Module category
            name: Module name
            params: Parameter dict (validated by Pydantic schema)

        Returns:
            Module instance (EntryDeterminer, StopLossDeterminer, etc.)

        Raises:
            ValueError: If module not found
            ValidationError: If params fail Pydantic validation
        """
        info = self.get_module_info(category, name)
        if info is None:
            available = [m.name for m in self.get_available_modules(category)]
            raise ValueError(
                f"Module '{name}' not found in category '{category}'. "
                f"Available: {available}"
            )
        validated = info.param_schema(**params)
        return info.cls.from_validated_params(validated)

    def get_all_modules_summary(self) -> Dict[str, List[Dict[str, Any]]]:
        """UI-friendly summary of all modules with JSON schemas."""
        result = {}
        for category in ModuleCategory.ALL:
            result[category] = [
                {
                    "name": info.name,
                    "description": info.description,
                    "schema": info.param_schema.model_json_schema(),
                    "compatible_with": info.compatible_with,
                }
                for info in self._modules[category].values()
            ]
        return result

    def validate_combination(
        self,
        entry: str,
        stop_loss: str,
        take_profit: str,
        exit_module: str,
    ) -> List[str]:
        """
        Validate module combination compatibility.

        Returns:
            List of warning messages. Empty list means all compatible.
        """
        warnings = []
        entry_info = self.get_module_info(ModuleCategory.ENTRY, entry)
        if entry_info and entry_info.compatible_with:
            mapping = {
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "exit": exit_module,
            }
            for cat, allowed in entry_info.compatible_with.items():
                actual = mapping.get(cat)
                if actual and allowed and actual not in allowed:
                    warnings.append(
                        f"Entry '{entry}' recommends {cat} in {allowed}, "
                        f"but '{actual}' selected."
                    )
        return warnings
