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

import logging
from datetime import datetime, timezone
from typing import Optional

# Detection indicator cache (Issue #19)
from src.strategies.indicator_cache import IndicatorStateCache

# ICT Fair Value Gap
from src.detectors.ict_fvg import (
    detect_bearish_fvg,
    detect_bullish_fvg,
    find_nearest_fvg,
    get_entry_zone,
)

# ICT Kill Zones
from src.detectors.ict_killzones import get_active_killzone, is_killzone_active

# ICT Liquidity
from src.detectors.ict_liquidity import (
    calculate_premium_discount,
    detect_liquidity_sweep,
    find_equal_highs,
    find_equal_lows,
    is_in_discount,
    is_in_premium,
)

# ICT Market Structure
from src.detectors.ict_market_structure import (
    get_current_trend,
)

# ICT Order Block
from src.detectors.ict_order_block import (
    find_nearest_ob,
    get_ob_zone,
    identify_bearish_ob,
    identify_bullish_ob,
)

# ICT Smart Money Concepts
from src.detectors.ict_smc import (
    detect_displacement,
    detect_inducement,
    find_mitigation_zone,
)
from src.models.candle import Candle
from src.models.position import Position
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
        Initialize ICT strategy with profile-based parameter loading and MTF structure.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            config: Strategy configuration dictionary

        Configuration Loading:
            1. Load active_profile from config (default: "strict")
            2. Load profile parameters as defaults
            3. Override with explicit config values if provided

        Multi-Timeframe Structure (Issue #7):
            - HTF (High Timeframe): Trend analysis (default: 4h)
            - MTF (Medium Timeframe): Structure detection (default: 1h)
            - LTF (Low Timeframe): Entry timing (default: 5m)
        """
        # Configure MTF intervals
        ltf_interval = config.get("ltf_interval", "5m")
        mtf_interval = config.get("mtf_interval", "1h")
        htf_interval = config.get("htf_interval", "4h")

        intervals = [ltf_interval, mtf_interval, htf_interval]

        # Initialize BaseStrategy with intervals
        super().__init__(symbol, config, intervals=intervals)

        # Store interval assignments for analysis
        self.ltf_interval = ltf_interval
        self.mtf_interval = mtf_interval
        self.htf_interval = htf_interval

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

        # Initialize indicator cache for pre-computed indicators (Issue #19)
        # This enables O(f+k) incremental updates vs O(n) full recalculation
        use_indicator_cache = config.get("use_indicator_cache", True)
        if use_indicator_cache:
            indicator_cache_config = {
                "max_order_blocks": config.get("max_order_blocks", 20),
                "max_fvgs": config.get("max_fvgs", 15),
                "displacement_ratio": self.displacement_ratio,
                "fvg_min_gap_percent": self.fvg_min_gap_percent,
                "indicator_expiry_candles": config.get("indicator_expiry_candles", 100),
            }
            cache = IndicatorStateCache(config=indicator_cache_config)
            self.set_indicator_cache(cache)
            self.logger.info(
                f"[{self.__class__.__name__}] Indicator cache enabled for {self.symbol}"
            )

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Analyze candle using ICT methodology with Multi-Timeframe structure (Issue #47).

        10-Step ICT Analysis:
        1. Kill Zone Filter
        2. Trend Analysis (HTF buffer)
        3. Premium/Discount Zone (MTF buffer)
        4. FVG/OB Detection (MTF buffer)
        5. Liquidity Analysis (MTF buffer)
        6. Inducement Check (LTF buffer)
        7. Displacement Confirmation (LTF buffer)
        8. Entry Timing (LTF buffer)
        9. TP Calculation
        10. SL Calculation

        Args:
            candle: Latest candle to analyze (typically LTF)

        Returns:
            Signal if ICT conditions met, None otherwise

        Note:
            Uses pre-computed detectors from LTF/MTF buffers. High-conviction
            setups require agreement across multiple detectors.
        """
        # 1. Validate candle is closed
        if not candle.is_closed:
            return None

        # 2. Update buffer with new candle
        self.update_buffer(candle)

        # 3. Update indicator cache if available
        self._update_feature_cache(candle)

        # 4. Check if all intervals ready
        if not self.is_ready():
            return None

        # 5. Get LTF buffer (primary analysis buffer for now)
        ltf_buffer = self.buffers.get(self.ltf_interval)
        if not ltf_buffer or len(ltf_buffer) < self.min_periods:
            self.logger.debug(
                f"LTF buffer not ready: {len(ltf_buffer) if ltf_buffer else 0}/{self.min_periods}"
            )
            return None

        # Use MTF buffer for structure detection when available
        mtf_buffer = self.buffers.get(self.mtf_interval)
        candle_buffer = ltf_buffer

        if self.use_killzones:
            if not is_killzone_active(candle.open_time):
                self.logger.debug(f"Outside Killzone: {candle.open_time}")
                return None  # Outside optimal trading times

        # Step 2: Trend Analysis (Market Structure)
        # Use indicator cache for trend if available (Issue #19)
        trend = None
        if self._indicator_cache is not None:
            htf_structure = self._indicator_cache.get_market_structure(
                self.htf_interval
            )
            mtf_structure = self._indicator_cache.get_market_structure(
                self.mtf_interval
            )
            # Prefer HTF trend, fall back to MTF
            if htf_structure:
                trend = htf_structure.trend
            elif mtf_structure:
                trend = mtf_structure.trend

        # Fallback to original calculation if cache unavailable
        if trend is None:
            trend = get_current_trend(candle_buffer, swing_lookback=self.swing_lookback)

        if trend is None or trend == "sideways":
            self.logger.debug(
                f"[{self.symbol}] No clear trend detected (swing_lookback={self.swing_lookback})"
            )
            return None  # No clear trend

        # Step 3: Premium/Discount Zone
        range_low, range_mid, range_high = calculate_premium_discount(
            candle_buffer, lookback=50
        )

        current_price = candle.close

        # Step 4: FVG/OB Detection - Use indicator cache if available (Issue #19)
        mtf_interval = self.mtf_interval
        if self._indicator_cache is not None:
            # Use pre-computed indicators from cache (O(f) lookup)
            bullish_fvgs_cached = self._indicator_cache.get_active_fvgs(
                mtf_interval, "bullish"
            )
            bearish_fvgs_cached = self._indicator_cache.get_active_fvgs(
                mtf_interval, "bearish"
            )
            bullish_obs_cached = self._indicator_cache.get_active_order_blocks(
                mtf_interval, "bullish"
            )
            bearish_obs_cached = self._indicator_cache.get_active_order_blocks(
                mtf_interval, "bearish"
            )

            # Convert cached indicators to legacy format for compatibility
            # Note: Cached OBs already have strength filtering applied at detection
            bullish_fvgs = bullish_fvgs_cached
            bearish_fvgs = bearish_fvgs_cached
            bullish_obs = [
                ob for ob in bullish_obs_cached if ob.strength >= self.ob_min_strength
            ]
            bearish_obs = [
                ob for ob in bearish_obs_cached if ob.strength >= self.ob_min_strength
            ]
        else:
            # Fallback: Full recalculation (O(n) per call)
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

            # Filter OBs by strength
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

        # Step 8: Entry Timing - Look for mitigation of FVG/OB
        # Skip when using indicator cache (cache handles status updates internally,
        # and cached FVGs are immutable so find_mitigation_zone would fail)
        if self._indicator_cache is None:
            _mitigations = find_mitigation_zone(
                candle_buffer,
                fvgs=bullish_fvgs + bearish_fvgs,
                obs=bullish_obs + bearish_obs,
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

            nearest_fvg = find_nearest_fvg(
                candidate_fvgs, current_price, direction="bullish"
            )
            nearest_ob = find_nearest_ob(
                candidate_obs, current_price, direction="bullish"
            )

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
                disp.direction == "bullish"
                for disp in displacements[-3:]
                if displacements
            )

            # Track displacement condition
            if recent_displacement:
                self.condition_stats["displacement_ok"] += 1

            # Entry conditions:
            # 1. In discount zone (value)
            # 2. Recent bearish inducement (trapped shorts)
            # 3. Recent bullish displacement (smart money buying)
            # 4. Near bullish FVG or OB (mitigation zone)
            if (
                recent_inducement
                and recent_displacement
                and (nearest_fvg or nearest_ob)
            ):
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
                take_profit = self._calculate_take_profit_with_buffer(
                    entry_price, side, list(candle_buffer)
                )

                # Calculate SL (below FVG/OB zone)
                stop_loss = self._calculate_stop_loss_with_indicators(
                    entry_price, side, nearest_fvg, nearest_ob
                )

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
                            get_active_killzone(candle.open_time)
                            if self.use_killzones
                            else None
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

            nearest_fvg = find_nearest_fvg(
                candidate_fvgs, current_price, direction="bearish"
            )
            nearest_ob = find_nearest_ob(
                candidate_obs, current_price, direction="bearish"
            )

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
                disp.direction == "bearish"
                for disp in displacements[-3:]
                if displacements
            )

            # Track displacement condition
            if recent_displacement:
                self.condition_stats["displacement_ok"] += 1

            # Entry conditions:
            # 1. In premium zone (expensive)
            # 2. Recent bullish inducement (trapped longs)
            # 3. Recent bearish displacement (smart money selling)
            # 4. Near bearish FVG or OB (mitigation zone)
            if (
                recent_inducement
                and recent_displacement
                and (nearest_fvg or nearest_ob)
            ):
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
                take_profit = self._calculate_take_profit_with_buffer(
                    entry_price, side, list(candle_buffer)
                )

                # Calculate SL (above FVG/OB zone)
                stop_loss = self._calculate_stop_loss_with_indicators(
                    entry_price, side, nearest_fvg, nearest_ob
                )

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
                            get_active_killzone(candle.open_time)
                            if self.use_killzones
                            else None
                        ),
                        "fvg_present": nearest_fvg is not None,
                        "ob_present": nearest_ob is not None,
                        "inducement": recent_inducement,
                        "displacement": recent_displacement,
                    },
                )

        # Log condition state when no signal generated (DEBUG level)
        self.logger.debug(
            f"[{self.symbol}] ICT Conditions Check: trend={trend}, "
            f"use_killzones={self.use_killzones}, "
            f"is_killzone={is_killzone_active(candle.open_time)}, "
            f"in_zone={(trend == 'bullish' and is_in_discount(current_price, range_low, range_high)) or (trend == 'bearish' and is_in_premium(current_price, range_low, range_high))}, "
            f"fvgs={len(bullish_fvgs) + len(bearish_fvgs)}, "
            f"obs={len(bullish_obs) + len(bearish_obs)}, "
            f"inducements={len(inducements)}, "
            f"displacements={len(displacements)} - No signal"
        )

        return None

    def _calculate_take_profit_with_buffer(
        self, entry_price: float, side: str, candle_buffer: list
    ) -> float:
        """
        Calculate take profit using risk-reward ratio with candle buffer.

        TP is calculated as entry +/- (risk * rr_ratio).

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'
            candle_buffer: Candle buffer for displacement calculation

        Returns:
            Take profit price
        """
        # Get recent displacement for risk calculation
        displacements = detect_displacement(
            candle_buffer, displacement_ratio=self.displacement_ratio
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

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """
        Calculate take profit using risk-reward ratio.

        Uses LTF buffer from self.buffers for displacement calculation.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Take profit price
        """
        ltf_buffer = self.buffers.get(self.ltf_interval)
        if ltf_buffer:
            return self._calculate_take_profit_with_buffer(
                entry_price, side, list(ltf_buffer)
            )
        else:
            # Fallback: Use 2% of entry price as risk
            risk_amount = entry_price * 0.02
            reward_amount = risk_amount * self.rr_ratio

            if side == "LONG":
                tp = entry_price + reward_amount
                return tp if tp > entry_price else entry_price * 1.02
            else:  # SHORT
                tp = entry_price - reward_amount
                return tp if tp < entry_price else entry_price * 0.98

    def _calculate_stop_loss_with_indicators(
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

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """
        Calculate stop loss using 1% of entry price.

        This is a simplified version for compatibility with BaseStrategy.
        For FVG/OB-based SL, use _calculate_stop_loss_with_indicators.

        Args:
            entry_price: Position entry price
            side: 'LONG' or 'SHORT'

        Returns:
            Stop loss price
        """
        if side == "LONG":
            return entry_price * 0.99
        else:  # SHORT
            return entry_price * 1.01

    def get_condition_stats(self) -> dict:
        """
        Get condition statistics for tuning analysis.

        Returns:
            Dictionary with condition success rates
        """
        total = self.condition_stats["total_checks"]
        if total == 0:
            return self.condition_stats.copy()

        success_rates = {
            "killzone_rate": self.condition_stats["killzone_ok"] / total
            if total > 0
            else 0,
            "trend_rate": self.condition_stats["trend_ok"] / total if total > 0 else 0,
            "zone_rate": self.condition_stats["zone_ok"] / total if total > 0 else 0,
            "fvg_ob_rate": self.condition_stats["fvg_ob_ok"] / total
            if total > 0
            else 0,
            "inducement_rate": self.condition_stats["inducement_ok"] / total
            if total > 0
            else 0,
            "displacement_rate": self.condition_stats["displacement_ok"] / total
            if total > 0
            else 0,
            "all_conditions_rate": self.condition_stats["all_conditions_ok"] / total
            if total > 0
            else 0,
            "signal_rate": self.condition_stats["signals_generated"] / total
            if total > 0
            else 0,
        }

        stats = self.condition_stats.copy()
        stats["success_rates"] = success_rates  # type: ignore
        return stats

    def reset_condition_stats(self) -> None:
        """Reset condition statistics to zero."""
        for key in self.condition_stats:
            self.condition_stats[key] = 0

    def get_indicator_cache_stats(self) -> dict:
        """
        Get statistics about pre-computed indicators (Issue #19).

        Returns:
            Dictionary with indicator counts per interval,
            or empty dict if indicator cache not enabled.
        """
        if self._indicator_cache is None:
            return {}
        return self._indicator_cache.get_cache_stats()

    def is_indicator_cache_enabled(self) -> bool:
        """Check if indicator cache is enabled."""
        return self._indicator_cache is not None

    async def should_exit(self, position: Position, candle: Candle) -> Optional[Signal]:
        """
        Evaluate whether an open position should be exited using ICT dynamic exit logic.
        Implements 4 exit strategies based on ExitConfig:
        1. trailing_stop: Trailing stop with activation threshold
        2. breakeven: Move SL to entry when profitable
        3. timed: Exit after specified time period
        4. indicator_based: Exit based on ICT indicators reversal
        Args:
            position: Current open position for this symbol
            candle: Latest candle to analyze for exit conditions
        Returns:
            Signal with CLOSE_LONG/CLOSE_SHORT if exit triggered, None otherwise
        Integration with ICT Analysis:
            - Uses existing ICT 10-step analysis context
            - Leverages FVG, OB, liquidity, displacement detection
            - Maintains compatibility with existing ICT logic
            - Follows ICT Smart Money Concepts for exit timing
        """
        if not candle.is_closed:
            return None

        self.update_buffer(candle)
        self._update_feature_cache(candle)
        if not self.is_ready():
            return None

        # Get exit configuration from strategy
        exit_config = getattr(self.config, "exit_config", None)
        if not exit_config or not exit_config.dynamic_exit_enabled:
            return None  # Dynamic exit disabled

        buffer = self.buffers.get(candle.interval)
        if not buffer or len(buffer) < self.min_periods:
            return None

        # Route to appropriate exit strategy
        if exit_config.exit_strategy == "trailing_stop":
            return self._check_trailing_stop_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "breakeven":
            return self._check_breakeven_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "timed":
            return self._check_timed_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "indicator_based":
            return self._check_indicator_based_exit(position, candle, exit_config)
        else:
            self.logger.warning(
                f"[{self.symbol}] Unknown exit strategy: {exit_config.exit_strategy}"
            )
            return None

        self.update_buffer(candle)
        self._update_feature_cache(candle)

        if not self.is_ready():
            return None

        exit_config = getattr(self.config, "exit_config", None)
        if not exit_config or not exit_config.dynamic_exit_enabled:
            return None

        buffer = self.buffers.get(candle.interval)
        if not buffer or len(buffer) < self.min_periods:
            return None

        if exit_config.exit_strategy == "trailing_stop":
            return self._check_trailing_stop_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "breakeven":
            return self._check_breakeven_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "timed":
            return self._check_timed_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "indicator_based":
            return self._check_indicator_based_exit(position, candle, exit_config)
        else:
            self.logger.warning(
                f"[{self.symbol}] Unknown exit strategy: {exit_config.exit_strategy}"
            )
            return None

        # Get exit configuration from strategy
        exit_config = getattr(self.config, "exit_config", None)
        if not exit_config or not exit_config.dynamic_exit_enabled:
            return None  # Dynamic exit disabled

        buffer = self.buffers.get(candle.interval)
        if not buffer or len(buffer) < self.min_periods:
            return None

        # Route to appropriate exit strategy
        if exit_config.exit_strategy == "trailing_stop":
            return self._check_trailing_stop_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "breakeven":
            return self._check_breakeven_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "timed":
            return self._check_timed_exit(position, candle, exit_config)
        elif exit_config.exit_strategy == "indicator_based":
            return self._check_indicator_based_exit(position, candle, exit_config)
        else:
            self.logger.warning(
                f"[{self.symbol}] Unknown exit strategy: {exit_config.exit_strategy}"
            )
            return None

    def _check_trailing_stop_exit(
        self, position: "Position", candle: "Candle", exit_config
    ) -> Optional["Signal"]:
        """
        Check trailing stop exit conditions.

        Uses trailing_distance from entry price and trailing_activation threshold
        to protect profits while allowing room for normal fluctuations.

        Args:
            position: Current open position
            candle: Current candle
            exit_config: ExitConfig with trailing parameters

        Returns:
            CLOSE signal if trailing stop triggered, None otherwise
        """
        try:
            # Calculate trailing stop level
            if position.side == "LONG":
                # For long: stop below entry, moves up as price rises
                trailing_stop = position.entry_price * (
                    1 - exit_config.trailing_distance
                )

                # Move stop up if price is higher than activation threshold
                activation_price = position.entry_price * (
                    1 + exit_config.trailing_activation
                )
                if candle.close > activation_price:
                    # Update trailing stop to lock in profits
                    new_stop = candle.close * (1 - exit_config.trailing_distance)
                    if new_stop > trailing_stop:
                        trailing_stop = new_stop

                # Check if current price hit trailing stop
                if candle.close <= trailing_stop:
                    self.logger.info(
                        f"[{self.symbol}] Trailing stop exit triggered: "
                        f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                        f"stop={trailing_stop:.2f}"
                    )
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop",
                    )

            else:  # SHORT position
                # For short: stop above entry, moves down as price falls
                trailing_stop = position.entry_price * (
                    1 + exit_config.trailing_distance
                )

                # Move stop down if price is lower than activation threshold
                activation_price = position.entry_price * (
                    1 - exit_config.trailing_activation
                )
                if candle.close < activation_price:
                    # Update trailing stop to lock in profits
                    new_stop = candle.close * (1 + exit_config.trailing_distance)
                    if new_stop < trailing_stop:
                        trailing_stop = new_stop

                # Check if current price hit trailing stop
                if candle.close >= trailing_stop:
                    self.logger.info(
                        f"[{self.symbol}] Trailing stop exit triggered: "
                        f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                        f"stop={trailing_stop:.2f}"
                    )
                    return Signal(
                        signal_type=SignalType.CLOSE_SHORT,
                        symbol=self.symbol,
                        entry_price=candle.close,
                        strategy_name=self.__class__.__name__,
                        timestamp=datetime.now(timezone.utc),
                        exit_reason="trailing_stop",
                    )

        except Exception as e:
            self.logger.error(f"[{self.symbol}] Error in trailing stop check: {e}")
            return None

        return None

    def _check_breakeven_exit(
        self, position: "Position", candle: "Candle", exit_config
    ) -> Optional["Signal"]:
        """
        Check breakeven exit conditions.

        Moves stop loss to entry price (breakeven) when position becomes profitable
        by the configured offset, protecting against reversals.

        Args:
            position: Current open position
            candle: Current candle
            exit_config: ExitConfig with breakeven parameters

        Returns:
            CLOSE signal if price reverses after hitting breakeven, None otherwise
        """
        try:
            if not exit_config.breakeven_enabled:
                return None

            # Calculate breakeven level (entry price)
            breakeven_level = position.entry_price

            # Calculate activation threshold (when to move SL to breakeven)
            profit_threshold = position.entry_price * exit_config.breakeven_offset

            if position.side == "LONG":
                # Check if position is profitable enough to activate breakeven
                if candle.close > position.entry_price + profit_threshold:
                    # Move SL to breakeven level (entry price)
                    current_stop = position.entry_price * (
                        1 - exit_config.breakeven_offset
                    )

                    # Check if price reversed and hit breakeven stop
                    if candle.close <= breakeven_level:
                        self.logger.info(
                            f"[{self.symbol}] Breakeven exit triggered: "
                            f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                            f"breakeven={breakeven_level:.2f}"
                        )
                        return Signal(
                            signal_type=SignalType.CLOSE_LONG,
                            symbol=self.symbol,
                            entry_price=candle.close,
                            strategy_name=self.__class__.__name__,
                            timestamp=datetime.now(timezone.utc),
                            exit_reason="breakeven",
                        )

            else:  # SHORT position
                # Check if position is profitable enough to activate breakeven
                if candle.close < position.entry_price - profit_threshold:
                    # Move SL to breakeven level (entry price)
                    current_stop = position.entry_price * (
                        1 + exit_config.breakeven_offset
                    )

                    # Check if price reversed and hit breakeven stop
                    if candle.close >= breakeven_level:
                        self.logger.info(
                            f"[{self.symbol}] Breakeven exit triggered: "
                            f"entry={position.entry_price:.2f}, current={candle.close:.2f}, "
                            f"breakeven={breakeven_level:.2f}"
                        )
                        return Signal(
                            signal_type=SignalType.CLOSE_SHORT,
                            symbol=self.symbol,
                            entry_price=candle.close,
                            strategy_name=self.__class__.__name__,
                            timestamp=datetime.now(timezone.utc),
                            exit_reason="breakeven",
                        )

        except Exception as e:
            self.logger.error(f"[{self.symbol}] Error in breakeven check: {e}")
            return None

        return None

    def _check_timed_exit(
        self, position: "Position", candle: "Candle", exit_config
    ) -> Optional["Signal"]:
        """
        Check time-based exit conditions.

        Exits position after configured time period regardless of P&L,
        used for risk management and avoiding overexposure.

        Args:
            position: Current open position
            candle: Current candle
            exit_config: ExitConfig with timeout parameters

        Returns:
            CLOSE signal if timeout reached, None otherwise
        """
        try:
            if not exit_config.timeout_enabled or not position.entry_time:
                return None

            # Calculate time elapsed since entry
            elapsed_time = candle.open_time - position.entry_time
            timeout_duration = exit_config.timeout_minutes * 60  # Convert to seconds

            if elapsed_time.total_seconds() >= timeout_duration:
                self.logger.info(
                    f"[{self.symbol}] Time-based exit triggered: "
                    f"elapsed={elapsed_time}, timeout={exit_config.timeout_minutes}min"
                )
                signal_type = (
                    SignalType.CLOSE_LONG
                    if position.side == "LONG"
                    else SignalType.CLOSE_SHORT
                )
                return Signal(
                    signal_type=signal_type,
                    symbol=self.symbol,
                    entry_price=candle.close,
                    strategy_name=self.__class__.__name__,
                    timestamp=datetime.now(timezone.utc),
                    exit_reason="timed",
                )

        except Exception as e:
            self.logger.error(f"[{self.symbol}] Error in timed exit check: {e}")
            return None

        return None

    def _check_indicator_based_exit(
        self, position: "Position", candle: "Candle", exit_config
    ) -> Optional["Signal"]:
        """
        Check indicator-based exit conditions using ICT analysis.

        Uses ICT Smart Money Concepts to detect trend reversals and liquidity
        that warrant exiting positions before TP/SL are hit.

        Args:
            position: Current open position
            candle: Current candle
            exit_config: ExitConfig with indicator parameters

        Returns:
            CLOSE signal if ICT indicators show reversal, None otherwise
        """
        try:
            # Get ICT analysis context
            mtf_buffer = self.buffers.get(self.mtf_interval)
            if not mtf_buffer or len(mtf_buffer) < 50:
                return None

            # Get current trend from ICT analysis
            trend = None
            if self._indicator_cache is not None:
                htf_structure = self._indicator_cache.get_market_structure(
                    self.htf_interval
                )
                mtf_structure = self._indicator_cache.get_market_structure(
                    self.mtf_interval
                )
                trend = (
                    htf_structure.trend
                    if htf_structure and hasattr(htf_structure, "trend")
                    else (
                        mtf_structure.trend
                        if mtf_structure and hasattr(mtf_structure, "trend")
                        else None
                    )
                )
            else:
                trend = get_current_trend(
                    mtf_buffer, swing_lookback=self.swing_lookback
                )

            if trend is None:
                return None

            # Detect displacement reversal (smart money activity)
            displacements = detect_displacement(
                mtf_buffer, displacement_ratio=self.displacement_ratio
            )

            # Detect new inducement patterns
            inducements = detect_inducement(mtf_buffer, lookback=10)

            # Check for exit conditions based on ICT concepts
            should_exit_position = False
            exit_reason = None

            if position.side == "LONG":
                # Exit long if:
                # 1. Trend changes to bearish (CHoCH)
                if trend == "bearish":
                    should_exit_position = True
                    exit_reason = "htf_trend_reversal"

                # 2. Strong bearish displacement detected
                bearish_displacements = [
                    d for d in displacements if d.direction == "bearish"
                ]
                if bearish_displacements and len(bearish_displacements) >= 2:
                    should_exit_position = True
                    exit_reason = "bearish_displacement"

                # 3. Bullish inducement detected (trapped retail)
                recent_inducement = any(
                    ind.direction == "bullish"
                    for ind in inducements[-3:]
                    if inducements
                )
                if recent_inducement:
                    should_exit_position = True
                    exit_reason = "bullish_inducement"

            else:  # SHORT position
                # Exit short if:
                # 1. Trend changes to bullish (CHoCH)
                if trend == "bullish":
                    should_exit_position = True
                    exit_reason = "htf_trend_reversal"

                # 2. Strong bullish displacement detected
                bullish_displacements = [
                    d for d in displacements if d.direction == "bullish"
                ]
                if bullish_displacements and len(bullish_displacements) >= 2:
                    should_exit_position = True
                    exit_reason = "bullish_displacement"

                # 3. Bearish inducement detected (trapped retail)
                recent_inducement = any(
                    ind.direction == "bearish"
                    for ind in inducements[-3:]
                    if inducements
                )
                if recent_inducement:
                    should_exit_position = True
                    exit_reason = "bearish_inducement"

            if should_exit_position:
                self.logger.info(
                    f"[{self.symbol}] ICT indicator-based exit triggered: "
                    f"position_side={position.side}, trend={trend}, reason={exit_reason}"
                )
                signal_type = (
                    SignalType.CLOSE_LONG
                    if position.side == "LONG"
                    else SignalType.CLOSE_SHORT
                )
                return Signal(
                    signal_type=signal_type,
                    symbol=self.symbol,
                    entry_price=candle.close,
                    strategy_name=self.__class__.__name__,
                    timestamp=datetime.now(timezone.utc),
                    exit_reason=exit_reason,
                )

        except Exception as e:
            self.logger.error(
                f"[{self.symbol}] Error in indicator-based exit check: {e}"
            )
            return None

        return None
