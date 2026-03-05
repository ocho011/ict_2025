"""
Dynamic strategy assembler — YAML symbol config to StrategyModuleConfig.

Replaces hardcoded builders in module_config_builder.py.
Uses ModuleRegistry for module discovery and instantiation.

Real-time Trading Guideline Compliance:
- Fresh instance creation per call (no shared state)
- Pydantic validation only during assembly (Cold Path)
"""

import logging
from typing import Dict, List, Optional, Tuple

from src.config.symbol_config import SymbolConfig
from src.strategies.modules.base.pricing import StrategyModuleConfig
from src.strategies.module_registry import ModuleCategory, ModuleRegistry

logger = logging.getLogger(__name__)

# Default modules when no spec provided (fallback)
_DEFAULT_MODULES: Dict[str, Tuple[str, dict]] = {
    ModuleCategory.ENTRY: ("sma_entry", {}),
    ModuleCategory.STOP_LOSS: ("percentage_sl", {}),
    ModuleCategory.TAKE_PROFIT: ("rr_take_profit", {}),
    ModuleCategory.EXIT: ("null_exit", {}),
}

# Interval sorting utility
_INTERVAL_MULTIPLIERS = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _interval_to_minutes(interval: str) -> int:
    """Convert interval string to minutes for sorting."""
    unit = interval[-1]
    value = int(interval[:-1])
    return value * _INTERVAL_MULTIPLIERS.get(unit, 1)


class DynamicAssembler:
    """
    Assembles StrategyModuleConfig dynamically from SymbolConfig.

    Reads SymbolConfig.modules dict, creates module instances via
    ModuleRegistry, and bundles into StrategyModuleConfig.

    Falls back to legacy build_module_config path when modules dict
    is empty (backward compatibility).
    """

    def __init__(self, registry: Optional[ModuleRegistry] = None):
        self._registry = registry or ModuleRegistry.get_instance()

    def assemble_for_symbol(
        self, symbol_config: SymbolConfig
    ) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
        """
        Assemble StrategyModuleConfig from symbol configuration.

        Args:
            symbol_config: SymbolConfig with modules dict

        Returns:
            (StrategyModuleConfig, intervals, min_rr_ratio)
        """
        # Try new explicit config fields first, then fallback to modules dict
        entry_spec = symbol_config.entry_config or symbol_config.modules.get('entry', {})
        exit_spec = symbol_config.exit_config or symbol_config.modules.get('exit', {})
        sl_spec = symbol_config.stop_loss_config or symbol_config.modules.get('stop_loss', {})
        tp_spec = symbol_config.take_profit_config or symbol_config.modules.get('take_profit', {})

        # If all specs are empty, fall back to legacy builder
        if not any([entry_spec, exit_spec, sl_spec, tp_spec]):
            return self._legacy_fallback(symbol_config)

        # Create 4 modules dynamically
        entry = self._create_module(ModuleCategory.ENTRY, entry_spec, symbol_config.symbol)
        stop_loss = self._create_module(ModuleCategory.STOP_LOSS, sl_spec, symbol_config.symbol)
        take_profit = self._create_module(ModuleCategory.TAKE_PROFIT, tp_spec, symbol_config.symbol)
        exit_det = self._create_module(ModuleCategory.EXIT, exit_spec, symbol_config.symbol)

        # Validate combination
        entry_type = self._get_module_type(entry_spec) or _DEFAULT_MODULES[ModuleCategory.ENTRY][0]
        sl_type = self._get_module_type(sl_spec) or _DEFAULT_MODULES[ModuleCategory.STOP_LOSS][0]
        tp_type = self._get_module_type(tp_spec) or _DEFAULT_MODULES[ModuleCategory.TAKE_PROFIT][0]
        exit_type = self._get_module_type(exit_spec) or _DEFAULT_MODULES[ModuleCategory.EXIT][0]

        warnings = self._registry.validate_combination(entry_type, sl_type, tp_type, exit_type)
        for w in warnings:
            logger.warning("[%s] Module compatibility: %s", symbol_config.symbol, w)

        module_config = StrategyModuleConfig(
            entry_determiner=entry,
            stop_loss_determiner=stop_loss,
            take_profit_determiner=take_profit,
            exit_determiner=exit_det,
        )

        # Derive intervals from aggregated requirements
        reqs = module_config.aggregated_requirements
        intervals = (
            sorted(reqs.timeframes, key=_interval_to_minutes)
            if reqs.timeframes else None
        )

        # Extract min_rr_ratio from take_profit params or default
        tp_params = self._get_module_params(tp_spec)
        min_rr_ratio = tp_params.get('take_profit_ratio', tp_params.get('risk_reward_ratio', 1.5))

        logger.info(
            "[%s] Dynamic assembly complete: entry=%s, sl=%s, tp=%s, exit=%s, intervals=%s",
            symbol_config.symbol, entry_type, sl_type, tp_type, exit_type, intervals,
        )

        return module_config, intervals, min_rr_ratio

    def _get_module_type(self, spec: dict) -> Optional[str]:
        """Normalize module type/strategy name."""
        return spec.get('strategy') or spec.get('type')

    def _get_module_params(self, spec: dict) -> dict:
        """Normalize module parameters."""
        return spec.get('parameters') or spec.get('params', {})

    def _create_module(self, category: str, spec: dict, symbol: str):
        """Create a single module. Uses default if spec is empty."""
        module_type = self._get_module_type(spec)
        params = self._get_module_params(spec)

        if not module_type:
            default_type, default_params = _DEFAULT_MODULES[category]
            module_type = default_type
            params = default_params
            logger.debug(
                "[%s] No %s module specified, using default: %s",
                symbol, category, module_type,
            )

        return self._registry.create_module(category, module_type, params)

    def _legacy_fallback(
        self, symbol_config: SymbolConfig
    ) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
        """Fall back to legacy build_module_config when no modules dict."""
        from src.strategies.module_config_builder import build_module_config

        logger.info(
            "[%s] No modules spec, falling back to legacy builder for strategy '%s'",
            symbol_config.symbol, symbol_config.strategy,
        )
        return build_module_config(
            strategy_name=symbol_config.strategy,
            strategy_config=symbol_config.strategy_params,
        )
