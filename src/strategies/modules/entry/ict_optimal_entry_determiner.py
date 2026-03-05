"""
ICT Optimal Entry Determiner module.

Transitioned to Full Composable Architecture.
Implements Steps 1-8 of the 10-step ICT analysis process.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from src.strategies.decorators import register_module

from src.strategies.modules.ict_profiles import get_profile_parameters, load_profile_from_name
from src.strategies.modules.detectors.fvg import (
    detect_bearish_fvg,
    detect_bullish_fvg,
    find_nearest_fvg,
    get_entry_zone,
)
from src.strategies.modules.detectors.killzones import get_active_killzone, is_killzone_active
from src.strategies.modules.detectors.liquidity import (
    calculate_premium_discount,
    detect_liquidity_sweep,
    find_equal_highs,
    find_equal_lows,
    is_in_discount,
    is_in_premium,
)
from src.strategies.modules.detectors.market_structure import get_current_trend
from src.strategies.modules.detectors.order_block import (
    find_nearest_ob,
    get_ob_zone,
    identify_bearish_ob,
    identify_bullish_ob,
)
from src.strategies.modules.detectors.smc import (
    detect_displacement,
    detect_inducement,
    find_mitigation_zone,
)
from src.strategies.modules.base.entry import EntryContext, EntryDecision, EntryDeterminer
from src.models.module_requirements import ModuleRequirements
from src.models.signal import SignalType


@register_module(
    'entry', 'ict_optimal_entry',
    description='ICT(Inner Circle Trader) 기반 최적 진입 결정자',
    compatible_with={
        'stop_loss': ['zone_based_sl', 'fixed_percent_sl'],
        'take_profit': ['displacement_tp', 'fixed_rr_tp'],
        'exit': ['ict_dynamic_exit', 'null_exit'],
    }
)
@dataclass
class ICTOptimalEntryDeterminer(EntryDeterminer):
    """
    ICT entry determination using Smart Money Concepts.
    """

    class ParamSchema(BaseModel):
        """Pydantic schema for ICT entry parameters (Cold Path validation)."""
        active_profile: str = Field("balanced", description="ICT 프로필 (strict/balanced/aggressive)")
        swing_lookback: int = Field(10, ge=5, le=50, description="스윙 탐색 범위")
        ltf_interval: str = Field("1m", description="Low Timeframe 인터벌")
        mtf_interval: str = Field("5m", description="Mid Timeframe 인터벌")
        htf_interval: str = Field("15m", description="High Timeframe 인터벌")
        fvg_min_gap_percent: float = Field(0.001, ge=0.0001, le=0.01, description="FVG 최소 갭 %")
        ob_min_strength: float = Field(1.5, ge=0.1, le=5.0, description="Order Block 최소 강도")
        use_killzones: bool = Field(True, description="킬존 시간대 필터 사용")

    @classmethod
    def from_validated_params(cls, params: "ICTOptimalEntryDeterminer.ParamSchema") -> "ICTOptimalEntryDeterminer":
        """Create instance from Pydantic-validated params."""
        return cls.from_config(params.model_dump())

    # ICT parameters (profile defaults)
    swing_lookback: int = 5
    displacement_ratio: float = 1.5
    fvg_min_gap_percent: float = 0.001
    ob_min_strength: float = 1.5
    liquidity_tolerance: float = 0.001
    use_killzones: bool = True
    min_periods: int = 50

    # MTF interval names (set from config)
    ltf_interval: str = "1m"
    mtf_interval: str = "5m"
    htf_interval: str = "15m"

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

    @property
    def requirements(self) -> ModuleRequirements:
        """ICT entry needs 3 timeframes with sufficient history."""
        return ModuleRequirements(
            timeframes=frozenset({self.ltf_interval, self.mtf_interval, self.htf_interval}),
            min_candles={
                self.ltf_interval: self.min_periods,
                self.mtf_interval: 50,
                self.htf_interval: 50,
            },
        )

    @classmethod
    def from_config(cls, config: dict) -> "ICTOptimalEntryDeterminer":
        """
        Create ICTOptimalEntryDeterminer from strategy config dict with profile loading.
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
            ltf_interval=config.get("ltf_interval", "1m"),
            mtf_interval=config.get("mtf_interval", "5m"),
            htf_interval=config.get("htf_interval", "15m"),
        )

    def analyze(self, context: EntryContext) -> Optional[EntryDecision]:
        """
        Analyze market context using ICT methodology.
        """
        candle = context.candle

        # Step 1: Validate candle is closed
        if not candle.is_closed:
            return None

        # Get LTF buffer (primary analysis buffer)
        ltf_buffer = context.buffers.get(self.ltf_interval)
        if not ltf_buffer or len(ltf_buffer) < self.min_periods:
            self.logger.debug(f"Insufficient buffer for {self.ltf_interval}: {len(ltf_buffer) if ltf_buffer else 0}/{self.min_periods}")
            return None

        # Use MTF buffer for structure detection when available
        candle_buffer = ltf_buffer

        # Kill Zone Filter
        if self.use_killzones:
            if not is_killzone_active(candle.open_time):
                self.logger.debug(f"Outside Killzone: {candle.open_time}")
                return None

        # Step 2: Trend Analysis (Market Structure)
        trend = None
        if context.feature_store is not None:
            htf_structure = context.feature_store.get_market_structure(
                self.htf_interval
            )
            mtf_structure = context.feature_store.get_market_structure(
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
            self.logger.debug(f"Trend is {trend} (required: bullish/bearish)")
            return None

        # Step 3: Premium/Discount Zone
        range_low, range_mid, range_high = calculate_premium_discount(
            candle_buffer, lookback=50
        )
        current_price = candle.close

        # Step 4: FVG/OB Detection
        mtf_interval = self.mtf_interval
        if context.feature_store is not None:
            bullish_fvgs_cached = context.feature_store.get_active_fvgs(
                mtf_interval, "bullish"
            )
            bearish_fvgs_cached = context.feature_store.get_active_fvgs(
                mtf_interval, "bearish"
            )
            bullish_obs_cached = context.feature_store.get_active_order_blocks(
                mtf_interval, "bullish"
            )
            bearish_obs_cached = context.feature_store.get_active_order_blocks(
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
        if context.feature_store is None:
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

                self.logger.info(
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

                price_extras = {
                    "fvg_zone": fvg_zone,
                    "ob_zone": ob_zone,
                    "displacement_size": displacement_size,
                }
                metadata = {
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
                    price_extras=price_extras,
                )
            else:
                 self.logger.debug(
                     f"LONG Conditions Fail: Inducement={recent_inducement}, "
                     f"Displacement={recent_displacement}, "
                     f"FVG/OB={has_fvg_ob}"
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

                self.logger.info(
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

                price_extras = {
                    "fvg_zone": fvg_zone,
                    "ob_zone": ob_zone,
                    "displacement_size": displacement_size,
                }
                metadata = {
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
                    price_extras=price_extras,
                )
            else:
                 self.logger.debug(
                     f"SHORT Conditions Fail: Inducement={recent_inducement}, "
                     f"Displacement={recent_displacement}, "
                     f"FVG/OB={has_fvg_ob}"
                 )
        else:
             self.logger.debug(
                 f"Zone/Trend Fail: Trend={trend}, "
                 f"InDiscount={is_in_discount(current_price, range_low, range_high)}, "
                 f"InPremium={is_in_premium(current_price, range_low, range_high)}"
             )

        return None
