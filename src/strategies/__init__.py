"""
Trading strategy framework.

This package provides the abstract base class and composable strategy
implementation for the automated trading system.

Exports:
    BaseStrategy: Abstract base class defining strategy interface
    ComposableStrategy: Modular strategy assembled from pluggable determiners
    StrategyFactory: Factory for creating composable strategy instances
"""

from typing import List, Optional

from src.pricing.base import StrategyModuleConfig
from src.strategies.base import BaseStrategy
from src.strategies.composable import ComposableStrategy


class StrategyFactory:
    """
    Factory for creating composable trading strategy instances.

    Provides centralized strategy instantiation via create_composed(),
    which assembles a ComposableStrategy from a StrategyModuleConfig.

    Usage:
        >>> from src.strategies.module_config_builder import build_module_config
        >>> mc, intervals, rr = build_module_config("ict_strategy", config)
        >>> strategy = StrategyFactory.create_composed(
        ...     symbol='BTCUSDT', config=config,
        ...     module_config=mc, intervals=intervals, min_rr_ratio=rr
        ... )
    """

    @classmethod
    def create_composed(
        cls,
        symbol: str,
        config: dict,
        module_config: StrategyModuleConfig,
        intervals: Optional[List[str]] = None,
        min_rr_ratio: float = 1.5,
    ) -> ComposableStrategy:
        """
        Create a ComposableStrategy with injected module determiners.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            config: Strategy configuration dict
            module_config: StrategyModuleConfig with all 4 determiners
            intervals: Optional list of intervals to track
            min_rr_ratio: Minimum risk-reward ratio filter (default 1.5)

        Returns:
            ComposableStrategy instance
        """
        return ComposableStrategy(
            symbol=symbol,
            config=config,
            module_config=module_config,
            intervals=intervals,
            min_rr_ratio=min_rr_ratio,
        )

__all__ = [
    "BaseStrategy",
    "ComposableStrategy",
    "StrategyFactory",
]
