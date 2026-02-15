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

from typing import List, Optional, Tuple

from src.entry import AlwaysEntryDeterminer, ICTEntryDeterminer, SMAEntryDeterminer
from src.exit import ICTExitDeterminer, NullExitDeterminer
from src.pricing.base import StrategyModuleConfig
from src.pricing.stop_loss.percentage import PercentageStopLoss
from src.pricing.stop_loss.zone_based import ZoneBasedStopLoss
from src.pricing.take_profit.displacement import DisplacementTakeProfit
from src.pricing.take_profit.risk_reward import RiskRewardTakeProfit
from src.utils.config_manager import ExitConfig


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
    if strategy_name == "ict_strategy":
        return _build_ict_config(strategy_config, exit_config)
    elif strategy_name == "mock_sma":
        return _build_sma_config(strategy_config)
    elif strategy_name == "always_signal":
        return _build_always_signal_config(strategy_config)
    else:
        raise ValueError(
            f"Unknown strategy name: {strategy_name}. "
            f"Supported: ict_strategy, mock_sma, always_signal"
        )


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

    # Multi-timeframe intervals for ICT
    intervals = [
        strategy_config.get("ltf_interval", "5m"),
        strategy_config.get("mtf_interval", "1h"),
        strategy_config.get("htf_interval", "4h"),
    ]

    min_rr_ratio = strategy_config.get("rr_ratio", 2.0)

    module_config = StrategyModuleConfig(
        entry_determiner=entry,
        stop_loss_determiner=sl,
        take_profit_determiner=tp,
        exit_determiner=exit_det,
    )

    return module_config, intervals, min_rr_ratio


def _build_sma_config(
    strategy_config: dict,
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
