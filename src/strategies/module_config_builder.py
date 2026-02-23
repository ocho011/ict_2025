"""
Module configuration builder for strategy assembly.

Maps strategy name + config dict to StrategyModuleConfig with all 4 determiners:
- Entry determiner (when/how to enter)
- Stop loss determiner (risk management)
- Take profit determiner (profit target)
- Exit determiner (dynamic exit logic)

Real-time Trading Guideline Compliance:
- Fresh instance creation per call (no shared state)
- Minimal validation (config already validated upstream)
- No datetime parsing
"""

from typing import Callable, Dict, List, Optional, Set, Tuple

from src.entry import AlwaysEntryDeterminer, SMAEntryDeterminer
from src.exit import NullExitDeterminer
from src.pricing.base import StrategyModuleConfig
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.utils.config_manager import ExitConfig

# Interval sorting utility
_INTERVAL_MULTIPLIERS = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _interval_to_minutes(interval: str) -> int:
    """Convert interval string to minutes for sorting. e.g., '5m'->5, '1h'->60."""
    unit = interval[-1]
    value = int(interval[:-1])
    return value * _INTERVAL_MULTIPLIERS.get(unit, 1)


# Strategy builder type: (strategy_config, exit_config) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]
StrategyBuilder = Callable[..., Tuple["StrategyModuleConfig", Optional[List[str]], float]]

_STRATEGY_REGISTRY: Dict[str, StrategyBuilder] = {}


def register_strategy(name: str, builder: StrategyBuilder) -> None:
    """Register a strategy builder function."""
    _STRATEGY_REGISTRY[name] = builder


def get_registered_strategies() -> Set[str]:
    """Return set of all registered strategy names."""
    _ensure_strategy_packages_loaded()
    return set(_STRATEGY_REGISTRY.keys())


def build_module_config(
    strategy_name: str,
    strategy_config: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """
    Build StrategyModuleConfig from strategy name and config.

    Creates fresh instances of all determiners for per-symbol isolation.
    Each call produces independent objects with no shared state.

    Args:
        strategy_name: Strategy identifier ("ict_strategy", "mock_sma", "always_signal")
        strategy_config: Strategy-specific configuration dict
        exit_config: Exit configuration (optional, uses defaults if None)

    Returns:
        Tuple of (module_config, intervals_override, min_rr_ratio)

    Raises:
        ValueError: If strategy_name is unknown
    """
    _ensure_strategy_packages_loaded()

    if strategy_name not in _STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy name: {strategy_name}. "
            f"Registered: {sorted(_STRATEGY_REGISTRY.keys())}"
        )
    builder = _STRATEGY_REGISTRY[strategy_name]
    return builder(strategy_config, exit_config)


def _build_sma_config(
    strategy_config: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """Build configuration for SMA strategy."""
    entry = SMAEntryDeterminer()
    sl = PercentageStopLoss()
    tp = RiskRewardTakeProfit()
    exit_det = NullExitDeterminer()

    intervals = None
    min_rr_ratio = strategy_config.get("rr_ratio", 2.0)

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    return module_config, intervals, min_rr_ratio


def _build_always_signal_config(
    strategy_config: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """Build configuration for AlwaysSignal strategy (testing)."""
    entry = AlwaysEntryDeterminer()
    sl = PercentageStopLoss()
    tp = RiskRewardTakeProfit()
    exit_det = NullExitDeterminer()

    intervals = None
    min_rr_ratio = strategy_config.get("rr_ratio", 2.0)

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    return module_config, intervals, min_rr_ratio


# Register built-in non-ICT strategies
register_strategy("mock_sma", _build_sma_config)
register_strategy("always_signal", _build_always_signal_config)


def _ensure_strategy_packages_loaded() -> None:
    """Lazy-load strategy packages that self-register."""
    if "ict_strategy" not in _STRATEGY_REGISTRY:
        import src.strategies.ict  # noqa: F401
