"""
Feature Store for centralized indicator management and pre-computation.

Replaces and extends IndicatorStateCache to provide a unified data hub
for all strategy modules (Determiners).

Compliant with Real-time Trading Guidelines:
- Shared indicator calculations to avoid redundancy
- Fixed-size caching for memory efficiency
- Decoupled data logic from execution context
"""

import logging
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Union, Any

import numpy as np
from src.models.candle import Candle
from src.models.indicators import (
    FairValueGap,
    IndicatorStatus,
    IndicatorType,
    LiquidityLevel,
    MarketStructure,
    OrderBlock,
)

# Reuse existing models
TrackedIndicator = Union[OrderBlock, FairValueGap, LiquidityLevel]


class FeatureStore:
    """
    Centralized store for pre-computed features and indicators.
    
    Provides:
    - Smart Money Concepts (OB, FVG, Structure)
    - Technical Indicators (EMA, SMA, ATR, etc.)
    - Data normalization and sharing across modules
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize Feature Store.
        """
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)

        # SMC Cache settings
        self.max_order_blocks = self.config.get("max_order_blocks", 20)
        self.max_fvgs = self.config.get("max_fvgs", 15)
        self.max_liquidity = self.config.get("max_liquidity", 10)
        self.indicator_expiry_candles = self.config.get("indicator_expiry_candles", 100)
        
        # Detection parameters
        self.displacement_ratio = self.config.get("displacement_ratio", 1.5)
        self.fvg_min_gap_percent = self.config.get("fvg_min_gap_percent", 0.001)

        # SMC Storage: {interval: deque}
        self._order_blocks: Dict[str, Deque[OrderBlock]] = {}
        self._fvgs: Dict[str, Deque[FairValueGap]] = {}
        self._liquidity: Dict[str, Deque[LiquidityLevel]] = {}
        self._market_structure: Dict[str, Optional[MarketStructure]] = {}

        # Generic Indicator Cache: {interval: {indicator_name: value}}
        self._generic_indicators: Dict[str, Dict[str, Any]] = {}

    def initialize_for_symbol(
        self, 
        symbol: str, 
        interval_data: Dict[str, List[Candle]],
        detect_obs: bool = True,
        detect_fvgs: bool = True,
        detect_structure: bool = True,
    ) -> None:
        """
        Initialize store with historical data for a symbol across multiple intervals.
        """
        for interval, candles in interval_data.items():
            if not candles:
                continue

            self.logger.info(f"Initializing Features for {symbol} {interval}")
            
            # Initialize SMC storage
            self._order_blocks[interval] = deque(maxlen=self.max_order_blocks)
            self._fvgs[interval] = deque(maxlen=self.max_fvgs)
            self._liquidity[interval] = deque(maxlen=self.max_liquidity)
            self._market_structure[interval] = None

            # Detect historical indicators
            if detect_obs:
                obs = self._detect_order_blocks_historical(interval, candles)
                for ob in obs:
                    self._order_blocks[interval].append(ob)

            if detect_fvgs:
                fvgs = self._detect_fvgs_historical(interval, candles)
                for fvg in fvgs:
                    self._fvgs[interval].append(fvg)

            if detect_structure:
                structure = self._analyze_market_structure(interval, candles)
                self._market_structure[interval] = structure

            # Update generic indicators for initial state
            self.update(interval, candles[-1], candles)

    def update(self, interval: str, candle: Candle, buffer: List[Candle]) -> None:
        """
        Update features upon receiving a new closed candle.
        """
        if interval not in self._generic_indicators:
            self._generic_indicators[interval] = {}

        # 1. Update Technical Indicators
        closes = np.array([c.close for c in buffer])
        
        if len(closes) >= 200:
            self._generic_indicators[interval]["ema_200"] = self._calculate_ema(closes, 200)
        if len(closes) >= 50:
            self._generic_indicators[interval]["ema_50"] = self._calculate_ema(closes, 50)
        if len(buffer) >= 15:
            self._generic_indicators[interval]["atr_14"] = self._calculate_atr(buffer, 14)

        # 2. Update SMC Statuses (Mitigation/Fill)
        if interval in self._order_blocks:
            self._update_order_block_statuses(interval, candle)
            self._update_fvg_statuses(interval, candle)

            # 3. Detect New SMC Indicators (Incremental)
            lookback = min(10, len(buffer))
            recent_candles = buffer[-lookback:]

            new_ob = self._check_order_block_formation(interval, recent_candles)
            if new_ob:
                self._order_blocks[interval].append(new_ob)

            new_fvg = self._check_fvg_formation(interval, recent_candles)
            if new_fvg:
                self._fvgs[interval].append(new_fvg)

            # 4. Update Market Structure
            if len(buffer) >= 20:
                self._update_market_structure(interval, buffer)

            # 5. Cleanup
            self._cleanup_expired_indicators(interval, len(buffer))

    def get(self, interval: str, key: str, default: Any = None) -> Any:
        """
        Query a feature value by key.
        """
        return self._generic_indicators.get(interval, {}).get(key, default)

    def get_active_order_blocks(self, interval: str, direction: Optional[str] = None) -> List[OrderBlock]:
        obs = self._order_blocks.get(interval, [])
        active = [ob for ob in obs if ob.is_active]
        if direction:
            active = [ob for ob in active if ob.direction == direction]
        return active

    def get_active_fvgs(self, interval: str, direction: Optional[str] = None) -> List[FairValueGap]:
        fvgs = self._fvgs.get(interval, [])
        active = [fvg for fvg in fvgs if fvg.is_active]
        if direction:
            active = [fvg for fvg in active if fvg.direction == direction]
        return active

    def get_market_structure(self, interval: str) -> Optional[MarketStructure]:
        return self._market_structure.get(interval)

    # Internal calculation helpers (vectorized via numpy)
    
    def _calculate_ema(self, data: np.ndarray, period: int) -> float:
        """Calculate Exponential Moving Average."""
        if len(data) < period:
            return float(data[-1])
        alpha = 2 / (period + 1)
        # Using a simple iterative EMA for small data sets, 
        # for high performance on large sets use pandas or optimized talib
        ema = data[0]
        for i in range(1, len(data)):
            ema = alpha * data[i] + (1 - alpha) * ema
        return float(ema)

    def _calculate_atr(self, candles: List[Candle], period: int) -> float:
        """Calculate Average True Range."""
        if len(candles) < period + 1:
            return 0.0
        
        tr_list = []
        for i in range(len(candles) - period, len(candles)):
            curr = candles[i]
            prev = candles[i-1]
            tr = max(
                curr.high - curr.low,
                abs(curr.high - prev.close),
                abs(curr.low - prev.close)
            )
            tr_list.append(tr)
        return float(np.mean(tr_list))

    # SMC Detection Methods (Migrated from IndicatorStateCache)

    def _detect_order_blocks_historical(self, interval: str, candles: List[Candle]) -> List[OrderBlock]:
        obs: List[OrderBlock] = []
        if len(candles) < 22:
            return obs
        avg_range = self._calculate_average_range(candles[-20:])
        if avg_range == 0: return obs

        for i in range(20, len(candles)):
            current = candles[i]
            candle_range = current.high - current.low
            if current.close > current.open and candle_range >= self.displacement_ratio * avg_range:
                ob = self._find_ob(interval, candles, i, avg_range, "bullish")
                if ob: obs.append(ob)
            elif current.close < current.open and candle_range >= self.displacement_ratio * avg_range:
                ob = self._find_ob(interval, candles, i, avg_range, "bearish")
                if ob: obs.append(ob)
        return obs[-self.max_order_blocks:]

    def _find_ob(self, interval: str, candles: List[Candle], disp_idx: int, avg_range: float, direction: str) -> Optional[OrderBlock]:
        displacement = candles[disp_idx]
        for j in range(disp_idx - 1, max(0, disp_idx - 5), -1):
            prev = candles[j]
            if (direction == "bullish" and prev.close < prev.open) or (direction == "bearish" and prev.close > prev.open):
                disp_size = displacement.high - displacement.low
                strength = disp_size / avg_range if avg_range > 0 else 1.0
                return OrderBlock(
                    id=f"{interval}_{prev.open_time.timestamp()}_{disp_idx}_{direction}",
                    interval=interval, direction=direction, high=prev.high, low=prev.low,
                    timestamp=prev.open_time, candle_index=j, displacement_size=disp_size, strength=strength,
                )
        return None

    def _detect_fvgs_historical(self, interval: str, candles: List[Candle]) -> List[FairValueGap]:
        fvgs: List[FairValueGap] = []
        if len(candles) < 3: return fvgs
        for i in range(2, len(candles)):
            c1, c2, c3 = candles[i-2], candles[i-1], candles[i]
            if c3.low > c1.high: # Bullish
                gap_size = c3.low - c1.high
                if (gap_size / c2.close) >= self.fvg_min_gap_percent:
                    fvgs.append(FairValueGap(
                        id=f"{interval}_{c2.open_time.timestamp()}_bullish",
                        interval=interval, direction="bullish", gap_high=c3.low, gap_low=c1.high,
                        timestamp=c2.open_time, candle_index=i-1, gap_size=gap_size
                    ))
            elif c3.high < c1.low: # Bearish
                gap_size = c1.low - c3.high
                if (gap_size / c2.close) >= self.fvg_min_gap_percent:
                    fvgs.append(FairValueGap(
                        id=f"{interval}_{c2.open_time.timestamp()}_bearish",
                        interval=interval, direction="bearish", gap_high=c1.low, gap_low=c3.high,
                        timestamp=c2.open_time, candle_index=i-1, gap_size=gap_size
                    ))
        return fvgs[-self.max_fvgs:]

    def _analyze_market_structure(self, interval: str, candles: List[Candle], lookback: int = 20) -> Optional[MarketStructure]:
        if len(candles) < lookback: return None
        recent = candles[-lookback:]
        highs, lows = [c.high for c in recent], [c.low for c in recent]
        swing_high, swing_low = max(highs), min(lows)
        
        first_half, second_half = recent[:lookback//2], recent[lookback//2:]
        first_avg = sum(c.close for c in first_half) / len(first_half)
        second_avg = sum(c.close for c in second_half) / len(second_half)
        threshold = (swing_high - swing_low) * 0.005
        
        if second_avg > first_avg + threshold: trend = "bullish"
        elif second_avg < first_avg - threshold: trend = "bearish"
        else: trend = "sideways"
        
        return MarketStructure(interval=interval, trend=trend, last_swing_high=swing_high, last_swing_low=swing_low)

    def _update_order_block_statuses(self, interval: str, candle: Candle) -> None:
        obs = self._order_blocks.get(interval, deque())
        updated_obs: Deque[OrderBlock] = deque(maxlen=self.max_order_blocks)
        for ob in obs:
            if not ob.is_active:
                updated_obs.append(ob)
                continue
            if candle.low <= ob.zone_high and candle.high >= ob.zone_low:
                if ob.direction == "bullish":
                    mitigation = 1.0 if candle.low < ob.zone_low else (ob.zone_high - candle.low) / ob.zone_size
                else:
                    mitigation = 1.0 if candle.high > ob.zone_high else (candle.high - ob.zone_low) / ob.zone_size
                mitigation = max(0.0, min(1.0, mitigation))
                status = IndicatorStatus.FILLED if mitigation >= 0.9 else (IndicatorStatus.MITIGATED if mitigation > 0.3 else IndicatorStatus.TOUCHED)
                updated_obs.append(ob.with_status(status, touch_count=ob.touch_count + 1, mitigation_percent=max(ob.mitigation_percent, mitigation)))
            else:
                updated_obs.append(ob)
        self._order_blocks[interval] = updated_obs

    def _update_fvg_statuses(self, interval: str, candle: Candle) -> None:
        fvgs = self._fvgs.get(interval, deque())
        updated_fvgs: Deque[FairValueGap] = deque(maxlen=self.max_fvgs)
        for fvg in fvgs:
            if not fvg.is_active:
                updated_fvgs.append(fvg)
                continue
            if candle.low <= fvg.zone_high and candle.high >= fvg.zone_low:
                gap_size = fvg.gap_high - fvg.gap_low
                if fvg.direction == "bullish":
                    fill = 1.0 if candle.low < fvg.zone_low else (fvg.zone_high - candle.low) / gap_size
                else:
                    fill = 1.0 if candle.high > fvg.zone_high else (candle.high - fvg.zone_low) / gap_size
                fill = max(0.0, min(1.0, fill))
                status = IndicatorStatus.FILLED if fill >= 0.9 else (IndicatorStatus.MITIGATED if fill > 0.3 else IndicatorStatus.TOUCHED)
                updated_fvgs.append(fvg.with_status(status, fill_percent=max(fvg.fill_percent, fill)))
            else:
                updated_fvgs.append(fvg)
        self._fvgs[interval] = updated_fvgs

    def _check_order_block_formation(self, interval: str, recent_candles: List[Candle]) -> Optional[OrderBlock]:
        if len(recent_candles) < 5: return None
        avg_range = self._calculate_average_range(recent_candles)
        if avg_range == 0: return None
        current = recent_candles[-1]
        c_range = current.high - current.low
        if current.close > current.open and c_range >= self.displacement_ratio * avg_range:
            return self._find_ob(interval, recent_candles, len(recent_candles) - 1, avg_range, "bullish")
        elif current.close < current.open and c_range >= self.displacement_ratio * avg_range:
            return self._find_ob(interval, recent_candles, len(recent_candles) - 1, avg_range, "bearish")
        return None

    def _check_fvg_formation(self, interval: str, recent_candles: List[Candle]) -> Optional[FairValueGap]:
        if len(recent_candles) < 3: return None
        c1, c2, c3 = recent_candles[-3], recent_candles[-2], recent_candles[-1]
        if c3.low > c1.high:
            gap_size = c3.low - c1.high
            if (gap_size / c2.close) >= self.fvg_min_gap_percent:
                return FairValueGap(id=f"{interval}_{c2.open_time.timestamp()}_bullish_new",
                    interval=interval, direction="bullish", gap_high=c3.low, gap_low=c1.high,
                    timestamp=c2.open_time, candle_index=len(recent_candles)-2, gap_size=gap_size)
        elif c3.high < c1.low:
            gap_size = c1.low - c3.high
            if (gap_size / c2.close) >= self.fvg_min_gap_percent:
                return FairValueGap(id=f"{interval}_{c2.open_time.timestamp()}_bearish_new",
                    interval=interval, direction="bearish", gap_high=c1.low, gap_low=c3.high,
                    timestamp=c2.open_time, candle_index=len(recent_candles)-2, gap_size=gap_size)
        return None

    def _update_market_structure(self, interval: str, buffer: List[Candle]) -> None:
        struct = self._analyze_market_structure(interval, buffer)
        if struct: self._market_structure[interval] = struct

    def _cleanup_expired_indicators(self, interval: str, curr_idx: int) -> None:
        thresh = curr_idx - self.indicator_expiry_candles
        self._order_blocks[interval] = deque([ob for ob in self._order_blocks[interval] if ob.candle_index > thresh or ob.is_active], maxlen=self.max_order_blocks)
        self._fvgs[interval] = deque([fvg for fvg in self._fvgs[interval] if fvg.candle_index > thresh or fvg.is_active], maxlen=self.max_fvgs)

    def _calculate_average_range(self, candles: List[Candle]) -> float:
        if not candles: return 0.0
        return sum(c.high - c.low for c in candles) / len(candles)
