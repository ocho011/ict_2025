"""
Data requirements declaration for strategy modules.

Each determiner (Entry/Exit/SL/TP) can declare its data dependencies
(timeframes, minimum candle counts) via ModuleRequirements.

Cold-path only: created once at initialization, never accessed in hot path.

Real-time Trading Guideline Compliance:
- frozen=True dataclass for immutability
- MappingProxyType for truly immutable dict field
- Zero hot-path impact (init-time only)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import FrozenSet, Mapping


@dataclass(frozen=True)
class ModuleRequirements:
    """
    Immutable declaration of a module's data dependencies.

    Attributes:
        timeframes: Set of interval strings this module needs (e.g., {'5m', '1h', '4h'}).
        min_candles: Minimum candle count per timeframe for backfill.
                     Keys must be a subset of timeframes.
    """

    timeframes: FrozenSet[str] = field(default_factory=frozenset)
    min_candles: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Wrap min_candles in MappingProxyType and validate keys."""
        if isinstance(self.min_candles, dict):
            object.__setattr__(
                self, "min_candles", MappingProxyType(self.min_candles)
            )

        if self.min_candles and self.timeframes:
            invalid_keys = set(self.min_candles.keys()) - self.timeframes
            if invalid_keys:
                raise ValueError(
                    f"min_candles keys {invalid_keys} not in timeframes {self.timeframes}"
                )

    @staticmethod
    def empty() -> ModuleRequirements:
        """No data requirements (default for simple determiners)."""
        return ModuleRequirements()

    @staticmethod
    def merge(*requirements: ModuleRequirements) -> ModuleRequirements:
        """
        Merge multiple requirements: union timeframes, max min_candles per tf.

        Used by StrategyModuleConfig to aggregate all 4 determiners' needs.
        """
        all_timeframes: set[str] = set()
        all_min_candles: dict[str, int] = {}

        for req in requirements:
            all_timeframes |= req.timeframes
            for tf, count in req.min_candles.items():
                all_min_candles[tf] = max(all_min_candles.get(tf, 0), count)

        return ModuleRequirements(
            timeframes=frozenset(all_timeframes),
            min_candles=all_min_candles,
        )
