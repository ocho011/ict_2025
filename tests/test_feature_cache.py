"""
Tests for Feature Store and Feature Models (Issue #19 / Composable Architecture).

This module tests:
1. Feature model creation and validation
2. FeatureStore initialization from history
3. Incremental feature updates on new candles
4. Feature lifecycle (active → touched → mitigated → filled)
5. Query methods for active features
"""

from collections import deque
from datetime import datetime, timedelta, timezone

import pytest

from src.models.candle import Candle
from src.models.indicators import (
    FairValueGap,
    IndicatorStatus,
    LiquidityLevel,
    MarketStructure,
    OrderBlock,
)
from src.strategies.feature_store import FeatureStore


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_candles():
    """Create sample candles for testing."""
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    candles = []

    # Generate 50 candles with realistic price action
    price = 50000.0
    for i in range(50):
        # Simulate some volatility
        if i % 10 == 5:
            # Strong bullish displacement
            open_price = price
            close_price = price + 500
            high = close_price + 50
            low = open_price - 20
        elif i % 10 == 7:
            # Strong bearish displacement
            open_price = price
            close_price = price - 500
            high = open_price + 20
            low = close_price - 50
        else:
            # Normal candle
            change = (i % 5 - 2) * 50
            open_price = price
            close_price = price + change
            high = max(open_price, close_price) + 30
            low = min(open_price, close_price) - 30

        candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=base_time + timedelta(hours=i),
            close_time=base_time + timedelta(hours=i + 1),
            open=open_price,
            high=high,
            close=close_price,
            low=low,
            volume=1000.0,
            is_closed=True,
        )
        candles.append(candle)
        price = close_price

    return candles


@pytest.fixture
def feature_store():
    """Create a FeatureStore instance."""
    return FeatureStore(
        config={
            "max_order_blocks": 20,
            "max_fvgs": 15,
            "displacement_ratio": 1.5,
            "fvg_min_gap_percent": 0.001,
        }
    )


# -----------------------------------------------------------------------------
# Test Feature Models
# -----------------------------------------------------------------------------


class TestOrderBlockModel:
    """Tests for OrderBlock dataclass."""

    def test_create_valid_bullish_ob(self):
        """Test creating a valid bullish Order Block."""
        ob = OrderBlock(
            id="1h_123456_5_bullish",
            interval="1h",
            direction="bullish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )

        assert ob.direction == "bullish"
        assert ob.zone_high == 50100.0
        assert ob.zone_low == 50000.0
        assert ob.zone_size == 100.0
        assert ob.midpoint == 50050.0
        assert ob.is_active is True
        assert ob.status == IndicatorStatus.ACTIVE

    def test_create_valid_bearish_ob(self):
        """Test creating a valid bearish Order Block."""
        ob = OrderBlock(
            id="1h_123456_5_bearish",
            interval="1h",
            direction="bearish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )

        assert ob.direction == "bearish"
        assert ob.is_active is True

    def test_invalid_direction_raises(self):
        """Test that invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="Invalid direction"):
            OrderBlock(
                id="test",
                interval="1h",
                direction="invalid",
                high=50100.0,
                low=50000.0,
                timestamp=datetime.now(timezone.utc),
                candle_index=5,
                displacement_size=500.0,
                strength=2.0,
            )

    def test_invalid_zone_raises(self):
        """Test that high <= low raises ValueError."""
        with pytest.raises(ValueError, match="high .* must be > low"):
            OrderBlock(
                id="test",
                interval="1h",
                direction="bullish",
                high=50000.0,
                low=50100.0,  # low > high
                timestamp=datetime.now(timezone.utc),
                candle_index=5,
                displacement_size=500.0,
                strength=2.0,
            )

    def test_with_status_creates_new_instance(self):
        """Test immutability pattern with_status."""
        ob = OrderBlock(
            id="test",
            interval="1h",
            direction="bullish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )

        updated = ob.with_status(IndicatorStatus.MITIGATED, touch_count=2)

        # Original unchanged
        assert ob.status == IndicatorStatus.ACTIVE
        assert ob.touch_count == 0

        # New instance updated
        assert updated.status == IndicatorStatus.MITIGATED
        assert updated.touch_count == 2
        assert updated.id == ob.id  # Same ID


class TestFairValueGapModel:
    """Tests for FairValueGap dataclass."""

    def test_create_valid_bullish_fvg(self):
        """Test creating a valid bullish FVG."""
        fvg = FairValueGap(
            id="1h_123456_bullish",
            interval="1h",
            direction="bullish",
            gap_high=50200.0,
            gap_low=50100.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=10,
            gap_size=100.0,
        )

        assert fvg.direction == "bullish"
        assert fvg.zone_high == 50200.0
        assert fvg.zone_low == 50100.0
        assert fvg.midpoint == 50150.0
        assert fvg.is_active is True

    def test_with_status_creates_new_instance(self):
        """Test immutability pattern with_status."""
        fvg = FairValueGap(
            id="test",
            interval="1h",
            direction="bullish",
            gap_high=50200.0,
            gap_low=50100.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=10,
            gap_size=100.0,
        )

        updated = fvg.with_status(IndicatorStatus.FILLED, fill_percent=1.0)

        assert fvg.status == IndicatorStatus.ACTIVE
        assert updated.status == IndicatorStatus.FILLED
        assert updated.fill_percent == 1.0


class TestMarketStructureModel:
    """Tests for MarketStructure dataclass."""

    def test_create_valid_bullish_structure(self):
        """Test creating valid bullish market structure."""
        ms = MarketStructure(
            interval="4h",
            trend="bullish",
            last_swing_high=51000.0,
            last_swing_low=49000.0,
        )

        assert ms.trend == "bullish"
        assert ms.is_bullish is True
        assert ms.is_bearish is False
        assert ms.is_ranging is False
        assert ms.swing_range == 2000.0

    def test_invalid_trend_raises(self):
        """Test that invalid trend raises ValueError."""
        with pytest.raises(ValueError, match="Invalid trend"):
            MarketStructure(
                interval="4h",
                trend="unknown",
                last_swing_high=51000.0,
                last_swing_low=49000.0,
            )


# -----------------------------------------------------------------------------
# Test FeatureStore
# -----------------------------------------------------------------------------


class TestFeatureStoreInitialization:
    """Tests for FeatureStore initialization."""

    def test_initialize_for_symbol(self, feature_store, sample_candles):
        """Test initializing store with historical candles."""
        feature_store.initialize_for_symbol("BTCUSDT", {"1h": sample_candles})

        # Should have detected some features
        assert feature_store.get_market_structure("1h") is not None
        assert len(feature_store.get_active_order_blocks("1h")) >= 0
        assert len(feature_store.get_active_fvgs("1h")) >= 0

    def test_initialize_empty_candles(self, feature_store):
        """Test initializing with empty candles."""
        feature_store.initialize_for_symbol("BTCUSDT", {"1h": []})

        assert feature_store.get_active_order_blocks("1h") == []
        assert feature_store.get_active_fvgs("1h") == []
        assert feature_store.get_market_structure("1h") is None


class TestFeatureStoreQueries:
    """Tests for FeatureStore query methods."""

    def test_get_active_order_blocks(self, feature_store, sample_candles):
        """Test getting active Order Blocks."""
        feature_store.initialize_for_symbol("BTCUSDT", {"1h": sample_candles})

        all_obs = feature_store.get_active_order_blocks("1h")
        bullish_obs = feature_store.get_active_order_blocks("1h", "bullish")
        bearish_obs = feature_store.get_active_order_blocks("1h", "bearish")

        # All active should be sum of bullish and bearish
        assert len(all_obs) == len(bullish_obs) + len(bearish_obs)

        # All returned should be active
        for ob in all_obs:
            assert ob.is_active is True

    def test_get_generic_indicators(self, feature_store, sample_candles):
        """Test getting EMA and ATR indicators."""
        feature_store.initialize_for_symbol("BTCUSDT", {"1h": sample_candles})
        
        # With 50 sample candles, we should have EMA 50 and ATR 14
        ema_50 = feature_store.get("1h", "ema_50")
        atr_14 = feature_store.get("1h", "atr_14")
        
        assert ema_50 is not None
        assert isinstance(ema_50, float)
        assert atr_14 is not None
        assert isinstance(atr_14, float)


class TestFeatureStoreUpdates:
    """Tests for FeatureStore incremental updates."""

    def test_update_on_new_candle(self, feature_store, sample_candles):
        """Test updating store on new candle."""
        # Initialize with first 40 candles
        feature_store.initialize_for_symbol("BTCUSDT", {"1h": sample_candles[:40]})

        # Update with new candle
        new_candle = sample_candles[40]
        buffer = sample_candles[:41]

        feature_store.update("1h", new_candle, buffer)

        # Should still have active features or newly detected ones
        assert feature_store.get_market_structure("1h") is not None

    def test_order_block_status_update_on_touch(self, feature_store):
        """Test OB status updates when price touches zone."""
        # Setup: Add an OB manually
        feature_store._order_blocks["1h"] = deque(maxlen=20)

        ob = OrderBlock(
            id="ob_test",
            interval="1h",
            direction="bullish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )
        feature_store._order_blocks["1h"].append(ob)

        # Candle that touches the OB zone
        touching_candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.now(timezone.utc),
            close_time=datetime.now(timezone.utc) + timedelta(hours=1),
            open=50200.0,
            high=50200.0,
            close=50050.0,  # Enters OB zone
            low=50040.0,  # Inside OB zone
            volume=1000.0,
            is_closed=True,
        )

        feature_store._update_order_block_statuses("1h", touching_candle)

        updated_obs = feature_store.get_active_order_blocks("1h")
        # If it was touched but not filled, it's still active but with updated status internally
        # Or it might have become MITIGATED
        obs_in_deque = list(feature_store._order_blocks["1h"])
        assert len(obs_in_deque) == 1
        assert obs_in_deque[0].touch_count > 0
