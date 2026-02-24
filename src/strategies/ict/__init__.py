"""
ICT (Inner Circle Trader) strategy package. Self-registering.

Note: Submodule imports are lazy (inside _build_ict_config) to avoid
circular imports via src.entry/__init__.py and src.exit/__init__.py
re-export stubs.
"""

from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Interval sorting utility
# ---------------------------------------------------------------------------
_INTERVAL_MULTIPLIERS = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _interval_to_minutes(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    return value * _INTERVAL_MULTIPLIERS.get(unit, 1)


# ---------------------------------------------------------------------------
# ICT strategy builder — self-registers into the strategy registry
# ---------------------------------------------------------------------------

def _build_ict_config(
    strategy_config: dict,
    exit_config=None,
) -> Tuple:
    """Build configuration for ICT strategy."""
    from src.pricing.base import StrategyModuleConfig
    from src.utils.config_manager import ExitConfig
    from src.strategies.ict.entry import ICTEntryDeterminer
    from src.strategies.ict.exit import ICTExitDeterminer
    from src.strategies.ict.pricing.zone_based_sl import ZoneBasedStopLoss
    from src.strategies.ict.pricing.displacement_tp import DisplacementTakeProfit

    if exit_config is None:
        exit_config = ExitConfig()

    entry = ICTEntryDeterminer.from_config(strategy_config)
    sl = ZoneBasedStopLoss()
    tp = DisplacementTakeProfit()
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

    agg = module_config.aggregated_requirements
    intervals = sorted(agg.timeframes, key=_interval_to_minutes) if agg.timeframes else None

    return module_config, intervals, min_rr_ratio


# Auto-register on import
from src.strategies.module_config_builder import register_strategy  # noqa: E402

register_strategy("ict_strategy", _build_ict_config)
