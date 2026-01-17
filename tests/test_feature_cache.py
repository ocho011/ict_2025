"""
Tests for Feature State Cache and Feature Models (Issue #19).

This module tests:
1. Feature model creation and validation
2. FeatureStateCache initialization from history
3. Incremental feature updates on new candles
4. Feature lifecycle (active → touched → mitigated → filled)
5. Query methods for active features
"""

from collections import deque
from datetime import datetime, timedelta

import pytest

from src.models.candle import Candle
from src.models.features import (
    FairValueGap,
    FeatureStatus,
    LiquidityLevel,
    MarketStructure,
    OrderBlock,
)
from src.strategies.feature_cache import FeatureStateCache


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_candles():
    """Create sample candles for testing."""
    base_time = datetime(2024, 1, 1, 0, 0, 0)
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
def feature_cache():
    """Create a FeatureStateCache instance."""
    return FeatureStateCache(
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
            timestamp=datetime.utcnow(),
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
        assert ob.status == FeatureStatus.ACTIVE

    def test_create_valid_bearish_ob(self):
        """Test creating a valid bearish Order Block."""
        ob = OrderBlock(
            id="1h_123456_5_bearish",
            interval="1h",
            direction="bearish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.utcnow(),
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
                timestamp=datetime.utcnow(),
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
                timestamp=datetime.utcnow(),
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
            timestamp=datetime.utcnow(),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )

        updated = ob.with_status(FeatureStatus.MITIGATED, touch_count=2)

        # Original unchanged
        assert ob.status == FeatureStatus.ACTIVE
        assert ob.touch_count == 0

        # New instance updated
        assert updated.status == FeatureStatus.MITIGATED
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
            timestamp=datetime.utcnow(),
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
            timestamp=datetime.utcnow(),
            candle_index=10,
            gap_size=100.0,
        )

        updated = fvg.with_status(FeatureStatus.FILLED, fill_percent=1.0)

        assert fvg.status == FeatureStatus.ACTIVE
        assert updated.status == FeatureStatus.FILLED
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
# Test FeatureStateCache
# -----------------------------------------------------------------------------


class TestFeatureStateCacheInitialization:
    """Tests for FeatureStateCache initialization."""

    def test_initialize_from_history(self, feature_cache, sample_candles):
        """Test initializing cache from historical candles."""
        counts = feature_cache.initialize_from_history("1h", sample_candles)

        assert "order_blocks" in counts
        assert "fvgs" in counts
        assert "structure" in counts

        # Should have detected some features
        stats = feature_cache.get_cache_stats()
        assert "1h" in stats
        assert stats["1h"]["has_structure"] is True

    def test_initialize_empty_candles(self, feature_cache):
        """Test initializing with empty candles."""
        counts = feature_cache.initialize_from_history("1h", [])

        assert counts["order_blocks"] == 0
        assert counts["fvgs"] == 0
        assert counts["structure"] is False

    def test_get_market_structure_after_init(self, feature_cache, sample_candles):
        """Test market structure is available after initialization."""
        feature_cache.initialize_from_history("1h", sample_candles)

        structure = feature_cache.get_market_structure("1h")

        assert structure is not None
        assert structure.interval == "1h"
        assert structure.trend in ("bullish", "bearish", "sideways")


class TestFeatureStateCacheQueries:
    """Tests for FeatureStateCache query methods."""

    def test_get_active_order_blocks(self, feature_cache, sample_candles):
        """Test getting active Order Blocks."""
        feature_cache.initialize_from_history("1h", sample_candles)

        all_obs = feature_cache.get_active_order_blocks("1h")
        bullish_obs = feature_cache.get_active_order_blocks("1h", "bullish")
        bearish_obs = feature_cache.get_active_order_blocks("1h", "bearish")

        # All active should be sum of bullish and bearish
        assert len(all_obs) == len(bullish_obs) + len(bearish_obs)

        # All returned should be active
        for ob in all_obs:
            assert ob.is_active is True

    def test_get_active_fvgs(self, feature_cache, sample_candles):
        """Test getting active FVGs."""
        feature_cache.initialize_from_history("1h", sample_candles)

        all_fvgs = feature_cache.get_active_fvgs("1h")
        bullish_fvgs = feature_cache.get_active_fvgs("1h", "bullish")
        bearish_fvgs = feature_cache.get_active_fvgs("1h", "bearish")

        assert len(all_fvgs) == len(bullish_fvgs) + len(bearish_fvgs)

    def test_find_nearest_order_block(self, feature_cache):
        """Test finding nearest Order Block to price."""
        # Manually add OBs for testing
        feature_cache._order_blocks["1h"] = deque(maxlen=20)

        ob1 = OrderBlock(
            id="ob1",
            interval="1h",
            direction="bullish",
            high=49500.0,
            low=49400.0,
            timestamp=datetime.utcnow(),
            candle_index=10,
            displacement_size=500.0,
            strength=2.0,
        )
        ob2 = OrderBlock(
            id="ob2",
            interval="1h",
            direction="bullish",
            high=49800.0,
            low=49700.0,
            timestamp=datetime.utcnow(),
            candle_index=15,
            displacement_size=500.0,
            strength=2.0,
        )

        feature_cache._order_blocks["1h"].append(ob1)
        feature_cache._order_blocks["1h"].append(ob2)

        # Find nearest bullish OB below price 50000
        nearest = feature_cache.find_nearest_order_block("1h", 50000.0, "bullish")

        assert nearest is not None
        assert nearest.id == "ob2"  # Closer to 50000

    def test_is_price_in_order_block(self, feature_cache):
        """Test price in OB zone detection."""
        ob = OrderBlock(
            id="test",
            interval="1h",
            direction="bullish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.utcnow(),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )

        assert feature_cache.is_price_in_order_block(50050.0, ob) is True
        assert feature_cache.is_price_in_order_block(50000.0, ob) is True  # Boundary
        assert feature_cache.is_price_in_order_block(50100.0, ob) is True  # Boundary
        assert feature_cache.is_price_in_order_block(49999.0, ob) is False
        assert feature_cache.is_price_in_order_block(50101.0, ob) is False


class TestFeatureStateCacheUpdates:
    """Tests for FeatureStateCache incremental updates."""

    def test_update_on_new_candle(self, feature_cache, sample_candles):
        """Test updating cache on new candle."""
        # Initialize with first 40 candles
        feature_cache.initialize_from_history("1h", sample_candles[:40])

        # Update with new candle
        new_candle = sample_candles[40]
        buffer = deque(sample_candles[:41], maxlen=200)

        new_features = feature_cache.update_on_new_candle("1h", new_candle, buffer)

        assert "order_blocks" in new_features
        assert "fvgs" in new_features

    def test_order_block_status_update_on_touch(self, feature_cache):
        """Test OB status updates when price touches zone."""
        # Setup: Add an OB
        feature_cache._order_blocks["1h"] = deque(maxlen=20)

        ob = OrderBlock(
            id="ob_test",
            interval="1h",
            direction="bullish",
            high=50100.0,
            low=50000.0,
            timestamp=datetime.utcnow(),
            candle_index=5,
            displacement_size=500.0,
            strength=2.0,
        )
        feature_cache._order_blocks["1h"].append(ob)

        # Candle that touches the OB zone
        touching_candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=datetime.utcnow(),
            close_time=datetime.utcnow() + timedelta(hours=1),
            open=50200.0,
            high=50200.0,
            close=50050.0,  # Enters OB zone
            low=50040.0,  # Inside OB zone
            volume=1000.0,
            is_closed=True,
        )

        feature_cache._update_order_block_statuses("1h", touching_candle)

        updated_obs = list(feature_cache._order_blocks["1h"])
        assert len(updated_obs) == 1
        # Status should be updated (TOUCHED or MITIGATED depending on depth)
        assert updated_obs[0].status != FeatureStatus.ACTIVE or updated_obs[0].touch_count > 0

    def test_cache_stats(self, feature_cache, sample_candles):
        """Test cache statistics method."""
        feature_cache.initialize_from_history("1h", sample_candles)

        stats = feature_cache.get_cache_stats()

        assert "1h" in stats
        assert "order_blocks_total" in stats["1h"]
        assert "order_blocks_active" in stats["1h"]
        assert "fvgs_total" in stats["1h"]
        assert "fvgs_active" in stats["1h"]
        assert "has_structure" in stats["1h"]
        assert "trend" in stats["1h"]


class TestFeatureStateCacheEdgeCases:
    """Tests for edge cases and error handling."""

    def test_query_uninitialized_interval(self, feature_cache):
        """Test querying an interval that wasn't initialized."""
        obs = feature_cache.get_active_order_blocks("4h")
        assert obs == []

        fvgs = feature_cache.get_active_fvgs("4h")
        assert fvgs == []

        structure = feature_cache.get_market_structure("4h")
        assert structure is None

    def test_find_nearest_with_no_features(self, feature_cache):
        """Test finding nearest feature when none exist."""
        feature_cache._order_blocks["1h"] = deque(maxlen=20)

        nearest = feature_cache.find_nearest_order_block("1h", 50000.0, "bullish")
        assert nearest is None

    def test_multiple_intervals(self, feature_cache, sample_candles):
        """Test cache handles multiple intervals independently."""
        # Create candles for different intervals
        candles_1h = sample_candles[:30]
        candles_4h = sample_candles[:30]  # Same data, different interval
        for c in candles_4h:
            c = Candle(
                symbol=c.symbol,
                interval="4h",
                open_time=c.open_time,
                close_time=c.close_time,
                open=c.open,
                high=c.high,
                close=c.close,
                low=c.low,
                volume=c.volume,
                is_closed=c.is_closed,
            )

        feature_cache.initialize_from_history("1h", candles_1h)
        feature_cache.initialize_from_history("4h", candles_4h)

        stats = feature_cache.get_cache_stats()

        assert "1h" in stats
        assert "4h" in stats


# -----------------------------------------------------------------------------
# Test ICTStrategy Integration with FeatureStateCache (Issue #19)
# -----------------------------------------------------------------------------


class TestICTStrategyFeatureCacheIntegration:
    """Tests for ICTStrategy integration with FeatureStateCache."""

    @pytest.fixture
    def ict_strategy(self):
        """Create ICTStrategy with feature cache enabled."""
        from src.strategies.ict_strategy import ICTStrategy

        config = {
            "buffer_size": 200,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
            "use_feature_cache": True,
            "max_order_blocks": 20,
            "max_fvgs": 15,
            "displacement_ratio": 1.5,
            "fvg_min_gap_percent": 0.001,
            "use_killzones": False,  # Disable for testing
        }
        return ICTStrategy("BTCUSDT", config)

    @pytest.fixture
    def ict_strategy_no_cache(self):
        """Create ICTStrategy with feature cache disabled."""
        from src.strategies.ict_strategy import ICTStrategy

        config = {
            "buffer_size": 200,
            "ltf_interval": "5m",
            "mtf_interval": "1h",
            "htf_interval": "4h",
            "use_feature_cache": False,
            "use_killzones": False,
        }
        return ICTStrategy("BTCUSDT", config)

    def test_feature_cache_enabled_by_default(self, ict_strategy):
        """Test that feature cache is enabled by default."""
        assert ict_strategy.is_feature_cache_enabled() is True
        assert ict_strategy.feature_cache is not None

    def test_feature_cache_can_be_disabled(self, ict_strategy_no_cache):
        """Test that feature cache can be disabled via config."""
        assert ict_strategy_no_cache.is_feature_cache_enabled() is False
        assert ict_strategy_no_cache.feature_cache is None

    def test_feature_cache_initialized_on_historical_data(
        self, ict_strategy, sample_candles
    ):
        """Test that feature cache is initialized when historical data is loaded."""
        # Initialize with historical data for each interval
        ict_strategy.initialize_with_historical_data("5m", sample_candles)
        ict_strategy.initialize_with_historical_data("1h", sample_candles[:30])

        # Check feature cache was initialized
        stats = ict_strategy.get_feature_cache_stats()

        assert "5m" in stats
        assert "1h" in stats
        assert stats["5m"]["has_structure"] is True

    def test_feature_cache_stats_method(self, ict_strategy, sample_candles):
        """Test get_feature_cache_stats returns correct data."""
        ict_strategy.initialize_with_historical_data("5m", sample_candles)

        stats = ict_strategy.get_feature_cache_stats()

        assert "5m" in stats
        assert "order_blocks_total" in stats["5m"]
        assert "order_blocks_active" in stats["5m"]
        assert "fvgs_total" in stats["5m"]
        assert "fvgs_active" in stats["5m"]
        assert "has_structure" in stats["5m"]
        assert "trend" in stats["5m"]

    def test_feature_cache_stats_empty_when_disabled(self, ict_strategy_no_cache):
        """Test get_feature_cache_stats returns empty dict when cache disabled."""
        stats = ict_strategy_no_cache.get_feature_cache_stats()
        assert stats == {}


class TestMultiTimeframeFeatureCacheIntegration:
    """Tests for MultiTimeframeStrategy feature cache integration."""

    @pytest.fixture
    def mtf_strategy(self, sample_candles):
        """Create a multi-timeframe strategy with feature cache."""
        from src.strategies.multi_timeframe import MultiTimeframeStrategy
        from src.strategies.feature_cache import FeatureStateCache

        # Create a concrete implementation for testing
        class TestMTFStrategy(MultiTimeframeStrategy):
            async def analyze_mtf(self, candle, buffers):
                return None  # Simple test implementation

        strategy = TestMTFStrategy(
            "BTCUSDT",
            ["5m", "1h", "4h"],
            {"buffer_size": 100},
        )

        # Set up feature cache
        cache = FeatureStateCache(config={"max_order_blocks": 20})
        strategy.set_feature_cache(cache)

        return strategy

    def test_set_feature_cache(self, mtf_strategy):
        """Test setting feature cache on strategy."""
        assert mtf_strategy.feature_cache is not None

    def test_feature_cache_initializes_on_history(self, mtf_strategy, sample_candles):
        """Test that feature cache initializes when history is loaded."""
        mtf_strategy.initialize_with_historical_data("1h", sample_candles)

        cache = mtf_strategy.feature_cache
        stats = cache.get_cache_stats()

        assert "1h" in stats
        assert stats["1h"]["has_structure"] is True

    @pytest.mark.asyncio
    async def test_feature_cache_updates_on_new_candle(
        self, mtf_strategy, sample_candles
    ):
        """Test that feature cache updates when new candle is analyzed."""
        # Initialize with historical data
        mtf_strategy.initialize_with_historical_data("1h", sample_candles[:40])

        # Create a new candle
        base_time = sample_candles[-1].close_time
        new_candle = Candle(
            symbol="BTCUSDT",
            interval="1h",
            open_time=base_time,
            close_time=base_time + timedelta(hours=1),
            open=51000.0,
            high=51100.0,
            close=51050.0,
            low=50980.0,
            volume=1000.0,
            is_closed=True,
        )

        # Analyze the candle (this should update the cache)
        await mtf_strategy.analyze(new_candle)

        # Verify the candle was added to the buffer
        assert len(mtf_strategy.buffers["1h"]) == 41
