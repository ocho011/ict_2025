"""
Module configuration builder for strategy assembly.

Maps strategy name + config dict to StrategyModuleConfig with all 4 determiners:
- Entry determiner (when/how to enter)
- Stop loss determiner (risk management)
- Take profit determiner (profit targets)
- Exit determiner (dynamic exits)

Used as a factory for ComposableStrategy.
"""

from typing import Callable, Dict, List, Optional, Set, Tuple

from src.strategies.modules.entry.always_entry_determiner import AlwaysEntryDeterminer
from src.strategies.modules.entry.sma_entry_determiner import SMAEntryDeterminer
from src.strategies.modules.exit.null_exit_determiner import NullExitDeterminer
from src.strategies.modules.base.pricing import StrategyModuleConfig
from src.strategies.modules.sl.percentage_stop_loss_determiner import PercentageStopLossDeterminer as PercentageStopLoss
from src.strategies.modules.tp.risk_reward_take_profit_determiner import RiskRewardTakeProfitDeterminer as RiskRewardTakeProfit
from src.utils.config_manager import ExitConfig
import src.strategies.modules  # Trigger auto-discovery and registration

# Interval sorting utility
_INTERVAL_MULTIPLIERS = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _interval_to_minutes(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    return value * _INTERVAL_MULTIPLIERS.get(unit, 1)


# Strategy registry mapping names to builder functions
_STRATEGY_REGISTRY: Dict[str, Callable] = {}


def register_strategy(name: str, builder_func: Callable) -> None:
    """Register a strategy builder function."""
    _STRATEGY_REGISTRY[name] = builder_func


def build_module_config(
    strategy_name: str,
    strategy_params: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """
    Build module configuration based on strategy name.

    Args:
        strategy_name: Name of the strategy (e.g., 'ict_strategy')
        strategy_params: Dict of strategy parameters
        exit_config: Optional dynamic exit configuration

    Returns:
        (StrategyModuleConfig, intervals, min_rr_ratio)
    """
    _ensure_strategy_packages_loaded()

    if strategy_name not in _STRATEGY_REGISTRY:
        available = list(_STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"Unknown strategy: {strategy_name}. Available: {available}"
        )

    builder = _STRATEGY_REGISTRY[strategy_name]
    return builder(strategy_params, exit_config)


def _build_sma_config(
    strategy_params: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """Builder for SMA crossover strategy."""
    entry = SMAEntryDeterminer(
        fast_period=strategy_params.get("fast_period", 10),
        slow_period=strategy_params.get("slow_period", 20),
    )
    sl = PercentageStopLoss(
        stop_loss_percent=strategy_params.get("stop_loss_percent", 0.02)
    )
    tp = RiskRewardTakeProfit(
        take_profit_ratio=strategy_params.get("rr_ratio", 2.0)
    )
    exit_det = NullExitDeterminer()

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    return module_config, ["1m"], strategy_params.get("rr_ratio", 2.0)


def _build_always_signal_config(
    strategy_params: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """Builder for Always Signal strategy (testing)."""
    entry = AlwaysEntryDeterminer()
    sl = PercentageStopLoss(stop_loss_percent=0.02)
    tp = RiskRewardTakeProfit(take_profit_ratio=2.0)
    exit_det = NullExitDeterminer()

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    return module_config, None, 2.0


def _build_composable_config(
    strategy_params: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """
    Build configuration for ComposableStrategy using DynamicAssembler.
    """
    from src.strategies.dynamic_assembler import DynamicAssembler
    from src.config.symbol_config import SymbolConfig

    temp_symbol_config = SymbolConfig(
        symbol="DYNAMIC",
        strategy="composable_strategy",
        entry_config=strategy_params.get("entry_config", {}),
        exit_config=strategy_params.get("exit_config", {}),
        stop_loss_config=strategy_params.get("stop_loss_config", {}),
        take_profit_config=strategy_params.get("take_profit_config", {}),
        modules=strategy_params.get("modules", {}),
        strategy_params=strategy_config,
    )

    assembler = DynamicAssembler()
    return assembler.assemble_for_symbol(temp_symbol_config)


def _build_ict_config(
    strategy_params: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """
    Build configuration for ICT strategy using migrated modules.
    """
    from src.strategies.modules.entry.ict_optimal_entry_determiner import ICTOptimalEntryDeterminer
    from src.strategies.modules.exit.ict_dynamic_exit_determiner import ICTDynamicExitDeterminer
    from src.strategies.modules.sl.zone_based_stop_loss_determiner import ZoneBasedStopLossDeterminer
    from src.strategies.modules.tp.displacement_take_profit_determiner import DisplacementTakeProfitDeterminer

    if exit_config is None:
        exit_config = ExitConfig()

    entry = ICTOptimalEntryDeterminer.from_config(strategy_config)
    sl = ZoneBasedStopLossDeterminer()
    tp = DisplacementTakeProfitDeterminer()
    exit_det = ICTDynamicExitDeterminer(
        exit_config=exit_config,
        swing_lookback=strategy_params.get("swing_lookback", 5),
        displacement_ratio=strategy_params.get("displacement_ratio", 1.5),
        mtf_interval=strategy_params.get("mtf_interval", "1h"),
        htf_interval=strategy_params.get("htf_interval", "4h"),
    )

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    # Derive intervals from requirements
    reqs = module_config.aggregated_requirements
    intervals = (
        sorted(reqs.timeframes, key=_interval_to_minutes)
        if reqs.timeframes else ["1m"]
    )

    return module_config, intervals, strategy_params.get("rr_ratio", 2.0)


# Register strategies
register_strategy("mock_sma", _build_sma_config)
register_strategy("always_signal", _build_always_signal_config)
register_strategy("composable_strategy", _build_composable_config)
register_strategy("ict_strategy", _build_ict_config)


def get_registered_strategies() -> List[str]:
    """Get list of registered strategy names."""
    return list(_STRATEGY_REGISTRY.keys())


def _ensure_strategy_packages_loaded() -> None:
    """Lazy-load strategy packages (Legacy - no-op now)."""
    pass
