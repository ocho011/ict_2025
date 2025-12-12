"""
Trading strategy framework.

This package provides the abstract base class and concrete implementations
of trading strategies for the automated trading system.

Exports:
    BaseStrategy: Abstract base class defining strategy interface
"""

from src.strategies.base import BaseStrategy

__all__ = ['BaseStrategy']
