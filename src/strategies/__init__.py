"""
Trading strategy framework.

This package provides the abstract base class and concrete implementations
of trading strategies for the automated trading system.

Exports:
    BaseStrategy: Abstract base class defining strategy interface
    MockSMACrossoverStrategy: SMA crossover strategy for testing
    AlwaysSignalStrategy: Test strategy that always generates signals
    StrategyFactory: Factory for creating strategy instances
"""

from typing import Dict, Type, List

from src.strategies.base import BaseStrategy
from src.strategies.mock_strategy import MockSMACrossoverStrategy
from src.strategies.always_signal import AlwaysSignalStrategy


class StrategyFactory:
    """
    Factory for creating trading strategy instances.

    Implements the Factory Method pattern to provide centralized strategy
    instantiation with type safety and extensibility.

    The factory maintains a registry of available strategy classes and provides
    methods to create instances, list available strategies, and check registration.

    Usage:
        >>> # Create a strategy instance
        >>> strategy = StrategyFactory.create(
        ...     name='mock_sma',
        ...     symbol='BTCUSDT',
        ...     config={'fast_period': 10, 'slow_period': 20}
        ... )
        >>> isinstance(strategy, BaseStrategy)
        True

        >>> # List available strategies
        >>> StrategyFactory.list_strategies()
        ['mock_sma']

        >>> # Check if strategy is registered
        >>> StrategyFactory.is_registered('mock_sma')
        True
    """

    # A central lookup table mapping string aliases to strategy classes. 
    # Used by the factory to dynamically create instances from a given name.
    _strategies: Dict[str, Type[BaseStrategy]] = {
        'mock_sma': MockSMACrossoverStrategy,
        'always_signal': AlwaysSignalStrategy,  # Test strategy for pipeline verification
        # Future ICT strategies:
        # 'ict_fvg': ICTFVGStrategy,
        # 'ict_ob': ICTOrderBlockStrategy,
        # 'ict_bos': ICTBreakOfStructureStrategy,
    }

    @classmethod
    def create(cls, name: str, symbol: str, config: dict) -> BaseStrategy:
        """
        Create a strategy instance by name.

        Args:
            name: Strategy identifier (e.g., 'mock_sma', 'ict_fvg').
                  Must be a registered strategy name.
            symbol: Trading symbol (e.g., 'BTCUSDT', 'ETHUSDT').
            config: Strategy configuration dictionary containing strategy-specific
                   parameters (e.g., periods, thresholds, risk settings).

        Returns:
            Instantiated strategy object inheriting from BaseStrategy.

        Raises:
            ValueError: If the strategy name is not registered in the factory.
                       Error message includes list of available strategies.
            TypeError: If config is not a dictionary.

        Example:
            >>> config = {
            ...     'fast_period': 10,
            ...     'slow_period': 20,
            ...     'risk_reward_ratio': 2.0,
            ...     'stop_loss_percent': 0.01
            ... }
            >>> strategy = StrategyFactory.create('mock_sma', 'BTCUSDT', config)
            >>> strategy.symbol
            'BTCUSDT'
        """
        # Validate config type
        if not isinstance(config, dict):
            raise TypeError(
                f"config must be a dict, got {type(config).__name__}"
            )

        # Check if strategy is registered
        if name not in cls._strategies:
            available = ', '.join(sorted(cls._strategies.keys()))
            raise ValueError(
                f"Unknown strategy: '{name}'. "
                f"Available strategies: {available}"
            )

        # Get strategy class and instantiate
        strategy_class = cls._strategies[name]
        return strategy_class(symbol=symbol, config=config)

    @classmethod
    def list_strategies(cls) -> List[str]:
        """
        Return list of all registered strategy names.

        Returns:
            List of strategy identifiers that can be used with create().

        Example:
            >>> strategies = StrategyFactory.list_strategies()
            >>> 'mock_sma' in strategies
            True
        """
        return list(cls._strategies.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        Check if a strategy name is registered.

        Args:
            name: Strategy identifier to check.

        Returns:
            True if the strategy is registered, False otherwise.

        Example:
            >>> StrategyFactory.is_registered('mock_sma')
            True
            >>> StrategyFactory.is_registered('unknown')
            False
        """
        return name in cls._strategies

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseStrategy]) -> None:
        """
        Register a new strategy class dynamically.

        This method allows plugins or external modules to register their
        strategy implementations at runtime.

        Args:
            name: Strategy identifier to register.
            strategy_class: Strategy class that inherits from BaseStrategy.

        Raises:
            TypeError: If strategy_class doesn't inherit from BaseStrategy.
            ValueError: If name is already registered (prevents accidental override).

        Example:
            >>> class CustomStrategy(BaseStrategy):
            ...     # Implementation
            ...     pass
            >>> StrategyFactory.register('custom', CustomStrategy)
            >>> StrategyFactory.is_registered('custom')
            True
        """
        # Validate strategy class inheritance
        if not issubclass(strategy_class, BaseStrategy):
            raise TypeError(
                f"strategy_class must inherit from BaseStrategy, "
                f"got {strategy_class.__name__}"
            )

        # Prevent accidental override of existing strategies
        if name in cls._strategies:
            raise ValueError(
                f"Strategy '{name}' is already registered. "
                f"Use a different name or unregister the existing strategy first."
            )

        cls._strategies[name] = strategy_class


__all__ = ['BaseStrategy', 'MockSMACrossoverStrategy', 'AlwaysSignalStrategy', 'StrategyFactory']
