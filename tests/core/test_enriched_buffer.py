"""
Unit tests for EnrichedBuffer (Issue #6)
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.core.enriched_buffer import EnrichedBuffer
from src.models.candle import Candle


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


def create_candle(close_price: float, offset_minutes: int = 0):
    """Helper to create test candles."""
    base_time = datetime.now(timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval="5m",
        open_time=base_time + timedelta(minutes=offset_minutes),
        close_time=base_time + timedelta(minutes=offset_minutes + 5),
        open=close_price - 100,
        high=close_price + 100,
        low=close_price - 200,
        close=close_price,
        volume=100.0,
        is_closed=True,
    )


class TestEnrichedBufferInit:
    """Test EnrichedBuffer initialization."""

    def test_init_default_maxlen(self):
        """Test initialization with default maxlen."""
        buffer = EnrichedBuffer()

        assert len(buffer) == 0
        assert buffer._maxlen == 500

    def test_init_custom_maxlen(self):
        """Test initialization with custom maxlen."""
        buffer = EnrichedBuffer(maxlen=100)

        assert len(buffer) == 0
        assert buffer._maxlen == 100

    def test_init_invalid_maxlen(self):
        """Test initialization with invalid maxlen."""
        with pytest.raises(ValueError, match="maxlen must be positive"):
            EnrichedBuffer(maxlen=0)

        with pytest.raises(ValueError, match="maxlen must be positive"):
            EnrichedBuffer(maxlen=-10)


class TestAppend:
    """Test candle appending and enrichment."""

    def test_append_single_candle(self, sample_candle):
        """Test appending a single candle."""
        buffer = EnrichedBuffer(maxlen=10)

        enriched = buffer.append(sample_candle)

        assert len(buffer) == 1
        assert enriched.candle == sample_candle

    def test_append_multiple_candles(self):
        """Test appending multiple candles."""
        buffer = EnrichedBuffer(maxlen=10)

        for i in range(5):
            candle = create_candle(close_price=50000 + i * 100)
            enriched = buffer.append(candle)
            assert enriched.candle.close == 50000 + i * 100

        assert len(buffer) == 5

    def test_append_auto_eviction(self):
        """Test automatic eviction when maxlen exceeded."""
        buffer = EnrichedBuffer(maxlen=3)

        # Add 5 candles (only last 3 should remain)
        for i in range(5):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        assert len(buffer) == 3

        # Verify oldest were evicted (should have candles 2, 3, 4)
        all_candles = buffer.get_all()
        assert all_candles[0].candle.close == 50200  # Candle 2
        assert all_candles[1].candle.close == 50300  # Candle 3
        assert all_candles[2].candle.close == 50400  # Candle 4


class TestGetMethods:
    """Test buffer retrieval methods."""

    def test_get_all_empty(self):
        """Test get_all with empty buffer."""
        buffer = EnrichedBuffer()

        assert buffer.get_all() == []

    def test_get_all_with_data(self):
        """Test get_all with data."""
        buffer = EnrichedBuffer(maxlen=10)

        for i in range(3):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        all_candles = buffer.get_all()
        assert len(all_candles) == 3
        assert all_candles[0].candle.close == 50000
        assert all_candles[-1].candle.close == 50200

    def test_get_last_n(self):
        """Test get_last_n method."""
        buffer = EnrichedBuffer(maxlen=10)

        for i in range(5):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        last_3 = buffer.get_last_n(3)
        assert len(last_3) == 3
        assert last_3[0].candle.close == 50200  # Candle 2
        assert last_3[-1].candle.close == 50400  # Candle 4

    def test_get_last_n_exceeds_buffer(self):
        """Test get_last_n when N exceeds buffer size."""
        buffer = EnrichedBuffer(maxlen=10)

        for i in range(3):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        last_10 = buffer.get_last_n(10)
        assert len(last_10) == 3  # Only 3 available


class TestClear:
    """Test buffer clearing."""

    def test_clear(self):
        """Test clearing buffer."""
        buffer = EnrichedBuffer(maxlen=10)

        for i in range(5):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        assert len(buffer) == 5

        buffer.clear()
        assert len(buffer) == 0


class TestLen:
    """Test __len__ method."""

    def test_len_empty(self):
        """Test len with empty buffer."""
        buffer = EnrichedBuffer()

        assert len(buffer) == 0

    def test_len_with_data(self):
        """Test len with data."""
        buffer = EnrichedBuffer(maxlen=10)

        for i in range(7):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        assert len(buffer) == 7


class TestRepr:
    """Test string representation."""

    def test_repr_empty(self):
        """Test repr with empty buffer."""
        buffer = EnrichedBuffer(maxlen=100)

        repr_str = repr(buffer)
        assert "EnrichedBuffer" in repr_str
        assert "len=0" in repr_str
        assert "maxlen=100" in repr_str

    def test_repr_with_data(self):
        """Test repr with data."""
        buffer = EnrichedBuffer(maxlen=100)

        for i in range(5):
            candle = create_candle(close_price=50000 + i * 100)
            buffer.append(candle)

        repr_str = repr(buffer)
        assert "len=5" in repr_str
        assert "memory≈1000bytes" in repr_str  # 5 * 200 bytes


class TestIncrementalEnrichment:
    """Test incremental enrichment behavior (Phase 3 placeholder)."""

    def test_enrichment_creates_enriched_candle(self, sample_candle):
        """Test that enrichment creates EnrichedCandle."""
        buffer = EnrichedBuffer()

        enriched = buffer.append(sample_candle)

        # Verify EnrichedCandle structure (even with empty indicators)
        assert enriched.candle == sample_candle
        assert enriched.fvgs == ()  # Phase 3: Will have actual FVGs
        assert enriched.order_blocks == ()  # Phase 3: Will have actual OBs
        assert enriched.displacement is None  # Phase 3: Will detect displacement
        assert enriched.structure_break is None  # Phase 3: Will detect breaks

    def test_enrichment_incremental_context(self):
        """Test that enrichment uses incremental context."""
        buffer = EnrichedBuffer(maxlen=100)

        # Add 10 candles
        for i in range(10):
            candle = create_candle(close_price=50000 + i * 100, offset_minutes=i * 5)
            enriched = buffer.append(candle)

            # Phase 3: Verify ICT indicators calculated using last N candles
            # For now, just verify structure exists
            assert enriched.candle is not None
