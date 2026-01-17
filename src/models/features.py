"""
Feature state models for pre-computed technical analysis features.

This module defines immutable dataclasses for tracking Order Blocks, Fair Value Gaps,
and Market Structure state across multiple timeframes. These models support the
feature pre-computation system (Issue #19) that calculates features during backfill
and tracks their lifecycle in real-time.

Key Design Principles:
- Immutability: Features are created once, status updates create new instances
- Validation: All features validated on creation (fail-fast)
- Performance: Minimal memory footprint with __slots__ optimization
- Lifecycle: Track creation, touch, mitigation, and invalidation states
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class FeatureStatus(Enum):
    """
    Lifecycle status for tracked features.

    State Transitions:
    - ACTIVE → TOUCHED: Price reached zone boundary
    - TOUCHED → MITIGATED: Price entered zone partially
    - MITIGATED → FILLED: Zone completely consumed
    - Any → INVALIDATED: Market structure change or expiry
    """

    ACTIVE = "active"  # Feature is valid and tradeable
    TOUCHED = "touched"  # Price reached zone but didn't enter
    MITIGATED = "mitigated"  # Price entered zone partially
    FILLED = "filled"  # Zone completely consumed
    INVALIDATED = "invalidated"  # Market structure change or expiry


class FeatureType(Enum):
    """Types of features tracked by the system."""

    ORDER_BLOCK = "order_block"
    FAIR_VALUE_GAP = "fvg"
    MARKET_STRUCTURE = "market_structure"
    LIQUIDITY = "liquidity"


@dataclass(frozen=True)
class OrderBlock:
    """
    Immutable Order Block representation.

    An Order Block is the last opposing candle before a strong displacement move.
    Bullish OB: Last bearish candle before strong upward move (demand zone)
    Bearish OB: Last bullish candle before strong downward move (supply zone)

    Lifecycle:
    1. Created during backfill or real-time detection
    2. TOUCHED when price reaches zone boundary
    3. MITIGATED when price enters zone
    4. FILLED when zone completely consumed
    5. INVALIDATED if market structure changes

    Attributes:
        id: Unique identifier (interval_timestamp_direction)
        interval: Timeframe (e.g., '1h', '4h')
        direction: 'bullish' (demand) or 'bearish' (supply)
        high: Upper boundary of OB zone
        low: Lower boundary of OB zone
        timestamp: Candle open time when OB was formed
        candle_index: Index in buffer when detected
        displacement_size: Size of the displacement move that created this OB
        strength: Relative strength (displacement_size / avg_range)
        status: Current lifecycle status
        touch_count: Number of times price reached zone
        mitigation_percent: Percentage of zone consumed (0.0 - 1.0)
        created_at: When this feature was detected
        last_updated: Last status update time
    """

    id: str
    interval: str
    direction: str  # 'bullish' or 'bearish'
    high: float
    low: float
    timestamp: datetime
    candle_index: int
    displacement_size: float
    strength: float
    status: FeatureStatus = FeatureStatus.ACTIVE
    touch_count: int = 0
    mitigation_percent: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validate OrderBlock on creation."""
        if self.direction not in ("bullish", "bearish"):
            raise ValueError(f"Invalid direction: {self.direction}. Must be 'bullish' or 'bearish'")
        if self.high <= self.low:
            raise ValueError(f"Invalid OB zone: high ({self.high}) must be > low ({self.low})")
        if self.strength < 0:
            raise ValueError(f"Invalid strength: {self.strength}. Must be >= 0")

    @property
    def zone_high(self) -> float:
        """Upper boundary of the tradeable zone."""
        return self.high

    @property
    def zone_low(self) -> float:
        """Lower boundary of the tradeable zone."""
        return self.low

    @property
    def zone_size(self) -> float:
        """Size of the OB zone in price units."""
        return self.high - self.low

    @property
    def midpoint(self) -> float:
        """Midpoint of the OB zone."""
        return (self.high + self.low) / 2

    @property
    def is_active(self) -> bool:
        """Check if OB is still tradeable."""
        return self.status in (FeatureStatus.ACTIVE, FeatureStatus.TOUCHED)

    def with_status(self, new_status: FeatureStatus, **updates) -> "OrderBlock":
        """Create new OB with updated status (immutability pattern)."""
        return OrderBlock(
            id=self.id,
            interval=self.interval,
            direction=self.direction,
            high=self.high,
            low=self.low,
            timestamp=self.timestamp,
            candle_index=self.candle_index,
            displacement_size=self.displacement_size,
            strength=self.strength,
            status=new_status,
            touch_count=updates.get("touch_count", self.touch_count),
            mitigation_percent=updates.get("mitigation_percent", self.mitigation_percent),
            created_at=self.created_at,
            last_updated=datetime.utcnow(),
        )


@dataclass(frozen=True)
class FairValueGap:
    """
    Immutable Fair Value Gap representation.

    An FVG is an imbalance in price caused by aggressive buying/selling,
    where a gap exists between three consecutive candles.

    Bullish FVG: Gap between candle1.high and candle3.low (price moved up fast)
    Bearish FVG: Gap between candle1.low and candle3.high (price moved down fast)

    Lifecycle:
    1. Created during backfill or real-time detection
    2. TOUCHED when price reaches gap boundary
    3. MITIGATED when price fills part of gap
    4. FILLED when gap completely closed
    5. INVALIDATED if too old or structure changes

    Attributes:
        id: Unique identifier (interval_timestamp_direction)
        interval: Timeframe (e.g., '5m', '1h')
        direction: 'bullish' or 'bearish'
        gap_high: Upper boundary of the gap
        gap_low: Lower boundary of the gap
        timestamp: When the FVG was formed (middle candle time)
        candle_index: Index of middle candle when detected
        gap_size: Size of the imbalance
        status: Current lifecycle status
        fill_percent: Percentage of gap filled (0.0 - 1.0)
        created_at: When this feature was detected
        last_updated: Last status update time
    """

    id: str
    interval: str
    direction: str  # 'bullish' or 'bearish'
    gap_high: float
    gap_low: float
    timestamp: datetime
    candle_index: int
    gap_size: float
    status: FeatureStatus = FeatureStatus.ACTIVE
    fill_percent: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validate FVG on creation."""
        if self.direction not in ("bullish", "bearish"):
            raise ValueError(f"Invalid direction: {self.direction}. Must be 'bullish' or 'bearish'")
        if self.gap_high <= self.gap_low:
            raise ValueError(
                f"Invalid FVG: gap_high ({self.gap_high}) must be > gap_low ({self.gap_low})"
            )
        if self.gap_size < 0:
            raise ValueError(f"Invalid gap_size: {self.gap_size}. Must be >= 0")

    @property
    def zone_high(self) -> float:
        """Upper boundary of the tradeable zone."""
        return self.gap_high

    @property
    def zone_low(self) -> float:
        """Lower boundary of the tradeable zone."""
        return self.gap_low

    @property
    def midpoint(self) -> float:
        """Midpoint of the FVG zone."""
        return (self.gap_high + self.gap_low) / 2

    @property
    def is_active(self) -> bool:
        """Check if FVG is still tradeable."""
        return self.status in (FeatureStatus.ACTIVE, FeatureStatus.TOUCHED)

    @property
    def filled(self) -> bool:
        """
        Backward compatibility property for legacy code.

        Returns True if FVG is no longer tradeable (mitigated, filled, or invalidated).
        """
        return self.status in (FeatureStatus.MITIGATED, FeatureStatus.FILLED, FeatureStatus.INVALIDATED)

    @property
    def index(self) -> int:
        """Backward compatibility property - alias for candle_index."""
        return self.candle_index

    def with_status(self, new_status: FeatureStatus, **updates) -> "FairValueGap":
        """Create new FVG with updated status (immutability pattern)."""
        return FairValueGap(
            id=self.id,
            interval=self.interval,
            direction=self.direction,
            gap_high=self.gap_high,
            gap_low=self.gap_low,
            timestamp=self.timestamp,
            candle_index=self.candle_index,
            gap_size=self.gap_size,
            status=new_status,
            fill_percent=updates.get("fill_percent", self.fill_percent),
            created_at=self.created_at,
            last_updated=datetime.utcnow(),
        )


@dataclass(frozen=True)
class MarketStructure:
    """
    Immutable Market Structure representation.

    Tracks the current trend state based on swing highs/lows and
    Break of Structure (BOS) / Change of Character (CHoCH) events.

    States:
    - bullish: Higher highs and higher lows
    - bearish: Lower highs and lower lows
    - sideways: No clear trend direction

    Attributes:
        interval: Timeframe (e.g., '4h')
        trend: Current trend direction ('bullish', 'bearish', 'sideways')
        last_swing_high: Most recent significant high
        last_swing_low: Most recent significant low
        prev_swing_high: Previous swing high (for BOS detection)
        prev_swing_low: Previous swing low (for BOS detection)
        last_bos_price: Price where last BOS occurred
        last_bos_type: Type of last BOS ('bullish_bos', 'bearish_bos', 'choch', None)
        updated_at: When structure was last updated
    """

    interval: str
    trend: str  # 'bullish', 'bearish', 'sideways'
    last_swing_high: float
    last_swing_low: float
    prev_swing_high: Optional[float] = None
    prev_swing_low: Optional[float] = None
    last_bos_price: Optional[float] = None
    last_bos_type: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Validate MarketStructure on creation."""
        if self.trend not in ("bullish", "bearish", "sideways"):
            raise ValueError(f"Invalid trend: {self.trend}. Must be 'bullish', 'bearish', or 'sideways'")
        if self.last_swing_high <= self.last_swing_low:
            raise ValueError(
                f"Invalid swings: last_swing_high ({self.last_swing_high}) "
                f"must be > last_swing_low ({self.last_swing_low})"
            )

    @property
    def is_bullish(self) -> bool:
        """Check if trend is bullish."""
        return self.trend == "bullish"

    @property
    def is_bearish(self) -> bool:
        """Check if trend is bearish."""
        return self.trend == "bearish"

    @property
    def is_ranging(self) -> bool:
        """Check if market is sideways/ranging."""
        return self.trend == "sideways"

    @property
    def swing_range(self) -> float:
        """Current swing range (high - low)."""
        return self.last_swing_high - self.last_swing_low

    def with_update(self, **updates) -> "MarketStructure":
        """Create new MarketStructure with updates (immutability pattern)."""
        return MarketStructure(
            interval=self.interval,
            trend=updates.get("trend", self.trend),
            last_swing_high=updates.get("last_swing_high", self.last_swing_high),
            last_swing_low=updates.get("last_swing_low", self.last_swing_low),
            prev_swing_high=updates.get("prev_swing_high", self.prev_swing_high),
            prev_swing_low=updates.get("prev_swing_low", self.prev_swing_low),
            last_bos_price=updates.get("last_bos_price", self.last_bos_price),
            last_bos_type=updates.get("last_bos_type", self.last_bos_type),
            updated_at=datetime.utcnow(),
        )


@dataclass(frozen=True)
class LiquidityLevel:
    """
    Immutable Liquidity Level representation.

    Tracks significant price levels where stop losses are likely clustered:
    - BSL (Buy-Side Liquidity): Above swing highs (short stop losses)
    - SSL (Sell-Side Liquidity): Below swing lows (long stop losses)

    Attributes:
        id: Unique identifier
        interval: Timeframe
        level_type: 'bsl' or 'ssl'
        price: Price level
        strength: Number of touches that formed this level
        timestamp: When level was identified
        swept: Whether liquidity was taken
        sweep_timestamp: When liquidity was swept (if applicable)
    """

    id: str
    interval: str
    level_type: str  # 'bsl' or 'ssl'
    price: float
    strength: int
    timestamp: datetime
    swept: bool = False
    sweep_timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Validate LiquidityLevel on creation."""
        if self.level_type not in ("bsl", "ssl"):
            raise ValueError(f"Invalid level_type: {self.level_type}. Must be 'bsl' or 'ssl'")
        if self.strength < 1:
            raise ValueError(f"Invalid strength: {self.strength}. Must be >= 1")

    @property
    def is_buy_side(self) -> bool:
        """Check if this is buy-side liquidity (above price)."""
        return self.level_type == "bsl"

    @property
    def is_sell_side(self) -> bool:
        """Check if this is sell-side liquidity (below price)."""
        return self.level_type == "ssl"

    @property
    def is_active(self) -> bool:
        """Check if liquidity hasn't been swept yet."""
        return not self.swept

    def with_sweep(self) -> "LiquidityLevel":
        """Create new LiquidityLevel marked as swept."""
        return LiquidityLevel(
            id=self.id,
            interval=self.interval,
            level_type=self.level_type,
            price=self.price,
            strength=self.strength,
            timestamp=self.timestamp,
            swept=True,
            sweep_timestamp=datetime.utcnow(),
        )
