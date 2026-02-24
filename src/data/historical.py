"""Historical data provider for backtesting via CSV replay."""

import asyncio
import csv
import logging
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional

from src.data.base import MarketDataProvider
from src.models.candle import Candle

_INTERVAL_SECONDS: Dict[str, float] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}

_DT_FMT = "%Y-%m-%d %H:%M:%S"


class ReplayMode(Enum):
    INSTANT = "instant"    # No delay between candles
    FAST = "fast"          # 1 ms delay between candles
    REALTIME = "realtime"  # Delay matches actual candle interval


class HistoricalDataProvider(MarketDataProvider):
    """Replays CSV candle data for backtesting.

    Candles are loaded into memory on construction. ``get_historical_candles``
    returns an initial window (mirroring the REST API); ``start_streaming``
    replays the remaining candles through ``on_candle_callback``.

    Args:
        candle_data: Nested mapping ``{symbol: {interval: [candles]}}``.
        replay_mode: Timing strategy for replay (default: INSTANT).
        on_candle_callback: Called once per replayed candle.
    """

    def __init__(
        self,
        candle_data: Dict[str, Dict[str, List[Candle]]],
        replay_mode: ReplayMode = ReplayMode.INSTANT,
        on_candle_callback: Optional[Callable[[Candle], None]] = None,
    ) -> None:
        self._data = candle_data
        self._replay_mode = replay_mode
        self._on_candle_callback = on_candle_callback

        # Tracks how many candles were handed out by get_historical_candles
        # per (symbol, interval) so replay starts after them.
        self._init_counts: Dict[str, Dict[str, int]] = {
            sym: {iv: 0 for iv in ivs} for sym, ivs in candle_data.items()
        }

        self._stop_event: Optional[asyncio.Event] = None
        self._is_running = False
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # MarketDataProvider ABC properties
    # ------------------------------------------------------------------

    @property
    def symbols(self) -> List[str]:
        return list(self._data.keys())

    @property
    def intervals(self) -> List[str]:
        seen: List[str] = []
        for ivs in self._data.values():
            for iv in ivs:
                if iv not in seen:
                    seen.append(iv)
        return seen

    @property
    def on_candle_callback(self) -> Optional[Callable[[Candle], None]]:
        return self._on_candle_callback

    # ------------------------------------------------------------------
    # MarketDataProvider ABC
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._is_running

    def get_historical_candles(
        self, symbol: str, interval: str, limit: int = 500
    ) -> List[Candle]:
        """Return up to *limit* candles for initialisation.

        Candles returned here are skipped during ``start_streaming`` to avoid
        duplicates.  Subsequent calls advance the skip cursor.

        Args:
            symbol: Trading pair (e.g. 'BTCUSDT').
            interval: Timeframe string (e.g. '1m').
            limit: Maximum candles to return.

        Returns:
            List of candles, oldest first.
        """
        candles = self._data.get(symbol, {}).get(interval, [])
        start = self._init_counts.get(symbol, {}).get(interval, 0)
        end = start + limit
        batch = candles[start:end]
        self._init_counts.setdefault(symbol, {})[interval] = start + len(batch)
        self.logger.debug(
            "get_historical_candles %s/%s: returned %d candles (cursor=%d)",
            symbol, interval, len(batch), self._init_counts[symbol][interval],
        )
        return batch

    async def start_streaming(self) -> None:
        """Replay all candles not yet consumed by ``get_historical_candles``.

        Iterates symbol→interval pairs in insertion order, calling
        ``on_candle_callback`` for each remaining candle.  Timing between
        candles is governed by ``replay_mode``.
        """
        if self._is_running:
            self.logger.warning("HistoricalDataProvider already streaming, ignoring")
            return

        self._stop_event = asyncio.Event()
        self._is_running = True
        self.logger.info(
            "Starting historical replay (mode=%s)", self._replay_mode.value
        )

        try:
            for symbol, intervals in self._data.items():
                for interval, candles in intervals.items():
                    skip = self._init_counts.get(symbol, {}).get(interval, 0)
                    replay_candles = candles[skip:]

                    self.logger.info(
                        "Replaying %d candles for %s/%s",
                        len(replay_candles), symbol, interval,
                    )

                    for candle in replay_candles:
                        if self._stop_event and self._stop_event.is_set():
                            self.logger.info("Replay stopped by stop() call")
                            return

                        if self._on_candle_callback:
                            self._on_candle_callback(candle)

                        delay = self._get_delay(interval)
                        if delay:
                            await asyncio.sleep(delay)

        finally:
            self._is_running = False
            self.logger.info("Historical replay complete")

    async def stop(self, timeout: float = 5.0) -> None:
        """Signal the replay loop to stop at the next candle boundary.

        Args:
            timeout: Unused for historical replay (included for ABC compatibility).
        """
        if self._stop_event is not None:
            self._stop_event.set()
        self._is_running = False
        self.logger.info("HistoricalDataProvider stop requested")

    # ------------------------------------------------------------------
    # CSV factory
    # ------------------------------------------------------------------

    @classmethod
    def from_csv(
        cls,
        file_paths: Dict[str, Dict[str, str]],
        replay_mode: ReplayMode = ReplayMode.INSTANT,
        on_candle_callback: Optional[Callable[[Candle], None]] = None,
    ) -> "HistoricalDataProvider":
        """Load candle data from CSV files and return a ready provider.

        Expected CSV columns (with header row):
            ``open_time,open,high,low,close,volume,close_time``

        Dates must be parseable as ``%Y-%m-%d %H:%M:%S`` or as a Unix
        timestamp in milliseconds (integer string).

        Args:
            file_paths: ``{symbol: {interval: "/path/to/file.csv"}}``.
            replay_mode: Timing strategy for replay.
            on_candle_callback: Called once per replayed candle.

        Returns:
            Configured :class:`HistoricalDataProvider`.
        """
        logger = logging.getLogger(__name__)
        candle_data: Dict[str, Dict[str, List[Candle]]] = {}

        for symbol, intervals in file_paths.items():
            candle_data[symbol] = {}
            for interval, path in intervals.items():
                candles = cls._load_csv(path, symbol, interval, logger)
                candle_data[symbol][interval] = candles
                logger.info(
                    "Loaded %d candles from %s (%s/%s)",
                    len(candles), path, symbol, interval,
                )

        return cls(candle_data, replay_mode, on_candle_callback)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        """Parse a datetime string or millisecond-epoch integer string."""
        value = value.strip()
        if value.isdigit():
            return datetime.utcfromtimestamp(int(value) / 1000)
        return datetime.strptime(value, _DT_FMT)

    @staticmethod
    def _load_csv(
        path: str,
        symbol: str,
        interval: str,
        logger: logging.Logger,
    ) -> List[Candle]:
        """Parse a single CSV file into a list of :class:`Candle` objects."""
        candles: List[Candle] = []
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row_num, row in enumerate(reader, start=2):
                try:
                    candles.append(
                        Candle(
                            symbol=symbol,
                            interval=interval,
                            open_time=HistoricalDataProvider._parse_dt(row["open_time"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                            close_time=HistoricalDataProvider._parse_dt(row["close_time"]),
                            is_closed=True,
                        )
                    )
                except (KeyError, ValueError) as exc:
                    logger.warning(
                        "Skipping malformed row %d in %s: %s", row_num, path, exc
                    )
        return candles

    def _get_delay(self, interval: str) -> float:
        """Return sleep duration in seconds based on replay mode."""
        if self._replay_mode == ReplayMode.INSTANT:
            return 0.0
        if self._replay_mode == ReplayMode.FAST:
            return 0.001
        # REALTIME
        return _INTERVAL_SECONDS.get(interval, 60)
