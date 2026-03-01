"""
Module registration decorator for strategy modules.

Provides @register_module decorator that automatically registers
strategy module classes (Entry, StopLoss, TakeProfit, Exit) into
the ModuleRegistry singleton at import time.

Requirements for decorated classes:
- Must define ParamSchema inner class (Pydantic BaseModel)
- Must define from_validated_params(cls, params) classmethod
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


def register_module(
    category: str,
    name: str,
    description: str = "",
    compatible_with: Optional[Dict[str, List[str]]] = None,
):
    """
    Class decorator: auto-register module into ModuleRegistry.

    Usage:
        @register_module('entry', 'ict_entry', description='ICT entry')
        class ICTEntryDeterminer(EntryDeterminer):
            class ParamSchema(BaseModel):
                active_profile: str = "balanced"

            @classmethod
            def from_validated_params(cls, params):
                return cls.from_config(params.model_dump())

    Args:
        category: Module category ('entry', 'stop_loss', 'take_profit', 'exit')
        name: Unique module name within category
        description: Human-readable description for UI
        compatible_with: Optional compatibility hints {category: [allowed_names]}
    """
    def decorator(cls):
        # Validate ParamSchema exists and is Pydantic BaseModel
        if not hasattr(cls, 'ParamSchema'):
            raise AttributeError(
                f"{cls.__name__} must define 'ParamSchema' inner class "
                f"(Pydantic BaseModel) for @register_module"
            )
        if not issubclass(cls.ParamSchema, BaseModel):
            raise TypeError(
                f"{cls.__name__}.ParamSchema must inherit from pydantic.BaseModel"
            )

        # Validate from_validated_params exists
        if not hasattr(cls, 'from_validated_params'):
            raise AttributeError(
                f"{cls.__name__} must define 'from_validated_params(cls, params)' "
                f"classmethod for @register_module"
            )

        # Register into ModuleRegistry (lazy import to avoid circular deps)
        from src.strategies.module_registry import ModuleRegistry
        ModuleRegistry.get_instance().register(
            category=category,
            name=name,
            cls_type=cls,
            param_schema=cls.ParamSchema,
            description=description,
            compatible_with=compatible_with,
        )

        # Return original class unmodified
        return cls

    return decorator
