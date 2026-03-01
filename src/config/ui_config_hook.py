"""
UI <-> Config integration hook.

Provides getDynamicParamsFromUI() and apply_config_update() APIs
for UI to query and modify symbol module configurations.

Design Principles:
- Cold Path only: Pydantic validation on UI input, never in hot trading loop
- Event-based: Changes propagated via ConfigUpdateEvent
- YAML sync: Changes persisted to YAML file
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.config.symbol_config import TradingConfigHierarchical
from src.events.config_events import ConfigUpdateEvent
from src.strategies.module_registry import ModuleCategory, ModuleRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UIConfigUpdate:
    """Config change request from UI."""
    symbol: str
    module_category: str  # 'entry' | 'stop_loss' | 'take_profit' | 'exit'
    module_type: Optional[str] = None  # None = params-only change
    params: Optional[Dict[str, Any]] = None


class UIConfigHook:
    """
    UI <-> Config integration hook.

    Two main APIs:
    - get_dynamic_params_from_ui(symbol): Query current config + available modules
    - apply_config_update(update): Validate and apply config change
    """

    def __init__(
        self,
        hierarchical_config: TradingConfigHierarchical,
        registry: Optional[ModuleRegistry] = None,
        config_event_callback: Optional[Callable] = None,
        yaml_writer: Optional[Callable] = None,
    ):
        self._config = hierarchical_config
        self._registry = registry or ModuleRegistry.get_instance()
        self._on_config_event = config_event_callback
        self._yaml_writer = yaml_writer

    def get_dynamic_params_from_ui(self, symbol: str) -> Dict[str, Any]:
        """
        Get current module config + available modules for UI display.

        Returns:
            {
                "symbol": "BTCUSDT",
                "entry": {"type": ..., "params": ..., "schema": ..., "available_modules": [...]},
                "stop_loss": {...},
                "take_profit": {...},
                "exit": {...}
            }
        """
        symbol_config = self._config.get_symbol_config(symbol)
        modules_spec = symbol_config.modules if symbol_config.modules else {}
        result: Dict[str, Any] = {"symbol": symbol}

        for category in ModuleCategory.ALL:
            mod_spec = modules_spec.get(category, {})
            mod_type = mod_spec.get('type', '')
            mod_params = mod_spec.get('params', {})

            schema = self._registry.get_param_schema(category, mod_type)
            available = self._registry.get_available_modules(category)

            result[category] = {
                "type": mod_type,
                "params": mod_params,
                "schema": schema.model_json_schema() if schema else None,
                "available_modules": [
                    {"name": m.name, "description": m.description}
                    for m in available
                ],
            }

        return result

    def get_all_symbols_config(self) -> List[Dict[str, Any]]:
        """Get config for all enabled symbols."""
        return [
            self.get_dynamic_params_from_ui(symbol)
            for symbol in self._config.get_enabled_symbols()
        ]

    async def apply_config_update(
        self, update: UIConfigUpdate
    ) -> ConfigUpdateEvent:
        """
        Validate and apply config change from UI.

        Flow:
        1. Pydantic schema validation (Cold Path)
        2. In-memory config update
        3. YAML file sync (optional)
        4. Emit ConfigUpdateEvent
        """
        symbol_config = self._config.get_symbol_config(update.symbol)
        modules_spec = symbol_config.modules if symbol_config.modules else {}
        current_type = modules_spec.get(update.module_category, {}).get('type', '')

        effective_type = update.module_type or current_type
        requires_rebuild = (
            update.module_type is not None
            and update.module_type != current_type
        )

        # 1. Pydantic validation
        validated_params: Dict[str, Any] = {}
        if update.params:
            schema = self._registry.get_param_schema(
                update.module_category, effective_type
            )
            if schema:
                validated = schema(**update.params)
                validated_params = validated.model_dump()
            else:
                validated_params = update.params

        # 2. In-memory update
        if update.module_category not in modules_spec:
            modules_spec[update.module_category] = {}
        if update.module_type:
            modules_spec[update.module_category]['type'] = update.module_type
        if validated_params:
            modules_spec[update.module_category]['params'] = validated_params

        # Ensure modules dict is on symbol_config
        if not symbol_config.modules:
            symbol_config.modules = modules_spec

        # 3. YAML sync
        if self._yaml_writer:
            try:
                self._yaml_writer(self._config)
            except Exception as e:
                logger.error("Failed to write YAML: %s", e)

        # 4. Emit event
        event = ConfigUpdateEvent(
            symbol=update.symbol,
            category=update.module_category,
            module_type=update.module_type,
            params=validated_params,
            requires_strategy_rebuild=requires_rebuild,
        )

        if self._on_config_event:
            await self._on_config_event(event)

        logger.info(
            "[%s] Config update applied: %s.%s (rebuild=%s)",
            update.symbol, update.module_category,
            update.module_type or "params_only", requires_rebuild,
        )

        return event
