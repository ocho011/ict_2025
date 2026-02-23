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

from src.entry import AlwaysEntryDeterminer, ICTEntryDeterminer, SMAEntryDeterminer

# Interval sorting utility
_INTERVAL_MULTIPLIERS = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _interval_to_minutes(interval: str) -> int:
    """Convert interval string to minutes for sorting. e.g., '5m'->5, '1h'->60."""
    unit = interval[-1]
    value = int(interval[:-1])
    return value * _INTERVAL_MULTIPLIERS.get(unit, 1)
from src.exit import ICTExitDeterminer, NullExitDeterminer
from src.pricing.base import StrategyModuleConfig
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
from src.pricing.take_profit.displacement import DisplacementTakeProfit
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.utils.config_manager import ExitConfig

# Strategy builder type: (strategy_config, exit_config) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]
StrategyBuilder = Callable[..., Tuple["StrategyModuleConfig", Optional[List[str]], float]]

_STRATEGY_REGISTRY: Dict[str, StrategyBuilder] = {}


def register_strategy(name: str, builder: StrategyBuilder) -> None:
    """Register a strategy builder function."""
    _STRATEGY_REGISTRY[name] = builder


def get_registered_strategies() -> Set[str]:
    """Return set of all registered strategy names."""
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
        Tuple of (module_config, intervals_override, min_rr_ratio):
        - module_config: Complete StrategyModuleConfig bundle
        - intervals_override: List of interval strings for multi-timeframe strategies,
                             or None to use default intervals
        - min_rr_ratio: Minimum risk-reward ratio for signal validation

    Raises:
        ValueError: If strategy_name is unknown

    Registry:
        ict_strategy:
            Entry: ICTEntryDeterminer (profile-based config)
            SL: ZoneBasedStopLoss (FVG/OB zones with buffer)
            TP: DisplacementTakeProfit (displacement-based R:R)
            Exit: ICTExitDeterminer (trailing/breakeven/timed/indicator)
            MTF: [ltf_interval, mtf_interval, htf_interval]

        mock_sma:
            Entry: SMAEntryDeterminer (simple moving average)
            SL: PercentageStopLoss (fixed percentage)
            TP: RiskRewardTakeProfit (R:R based on SL distance)
            Exit: NullExitDeterminer (no dynamic exit)
            MTF: None (single timeframe)

        always_signal:
            Entry: AlwaysEntryDeterminer (always signals entry)
            SL: PercentageStopLoss (fixed percentage)
            TP: RiskRewardTakeProfit (R:R based on SL distance)
            Exit: NullExitDeterminer (no dynamic exit)
            MTF: None (single timeframe)
    """
    if strategy_name not in _STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy name: {strategy_name}. "
            f"Registered: {sorted(_STRATEGY_REGISTRY.keys())}"
        )
    builder = _STRATEGY_REGISTRY[strategy_name]
    return builder(strategy_config, exit_config)


def _build_ict_config(
    strategy_config: dict,
    exit_config: Optional[ExitConfig],
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """Build configuration for ICT strategy."""
    # Entry: Use classmethod for profile loading + parameter defaults
    entry = ICTEntryDeterminer.from_config(strategy_config)

    # Pricing: ICT-specific zone-based SL and displacement TP
    sl = ZoneBasedStopLoss()
    tp = DisplacementTakeProfit()

    # Exit: ICT exit determiner with direct construction
    exit_det = ICTExitDeterminer(
        exit_config=exit_config,
        swing_lookback=strategy_config.get("swing_lookback", 5),
        displacement_ratio=strategy_config.get("displacement_ratio", 1.5),
        mtf_interval=strategy_config.get("mtf_interval", "1h"),
        htf_interval=strategy_config.get("htf_interval", "4h"),
    )

    min_rr_ratio = strategy_config.get("rr_ratio", 2.0)

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    # Derive intervals from aggregated module requirements
    agg = module_config.aggregated_requirements
    intervals = sorted(agg.timeframes, key=_interval_to_minutes) if agg.timeframes else None

    return module_config, intervals, min_rr_ratio


def _build_sma_config(
    strategy_config: dict,
    exit_config: Optional[ExitConfig] = None,
) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
    """Build configuration for SMA strategy."""
    # Entry: Simple moving average entry
    entry = SMAEntryDeterminer()

    # Pricing: Percentage-based SL and risk-reward TP
    sl = PercentageStopLoss()
    tp = RiskRewardTakeProfit()

    # Exit: No dynamic exit logic
    exit_det = NullExitDeterminer()

    # Single timeframe (use default)
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
    # Entry: Always signals entry (for testing)
    entry = AlwaysEntryDeterminer()

    # Pricing: Percentage-based SL and risk-reward TP
    sl = PercentageStopLoss()
    tp = RiskRewardTakeProfit()

    # Exit: No dynamic exit logic
    exit_det = NullExitDeterminer()

    # Single timeframe (use default)
    intervals = None
    min_rr_ratio = strategy_config.get("rr_ratio", 2.0)

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    return module_config, intervals, min_rr_ratio


# Register built-in strategies
register_strategy("ict_strategy", _build_ict_config)
register_strategy("mock_sma", _build_sma_config)
register_strategy("always_signal", _build_always_signal_config)
