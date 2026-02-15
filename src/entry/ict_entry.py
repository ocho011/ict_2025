"""
ICT entry determination module.

Extracted from ICTStrategy.analyze() (Steps 1-8 of 10-step ICT analysis).
Returns EntryDecision (NOT Signal) - TP/SL calculated by separate determiners.

Extraction boundary:
- IN:  Steps 1-8 (killzone, trend, premium/discount, FVG/OB, liquidity,
       inducement, displacement, entry timing) + zone extraction + metadata assembly
- OUT: TP/SL calculation, RR validation (moved to ComposableStrategy),
       buffer management (update_buffer, is_ready, _update_feature_cache)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.config.ict_profiles import get_profile_parameters, load_profile_from_name
from src.detectors.ict_fvg import (
    detect_bearish_fvg,
    detect_bullish_fvg,
    find_nearest_fvg,
    get_entry_zone,
)
from src.detectors.ict_killzones import get_active_killzone, is_killzone_active
from src.detectors.ict_liquidity import (
    calculate_premium_discount,
    detect_liquidity_sweep,
    find_equal_highs,
    find_equal_lows,
    is_in_discount,
    is_in_premium,
)
from src.detectors.ict_market_structure import get_current_trend
from src.detectors.ict_order_block import (
    find_nearest_ob,
    get_ob_zone,
    identify_bearish_ob,
    identify_bullish_ob,
)
from src.detectors.ict_smc import (
    detect_displacement,
    detect_inducement,
    find_mitigation_zone,
)
from src.entry.base import EntryContext, EntryDecision, EntryDeterminer
from src.models.signal import SignalType


@dataclass
class ICTEntryDeterminer(EntryDeterminer):
    """
    ICT entry determination using Smart Money Concepts.

    Extracted from ICTStrategy.analyze() lines 275-675.
    Implements Steps 1-8 of the 10-step ICT analysis process.

    What's REMOVED (not this determiner's job):
    - buffer management (update_buffer, _update_feature_cache, is_ready)
    - TP/SL calculation (separate determiners)
    - RR ratio validation (moved to ComposableStrategy)

    What's ADDED:
    - Zone extraction: get_entry_zone/get_ob_zone -> tuples in metadata
    - Displacement size extraction -> float in metadata
    - Returns EntryDecision instead of Signal

    Metadata convention:
    - Keys prefixed with '_' are internal transport (stripped from final Signal)
    - Other keys become part of public Signal metadata
    """

    # ICT parameters (profile defaults)
    swing_lookback: int = 5
    displacement_ratio: float = 1.5
    fvg_min_gap_percent: float = 0.001
    ob_min_strength: float = 1.5
    liquidity_tolerance: float = 0.001
    use_killzones: bool = True
    min_periods: int = 50

    # MTF interval names (set from config)
    ltf_interval: str = "5m"
    mtf_interval: str = "1h"
    htf_interval: str = "4h"

    # Condition statistics for tuning analysis
    condition_stats: Dict[str, int] = field(default_factory=lambda: {
        "total_checks": 0,
        "killzone_ok": 0,
        "trend_ok": 0,
        "zone_ok": 0,
        "fvg_ob_ok": 0,
        "inducement_ok": 0,
        "displacement_ok": 0,
        "all_conditions_ok": 0,
        "signals_generated": 0,
    })

    def __post_init__(self):
        self.logger = logging.getLogger(__name__)
        self.min_periods = max(50, self.swing_lookback * 4)

    @classmethod
    def from_config(cls, config: dict) -> "ICTEntryDeterminer":
        """
        Create ICTEntryDeterminer from strategy config dict with profile loading.

        Args:
            config: Strategy configuration dictionary

        Returns:
            Configured ICTEntryDeterminer instance
        """
        # Load profile-based parameter defaults
        profile_name = config.get("active_profile", "strict")
        try:
            profile = load_profile_from_name(profile_name)
            profile_params = get_profile_parameters(profile)
        except ValueError:
            profile_params = {}

        return cls(
            swing_lookback=config.get(
                "swing_lookback", profile_params.get("swing_lookback", 5)
            ),
            displacement_ratio=config.get(
                "displacement_ratio", profile_params.get("displacement_ratio", 1.5)
            ),
            fvg_min_gap_percent=config.get(
                "fvg_min_gap_percent", profile_params.get("fvg_min_gap_percent", 0.001)
            ),
            ob_min_strength=config.get(
                "ob_min_strength", profile_params.get("ob_min_strength", 1.5)
            ),
            liquidity_tolerance=config.get(
                "liquidity_tolerance", profile_params.get("liquidity_tolerance", 0.001)
            ),
            use_killzones=config.get("use_killzones", True),
            ltf_interval=config.get("ltf_interval", "5m"),
            mtf_interval=config.get("mtf_interval", "1h"),
            htf_interval=config.get("htf_interval", "4h"),
        )

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        """
        Analyze market context using ICT methodology.

        Extracted from ICTStrategy.analyze() lines 275-675.
        Steps 1-8 preserved exactly. Steps 9-10 (TP/SL) removed.

        Returns:
            EntryDecision with metadata for downstream TP/SL calculation,
            or None if conditions not met.
        """
        candle = context.candle

        # Step 1: Validate candle is closed
        if not candle.is_closed:
            return None

        # Get LTF buffer (primary analysis buffer)
        ltf_buffer = context.buffers.get(self.ltf_interval)
        if not ltf_buffer or len(ltf_buffer) < self.min_periods:
            return None

        # Use MTF buffer for structure detection when available
        candle_buffer = ltf_buffer

        # Kill Zone Filter
        if self.use_killzones:
            if not is_killzone_active(candle.open_time):
                return None

        # Step 2: Trend Analysis (Market Structure)
        trend = None
        if context.indicator_cache is not None:
            htf_structure = context.indicator_cache.get_market_structure(
                self.htf_interval
            )
            mtf_structure = context.indicator_cache.get_market_structure(
                self.mtf_interval
            )
            if htf_structure:
                trend = htf_structure.trend
            elif mtf_structure:
                trend = mtf_structure.trend

        # Fallback to original calculation if cache unavailable
        if trend is None:
            trend = get_current_trend(candle_buffer, swing_lookback=self.swing_lookback)

        if trend is None or trend == "sideways":
            return None

        # Step 3: Premium/Discount Zone
        range_low, range_mid, range_high = calculate_premium_discount(
            candle_buffer, lookback=50
        )
        current_price = candle.close

        # Step 4: FVG/OB Detection
        mtf_interval = self.mtf_interval
        if context.indicator_cache is not None:
            bullish_fvgs_cached = context.indicator_cache.get_active_fvgs(
                mtf_interval, "bullish"
            )
            bearish_fvgs_cached = context.indicator_cache.get_active_fvgs(
                mtf_interval, "bearish"
            )
            bullish_obs_cached = context.indicator_cache.get_active_order_blocks(
                mtf_interval, "bullish"
            )
            bearish_obs_cached = context.indicator_cache.get_active_order_blocks(
                mtf_interval, "bearish"
            )

            bullish_fvgs = bullish_fvgs_cached
            bearish_fvgs = bearish_fvgs_cached
            bullish_obs = [
                ob for ob in bullish_obs_cached if ob.strength >= self.ob_min_strength
            ]
            bearish_obs = [
                ob for ob in bearish_obs_cached if ob.strength >= self.ob_min_strength
            ]
        else:
            bullish_fvgs = detect_bullish_fvg(
                candle_buffer,
                interval=mtf_interval,
                min_gap_percent=self.fvg_min_gap_percent,
            )
            bearish_fvgs = detect_bearish_fvg(
                candle_buffer,
                interval=mtf_interval,
                min_gap_percent=self.fvg_min_gap_percent,
            )
            bullish_obs, bearish_obs = (
                identify_bullish_ob(
                    candle_buffer,
                    interval=mtf_interval,
                    displacement_ratio=self.displacement_ratio,
                ),
                identify_bearish_ob(
                    candle_buffer,
                    interval=mtf_interval,
                    displacement_ratio=self.displacement_ratio,
                ),
            )
            bullish_obs = [
                ob for ob in bullish_obs if ob.strength >= self.ob_min_strength
            ]
            bearish_obs = [
                ob for ob in bearish_obs if ob.strength >= self.ob_min_strength
            ]

        # Step 5: Liquidity Analysis
        equal_highs = find_equal_highs(
            candle_buffer, tolerance_percent=self.liquidity_tolerance, lookback=20
        )
        equal_lows = find_equal_lows(
            candle_buffer, tolerance_percent=self.liquidity_tolerance, lookback=20
        )
        detect_liquidity_sweep(candle_buffer, equal_highs + equal_lows)

        # Step 6: Inducement Check
        inducements = detect_inducement(candle_buffer, lookback=10)

        # Step 7: Displacement Confirmation
        displacements = detect_displacement(
            candle_buffer, displacement_ratio=self.displacement_ratio
        )

        # Step 8: Entry Timing - mitigation zone detection
        if context.indicator_cache is None:
            _mitigations = find_mitigation_zone(
                candle_buffer,
                fvgs=bullish_fvgs + bearish_fvgs,
                obs=bullish_obs + bearish_obs,
            )

        # Condition tracking for tuning analysis
        self.condition_stats["total_checks"] += 1

        in_killzone = not self.use_killzones or is_killzone_active(candle.open_time)
        if in_killzone:
            self.condition_stats["killzone_ok"] += 1

        has_trend = trend is not None
        if has_trend:
            self.condition_stats["trend_ok"] += 1

        # LONG Entry Logic
        if trend == "bullish" and is_in_discount(current_price, range_low, range_high):
            self.condition_stats["zone_ok"] += 1

            candidate_fvgs = [f for f in bullish_fvgs if f.gap_low < current_price]
            candidate_obs = [ob for ob in bullish_obs if ob.low < current_price]

            nearest_fvg = find_nearest_fvg(
                candidate_fvgs, current_price, direction="bullish"
            )
            nearest_ob = find_nearest_ob(
                candidate_obs, current_price, direction="bullish"
            )

            has_fvg_ob = nearest_fvg is not None or nearest_ob is not None
            if has_fvg_ob:
                self.condition_stats["fvg_ob_ok"] += 1

            recent_inducement = any(
                ind.direction == "bearish" for ind in inducements[-3:] if inducements
            )
            if recent_inducement:
                self.condition_stats["inducement_ok"] += 1

            recent_displacement = any(
                disp.direction == "bullish"
                for disp in displacements[-3:]
                if displacements
            )
            if recent_displacement:
                self.condition_stats["displacement_ok"] += 1

            if (
                recent_inducement
                and recent_displacement
                and (nearest_fvg or nearest_ob)
            ):
                self.condition_stats["all_conditions_ok"] += 1
                self.condition_stats["signals_generated"] += 1

                self.logger.debug(
                    f"ICT LONG Signal: trend={trend}, zone=discount, "
                    f"fvg={nearest_fvg is not None}, ob={nearest_ob is not None}, "
                    f"inducement={recent_inducement}, displacement={recent_displacement}"
                )

                entry_price = candle.close

                # Step 9: Zone Extraction for downstream TP/SL
                fvg_zone = get_entry_zone(nearest_fvg) if nearest_fvg else None
                ob_zone = get_ob_zone(nearest_ob) if nearest_ob else None

                displacement_size = None
                if displacements:
                    displacement_size = displacements[-1].size

                metadata = {
                    # Internal transport keys (stripped from final Signal)
                    "_fvg_zone": fvg_zone,
                    "_ob_zone": ob_zone,
                    "_displacement_size": displacement_size,
                    # Public metadata
                    "trend": trend,
                    "zone": "discount",
                    "killzone": (
                        get_active_killzone(candle.open_time)
                        if self.use_killzones
                        else None
                    ),
                    "fvg_present": nearest_fvg is not None,
                    "ob_present": nearest_ob is not None,
                    "inducement": recent_inducement,
                    "displacement": recent_displacement,
                }

                return EntryDecision(
                    signal_type=SignalType.LONG_ENTRY,
                    entry_price=entry_price,
                    confidence=1.0,
                    metadata=metadata,
                )

        # SHORT Entry Logic
        elif trend == "bearish" and is_in_premium(current_price, range_low, range_high):
            self.condition_stats["zone_ok"] += 1

            candidate_fvgs = [f for f in bearish_fvgs if f.gap_high > current_price]
            candidate_obs = [ob for ob in bearish_obs if ob.high > current_price]

            nearest_fvg = find_nearest_fvg(
                candidate_fvgs, current_price, direction="bearish"
            )
            nearest_ob = find_nearest_ob(
                candidate_obs, current_price, direction="bearish"
            )

            has_fvg_ob = nearest_fvg is not None or nearest_ob is not None
            if has_fvg_ob:
                self.condition_stats["fvg_ob_ok"] += 1

            recent_inducement = any(
                ind.direction == "bullish" for ind in inducements[-3:] if inducements
            )
            if recent_inducement:
                self.condition_stats["inducement_ok"] += 1

            recent_displacement = any(
                disp.direction == "bearish"
                for disp in displacements[-3:]
                if displacements
            )
            if recent_displacement:
                self.condition_stats["displacement_ok"] += 1

            if (
                recent_inducement
                and recent_displacement
                and (nearest_fvg or nearest_ob)
            ):
                self.condition_stats["all_conditions_ok"] += 1
                self.condition_stats["signals_generated"] += 1

                self.logger.debug(
                    f"ICT SHORT Signal: trend={trend}, zone=premium, "
                    f"fvg={nearest_fvg is not None}, ob={nearest_ob is not None}, "
                    f"inducement={recent_inducement}, displacement={recent_displacement}"
                )

                entry_price = candle.close

                # Step 9: Zone Extraction for downstream TP/SL
                fvg_zone = get_entry_zone(nearest_fvg) if nearest_fvg else None
                ob_zone = get_ob_zone(nearest_ob) if nearest_ob else None

                displacement_size = None
                if displacements:
                    displacement_size = displacements[-1].size

                metadata = {
                    "_fvg_zone": fvg_zone,
                    "_ob_zone": ob_zone,
                    "_displacement_size": displacement_size,
                    "trend": trend,
                    "zone": "premium",
                    "killzone": (
                        get_active_killzone(candle.open_time)
                        if self.use_killzones
                        else None
                    ),
                    "fvg_present": nearest_fvg is not None,
                    "ob_present": nearest_ob is not None,
                    "inducement": recent_inducement,
                    "displacement": recent_displacement,
                }

                return EntryDecision(
                    signal_type=SignalType.SHORT_ENTRY,
                    entry_price=entry_price,
                    confidence=1.0,
                    metadata=metadata,
                )

        self.logger.debug(
            f"ICT Conditions Check: trend={trend}, "
            f"use_killzones={self.use_killzones}, "
            f"is_killzone={is_killzone_active(candle.open_time)}, "
            f"fvgs={len(bullish_fvgs) + len(bearish_fvgs)}, "
            f"obs={len(bullish_obs) + len(bearish_obs)}, "
            f"inducements={len(inducements)}, "
            f"displacements={len(displacements)} - No signal"
        )

        return None

    def get_condition_stats(self) -> dict:
        """Get condition statistics for tuning analysis."""
        total = self.condition_stats["total_checks"]
        if total == 0:
            return self.condition_stats.copy()

        success_rates = {
            "killzone_rate": self.condition_stats["killzone_ok"] / total,
            "trend_rate": self.condition_stats["trend_ok"] / total,
            "zone_rate": self.condition_stats["zone_ok"] / total,
            "fvg_ob_rate": self.condition_stats["fvg_ob_ok"] / total,
            "inducement_rate": self.condition_stats["inducement_ok"] / total,
            "displacement_rate": self.condition_stats["displacement_ok"] / total,
            "all_conditions_rate": self.condition_stats["all_conditions_ok"] / total,
            "signal_rate": self.condition_stats["signals_generated"] / total,
        }

        stats = self.condition_stats.copy()
        stats["success_rates"] = success_rates  # type: ignore
        return stats

    def reset_condition_stats(self) -> None:
        """Reset condition statistics to zero."""
        for key in self.condition_stats:
            self.condition_stats[key] = 0
