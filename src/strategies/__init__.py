"""
Trading strategy framework.

This package provides the abstract base class and concrete implementations
of trading strategies for the automated trading system.

Exports:
    BaseStrategy: Abstract base class defining strategy interface
    MockSMACrossoverStrategy: SMA crossover strategy for testing
"""

from src.strategies.base import BaseStrategy
from src.strategies.mock_strategy import MockSMACrossoverStrategy

__all__ = ['BaseStrategy', 'MockSMACrossoverStrategy']
