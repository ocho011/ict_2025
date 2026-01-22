"""
Unit tests for EnrichedCandle model (Issue #6)
"""

from datetime import datetime, timezone

import pytest

from src.models.candle import Candle
from src.models.enriched_candle import EnrichedCandle
from src.models.ict_signals import (
    Displacement,
    StructureBreak,
)
from src.models.features import (
    FairValueGap,
    FeatureStatus,
    OrderBlock,
)


@pytest.fixture
def sample_candle():
    """Create a sample candle for testing."""
    return Candle(
        symbol="BTCUSDT",
        interval="5m",
        open_time=datetime.now(timezone.utc),
        close_time=datetime.now(timezone.utc),
        open=50000.0,
        high=50500.0,
        low=49800.0,
        close=50300.0,
        volume=100.0,
        is_closed=True,
    )


@pytest.fixture
def sample_fvg():
    """Create a sample FVG."""
    return FairValueGap(
        id="fvg_1",
        interval="5m",
        direction="bullish",
        gap_high=50100.0,
        gap_low=50000.0,
        timestamp=datetime.now(timezone.utc),
        candle_index=0,
        gap_size=100.0,
    )


@pytest.fixture
def sample_order_block():
    """Create a sample Order Block."""
    return OrderBlock(
        id="ob_1",
        interval="5m",
        direction="bullish",
        high=50200.0,
        low=50000.0,
        timestamp=datetime.now(timezone.utc),
        candle_index=0,
        displacement_size=300.0,
        strength=1.8,
    )


@pytest.fixture
def sample_displacement():
    """Create a sample Displacement."""
    return Displacement(
        index=0,
        direction="bullish",
        start_price=50000.0,
        end_price=50400.0,
        displacement_ratio=1.6,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_structure_break():
    """Create a sample Structure Break."""
    return StructureBreak(
        index=0,
        type="BOS",
        direction="bullish",
        broken_level=50200.0,
        timestamp=datetime.now(timezone.utc),
    )


class TestEnrichedCandleInit:
    """Test EnrichedCandle initialization."""

    def test_init_minimal(self, sample_candle):
        """Test initialization with only candle (no indicators)."""
        enriched = EnrichedCandle(candle=sample_candle)

        assert enriched.candle == sample_candle
        assert enriched.fvgs == ()
        assert enriched.order_blocks == ()
        assert enriched.displacement is None
        assert enriched.structure_break is None

    def test_init_with_indicators(
        self, sample_candle, sample_fvg, sample_order_block
    ):
        """Test initialization with ICT indicators."""
        enriched = EnrichedCandle(
            candle=sample_candle,
            fvgs=(sample_fvg,),
            order_blocks=(sample_order_block,),
        )

        assert len(enriched.fvgs) == 1
        assert len(enriched.order_blocks) == 1
        assert enriched.fvgs[0] == sample_fvg
        assert enriched.order_blocks[0] == sample_order_block


class TestBullishSetup:
    """Test bullish setup detection."""

    def test_has_bullish_setup_true(
        self, sample_candle, sample_fvg, sample_structure_break
    ):
        """Test bullish setup detection (FVG + BOS)."""
        enriched = EnrichedCandle(
            candle=sample_candle,
            fvgs=(sample_fvg,),
            structure_break=sample_structure_break,
        )

        assert enriched.has_bullish_setup() is True

    def test_has_bullish_setup_no_fvg(
        self, sample_candle, sample_structure_break
    ):
        """Test bullish setup fails without FVG."""
        enriched = EnrichedCandle(
            candle=sample_candle, structure_break=sample_structure_break
        )

        assert enriched.has_bullish_setup() is False

    def test_has_bullish_setup_no_bos(self, sample_candle, sample_fvg):
        """Test bullish setup fails without BOS."""
        enriched = EnrichedCandle(candle=sample_candle, fvgs=(sample_fvg,))

        assert enriched.has_bullish_setup() is False

    def test_has_bullish_setup_wrong_direction(
        self, sample_candle, sample_fvg
    ):
        """Test bullish setup fails with bearish structure break."""
        bearish_break = StructureBreak(
            index=0,
            type="BOS",
            direction="bearish",
            broken_level=50200.0,
            timestamp=datetime.now(timezone.utc),
        )
        enriched = EnrichedCandle(
            candle=sample_candle,
            fvgs=(sample_fvg,),
            structure_break=bearish_break,
        )

        assert enriched.has_bullish_setup() is False


class TestBearishSetup:
    """Test bearish setup detection."""

    def test_has_bearish_setup_true(self, sample_candle):
        """Test bearish setup detection (FVG + BOS)."""
        bearish_fvg = FairValueGap(
            id="fvg_bearish",
            interval="5m",
            direction="bearish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=0,
            gap_size=100.0,
        )
        bearish_break = StructureBreak(
            index=0,
            type="BOS",
            direction="bearish",
            broken_level=50200.0,
            timestamp=datetime.now(timezone.utc),
        )
        enriched = EnrichedCandle(
            candle=sample_candle,
            fvgs=(bearish_fvg,),
            structure_break=bearish_break,
        )

        assert enriched.has_bearish_setup() is True


class TestDisplacement:
    """Test displacement detection."""

    def test_has_displacement_true(
        self, sample_candle, sample_displacement
    ):
        """Test displacement detection with threshold."""
        enriched = EnrichedCandle(
            candle=sample_candle, displacement=sample_displacement
        )

        assert enriched.has_displacement(min_ratio=1.5) is True

    def test_has_displacement_below_threshold(
        self, sample_candle, sample_displacement
    ):
        """Test displacement fails below threshold."""
        enriched = EnrichedCandle(
            candle=sample_candle, displacement=sample_displacement
        )

        # Displacement ratio is 1.6, should fail at 1.8
        assert enriched.has_displacement(min_ratio=1.8) is False

    def test_has_displacement_none(self, sample_candle):
        """Test displacement detection with no displacement."""
        enriched = EnrichedCandle(candle=sample_candle)

        assert enriched.has_displacement() is False


class TestFVGMethods:
    """Test FVG-related methods."""

    def test_has_unfilled_fvgs(self, sample_candle):
        """Test unfilled FVG detection."""
        unfilled_fvg = FairValueGap(
            id="fvg_u",
            interval="5m",
            direction="bullish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=0,
            gap_size=100.0,
        )
        enriched = EnrichedCandle(candle=sample_candle, fvgs=(unfilled_fvg,))

        assert enriched.has_unfilled_fvgs() is True

    def test_has_unfilled_fvgs_all_filled(self, sample_candle):
        """Test unfilled FVG detection when all filled."""
        filled_fvg = FairValueGap(
            id="fvg_f",
            interval="5m",
            direction="bullish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=0,
            gap_size=100.0,
            status=FeatureStatus.FILLED,
        )
        enriched = EnrichedCandle(candle=sample_candle, fvgs=(filled_fvg,))

        assert enriched.has_unfilled_fvgs() is False

    def test_get_bullish_fvgs(self, sample_candle):
        """Test filtering bullish FVGs."""
        bullish_fvg = FairValueGap(
            id="fvg_bull",
            interval="5m",
            direction="bullish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=0,
            gap_size=100.0,
        )
        bearish_fvg = FairValueGap(
            id="fvg_bear",
            interval="5m",
            direction="bearish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=1,
            gap_size=100.0,
        )
        enriched = EnrichedCandle(
            candle=sample_candle, fvgs=(bullish_fvg, bearish_fvg)
        )

        bullish = enriched.get_bullish_fvgs()
        assert len(bullish) == 1
        assert bullish[0].direction == "bullish"

    def test_get_bearish_fvgs(self, sample_candle):
        """Test filtering bearish FVGs."""
        bullish_fvg = FairValueGap(
            id="fvg_bull",
            interval="5m",
            direction="bullish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=0,
            gap_size=100.0,
        )
        bearish_fvg = FairValueGap(
            id="fvg_bear",
            interval="5m",
            direction="bearish",
            gap_high=50100.0,
            gap_low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=1,
            gap_size=100.0,
        )
        enriched = EnrichedCandle(
            candle=sample_candle, fvgs=(bullish_fvg, bearish_fvg)
        )

        bearish = enriched.get_bearish_fvgs()
        assert len(bearish) == 1
        assert bearish[0].direction == "bearish"


class TestOrderBlockMethods:
    """Test Order Block-related methods."""

    def test_get_strongest_order_block(self, sample_candle):
        """Test getting strongest order block."""
        ob1 = OrderBlock(
            id="ob1",
            interval="5m",
            direction="bullish",
            high=50200.0,
            low=50000.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=0,
            displacement_size=300.0,
            strength=1.5,
        )
        ob2 = OrderBlock(
            id="ob2",
            interval="5m",
            direction="bullish",
            high=50300.0,
            low=50100.0,
            timestamp=datetime.now(timezone.utc),
            candle_index=1,
            displacement_size=400.0,
            strength=2.1,
        )
        enriched = EnrichedCandle(
            candle=sample_candle, order_blocks=(ob1, ob2)
        )

        strongest = enriched.get_strongest_order_block()
        assert strongest is not None
        assert strongest.strength == 2.1

    def test_get_strongest_order_block_none(self, sample_candle):
        """Test getting strongest order block when none exist."""
        enriched = EnrichedCandle(candle=sample_candle)

        assert enriched.get_strongest_order_block() is None


class TestChangeOfCharacter:
    """Test Change of Character detection."""

    def test_has_change_of_character_true(self, sample_candle):
        """Test CHoCH detection."""
        choch = StructureBreak(
            index=0,
            type="CHoCH",
            direction="bullish",
            broken_level=50200.0,
            timestamp=datetime.now(timezone.utc),
        )
        enriched = EnrichedCandle(
            candle=sample_candle, structure_break=choch
        )

        assert enriched.has_change_of_character() is True

    def test_has_change_of_character_bos(self, sample_candle):
        """Test CHoCH detection with BOS (should be False)."""
        bos = StructureBreak(
            index=0,
            type="BOS",
            direction="bullish",
            broken_level=50200.0,
            timestamp=datetime.now(timezone.utc),
        )
        enriched = EnrichedCandle(candle=sample_candle, structure_break=bos)

        assert enriched.has_change_of_character() is False


class TestIndicatorCount:
    """Test indicator counting and conviction scoring."""

    def test_indicator_count_zero(self, sample_candle):
        """Test indicator count with no indicators."""
        enriched = EnrichedCandle(candle=sample_candle)

        assert enriched.indicator_count == 0

    def test_indicator_count_all(
        self,
        sample_candle,
        sample_fvg,
        sample_order_block,
        sample_displacement,
        sample_structure_break,
    ):
        """Test indicator count with all indicators present."""
        enriched = EnrichedCandle(
            candle=sample_candle,
            fvgs=(sample_fvg,),
            order_blocks=(sample_order_block,),
            displacement=sample_displacement,
            structure_break=sample_structure_break,
        )

        assert enriched.indicator_count == 4

    def test_is_high_conviction_true(
        self,
        sample_candle,
        sample_fvg,
        sample_order_block,
        sample_displacement,
    ):
        """Test high conviction detection (3+ indicators)."""
        enriched = EnrichedCandle(
            candle=sample_candle,
            fvgs=(sample_fvg,),
            order_blocks=(sample_order_block,),
            displacement=sample_displacement,
        )

        assert enriched.is_high_conviction is True

    def test_is_high_conviction_false(self, sample_candle, sample_fvg):
        """Test high conviction fails with < 3 indicators."""
        enriched = EnrichedCandle(candle=sample_candle, fvgs=(sample_fvg,))

        assert enriched.is_high_conviction is False


class TestRepr:
    """Test string representation."""

    def test_repr(self, sample_candle, sample_fvg):
        """Test __repr__ output."""
        enriched = EnrichedCandle(candle=sample_candle, fvgs=(sample_fvg,))

        repr_str = repr(enriched)
        assert "EnrichedCandle" in repr_str
        assert "BTCUSDT" in repr_str
        assert "5m" in repr_str
        assert "fvgs=1" in repr_str
