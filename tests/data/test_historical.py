"""Tests for HistoricalDataProvider."""

import asyncio
import csv
from datetime import datetime
from pathlib import Path

import pytest

from src.data.base import MarketDataProvider
from src.data.historical import HistoricalDataProvider, ReplayMode
from src.models.candle import Candle

try:
    from src.core.data_collector import BinanceDataCollector
    _HAS_BINANCE = True
except ImportError:
    _HAS_BINANCE = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_candles():
    """10 BTCUSDT 1m candles with realistic prices."""
    candles = []
    base_price = 50000.0
    for i in range(10):
        open_time = datetime(2025, 1, 1, 0, i)
        close_time = datetime(2025, 1, 1, 0, i, 59)
        price = base_price + i * 100.0
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval="1m",
                open_time=open_time,
                open=price,
                high=price + 50.0,
                low=price - 50.0,
                close=price + 20.0,
                volume=10.5 + i,
                close_time=close_time,
                is_closed=True,
            )
        )
    return candles


@pytest.fixture
def provider(sample_candles):
    """HistoricalDataProvider pre-loaded with sample BTCUSDT/1m candles."""
    candle_data = {"BTCUSDT": {"1m": sample_candles}}
    return HistoricalDataProvider(candle_data, replay_mode=ReplayMode.INSTANT)


@pytest.fixture
def csv_file(tmp_path, sample_candles):
    """Write sample_candles to a temp CSV file and return its path."""
    path = tmp_path / "btcusdt_1m.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
        for c in sample_candles:
            writer.writerow([
                c.open_time.strftime("%Y-%m-%d %H:%M:%S"),
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume,
                c.close_time.strftime("%Y-%m-%d %H:%M:%S"),
            ])
    return str(path)


# ---------------------------------------------------------------------------
# TestGetHistoricalCandles
# ---------------------------------------------------------------------------


class TestGetHistoricalCandles:
    """Tests for get_historical_candles cursor and bounds behaviour."""

    def test_returns_requested_limit(self, provider):
        candles = provider.get_historical_candles("BTCUSDT", "1m", limit=5)
        assert len(candles) == 5

    def test_advances_cursor(self, provider):
        first = provider.get_historical_candles("BTCUSDT", "1m", limit=3)
        second = provider.get_historical_candles("BTCUSDT", "1m", limit=3)
        first_times = {c.open_time for c in first}
        second_times = {c.open_time for c in second}
        assert first_times.isdisjoint(second_times)

    def test_respects_data_bounds(self, provider):
        # Request more candles than available (10 total)
        candles = provider.get_historical_candles("BTCUSDT", "1m", limit=100)
        assert len(candles) == 10

    def test_unknown_symbol_returns_empty(self, provider):
        candles = provider.get_historical_candles("ETHUSDT", "1m", limit=5)
        assert candles == []


# ---------------------------------------------------------------------------
# TestStartStreaming
# ---------------------------------------------------------------------------


class TestStartStreaming:
    """Tests for start_streaming replay behaviour."""

    @pytest.mark.asyncio
    async def test_replays_remaining_candles(self, provider):
        provider.get_historical_candles("BTCUSDT", "1m", limit=3)
        received = []
        provider._on_candle_callback = lambda c: received.append(c)
        await provider.start_streaming()
        assert len(received) == 7

    @pytest.mark.asyncio
    async def test_replay_instant_mode(self, provider):
        provider._on_candle_callback = lambda c: None
        # Should complete near-instantly in INSTANT mode
        await asyncio.wait_for(provider.start_streaming(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_stop_halts_replay(self, sample_candles):
        # Use FAST mode so there are small delays that allow stop() to interrupt
        candle_data = {"BTCUSDT": {"1m": sample_candles}}
        prov = HistoricalDataProvider(candle_data, replay_mode=ReplayMode.FAST)
        received = []

        async def _run():
            prov._on_candle_callback = lambda c: received.append(c)
            await prov.start_streaming()

        task = asyncio.create_task(_run())
        # Let a couple of candles through then stop
        await asyncio.sleep(0.005)
        await prov.stop()
        await task
        assert len(received) < 10

    @pytest.mark.asyncio
    async def test_callback_receives_all_candles(self, provider):
        received = []
        provider._on_candle_callback = lambda c: received.append(c)
        await provider.start_streaming()
        assert len(received) == 10

    @pytest.mark.asyncio
    async def test_is_running_during_replay(self, sample_candles):
        # Use FAST mode so streaming takes a moment
        candle_data = {"BTCUSDT": {"1m": sample_candles}}
        prov = HistoricalDataProvider(candle_data, replay_mode=ReplayMode.FAST)
        running_states = []

        def _cb(c):
            running_states.append(prov.is_running)

        prov._on_candle_callback = _cb
        assert prov.is_running is False
        await prov.start_streaming()
        # All callbacks should have seen is_running == True
        assert all(running_states)
        # After completion it should be False
        assert prov.is_running is False


# ---------------------------------------------------------------------------
# TestFromCsv
# ---------------------------------------------------------------------------


class TestFromCsv:
    """Tests for the from_csv class method."""

    def test_loads_csv_correctly(self, csv_file, sample_candles):
        prov = HistoricalDataProvider.from_csv({"BTCUSDT": {"1m": csv_file}})
        candles = prov.get_historical_candles("BTCUSDT", "1m", limit=100)
        assert len(candles) == len(sample_candles)
        assert candles[0].open == sample_candles[0].open
        assert candles[0].open_time == sample_candles[0].open_time
        assert candles[-1].close == sample_candles[-1].close

    def test_malformed_row_skipped(self, tmp_path, sample_candles):
        path = tmp_path / "bad.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
            # Good row
            c = sample_candles[0]
            writer.writerow([
                c.open_time.strftime("%Y-%m-%d %H:%M:%S"),
                c.open, c.high, c.low, c.close, c.volume,
                c.close_time.strftime("%Y-%m-%d %H:%M:%S"),
            ])
            # Bad row — non-numeric price
            writer.writerow(["2025-01-01 00:01:00", "bad", "bad", "bad", "bad", "bad", "2025-01-01 00:01:59"])
            # Another good row
            c2 = sample_candles[1]
            writer.writerow([
                c2.open_time.strftime("%Y-%m-%d %H:%M:%S"),
                c2.open, c2.high, c2.low, c2.close, c2.volume,
                c2.close_time.strftime("%Y-%m-%d %H:%M:%S"),
            ])

        prov = HistoricalDataProvider.from_csv({"BTCUSDT": {"1m": str(path)}})
        candles = prov.get_historical_candles("BTCUSDT", "1m", limit=100)
        assert len(candles) == 2


# ---------------------------------------------------------------------------
# TestProperties
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests for symbols, intervals, and on_candle_callback properties."""

    def test_symbols(self, provider):
        assert provider.symbols == ["BTCUSDT"]

    def test_symbols_multiple(self, sample_candles):
        eth_candles = [
            Candle(
                symbol="ETHUSDT",
                interval="1m",
                open_time=datetime(2025, 1, 1, 0, i),
                open=3000.0,
                high=3050.0,
                low=2950.0,
                close=3020.0,
                volume=100.0,
                close_time=datetime(2025, 1, 1, 0, i, 59),
                is_closed=True,
            )
            for i in range(5)
        ]
        candle_data = {"BTCUSDT": {"1m": sample_candles}, "ETHUSDT": {"1m": eth_candles}}
        prov = HistoricalDataProvider(candle_data)
        assert set(prov.symbols) == {"BTCUSDT", "ETHUSDT"}

    def test_intervals(self, provider):
        assert provider.intervals == ["1m"]

    def test_intervals_no_duplicates(self, sample_candles):
        candle_data = {
            "BTCUSDT": {"1m": sample_candles, "5m": sample_candles[:5]},
            "ETHUSDT": {"1m": sample_candles[:3]},
        }
        prov = HistoricalDataProvider(candle_data)
        ivs = prov.intervals
        assert len(ivs) == len(set(ivs))
        assert set(ivs) == {"1m", "5m"}

    def test_on_candle_callback(self, sample_candles):
        received = []
        cb = lambda c: received.append(c)
        candle_data = {"BTCUSDT": {"1m": sample_candles}}
        prov = HistoricalDataProvider(candle_data, on_candle_callback=cb)
        assert prov.on_candle_callback is cb

    def test_on_candle_callback_none_by_default(self, provider):
        assert provider.on_candle_callback is None


# ---------------------------------------------------------------------------
# TestMarketDataProviderABC
# ---------------------------------------------------------------------------


class TestMarketDataProviderABC:
    """Tests for ABC conformance."""

    def test_is_subclass(self):
        assert issubclass(HistoricalDataProvider, MarketDataProvider)

    @pytest.mark.skipif(not _HAS_BINANCE, reason="BinanceDataCollector not importable")
    def test_binance_is_subclass(self):
        assert issubclass(BinanceDataCollector, MarketDataProvider)
