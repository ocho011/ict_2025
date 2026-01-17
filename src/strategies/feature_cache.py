"""
Feature State Cache for pre-computed technical analysis features.

This module implements a fixed-size cache for managing the lifecycle of
Order Blocks, Fair Value Gaps, and Market Structure features across
multiple timeframes. Supports the feature pre-computation system (Issue #19).

Key Features:
- Fixed-size deque management with FIFO eviction
- Price-based invalidation for OBs and FVGs
- Efficient queries for active features
- Thread-safe operations (single-threaded asyncio context)

Performance Characteristics:
- Feature lookup: O(n) where n = active features (typically < 50)
- Feature update: O(1) for status updates
- Feature detection: O(k) where k = lookback window
"""

import logging
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Union

from src.models.candle import Candle
from src.models.features import (
    FairValueGap,
    FeatureStatus,
    FeatureType,
    LiquidityLevel,
    MarketStructure,
    OrderBlock,
)

# Type alias for tracked features
TrackedFeature = Union[OrderBlock, FairValueGap, LiquidityLevel]


class FeatureStateCache:
    """
    Manages lifecycle of pre-computed features across intervals.

    Design Principles:
    - Fixed-size buffers prevent unbounded memory growth
    - FIFO eviction for old features
    - Immutable features (status updates create new instances)
    - Price-based invalidation for consumed zones

    Usage:
        cache = FeatureStateCache(config={'max_order_blocks': 20})

        # During backfill
        cache.initialize_from_history('1h', candles)

        # During real-time
        new_features = cache.update_on_new_candle('1h', candle, buffers['1h'])
        active_obs = cache.get_active_order_blocks('1h', 'bullish')
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize feature cache with configuration.

        Args:
            config: Optional configuration dict with:
                - max_order_blocks: Max OBs per interval (default: 20)
                - max_fvgs: Max FVGs per interval (default: 15)
                - max_liquidity: Max liquidity levels per interval (default: 10)
                - feature_expiry_candles: Candles before feature expires (default: 100)
                - displacement_ratio: Min ratio for OB detection (default: 1.5)
                - fvg_min_gap_percent: Min FVG size as % of price (default: 0.001)
        """
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)

        # Configuration with defaults
        self.max_order_blocks = self.config.get("max_order_blocks", 20)
        self.max_fvgs = self.config.get("max_fvgs", 15)
        self.max_liquidity = self.config.get("max_liquidity", 10)
        self.feature_expiry_candles = self.config.get("feature_expiry_candles", 100)
        self.displacement_ratio = self.config.get("displacement_ratio", 1.5)
        self.fvg_min_gap_percent = self.config.get("fvg_min_gap_percent", 0.001)

        # Feature storage: {interval: deque[Feature]}
        self._order_blocks: Dict[str, Deque[OrderBlock]] = {}
        self._fvgs: Dict[str, Deque[FairValueGap]] = {}
        self._liquidity: Dict[str, Deque[LiquidityLevel]] = {}

        # Market structure: {interval: MarketStructure}
        self._market_structure: Dict[str, Optional[MarketStructure]] = {}

        # Tracking for incremental detection
        self._last_processed_index: Dict[str, int] = {}

    def initialize_from_history(
        self,
        interval: str,
        candles: List[Candle],
        detect_obs: bool = True,
        detect_fvgs: bool = True,
        detect_structure: bool = True,
    ) -> Dict[str, int]:
        """
        Pre-compute all features from historical candles during backfill.

        Called once per interval during strategy initialization.
        Time complexity: O(n) where n = len(candles)

        Args:
            interval: Timeframe (e.g., '1h')
            candles: Historical candles in chronological order
            detect_obs: Whether to detect Order Blocks
            detect_fvgs: Whether to detect Fair Value Gaps
            detect_structure: Whether to analyze Market Structure

        Returns:
            Dict with counts of detected features
        """
        if not candles:
            self.logger.warning(f"[FeatureStateCache] No candles for {interval} initialization")
            return {"order_blocks": 0, "fvgs": 0, "structure": False}

        # Initialize storage for this interval
        self._order_blocks[interval] = deque(maxlen=self.max_order_blocks)
        self._fvgs[interval] = deque(maxlen=self.max_fvgs)
        self._liquidity[interval] = deque(maxlen=self.max_liquidity)
        self._market_structure[interval] = None

        counts = {"order_blocks": 0, "fvgs": 0, "structure": False}

        # Detect Order Blocks
        if detect_obs:
            obs = self._detect_order_blocks_historical(interval, candles)
            for ob in obs:
                self._order_blocks[interval].append(ob)
            counts["order_blocks"] = len(obs)

        # Detect FVGs
        if detect_fvgs:
            fvgs = self._detect_fvgs_historical(interval, candles)
            for fvg in fvgs:
                self._fvgs[interval].append(fvg)
            counts["fvgs"] = len(fvgs)

        # Analyze Market Structure
        if detect_structure:
            structure = self._analyze_market_structure(interval, candles)
            self._market_structure[interval] = structure
            counts["structure"] = structure is not None

        # Track last processed index
        self._last_processed_index[interval] = len(candles) - 1

        self.logger.info(
            f"[FeatureStateCache] {interval} initialized: "
            f"OBs={counts['order_blocks']}, FVGs={counts['fvgs']}, "
            f"Structure={'Yes' if counts['structure'] else 'No'}"
        )

        return counts

    def update_on_new_candle(
        self,
        interval: str,
        candle: Candle,
        all_candles: Union[List[Candle], deque],
    ) -> Dict[str, List[TrackedFeature]]:
        """
        Incremental update on new real-time candle.

        Operations:
        1. Update status of existing features (mitigation, fill, expiry)
        2. Detect new features from recent candles only
        3. Update market structure if applicable

        Time complexity: O(f + k) where f=active_features, k=lookback_window

        Args:
            interval: Timeframe of the candle
            candle: New closed candle
            all_candles: Full candle buffer for context

        Returns:
            Dict of newly created features by type
        """
        new_features: Dict[str, List[TrackedFeature]] = {
            "order_blocks": [],
            "fvgs": [],
        }

        if interval not in self._order_blocks:
            # Interval not initialized, skip
            return new_features

        # 1. Update existing feature statuses based on price action
        self._update_order_block_statuses(interval, candle)
        self._update_fvg_statuses(interval, candle)

        # 2. Detect new features from recent candles (incremental)
        candles_list = list(all_candles)
        lookback = min(10, len(candles_list))  # Only check last 10 candles
        recent_candles = candles_list[-lookback:]

        # Check for new Order Block formation
        new_ob = self._check_order_block_formation(interval, recent_candles)
        if new_ob:
            self._order_blocks[interval].append(new_ob)
            new_features["order_blocks"].append(new_ob)

        # Check for new FVG formation
        new_fvg = self._check_fvg_formation(interval, recent_candles)
        if new_fvg:
            self._fvgs[interval].append(new_fvg)
            new_features["fvgs"].append(new_fvg)

        # 3. Update market structure
        if len(candles_list) >= 20:  # Need enough data for structure analysis
            self._update_market_structure(interval, candles_list)

        # 4. Cleanup expired features
        self._cleanup_expired_features(interval, len(candles_list))

        return new_features

    def get_active_order_blocks(
        self,
        interval: str,
        direction: Optional[str] = None,
    ) -> List[OrderBlock]:
        """
        Get all active Order Blocks for an interval.

        Args:
            interval: Timeframe
            direction: Optional filter ('bullish' or 'bearish')

        Returns:
            List of active OrderBlock objects
        """
        obs = self._order_blocks.get(interval, deque())
        active = [ob for ob in obs if ob.is_active]

        if direction:
            active = [ob for ob in active if ob.direction == direction]

        return active

    def get_active_fvgs(
        self,
        interval: str,
        direction: Optional[str] = None,
    ) -> List[FairValueGap]:
        """
        Get all active Fair Value Gaps for an interval.

        Args:
            interval: Timeframe
            direction: Optional filter ('bullish' or 'bearish')

        Returns:
            List of active FairValueGap objects
        """
        fvgs = self._fvgs.get(interval, deque())
        active = [fvg for fvg in fvgs if fvg.is_active]

        if direction:
            active = [fvg for fvg in active if fvg.direction == direction]

        return active

    def get_market_structure(self, interval: str) -> Optional[MarketStructure]:
        """
        Get current market structure for an interval.

        Args:
            interval: Timeframe

        Returns:
            MarketStructure object or None if not analyzed
        """
        return self._market_structure.get(interval)

    def find_nearest_order_block(
        self,
        interval: str,
        price: float,
        direction: str,
    ) -> Optional[OrderBlock]:
        """
        Find the nearest active Order Block to current price.

        For bullish direction: Find nearest OB below price (support)
        For bearish direction: Find nearest OB above price (resistance)

        Args:
            interval: Timeframe
            price: Current price
            direction: 'bullish' or 'bearish'

        Returns:
            Nearest OrderBlock or None
        """
        active_obs = self.get_active_order_blocks(interval, direction)

        if not active_obs:
            return None

        if direction == "bullish":
            # Find nearest support below price
            below = [ob for ob in active_obs if ob.zone_high <= price]
            return max(below, key=lambda ob: ob.zone_high) if below else None
        else:
            # Find nearest resistance above price
            above = [ob for ob in active_obs if ob.zone_low >= price]
            return min(above, key=lambda ob: ob.zone_low) if above else None

    def find_nearest_fvg(
        self,
        interval: str,
        price: float,
        direction: str,
    ) -> Optional[FairValueGap]:
        """
        Find the nearest active FVG to current price.

        For bullish direction: Find nearest FVG below price
        For bearish direction: Find nearest FVG above price

        Args:
            interval: Timeframe
            price: Current price
            direction: 'bullish' or 'bearish'

        Returns:
            Nearest FairValueGap or None
        """
        active_fvgs = self.get_active_fvgs(interval, direction)

        if not active_fvgs:
            return None

        if direction == "bullish":
            below = [fvg for fvg in active_fvgs if fvg.zone_high <= price]
            return max(below, key=lambda fvg: fvg.zone_high) if below else None
        else:
            above = [fvg for fvg in active_fvgs if fvg.zone_low >= price]
            return min(above, key=lambda fvg: fvg.zone_low) if above else None

    def is_price_in_order_block(self, price: float, ob: OrderBlock) -> bool:
        """Check if price is within an Order Block zone."""
        return ob.zone_low <= price <= ob.zone_high

    def is_price_in_fvg(self, price: float, fvg: FairValueGap) -> bool:
        """Check if price is within a Fair Value Gap zone."""
        return fvg.zone_low <= price <= fvg.zone_high

    # -------------------------------------------------------------------------
    # Private: Feature Detection Methods
    # -------------------------------------------------------------------------

    def _detect_order_blocks_historical(
        self,
        interval: str,
        candles: List[Candle],
    ) -> List[OrderBlock]:
        """Detect all Order Blocks from historical candles."""
        obs: List[OrderBlock] = []

        if len(candles) < 22:  # Need enough data for avg_range calculation
            return obs

        # Calculate average range for displacement comparison
        avg_range = self._calculate_average_range(candles[-20:])

        if avg_range == 0:
            return obs

        # Scan for displacement moves and identify OBs
        for i in range(20, len(candles)):
            current = candles[i]
            candle_range = current.high - current.low

            # Check for strong displacement
            is_bullish_displacement = (
                current.close > current.open and candle_range >= self.displacement_ratio * avg_range
            )
            is_bearish_displacement = (
                current.close < current.open and candle_range >= self.displacement_ratio * avg_range
            )

            if is_bullish_displacement:
                # Find last bearish candle before displacement
                ob = self._find_bullish_ob(interval, candles, i, avg_range)
                if ob:
                    obs.append(ob)

            elif is_bearish_displacement:
                # Find last bullish candle before displacement
                ob = self._find_bearish_ob(interval, candles, i, avg_range)
                if ob:
                    obs.append(ob)

        # Keep only most recent OBs (respect max limit)
        return obs[-self.max_order_blocks :]

    def _find_bullish_ob(
        self,
        interval: str,
        candles: List[Candle],
        displacement_idx: int,
        avg_range: float,
    ) -> Optional[OrderBlock]:
        """Find bullish Order Block before displacement."""
        displacement = candles[displacement_idx]

        for j in range(displacement_idx - 1, max(0, displacement_idx - 5), -1):
            prev = candles[j]

            # Bullish OB: Last bearish candle before upward move
            if prev.close < prev.open:
                displacement_size = displacement.high - displacement.low
                strength = displacement_size / avg_range if avg_range > 0 else 1.0

                ob_id = f"{interval}_{prev.open_time.timestamp()}_{displacement_idx}_bullish"

                return OrderBlock(
                    id=ob_id,
                    interval=interval,
                    direction="bullish",
                    high=prev.high,
                    low=prev.low,
                    timestamp=prev.open_time,
                    candle_index=j,
                    displacement_size=displacement_size,
                    strength=strength,
                )

        return None

    def _find_bearish_ob(
        self,
        interval: str,
        candles: List[Candle],
        displacement_idx: int,
        avg_range: float,
    ) -> Optional[OrderBlock]:
        """Find bearish Order Block before displacement."""
        displacement = candles[displacement_idx]

        for j in range(displacement_idx - 1, max(0, displacement_idx - 5), -1):
            prev = candles[j]

            # Bearish OB: Last bullish candle before downward move
            if prev.close > prev.open:
                displacement_size = displacement.high - displacement.low
                strength = displacement_size / avg_range if avg_range > 0 else 1.0

                ob_id = f"{interval}_{prev.open_time.timestamp()}_{displacement_idx}_bearish"

                return OrderBlock(
                    id=ob_id,
                    interval=interval,
                    direction="bearish",
                    high=prev.high,
                    low=prev.low,
                    timestamp=prev.open_time,
                    candle_index=j,
                    displacement_size=displacement_size,
                    strength=strength,
                )

        return None

    def _detect_fvgs_historical(
        self,
        interval: str,
        candles: List[Candle],
    ) -> List[FairValueGap]:
        """Detect all Fair Value Gaps from historical candles."""
        fvgs: List[FairValueGap] = []

        if len(candles) < 3:
            return fvgs

        for i in range(2, len(candles)):
            c1 = candles[i - 2]  # First candle
            c2 = candles[i - 1]  # Middle candle (gap candle)
            c3 = candles[i]  # Third candle

            # Bullish FVG: Gap between c1.high and c3.low
            if c3.low > c1.high:
                gap_size = c3.low - c1.high
                gap_percent = gap_size / c2.close if c2.close > 0 else 0

                if gap_percent >= self.fvg_min_gap_percent:
                    fvg_id = f"{interval}_{c2.open_time.timestamp()}_bullish"

                    fvgs.append(
                        FairValueGap(
                            id=fvg_id,
                            interval=interval,
                            direction="bullish",
                            gap_high=c3.low,
                            gap_low=c1.high,
                            timestamp=c2.open_time,
                            candle_index=i - 1,
                            gap_size=gap_size,
                        )
                    )

            # Bearish FVG: Gap between c1.low and c3.high
            elif c3.high < c1.low:
                gap_size = c1.low - c3.high
                gap_percent = gap_size / c2.close if c2.close > 0 else 0

                if gap_percent >= self.fvg_min_gap_percent:
                    fvg_id = f"{interval}_{c2.open_time.timestamp()}_bearish"

                    fvgs.append(
                        FairValueGap(
                            id=fvg_id,
                            interval=interval,
                            direction="bearish",
                            gap_high=c1.low,
                            gap_low=c3.high,
                            timestamp=c2.open_time,
                            candle_index=i - 1,
                            gap_size=gap_size,
                        )
                    )

        # Keep only most recent FVGs
        return fvgs[-self.max_fvgs :]

    def _analyze_market_structure(
        self,
        interval: str,
        candles: List[Candle],
        lookback: int = 20,
    ) -> Optional[MarketStructure]:
        """Analyze market structure from candles."""
        if len(candles) < lookback:
            return None

        recent = candles[-lookback:]

        # Find swing highs and lows
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]

        swing_high = max(highs)
        swing_low = min(lows)

        # Simple trend determination
        first_half = recent[: lookback // 2]
        second_half = recent[lookback // 2 :]

        first_avg = sum(c.close for c in first_half) / len(first_half)
        second_avg = sum(c.close for c in second_half) / len(second_half)

        threshold = (swing_high - swing_low) * 0.1  # 10% of range

        if second_avg > first_avg + threshold:
            trend = "bullish"
        elif second_avg < first_avg - threshold:
            trend = "bearish"
        else:
            trend = "sideways"

        return MarketStructure(
            interval=interval,
            trend=trend,
            last_swing_high=swing_high,
            last_swing_low=swing_low,
        )

    # -------------------------------------------------------------------------
    # Private: Incremental Update Methods
    # -------------------------------------------------------------------------

    def _check_order_block_formation(
        self,
        interval: str,
        recent_candles: List[Candle],
    ) -> Optional[OrderBlock]:
        """Check if a new Order Block formed in recent candles."""
        if len(recent_candles) < 5:
            return None

        avg_range = self._calculate_average_range(recent_candles)
        if avg_range == 0:
            return None

        # Check only the most recent candle for displacement
        current = recent_candles[-1]
        candle_range = current.high - current.low

        is_bullish_displacement = (
            current.close > current.open and candle_range >= self.displacement_ratio * avg_range
        )
        is_bearish_displacement = (
            current.close < current.open and candle_range >= self.displacement_ratio * avg_range
        )

        if is_bullish_displacement:
            return self._find_bullish_ob(interval, recent_candles, len(recent_candles) - 1, avg_range)
        elif is_bearish_displacement:
            return self._find_bearish_ob(interval, recent_candles, len(recent_candles) - 1, avg_range)

        return None

    def _check_fvg_formation(
        self,
        interval: str,
        recent_candles: List[Candle],
    ) -> Optional[FairValueGap]:
        """Check if a new FVG formed in recent candles."""
        if len(recent_candles) < 3:
            return None

        # Check only the most recent 3-candle pattern
        c1 = recent_candles[-3]
        c2 = recent_candles[-2]
        c3 = recent_candles[-1]

        # Bullish FVG
        if c3.low > c1.high:
            gap_size = c3.low - c1.high
            gap_percent = gap_size / c2.close if c2.close > 0 else 0

            if gap_percent >= self.fvg_min_gap_percent:
                fvg_id = f"{interval}_{c2.open_time.timestamp()}_bullish_new"

                return FairValueGap(
                    id=fvg_id,
                    interval=interval,
                    direction="bullish",
                    gap_high=c3.low,
                    gap_low=c1.high,
                    timestamp=c2.open_time,
                    candle_index=len(recent_candles) - 2,
                    gap_size=gap_size,
                )

        # Bearish FVG
        elif c3.high < c1.low:
            gap_size = c1.low - c3.high
            gap_percent = gap_size / c2.close if c2.close > 0 else 0

            if gap_percent >= self.fvg_min_gap_percent:
                fvg_id = f"{interval}_{c2.open_time.timestamp()}_bearish_new"

                return FairValueGap(
                    id=fvg_id,
                    interval=interval,
                    direction="bearish",
                    gap_high=c1.low,
                    gap_low=c3.high,
                    timestamp=c2.open_time,
                    candle_index=len(recent_candles) - 2,
                    gap_size=gap_size,
                )

        return None

    def _update_order_block_statuses(self, interval: str, candle: Candle) -> None:
        """Update Order Block statuses based on price action."""
        obs = self._order_blocks.get(interval, deque())
        updated_obs: Deque[OrderBlock] = deque(maxlen=self.max_order_blocks)

        for ob in obs:
            if not ob.is_active:
                updated_obs.append(ob)
                continue

            # Check if price touched or entered the OB zone
            price_touched_zone = candle.low <= ob.zone_high and candle.high >= ob.zone_low

            if price_touched_zone:
                # Calculate mitigation percentage
                if ob.direction == "bullish":
                    # For bullish OB, mitigation from above
                    if candle.low < ob.zone_low:
                        mitigation = 1.0  # Fully mitigated
                    else:
                        mitigation = (ob.zone_high - candle.low) / ob.zone_size
                else:
                    # For bearish OB, mitigation from below
                    if candle.high > ob.zone_high:
                        mitigation = 1.0  # Fully mitigated
                    else:
                        mitigation = (candle.high - ob.zone_low) / ob.zone_size

                mitigation = max(0.0, min(1.0, mitigation))

                if mitigation >= 0.9:
                    new_status = FeatureStatus.FILLED
                elif mitigation > 0.3:
                    new_status = FeatureStatus.MITIGATED
                else:
                    new_status = FeatureStatus.TOUCHED

                updated_ob = ob.with_status(
                    new_status,
                    touch_count=ob.touch_count + 1,
                    mitigation_percent=max(ob.mitigation_percent, mitigation),
                )
                updated_obs.append(updated_ob)
            else:
                updated_obs.append(ob)

        self._order_blocks[interval] = updated_obs

    def _update_fvg_statuses(self, interval: str, candle: Candle) -> None:
        """Update FVG statuses based on price action."""
        fvgs = self._fvgs.get(interval, deque())
        updated_fvgs: Deque[FairValueGap] = deque(maxlen=self.max_fvgs)

        for fvg in fvgs:
            if not fvg.is_active:
                updated_fvgs.append(fvg)
                continue

            # Check if price entered the FVG zone
            price_in_zone = candle.low <= fvg.zone_high and candle.high >= fvg.zone_low

            if price_in_zone:
                # Calculate fill percentage
                gap_size = fvg.gap_high - fvg.gap_low

                if fvg.direction == "bullish":
                    # Bullish FVG fills from above
                    if candle.low < fvg.zone_low:
                        fill_percent = 1.0
                    else:
                        fill_percent = (fvg.zone_high - candle.low) / gap_size
                else:
                    # Bearish FVG fills from below
                    if candle.high > fvg.zone_high:
                        fill_percent = 1.0
                    else:
                        fill_percent = (candle.high - fvg.zone_low) / gap_size

                fill_percent = max(0.0, min(1.0, fill_percent))

                if fill_percent >= 0.9:
                    new_status = FeatureStatus.FILLED
                elif fill_percent > 0.3:
                    new_status = FeatureStatus.MITIGATED
                else:
                    new_status = FeatureStatus.TOUCHED

                updated_fvg = fvg.with_status(
                    new_status,
                    fill_percent=max(fvg.fill_percent, fill_percent),
                )
                updated_fvgs.append(updated_fvg)
            else:
                updated_fvgs.append(fvg)

        self._fvgs[interval] = updated_fvgs

    def _update_market_structure(
        self,
        interval: str,
        candles: List[Candle],
    ) -> None:
        """Update market structure with new candle data."""
        new_structure = self._analyze_market_structure(interval, candles)
        if new_structure:
            self._market_structure[interval] = new_structure

    def _cleanup_expired_features(self, interval: str, current_index: int) -> None:
        """Remove features that are too old."""
        expiry_threshold = current_index - self.feature_expiry_candles

        # Cleanup old OBs
        obs = self._order_blocks.get(interval, deque())
        self._order_blocks[interval] = deque(
            [ob for ob in obs if ob.candle_index > expiry_threshold or ob.is_active],
            maxlen=self.max_order_blocks,
        )

        # Cleanup old FVGs
        fvgs = self._fvgs.get(interval, deque())
        self._fvgs[interval] = deque(
            [fvg for fvg in fvgs if fvg.candle_index > expiry_threshold or fvg.is_active],
            maxlen=self.max_fvgs,
        )

    def _calculate_average_range(self, candles: List[Candle]) -> float:
        """Calculate average candle range."""
        if not candles:
            return 0.0

        total_range = sum(c.high - c.low for c in candles)
        return total_range / len(candles)

    # -------------------------------------------------------------------------
    # Public: Statistics and Debugging
    # -------------------------------------------------------------------------

    def get_cache_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics about cached features."""
        stats = {}

        for interval in self._order_blocks.keys():
            obs = self._order_blocks.get(interval, deque())
            fvgs = self._fvgs.get(interval, deque())
            structure = self._market_structure.get(interval)

            stats[interval] = {
                "order_blocks_total": len(obs),
                "order_blocks_active": len([ob for ob in obs if ob.is_active]),
                "fvgs_total": len(fvgs),
                "fvgs_active": len([fvg for fvg in fvgs if fvg.is_active]),
                "has_structure": structure is not None,
                "trend": structure.trend if structure else None,
            }

        return stats
