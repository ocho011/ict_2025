"""Unit tests for BufferManager extracted from BaseStrategy."""

from collections import deque
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.models.candle import Candle
from src.strategies.buffer_manager import BufferManager


def _make_candle(interval: str = "5m", close: float = 100.0, index: int = 0) -> Candle:
    """Helper to create test candles."""
    total_minutes = index * 5
    ts = datetime(2024, 1, 1, total_minutes // 60, total_minutes % 60, tzinfo=timezone.utc)
    return Candle(
        symbol="BTCUSDT",
        interval=interval,
        open_time=ts,
        close_time=ts,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=100.0,
        is_closed=True,
    )


class TestBufferManagerInit:
    """Test initialization."""

    def test_single_interval(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        assert bm.intervals == ["5m"]
        assert "5m" in bm.buffers
        assert len(bm.buffers["5m"]) == 0

    def test_multi_interval(self):
        bm = BufferManager(buffer_size=50, intervals=["5m", "1h", "4h"])
        assert len(bm.intervals) == 3
        assert all(iv in bm.buffers for iv in ["5m", "1h", "4h"])

    def test_all_not_ready_initially(self):
        bm = BufferManager(buffer_size=100, intervals=["5m", "1h"])
        assert not bm.is_all_ready()

    def test_buffer_maxlen(self):
        bm = BufferManager(buffer_size=10, intervals=["5m"])
        assert bm.buffers["5m"].maxlen == 10


class TestBufferManagerInitialize:
    """Test historical data initialization."""

    def test_initialize_populates_buffer(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        candles = [_make_candle("5m", close=100 + i, index=i) for i in range(50)]
        bm.initialize(candles, interval="5m")
        assert len(bm.buffers["5m"]) == 50
        assert bm._initialized["5m"] is True

    def test_initialize_respects_maxlen(self):
        bm = BufferManager(buffer_size=10, intervals=["5m"])
        candles = [_make_candle("5m", close=100 + i, index=i) for i in range(20)]
        bm.initialize(candles, interval="5m")
        assert len(bm.buffers["5m"]) == 10
        # Should keep most recent 10
        assert bm.buffers["5m"][-1].close == 119.0

    def test_initialize_empty_candles(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        bm.initialize([], interval="5m")
        assert len(bm.buffers["5m"]) == 0
        assert bm._initialized["5m"] is True

    def test_initialize_auto_registers_unknown_interval(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        candles = [_make_candle("1h", close=100, index=0)]
        bm.initialize(candles, interval="1h")
        assert "1h" in bm.buffers
        assert "1h" in bm.intervals

    def test_initialize_callback_invoked(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        candles = [_make_candle("5m", close=100 + i, index=i) for i in range(5)]
        callback = MagicMock()
        bm.initialize(candles, interval="5m", on_initialized=callback)
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "5m"
        assert len(args[1]) == 5

    def test_initialize_callback_not_invoked_when_empty(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        callback = MagicMock()
        bm.initialize([], interval="5m", on_initialized=callback)
        callback.assert_not_called()

    def test_initialize_auto_detects_interval_from_candle(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        candles = [_make_candle("5m", close=100, index=0)]
        bm.initialize(candles)  # No explicit interval
        assert len(bm.buffers["5m"]) == 1


class TestBufferManagerUpdate:
    """Test real-time candle updates."""

    def test_update_appends_to_correct_buffer(self):
        bm = BufferManager(buffer_size=100, intervals=["5m", "1h"])
        bm.update(_make_candle("5m", close=100))
        bm.update(_make_candle("1h", close=200))
        assert len(bm.buffers["5m"]) == 1
        assert len(bm.buffers["1h"]) == 1

    def test_update_auto_registers_unknown_interval(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        bm.update(_make_candle("15m", close=100))
        assert "15m" in bm.buffers
        assert "15m" in bm.intervals
        assert bm._initialized["15m"] is True

    def test_update_fifo_eviction(self):
        bm = BufferManager(buffer_size=3, intervals=["5m"])
        for i in range(5):
            bm.update(_make_candle("5m", close=100 + i, index=i))
        assert len(bm.buffers["5m"]) == 3
        # Oldest should be evicted, newest kept
        assert bm.buffers["5m"][0].close == 102.0
        assert bm.buffers["5m"][-1].close == 104.0


class TestBufferManagerQueries:
    """Test query methods."""

    def test_get_latest(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        for i in range(10):
            bm.update(_make_candle("5m", close=100 + i, index=i))
        result = bm.get_latest(3, "5m")
        assert len(result) == 3
        assert result[-1].close == 109.0

    def test_get_latest_insufficient_data(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        bm.update(_make_candle("5m", close=100))
        assert bm.get_latest(5, "5m") == []

    def test_get_latest_unknown_interval(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        assert bm.get_latest(5, "1h") == []

    def test_get_current_size(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        assert bm.get_current_size("5m") == 0
        bm.update(_make_candle("5m", close=100))
        assert bm.get_current_size("5m") == 1

    def test_get_current_size_unknown_interval(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        assert bm.get_current_size("1h") == 0

    def test_is_buffer_ready(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        assert not bm.is_buffer_ready(5, "5m")
        for i in range(5):
            bm.update(_make_candle("5m", close=100 + i, index=i))
        assert bm.is_buffer_ready(5, "5m")
        assert not bm.is_buffer_ready(6, "5m")

    def test_is_all_ready(self):
        bm = BufferManager(buffer_size=100, intervals=["5m", "1h"])
        assert not bm.is_all_ready()
        bm.initialize([_make_candle("5m")], interval="5m")
        assert not bm.is_all_ready()
        bm.initialize([_make_candle("1h")], interval="1h")
        assert bm.is_all_ready()

    def test_default_interval_used_when_none(self):
        bm = BufferManager(buffer_size=100, intervals=["5m"])
        bm.update(_make_candle("5m", close=100))
        # None interval should default to first registered
        assert bm.get_current_size(None) == 1
        assert bm.get_latest(1, None) == [bm.buffers["5m"][-1]]
        assert bm.is_buffer_ready(1, None) is True
