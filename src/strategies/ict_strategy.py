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

from typing import Optional
from datetime import datetime, timezone

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import BaseStrategy

# ICT Market Structure
from src.indicators.ict_market_structure import (
    identify_swing_highs,
    identify_swing_lows,
    detect_bos,
    detect_choch,
    get_current_trend
)

# ICT Fair Value Gap
from src.indicators.ict_fvg import (
    detect_bullish_fvg,
    detect_bearish_fvg,
    find_nearest_fvg,
    get_entry_zone
)

# ICT Order Block
from src.indicators.ict_order_block import (
    identify_bullish_ob,
    identify_bearish_ob,
    find_nearest_ob,
    get_ob_zone
)

# ICT Liquidity
from src.indicators.ict_liquidity import (
    find_equal_highs,
    find_equal_lows,
    calculate_premium_discount,
    is_in_premium,
    is_in_discount,
    detect_liquidity_sweep
)

# ICT Smart Money Concepts
from src.indicators.ict_smc import (
    detect_inducement,
    detect_displacement,
    find_mitigation_zone
)

# ICT Kill Zones
from src.indicators.ict_killzones import (
    is_killzone_active,
    get_active_killzone
)


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
        Initialize ICT strategy.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            config: Strategy configuration dictionary
        """
        super().__init__(symbol, config)

        # ICT-specific parameters
        self.swing_lookback = config.get('swing_lookback', 5)
        self.displacement_ratio = config.get('displacement_ratio', 1.5)
        self.fvg_min_gap_percent = config.get('fvg_min_gap_percent', 0.001)
        self.ob_min_strength = config.get('ob_min_strength', 1.5)
        self.liquidity_tolerance = config.get('liquidity_tolerance', 0.001)
        self.rr_ratio = config.get('rr_ratio', 2.0)
        self.use_killzones = config.get('use_killzones', True)

        # Minimum buffer size for ICT analysis
        self.min_periods = max(50, self.swing_lookback * 4)

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
            return None

        # Step 1: Kill Zone Filter
        if self.use_killzones:
            if not is_killzone_active(candle.open_time):
                return None  # Outside optimal trading times

        # Step 2: Trend Analysis (Market Structure)
        trend = get_current_trend(self.candle_buffer, swing_lookback=self.swing_lookback)

        if trend is None:
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
            identify_bearish_ob(self.candle_buffer, displacement_ratio=self.displacement_ratio)
        )

        # Filter OBs by strength
        bullish_obs = [ob for ob in bullish_obs if ob.strength >= self.ob_min_strength]
        bearish_obs = [ob for ob in bearish_obs if ob.strength >= self.ob_min_strength]

        # Step 5: Liquidity Analysis
        equal_highs = find_equal_highs(
            self.candle_buffer,
            tolerance_percent=self.liquidity_tolerance,
            lookback=20
        )
        equal_lows = find_equal_lows(
            self.candle_buffer,
            tolerance_percent=self.liquidity_tolerance,
            lookback=20
        )

        liquidity_sweeps = detect_liquidity_sweep(
            self.candle_buffer,
            equal_highs + equal_lows
        )

        # Step 6: Inducement Check
        inducements = detect_inducement(self.candle_buffer, lookback=10)

        # Step 7: Displacement Confirmation
        displacements = detect_displacement(
            self.candle_buffer, displacement_ratio=self.displacement_ratio
        )

        # Step 8: Entry Timing - Look for mitigation of FVG/OB
        mitigations = find_mitigation_zone(
            self.candle_buffer,
            fvgs=bullish_fvgs + bearish_fvgs,
            obs=bullish_obs + bearish_obs
        )

        # LONG Entry Logic
        if trend == 'bullish' and is_in_discount(current_price, range_low, range_high):
            # Check for bullish FVG or OB nearby
            nearest_fvg = find_nearest_fvg(
                bullish_fvgs, current_price, direction='bullish'
            )
            nearest_ob = find_nearest_ob(
                bullish_obs, current_price, direction='bullish'
            )

            # Check for recent inducement (bearish fake move)
            recent_inducement = any(
                ind.direction == 'bearish' for ind in inducements[-3:] if inducements
            )

            # Check for recent displacement (bullish move)
            recent_displacement = any(
                disp.direction == 'bullish' for disp in displacements[-3:] if displacements
            )

            # Entry conditions:
            # 1. In discount zone (value)
            # 2. Recent bearish inducement (trapped shorts)
            # 3. Recent bullish displacement (smart money buying)
            # 4. Near bullish FVG or OB (mitigation zone)
            if recent_inducement and recent_displacement and (nearest_fvg or nearest_ob):
                entry_price = candle.close
                side = 'LONG'

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
                        'trend': trend,
                        'zone': 'discount',
                        'killzone': get_active_killzone(candle.open_time) if self.use_killzones else None,
                        'fvg_present': nearest_fvg is not None,
                        'ob_present': nearest_ob is not None,
                        'inducement': recent_inducement,
                        'displacement': recent_displacement
                    }
                )

        # SHORT Entry Logic
        elif trend == 'bearish' and is_in_premium(current_price, range_low, range_high):
            # Check for bearish FVG or OB nearby
            nearest_fvg = find_nearest_fvg(
                bearish_fvgs, current_price, direction='bearish'
            )
            nearest_ob = find_nearest_ob(
                bearish_obs, current_price, direction='bearish'
            )

            # Check for recent inducement (bullish fake move)
            recent_inducement = any(
                ind.direction == 'bullish' for ind in inducements[-3:] if inducements
            )

            # Check for recent displacement (bearish move)
            recent_displacement = any(
                disp.direction == 'bearish' for disp in displacements[-3:] if displacements
            )

            # Entry conditions:
            # 1. In premium zone (expensive)
            # 2. Recent bullish inducement (trapped longs)
            # 3. Recent bearish displacement (smart money selling)
            # 4. Near bearish FVG or OB (mitigation zone)
            if recent_inducement and recent_displacement and (nearest_fvg or nearest_ob):
                entry_price = candle.close
                side = 'SHORT'

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
                        'trend': trend,
                        'zone': 'premium',
                        'killzone': get_active_killzone(candle.open_time) if self.use_killzones else None,
                        'fvg_present': nearest_fvg is not None,
                        'ob_present': nearest_ob is not None,
                        'inducement': recent_inducement,
                        'displacement': recent_displacement
                    }
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

        if side == 'LONG':
            return entry_price + reward_amount
        else:  # SHORT
            return entry_price - reward_amount

    def calculate_stop_loss(
        self,
        entry_price: float,
        side: str,
        nearest_fvg=None,
        nearest_ob=None
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
            if side == 'LONG':
                return entry_price * 0.99
            else:  # SHORT
                return entry_price * 1.01

        # Place SL below/above zone with small buffer
        buffer = entry_price * 0.001  # 0.1% buffer

        if side == 'LONG':
            # SL below FVG/OB zone
            return zone_low - buffer
        else:  # SHORT
            # SL above FVG/OB zone
            return zone_high + buffer
