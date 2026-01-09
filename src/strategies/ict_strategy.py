"""
ICT (Inner Circle Trader) Strategy

Comprehensive strategy implementing ICT concepts:
- Market Structure (BOS, CHoCH, trend)
- Fair Value Gaps (FVG)
- Order Blocks (OB)
- Liquidity Pools (BSL, SSL)
- Smart Money Concepts (inducement, displacement, mitigation)
- Kill Zones (time-based filters)
"""

from datetime import datetime, timezone
from typing import Optional

# ICT Fair Value Gap
from src.indicators.ict_fvg import (
    detect_bearish_fvg,
    detect_bullish_fvg,
    find_nearest_fvg,
    get_entry_zone,
)

# ICT Kill Zones
from src.indicators.ict_killzones import get_active_killzone, is_killzone_active

# ICT Liquidity
from src.indicators.ict_liquidity import (
    calculate_premium_discount,
    detect_liquidity_sweep,
    find_equal_highs,
    find_equal_lows,
    is_in_discount,
    is_in_premium,
)

# ICT Market Structure
from src.indicators.ict_market_structure import (
    get_current_trend,
)

# ICT Order Block
from src.indicators.ict_order_block import (
    find_nearest_ob,
    get_ob_zone,
    identify_bearish_ob,
    identify_bullish_ob,
)

# ICT Smart Money Concepts
from src.indicators.ict_smc import detect_displacement, detect_inducement, find_mitigation_zone
from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy

# ICT Profile System
from src.config.ict_profiles import get_profile_parameters, load_profile_from_name


class ICTStrategy(BaseStrategy):
    """
    ICT trading strategy using Smart Money Concepts.

    10-Step Analysis Process:
    1. Kill Zone Filter: Only trade during London/NY sessions
    2. Trend Analysis: Identify overall market structure (BOS, CHoCH)
    3. Premium/Discount: Determine value zone
    4. FVG/OB Detection: Find imbalances and institutional order blocks
    5. Liquidity Analysis: Identify BSL/SSL levels
    6. Inducement Check: Look for fake moves trapping retail
    7. Displacement: Confirm smart money activity
    8. Entry Timing: Enter on mitigation of FVG/OB in discount (long) or premium (short)
    9. TP Calculation: Target next liquidity pool or displacement extension
    10. SL Calculation: Below/above FVG or OB zone

    Configuration Parameters:
    - buffer_size: Historical candles to store (default: 200)
    - swing_lookback: Candles for swing detection (default: 5)
    - displacement_ratio: Minimum displacement strength (default: 1.5)
    - fvg_min_gap_percent: Minimum FVG gap size (default: 0.001)
    - ob_min_strength: Minimum OB strength (default: 1.5)
    - liquidity_tolerance: Price tolerance for equal highs/lows (default: 0.001)
    - rr_ratio: Risk-reward ratio for TP (default: 2.0)
    - use_killzones: Filter by kill zones (default: True)
    """

    def __init__(self, symbol: str, config: dict) -> None:
        """
        Initialize ICT strategy with profile-based parameter loading.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            config: Strategy configuration dictionary

        Configuration Loading:
            1. Load active_profile from config (default: "strict")
            2. Load profile parameters as defaults
            3. Override with explicit config values if provided
        """
        super().__init__(symbol, config)

        # Load profile-based parameters
        profile_name = config.get("active_profile", "strict")

        try:
            profile = load_profile_from_name(profile_name)
            profile_params = get_profile_parameters(profile)

            self.logger.info(
                f"Loading ICT profile: {profile_name.upper()} "
                f"(Expected: {profile_params.get('signal_frequency', 'unknown')} signals/week)"
            )

            # Store active profile name
            self.active_profile = profile_name

        except ValueError as e:
            self.logger.warning(
                f"Invalid profile '{profile_name}': {e}. Using strict defaults."
            )
            profile_params = {}
            self.active_profile = "strict"

        # ICT-specific parameters (profile defaults + config overrides)
        self.swing_lookback = config.get(
            "swing_lookback", profile_params.get("swing_lookback", 5)
        )
        self.displacement_ratio = config.get(
            "displacement_ratio", profile_params.get("displacement_ratio", 1.5)
        )
        self.fvg_min_gap_percent = config.get(
            "fvg_min_gap_percent", profile_params.get("fvg_min_gap_percent", 0.001)
        )
        self.ob_min_strength = config.get(
            "ob_min_strength", profile_params.get("ob_min_strength", 1.5)
        )
        self.liquidity_tolerance = config.get(
            "liquidity_tolerance", profile_params.get("liquidity_tolerance", 0.001)
        )
        self.rr_ratio = config.get("rr_ratio", profile_params.get("rr_ratio", 2.0))
        self.use_killzones = config.get("use_killzones", True)

        # Log loaded parameters
        self.logger.info(
            f"ICT Parameters: swing_lookback={self.swing_lookback}, "
            f"displacement_ratio={self.displacement_ratio}, "
            f"fvg_min_gap={self.fvg_min_gap_percent}, "
            f"ob_min_strength={self.ob_min_strength}, "
            f"liquidity_tolerance={self.liquidity_tolerance}"
        )

        # Minimum buffer size for ICT analysis
        self.min_periods = max(50, self.swing_lookback * 4)

        # Condition statistics tracking (for tuning analysis)
        self.condition_stats = {
            "total_checks": 0,
            "killzone_ok": 0,
            "trend_ok": 0,
            "zone_ok": 0,
            "fvg_ob_ok": 0,
            "inducement_ok": 0,
            "displacement_ok": 0,
            "all_conditions_ok": 0,
            "signals_generated": 0,
        }

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle using ICT methodology.

        10-Step ICT Analysis:
        1. Kill Zone Filter
        2. Trend Analysis
        3. Premium/Discount Zone
        4. FVG/OB Detection
        5. Liquidity Analysis
        6. Inducement Check
        7. Displacement Confirmation
        8. Entry Timing
        9. TP Calculation
        10. SL Calculation

        Args:
            candle: Latest candle to analyze

        Returns:
            Signal if ICT conditions met, None otherwise
        """
        # Validate candle is closed
        if not candle.is_closed:
            return None

        # Update buffer
        self.update_buffer(candle)

        # Check sufficient data
        if not self.is_buffer_ready(self.min_periods):
            self.logger.debug(f"Buffer not ready: {len(self.candle_buffer)}/{self.min_periods}")
            return None

        if self.use_killzones:
            if not is_killzone_active(candle.open_time):
                self.logger.debug(f"Outside Killzone: {candle.open_time}")
                return None  # Outside optimal trading times

        # Step 2: Trend Analysis (Market Structure)
        trend = get_current_trend(self.candle_buffer, swing_lookback=self.swing_lookback)

        if trend is None:
            self.logger.debug(f"No clear trend detected (swing_lookback={self.swing_lookback})")
            return None  # No clear trend

        # Step 3: Premium/Discount Zone
        range_low, range_mid, range_high = calculate_premium_discount(
            self.candle_buffer, lookback=50
        )

        current_price = candle.close

        # Step 4: FVG/OB Detection
        bullish_fvgs = detect_bullish_fvg(
            self.candle_buffer, min_gap_percent=self.fvg_min_gap_percent
        )
        bearish_fvgs = detect_bearish_fvg(
            self.candle_buffer, min_gap_percent=self.fvg_min_gap_percent
        )

        bullish_obs, bearish_obs = (
            identify_bullish_ob(self.candle_buffer, displacement_ratio=self.displacement_ratio),
            identify_bearish_ob(self.candle_buffer, displacement_ratio=self.displacement_ratio),
        )

        # Filter OBs by strength
        bullish_obs = [ob for ob in bullish_obs if ob.strength >= self.ob_min_strength]
        bearish_obs = [ob for ob in bearish_obs if ob.strength >= self.ob_min_strength]

        # Step 5: Liquidity Analysis
        equal_highs = find_equal_highs(
            self.candle_buffer, tolerance_percent=self.liquidity_tolerance, lookback=20
        )
        equal_lows = find_equal_lows(
            self.candle_buffer, tolerance_percent=self.liquidity_tolerance, lookback=20
        )

        detect_liquidity_sweep(self.candle_buffer, equal_highs + equal_lows)

        # Step 6: Inducement Check
        inducements = detect_inducement(self.candle_buffer, lookback=10)

        # Step 7: Displacement Confirmation
        displacements = detect_displacement(
            self.candle_buffer, displacement_ratio=self.displacement_ratio
        )

        # Step 8: Entry Timing - Look for mitigation of FVG/OB
        _mitigations = find_mitigation_zone(
            self.candle_buffer, fvgs=bullish_fvgs + bearish_fvgs, obs=bullish_obs + bearish_obs
        )

        # Condition tracking for tuning analysis
        self.condition_stats["total_checks"] += 1

        # Track killzone condition
        in_killzone = not self.use_killzones or is_killzone_active(candle.open_time)
        if in_killzone:
            self.condition_stats["killzone_ok"] += 1

        # Track trend condition
        has_trend = trend is not None
        if has_trend:
            self.condition_stats["trend_ok"] += 1

        # LONG Entry Logic
        if trend == "bullish" and is_in_discount(current_price, range_low, range_high):
            # Track zone condition (LONG: discount)
            self.condition_stats["zone_ok"] += 1

            # Check for bullish FVG or OB nearby (prefer those BELOW current price for support)
            # Mitigation means price is dipping INTO the zone from above
            candidate_fvgs = [f for f in bullish_fvgs if f.gap_low < current_price]
            candidate_obs = [ob for ob in bullish_obs if ob.low < current_price]
            
            nearest_fvg = find_nearest_fvg(candidate_fvgs, current_price, direction="bullish")
            nearest_ob = find_nearest_ob(candidate_obs, current_price, direction="bullish")

            # Track FVG/OB condition
            has_fvg_ob = nearest_fvg is not None or nearest_ob is not None
            if has_fvg_ob:
                self.condition_stats["fvg_ob_ok"] += 1

            # Check for recent inducement (bearish fake move)
            recent_inducement = any(
                ind.direction == "bearish" for ind in inducements[-3:] if inducements
            )

            # Track inducement condition
            if recent_inducement:
                self.condition_stats["inducement_ok"] += 1

            # Check for recent displacement (bullish move)
            recent_displacement = any(
                disp.direction == "bullish" for disp in displacements[-3:] if displacements
            )

            # Track displacement condition
            if recent_displacement:
                self.condition_stats["displacement_ok"] += 1

            # Entry conditions:
            # 1. In discount zone (value)
            # 2. Recent bearish inducement (trapped shorts)
            # 3. Recent bullish displacement (smart money buying)
            # 4. Near bullish FVG or OB (mitigation zone)
            if recent_inducement and recent_displacement and (nearest_fvg or nearest_ob):
                # All conditions met
                self.condition_stats["all_conditions_ok"] += 1
                self.condition_stats["signals_generated"] += 1

                # Log detailed condition state
                self.logger.debug(
                    f"ICT LONG Signal: trend={trend}, zone=discount, "
                    f"fvg={nearest_fvg is not None}, ob={nearest_ob is not None}, "
                    f"inducement={recent_inducement}, displacement={recent_displacement}"
                )
                entry_price = candle.close
                side = "LONG"

                # Calculate TP (next BSL or displacement extension)
                take_profit = self.calculate_take_profit(entry_price, side)

                # Calculate SL (below FVG/OB zone)
                stop_loss = self.calculate_stop_loss(entry_price, side, nearest_fvg, nearest_ob)

                return Signal(
                    signal_type=SignalType.LONG_ENTRY,
                    symbol=self.symbol,
                    entry_price=entry_price,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    strategy_name=self.__class__.__name__,
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        "trend": trend,
                        "zone": "discount",
                        "killzone": (
                            get_active_killzone(candle.open_time) if self.use_killzones else None
                        ),
                        "fvg_present": nearest_fvg is not None,
                        "ob_present": nearest_ob is not None,
                        "inducement": recent_inducement,
                        "displacement": recent_displacement,
                    },
                )

        # SHORT Entry Logic
        elif trend == "bearish" and is_in_premium(current_price, range_low, range_high):
            # Track zone condition (SHORT: premium)
            self.condition_stats["zone_ok"] += 1

            # Check for bearish FVG or OB nearby (prefer those ABOVE current price for resistance)
            # Mitigation means price is rising INTO the zone from below
            candidate_fvgs = [f for f in bearish_fvgs if f.gap_high > current_price]
            candidate_obs = [ob for ob in bearish_obs if ob.high > current_price]
            
            nearest_fvg = find_nearest_fvg(candidate_fvgs, current_price, direction="bearish")
            nearest_ob = find_nearest_ob(candidate_obs, current_price, direction="bearish")

            # Track FVG/OB condition
            has_fvg_ob = nearest_fvg is not None or nearest_ob is not None
            if has_fvg_ob:
                self.condition_stats["fvg_ob_ok"] += 1

            # Check for recent inducement (bullish fake move)
            recent_inducement = any(
                ind.direction == "bullish" for ind in inducements[-3:] if inducements
            )

            # Track inducement condition
            if recent_inducement:
                self.condition_stats["inducement_ok"] += 1

            # Check for recent displacement (bearish move)
            recent_displacement = any(
                disp.direction == "bearish" for disp in displacements[-3:] if displacements
            )

            # Track displacement condition
            if recent_displacement:
                self.condition_stats["displacement_ok"] += 1

            # Entry conditions:
            # 1. In premium zone (expensive)
            # 2. Recent bullish inducement (trapped longs)
            # 3. Recent bearish displacement (smart money selling)
            # 4. Near bearish FVG or OB (mitigation zone)
            if recent_inducement and recent_displacement and (nearest_fvg or nearest_ob):
                # All conditions met
                self.condition_stats["all_conditions_ok"] += 1
                self.condition_stats["signals_generated"] += 1

                # Log detailed condition state
                self.logger.debug(
                    f"ICT SHORT Signal: trend={trend}, zone=premium, "
                    f"fvg={nearest_fvg is not None}, ob={nearest_ob is not None}, "
                    f"inducement={recent_inducement}, displacement={recent_displacement}"
                )
                entry_price = candle.close
                side = "SHORT"

                # Calculate TP (next SSL or displacement extension)
                take_profit = self.calculate_take_profit(entry_price, side)

                # Calculate SL (above FVG/OB zone)
                stop_loss = self.calculate_stop_loss(entry_price, side, nearest_fvg, nearest_ob)

                return Signal(
                    signal_type=SignalType.SHORT_ENTRY,
                    symbol=self.symbol,
                    entry_price=entry_price,
                    take_profit=take_profit,
                    stop_loss=stop_loss,
                    strategy_name=self.__class__.__name__,
                    timestamp=datetime.now(timezone.utc),
                    metadata={
                        "trend": trend,
                        "zone": "premium",
                        "killzone": (
                            get_active_killzone(candle.open_time) if self.use_killzones else None
                        ),
                        "fvg_present": nearest_fvg is not None,
                        "ob_present": nearest_ob is not None,
                        "inducement": recent_inducement,
                        "displacement": recent_displacement,
                    },
                )

        # Log condition state when no signal generated (DEBUG level)
        self.logger.debug(
            f"ICT Conditions Check: trend={trend}, "
            f"use_killzones={self.use_killzones}, "
            f"is_killzone={is_killzone_active(candle.open_time)}, "
            f"in_zone={(trend == 'bullish' and is_in_discount(current_price, range_low, range_high)) or (trend == 'bearish' and is_in_premium(current_price, range_low, range_high))}, "
            f"fvgs={len(bullish_fvgs) + len(bearish_fvgs)}, "
            f"obs={len(bullish_obs) + len(bearish_obs)}, "
            f"inducements={len(inducements)}, "
            f"displacements={len(displacements)} - No signal"
        )

        return None

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit using risk-reward ratio.

        TP is calculated as entry +/- (risk * rr_ratio).

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Take profit price
        """
        # Get recent displacement for risk calculation
        displacements = detect_displacement(
            self.candle_buffer, displacement_ratio=self.displacement_ratio
        )

        if displacements:
            # Use last displacement size as base risk
            last_disp = displacements[-1]
            risk_amount = last_disp.size
        else:
            # Fallback: Use 2% of entry price as risk
            risk_amount = entry_price * 0.02

        reward_amount = risk_amount * self.rr_ratio

        if side == "LONG":
            tp = entry_price + reward_amount
            # Safety: TP must be > entry_price
            return tp if tp > entry_price else entry_price * 1.02
        else:  # SHORT
            tp = entry_price - reward_amount
            # Safety: TP must be < entry_price
            return tp if tp < entry_price else entry_price * 0.98

    def calculate_stop_loss(
        self, entry_price: float, side: str, nearest_fvg=None, nearest_ob=None
    ) -> float:
        """
        Calculate stop loss below/above FVG or OB zone.

        SL is placed below the FVG/OB zone (for longs) or above (for shorts)
        to avoid premature stops during mitigation.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'
            nearest_fvg: Nearest FVG object (optional)
            nearest_ob: Nearest OB object (optional)

        Returns:
            Stop loss price
        """
        # Try to use FVG/OB zone for SL
        if nearest_fvg:
            zone_low, zone_high = get_entry_zone(nearest_fvg)
        elif nearest_ob:
            zone_low, zone_high = get_ob_zone(nearest_ob)
        else:
            # Fallback: Use 1% of entry price
            if side == "LONG":
                return entry_price * 0.99
            else:  # SHORT
                return entry_price * 1.01

        # Place SL below/above zone with small buffer
        buffer = entry_price * 0.001  # 0.1% buffer

        if side == "LONG":
            # SL below FVG/OB zone
            sl = zone_low - buffer
            # Safety: SL must be < entry_price
            return sl if sl < entry_price else entry_price * 0.99
        else:  # SHORT
            # SL above FVG/OB zone
            sl = zone_high + buffer
            # Safety: SL must be > entry_price
            return sl if sl > entry_price else entry_price * 1.01

    def get_condition_stats(self) -> dict:
        """
        Get condition statistics for tuning analysis.

        Returns:
            Dictionary with condition success rates
        """
        total = self.condition_stats["total_checks"]
        if total == 0:
            return self.condition_stats.copy()

        stats = self.condition_stats.copy()
        stats["success_rates"] = {
            "killzone_rate": stats["killzone_ok"] / total if total > 0 else 0,
            "trend_rate": stats["trend_ok"] / total if total > 0 else 0,
            "zone_rate": stats["zone_ok"] / total if total > 0 else 0,
            "fvg_ob_rate": stats["fvg_ob_ok"] / total if total > 0 else 0,
            "inducement_rate": stats["inducement_ok"] / total if total > 0 else 0,
            "displacement_rate": stats["displacement_ok"] / total if total > 0 else 0,
            "all_conditions_rate": stats["all_conditions_ok"] / total if total > 0 else 0,
            "signal_rate": stats["signals_generated"] / total if total > 0 else 0,
        }
        return stats

    def reset_condition_stats(self) -> None:
        """Reset condition statistics to zero."""
        for key in self.condition_stats:
            self.condition_stats[key] = 0
